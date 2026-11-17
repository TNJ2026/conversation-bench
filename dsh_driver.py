"""DSH SDK-profile JSON-RPC transport. No third-party Python dependencies."""
import json
import os
from pathlib import Path
import re
import queue
import signal
import subprocess
import threading
import time


DSH_BIN = '/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh'


def runtime_environment(config,smoke=False):
    """Bridge only the official API key; never persist credentials in records.

    Accept the simple scalar format written by DSH, not arbitrary YAML.
    Complex/ambiguous documents fail closed rather than guessing a secret.
    """
    if smoke or config.get('provider')!='deepseek-official' or os.environ.get('DEEPSEEK_API_KEY'):
        return {}
    home=Path(os.environ.get('DSH_HOME') or Path.home()/'.dsh')
    source=home/'.credentials.yaml'
    if not source.exists():return {}
    if source.stat().st_mode & 0o077:raise ValueError('DSH credentials must be owner-only (chmod 600).')
    lines=source.read_text().splitlines();inside=False;values=[];sections=0
    for line in lines:
        if line and not line[0].isspace() and not line.startswith('#'):
            inside=line.strip()=='refs:'
            if inside:sections+=1
        elif inside:
            match=re.fullmatch(r'  DEEPSEEK_API_KEY: *(.*)',line)
            if match:values.append(match[1])
    if not values:return {}
    if sections!=1 or len(values)!=1:raise ValueError('Ambiguous DSH API key entry.')
    raw=values[0]
    try:
        value=json.loads(raw) if raw.startswith('"') else raw[1:-1].replace("''", "'") if raw.startswith("'") and raw.endswith("'") else raw
        if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+',value):raise ValueError()
    except ValueError:
        raise ValueError('Unsupported DSH API key scalar; use the launch environment instead.') from None
    return {'DEEPSEEK_API_KEY':value}


class DriverError(RuntimeError):
    pass


def text_content(event):
    data = event.get('data', {})
    content = data.get('message', data).get('content', [])
    return ''.join(b.get('text', '') for b in content if b.get('type') == 'text')


class DshDriver:
    """One stopped-and-flushed runtime per action, so its home can be checkpointed."""
    def __init__(self, config):
        self.config = config

    def perform(self, home, workspace, session_id, prompt, resume, transcript):
        config = self.config
        home.mkdir(parents=True, exist_ok=True)
        transcript.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, DSH_HOME=str(home))
        command = [config['dsh_bin'], '--profile', 'sdk']
        if config.get('profile_patch'):
            command.extend(['--patch', str(config['profile_patch'])])
        deadline = time.monotonic() + config['timeout']
        with transcript.open('w', encoding='utf-8') as raw, transcript.with_suffix('.stderr.log').open('w') as err:
            proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err,
                                    text=True, encoding='utf-8', env=env, cwd=workspace,
                                    start_new_session=os.name != 'nt')
            frames = queue.Queue()
            def read():
                try:
                    for line in proc.stdout:
                        raw.write(line); raw.flush()
                        try:
                            frames.put(json.loads(line))
                        except ValueError:
                            frames.put(DriverError('DSH stdout is not JSON-RPC; see the private wire log.'))
                finally:
                    frames.put(DriverError('DSH closed its protocol stream.'))
            reader = threading.Thread(target=read, daemon=True); reader.start()
            notices = []
            request_id = 0
            def send(frame):
                proc.stdin.write(json.dumps(dict(jsonrpc='2.0', **frame), ensure_ascii=False) + '\n')
                proc.stdin.flush()
            def receive():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise DriverError('DSH action timed out; its outcome must not be retried automatically.')
                try:
                    frame = frames.get(timeout=remaining)
                except queue.Empty:
                    raise DriverError('DSH action timed out; inspect the wire log before starting a new trial.') from None
                if isinstance(frame, Exception):
                    raise frame
                if not isinstance(frame, dict):
                    raise DriverError('Invalid JSON-RPC frame.')
                if 'method' in frame:
                    if 'id' in frame:
                        # Do not fabricate human answers or authorize requested operations.
                        send({'id':frame['id'], 'error':{'code':-32601, 'message':'Unattended benchmark cannot answer user requests.'}})
                        raise DriverError('DSH requested human input; the run needs attention.')
                    notices.append(frame)
                return frame
            def rpc(method, params=None):
                nonlocal request_id
                request_id += 1
                current = request_id
                send({'id':current, 'method':method, **({'params':params} if params is not None else {})})
                while True:
                    frame = receive()
                    if frame.get('id') == current and 'method' not in frame:
                        if 'error' in frame:
                            raise DriverError(f'DSH rejected {method}; see the private wire log.')
                        return frame.get('result')
            try:
                init = {'cwd':str(workspace), 'provider':config['provider'], 'model':config['model']}
                if config.get('effort'):
                    init['reasoningEffort'] = config['effort']
                initialized = rpc('initialize', init)
                server = initialized.get('serverInfo', {}) if isinstance(initialized, dict) else {}
                if server.get('name') != 'deepseek-harness-sdk-runtime':
                    raise DriverError('The selected DSH does not expose the supported SDK runtime.')
                if resume:
                    rpc('session/resume', {'sessionId':session_id})
                notices.clear()
                receipt = rpc('session/query', {'sessionId':session_id, 'contentBlocks':[{'type':'text','text':prompt}]})
                if not isinstance(receipt, dict) or receipt.get('kind') not in ('prompt', 'command'):
                    raise DriverError('Unsupported session/query response.')
                if receipt['kind'] == 'prompt' and not isinstance(receipt.get('messageId'), str):
                    raise DriverError('Prompt receipt has no message identity.')
                cursor, admitted, ended = 0, False, False
                events = []
                answer, reason = '', None
                command_id = receipt.get('execution', {}).get('commandId')
                if receipt['kind'] == 'command' and not command_id:
                    raise DriverError('Native command has no lifecycle identity.')
                while True:
                    if cursor == len(notices):
                        receive()
                        continue
                    frame = notices[cursor]; cursor += 1
                    params = frame.get('params', {})
                    if params.get('sessionId') != session_id:
                        continue
                    event = params.get('event', {}) if frame['method'] == 'session.event' else {}
                    data = event.get('data', {})
                    if receipt['kind'] == 'prompt':
                        if event.get('type') == 'agent/inbox/spliced' and any(
                                m.get('id') == receipt.get('messageId') for m in data.get('inserted', [])):
                            admitted = True
                        if not admitted:
                            continue
                    if event:
                        events.append(event)
                        if event.get('type') == 'assistant/message':
                            answer = text_content(event)
                        if event.get('type') == 'turn/end':
                            reason = data.get('reason', {}).get('kind')
                        if event.get('type') == 'command/done' and data.get('commandId') == command_id:
                            ended = True
                    if receipt['kind'] == 'prompt' and frame['method'] == 'session.status' and params.get('status') == 'idle':
                        if not reason:
                            raise DriverError('The prompt became idle without a terminal turn event.')
                        break
                    if receipt['kind'] == 'command' and frame['method'] == 'session.query.completed' and params.get('commandId') == command_id:
                        if not ended or not any(e.get('type') == 'command/run' and e.get('data', {}).get('commandId') == command_id for e in events):
                            raise DriverError('Native command completion has no matching lifecycle events.')
                        answer, reason = params.get('finalResponse'), params.get('finishReason')
                        if not isinstance(answer, str) or not isinstance(reason, str):
                            raise DriverError('Invalid command completion payload.')
                        break
                rpc('shutdown')
                try:
                    proc.wait(timeout=min(15, max(0.1, deadline-time.monotonic())))
                except subprocess.TimeoutExpired:
                    raise DriverError('DSH did not stop after shutdown; checkpointing is unsafe.') from None
                reader.join(timeout=2)
                if proc.returncode != 0 or reader.is_alive():
                    raise DriverError('DSH did not exit cleanly; checkpointing is unsafe.')
                return {'answer':answer, 'finish_reason':reason, 'events':events, 'server':server}
            finally:
                if proc.poll() is None or reader.is_alive():
                    if os.name == 'nt':
                        if proc.poll() is None:
                            proc.terminate()
                    else:
                        try:
                            os.killpg(proc.pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass  # The owned process group already exited.
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        if os.name == 'nt':
                            proc.kill()
                        else:
                            try:
                                os.killpg(proc.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass  # The owned process group exited during the grace period.
                        proc.wait(timeout=5)
                reader.join(timeout=2)
                proc.stdin.close(); proc.stdout.close()
