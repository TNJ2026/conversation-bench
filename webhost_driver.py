"""Web-host transport: drive the shipped browser runtime over its local HTTP API.

The desktop profile is reserved for the Electron application, so this transport
boots the `web` profile (the same UI/runtime stack without the native shell) in
an isolated DSH_HOME and speaks the documented `/api` client-request envelope.
"""
import http.cookiejar
import json
import os
import queue
import re
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BOOT_URL = re.compile(r'(http://127\.0\.0\.1:\d+)/\?token=([A-Za-z0-9_-]+)')
def sandbox_profile(home, workspace):
    """Allow the host by default but deny the answer key, other runs, and user state."""
    home = Path(home).resolve()
    repo = Path(__file__).resolve().parent
    run_root = home.parent.parent
    denied = [repo/'docs', repo/'cases', repo/'README.md', repo/'README.zh-CN.md', repo/'cases-v2.json',
              Path.home()/'.dsh', Path.home()/'Library'/'Application Support'/'@deepseek-ai',
              Path.home()/'Downloads'/'deepseek-harness-plugins', Path('/private/tmp')]
    if run_root.is_dir():
        denied += [entry for entry in run_root.iterdir()
                   if entry.name.startswith(('run.', 'scores', 'report')) or entry.name == 'raw']
    studies = repo/'studies'
    if studies.is_dir():
        denied += [child for child in studies.iterdir() if child.is_dir() and child.resolve() != run_root]
    lines = ['(version 1)', '(allow default)']
    for path in denied:
        escaped = str(path).replace('"', '\\"')
        lines.append('(deny file-read* (subpath "%s"))' % escaped)
        lines.append('(deny file-write* (subpath "%s"))' % escaped)
    return '\n'.join(lines) + '\n'


class DriverError(RuntimeError):
    pass


def text_of(message):
    content = (message or {}).get('content') or []
    return ''.join(block.get('text', '') for block in content if block.get('type') == 'text')


class WebHostDriver:
    """One stopped runtime per action so the isolated home can be checkpointed."""

    def __init__(self, config):
        self.config = config

    def perform(self, home, workspace, session_id, prompt, resume, transcript):
        home, workspace = Path(home).resolve(), Path(workspace).resolve()
        home.mkdir(parents=True, exist_ok=True)
        workspace.mkdir(parents=True, exist_ok=True)
        transcript.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.config['timeout']
        env = dict(os.environ, DSH_HOME=str(home))
        if self.config.get('sandbox', True):
            # The outer sandbox is the boundary; disable the nested one so bash keeps working.
            env['DSH_PERMISSION_MODE'] = 'danger-full-access'
        unwrapped = [self.config['dsh_bin'], '--profile', 'web', '--no-open', '--port', '0']
        if self.config.get('sandbox', True):
            profile = home.parent/'sandbox.sb'
            profile.write_text(sandbox_profile(home, workspace))
            command = ['/usr/bin/sandbox-exec', '-f', str(profile), *unwrapped]
        else:
            command = unwrapped
        with transcript.open('w', encoding='utf-8') as log:
            proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding='utf-8', env=env,
                                    cwd=workspace, start_new_session=os.name != 'nt')
            lines = queue.Queue()

            def pump():
                try:
                    for line in proc.stdout:
                        lines.put(line)
                finally:
                    lines.put(None)

            threading.Thread(target=pump, daemon=True).start()
            try:
                base, token = self._boot(lines, deadline, log, proc)
                client = _Client(base, token, deadline, log)
                client.connect()
                state_path = home/'web-session.json'
                stored = json.loads(state_path.read_text()) if state_path.exists() else {}
                sid = stored.get('sessionId')
                if sid is None:
                    created = client.rpc('session/create', {'request': {'cwd': str(workspace)}})
                    sid = created['sessionId']
                    state_path.write_text(json.dumps({'sessionId': sid}, indent=2) + '\n')
                    client.rpc('session/selectModel', {'request': {
                        'sessionId': sid, 'provider': self.config['provider'],
                        'model': self.config['model'],
                        **({'reasoningEffort': self.config['effort']} if self.config.get('effort') else {})}})
                before = client.rpc('session/state', {'request': {'sessionId': sid}})['cursor']
                if prompt.startswith('/'):
                    client.rpc('commands/execute', {'agentId': sid, 'line': prompt, 'submittedAttachments': []})
                else:
                    client.rpc('session/prompt', {'request': {
                        'requestId': uuid.uuid4().hex, 'sessionId': sid, 'mode': 'queue',
                        'content': [{'type': 'text', 'text': prompt}]}})
                    remaining = max(1, int((deadline - time.monotonic()) * 1000))
                    client.rpc('session/wait', {'request': {'sessionId': sid, 'timeoutMs': remaining}})
                events = self._events_since(client, sid, before)
                if not events:
                    raise DriverError('The runtime produced no durable events for this action.')
                answer, reason = '', None
                for event in events:
                    if event.get('type') == 'assistant/message':
                        answer = text_of(event.get('data', {}).get('message'))
                    if event.get('type') == 'turn/end':
                        reason = (event.get('data', {}).get('reason') or {}).get('kind')
                if prompt.startswith('/') and not answer:
                    answer = next((event.get('data', {}).get('text', '') for event in reversed(events)
                                   if event.get('type') == 'command/done'), '')
                if not reason and prompt.startswith('/'):
                    reason = 'completed' if any(e.get('type') == 'command/done' for e in events) else None
                self._stop(proc, lines)
                return {'answer': answer, 'finish_reason': reason, 'events': events,
                        'server': {'name': 'deepseek-harness-web-host', 'version': self.config.get('app_version', 'unknown')}}
            finally:
                if proc.poll() is None:
                    self._kill(proc)

    @staticmethod
    def _events_since(client, sid, before):
        """Page backwards until every event after `before` is in hand."""
        seen = {}
        request = {'address': {'kind': 'session', 'sessionId': sid}}
        for _ in range(200):
            page = client.rpc('session/events', {'request': request})
            records = [record['event'] for record in page.get('records', []) if record.get('event')]
            for event in records:
                seen[event['seq']] = event
            if not page.get('hasMore') or not records:
                break
            oldest = min(event['seq'] for event in records)
            if oldest <= before + 1 or request.get('beforeSeq') == oldest:
                break
            request = dict(request, beforeSeq=oldest)
        return [seen[seq] for seq in sorted(seen) if seq > before]

    def _boot(self, lines, deadline, log, proc):
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DriverError('The runtime did not publish its API URL before the deadline.')
            try:
                line = lines.get(timeout=remaining)
            except queue.Empty:
                raise DriverError('The runtime did not publish its API URL before the deadline.') from None
            if line is None:
                raise DriverError('The runtime exited before publishing its API URL.')
            log.write(line)
            log.flush()
            match = BOOT_URL.search(line)
            if match:
                self._token_url = line.strip()
                return match.group(1), match.group(2)

    def _stop(self, proc, lines):
        if os.name == 'nt':
            proc.terminate()
        else:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self._kill(proc)
            raise DriverError('The runtime did not stop cleanly; checkpointing is unsafe.') from None
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                lines.get(timeout=0.2)
            except queue.Empty:
                break
        if proc.returncode not in (0, -signal.SIGTERM):
            raise DriverError('The runtime exited with status %r; checkpointing is unsafe.' % (proc.returncode,))

    @staticmethod
    def _kill(proc):
        try:
            if os.name == 'nt':
                proc.kill()
            else:
                os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass


class _Client:
    def __init__(self, base, token, deadline, log):
        self.base, self.token, self.deadline, self.log = base, token, deadline, log
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.count = 0

    def connect(self):
        self._fetch(self.base + '/?token=' + self.token, None, 'auth')

    def rpc(self, endpoint, args):
        self.count += 1
        envelope = {'type': 'client-request', 'rpcId': f'r{self.count}', 'method': endpoint, 'payload': {'args': args}}
        raw = self._fetch(self.base + '/api/' + endpoint, envelope, endpoint)
        result = (raw or {}).get('result') or {}
        if not result.get('ok'):
            error = result.get('error') or {}
            raise DriverError('The runtime rejected %s: %s' % (endpoint, error.get('code') or 'unknown error'))
        return result.get('value')

    def _fetch(self, url, envelope, label):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise DriverError('Timed out before %s.' % label)
        data = json.dumps(envelope, ensure_ascii=False).encode() if envelope is not None else None
        request = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=remaining) as response:
                body = response.read().decode('utf-8', 'replace')
        except (urllib.error.URLError, TimeoutError) as error:
            raise DriverError('The runtime API failed during %s: %s' % (label, error)) from None
        self.log.write(json.dumps({'endpoint': label, 'request': envelope is not None,
                                   'response': body[:4000]}, ensure_ascii=False) + '\n')
        self.log.flush()
        if envelope is None:
            return {}
        try:
            return json.loads(body)
        except ValueError:
            raise DriverError('The runtime returned a non-JSON API response.') from None
