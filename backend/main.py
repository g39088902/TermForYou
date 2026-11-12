import os
import json
import asyncio
import logging
import urllib.parse
from typing import Optional, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Response, Query
from fastapi.middleware.cors import CORSMiddleware
import asyncssh

from models import (
    SshHostInfo,
    TerminalAuthPayload,
    DockerRestartPayload,
    DockerActionPayload,
    CronTaskCreatePayload,
    CronTaskEnabledPayload,
    ProcessSignalPayload,
    CreateHostPayload,
    SetCredentialPayload,
    WriteFilePayload,
    MkdirPayload,
    TouchFilePayload,
    RenameFilePayload,
    CopyFilePayload,
    DeleteFilesPayload,
    ChmodFilePayload,
    ArchiveFilesPayload,
    SingleDirSizePayload,
    DownloadBatchPayload,
)
from ssh_config_parser import (
    parse_ssh_config,
    find_host_by_alias,
    get_ssh_config_path,
    delete_host_from_ssh_config,
    add_host_to_ssh_config,
)
from metrics_collector import metrics_service, docker_exec_command
from db import init_db, get_all_host_stats, record_manual_connection, delete_host_stat
from probe_service import probe_single_host, probe_all_hosts_concurrently

app = FastAPI(title="TermForYou SSH Backend", version="1.0.0")
logger = logging.getLogger(__name__)

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

@app.post("/api/v1/ssh/hosts")
async def create_ssh_host(payload: CreateHostPayload):
    """持久化新增或修改主机配置至 ~/.ssh/config"""
    add_host_to_ssh_config(
        host_alias=payload.host_alias,
        hostname=payload.hostname,
        port=payload.port,
        user=payload.user
    )
    return {
        "status": "ok",
        "message": f"主机「{payload.host_alias}」已成功持久化写入 ~/.ssh/config",
        "host_alias": payload.host_alias
    }

@app.delete("/api/v1/ssh/hosts/{host_alias}")
async def delete_ssh_host(host_alias: str):
    """
    持久删除指定服务器配置：
    1. 从 ~/.ssh/config 中彻底移除 Host 块 (自动备份 ~/.ssh/config.bak)
    2. 从 SQLite host_stats 中清理连接历史与频次
    3. 清理内存连接缓存
    """
    deleted_from_config = delete_host_from_ssh_config(host_alias)
    deleted_from_db = delete_host_stat(host_alias)

    # 清理 metrics 缓存和已建连接
    if host_alias in metrics_service._connections:
        conn = metrics_service._connections.pop(host_alias, None)
        if conn and not conn.is_closed():
            conn.close()
    metrics_service._last_raw.pop(host_alias, None)
    metrics_service._last_result.pop(host_alias, None)
    metrics_service._credentials.pop(host_alias, None)

    return {
        "status": "ok",
        "host_alias": host_alias,
        "deleted_from_config": deleted_from_config,
        "deleted_from_db": deleted_from_db,
        "message": f"主机「{host_alias}」配置与统计数据已彻底持久删除"
    }

@app.post("/api/v1/ssh/probe/{host_alias}")
async def probe_host_endpoint(host_alias: str):
    """探测单台主机的开机状态、端口响应延时及全页面数据，并精确检测是否因密码不对而未接通"""
    host_info = find_host_by_alias(host_alias)
    if not host_info:
        raise HTTPException(status_code=404, detail=f"未找到主机: {host_alias}")
    probe_res = await probe_single_host(host_info.host_alias, host_info.hostname, host_info.port)
    
    # 若目标开机，进一步探测全页面数据并检测密码/认证状态
    inspection_data = None
    auth_failed = False
    auth_message = None
    if probe_res.get("online"):
        try:
            inspection_data = await metrics_service.fetch_full_inspection(host_alias)
            if inspection_data and (inspection_data.get("auth_failed") or inspection_data.get("status") == "auth_failed"):
                auth_failed = True
                auth_message = inspection_data.get("message", "密码不对或身份认证被拒绝 (Permission denied)")
        except Exception as e:
            pass

    return {
        **probe_res,
        "auth_failed": auth_failed,
        "auth_message": auth_message,
        "auth_method": inspection_data.get("auth_method") if inspection_data else metrics_service._auth_methods.get(host_alias),
        "inspection": inspection_data
    }

@app.post("/api/v1/ssh/probe-all")
async def probe_all_hosts_endpoint():
    """并发批量探测全部服务器的开机与否状态与响应延迟，并对开机服务器并发采集系统全页面核心指标，标识密码错误状态"""
    hosts = parse_ssh_config()
    results = await probe_all_hosts_concurrently(hosts)

    # 筛选出开机在线的主机，并发采集系统指标 (CPU/内存/磁盘/操作系统/防火墙)
    online_aliases = [
        alias for alias, res in results.items()
        if res.get("online")
    ]
    metrics_map = {}
    if online_aliases:
        metrics_map = await metrics_service.fetch_all_metrics(online_aliases)
        # 将密码不对/认证被拒状态回填到 results
        for alias, m in metrics_map.items():
            if m and (m.get("auth_failed") or m.get("status") == "auth_failed"):
                if alias in results:
                    results[alias]["auth_failed"] = True
                    results[alias]["auth_message"] = m.get("message", "已开机，但密码不对或未完成认证")
            if m and m.get("auth_method") and alias in results:
                results[alias]["auth_method"] = m.get("auth_method")

    return {
        "status": "ok",
        "count": len(hosts),
        "results": results,
        "metrics": metrics_map
    }

@app.post("/api/v1/ssh/credentials/{host_alias}")
async def set_host_credential_endpoint(host_alias: str, payload: SetCredentialPayload):
    """为指定主机动态配置/更新 SSH 密码并立即重新发起全量深度探测"""
    host_info = find_host_by_alias(host_alias)
    if not host_info:
        raise HTTPException(status_code=404, detail=f"未找到主机: {host_alias}")
    metrics_service.set_credential(host_alias, payload.password)

    inspection = await metrics_service.fetch_full_inspection(host_alias)
    auth_failed = bool(inspection.get("auth_failed") or inspection.get("status") == "auth_failed")
    return {
        "status": "ok",
        "host_alias": host_alias,
        "auth_failed": auth_failed,
        "auth_message": inspection.get("message") if auth_failed else None,
        "auth_method": inspection.get("auth_method", "password"),
        "inspection": inspection
    }

@app.get("/api/v1/ssh/inspect/{host_alias}")
async def inspect_host_endpoint(host_alias: str):
    """
    全页面深度数据探测：实时采集目标主机的性能监控、真实进程列表、Docker 容器、Systemd 服务、Crontab 计划任务、防火墙规则与文件树
    """
    host_info = find_host_by_alias(host_alias)
    if not host_info:
        raise HTTPException(status_code=404, detail=f"未找到主机: {host_alias}")
    return await metrics_service.fetch_full_inspection(host_alias)

@app.post("/api/v1/ssh/cron/{host_alias}/tasks")
async def create_cron_task(host_alias: str, payload: CronTaskCreatePayload):
    """在 SSH 登录用户的 crontab 中追加一个真实计划任务。"""
    if not find_host_by_alias(host_alias):
        raise HTTPException(status_code=404, detail=f"未找到主机: {host_alias}")
    result = await metrics_service.create_cron_task(
        host_alias,
        title=payload.title,
        expression=payload.expression,
        command=payload.command,
    )
    if result.get("status") != "ok":
        raise HTTPException(status_code=400, detail=result.get("message", "写入 Crontab 失败"))
    return result

@app.post("/api/v1/ssh/cron/{host_alias}/tasks/{task_id}/enabled")
async def set_cron_task_enabled(host_alias: str, task_id: str, payload: CronTaskEnabledPayload):
    """真实注释或恢复指定 Crontab 任务。"""
    if not find_host_by_alias(host_alias):
        raise HTTPException(status_code=404, detail=f"未找到主机: {host_alias}")
    result = await metrics_service.set_cron_task_enabled(host_alias, task_id, payload.enabled)
    if result.get("status") != "ok":
        raise HTTPException(status_code=400, detail=result.get("message", "更新 Crontab 失败"))
    return result

@app.post("/api/v1/ssh/cron/{host_alias}/tasks/{task_id}/run")
async def run_cron_task(host_alias: str, task_id: str):
    """在目标机当前 SSH 用户上下文中立即执行一次指定任务命令。"""
    if not find_host_by_alias(host_alias):
        raise HTTPException(status_code=404, detail=f"未找到主机: {host_alias}")
    result = await metrics_service.run_cron_task(host_alias, task_id)
    if result.get("status") != "ok":
        raise HTTPException(status_code=400, detail=result.get("message", "试运行失败"))
    return result

@app.get("/api/v1/ssh/processes/{host_alias}")
async def list_processes_endpoint(host_alias: str):
    if not find_host_by_alias(host_alias):
        raise HTTPException(status_code=404, detail=f"未找到主机: {host_alias}")
    return await metrics_service.list_processes(host_alias)

@app.post("/api/v1/ssh/processes/{host_alias}/kill")
async def signal_process_endpoint(host_alias: str, payload: ProcessSignalPayload):
    if not find_host_by_alias(host_alias):
        raise HTTPException(status_code=404, detail=f"未找到主机: {host_alias}")
    return await metrics_service.signal_process(host_alias, payload)

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

# ==============================================================================
# 远端服务器 SFTP / SSH 文件管理 API 路由组
# ==============================================================================

@app.get("/api/v1/ssh/files/{host_alias}/list")
async def list_remote_files(host_alias: str, path: str = "~", show_hidden: bool = True):
    """获取指定远端主机目录下的真实文件列表、权限、所有者与磁盘挂载空间"""
    return await metrics_service.list_directory(host_alias, path=path, show_hidden=show_hidden)

@app.get("/api/v1/ssh/files/{host_alias}/du")
async def analyze_remote_disk_usage(host_alias: str, path: str = "~"):
    """分析远端主机指定目录下各子项体积分布 (类 ncdu 磁盘占用分析)"""
    return await metrics_service.analyze_disk_usage(host_alias, path=path)

@app.get("/api/v1/ssh/files/{host_alias}/dir-sizes")
async def get_remote_directory_sizes(host_alias: str, path: str = "~"):
    """异步扫描指定目录下所有子目录的真实磁盘占用 (非阻塞)"""
    return await metrics_service.analyze_disk_usage(host_alias, path=path)

@app.post("/api/v1/ssh/files/{host_alias}/single-dir-size")
async def calculate_remote_single_dir_size(host_alias: str, payload: SingleDirSizePayload):
    """单独测算指定文件夹的真实磁盘占用 (du -sb)"""
    return await metrics_service.calculate_single_dir_size(host_alias, path=payload.path, sudo=payload.sudo)

@app.get("/api/v1/ssh/files/{host_alias}/content")
async def read_remote_file_content(host_alias: str, path: str):
    """读取远端文本文件内容供内置编辑器在线编辑"""
    return await metrics_service.read_file_content(host_alias, path=path)

@app.put("/api/v1/ssh/files/{host_alias}/content")
async def write_remote_file_content(host_alias: str, payload: WriteFilePayload):
    """将内置编辑器修改后的内容保存写回远端服务器"""
    return await metrics_service.write_file_content(
        host_alias,
        path=payload.path,
        content=payload.content,
        sudo_write=payload.sudo_write
    )

@app.post("/api/v1/ssh/files/{host_alias}/mkdir")
async def mkdir_remote_directory(host_alias: str, payload: MkdirPayload):
    """在远端服务器新建文件夹"""
    return await metrics_service.create_directory(
        host_alias,
        path=payload.path,
        mode=payload.mode,
        sudo=payload.sudo
    )

@app.post("/api/v1/ssh/files/{host_alias}/touch")
async def touch_remote_file(host_alias: str, payload: TouchFilePayload):
    """在远端服务器新建空白或带初始内容的文件"""
    return await metrics_service.create_file(
        host_alias,
        path=payload.path,
        content=payload.content,
        sudo=payload.sudo
    )

@app.post("/api/v1/ssh/files/{host_alias}/rename")
async def rename_remote_path(host_alias: str, payload: RenameFilePayload):
    """重命名或移动远端文件/目录"""
    return await metrics_service.rename_path(
        host_alias,
        old_path=payload.old_path,
        new_path=payload.new_path,
        sudo=payload.sudo
    )

@app.post("/api/v1/ssh/files/{host_alias}/copy")
async def copy_remote_path(host_alias: str, payload: CopyFilePayload):
    """复制远端文件/目录"""
    return await metrics_service.copy_path(
        host_alias,
        src_path=payload.src_path,
        dest_path=payload.dest_path,
        sudo=payload.sudo
    )

@app.post("/api/v1/ssh/files/{host_alias}/delete")
async def delete_remote_paths(host_alias: str, payload: DeleteFilesPayload):
    """删除远端文件或目录（带系统核心目录防误删保护）"""
    return await metrics_service.delete_paths(
        host_alias,
        paths=payload.paths,
        sudo=payload.sudo
    )

@app.delete("/api/v1/ssh/docker/{host_alias}/containers/{container}")
async def remove_docker_container(host_alias: str, container: str, force: bool = False, remove_volumes: bool = False):
    """删除远端 Docker 容器"""
    return await metrics_service.remove_docker_container(host_alias, container, force, remove_volumes)

@app.post("/api/v1/ssh/files/{host_alias}/chmod")
async def chmod_remote_path(host_alias: str, payload: ChmodFilePayload):
    """变更远端文件/目录的权限 (chmod) 及所有者 (chown)"""
    return await metrics_service.chmod_path(
        host_alias,
        path=payload.path,
        octal=payload.octal,
        recursive=payload.recursive,
        owner=payload.owner,
        group=payload.group,
        sudo=payload.sudo
    )

@app.post("/api/v1/ssh/files/{host_alias}/archive")
async def archive_remote_paths(host_alias: str, payload: ArchiveFilesPayload):
    """远端打包压缩 (.tar.gz) 或解压归档文件"""
    return await metrics_service.archive_paths(
        host_alias,
        paths=payload.paths,
        output_path=payload.output_path,
        target_dir=payload.target_dir,
        action=payload.action,
        sudo=payload.sudo
    )

@app.post("/api/v1/ssh/files/{host_alias}/upload")
async def upload_remote_file(host_alias: str, path: str, sudo: bool = False, request: Request = None):
    """接收客户端上传的文件二进制流并写入远端服务器目标路径"""
    body_bytes = await request.body()
    return await metrics_service.upload_file(host_alias, remote_path=path, data=body_bytes, sudo=sudo)

@app.get("/api/v1/ssh/files/{host_alias}/download")
async def download_remote_file(host_alias: str, path: str):
    """从远端服务器下载文件（若目标为文件夹则自动打包为 .tar.gz 流式下载）"""
    data, filename, err = await metrics_service.download_file(host_alias, remote_path=path)
    if err or data is None:
        raise HTTPException(status_code=400, detail=err or "下载失败")
    encoded_name = urllib.parse.quote(filename or "download")
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
            "Access-Control-Expose-Headers": "Content-Disposition",
        }
    )

@app.get("/api/v1/ssh/files/{host_alias}/download-batch")
async def download_batch_files_get(host_alias: str, paths: List[str] = Query(...)):
    """从远端服务器批量下载文件（GET 查询参数，自动打包为 .tar.gz 流式下载）"""
    data, filename, err = await metrics_service.download_batch(host_alias, paths=paths)
    if err or data is None:
        raise HTTPException(status_code=400, detail=err or "批量下载失败")
    encoded_name = urllib.parse.quote(filename or "batch_download.tar.gz")
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
            "Access-Control-Expose-Headers": "Content-Disposition",
        }
    )

@app.post("/api/v1/ssh/files/{host_alias}/download-batch")
async def download_batch_files_post(host_alias: str, payload: DownloadBatchPayload):
    """从远端服务器批量下载文件（POST JSON 请求体，自动打包为 .tar.gz 流式下载）"""
    data, filename, err = await metrics_service.download_batch(host_alias, paths=payload.paths)
    if err or data is None:
        raise HTTPException(status_code=400, detail=err or "批量下载失败")
    encoded_name = urllib.parse.quote(filename or "batch_download.tar.gz")
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
            "Access-Control-Expose-Headers": "Content-Disposition",
        }
    )

@app.post("/api/v1/ssh/docker/{host_alias}/containers/{container}/restart")
async def restart_docker_container_endpoint(host_alias: str, container: str, payload: DockerRestartPayload):
    if not find_host_by_alias(host_alias):
        raise HTTPException(status_code=404, detail=f"未找到主机: {host_alias}")
    return await metrics_service.restart_docker_container(host_alias, container, sudo=payload.sudo)


@app.post("/api/v1/ssh/docker/{host_alias}/containers/{container}/action")
async def control_docker_container_endpoint(host_alias: str, container: str, payload: DockerActionPayload):
    if not find_host_by_alias(host_alias):
        raise HTTPException(status_code=404, detail=f"未找到主机: {host_alias}")
    return await metrics_service.control_docker_container(host_alias, container, payload.action, sudo=payload.sudo)


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
        if init_json.get("action") != "auth":
            raise ValueError("首帧必须为 auth")
        auth_data = TerminalAuthPayload(**init_json.get("payload", {}))
        cols = auth_data.cols
        rows = auth_data.rows
        term = auth_data.term
    except Exception:
        await websocket.send_json({"action": "stderr", "payload": "终端认证参数无效或超时，请重新连接。\r\n"})
        await websocket.close(code=1008)
        return

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
    elif host_alias in metrics_service._credentials:
        conn_kwargs["password"] = metrics_service._credentials[host_alias]

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
            command = docker_exec_command(auth_data.docker_container, auth_data.sudo) if auth_data.docker_container else None
            async with conn.create_process(
                command,
                term_type=term,
                term_size=(cols, rows),
                env={"LANG": "en_US.UTF-8"},
                encoding=None # 原始字节流
            ) as process:
                await websocket.send_json({"action": "ready"})

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
                    while True:
                        try:
                            msg_raw = await websocket.receive_text()
                        except (WebSocketDisconnect, asyncio.CancelledError):
                            break
                        except Exception:
                            break

                        try:
                            msg = json.loads(msg_raw)
                            action = msg.get("action")

                            if action == "stdin":
                                data = msg.get("payload", "")
                                if data:
                                    process.stdin.write(data.encode("utf-8"))
                            elif action == "resize":
                                payload = msg.get("payload") or {}
                                new_cols = int(payload.get("cols", cols) or cols)
                                new_rows = int(payload.get("rows", rows) or rows)
                                if new_cols > 0 and new_rows > 0:
                                    try:
                                        process.change_terminal_size(new_cols, new_rows)
                                    except Exception as e:
                                        logger.warning(f"change_terminal_size failed: {e}")
                            elif action == "ping":
                                await websocket.send_text(json.dumps({"action": "pong"}))
                        except Exception as e:
                            logger.warning(f"Error handling websocket message: {e}")

                remote_task = asyncio.create_task(pump_remote_to_ws())
                ws_task = asyncio.create_task(pump_ws_to_remote())

                done, pending = await asyncio.wait(
                    [remote_task, ws_task],
                    return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                if remote_task in done:
                    await process.wait_closed()
                    await websocket.send_json({"action": "stdout", "payload": f"\r\n会话已结束 (Exit {process.exit_status})\r\n"})

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
