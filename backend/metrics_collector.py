import re
import os
import time
import json
import base64
import shlex
import asyncio
from typing import Optional, Dict, Any, List
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

    disk_read_bytes, disk_write_bytes = 0, 0
    if os.path.exists("/proc/diskstats"):
        import re
        with open("/proc/diskstats") as f_ds:
            for line in f_ds:
                parts = line.split()
                if len(parts) >= 10:
                    dev = parts[2]
                    if re.match(r"^(sd[a-z]+|vd[a-z]+|nvme[0-9]+n[0-9]+|xvd[a-z]+|mmcblk[0-9]+)$", dev):
                        disk_read_bytes += int(parts[5]) * 512
                        disk_write_bytes += int(parts[9]) * 512
        if disk_read_bytes == 0 and disk_write_bytes == 0:
            with open("/proc/diskstats") as f_ds:
                for line in f_ds:
                    parts = line.split()
                    if len(parts) >= 10:
                        dev = parts[2]
                        if not dev.startswith(("loop", "ram", "dm-")) and (dev[-1].isalpha() or dev.endswith("n1")):
                            disk_read_bytes += int(parts[5]) * 512
                            disk_write_bytes += int(parts[9]) * 512

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
        "disk_read_bytes": disk_read_bytes,
        "disk_write_bytes": disk_write_bytes,
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
  drb=0; dwb=0;
  while ((getline line < "/proc/diskstats") > 0) {
    split(line, ds);
    if (ds[3] ~ /^(sd[a-z]+|vd[a-z]+|nvme[0-9]+n[0-9]+|xvd[a-z]+|mmcblk[0-9]+)$/) {
      drb += ds[6] * 512;
      dwb += ds[10] * 512;
    }
  }
  close("/proc/diskstats");
  "df -k / | tail -1" | getline dfline;
  split(dfline, dfa);
  d_tot = (dfa[2]+0) / (1024*1024);
  d_used = (dfa[3]+0) / (1024*1024);
  d_pct = 0;
  if (d_tot > 0) d_pct = (d_used / d_tot) * 100;
  printf "{\"status\":\"ok\",\"load\":[%f,%f,%f],\"uptime_sec\":%d,\"mem_used_mb\":%.1f,\"mem_total_mb\":%.1f,\"swap_used_mb\":%.1f,\"swap_total_mb\":%.1f,\"cpu_idle\":%d,\"cpu_total\":%d,\"cpu_cores\":[],\"rx_bytes\":%d,\"tx_bytes\":%d,\"disk_percent\":%.1f,\"disk_total_gb\":%.1f,\"disk_used_gb\":%.1f,\"disk_read_bytes\":%d,\"disk_write_bytes\":%d}\n",
    l1, l5, l15, up_sec, (mu/1024), (mt/1024), (su/1024), (st/1024), cidle, ctot, rx, tx, d_pct, d_tot, d_used, drb, dwb;
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
    dk_out = run_cmd(['docker', 'ps', '-a', '--no-trunc', '--format', '{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}|{{.State}}|{{.Ports}}|{{.CreatedAt}}|{{.Size}}'], timeout=10)
    if not dk_out:
        dk_out = run_cmd(['docker', 'ps', '-a', '--no-trunc', '--format', '{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}|{{.State}}|{{.Ports}}|{{.CreatedAt}}|'], timeout=3)
    mounts_map = {}
    mt_out = run_cmd(['docker', 'inspect', '-f', '{{.Id}}|{{range .Mounts}}{{.Type}}:{{.Source}}:{{.Destination}};{{end}}', *[x.split('|')[0] for x in (dk_out or '').strip().splitlines()[:25] if x]], timeout=8) if dk_out else ''
    for ml in mt_out.strip().splitlines():
        if '|' not in ml: continue
        mid, mv = ml.split('|', 1)
        vols = []
        for item in mv.split(';'):
            parts = item.split(':')
            if len(parts) >= 3 and parts[0] in ('bind', 'volume'):
                vols.append({'hostPath': parts[1], 'containerPath': ':'.join(parts[2:]), 'type': parts[0]})
        mounts_map[mid[:12]] = vols
    if dk_out:
        for line in dk_out.strip().splitlines()[:25]:
            if not line: continue
            try:
                cid, cname, cimg, cstatus, cstate, cports, ccreated, csize = line.split('|', 7)
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
                        if (h_port or c_port) and not any(x['hostPort'] == (h_port or c_port) and x['containerPort'] == (c_port or h_port) and x['protocol'] == proto for x in parsed_ports):
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
                    'volumes': mounts_map.get(cid[:12], []),
                    'diskUsage': csize,
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
target_dir = '/'
try:
    import stat as stat_mod
    try:
        import pwd, grp
    except Exception:
        pwd, grp = None, None
    target_dir = os.path.abspath(os.path.expanduser('~'))
    if not os.path.exists(target_dir): target_dir = '/'
    entries = sorted(os.listdir(target_dir), key=lambda x: x.lower())[:120]
    for fname in entries:
        fpath = os.path.join(target_dir, fname)
        try:
            is_link = os.path.islink(fpath)
            st = os.stat(fpath) if not is_link else (os.stat(fpath) if os.path.exists(fpath) else os.lstat(fpath))
            is_dir = stat_mod.S_ISDIR(st.st_mode)
            perm_sym = stat_mod.filemode(st.st_mode)
            mode_oct = '0' + oct(stat_mod.S_IMODE(st.st_mode))[-3:].zfill(3)
            mtime_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.st_mtime))
            owner_name = str(st.st_uid)
            group_name = str(st.st_gid)
            if pwd:
                try: owner_name = pwd.getpwuid(st.st_uid).pw_name
                except Exception: pass
            if grp:
                try: group_name = grp.getgrgid(st.st_gid).gr_name
                except Exception: pass
            files.append({
                'name': fname,
                'path': fpath,
                'isDir': is_dir,
                'isSymlink': is_link,
                'linkTarget': os.readlink(fpath) if is_link else None,
                'sizeBytes': st.st_size if not is_dir else 4096,
                'permissions': perm_sym,
                'octal': mode_oct,
                'owner': owner_name,
                'group': group_name,
                'modifiedAt': mtime_str
            })
        except Exception:
            pass
    files.sort(key=lambda item: (not item['isDir'], item['name'].lower()))
except Exception:
    pass
data['cwd'] = target_dir
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
        # 记录主机认证方式缓存 (host_alias -> "password" | "default_key" | "custom_key")
        self._auth_methods: Dict[str, str] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def set_credential(self, host_alias: str, password: Optional[str]):
        if password is not None:
            self._credentials[host_alias] = password
            self._auth_methods[host_alias] = "password"
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
            if client_keys:
                self._auth_methods[host_alias] = "custom_key"
            elif pwd:
                self._auth_methods[host_alias] = "password"
            else:
                self._auth_methods[host_alias] = "default_key"
            return new_conn, None, None
        except asyncssh.PermissionDenied as e:
            self._connections.pop(host_alias, None)
            self._auth_methods[host_alias] = "password" if not client_keys else "custom_key"
            return None, "auth_failed", f"身份认证被拒绝 (Permission denied): {str(e)}"
        except Exception as e:
            # 连接失败清理缓存
            self._connections.pop(host_alias, None)
            err_str = str(e).lower()
            if "permission denied" in err_str or "authentication failed" in err_str or "password auth" in err_str:
                self._auth_methods[host_alias] = "password" if not client_keys else "custom_key"
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
                        "auth_method": self._auth_methods.get(host_alias, "password"),
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
                    "tx_bytes": raw_data["tx_bytes"],
                    "disk_read_bytes": raw_data.get("disk_read_bytes", 0),
                    "disk_write_bytes": raw_data.get("disk_write_bytes", 0)
                }

                cpu_usage = 0
                cpu_cores_usage = []
                net_up_kbps = 0.0
                net_down_kbps = 0.0
                disk_read_kbps = 0.0
                disk_write_kbps = 0.0

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

                    # 磁盘读写吞吐 (KB/s 千字节每秒)
                    d_dr = raw_data.get("disk_read_bytes", 0) - prev_raw.get("disk_read_bytes", 0)
                    d_dw = raw_data.get("disk_write_bytes", 0) - prev_raw.get("disk_write_bytes", 0)
                    if d_dr >= 0:
                        disk_read_kbps = round(d_dr / (1024.0 * dt), 1)
                    if d_dw >= 0:
                        disk_write_kbps = round(d_dw / (1024.0 * dt), 1)
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
                    "diskReadKbps": disk_read_kbps,
                    "diskWriteKbps": disk_write_kbps,
                    "netUpKbps": net_up_kbps,
                    "netDownKbps": net_down_kbps,
                    "uptime": uptime_str,
                    "os": raw_data.get("os", "Linux"),
                    "kernel": raw_data.get("kernel", ""),
                    "firewallBackend": raw_data.get("firewall_backend", "iptables"),
                    "firewallEnabled": bool(raw_data.get("firewall_enabled", False)),
                    "auth_method": self._auth_methods.get(host_alias),
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
                    "auth_method": self._auth_methods.get(host_alias, "password"),
                    "error_type": "auth_failed",
                    "message": err_msg or "密码不对或身份认证被拒绝 (Permission denied)",
                    "host_alias": host_alias,
                    "timestamp": now,
                    "metrics": {
                        "status": "auth_failed",
                        "auth_failed": True,
                        "auth_method": self._auth_methods.get(host_alias, "password"),
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
                    "auth_method": self._auth_methods.get(host_alias),
                    "timestamp": now,
                    "cwd": inspect_data.get("cwd", "/root"),
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
            "auth_method": self._auth_methods.get(host_alias),
            "timestamp": now,
            "metrics": metrics,
            "processes": [],
            "dockerContainers": [],
            "systemdServices": [],
            "cronTasks": [],
            "firewallRules": [],
            "files": []
        }

    async def _run_remote_json_script(self, host_alias: str, py_code: str, payload: Dict[str, Any], timeout: float = 10.0) -> Dict[str, Any]:
        """在远端主机安全执行带 JSON 参数的 Python3 脚本并返回解析后的 JSON 结果"""
        conn, err_type, err_msg = await self._get_connection(host_alias)
        if not conn:
            return {
                "status": "error",
                "error_type": err_type or "connection_error",
                "message": err_msg or "无法建立 SSH 连接"
            }

        b64_payload = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
        full_cmd = f"python3 -c {shlex.quote(py_code)} {shlex.quote(b64_payload)}"
        try:
            res = await conn.run(full_cmd, timeout=timeout)
            out_str = (res.stdout or "").strip()
            if not out_str:
                err_out = (res.stderr or "").strip()
                return {"status": "error", "message": err_out or "远端命令未返回有效数据"}
            # 取最后一行 JSON 输出
            lines = [l for l in out_str.splitlines() if l.strip()]
            return json.loads(lines[-1])
        except Exception as e:
            self._connections.pop(host_alias, None)
            return {"status": "error", "message": str(e)}

    async def remove_docker_container(self, host_alias: str, container: str, force: bool = False, remove_volumes: bool = False) -> Dict[str, Any]:
        """通过单次 SSH 会话删除 Docker 容器（可选强制/同时删除匿名卷）"""
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", container or ""):
            return {"status": "error", "message": "非法容器名称或 ID"}
        conn, err_type, err_msg = await self._get_connection(host_alias)
        if not conn:
            return {"status": "error", "error_type": err_type or "connection_error", "message": err_msg or "无法建立 SSH 连接"}
        flags = ("-f " if force else "") + ("-v " if remove_volumes else "")
        base = f"docker rm {flags}{shlex.quote(container)}"
        try:
            res = await conn.run(f"{base} 2>&1 || sudo -n {base} 2>&1", timeout=30)
            if res.exit_status == 0:
                return {"status": "ok", "message": f"已删除容器 {container}"}
            return {"status": "error", "message": (res.stdout or res.stderr or "删除失败").strip()}
        except Exception as e:
            self._connections.pop(host_alias, None)
            return {"status": "error", "message": str(e)}

    async def list_directory(self, host_alias: str, path: str = "~", show_hidden: bool = True) -> Dict[str, Any]:
        """列出远端指定目录的真实文件列表与权限/大小/所有者/磁盘空间信息"""
        script = r'''
import os, sys, json, base64, stat, time, subprocess
try:
    import pwd, grp
except Exception:
    pwd, grp = None, None

req = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8'))
raw_path = (req.get('path') or '~').strip()
show_hidden = bool(req.get('show_hidden', True))

home_dir = os.path.abspath(os.path.expanduser('~'))
if raw_path == '~' or raw_path == '':
    target_dir = home_dir
elif raw_path.startswith('~/'):
    target_dir = os.path.abspath(os.path.join(home_dir, raw_path[2:]))
else:
    target_dir = os.path.abspath(raw_path)

if not os.path.exists(target_dir):
    print(json.dumps({'status': 'error', 'message': f'目录不存在: {target_dir}', 'cwd': target_dir}))
    sys.exit(0)

if not os.path.isdir(target_dir):
    target_dir = os.path.dirname(target_dir) or '/'

def get_file_entry(fpath, fname):
    is_link = os.path.islink(fpath)
    link_target = None
    if is_link:
        try:
            link_target = os.readlink(fpath)
        except Exception:
            pass
    st = os.stat(fpath) if (not is_link or os.path.exists(fpath)) else os.lstat(fpath)
    is_dir = stat.S_ISDIR(st.st_mode)
    perm_sym = stat.filemode(st.st_mode)
    mode_oct = '0' + oct(stat.S_IMODE(st.st_mode))[-3:].zfill(3)
    mtime_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.st_mtime))
    owner_name = str(st.st_uid)
    group_name = str(st.st_gid)
    if pwd:
        try: owner_name = pwd.getpwuid(st.st_uid).pw_name
        except Exception: pass
    if grp:
        try: group_name = grp.getgrgid(st.st_gid).gr_name
        except Exception: pass
    return {
        'name': fname,
        'path': fpath,
        'isDir': is_dir,
        'isSymlink': is_link,
        'linkTarget': link_target,
        'sizeBytes': st.st_size if not is_dir else 4096,
        'permissions': perm_sym,
        'octal': mode_oct,
        'owner': owner_name,
        'group': group_name,
        'modifiedAt': mtime_str
    }

files = []
try:
    names = os.listdir(target_dir)
    for fname in names:
        if not show_hidden and fname.startswith('.'):
            continue
        fpath = os.path.join(target_dir, fname)
        try:
            files.append(get_file_entry(fpath, fname))
        except Exception:
            pass
except PermissionError:
    # 尝试使用 sudo ls
    try:
        out = subprocess.check_output(['sudo', '-n', 'python3', '-c', f"""
import os, json, stat, time
try:
    import pwd, grp
except Exception:
    pwd, grp = None, None
t = {repr(target_dir)}
sh = {repr(show_hidden)}
res = []
for fn in os.listdir(t):
    if not sh and fn.startswith('.'): continue
    fp = os.path.join(t, fn)
    try:
        il = os.path.islink(fp)
        st = os.stat(fp) if (not il or os.path.exists(fp)) else os.lstat(fp)
        id_ = stat.S_ISDIR(st.st_mode)
        res.append({{
            'name': fn, 'path': fp, 'isDir': id_, 'isSymlink': il,
            'linkTarget': os.readlink(fp) if il else None,
            'sizeBytes': st.st_size if not id_ else 4096,
            'permissions': stat.filemode(st.st_mode),
            'octal': '0' + oct(stat.S_IMODE(st.st_mode))[-3:].zfill(3),
            'owner': pwd.getpwuid(st.st_uid).pw_name if pwd else str(st.st_uid),
            'group': grp.getgrgid(st.st_gid).gr_name if grp else str(st.st_gid),
            'modifiedAt': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.st_mtime))
        }})
    except Exception: pass
print(json.dumps(res))
"""], timeout=4).decode('utf-8')
        files = json.loads(out.strip().splitlines()[-1])
    except Exception as e:
        print(json.dumps({'status': 'error', 'message': f'权限不足，无法读取目录: {target_dir}', 'cwd': target_dir}))
        sys.exit(0)
except Exception as e:
    print(json.dumps({'status': 'error', 'message': str(e), 'cwd': target_dir}))
    sys.exit(0)

files.sort(key=lambda item: (not item['isDir'], item['name'].lower()))

disk_info = None
try:
    sv = os.statvfs(target_dir)
    total_b = sv.f_blocks * sv.f_frsize
    free_b = sv.f_bavail * sv.f_frsize
    used_b = total_b - free_b
    pct = round((used_b / total_b) * 100, 1) if total_b > 0 else 0
    disk_info = {
        'totalBytes': total_b,
        'usedBytes': used_b,
        'freeBytes': free_b,
        'usedPercent': pct
    }
except Exception:
    pass

parent_dir = os.path.dirname(target_dir) if target_dir != '/' else None

print(json.dumps({
    'status': 'ok',
    'cwd': target_dir,
    'parent': parent_dir,
    'home': home_dir,
    'disk': disk_info,
    'files': files
}))
'''
        return await self._run_remote_json_script(host_alias, script, {"path": path, "show_hidden": show_hidden}, timeout=8.0)

    async def analyze_disk_usage(self, host_alias: str, path: str = "~") -> Dict[str, Any]:
        """分析指定目录下各子目录/文件的体积占比 (类 ncdu 可视化)"""
        script = r'''
import os, sys, json, base64, subprocess

req = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8'))
raw_path = (req.get('path') or '~').strip()
home_dir = os.path.abspath(os.path.expanduser('~'))
if raw_path == '~' or raw_path == '':
    target_dir = home_dir
elif raw_path.startswith('~/'):
    target_dir = os.path.abspath(os.path.join(home_dir, raw_path[2:]))
else:
    target_dir = os.path.abspath(raw_path)

if not os.path.isdir(target_dir):
    target_dir = os.path.dirname(target_dir) or '/'

items = []
total_bytes = 0

try:
    # 优先使用 du -sb -x --max-depth=1 (GNU coreutils)
    # -x (--one-file-system) 避免跨越虚拟文件系统（如 /proc, /sys, /dev），避免全盘递归与超时
    p = subprocess.Popen(
        ['du', '-sb', '-x', '--max-depth=1', target_dir],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True
    )
    out, _ = p.communicate(timeout=6)
    if out:
        for line in out.strip().splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[0].isdigit():
                sz = int(parts[0])
                p_path = os.path.abspath(parts[1].strip())
                if p_path == target_dir:
                    total_bytes = sz
                else:
                    items.append({
                        'name': os.path.basename(p_path) or p_path,
                        'path': p_path,
                        'sizeBytes': sz,
                        'isDir': os.path.isdir(p_path)
                    })
except Exception:
    pass

# 若 du 超时或不支持 -sb，回退尝试 Busybox du -d 1 -k -x
if not items:
    try:
        p = subprocess.Popen(
            ['du', '-d', '1', '-k', '-x', target_dir],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True
        )
        out, _ = p.communicate(timeout=6)
        if out:
            for line in out.strip().splitlines():
                parts = line.split(None, 1)
                if len(parts) == 2 and parts[0].isdigit():
                    sz = int(parts[0]) * 1024
                    p_path = os.path.abspath(parts[1].strip())
                    if p_path == target_dir:
                        total_bytes = sz
                    else:
                        items.append({
                            'name': os.path.basename(p_path) or p_path,
                            'path': p_path,
                            'sizeBytes': sz,
                            'isDir': os.path.isdir(p_path)
                        })
    except Exception:
        pass

# 若仍无数据，回退至当前目录直接子项快速统计
is_fallback = False
if not items:
    is_fallback = True
    try:
        for name in os.listdir(target_dir)[:60]:
            fp = os.path.join(target_dir, name)
            try:
                st = os.lstat(fp)
                is_d = os.path.isdir(fp)
                items.append({
                    'name': name,
                    'path': fp,
                    'sizeBytes': st.st_size if not is_d else 0,
                    'isDir': is_d
                })
            except Exception:
                pass
    except Exception:
        pass

sum_items = sum(x['sizeBytes'] for x in items)
if total_bytes < sum_items:
    total_bytes = sum_items

# 重点优化：如果是降级模式，绝不将 inode 元数据 4096 冒充为真实的目录体积
dir_sizes = {} if is_fallback else {item['path']: item['sizeBytes'] for item in items if item.get('isDir')}
dir_sizes_by_name = {} if is_fallback else {item['name']: item['sizeBytes'] for item in items if item.get('isDir')}

items.sort(key=lambda x: x['sizeBytes'], reverse=True)
top_items = items[:8]
for item in top_items:
    item['percent'] = round((item['sizeBytes'] / total_bytes) * 100, 1) if total_bytes > 0 else 0

print(json.dumps({
    'status': 'ok',
    'cwd': target_dir,
    'totalBytes': total_bytes,
    'items': top_items,
    'dirSizes': dir_sizes,
    'dirSizesByName': dir_sizes_by_name
}))
'''
        return await self._run_remote_json_script(host_alias, script, {"path": path}, timeout=8.0)

    async def calculate_single_dir_size(self, host_alias: str, path: str, sudo: bool = False) -> Dict[str, Any]:
        """单独测算指定文件夹的真实磁盘占用 (du -sb / du -sk)"""
        script = r'''
import os, sys, json, base64, subprocess

req = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8'))
raw_path = (req.get('path') or '').strip()
sudo = bool(req.get('sudo', False))
home_dir = os.path.abspath(os.path.expanduser('~'))
if raw_path == '~' or raw_path == '':
    target_dir = home_dir
elif raw_path.startswith('~/'):
    target_dir = os.path.abspath(os.path.join(home_dir, raw_path[2:]))
else:
    target_dir = os.path.abspath(raw_path)

if not os.path.exists(target_dir):
    print(json.dumps({'status': 'error', 'message': f'路径不存在: {target_dir}'}))
    sys.exit(0)

size_bytes = 0
prefix = ['sudo', '-n'] if sudo else []

# 优先使用 du -sb -x (GNU)
try:
    cmd = prefix + ['du', '-sb', '-x', target_dir]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True)
    out, _ = p.communicate(timeout=6)
    if out:
        parts = out.strip().splitlines()[-1].split(None, 1)
        if parts and parts[0].isdigit():
            size_bytes = int(parts[0])
except Exception:
    pass

# 回退尝试 du -sk -x (BusyBox / BSD)
if size_bytes == 0:
    try:
        cmd = prefix + ['du', '-sk', '-x', target_dir]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True)
        out, _ = p.communicate(timeout=6)
        if out:
            parts = out.strip().splitlines()[-1].split(None, 1)
            if parts and parts[0].isdigit():
                size_bytes = int(parts[0]) * 1024
    except Exception:
        pass

print(json.dumps({
    'status': 'ok',
    'path': target_dir,
    'sizeBytes': size_bytes
}))
'''
        return await self._run_remote_json_script(host_alias, script, {"path": path, "sudo": sudo}, timeout=8.0)

    async def read_file_content(self, host_alias: str, path: str) -> Dict[str, Any]:
        """读取远端文本文件内容，支持无权限时自动尝试 sudo -n 读取"""
        script = r'''
import os, sys, json, base64, stat, time, subprocess
try:
    import pwd, grp
except Exception:
    pwd, grp = None, None

req = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8'))
target_path = os.path.abspath(os.path.expanduser(req.get('path', '')))

if not os.path.exists(target_path):
    print(json.dumps({'status': 'error', 'message': f'文件不存在: {target_path}'}))
    sys.exit(0)

if os.path.isdir(target_path):
    print(json.dumps({'status': 'error', 'message': f'目标是目录而非文件: {target_path}'}))
    sys.exit(0)

MAX_BYTES = 2 * 1024 * 1024  # 2MB 保护上限
raw_bytes = None
used_sudo = False

try:
    st = os.stat(target_path)
    if st.st_size > MAX_BYTES:
        print(json.dumps({
            'status': 'error',
            'message': f'文件体积过大 ({round(st.st_size / 1048576, 2)} MB > 2 MB)，请使用「下载」功能查看或通过终端 tail 查看'
        }))
        sys.exit(0)
    with open(target_path, 'rb') as f:
        raw_bytes = f.read(MAX_BYTES + 1)
except PermissionError:
    try:
        raw_bytes = subprocess.check_output(['sudo', '-n', 'cat', target_path], timeout=5)
        used_sudo = True
    except Exception as e:
        print(json.dumps({'status': 'error', 'message': f'权限不足且免密 sudo 读取失败: {target_path}'}))
        sys.exit(0)
except Exception as e:
    print(json.dumps({'status': 'error', 'message': str(e)}))
    sys.exit(0)

if len(raw_bytes) > MAX_BYTES:
    print(json.dumps({'status': 'error', 'message': '文件体积超过 2MB 在线编辑上限，请下载后查看'}))
    sys.exit(0)

# 检测是否为二进制文件
if b'\x00' in raw_bytes[:8192]:
    print(json.dumps({
        'status': 'error',
        'isBinary': True,
        'message': '检测到二进制文件，不支持文本在线编辑，请使用下载功能'
    }))
    sys.exit(0)

content_str = raw_bytes.decode('utf-8', errors='replace')
try:
    st = os.stat(target_path)
    perm_sym = stat.filemode(st.st_mode)
    mode_oct = '0' + oct(stat.S_IMODE(st.st_mode))[-3:].zfill(3)
    mtime_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.st_mtime))
    owner_name = pwd.getpwuid(st.st_uid).pw_name if pwd else str(st.st_uid)
    group_name = grp.getgrgid(st.st_gid).gr_name if grp else str(st.st_gid)
    size_b = st.st_size
except Exception:
    perm_sym = '-rw-r--r--'
    mode_oct = '0644'
    mtime_str = ''
    owner_name = 'root'
    group_name = 'root'
    size_b = len(raw_bytes)

print(json.dumps({
    'status': 'ok',
    'path': target_path,
    'content': content_str,
    'sizeBytes': size_b,
    'permissions': perm_sym,
    'octal': mode_oct,
    'owner': owner_name,
    'group': group_name,
    'modifiedAt': mtime_str,
    'usedSudo': used_sudo
}))
'''
        return await self._run_remote_json_script(host_alias, script, {"path": path}, timeout=8.0)

    async def write_file_content(self, host_alias: str, path: str, content: str, sudo_write: bool = False) -> Dict[str, Any]:
        """将文本内容保存至远端服务器文件，支持直接写入或 sudo tee 提权写入"""
        script = r'''
import os, sys, json, base64, stat, time, subprocess
try:
    import pwd, grp
except Exception:
    pwd, grp = None, None

req = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8'))
target_path = os.path.abspath(os.path.expanduser(req.get('path', '')))
content = req.get('content', '')
sudo_write = bool(req.get('sudo_write', False))
raw_bytes = content.encode('utf-8')

wrote = False
err_detail = ''

if not sudo_write:
    try:
        parent = os.path.dirname(target_path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)
        with open(target_path, 'wb') as f:
            f.write(raw_bytes)
        wrote = True
    except PermissionError as e:
        sudo_write = True
        err_detail = str(e)
    except Exception as e:
        print(json.dumps({'status': 'error', 'message': f'写入失败: {str(e)}'}))
        sys.exit(0)

if not wrote and sudo_write:
    try:
        parent = os.path.dirname(target_path)
        if parent and not os.path.exists(parent):
            subprocess.run(['sudo', '-n', 'mkdir', '-p', parent], check=True, timeout=4)
        p = subprocess.Popen(
            ['sudo', '-n', 'tee', target_path],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )
        _, stderr_bytes = p.communicate(input=raw_bytes, timeout=6)
        if p.returncode != 0:
            raise RuntimeError(stderr_bytes.decode('utf-8', errors='replace').strip() or 'sudo tee failed')
        wrote = True
    except Exception as e:
        print(json.dumps({'status': 'error', 'message': f'提权写入失败: {str(e)} ({err_detail})'}))
        sys.exit(0)

try:
    st = os.stat(target_path)
    perm_sym = stat.filemode(st.st_mode)
    mode_oct = '0' + oct(stat.S_IMODE(st.st_mode))[-3:].zfill(3)
    mtime_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.st_mtime))
    owner_name = pwd.getpwuid(st.st_uid).pw_name if pwd else str(st.st_uid)
    group_name = grp.getgrgid(st.st_gid).gr_name if grp else str(st.st_gid)
    file_entry = {
        'name': os.path.basename(target_path),
        'path': target_path,
        'isDir': False,
        'sizeBytes': st.st_size,
        'permissions': perm_sym,
        'octal': mode_oct,
        'owner': owner_name,
        'group': group_name,
        'modifiedAt': mtime_str
    }
except Exception:
    file_entry = None

print(json.dumps({
    'status': 'ok',
    'path': target_path,
    'file': file_entry,
    'message': f'已成功保存文件 {target_path}'
}))
'''
        return await self._run_remote_json_script(
            host_alias,
            script,
            {"path": path, "content": content, "sudo_write": sudo_write},
            timeout=10.0
        )

    async def create_directory(self, host_alias: str, path: str, mode: str = "0755", sudo: bool = False) -> Dict[str, Any]:
        """在远端服务器新建文件夹 (mkdir -p)"""
        script = r'''
import os, sys, json, base64, subprocess

req = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8'))
target_path = os.path.abspath(os.path.expanduser(req.get('path', '')))
mode_str = req.get('mode', '0755').strip()
use_sudo = bool(req.get('sudo', False))

try:
    mode_int = int(mode_str[-3:], 8)
except Exception:
    mode_int = 0o755

try:
    if not use_sudo:
        os.makedirs(target_path, mode=mode_int, exist_ok=True)
        os.chmod(target_path, mode_int)
    else:
        subprocess.run(['sudo', '-n', 'mkdir', '-p', '-m', mode_str[-3:], target_path], check=True, timeout=5)
    print(json.dumps({'status': 'ok', 'path': target_path, 'message': f'已创建目录 {target_path}'}))
except PermissionError:
    try:
        subprocess.run(['sudo', '-n', 'mkdir', '-p', '-m', mode_str[-3:], target_path], check=True, timeout=5)
        print(json.dumps({'status': 'ok', 'path': target_path, 'message': f'已通过 sudo 创建目录 {target_path}'}))
    except Exception as e:
        print(json.dumps({'status': 'error', 'message': f'权限不足，创建目录失败: {str(e)}'}))
except Exception as e:
    print(json.dumps({'status': 'error', 'message': f'创建目录失败: {str(e)}'}))
'''
        return await self._run_remote_json_script(host_alias, script, {"path": path, "mode": mode, "sudo": sudo}, timeout=8.0)

    async def create_file(self, host_alias: str, path: str, content: str = "", sudo: bool = False) -> Dict[str, Any]:
        """在远端服务器新建文件"""
        return await self.write_file_content(host_alias, path, content, sudo_write=sudo)

    async def rename_path(self, host_alias: str, old_path: str, new_path: str, sudo: bool = False) -> Dict[str, Any]:
        """重命名或移动远端文件/目录"""
        script = r'''
import os, sys, json, base64, shutil, subprocess

req = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8'))
old_p = os.path.abspath(os.path.expanduser(req.get('old_path', '')))
new_p = os.path.abspath(os.path.expanduser(req.get('new_path', '')))
use_sudo = bool(req.get('sudo', False))

if not os.path.exists(old_p) and not os.path.islink(old_p):
    print(json.dumps({'status': 'error', 'message': f'源路径不存在: {old_p}'}))
    sys.exit(0)

try:
    if not use_sudo:
        shutil.move(old_p, new_p)
    else:
        subprocess.run(['sudo', '-n', 'mv', old_p, new_p], check=True, timeout=5)
    print(json.dumps({'status': 'ok', 'old_path': old_p, 'new_path': new_p, 'message': f'已重命名/移动至 {new_p}'}))
except PermissionError:
    try:
        subprocess.run(['sudo', '-n', 'mv', old_p, new_p], check=True, timeout=5)
        print(json.dumps({'status': 'ok', 'old_path': old_p, 'new_path': new_p, 'message': f'已通过 sudo 重命名/移动至 {new_p}'}))
    except Exception as e:
        print(json.dumps({'status': 'error', 'message': f'权限不足，重命名失败: {str(e)}'}))
except Exception as e:
    print(json.dumps({'status': 'error', 'message': f'重命名失败: {str(e)}'}))
'''
        return await self._run_remote_json_script(
            host_alias, script, {"old_path": old_path, "new_path": new_path, "sudo": sudo}, timeout=8.0
        )

    async def copy_path(self, host_alias: str, src_path: str, dest_path: str, sudo: bool = False) -> Dict[str, Any]:
        """复制远端文件或目录"""
        script = r'''
import os, sys, json, base64, shutil, subprocess

req = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8'))
src_p = os.path.abspath(os.path.expanduser(req.get('src_path', '')))
dest_p = os.path.abspath(os.path.expanduser(req.get('dest_path', '')))
use_sudo = bool(req.get('sudo', False))

if not os.path.exists(src_p):
    print(json.dumps({'status': 'error', 'message': f'源路径不存在: {src_p}'}))
    sys.exit(0)

if src_p == dest_p:
    base, ext = os.path.splitext(dest_p)
    dest_p = f"{base}_copy{ext}"

try:
    if not use_sudo:
        if os.path.isdir(src_p):
            shutil.copytree(src_p, dest_p)
        else:
            shutil.copy2(src_p, dest_p)
    else:
        subprocess.run(['sudo', '-n', 'cp', '-a', src_p, dest_p], check=True, timeout=10)
    print(json.dumps({'status': 'ok', 'src_path': src_p, 'dest_path': dest_p, 'message': f'已复制至 {dest_p}'}))
except PermissionError:
    try:
        subprocess.run(['sudo', '-n', 'cp', '-a', src_p, dest_p], check=True, timeout=10)
        print(json.dumps({'status': 'ok', 'src_path': src_p, 'dest_path': dest_p, 'message': f'已通过 sudo 复制至 {dest_p}'}))
    except Exception as e:
        print(json.dumps({'status': 'error', 'message': f'权限不足，复制失败: {str(e)}'}))
except Exception as e:
    print(json.dumps({'status': 'error', 'message': f'复制失败: {str(e)}'}))
'''
        return await self._run_remote_json_script(
            host_alias, script, {"src_path": src_path, "dest_path": dest_path, "sudo": sudo}, timeout=12.0
        )

    async def delete_paths(self, host_alias: str, paths: List[str], sudo: bool = False) -> Dict[str, Any]:
        """安全删除远端文件或目录（内置系统根目录防误删保护）"""
        script = r'''
import os, sys, json, base64, shutil, subprocess

req = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8'))
raw_paths = req.get('paths', [])
use_sudo = bool(req.get('sudo', False))

PROTECTED = {'/', '/bin', '/boot', '/dev', '/etc', '/home', '/lib', '/lib64', '/opt', '/proc', '/root', '/run', '/sbin', '/srv', '/sys', '/tmp', '/usr', '/var'}

deleted = []
errors = []

for rp in raw_paths:
    tp = os.path.abspath(os.path.expanduser(rp))
    if tp in PROTECTED:
        errors.append(f'拒绝删除系统核心保护目录: {tp}')
        continue
    if not os.path.exists(tp) and not os.path.islink(tp):
        errors.append(f'路径不存在: {tp}')
        continue
    try:
        if not use_sudo:
            if os.path.islink(tp) or os.path.isfile(tp):
                os.unlink(tp)
            elif os.path.isdir(tp):
                shutil.rmtree(tp)
            else:
                os.remove(tp)
        else:
            subprocess.run(['sudo', '-n', 'rm', '-rf', tp], check=True, timeout=8)
        deleted.append(tp)
    except PermissionError:
        try:
            subprocess.run(['sudo', '-n', 'rm', '-rf', tp], check=True, timeout=8)
            deleted.append(tp)
        except Exception as e:
            errors.append(f'{tp}: 权限不足 ({str(e)})')
    except Exception as e:
        errors.append(f'{tp}: {str(e)}')

if errors and not deleted:
    print(json.dumps({'status': 'error', 'message': '; '.join(errors), 'deleted': deleted}))
else:
    print(json.dumps({
        'status': 'ok',
        'deleted': deleted,
        'errors': errors,
        'message': f'已成功删除 {len(deleted)} 个项目'
    }))
'''
        return await self._run_remote_json_script(
            host_alias, script, {"paths": paths, "sudo": sudo}, timeout=12.0
        )

    async def chmod_path(
        self,
        host_alias: str,
        path: str,
        octal: str,
        recursive: bool = False,
        owner: Optional[str] = None,
        group: Optional[str] = None,
        sudo: bool = False
    ) -> Dict[str, Any]:
        """修改远端文件/目录的权限 (chmod) 与所有者 (chown)"""
        script = r'''
import os, sys, json, base64, stat, time, subprocess
try:
    import pwd, grp
except Exception:
    pwd, grp = None, None

req = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8'))
target_path = os.path.abspath(os.path.expanduser(req.get('path', '')))
octal_str = (req.get('octal') or '0644').strip()
recursive = bool(req.get('recursive', False))
owner = req.get('owner')
group = req.get('group')
use_sudo = bool(req.get('sudo', False))

if not os.path.exists(target_path):
    print(json.dumps({'status': 'error', 'message': f'目标不存在: {target_path}'}))
    sys.exit(0)

mode_clean = octal_str[-3:] if len(octal_str) >= 3 else octal_str

def run_chmod(with_sudo):
    cmd = (['sudo', '-n'] if with_sudo else []) + ['chmod']
    if recursive:
        cmd.append('-R')
    cmd.extend([mode_clean, target_path])
    subprocess.run(cmd, check=True, timeout=8)

    if owner or group:
        own_spec = f"{owner or ''}:{group or ''}".strip(':')
        if own_spec:
            chown_cmd = (['sudo', '-n'] if with_sudo else []) + ['chown']
            if recursive:
                chown_cmd.append('-R')
            chown_cmd.extend([own_spec, target_path])
            subprocess.run(chown_cmd, check=True, timeout=8)

try:
    run_chmod(use_sudo)
except Exception as e:
    if not use_sudo:
        try:
            run_chmod(True)
        except Exception as e2:
            print(json.dumps({'status': 'error', 'message': f'修改权限失败: {str(e2)}'}))
            sys.exit(0)
    else:
        print(json.dumps({'status': 'error', 'message': f'修改权限失败: {str(e)}'}))
        sys.exit(0)

st = os.stat(target_path)
perm_sym = stat.filemode(st.st_mode)
mode_oct = '0' + oct(stat.S_IMODE(st.st_mode))[-3:].zfill(3)
mtime_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.st_mtime))
owner_name = pwd.getpwuid(st.st_uid).pw_name if pwd else str(st.st_uid)
group_name = grp.getgrgid(st.st_gid).gr_name if grp else str(st.st_gid)

print(json.dumps({
    'status': 'ok',
    'path': target_path,
    'permissions': perm_sym,
    'octal': mode_oct,
    'owner': owner_name,
    'group': group_name,
    'modifiedAt': mtime_str,
    'message': f'已成功将 {target_path} 权限更新为 {mode_oct} ({perm_sym})'
}))
'''
        return await self._run_remote_json_script(
            host_alias,
            script,
            {
                "path": path,
                "octal": octal,
                "recursive": recursive,
                "owner": owner,
                "group": group,
                "sudo": sudo
            },
            timeout=10.0
        )

    async def archive_paths(
        self,
        host_alias: str,
        paths: List[str],
        output_path: Optional[str] = None,
        target_dir: Optional[str] = None,
        action: str = "compress",
        sudo: bool = False
    ) -> Dict[str, Any]:
        """在远端打包压缩 (.tar.gz) 或解压归档文件 (.tar.gz / .tgz / .tar / .zip)"""
        script = r'''
import os, sys, json, base64, time, subprocess

req = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8'))
raw_paths = req.get('paths', [])
output_path = req.get('output_path')
target_dir = req.get('target_dir')
action = req.get('action', 'compress')
use_sudo = bool(req.get('sudo', False))

prefix = ['sudo', '-n'] if use_sudo else []

if action == 'extract':
    if not raw_paths:
        print(json.dumps({'status': 'error', 'message': '未指定要解压的归档文件'}))
        sys.exit(0)
    archive_file = os.path.abspath(os.path.expanduser(raw_paths[0]))
    if not os.path.exists(archive_file):
        print(json.dumps({'status': 'error', 'message': f'归档文件不存在: {archive_file}'}))
        sys.exit(0)
    dest_dir = os.path.abspath(os.path.expanduser(target_dir)) if target_dir else os.path.dirname(archive_file)
    try:
        low = archive_file.lower()
        if low.endswith('.zip'):
            cmd = prefix + ['unzip', '-o', archive_file, '-d', dest_dir]
        elif low.endswith('.tar.gz') or low.endswith('.tgz'):
            cmd = prefix + ['tar', '-xzf', archive_file, '-C', dest_dir]
        elif low.endswith('.tar.bz2') or low.endswith('.tbz2'):
            cmd = prefix + ['tar', '-xjf', archive_file, '-C', dest_dir]
        elif low.endswith('.tar.xz') or low.endswith('.txz'):
            cmd = prefix + ['tar', '-xJf', archive_file, '-C', dest_dir]
        elif low.endswith('.tar'):
            cmd = prefix + ['tar', '-xf', archive_file, '-C', dest_dir]
        else:
            cmd = prefix + ['tar', '-xf', archive_file, '-C', dest_dir]
        subprocess.run(cmd, check=True, timeout=25)
        print(json.dumps({'status': 'ok', 'target_dir': dest_dir, 'message': f'已成功解压 {os.path.basename(archive_file)} 至 {dest_dir}'}))
    except Exception as e:
        print(json.dumps({'status': 'error', 'message': f'解压失败: {str(e)}'}))
else:
    if not raw_paths:
        print(json.dumps({'status': 'error', 'message': '未指定要打包的路径'}))
        sys.exit(0)
    abs_paths = [os.path.abspath(os.path.expanduser(p)) for p in raw_paths]
    base_dir = os.path.dirname(abs_paths[0]) if len(abs_paths) == 1 and not os.path.isdir(abs_paths[0]) else (
        os.path.dirname(abs_paths[0].rstrip('/')) if len(abs_paths) == 1 else os.path.commonpath(abs_paths)
    )
    if not base_dir:
        base_dir = '/'
    if not output_path:
        ts = time.strftime('%Y%m%d_%H%M%S')
        first_name = os.path.basename(abs_paths[0].rstrip('/')) or 'root'
        out_dir = os.path.dirname(abs_paths[0].rstrip('/')) if len(abs_paths) == 1 else base_dir
        if not out_dir or out_dir == '/':
            out_dir = '/tmp'
        output_path = os.path.join(out_dir, f"{first_name}_{ts}.tar.gz")
    else:
        output_path = os.path.abspath(os.path.expanduser(output_path))
        if not output_path.endswith('.tar.gz') and not output_path.endswith('.tgz'):
            output_path += '.tar.gz'

    rel_names = [os.path.relpath(p, base_dir) for p in abs_paths]
    cmd = prefix + ['tar', '-czf', output_path, '-C', base_dir] + rel_names
    try:
        subprocess.run(cmd, check=True, timeout=30)
        print(json.dumps({
            'status': 'ok',
            'output_path': output_path,
            'message': f'已成功打包生成 {output_path}'
        }))
    except Exception as e:
        print(json.dumps({'status': 'error', 'message': f'打包失败: {str(e)}'}))
'''
        return await self._run_remote_json_script(
            host_alias,
            script,
            {
                "paths": paths,
                "output_path": output_path,
                "target_dir": target_dir,
                "action": action,
                "sudo": sudo
            },
            timeout=35.0
        )

    async def upload_file(self, host_alias: str, remote_path: str, data: bytes, sudo: bool = False) -> Dict[str, Any]:
        """通过 SSH 管道将本地上传的二进制/文本文件流式写入远端目标路径"""
        conn, err_type, err_msg = await self._get_connection(host_alias)
        if not conn:
            return {"status": "error", "message": err_msg or "无法建立 SSH 连接"}

        q_path = shlex.quote(remote_path)
        cmd = f"sudo -n tee {q_path} > /dev/null" if sudo else f"cat > {q_path}"
        try:
            res = await conn.run(cmd, input=data, encoding=None, timeout=60.0)
            if res.exit_status != 0 and not sudo:
                # 自动尝试 sudo tee
                res2 = await conn.run(f"sudo -n tee {q_path} > /dev/null", input=data, encoding=None, timeout=60.0)
                if res2.exit_status != 0:
                    err_txt = (res2.stderr or b"").decode("utf-8", errors="replace").strip()
                    return {"status": "error", "message": f"上传写入失败: {err_txt}"}
            elif res.exit_status != 0:
                err_txt = (res.stderr or b"").decode("utf-8", errors="replace").strip()
                return {"status": "error", "message": f"上传写入失败: {err_txt}"}

            return {
                "status": "ok",
                "path": remote_path,
                "sizeBytes": len(data),
                "message": f"文件已成功上传至 {remote_path} ({round(len(data) / 1024, 1)} KB)"
            }
        except Exception as e:
            return {"status": "error", "message": f"上传异常: {str(e)}"}

    async def download_file(self, host_alias: str, remote_path: str) -> tuple[Optional[bytes], Optional[str], Optional[str]]:
        """从远端下载文件（若目标是文件夹则自动流式打包为 .tar.gz 下载）"""
        conn, err_type, err_msg = await self._get_connection(host_alias)
        if not conn:
            return None, None, err_msg or "无法建立 SSH 连接"

        # 先检查目标类型
        check_res = await self._run_remote_json_script(
            host_alias,
            r'''
import os, sys, json, base64
req = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8'))
p = os.path.abspath(os.path.expanduser(req.get('path', '')))
if not os.path.exists(p):
    print(json.dumps({'status': 'error', 'message': f'文件不存在: {p}'}))
else:
    print(json.dumps({
        'status': 'ok',
        'path': p,
        'isDir': os.path.isdir(p),
        'name': os.path.basename(p.rstrip('/')) or 'root'
    }))
''',
            {"path": remote_path},
            timeout=5.0
        )
        if check_res.get("status") != "ok":
            return None, None, check_res.get("message", "目标文件不存在")

        abs_path = check_res["path"]
        is_dir = check_res["isDir"]
        base_name = check_res["name"]
        q_path = shlex.quote(abs_path)

        try:
            if is_dir:
                parent_dir = shlex.quote(os.path.dirname(abs_path.rstrip("/")) or "/")
                dir_name = shlex.quote(base_name)
                cmd = f"tar -czf - -C {parent_dir} {dir_name} 2>/dev/null || sudo -n tar -czf - -C {parent_dir} {dir_name}"
                res = await conn.run(cmd, encoding=None, timeout=60.0)
                if res.exit_status != 0 or not res.stdout:
                    return None, None, "打包下载目录失败"
                return res.stdout, f"{base_name}.tar.gz", None
            else:
                cmd = f"cat {q_path} 2>/dev/null || sudo -n cat {q_path}"
                res = await conn.run(cmd, encoding=None, timeout=60.0)
                if res.exit_status != 0 and res.stdout is None:
                    return None, None, "读取远端文件失败"
                return res.stdout or b"", base_name, None
        except Exception as e:
            return None, None, str(e)

    async def download_batch(self, host_alias: str, paths: List[str]) -> tuple[Optional[bytes], Optional[str], Optional[str]]:
        """批量下载远端多个文件或文件夹（自动打包为 .tar.gz 流式传输）"""
        if not paths:
            return None, None, "未指定下载文件路径"
        if len(paths) == 1:
            return await self.download_file(host_alias, paths[0])

        conn, err_type, err_msg = await self._get_connection(host_alias)
        if not conn:
            return None, None, err_msg or "无法建立 SSH 连接"

        norm_paths = [os.path.abspath(os.path.expanduser(p)) for p in paths]
        parent_dir = os.path.dirname(norm_paths[0]) or "/"
        all_same_parent = all((os.path.dirname(p) or "/") == parent_dir for p in norm_paths)

        if all_same_parent:
            names = [shlex.quote(os.path.basename(p)) for p in norm_paths]
            q_parent = shlex.quote(parent_dir)
            names_str = " ".join(names)
            cmd = f"tar -czf - -C {q_parent} {names_str} 2>/dev/null || sudo -n tar -czf - -C {q_parent} {names_str}"
        else:
            q_paths = " ".join(shlex.quote(p.lstrip("/")) for p in norm_paths)
            cmd = f"tar -czf - -C / {q_paths} 2>/dev/null || sudo -n tar -czf - -C / {q_paths}"

        ts = time.strftime("%Y%m%d_%H%M%S")
        out_name = f"batch_{len(norm_paths)}items_{ts}.tar.gz"
        try:
            res = await conn.run(cmd, encoding=None, timeout=120.0)
            if res.exit_status != 0 or not res.stdout:
                return None, None, "批量打包下载失败或部分路径无读取权限"
            return res.stdout, out_name, None
        except Exception as e:
            return None, None, str(e)

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
