import os
import json
import asyncio
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import asyncssh

from models import SshHostInfo, TerminalAuthPayload
from ssh_config_parser import parse_ssh_config, find_host_by_alias, get_ssh_config_path
from metrics_collector import metrics_service
from db import init_db, get_all_host_stats, record_manual_connection

app = FastAPI(title="TermForYou SSH Backend", version="1.0.0")

@app.on_event("startup")
def on_startup():
    init_db()

# 允许前端开发服务跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/v1/ssh/hosts", response_model=list[SshHostInfo])
async def list_ssh_hosts():
    """读取本地 ~/.ssh/config 并返回按用户手动连接次数降序排列的服务器列表"""
    hosts = parse_ssh_config()
    stats = get_all_host_stats()
    for h in hosts:
        host_stat = stats.get(h.host_alias, {})
        h.connection_count = host_stat.get("connection_count", 0)
        h.last_connected_at = host_stat.get("last_connected_at", None)

    # 按用户手动连接次数降序排序 (若次数相同按最近连接时间降序)
    hosts.sort(
        key=lambda h: (h.connection_count, h.last_connected_at or 0),
        reverse=True
    )
    return hosts

@app.post("/api/v1/ssh/hosts/{host_alias}/connect")
async def record_host_connect(host_alias: str):
    """记录用户手动连接服务器事件，SQLite 中累加连接计数并更新时间戳"""
    stat = record_manual_connection(host_alias)
    return {
        "status": "ok",
        "stat": stat
    }

@app.get("/api/v1/ssh/config-path")
async def get_config_info():
    path = get_ssh_config_path()
    return {
        "path": path,
        "exists": os.path.exists(path)
    }

@app.get("/api/v1/ssh/metrics/{host_alias}")
async def get_host_metrics(host_alias: str):
    """
    获取指定主机的 CPU、内存、磁盘、流量等实时性能指标 (免 Agent 纳秒/微秒级极轻量采集)
    """
    return await metrics_service.fetch_metrics(host_alias)

@app.websocket("/ws/terminal/{host_alias}")
async def terminal_websocket(websocket: WebSocket, host_alias: str):
    """
    终端交互 WebSocket：
    通过 asyncssh 直连远端主机，分配 PTY，将用户按键与终端输出双向转发。
    """
    await websocket.accept()

    host_info = find_host_by_alias(host_alias)
    if not host_info:
        await websocket.send_text(json.dumps({
            "action": "stderr",
            "payload": f"\r\n\x1b[31m未在 ~/.ssh/config 中找到主机: {host_alias}\x1b[0m\r\n"
        }))
        await websocket.close()
        return

    # 等待前端发送第一帧认证载荷 (auth payload)
    auth_data = None
    cols, rows, term = 120, 34, "xterm-256color"

    try:
        init_raw = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
        init_json = json.loads(init_raw)
        if init_json.get("action") == "auth":
            auth_payload = init_json.get("payload", {})
            auth_data = TerminalAuthPayload(**auth_payload)
            cols = auth_data.cols
            rows = auth_data.rows
            term = auth_data.term
    except Exception:
        pass

    # 准备 asyncssh 连接参数
    conn_kwargs = {
        "host": host_info.hostname,
        "port": host_info.port,
        "username": host_info.user,
        "known_hosts": None, # 遵循本地 SSH 验证
    }

    if auth_data and auth_data.password:
        conn_kwargs["password"] = auth_data.password
        metrics_service.set_credential(host_alias, auth_data.password)

    # 如果配置了 IdentityFile 并且文件存在
    client_keys = []
    for key_path in host_info.identity_files:
        if os.path.exists(key_path):
            client_keys.append(key_path)
    if client_keys:
        conn_kwargs["client_keys"] = client_keys

    if auth_data and auth_data.passphrase:
        conn_kwargs["passphrase"] = auth_data.passphrase

    await websocket.send_text(json.dumps({
        "action": "stdout",
        "payload": f"\x1b[36m正在连接 {host_info.user}@{host_info.hostname}:{host_info.port}...\x1b[0m\r\n"
    }))

    try:
        async with asyncssh.connect(**conn_kwargs) as conn:
            # 成功建立 SSH 会话，记录一次手动连接并持久化到 SQLite
            try:
                record_manual_connection(host_alias)
            except Exception:
                pass

            await websocket.send_text(json.dumps({
                "action": "stdout",
                "payload": f"\x1b[32mSSH 会话连接成功 (PTY {cols}x{rows})\x1b[0m\r\n\r\n"
            }))

            # 创建 PTY 伪终端交互式会话
            async with conn.create_process(
                term_type=term,
                term_size=(cols, rows),
                encoding=None # 原始字节流
            ) as process:

                async def pump_remote_to_ws():
                    try:
                        while not process.stdout.at_eof():
                            chunk = await process.stdout.read(4096)
                            if not chunk:
                                break
                            # 以 latin1 或 utf-8 errors='replace' 发送文本
                            text = chunk.decode("utf-8", errors="replace")
                            await websocket.send_text(json.dumps({
                                "action": "stdout",
                                "payload": text
                            }))
                    except Exception:
                        pass

                async def pump_ws_to_remote():
                    try:
                        while True:
                            msg_raw = await websocket.receive_text()
                            msg = json.loads(msg_raw)
                            action = msg.get("action")

                            if action == "stdin":
                                data = msg.get("payload", "")
                                process.stdin.write(data.encode("utf-8"))
                            elif action == "resize":
                                new_cols = msg.get("payload", {}).get("cols", cols)
                                new_rows = msg.get("payload", {}).get("rows", rows)
                                process.terminal_size_changed((new_cols, new_rows))
                            elif action == "ping":
                                await websocket.send_text(json.dumps({"action": "pong"}))
                    except (WebSocketDisconnect, asyncio.CancelledError):
                        pass
                    except Exception:
                        pass

                remote_task = asyncio.create_task(pump_remote_to_ws())
                ws_task = asyncio.create_task(pump_ws_to_remote())

                done, pending = await asyncio.wait(
                    [remote_task, ws_task],
                    return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    task.cancel()

    except asyncssh.PermissionDenied as e:
        await websocket.send_text(json.dumps({
            "action": "auth_required",
            "payload": f"认证失败：需要密码或密钥口令 ({str(e)})"
        }))
    except Exception as e:
        await websocket.send_text(json.dumps({
            "action": "stderr",
            "payload": f"\r\n\x1b[31m[TermForYou 连接异常] {type(e).__name__}: {str(e)}\x1b[0m\r\n"
        }))
    finally:
        try:
            await websocket.close()
        except Exception:
            pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
