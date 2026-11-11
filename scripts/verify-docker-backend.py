"""Run: backend/.venv/bin/python scripts/verify-docker-backend.py"""
import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from models import TerminalAuthPayload, DockerActionPayload
from metrics_collector import HostMetricsService, docker_exec_command
from pydantic import ValidationError


class DockerBackendChecks(unittest.IsolatedAsyncioTestCase):
    def test_action_payload(self):
        self.assertFalse(DockerActionPayload(action="start").sudo)
        self.assertTrue(DockerActionPayload(action="stop", sudo=True).sudo)
        for action in ["rm", "restart", "start;id", "--help", ""]:
            with self.assertRaises(ValidationError):
                DockerActionPayload(action=action)

    async def test_start_stop_commands_and_failures(self):
        service = HostMetricsService()
        connection = SimpleNamespace(run=AsyncMock(return_value=SimpleNamespace(exit_status=0)))
        service._get_connection = AsyncMock(return_value=(connection, None, None))
        for action, flags in [("start", ""), ("stop", "-t 10 ")]:
            for sudo in [False, True]:
                connection.run.reset_mock()
                result = await service.control_docker_container("test", "web-1", action, sudo=sudo)
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["action"], action)
                connection.run.assert_awaited_once_with(
                    ("sudo -n " if sudo else "") + f"docker {action} {flags}-- web-1", timeout=45
                )
            connection.run.reset_mock()
            connection.run.return_value = SimpleNamespace(exit_status=1, stderr="No such container", stdout="")
            result = await service.control_docker_container("test", "missing", action)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["exit_code"], 1)
            self.assertEqual(connection.run.await_count, 1, "Never fall back to sudo on failure")
            connection.run.return_value = SimpleNamespace(exit_status=0)

    async def test_invalid_action_never_connects(self):
        service = HostMetricsService()
        service._get_connection = AsyncMock()
        for action in ["rm", "start;id", "--help", ""]:
            result = await service.control_docker_container("test", "web", action)
            self.assertEqual(result["status"], "error")
        for action in ["start", "stop"]:
            for container in ["-f", "web;id", "a b", "", "$(id)"]:
                result = await service.control_docker_container("test", container, action)
                self.assertEqual(result["status"], "error")
        service._get_connection.assert_not_awaited()

    def test_exec_arguments(self):
        self.assertEqual(docker_exec_command("web-1"), "docker exec -it -- web-1 /bin/sh")
        self.assertEqual(docker_exec_command("abc123", True), "sudo -n docker exec -it -- abc123 /bin/sh")
        self.assertFalse(TerminalAuthPayload().sudo)
        for value in ["", "-privileged", "a;id", "a\nb", "$(id)", "a/b", "a b"]:
            with self.assertRaises(ValueError):
                docker_exec_command(value)
            with self.assertRaises(ValidationError):
                TerminalAuthPayload(docker_container=value)

    async def test_restart_success_and_explicit_sudo(self):
        service = HostMetricsService()
        connection = SimpleNamespace(run=AsyncMock(return_value=SimpleNamespace(exit_status=0)))
        service._get_connection = AsyncMock(return_value=(connection, None, None))
        result = await service.restart_docker_container("test", "web-1")
        self.assertEqual(result["status"], "ok")
        connection.run.assert_awaited_once_with("docker restart -t 10 -- web-1", timeout=45)
        connection.run.reset_mock()
        await service.restart_docker_container("test", "web-1", sudo=True)
        connection.run.assert_awaited_once_with("sudo -n docker restart -t 10 -- web-1", timeout=45)

    async def test_invalid_restart_never_connects(self):
        service = HostMetricsService()
        service._get_connection = AsyncMock()
        for value in ["-f", "web;id", "a b", "", "$(id)"]:
            result = await service.restart_docker_container("test", value)
            self.assertEqual(result["status"], "error")
        service._get_connection.assert_not_awaited()

    async def test_restart_failure_does_not_retry_with_sudo(self):
        service = HostMetricsService()
        connection = SimpleNamespace(run=AsyncMock(return_value=SimpleNamespace(
            exit_status=1, stderr="permission denied", stdout=""
        )))
        service._get_connection = AsyncMock(return_value=(connection, None, None))
        result = await service.restart_docker_container("test", "web")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], "permission denied")
        self.assertEqual(connection.run.await_count, 1)
        connection.run.side_effect = asyncio.TimeoutError()
        self.assertEqual((await service.restart_docker_container("test", "web"))["status"], "error")

    async def test_connection_failure(self):
        service = HostMetricsService()
        service._get_connection = AsyncMock(return_value=(None, "auth_failed", "authentication failed"))
        result = await service.restart_docker_container("test", "web")
        self.assertEqual(result["error_type"], "auth_failed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
