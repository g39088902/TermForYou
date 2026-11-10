import asyncio
import time
from typing import Dict, Any, List
from models import SshHostInfo

async def probe_single_host(
    host_alias: str,
    hostname: str,
    port: int = 22,
    timeout: float = 1.8
) -> Dict[str, Any]:
    """
    轻量非侵入式网络握手：
    精确探测远端服务器开机与否状态，计算往返延迟 RTT 并捕获 SSH Banner
    """
    t0 = time.time()
    writer = None
    try:
        connect_coro = asyncio.open_connection(hostname, port)
        reader, writer = await asyncio.wait_for(connect_coro, timeout=timeout)
        rtt_ms = max(1, int((time.time() - t0) * 1000))

        banner = ""
        try:
            banner_coro = reader.readline()
            line = await asyncio.wait_for(banner_coro, timeout=0.8)
            banner = line.decode("utf-8", errors="ignore").strip()
        except Exception:
            pass

        return {
            "host_alias": host_alias,
            "hostname": hostname,
            "port": port,
            "status": "online",
            "online": True,
            "rtt_ms": rtt_ms,
            "banner": banner or "TCP/SSH 端口可达",
            "message": f"已开机 (响应 {rtt_ms}ms)",
            "timestamp": int(time.time())
        }
    except asyncio.TimeoutError:
        return {
            "host_alias": host_alias,
            "hostname": hostname,
            "port": port,
            "status": "offline",
            "online": False,
            "rtt_ms": None,
            "banner": None,
            "message": "连接超时 · 目标主机未开机或网络不可达",
            "timestamp": int(time.time())
        }
    except Exception as e:
        return {
            "host_alias": host_alias,
            "hostname": hostname,
            "port": port,
            "status": "offline",
            "online": False,
            "rtt_ms": None,
            "banner": None,
            "message": f"连接拒绝或离线 ({type(e).__name__})",
            "timestamp": int(time.time())
        }
    finally:
        if writer:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

async def probe_all_hosts_concurrently(hosts: List[SshHostInfo]) -> Dict[str, Dict[str, Any]]:
    """并发批量探测全部服务器开机状态"""
    if not hosts:
        return {}
    tasks = [
        probe_single_host(h.host_alias, h.hostname, h.port)
        for h in hosts
    ]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    return {r["host_alias"]: r for r in results}
