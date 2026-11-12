"""Run: backend/.venv/bin/python scripts/verify-process-backend.py (no SSH)."""
import asyncio
import base64
import contextlib
import io
import json
import shlex
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from models import ProcessSignalPayload
from process_manager import PROCESS_SIGNAL_CODE, PROCESS_LIST_CODE
from metrics_collector import HostMetricsService, REMOTE_FULL_INSPECT_SCRIPT
from pydantic import ValidationError

BOOT = '11111111-1111-1111-1111-111111111111'
IDENTITY = BOOT + ':999'


def stat(pid, parent=1, start='999', state='S'):
    fields = [state, str(parent)] + ['0'] * 18
    fields[19] = start
    return str(pid) + ' (name with ) spaces) ' + ' '.join(fields)


class SignalChecks(unittest.TestCase):
    def run_signal(self, pid=42, identity=IDENTITY, state='S', failure=None, pidfd=True):
        sent = []
        def read(path, *args, **kwargs):
            if path == '/proc/sys/kernel/random/boot_id': return io.StringIO(BOOT)
            if path == '/proc/100/stat': return io.StringIO(stat(100))
            if path == '/proc/42/stat': return io.StringIO(stat(42, state=state))
            raise FileNotFoundError(path)
        def send(*args):
            if failure: raise failure
            sent.append(args)
        output = io.StringIO()
        payload = {'pid': pid, 'identity': identity, 'signal': 'SIGTERM'}
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch('builtins.open', read))
            stack.enter_context(patch('os.getpid', return_value=100))
            stack.enter_context(patch('os.kill', side_effect=send))
            stack.enter_context(patch('os.pidfd_open', create=True, side_effect=(lambda _: 17) if pidfd else OSError(38, 'unavailable')))
            stack.enter_context(patch('signal.pidfd_send_signal', create=True, side_effect=send))
            stack.enter_context(patch('os.close'))
            stack.enter_context(patch.object(sys, 'argv', ['remote', encoded]))
            stack.enter_context(contextlib.redirect_stdout(output))
            try: exec(PROCESS_SIGNAL_CODE, {})
            except SystemExit: pass
        return json.loads(output.getvalue()), sent

    def test_pidfd_and_legacy_signal(self):
        for pidfd in (True, False):
            result, sent = self.run_signal(pidfd=pidfd)
            self.assertEqual(result['status'], 'ok')
            self.assertEqual(sent[0][0], 17 if pidfd else 42)

    def test_identity_change_never_signals(self):
        result, sent = self.run_signal(identity=BOOT + ':998')
        self.assertEqual(result['error_type'], 'stale_process')
        self.assertEqual(sent, [])

    def test_protected_missing_and_zombie(self):
        for kwargs, kind in [({'pid': 1}, 'invalid_request'), ({'pid': 100}, 'protected_process'), ({'pid': 43}, 'not_found'), ({'state': 'Z'}, 'zombie_process')]:
            result, sent = self.run_signal(**kwargs)
            self.assertEqual(result['error_type'], kind)
            self.assertEqual(sent, [])

    def test_permission_denied_and_exit_race(self):
        for failure, kind in [(PermissionError(), 'permission_denied'), (ProcessLookupError(), 'not_found')]:
            result, sent = self.run_signal(failure=failure)
            self.assertEqual(result['error_type'], kind)
            self.assertEqual(sent, [])

    def test_request_validation(self):
        valid = {'pid': 42, 'identity': IDENTITY, 'signal': 'SIGKILL'}
        self.assertFalse(ProcessSignalPayload(**valid).sudo)
        for field, value in [('pid', 0), ('pid', -42), ('pid', 1), ('pid', True), ('pid', '42;id'), ('pid', 2**32), ('identity', 'bad;id'), ('signal', 'SIGSTOP'), ('sudo', 'false')]:
            with self.assertRaises(ValidationError): ProcessSignalPayload(**dict(valid, **{field: value}))

    def test_inspection_program_compiles(self):
        code = shlex.split(REMOTE_FULL_INSPECT_SCRIPT)[2]
        compile(code, 'full-inspect', 'exec')
        self.assertIn(PROCESS_LIST_CODE, code)


class ServiceChecks(unittest.IsolatedAsyncioTestCase):
    async def test_payload_quoting_and_only_explicit_sudo(self):
        service = HostMetricsService()
        conn = SimpleNamespace(run=AsyncMock(return_value=SimpleNamespace(stdout='{"status":"ok"}', stderr='', exit_status=0)))
        service._get_connection = AsyncMock(return_value=(conn, None, None))
        for sudo in (False, True):
            await service.signal_process('test', ProcessSignalPayload(pid=42, identity=IDENTITY, signal='SIGTERM', sudo=sudo))
            args = shlex.split(conn.run.call_args.args[0])
            self.assertEqual(args[:3] if sudo else args[:1], ['sudo', '-n', '--'] if sudo else ['python3'])
            self.assertEqual(args[-2], PROCESS_SIGNAL_CODE)
            payload = json.loads(base64.b64decode(args[-1]))
            self.assertEqual(payload['identity'], IDENTITY)
            self.assertEqual(payload['sudo'], sudo)
        conn.run.side_effect = TimeoutError('timeout')
        self.assertEqual((await service.signal_process('test', ProcessSignalPayload(pid=42, identity=IDENTITY, signal='SIGTERM')))['status'], 'error')

    async def test_authentication_and_sudo_failure(self):
        service = HostMetricsService()
        service._get_connection = AsyncMock(return_value=(None, 'auth_failed', 'authentication failed'))
        payload = ProcessSignalPayload(pid=42, identity=IDENTITY, signal='SIGTERM')
        self.assertEqual((await service.signal_process('test', payload))['error_type'], 'auth_failed')
        conn = SimpleNamespace(run=AsyncMock(return_value=SimpleNamespace(stdout='', stderr='sudo: password required', exit_status=1)))
        service._get_connection = AsyncMock(return_value=(conn, None, None))
        result = await service.signal_process('test', payload)
        self.assertEqual(result['status'], 'error')
        self.assertIn('password required', result['message'])
        self.assertEqual(conn.run.await_count, 1)


if __name__ == '__main__': unittest.main(verbosity=2)
