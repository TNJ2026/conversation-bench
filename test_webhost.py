"""Keyless tests for the web-host transport against a fake local runtime."""
import json
import tempfile
import unittest
import io
import os
import queue
import signal
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

import webhost_driver
from webhost_driver import DriverError, WebHostDriver

FAKE = r'''#!/usr/bin/env python3
import json, signal, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
EVENTS = [
    {'type': 'turn/start', 'seq': 1, 'data': {}},
    {'type': 'user/message', 'seq': 2, 'data': {'content': [{'type': 'text', 'text': 'hello'}]}},
    {'type': 'assistant/message', 'seq': 3, 'data': {'message': {'content': [{'type': 'text', 'text': 'ok'}]}}},
    {'type': 'turn/end', 'seq': 4, 'data': {'reason': {'kind': 'completed'}}},
]
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if 'token' in self.path:
            self.send_response(303); self.send_header('Location', '/')
            self.send_header('Set-Cookie', 'dsh-auth-x=v1; Path=/'); self.end_headers()
        else:
            self.send_response(200); self.send_header('Content-Type', 'text/html')
            self.end_headers(); self.wfile.write(b'<html></html>')
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert body['type'] == 'client-request' and body['method'] == self.path.split('/api/')[1]
        method = body['method']
        if method == 'session/create': value = {'sessionId': 's-test'}
        elif method == 'session/selectModel': value = {'selected': {'provider': 'p', 'model': 'm'}}
        elif method == 'session/state': value = {'cursor': 1, 'active': False, 'running': False}
        elif method == 'session/prompt': value = {'accepted': True}
        elif method == 'commands/execute': value = {'commandId': 'c1', 'result': {'kind': 'success', 'text': 'Compacted'}}
        elif method == 'session/wait': value = {'reason': 'idle', 'state': {'cursor': 4}}
        elif method == 'session/events':
            value = {'cursor': 4, 'hasMore': False,
                     'records': [{'type': 'event', 'event': e} for e in EVENTS]}
        else: raise SystemExit('unexpected ' + method)
        out = json.dumps({'type': 'server-response', 'rpcId': body['rpcId'],
                          'result': {'ok': True, 'value': value}}).encode()
        self.send_response(200); self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(out))); self.end_headers(); self.wfile.write(out)
server = HTTPServer(('127.0.0.1', 0), H)
print('dsh web: http://127.0.0.1:%d/?token=tok' % server.server_port, flush=True)
signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
server.serve_forever()
'''

class WebHostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fake = self.root/'fake-dsh'; self.fake.write_text(FAKE); self.fake.chmod(0o755)
        self.config = {'dsh_bin': str(self.fake), 'provider': 'fixture', 'model': 'fixture',
                       'effort': 'low', 'timeout': 20, 'app_version': 'test-only', 'sandbox': False}

    def test_one_action_creates_session_and_returns_filtered_events(self):
        result = WebHostDriver(self.config).perform(self.root/'home', self.root/'ws', 'id', 'hello', False,
                                                    self.root/'wire.jsonl')
        self.assertEqual(result['answer'], 'ok')
        self.assertEqual(result['finish_reason'], 'completed')
        self.assertEqual([e['type'] for e in result['events']], ['user/message', 'assistant/message', 'turn/end'])
        self.assertEqual(json.loads((self.root/'home'/'web-session.json').read_text())['sessionId'], 's-test')
        self.assertEqual(result['server']['name'], 'deepseek-harness-web-host')

    def test_command_uses_the_command_endpoint(self):
        WebHostDriver(self.config).perform(self.root/'home',self.root/'ws','id','hello',False,self.root/'first.jsonl')
        result = WebHostDriver(self.config).perform(self.root/'home', self.root/'ws', 'id', '/compact', True,
                                                    self.root/'wire.jsonl')
        self.assertTrue(any(e['type'] == 'turn/end' for e in result['events']))

    def test_missing_restore_identity_does_not_create_fresh_history(self):
        with self.assertRaisesRegex(DriverError,'refusing to create fresh history'):
            WebHostDriver(self.config).perform(self.root/'home',self.root/'ws','id','hello',True,self.root/'wire.jsonl')
        self.assertFalse((self.root/'home').exists())

    def test_unreachable_runtime_fails_loudly(self):
        self.fake.write_text('#!/bin/sh\nexit 1\n'); self.fake.chmod(0o755)
        with self.assertRaisesRegex(DriverError, 'exited'):
            WebHostDriver(self.config).perform(self.root/'home', self.root/'ws', 'id', 'x', False,
                                               self.root/'wire.jsonl')

    def test_shutdown_timeout_never_returns_a_checkpointable_result(self):
        self.fake.write_text(FAKE.replace('signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))',
                                         'signal.signal(signal.SIGTERM, signal.SIG_IGN)'))
        config=dict(self.config,shutdown_timeout=.15)
        with self.assertRaisesRegex(DriverError,'checkpointing is unsafe'):
            WebHostDriver(config).perform(self.root/'home',self.root/'ws','id','hello',False,self.root/'wire.jsonl')

    def test_sandbox_profile_denies_answer_key_and_other_runs(self):
        repo = Path(webhost_driver.__file__).resolve().parent
        run = self.root/'run'; home = run/'homes'/'A';home.mkdir(parents=True)
        profile = webhost_driver.sandbox_profile(home, self.root/'ws')
        self.assertNotIn('(deny default)', profile)
        self.assertIn('(subpath '+json.dumps(str(repo))+')', profile)
        self.assertIn('/private/tmp', profile)
        self.assertIn('(subpath '+json.dumps(str(run.resolve()))+')', profile)
        self.assertIn('(require-not (subpath '+json.dumps(str(home.resolve()))+'))', profile)
        self.assertIn('(deny file-read*', profile)

    @unittest.skipUnless(sys.platform=='darwin' and Path('/usr/bin/sandbox-exec').exists(),'Seatbelt integration requires macOS')
    def test_native_sandbox_blocks_arbitrary_records_and_sibling_branch_answers(self):
        with tempfile.TemporaryDirectory(dir=Path.home()/'Library'/'Caches',prefix='bench-isolation-test-') as temp:
            root=Path(temp);run=root/'run';home=run/'homes'/'B';home.mkdir(parents=True)
            other=run/'homes'/'A'/'sessions';other.mkdir(parents=True)
            own=home/'own.txt';own.write_text('own state')
            answer=other/'answer.txt';answer.write_text('synthetic other-branch answer')
            plan=run/'anything.json';plan.write_text('synthetic answer key')
            workspace=root/'workspace';workspace.mkdir()
            profile=root/'test.sb';profile.write_text(webhost_driver.sandbox_profile(home,workspace))
            late=run/'created-after-policy.json';late.write_text('synthetic late record')
            alias=home/'alias';alias.symlink_to(answer)
            def read(path):
                return subprocess.run(['/usr/bin/sandbox-exec','-f',str(profile),'/bin/cat',str(path)],capture_output=True).returncode
            self.assertEqual(read(own),0)
            for path in (answer,plan,late,alias):
                with self.subTest(path=path):self.assertNotEqual(read(path),0)
            metadata=subprocess.run(['/usr/bin/sandbox-exec','-f',str(profile),'/usr/bin/stat','-f','%N',str(run)],capture_output=True)
            listing=subprocess.run(['/usr/bin/sandbox-exec','-f',str(profile),'/bin/ls',str(run)],capture_output=True)
            self.assertEqual(metadata.returncode,0)
            self.assertNotEqual(listing.returncode,0)

    @unittest.skipUnless(os.name=='posix','Process-group lifecycle requires POSIX')
    def test_stop_waits_for_descendant_flush_even_without_inherited_stdout(self):
        script=r'''
import os,signal,sys,time
from pathlib import Path
if os.fork()==0:
 def stop(*args):
  time.sleep(.8)
  Path(sys.argv[1]).write_text('flushed')
  sys.exit(0)
 signal.signal(signal.SIGTERM,stop)
 print('child ready',flush=True)
 if sys.argv[2]=='redirect':os.dup2(os.open(os.devnull,os.O_WRONLY),1)
 while True:time.sleep(.05)
else:
 signal.signal(signal.SIGTERM,lambda *args:sys.exit(0))
 print('parent ready',flush=True)
 while True:time.sleep(.05)
'''
        for mode in ('inherited','redirect'):
            with self.subTest(mode=mode):
                flushed=self.root/('flush-'+mode)
                proc=subprocess.Popen([sys.executable,'-c',script,str(flushed),mode],stdout=subprocess.PIPE,text=True,start_new_session=True)
                lines=queue.Queue()
                def pump():
                    for line in proc.stdout:lines.put(line)
                    lines.put(None)
                reader=Thread(target=pump,daemon=True);reader.start()
                try:
                    lines.get(timeout=5);lines.get(timeout=5)
                    driver=WebHostDriver({'shutdown_timeout':5})
                    driver._stop(proc,lines,reader,io.StringIO())
                    self.assertTrue(flushed.exists())
                    self.assertFalse(reader.is_alive())
                    self.assertFalse(driver._group_alive(proc))
                finally:
                    WebHostDriver._kill(proc);reader.join(2);proc.stdout.close()

    @unittest.skipUnless(os.name=='posix','Process-group lifecycle requires POSIX')
    def test_unhandled_termination_is_not_a_clean_checkpoint(self):
        proc=subprocess.Popen([sys.executable,'-c','import time;print("ready",flush=True);time.sleep(10)'],stdout=subprocess.PIPE,text=True,start_new_session=True)
        lines=queue.Queue()
        def pump():
            for line in proc.stdout:lines.put(line)
            lines.put(None)
        reader=Thread(target=pump,daemon=True);reader.start()
        try:
            lines.get(timeout=5)
            with self.assertRaisesRegex(DriverError,'checkpointing is unsafe'):
                WebHostDriver({})._stop(proc,lines,reader,io.StringIO())
        finally:
            WebHostDriver._kill(proc);reader.join(2);proc.stdout.close()

if __name__ == '__main__':
    unittest.main()
