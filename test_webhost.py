"""Keyless tests for the web-host transport against a fake local runtime."""
import json
import tempfile
import unittest
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
        result = WebHostDriver(self.config).perform(self.root/'home', self.root/'ws', 'id', '/compact', True,
                                                    self.root/'wire.jsonl')
        self.assertTrue(any(e['type'] == 'turn/end' for e in result['events']))

    def test_unreachable_runtime_fails_loudly(self):
        self.fake.write_text('#!/bin/sh\nexit 1\n'); self.fake.chmod(0o755)
        with self.assertRaisesRegex(DriverError, 'exited'):
            WebHostDriver(self.config).perform(self.root/'home', self.root/'ws', 'id', 'x', False,
                                               self.root/'wire.jsonl')

    def test_sandbox_profile_denies_answer_key_and_other_runs(self):
        repo = Path(webhost_driver.__file__).resolve().parent
        (self.root/'run.json').write_text('{}'); (self.root/'raw').mkdir(exist_ok=True)
        (self.root/'homes').mkdir(exist_ok=True)
        profile = webhost_driver.sandbox_profile(self.root/'homes'/'A', self.root/'ws')
        self.assertNotIn('(deny default)', profile)
        self.assertIn(str(repo/'docs').replace('"', '\\"'), profile)
        self.assertIn('/private/tmp', profile)
        self.assertIn('run.json', profile)
        self.assertIn('raw', profile)
        self.assertIn('(deny file-read*', profile)

if __name__ == '__main__':
    unittest.main()
