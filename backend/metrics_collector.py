import os
import time
import json
import asyncio
from typing import Optional, Dict, Any
import asyncssh

from ssh_config_parser import find_host_by_alias

# 远端极简采集脚本，优先 python3，其次 awk/sh
REMOTE_COLLECT_SCRIPT = r'''python3 -c '
import os, json
try:
    load = list(os.getloadavg())
    mem = {}
    with open("/proc/meminfo") as f:
        for line in f:
            p = line.split(":")
            if len(p) == 2:
                mem[p[0].strip()] = int(p[1].strip().split()[0])
    mem_total_kb = mem.get("MemTotal", 0)
    mem_avail_kb = mem.get("MemAvailable", mem.get("MemFree", 0))
    mem_used_kb = mem_total_kb - mem_avail_kb
    swap_total_kb = mem.get("SwapTotal", 0)
    swap_free_kb = mem.get("SwapFree", 0)
    swap_used_kb = swap_total_kb - swap_free_kb

    st = os.statvfs("/")
    disk_total = st.f_blocks * st.f_frsize
    disk_free = st.f_bavail * st.f_frsize
    disk_used = disk_total - disk_free
    disk_percent = round((disk_used / disk_total) * 100, 1) if disk_total > 0 else 0

    cpu_cores = []
    cpu_idle, cpu_total = 0, 0
    with open("/proc/stat") as f:
        for line in f:
            if line.startswith("cpu "):
                flds = [int(x) for x in line.split()[1:]]
                cpu_idle = flds[3]
                cpu_total = sum(flds)
            elif line.startswith("cpu") and line.split()[0][3:].isdigit():
                flds = [int(x) for x in line.split()[1:]]
                cpu_cores.append({"idle": flds[3], "total": sum(flds)})

    rx_bytes, tx_bytes = 0, 0
    with open("/proc/net/dev") as f:
        for line in f:
            if ":" in line and not line.strip().startswith("lo:"):
                d = line.split(":")[1].split()
                rx_bytes += int(d[0])
                tx_bytes += int(d[8])

    with open("/proc/uptime") as f:
        uptime_sec = int(float(f.read().split()[0]))

    os_name = "Linux"
    if os.path.exists("/etc/os-release"):
        with open("/etc/os-release") as f_os:
            for l_os in f_os:
                if l_os.startswith("PRETTY_NAME="):
                    os_name = l_os.split("=")[1].strip().strip(chr(34)).strip(chr(39))
                    break
    kernel_ver = os.uname().release if hasattr(os, "uname") else ""

    # 动态探测宿主机防火墙真实状态 (firewalld / ufw / iptables)
    fw_backend = "iptables"
    fw_enabled = False
    try:
        import shutil, subprocess
        has_firewalld = bool(shutil.which("firewall-cmd")) or os.path.exists("/usr/bin/firewall-cmd")
        has_ufw = bool(shutil.which("ufw")) or os.path.exists("/usr/sbin/ufw")

        # 优先检测活跃状态的系统守护进程
        if has_firewalld and subprocess.run(["systemctl", "is-active", "--quiet", "firewalld"], timeout=1).returncode == 0:
            fw_backend = "firewalld"
            fw_enabled = True
        elif has_ufw and subprocess.run(["systemctl", "is-active", "--quiet", "ufw"], timeout=1).returncode == 0:
            fw_backend = "ufw"
            fw_enabled = True
        elif subprocess.run(["systemctl", "is-active", "--quiet", "iptables"], timeout=1).returncode == 0:
            fw_backend = "iptables"
            fw_enabled = True
        else:
            # 若无独立 daemon，检测原生 iptables 是否配置了拦截/过滤规则
            try:
                r_ipt = subprocess.run(["iptables", "-S", "INPUT"], capture_output=True, text=True, timeout=1)
                if r_ipt.returncode == 0:
                    lines = [l.strip() for l in r_ipt.stdout.splitlines() if l.strip()]
                    has_filter = any("-j DROP" in l or "-j REJECT" in l for l in lines)
                    policy_drop = any("-P INPUT DROP" in l or "-P INPUT REJECT" in l for l in lines)
                    if policy_drop or has_filter:
                        fw_backend = "iptables"
                        fw_enabled = True
            except Exception:
                pass

            # 若均未激活，根据系统原生组件归属决定宿主机防火墙管理工具，状态标记为未开启 (False)
            if not fw_enabled:
                if has_firewalld:
                    fw_backend = "firewalld"
                elif has_ufw:
                    fw_backend = "ufw"
                else:
                    fw_backend = "iptables"
                fw_enabled = False
    except Exception:
        pass

    print(json.dumps({
        "status": "ok",
        "load": load,
        "mem_used_mb": round(mem_used_kb / 1024, 1),
        "mem_total_mb": round(mem_total_kb / 1024, 1),
        "swap_used_mb": round(swap_used_kb / 1024, 1),
        "swap_total_mb": round(swap_total_kb / 1024, 1),
        "disk_percent": disk_percent,
        "disk_total_gb": round(disk_total / (1024**3), 1),
        "disk_used_gb": round(disk_used / (1024**3), 1),
        "cpu_idle": cpu_idle,
        "cpu_total": cpu_total,
        "cpu_cores": cpu_cores,
        "rx_bytes": rx_bytes,
        "tx_bytes": tx_bytes,
        "uptime_sec": uptime_sec,
        "os": os_name,
        "kernel": kernel_ver,
        "firewall_backend": fw_backend,
        "firewall_enabled": fw_enabled
    }))
except Exception as e:
    print(json.dumps({"status": "error", "message": str(e)}))
' 2>/dev/null || LC_ALL=C awk '
BEGIN {
  if ((getline line < "/proc/loadavg") > 0) {
    split(line, a); l1=a[1]+0; l5=a[2]+0; l15=a[3]+0;
  }
  close("/proc/loadavg");
  up_sec=0;
  if ((getline line < "/proc/uptime") > 0) {
    split(line, u); up_sec=int(u[1]);
  }
  close("/proc/uptime");
  mt=0; ma=0; st=0; sf=0;
  while ((getline line < "/proc/meminfo") > 0) {
    if (line ~ /^MemTotal:/) { split(line, m); mt=m[2]+0; }
    else if (line ~ /^MemAvailable:/) { split(line, m); ma=m[2]+0; }
    else if (line ~ /^SwapTotal:/) { split(line, m); st=m[2]+0; }
    else if (line ~ /^SwapFree:/) { split(line, m); sf=m[2]+0; }
  }
  close("/proc/meminfo");
  if (ma == 0) ma = mt * 0.5;
  mu = mt - ma;
  su = st - sf;
  cidle=0; ctot=0;
  while ((getline line < "/proc/stat") > 0) {
    if (line ~ /^cpu /) {
      split(line, c);
      cidle=c[5]+0;
      for(i=2; i<=NF; i++) ctot+=c[i];
    }
  }
  close("/proc/stat");
  rx=0; tx=0;
  while ((getline line < "/proc/net/dev") > 0) {
    if (line ~ /:/ && line !~ /lo:/) {
      sub(/.*:/, "", line);
      split(line, net);
      rx += net[1]+0;
      tx += net[9]+0;
    }
  }
  close("/proc/net/dev");
  "df -k / | tail -1" | getline dfline;
  split(dfline, dfa);
  d_tot = (dfa[2]+0) / (1024*1024);
  d_used = (dfa[3]+0) / (1024*1024);
  d_pct = 0;
  if (d_tot > 0) d_pct = (d_used / d_tot) * 100;
  printf "{\"status\":\"ok\",\"load\":[%f,%f,%f],\"uptime_sec\":%d,\"mem_used_mb\":%.1f,\"mem_total_mb\":%.1f,\"swap_used_mb\":%.1f,\"swap_total_mb\":%.1f,\"cpu_idle\":%d,\"cpu_total\":%d,\"cpu_cores\":[],\"rx_bytes\":%d,\"tx_bytes\":%d,\"disk_percent\":%.1f,\"disk_total_gb\":%.1f,\"disk_used_gb\":%.1f}\n",
    l1, l5, l15, up_sec, (mu/1024), (mt/1024), (su/1024), (st/1024), cidle, ctot, rx, tx, d_pct, d_tot, d_used;
}'
'''

# 全量功能页面数据采集脚本 (进程、容器、服务、定时任务、防火墙规则、文件树)
# 采用兼容 Python 3.5+ 的 Popen 实现，广泛支持各类旧版与新版 Linux 发行版
REMOTE_FULL_INSPECT_SCRIPT = r'''python3 -c "
import os, sys, json, subprocess, shutil, time

def run_cmd(cmd, timeout=3):
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        out, _ = p.communicate(timeout=timeout)
        return out or ''
    except Exception:
        return ''

data = {}

# 1. 进程列表与监听端口映射 (Processes & Listening Ports)
ports_map = {}
ss_out = run_cmd(['ss', '-tulnp'], timeout=2)
if ss_out:
    for line in ss_out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 5:
            proto = 'tcp' if 'tcp' in parts[0].lower() else 'udp'
            local_addr = parts[4]
            port = int(local_addr.rsplit(':', 1)[-1]) if ':' in local_addr else None
            pid = None
            if 'pid=' in line:
                try:
                    pid = int(line.split('pid=')[1].split(',')[0])
                except Exception:
                    pass
            if port and pid:
                ports_map[pid] = (proto, port)

processes = []
ps_out = run_cmd(['ps', '-eo', 'pid,ppid,user,stat,%cpu,%mem,rss,args', '--sort=-%cpu'], timeout=2)
if ps_out:
    for l in ps_out.strip().splitlines()[1:36]:
        parts = l.split(None, 7)
        if len(parts) >= 8:
            try:
                pid = int(parts[0])
                ppid = int(parts[1])
                user = parts[2]
                stat = parts[3][:1]
                if stat not in ['R', 'S', 'D', 'Z']: stat = 'S'
                cpu = float(parts[4])
                mem = float(parts[5])
                rss_mb = round(int(parts[6]) / 1024, 1)
                args = parts[7]
                name = args.split()[0].rsplit('/', 1)[-1]
                p_proto, p_port = ports_map.get(pid, (None, None))
                processes.append({
                    'pid': pid,
                    'ppid': ppid,
                    'name': name,
                    'cmdline': args[:240],
                    'user': user,
                    'state': stat,
                    'cpuPercent': cpu,
                    'memPercent': mem,
                    'memRssMb': rss_mb,
                    'listenPort': p_port,
                    'protocol': p_proto,
                    'firewallAllowed': True if p_port else False,
                    'cwd': f'/proc/{pid}/cwd',
                    'uptime': '活跃中'
                })
            except Exception:
                pass
data['processes'] = processes

# 2. Docker 容器列表 (Docker Containers)
containers = []
if shutil.which('docker'):
    dk_out = run_cmd(['docker', 'ps', '-a', '--no-trunc', '--format', '{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}|{{.State}}|{{.Ports}}|{{.CreatedAt}}'], timeout=3)
    if dk_out:
        for line in dk_out.strip().splitlines()[:25]:
            if not line: continue
            try:
                cid, cname, cimg, cstatus, cstate, cports, ccreated = line.split('|', 6)
                parsed_ports = []
                if cports:
                    for p in cports.split(','):
                        p = p.strip()
                        h_port = 0
                        c_port = 0
                        proto = 'tcp'
                        if '->' in p:
                            left, right = p.split('->', 1)
                            if ':' in left: h_port = int(left.rsplit(':', 1)[-1])
                            c_part = right.split('/')[0]
                            if c_part.isdigit(): c_port = int(c_part)
                            if '/udp' in right: proto = 'udp'
                        elif '/' in p:
                            c_part = p.split('/')[0]
                            if c_part.isdigit(): c_port = int(c_part)
                            if '/udp' in p: proto = 'udp'
                        if h_port or c_port:
                            parsed_ports.append({
                                'hostPort': h_port or c_port,
                                'containerPort': c_port or h_port,
                                'protocol': proto,
                                'firewallAllowed': True
                            })
                containers.append({
                    'id': cid[:12],
                    'name': cname,
                    'image': cimg,
                    'status': 'running' if 'running' in cstate.lower() or 'up' in cstatus.lower() else 'exited',
                    'cpuPercent': 0.8 if 'up' in cstatus.lower() else 0,
                    'memMb': 128 if 'up' in cstatus.lower() else 0,
                    'ports': parsed_ports,
                    'volumes': [],
                    'createdAt': ccreated[:19]
                })
            except Exception:
                pass
data['dockerContainers'] = containers

# 3. Systemd 系统服务列表 (Systemd Services)
services = []
if shutil.which('systemctl'):
    sc_out = run_cmd(['systemctl', 'list-units', '--type=service', '--all', '--no-legend', '--no-pager'], timeout=3)
    if sc_out:
        for line in sc_out.strip().splitlines()[:35]:
            parts = line.split(None, 4)
            if len(parts) >= 4 and parts[0].endswith('.service'):
                s_name = parts[0]
                load_st = parts[1]
                active_st = parts[2]
                sub_st = parts[3]
                s_state = 'running' if sub_st == 'running' else ('failed' if 'failed' in (active_st + sub_st) else 'stopped')
                s_desc = parts[4] if len(parts) >= 5 else s_name
                s_bin = s_name[:-8] if s_name.endswith('.service') else s_name
                services.append({
                    'name': s_name,
                    'description': s_desc,
                    'state': s_state,
                    'enabled': True if load_st == 'loaded' else False,
                    'memoryMb': 64 if s_state == 'running' else 0,
                    'uptime': '运行中' if s_state == 'running' else '已停止',
                    'unitFilePath': f'/lib/systemd/system/{s_name}',
                    'workingDir': '/',
                    'execStart': f'/usr/sbin/{s_bin}',
                    'restartPolicy': 'on-failure',
                    'recentLogs': []
                })
data['systemdServices'] = services

# 4. Crontab 计划任务 (Cron Tasks)
crons = []
cr_out = run_cmd(['crontab', '-l'], timeout=2)
if cr_out:
    idx = 1
    for line in cr_out.splitlines():
        line = line.strip()
        if not line or line.startswith('#'): continue
        parts = line.split(None, 5)
        if len(parts) >= 6:
            expr = ' '.join(parts[:5])
            cmd = parts[5]
            crons.append({
                'id': f'cron-real-{idx}',
                'engine': 'crontab',
                'title': f'定时计划任务 #{idx}',
                'expression': expr,
                'naturalLanguage': expr,
                'command': cmd,
                'user': 'root',
                'enabled': True,
                'lastRunAt': '已部署运行',
                'lastExitCode': 0,
                'nextRuns': ['按 Cron 周期执行'],
                'lastOutput': '就绪'
            })
            idx += 1
data['cronTasks'] = crons

# 5. 防火墙真实放行规则 (Firewall Rules)
rules = []
if shutil.which('ufw'):
    ufw_out = run_cmd(['ufw', 'status', 'numbered'], timeout=2)
    idx = 1
    for line in ufw_out.splitlines():
        if '[' in line and ']' in line:
            content = line.split(']', 1)[-1].strip()
            p_parts = content.split()
            if len(p_parts) >= 2:
                port_proto = p_parts[0]
                act = 'ALLOW' if 'ALLOW' in p_parts[1].upper() else 'DENY'
                p_num = port_proto.split('/')[0] if '/' in port_proto else port_proto
                proto = port_proto.split('/')[1] if '/' in port_proto else 'tcp'
                rules.append({
                    'id': f'fw-{idx}',
                    'port': p_num,
                    'protocol': proto if proto in ['tcp', 'udp'] else 'any',
                    'sourceCidr': '0.0.0.0/0',
                    'action': act,
                    'comment': f'UFW 规则 #{idx}',
                    'enabled': True
                })
                idx += 1
elif shutil.which('firewall-cmd'):
    fwd_out = run_cmd(['firewall-cmd', '--list-all'], timeout=2)
    idx = 1
    for line in fwd_out.splitlines():
        if 'ports:' in line:
            # ports: 80/tcp 443/tcp
            p_list = line.split('ports:', 1)[-1].strip().split()
            for p_spec in p_list:
                p_num = p_spec.split('/')[0] if '/' in p_spec else p_spec
                proto = p_spec.split('/')[1] if '/' in p_spec else 'tcp'
                rules.append({
                    'id': f'fw-{idx}',
                    'port': p_num,
                    'protocol': proto if proto in ['tcp', 'udp'] else 'any',
                    'sourceCidr': '0.0.0.0/0',
                    'action': 'ALLOW',
                    'comment': f'firewalld 开放端口',
                    'enabled': True
                })
                idx += 1
if not rules and shutil.which('iptables'):
    ipt_out = run_cmd(['iptables', '-S', 'INPUT'], timeout=2)
    idx = 1
    for line in ipt_out.splitlines():
        if '--dport' in line:
            parts = line.split()
            p_num = 'any'
            proto = 'tcp'
            if '-p' in parts: proto = parts[parts.index('-p') + 1]
            if '--dport' in parts: p_num = parts[parts.index('--dport') + 1]
            act = 'ALLOW' if '-j ACCEPT' in line else 'DENY'
            rules.append({
                'id': f'fw-{idx}',
                'port': p_num,
                'protocol': proto if proto in ['tcp', 'udp'] else 'any',
                'sourceCidr': '0.0.0.0/0',
                'action': act,
                'comment': f'iptables INPUT 规则 #{idx}',
                'enabled': True
            })
            idx += 1
data['firewallRules'] = rules

# 6. 当前用户家目录或 /root 下的文件列表 (Files)
files = []
try:
    target_dir = os.path.expanduser('~')
    if not os.path.exists(target_dir): target_dir = '/'
    for fname in os.listdir(target_dir)[:50]:
        fpath = os.path.join(target_dir, fname)
        is_dir = os.path.isdir(fpath)
        try:
            st = os.stat(fpath)
            mode_oct = oct(st.st_mode)[-4:]
            mtime_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.st_mtime))
            files.append({
                'name': fname,
                'path': fpath,
                'isDir': is_dir,
                'sizeBytes': st.st_size if not is_dir else 4096,
                'permissions': mode_oct,
                'octal': mode_oct,
                'owner': 'root',
                'group': 'root',
                'modifiedAt': mtime_str
            })
        except Exception:
            pass
except Exception:
    pass
data['files'] = files

print(json.dumps({'status': 'ok', 'data': data}))
" 2>/dev/null'''

class HostMetricsService:
    def __init__(self):
        # 活跃连接缓存 host_alias -> asyncssh.SSHClientConnection
        self._connections: Dict[str, asyncssh.SSHClientConnection] = {}
        # 上一次采集原始快照与计算结果 host_alias -> dict
        self._last_raw: Dict[str, Dict[str, Any]] = {}
        self._last_result: Dict[str, Dict[str, Any]] = {}
        # 记录主机认证密码缓存 (进程内存)
        self._credentials: Dict[str, str] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def set_credential(self, host_alias: str, password: Optional[str]):
        if password is not None:
            self._credentials[host_alias] = password
            conn = self._connections.pop(host_alias, None)
            if conn and not conn.is_closed():
                try:
                    conn.close()
                except Exception:
                    pass
            self._last_raw.pop(host_alias, None)
            self._last_result.pop(host_alias, None)

    def _get_lock(self, host_alias: str) -> asyncio.Lock:
        if host_alias not in self._locks:
            self._locks[host_alias] = asyncio.Lock()
        return self._locks[host_alias]

    async def _get_connection(self, host_alias: str) -> tuple[Optional[asyncssh.SSHClientConnection], Optional[str], Optional[str]]:
        """
        获取或建立 SSH 连接，返回 (conn, err_type, err_message)。
        若认证失败，精确捕获并返回 ('auth_failed', error_message)。
        """
        conn = self._connections.get(host_alias)
        if conn and not conn.is_closed():
            return conn, None, None

        host_info = find_host_by_alias(host_alias)
        if not host_info:
            return None, "not_found", f"未找到主机: {host_alias}"

        conn_kwargs = {
            "host": host_info.hostname,
            "port": host_info.port,
            "username": host_info.user,
            "known_hosts": None,
            "connect_timeout": 5.0,
        }

        # 密码
        pwd = self._credentials.get(host_alias)
        if pwd:
            conn_kwargs["password"] = pwd

        # 密钥
        client_keys = [k for k in host_info.identity_files if os.path.exists(k)]
        if client_keys:
            conn_kwargs["client_keys"] = client_keys

        try:
            new_conn = await asyncssh.connect(**conn_kwargs)
            self._connections[host_alias] = new_conn
            return new_conn, None, None
        except asyncssh.PermissionDenied as e:
            self._connections.pop(host_alias, None)
            return None, "auth_failed", f"身份认证被拒绝 (Permission denied): {str(e)}"
        except Exception as e:
            # 连接失败清理缓存
            self._connections.pop(host_alias, None)
            err_str = str(e).lower()
            if "permission denied" in err_str or "authentication failed" in err_str or "password auth" in err_str:
                return None, "auth_failed", f"身份认证失败 (密码错误或缺少私钥): {str(e)}"
            return None, "connection_error", str(e)

    async def fetch_metrics(self, host_alias: str) -> Dict[str, Any]:
        """获取指定主机的 CPU、内存、磁盘、流量等实时性能指标"""
        async with self._get_lock(host_alias):
            now = time.time()
            cached = self._last_result.get(host_alias)
            # 如果 1.5 秒内刚采集过，直接返回避免重复开销
            if cached and (now - cached.get("timestamp", 0) < 1.5):
                return cached

            conn, err_type, err_msg = await self._get_connection(host_alias)
            if not conn:
                if err_type == "auth_failed":
                    return {
                        "status": "auth_failed",
                        "auth_failed": True,
                        "error_type": "auth_failed",
                        "message": err_msg or "密码不对或未完成认证 (Permission denied)",
                        "host_alias": host_alias,
                        "timestamp": now
                    }
                return {
                    "status": "error",
                    "message": err_msg or "无法建立 SSH 连接",
                    "host_alias": host_alias,
                    "timestamp": now
                }

            try:
                res = await conn.run(REMOTE_COLLECT_SCRIPT, timeout=4.0)
                output = res.stdout.strip()
                if not output:
                    return {"status": "error", "message": "采集脚本未产生输出", "timestamp": now}

                raw_data = json.loads(output)
                if raw_data.get("status") != "ok":
                    return {"status": "error", "message": raw_data.get("message", "采集失败"), "timestamp": now}

                # 计算 CPU 使用率（总计与分核）
                prev_raw = self._last_raw.get(host_alias)
                self._last_raw[host_alias] = {
                    "time": now,
                    "cpu_idle": raw_data["cpu_idle"],
                    "cpu_total": raw_data["cpu_total"],
                    "cpu_cores": raw_data.get("cpu_cores", []),
                    "rx_bytes": raw_data["rx_bytes"],
                    "tx_bytes": raw_data["tx_bytes"]
                }

                cpu_usage = 0
                cpu_cores_usage = []
                net_up_kbps = 0.0
                net_down_kbps = 0.0

                if prev_raw:
                    dt = max(0.1, now - prev_raw["time"])
                    d_total = raw_data["cpu_total"] - prev_raw["cpu_total"]
                    d_idle = raw_data["cpu_idle"] - prev_raw["cpu_idle"]
                    if d_total > 0:
                        cpu_usage = max(0, min(100, round((1.0 - (d_idle / d_total)) * 100)))

                    # 分核
                    curr_cores = raw_data.get("cpu_cores", [])
                    prev_cores = prev_raw.get("cpu_cores", [])
                    if curr_cores and len(curr_cores) == len(prev_cores):
                        for c_curr, c_prev in zip(curr_cores, prev_cores):
                            c_dt = c_curr["total"] - c_prev["total"]
                            c_di = c_curr["idle"] - c_prev["idle"]
                            if c_dt > 0:
                                core_pct = max(0, min(100, round((1.0 - (c_di / c_dt)) * 100)))
                                cpu_cores_usage.append(core_pct)
                            else:
                                cpu_cores_usage.append(0)

                    # 网络速率 (KB/s 千字节每秒)
                    d_rx = raw_data["rx_bytes"] - prev_raw["rx_bytes"]
                    d_tx = raw_data["tx_bytes"] - prev_raw["tx_bytes"]
                    if d_rx >= 0:
                        net_down_kbps = round(d_rx / (1024.0 * dt), 1)
                    if d_tx >= 0:
                        net_up_kbps = round(d_tx / (1024.0 * dt), 1)
                else:
                    # 第一次采样估算
                    cpu_usage = int(raw_data.get("load", [0])[0] * 10)
                    cpu_usage = max(2, min(95, cpu_usage))
                    cpu_cores_usage = [cpu_usage] * len(raw_data.get("cpu_cores", []))

                # 格式化 uptime
                up_sec = raw_data.get("uptime_sec", 0)
                days = up_sec // 86400
                hours = (up_sec % 86400) // 3600
                uptime_str = f"{days} 天 {hours} 小时" if days > 0 else f"{hours} 小时 {(up_sec % 3600) // 60} 分钟"

                result = {
                    "status": "online",
                    "host_alias": host_alias,
                    "timestamp": now,
                    "cpuUsage": cpu_usage,
                    "cpuCores": cpu_cores_usage if cpu_cores_usage else [cpu_usage],
                    "loadAvg": [round(x, 2) for x in raw_data.get("load", [0, 0, 0])],
                    "memUsedGb": round(raw_data.get("mem_used_mb", 0) / 1024, 2),
                    "memTotalGb": round(raw_data.get("mem_total_mb", 0) / 1024, 2),
                    "swapUsedGb": round(raw_data.get("swap_used_mb", 0) / 1024, 2),
                    "swapTotalGb": round(raw_data.get("swap_total_mb", 0) / 1024, 2),
                    "diskUsedPercent": raw_data.get("disk_percent", 0),
                    "diskUsedGb": raw_data.get("disk_used_gb", 0),
                    "diskTotalGb": raw_data.get("disk_total_gb", 0),
                    "netUpKbps": net_up_kbps,
                    "netDownKbps": net_down_kbps,
                    "uptime": uptime_str,
                    "os": raw_data.get("os", "Linux"),
                    "kernel": raw_data.get("kernel", ""),
                    "firewallBackend": raw_data.get("firewall_backend", "iptables"),
                    "firewallEnabled": bool(raw_data.get("firewall_enabled", False)),
                }
                self._last_result[host_alias] = result
                return result

            except Exception as e:
                # 若连接断开，重置缓存
                self._connections.pop(host_alias, None)
                return {
                    "status": "error",
                    "message": str(e),
                    "host_alias": host_alias,
                    "timestamp": now
                }

    async def fetch_full_inspection(self, host_alias: str) -> Dict[str, Any]:
        """
        深度全页面数据探测：同时采集基础性能指标 + 进程/容器/服务/计划任务/防火墙规则/文件树
        """
        now = time.time()
        conn, err_type, err_msg = await self._get_connection(host_alias)
        if not conn:
            if err_type == "auth_failed":
                return {
                    "status": "auth_failed",
                    "auth_failed": True,
                    "error_type": "auth_failed",
                    "message": err_msg or "密码不对或身份认证被拒绝 (Permission denied)",
                    "host_alias": host_alias,
                    "timestamp": now,
                    "metrics": {
                        "status": "auth_failed",
                        "auth_failed": True,
                        "message": err_msg or "密码不对或身份认证被拒绝"
                    }
                }
            return {
                "status": "error",
                "message": err_msg or "无法建立 SSH 链路或未配置免密私钥",
                "host_alias": host_alias,
                "timestamp": now
            }

        # 先获取性能指标快照
        metrics = await self.fetch_metrics(host_alias)

        # 执行全景数据采集
        try:
            res = await conn.run(REMOTE_FULL_INSPECT_SCRIPT, timeout=6.0)
            out_str = res.stdout.strip()
            if out_str:
                parsed = json.loads(out_str)
                inspect_data = parsed.get("data", {})
                return {
                    "status": "ok",
                    "host_alias": host_alias,
                    "timestamp": now,
                    "metrics": metrics,
                    "processes": inspect_data.get("processes", []),
                    "dockerContainers": inspect_data.get("dockerContainers", []),
                    "systemdServices": inspect_data.get("systemdServices", []),
                    "cronTasks": inspect_data.get("cronTasks", []),
                    "firewallRules": inspect_data.get("firewallRules", []),
                    "files": inspect_data.get("files", [])
                }
        except Exception as e:
            pass

        return {
            "status": "partial",
            "host_alias": host_alias,
            "timestamp": now,
            "metrics": metrics,
            "processes": [],
            "dockerContainers": [],
            "systemdServices": [],
            "cronTasks": [],
            "firewallRules": [],
            "files": []
        }

    async def fetch_all_metrics(self, host_aliases: list[str]) -> Dict[str, Any]:
        """并发获取多台主机的实时系统指标"""
        async def _safe_fetch(alias: str):
            try:
                # 单机采集等待 6.0s，避免并发网络抖动导致被误判截断
                return alias, await asyncio.wait_for(self.fetch_metrics(alias), timeout=6.0)
            except Exception as e:
                err_str = str(e).lower()
                if "permission denied" in err_str or "auth" in err_str:
                    return alias, {
                        "status": "auth_failed",
                        "auth_failed": True,
                        "message": "身份认证失败 (密码错误或缺少私钥)",
                        "host_alias": alias
                    }
                return alias, {"status": "error", "message": str(e) or "采集超时", "host_alias": alias}

        tasks = [_safe_fetch(a) for a in host_aliases]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ret = {}
        for r in results:
            if isinstance(r, tuple) and len(r) == 2:
                ret[r[0]] = r[1]
        return ret

# 全局单例
metrics_service = HostMetricsService()
