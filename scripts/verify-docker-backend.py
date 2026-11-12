"""Run: backend/.venv/bin/python scripts/verify-docker-backend.py"""
import asyncio
import json
import shlex
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from models import TerminalAuthPayload, DockerActionPayload, DockerContainerInfo
from metrics_collector import HostMetricsService, docker_exec_command, REMOTE_FULL_INSPECT_SCRIPT
from pydantic import ValidationError


class DockerInspectionChecks(unittest.TestCase):
    """Exercise the actual remote Python parser with representative Docker output."""
    cid = "a" * 64

    def inspect(self, details, ports="127.0.0.1:8080->80/tcp, 443/tcp"):
        commands = []
        def run_cmd(command, timeout=3):
            commands.append(command)
            if command[1] == "ps":
                return f"{self.cid}|web|nginx:alpine|Up 2 hours|running|{ports}|2026-11-11 00:00:00 +0000 UTC|0B"
            return details
        code = shlex.split(REMOTE_FULL_INSPECT_SCRIPT)[2]
        # Validate shell quoting and the complete remote program, then execute Docker collection only.
        compile(code, "remote", "exec")
        docker_code = code[code.index("# 2. Docker"):code.index("# 3. Systemd")]
        namespace = {"shutil": SimpleNamespace(which=lambda _: True), "json": json, "run_cmd": run_cmd, "data": {}}
        exec(docker_code, namespace)
        items = namespace["data"]["dockerContainers"]
        self.assertEqual(len(items), 1)
        self.assertEqual(len(commands), 2, "One ps and one batched inspect; no per-container calls")
        self.assertNotIn('"Env"', commands[1][3])
        self.assertNotIn('"Cmd"', commands[1][3])
        self.assertNotIn('{{json (index . "Config" "Labels")}}', commands[1][3])
        return DockerContainerInfo(**items[0]).model_dump()

    def detail(self, mode="bridge", nano=500000000, quota=0, health="healthy"):
        return json.dumps([
            self.cid, "2026-11-11T00:00:00Z", "2026-11-11T01:00:00Z", "0001-01-01T00:00:00Z",
            0, False, 2, mode, {"Name": "on-failure", "MaximumRetryCount": 3},
            67108864, nano, quota, 100000, "0-1", False, True, "1000:1000",
            [{"Source": "/data/a:b;c", "Destination": "/data", "Type": "bind", "RW": False},
             {"Source": "", "Destination": "/tmp", "Type": "tmpfs", "RW": True}],
            {"app-net": {"IPAddress": "172.20.0.2", "GlobalIPv6Address": "fd00::2"}},
            {"80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8080"}, {"HostIp": "::1", "HostPort": "8080"}], "443/tcp": None},
            {"80/tcp": {}, "443/tcp": {}, "53/udp": {}, "5000/sctp": {}},
            "app", "web", {}, {}, health
        ])

    def test_operational_details_and_port_semantics(self):
        c = self.inspect(self.detail())
        self.assertTrue(c["detailsAvailable"])
        self.assertEqual((c["networkMode"], c["restartPolicy"], c["restartMaxRetries"]), ("bridge", "on-failure", 3))
        self.assertEqual((c["cpuLimit"], c["memoryLimitBytes"]), (0.5, 67108864))
        self.assertEqual(c["networks"][0]["ipv6Address"], "fd00::2")
        self.assertEqual(c["volumes"][0]["hostPath"], "/data/a:b;c")
        self.assertTrue(c["volumes"][0]["readOnly"])
        self.assertEqual(c["volumes"][1]["type"], "tmpfs")
        self.assertEqual((c["runUser"], c["readOnlyRootfs"], c["healthStatus"]), ("1000:1000", True, "healthy"))
        self.assertEqual((c["composeProject"], c["composeService"]), ("app", "web"))
        self.assertEqual(len(c["ports"]), 5)
        self.assertEqual({p["hostIp"] for p in c["ports"] if p["hostPort"]}, {"127.0.0.1", "::1"})
        self.assertTrue(all(p["hostPort"] == 0 for p in c["ports"] if p["containerPort"] != 80))
        self.assertTrue(all("firewallAllowed" not in p for p in c["ports"]))
        self.assertNotIn("cpuPercent", c)
        self.assertNotIn("memMb", c)

    def test_host_none_quota_and_no_healthcheck(self):
        for mode in ["host", "none", "container:abc"]:
            c = self.inspect(self.detail(mode=mode, nano=0, quota=25000, health=None))
            self.assertEqual(c["networkMode"], mode)
            self.assertEqual(c["cpuLimit"], 0.25)
            self.assertIsNone(c["healthStatus"])
        self.assertEqual(self.inspect(self.detail(nano=0))["cpuLimit"], 0)

    def test_missing_details_preserve_list_and_unknowns(self):
        for detail in ["", "not-json", "[]"]:
            c = self.inspect(detail)
            self.assertFalse(c["detailsAvailable"])
            self.assertIsNone(c["networkMode"])
            self.assertIsNone(c["memoryLimitBytes"], "Unknown is different from unlimited")
            self.assertIsNone(c["privileged"], "Unknown is different from disabled")
            self.assertEqual([(p["hostPort"], p["containerPort"]) for p in c["ports"]], [(8080, 80), (0, 443)])

    def test_stopped_container_preserves_configured_ports(self):
        detail = json.loads(self.detail())
        detail[19] = None  # NetworkSettings.Ports is absent before Docker creates the network.
        detail[23] = {"80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8080"}]}
        c = self.inspect(json.dumps(detail))
        published = [p for p in c["ports"] if p["hostPort"]]
        self.assertEqual([(p["hostIp"], p["hostPort"]) for p in published], [("127.0.0.1", 8080)])

    def test_tmpfs_not_listed_in_mounts(self):
        detail = json.loads(self.detail())
        detail[24] = {"/cache": "ro,size=1048576"}
        c = self.inspect(json.dumps(detail))
        self.assertIn({"hostPath": "", "containerPath": "/cache", "type": "tmpfs", "readOnly": True}, c["volumes"])


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
