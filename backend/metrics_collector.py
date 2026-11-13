import re
import os
import time
import json
import base64
import shlex
import asyncio
import ipaddress
from typing import Optional, Dict, Any, List, Tuple
import asyncssh

from ssh_config_parser import find_host_by_alias
from models import (
    DockerContainerInfo,
    ProcessSignalPayload,
    FirewallRuleCreatePayload,
    FirewallRuleDeletePayload,
)
from process_manager import PROCESS_LIST_CODE, PROCESS_SIGNAL_CODE

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

# 1. 服务器时区：crontab 按服务器本地时区触发，前端据此换算为北京时间
def read_timezone():
    tz_name = ''
    try:
        with open('/etc/timezone') as tz_file:
            tz_name = tz_file.read().strip()
    except Exception:
        tz_name = ''
    if not tz_name:
        try:
            link = os.path.realpath('/etc/localtime')
            if 'zoneinfo/' in link:
                tz_name = link.split('zoneinfo/', 1)[1]
        except Exception:
            tz_name = ''
    tz_offset = ''
    try:
        tz_offset = time.strftime('%z') or ''
    except Exception:
        tz_offset = ''
    if not tz_offset:
        minutes = -time.timezone // 60
        sign = '-' if minutes < 0 else '+'
        tz_offset = sign + '%02d%02d' % (abs(minutes) // 60, abs(minutes) % 60)
    try:
        tz_abbr = time.strftime('%Z') or tz_offset
    except Exception:
        tz_abbr = tz_offset
    return {'name': tz_name or 'unknown', 'abbreviation': tz_abbr, 'utcOffset': tz_offset}

data['timezone'] = read_timezone()

# PROCESS_LIST_CODE

# 2. Docker 容器列表 (Docker Containers)
containers = []
if shutil.which('docker'):
    dk_out = run_cmd(['docker', 'ps', '-a', '--no-trunc', '--format', '{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}|{{.State}}|{{.Ports}}|{{.CreatedAt}}|{{.Size}}'], timeout=10)
    if not dk_out:
        dk_out = run_cmd(['docker', 'ps', '-a', '--no-trunc', '--format', '{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}|{{.State}}|{{.Ports}}|{{.CreatedAt}}|'], timeout=3)
    # Project only operational fields: never collect Env, command arguments or arbitrary labels.
    inspect_fields = [
        '.Id', '.Created', '.State.StartedAt', '.State.FinishedAt', '.State.ExitCode',
        '.State.OOMKilled', '.RestartCount', '.HostConfig.NetworkMode',
        '.HostConfig.RestartPolicy', '.HostConfig.Memory', '.HostConfig.NanoCpus',
        '.HostConfig.CpuQuota', '.HostConfig.CpuPeriod', '.HostConfig.CpusetCpus',
        '.HostConfig.Privileged', '.HostConfig.ReadonlyRootfs', '.Config.User',
        '.Mounts', '.NetworkSettings.Networks', '.NetworkSettings.Ports',
        '.Config.ExposedPorts',
        'composeProject', 'composeService',
        '.HostConfig.PortBindings', '.HostConfig.Tmpfs'
    ]
    templates = []
    for field in inspect_fields:
        if field.startswith('.'):
            # index tolerates absent optional keys (Tmpfs, ExposedPorts, etc.).
            keys = ' '.join(json.dumps(key) for key in field[1:].split('.'))
            templates.append('{{json (index . ' + keys + ')}}')
        else:
            label = 'com.docker.compose.' + ('project' if field == 'composeProject' else 'service')
            templates.append('{{with (index .Config ' + json.dumps('Labels') + ')}}{{json (index . ' + json.dumps(label) + ')}}{{else}}null{{end}}')
    inspect_format = '[' + ','.join(templates)
    inspect_format += ',{{with (index .State \"Health\")}}{{json .Status}}{{else}}null{{end}}]'
    ids = [x.split('|')[0] for x in (dk_out or '').strip().splitlines()[:25] if x]
    inspect_out = run_cmd(['docker', 'inspect', '--format', inspect_format, *ids], timeout=3) if ids else ''
    details_map = {}
    for detail_line in inspect_out.splitlines():
        try:
            values = json.loads(detail_line)
            detail = dict(zip(inspect_fields + ['health'], values))
            details_map[detail['.Id']] = detail
        except (ValueError, TypeError, KeyError):
            continue
    if dk_out:
        for line in dk_out.strip().splitlines()[:25]:
            if not line: continue
            try:
                cid, cname, cimg, cstatus, cstate, cports, ccreated, csize = line.split('|', 7)
                detail = details_map.get(cid, {})
                parsed_ports = []
                if detail:
                    bindings = detail.get('.NetworkSettings.Ports') or detail.get('.HostConfig.PortBindings') or {}
                    exposed = detail.get('.Config.ExposedPorts') or {}
                    for port_key in sorted(set(bindings) | set(exposed)):
                        port, proto = port_key.split('/', 1)
                        if proto not in ('tcp', 'udp', 'sctp'): continue
                        for binding in bindings.get(port_key) or [None]:
                            parsed_ports.append({
                                'hostPort': int(binding.get('HostPort') or 0) if binding else 0,
                                'hostIp': binding.get('HostIp', '') if binding else '',
                                'containerPort': int(port), 'protocol': proto
                            })
                elif cports:
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
                            proto = right.split('/')[-1] if '/' in right else 'tcp'
                        elif '/' in p:
                            c_part = p.split('/')[0]
                            if c_part.isdigit(): c_port = int(c_part)
                            proto = p.split('/')[-1]
                        if (h_port or c_port) and not any(x['hostPort'] == h_port and x['containerPort'] == (c_port or h_port) and x['protocol'] == proto for x in parsed_ports):
                            parsed_ports.append({
                                'hostPort': h_port,
                                'containerPort': c_port or h_port,
                                'protocol': proto
                            })
                restart = detail.get('.HostConfig.RestartPolicy') or {}
                nanos = detail.get('.HostConfig.NanoCpus') or 0
                quota = detail.get('.HostConfig.CpuQuota') or 0
                period = detail.get('.HostConfig.CpuPeriod') or 100000
                cpu_limit = nanos / 1e9 if nanos > 0 else (quota / period if quota > 0 else 0)
                volumes = [{
                    'hostPath': m.get('Source', ''), 'containerPath': m.get('Destination', ''),
                    'type': m.get('Type', ''), 'readOnly': not m.get('RW', True)
                } for m in detail.get('.Mounts') or []]
                for destination, options in (detail.get('.HostConfig.Tmpfs') or {}).items():
                    if not any(v['containerPath'] == destination for v in volumes):
                        volumes.append({'hostPath': '', 'containerPath': destination, 'type': 'tmpfs', 'readOnly': 'ro' in options.split(',')})
                containers.append({
                    'id': cid[:12],
                    'name': cname,
                    'image': cimg,
                    'status': cstate.lower() if cstate.lower() in ('running', 'exited', 'restarting', 'created', 'paused', 'removing', 'dead') else 'unknown',
                    'ports': parsed_ports,
                    'volumes': volumes,
                    'diskUsage': csize,
                    'createdAt': detail.get('.Created') or ccreated,
                    'detailsAvailable': bool(detail),
                    'networkMode': detail.get('.HostConfig.NetworkMode'),
                    'networks': [{
                        'name': name, 'ipAddress': net.get('IPAddress', ''),
                        'ipv6Address': net.get('GlobalIPv6Address', '')
                    } for name, net in (detail.get('.NetworkSettings.Networks') or {}).items()],
                    'restartPolicy': restart.get('Name') if detail else None,
                    'restartMaxRetries': restart.get('MaximumRetryCount') if detail else None,
                    'restartCount': detail.get('.RestartCount'),
                    'healthStatus': detail.get('health'),
                    'startedAt': detail.get('.State.StartedAt'),
                    'finishedAt': detail.get('.State.FinishedAt'),
                    'exitCode': detail.get('.State.ExitCode'),
                    'oomKilled': detail.get('.State.OOMKilled'),
                    'memoryLimitBytes': detail.get('.HostConfig.Memory'),
                    'cpuLimit': cpu_limit if detail else None,
                    'cpusetCpus': detail.get('.HostConfig.CpusetCpus'),
                    'privileged': detail.get('.HostConfig.Privileged'),
                    'readOnlyRootfs': detail.get('.HostConfig.ReadonlyRootfs'),
                    'runUser': detail.get('.Config.User'),
                    'composeProject': detail.get('composeProject') or None,
                    'composeService': detail.get('composeService') or None
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
import base64, hashlib, datetime, getpass
def cron_id(raw):
    return 'cron-' + hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]
def cron_title(value):
    try:
        return base64.b64decode(value.encode('ascii')).decode('utf-8')
    except Exception:
        return ''
def cron_task(raw, enabled=True, title='', idx=1):
    parts = raw.split(None, 1)
    if not parts: return None
    if parts[0].startswith('@'):
        expr, cmd = parts[0], parts[1] if len(parts) > 1 else ''
    else:
        fields = raw.split(None, 5)
        if len(fields) < 6: return None
        expr, cmd = ' '.join(fields[:5]), fields[5]
    if not cmd: return None
    title = title or f'定时计划任务 #{idx}'
    return {
        'id': cron_id(raw), 'engine': 'crontab', 'title': title,
        'expression': expr, 'command': cmd,
        'scriptPath': cmd.split()[0] if cmd.startswith('/') else None,
        'user': getpass.getuser(), 'enabled': enabled,
        'lastRunAt': '尚未执行', 'lastExitCode': None,
        'lastOutput': '等待首次周期触发...'
    }
cr_out = run_cmd(['crontab', '-l'], timeout=2)
if cr_out:
    pending_title, idx = '', 1
    for raw_line in cr_out.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith('# TERMFORYOU_TITLE '):
            pending_title = cron_title(stripped[len('# TERMFORYOU_TITLE '):].strip())
            continue
        if stripped.startswith('# TERMFORYOU_DISABLED '):
            try:
                payload = json.loads(base64.b64decode(stripped[len('# TERMFORYOU_DISABLED '):].strip()).decode('utf-8'))
                task = cron_task(payload.get('raw', ''), False, payload.get('title', '') or pending_title, idx)
                if task: crons.append(task); idx += 1
            except Exception:
                pass
            pending_title = ''
            continue
        if not stripped or stripped.startswith('#'):
            continue
        task = cron_task(line, True, pending_title, idx)
        pending_title = ''
        if task: crons.append(task); idx += 1
data['cronTasks'] = crons

# 5. 防火墙真实放行规则 (Firewall Rules)
rules = []
if shutil.which('ufw'):
    ufw_out = run_cmd(['ufw', 'status', 'numbered'], timeout=2)
    for line in ufw_out.splitlines():
        m = re.match(r'^\[\s*(\d+)\]\s+(.+?)\s+(ALLOW|DENY|REJECT)\s+(?:IN|OUT|FWD)?\s*(.+)$', line.strip(), re.IGNORECASE)
        if not m:
            continue
        r_num = int(m.group(1))
        to_part = m.group(2).strip()
        act_raw = m.group(3).upper()
        rest_part = m.group(4).strip()
        comment = f'UFW 规则 #{r_num}'
        if '#' in rest_part:
            rest_part, comment_raw = rest_part.split('#', 1)
            rest_part = rest_part.strip()
            if comment_raw.strip():
                comment = comment_raw.strip()
        is_v6 = '(v6)' in to_part or '(v6)' in rest_part
        to_clean = to_part.replace('(v6)', '').strip()
        rest_clean = rest_part.replace('(v6)', '').strip()
        src_cidr = '::/0' if (is_v6 and rest_clean.lower() == 'anywhere') else ('0.0.0.0/0' if rest_clean.lower() == 'anywhere' or not rest_clean else rest_clean.split()[0])
        p_num = to_clean.split('/')[0] if '/' in to_clean else to_clean
        proto = to_clean.split('/')[1].lower() if '/' in to_clean else 'any'
        if proto not in ('tcp', 'udp'):
            proto = 'any'
        rules.append({
            'id': f'ufw-{r_num}',
            'ruleNumber': r_num,
            'backend': 'ufw',
            'port': p_num,
            'protocol': proto,
            'sourceCidr': src_cidr,
            'action': act_raw if act_raw in ('ALLOW', 'DENY', 'REJECT') else 'DENY',
            'comment': comment,
            'enabled': True
        })
elif shutil.which('firewall-cmd'):
    fwd_out = run_cmd(['firewall-cmd', '--list-all'], timeout=2)
    idx = 1
    for line in fwd_out.splitlines():
        if 'ports:' in line:
            p_list = line.split('ports:', 1)[-1].strip().split()
            for p_spec in p_list:
                p_num = p_spec.split('/')[0] if '/' in p_spec else p_spec
                proto = p_spec.split('/')[1].lower() if '/' in p_spec else 'tcp'
                rules.append({
                    'id': f'fwd-{idx}',
                    'ruleNumber': idx,
                    'backend': 'firewalld',
                    'port': p_num.replace('-', ':'),
                    'protocol': proto if proto in ['tcp', 'udp'] else 'any',
                    'sourceCidr': '0.0.0.0/0',
                    'action': 'ALLOW',
                    'comment': 'firewalld 开放端口',
                    'enabled': True
                })
                idx += 1
if not rules and shutil.which('iptables'):
    ipt_out = run_cmd(['iptables', '-S', 'INPUT'], timeout=2)
    rule_idx = 0
    for line in ipt_out.splitlines():
        stripped = line.strip()
        if not stripped.startswith('-A INPUT'):
            continue
        rule_idx += 1
        if '--dport' in stripped:
            parts = stripped.split()
            p_num = 'any'
            proto = 'tcp'
            src_cidr = '0.0.0.0/0'
            if '-p' in parts and parts.index('-p') + 1 < len(parts):
                proto = parts[parts.index('-p') + 1].lower()
            if '--dport' in parts and parts.index('--dport') + 1 < len(parts):
                p_num = parts[parts.index('--dport') + 1]
            if '-s' in parts and parts.index('-s') + 1 < len(parts):
                src_cidr = parts[parts.index('-s') + 1]
            if '-j ACCEPT' in stripped:
                act = 'ALLOW'
            elif '-j REJECT' in stripped:
                act = 'REJECT'
            else:
                act = 'DENY'
            rules.append({
                'id': f'ipt-{rule_idx}',
                'ruleNumber': rule_idx,
                'backend': 'iptables',
                'port': p_num,
                'protocol': proto if proto in ['tcp', 'udp'] else 'any',
                'sourceCidr': src_cidr,
                'action': act,
                'comment': f'iptables INPUT 规则 #{rule_idx}',
                'enabled': True
            })
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

# Share the /proc collector between full inspection and the lightweight process API.
_inspection_code = shlex.split(REMOTE_FULL_INSPECT_SCRIPT)[2]
REMOTE_FULL_INSPECT_SCRIPT = "python3 -c " + shlex.quote(_inspection_code.replace("# PROCESS_LIST_CODE", PROCESS_LIST_CODE))

def docker_exec_command(container: str, sudo: bool = False) -> str:
    """Only allow a Docker identifier and a fixed interactive shell command."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", container or ""):
        raise ValueError("非法容器名称或 ID")
    return ("sudo -n " if sudo else "") + f"docker exec -it -- {shlex.quote(container)} /bin/sh"


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
        # Crontab 试运行结果仅保存在后端进程内存，不写入 SQLite 或远端配置。
        self._cron_runtime: Dict[str, Dict[str, Dict[str, Any]]] = {}

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
                cron_tasks = inspect_data.get("cronTasks", [])
                for cron_task in cron_tasks:
                    runtime = self._cron_runtime.get(host_alias, {}).get(cron_task.get("id"))
                    if runtime:
                        cron_task.update(runtime)
                return {
                    "status": "ok",
                    "host_alias": host_alias,
                    "auth_method": self._auth_methods.get(host_alias),
                    "timestamp": now,
                    "cwd": inspect_data.get("cwd", "/root"),
                    "timezone": inspect_data.get("timezone") or {},
                    "metrics": metrics,
                    "processes": inspect_data.get("processes", []),
                    "processesError": inspect_data.get("processesError"),
                    "dockerContainers": [DockerContainerInfo(**c).model_dump() for c in inspect_data.get("dockerContainers", [])],
                    "systemdServices": inspect_data.get("systemdServices", []),
                    "cronTasks": cron_tasks,
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

    async def _run_remote_json_script(self, host_alias: str, py_code: str, payload: Dict[str, Any], timeout: float = 10.0, sudo: bool = False) -> Dict[str, Any]:
        """在远端主机安全执行带 JSON 参数的 Python3 脚本并返回解析后的 JSON 结果"""
        conn, err_type, err_msg = await self._get_connection(host_alias)
        if not conn:
            return {
                "status": "error",
                "error_type": err_type or "connection_error",
                "message": err_msg or "无法建立 SSH 连接"
            }

        b64_payload = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
        full_cmd = ("sudo -n -- " if sudo else "") + f"python3 -c {shlex.quote(py_code)} {shlex.quote(b64_payload)}"
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

    async def _cron_mutation(self, host_alias: str, payload: Dict[str, Any], timeout: float = 12.0) -> Dict[str, Any]:
        """执行 Crontab 读写/试运行脚本，所有用户输入通过 JSON Base64 传递。"""
        code = r'''
import sys, os, json, base64, hashlib, subprocess, datetime, getpass
payload = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8'))
mode = payload.get('mode', '')
def task_id(raw):
    return 'cron-' + hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]
def title_decode(value):
    try: return base64.b64decode(value.encode('ascii')).decode('utf-8')
    except Exception: return ''
def title_encode(value):
    return base64.b64encode(value.encode('utf-8')).decode('ascii')
def make_task(raw, enabled, title=''):
    parts = raw.split(None, 1)
    if not parts: return None
    if parts[0].startswith('@'):
        expr, command = parts[0], parts[1] if len(parts) > 1 else ''
    else:
        cron = raw.split(None, 5)
        if len(cron) < 6: return None
        expr, command = ' '.join(cron[:5]), cron[5]
    if not command: return None
    return {'id': task_id(raw), 'engine': 'crontab', 'title': title or '定时计划任务', 'expression': expr,
            'command': command, 'scriptPath': command.split()[0] if command.startswith('/') else None,
            'user': getpass.getuser(), 'enabled': enabled, 'lastRunAt': '尚未执行', 'lastExitCode': None,
            'lastOutput': '等待首次周期触发...'}
def read_lines():
    result = subprocess.run(['crontab', '-l'], capture_output=True, text=True, timeout=5)
    if result.returncode not in (0, 1):
        raise RuntimeError((result.stderr or '无法读取当前用户 Crontab').strip())
    return result.stdout.splitlines()
def write_lines(lines):
    text = '\n'.join(lines)
    if text: text += '\n'
    result = subprocess.run(['crontab', '-'], input=text, capture_output=True, text=True, timeout=5)
    if result.returncode != 0: raise RuntimeError((result.stderr or '写入 Crontab 失败').strip())
def entries(lines):
    found, pending = [], ''
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('# TERMFORYOU_TITLE '):
            pending = title_decode(stripped[len('# TERMFORYOU_TITLE '):].strip())
            continue
        if stripped.startswith('# TERMFORYOU_DISABLED '):
            try:
                item = json.loads(base64.b64decode(stripped[len('# TERMFORYOU_DISABLED '):].strip()).decode('utf-8'))
                raw = item.get('raw', '')
                task = make_task(raw, False, item.get('title', '') or pending)
                if task: found.append((index, 'disabled', raw, task, item.get('title', '')))
            except Exception: pass
            pending = ''
            continue
        if not stripped or stripped.startswith('#'): continue
        task = make_task(line.rstrip(), True, pending)
        pending = ''
        if task: found.append((index, 'active', line.rstrip(), task, task.get('title', '')))
    return found
try:
    lines = read_lines()
    if mode == 'create':
        title, expression, command = payload.get('title', ''), payload.get('expression', '').strip(), payload.get('command', '')
        if any('\n' in value or '\r' in value for value in (title, expression, command)):
            raise ValueError('标题、表达式和命令不能包含换行')
        special_expressions = {'@reboot', '@hourly', '@daily', '@midnight', '@weekly', '@monthly', '@yearly', '@annually'}
        if expression not in special_expressions and len(expression.split()) != 5:
            raise ValueError('Cron 表达式必须包含 5 个字段，或使用 @reboot/@daily 等特殊表达式')
        if not command.strip(): raise ValueError('命令不能为空')
        lines.extend(['# TERMFORYOU_TITLE ' + title_encode(title.strip()), expression + ' ' + command.strip()])
        write_lines(lines)
        item = make_task(expression + ' ' + command.strip(), True, title.strip())
        print(json.dumps({'status':'ok', 'task': item, 'message':'已写入远端 Crontab'}, ensure_ascii=False))
    elif mode == 'enabled':
        wanted, enabled = payload.get('task_id', ''), bool(payload.get('enabled'))
        changed = False
        for index, kind, raw, task, title in entries(lines):
            if task['id'] != wanted: continue
            if enabled and kind == 'disabled':
                lines[index:index + 1] = ['# TERMFORYOU_TITLE ' + title_encode(title), raw]
            elif not enabled and kind == 'active':
                encoded = base64.b64encode(json.dumps({'raw': raw, 'title': title}, ensure_ascii=False).encode('utf-8')).decode('ascii')
                lines[index:index + 1] = ['# TERMFORYOU_DISABLED ' + encoded]
            else: continue
            changed = True
            break
        if not changed: raise ValueError('未找到指定的 Crontab 任务，可能已被其他操作修改')
        write_lines(lines)
        print(json.dumps({'status':'ok', 'enabled': enabled, 'message': ('已启用' if enabled else '已禁用') + '远端 Crontab 任务'}, ensure_ascii=False))
    elif mode == 'run':
        wanted = payload.get('task_id', '')
        matched = next((task for _, _, _, task, _ in entries(lines) if task['id'] == wanted), None)
        if not matched: raise ValueError('未找到指定的 Crontab 任务，可能已被删除')
        started = datetime.datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S')
        try:
            result = subprocess.run(['bash', '-lc', matched['command']], capture_output=True, text=True, timeout=60)
            output = ((result.stdout or '') + (result.stderr or '')).strip()
            exit_code = result.returncode
        except subprocess.TimeoutExpired as error:
            output = ((error.stdout or '') if isinstance(error.stdout, str) else '') + ((error.stderr or '') if isinstance(error.stderr, str) else '')
            output = (output.strip() + '\n执行超过 60 秒，已终止').strip()
            exit_code = 124
        matched.update({'lastRunAt': started, 'lastExitCode': exit_code, 'lastOutput': output[-4000:] or '(无输出)'})
        print(json.dumps({'status':'ok', 'task': matched, 'exit_code': exit_code, 'output': output[-4000:]}, ensure_ascii=False))
    else:
        raise ValueError('不支持的 Crontab 操作')
except Exception as error:
    print(json.dumps({'status':'error', 'message': str(error)}, ensure_ascii=False))
'''
        # Serialize writes/runs per host so concurrent UI clicks cannot overwrite a newer crontab.
        async with self._get_lock(host_alias):
            return await self._run_remote_json_script(host_alias, code, payload, timeout=timeout)

    async def create_cron_task(self, host_alias: str, title: str, expression: str, command: str) -> Dict[str, Any]:
        return await self._cron_mutation(host_alias, {
            'mode': 'create', 'title': title, 'expression': expression, 'command': command
        })

    async def set_cron_task_enabled(self, host_alias: str, task_id: str, enabled: bool) -> Dict[str, Any]:
        if not re.fullmatch(r'cron-[0-9a-f]{16}', task_id or ''):
            return {'status': 'error', 'message': '非法的 Crontab 任务标识'}
        return await self._cron_mutation(host_alias, {'mode': 'enabled', 'task_id': task_id, 'enabled': enabled})

    async def run_cron_task(self, host_alias: str, task_id: str) -> Dict[str, Any]:
        if not re.fullmatch(r'cron-[0-9a-f]{16}', task_id or ''):
            return {'status': 'error', 'message': '非法的 Crontab 任务标识'}
        result = await self._cron_mutation(host_alias, {'mode': 'run', 'task_id': task_id}, timeout=70.0)
        task = result.get('task') if isinstance(result, dict) else None
        if result.get('status') == 'ok' and task:
            self._cron_runtime.setdefault(host_alias, {})[task_id] = {
                'lastRunAt': task.get('lastRunAt', '刚刚'),
                'lastExitCode': task.get('lastExitCode'),
                'lastOutput': task.get('lastOutput', '(无输出)')
            }
        return result

    async def list_processes(self, host_alias: str) -> Dict[str, Any]:
        code = "import json\ndata = {}\n" + PROCESS_LIST_CODE + "\nprint(json.dumps(dict(status='error' if data.get('processesError') else 'ok', **data)))"
        return await self._run_remote_json_script(host_alias, code, {}, timeout=8)

    async def signal_process(self, host_alias: str, payload: ProcessSignalPayload) -> Dict[str, Any]:
        # Validate again at the service boundary; never interpolate request fields into shell code.
        payload = ProcessSignalPayload.model_validate(payload.model_dump())
        return await self._run_remote_json_script(host_alias, PROCESS_SIGNAL_CODE, payload.model_dump(), sudo=payload.sudo)

    async def restart_docker_container(self, host_alias: str, container: str, sudo: bool = False) -> Dict[str, Any]:
        return await self.control_docker_container(host_alias, container, "restart", sudo=sudo)

    async def control_docker_container(self, host_alias: str, container: str, action: str, sudo: bool = False) -> Dict[str, Any]:
        action_labels = {"start": "启动", "stop": "停止", "restart": "重启"}
        if action not in action_labels:
            return {"status": "error", "message": "不支持的容器操作"}
        label = action_labels[action]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", container or ""):
            return {"status": "error", "message": "非法容器名称或 ID"}
        conn, err_type, err_msg = await self._get_connection(host_alias)
        if not conn:
            return {"status": "error", "error_type": err_type, "message": err_msg or "无法建立 SSH 连接"}
        flags = "-t 10 " if action in ("stop", "restart") else ""
        command = ("sudo -n " if sudo else "") + f"docker {action} {flags}-- {shlex.quote(container)}"
        try:
            result = await conn.run(command, timeout=45)
            if result.exit_status != 0:
                return {"status": "error", "message": (result.stderr or result.stdout or f"容器{label}失败").strip(), "exit_code": result.exit_status}
            return {"status": "ok", "container": container, "action": action, "message": f"已{label}容器 {container}", "exit_code": 0}
        except Exception as exc:
            return {"status": "error", "message": f"未能确认{label}结果：{exc}；请刷新容器状态后再操作"}

    async def control_systemd_service(self, host_alias: str, service: str, action: str, sudo: bool = False) -> Dict[str, Any]:
        action_labels = {"start": "启动", "stop": "停止", "restart": "重启"}
        if action not in action_labels:
            return {"status": "error", "message": "不支持的服务操作"}
        label = action_labels[action]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9@_.:-]*", service or "") or ".." in service:
            return {"status": "error", "message": "非法 Systemd 服务名称"}
        conn, err_type, err_msg = await self._get_connection(host_alias)
        if not conn:
            return {"status": "error", "error_type": err_type, "message": err_msg or "无法建立 SSH 连接"}
        command = ("sudo -n " if sudo else "") + f"systemctl {action} -- {shlex.quote(service)}"
        try:
            result = await conn.run(command, timeout=45)
            if result.exit_status != 0:
                return {"status": "error", "message": (result.stderr or result.stdout or f"服务{label}失败").strip(), "exit_code": result.exit_status}
            return {"status": "ok", "service": service, "action": action, "message": f"已{label}服务 {service}", "exit_code": 0}
        except Exception as exc:
            return {"status": "error", "message": f"未能确认{label}结果：{exc}；请刷新服务状态后再操作"}

    @staticmethod
    def _validate_firewall_port(raw_port: str) -> Tuple[Optional[str], Optional[str]]:
        p = (raw_port or "").strip()
        if not p:
            return None, "端口不能为空"
        m = re.fullmatch(r"(\d{1,5})(?:[:\-](\d{1,5}))?", p)
        if not m:
            return None, "端口格式非法，仅支持单端口 (如 8080) 或端口段 (如 8000:8010)"
        start = int(m.group(1))
        if not (1 <= start <= 65535):
            return None, "端口号必须在 1~65535 之间"
        if m.group(2) is not None:
            end = int(m.group(2))
            if not (1 <= end <= 65535) or start >= end:
                return None, "端口段范围非法，需满足 1 <= 起始端口 < 结束端口 <= 65535"
            return f"{start}:{end}", None
        return str(start), None

    @staticmethod
    def _validate_firewall_source(raw_source: str) -> Tuple[Optional[str], Optional[str]]:
        s = (raw_source or "").strip()
        if not s or s.lower() in ("any", "anywhere", "0.0.0.0/0"):
            return "0.0.0.0/0", None
        try:
            net = ipaddress.ip_network(s, strict=False)
            return str(net), None
        except ValueError:
            return None, "来源 IP / CIDR 格式非法（示例：0.0.0.0/0 或 192.168.1.0/24）"

    async def _resolve_firewall_backend(self, conn: Any, preferred: Optional[str]) -> Optional[str]:
        if preferred in ("ufw", "firewalld", "iptables"):
            return preferred
        detect_cmd = (
            "if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld 2>/dev/null; then echo firewalld; "
            "elif command -v ufw >/dev/null 2>&1 && systemctl is-active --quiet ufw 2>/dev/null; then echo ufw; "
            "elif command -v ufw >/dev/null 2>&1; then echo ufw; "
            "elif command -v firewall-cmd >/dev/null 2>&1; then echo firewalld; "
            "elif command -v iptables >/dev/null 2>&1; then echo iptables; fi"
        )
        res = await conn.run(detect_cmd, timeout=5)
        detected = (res.stdout or "").strip().splitlines()[0].strip() if (res.stdout or "").strip() else ""
        return detected if detected in ("ufw", "firewalld", "iptables") else None

    async def create_firewall_rule(self, host_alias: str, payload: FirewallRuleCreatePayload) -> Dict[str, Any]:
        port_norm, port_err = self._validate_firewall_port(payload.port)
        if port_err or not port_norm:
            return {"status": "error", "message": port_err or "端口非法"}
        source_norm, src_err = self._validate_firewall_source(payload.sourceCidr)
        if src_err or not source_norm:
            return {"status": "error", "message": src_err or "来源网段非法"}

        conn, err_type, err_msg = await self._get_connection(host_alias)
        if not conn:
            return {"status": "error", "error_type": err_type, "message": err_msg or "无法建立 SSH 连接"}

        backend = await self._resolve_firewall_backend(conn, payload.backend)
        if not backend:
            return {"status": "error", "message": "未在目标主机检测到可用的 ufw / firewalld / iptables"}

        prefix = "sudo -n " if payload.sudo else ""
        if backend == "ufw":
            verb = {"ALLOW": "allow", "DENY": "deny", "REJECT": "reject"}[payload.action]
            from_arg = "any" if source_norm in ("0.0.0.0/0", "::/0") else source_norm
            proto_part = f" proto {payload.protocol}" if payload.protocol in ("tcp", "udp") else ""
            comment_clean = re.sub(r"[\r\n\x00-\x1f]", " ", payload.comment or "").strip()[:64]
            comment_part = f" comment {shlex.quote(comment_clean)}" if comment_clean else ""
            cmd = f"{prefix}ufw {verb} from {shlex.quote(from_arg)} to any port {shlex.quote(port_norm)}{proto_part}{comment_part}"
        elif backend == "firewalld":
            if payload.action != "ALLOW":
                return {"status": "error", "message": "firewalld 基础端口规则仅支持 ALLOW 放行；如需拦截请使用 ufw/iptables"}
            if source_norm not in ("0.0.0.0/0", "::/0"):
                return {"status": "error", "message": "firewalld 基础端口规则暂不支持限制来源 IP/CIDR，请使用 0.0.0.0/0"}
            port_fwd = port_norm.replace(":", "-")
            protos = ["tcp", "udp"] if payload.protocol == "any" else [payload.protocol]
            add_cmds = " && ".join(f"{prefix}firewall-cmd --permanent --add-port={shlex.quote(f'{port_fwd}/{p}')}" for p in protos)
            cmd = f"{add_cmds} && {prefix}firewall-cmd --reload"
        else:
            target = {"ALLOW": "ACCEPT", "DENY": "DROP", "REJECT": "REJECT"}[payload.action]
            protos = ["tcp", "udp"] if payload.protocol == "any" else [payload.protocol]
            src_part = f"-s {shlex.quote(source_norm)} " if source_norm not in ("0.0.0.0/0", "::/0") else ""
            cmd = " && ".join(
                f"{prefix}iptables -A INPUT -p {p} --dport {shlex.quote(port_norm)} {src_part}-j {target}"
                for p in protos
            )

        try:
            result = await conn.run(cmd, timeout=20)
            if result.exit_status != 0:
                detail = (result.stderr or result.stdout or "防火墙规则添加失败").strip()
                return {"status": "error", "backend": backend, "message": detail, "exit_code": result.exit_status}
            return {
                "status": "ok",
                "backend": backend,
                "command": cmd,
                "message": f"已在 {backend.upper()} 中应用规则 ({payload.action} {port_norm}/{payload.protocol.upper()})",
                "exit_code": 0,
            }
        except Exception as exc:
            return {"status": "error", "backend": backend, "message": f"添加防火墙规则超时或异常：{exc}"}

    async def delete_firewall_rule(self, host_alias: str, payload: FirewallRuleDeletePayload) -> Dict[str, Any]:
        port_norm, port_err = self._validate_firewall_port(payload.port)
        if port_err or not port_norm:
            return {"status": "error", "message": port_err or "端口非法"}
        source_norm, src_err = self._validate_firewall_source(payload.sourceCidr)
        if src_err or not source_norm:
            return {"status": "error", "message": src_err or "来源网段非法"}

        conn, err_type, err_msg = await self._get_connection(host_alias)
        if not conn:
            return {"status": "error", "error_type": err_type, "message": err_msg or "无法建立 SSH 连接"}

        backend = await self._resolve_firewall_backend(conn, payload.backend)
        if not backend:
            return {"status": "error", "message": "未在目标主机检测到可用的 ufw / firewalld / iptables"}

        prefix = "sudo -n " if payload.sudo else ""
        if backend == "ufw":
            if payload.ruleNumber is None or payload.ruleNumber < 1:
                return {"status": "error", "message": "缺少 UFW 规则编号，请先刷新规则列表后重试"}
            cmd = f"{prefix}ufw --force delete {int(payload.ruleNumber)}"
        elif backend == "firewalld":
            port_fwd = port_norm.replace(":", "-")
            protos = ["tcp", "udp"] if payload.protocol == "any" else [payload.protocol]
            rm_cmds = " && ".join(f"{prefix}firewall-cmd --permanent --remove-port={shlex.quote(f'{port_fwd}/{p}')}" for p in protos)
            cmd = f"{rm_cmds} && {prefix}firewall-cmd --reload"
        else:
            if payload.ruleNumber is not None and payload.ruleNumber >= 1:
                cmd = f"{prefix}iptables -D INPUT {int(payload.ruleNumber)}"
            else:
                target = {"ALLOW": "ACCEPT", "DENY": "DROP", "REJECT": "REJECT"}[payload.action]
                protos = ["tcp", "udp"] if payload.protocol == "any" else [payload.protocol]
                src_part = f"-s {shlex.quote(source_norm)} " if source_norm not in ("0.0.0.0/0", "::/0") else ""
                cmd = " && ".join(
                    f"{prefix}iptables -D INPUT -p {p} --dport {shlex.quote(port_norm)} {src_part}-j {target}"
                    for p in protos
                )

        try:
            result = await conn.run(cmd, timeout=20)
            if result.exit_status != 0:
                detail = (result.stderr or result.stdout or "防火墙规则删除失败").strip()
                return {"status": "error", "backend": backend, "message": detail, "exit_code": result.exit_status}
            return {
                "status": "ok",
                "backend": backend,
                "command": cmd,
                "message": f"已从 {backend.upper()} 删除端口 {port_norm}/{payload.protocol.upper()} 规则",
                "exit_code": 0,
            }
        except Exception as exc:
            return {"status": "error", "backend": backend, "message": f"删除防火墙规则超时或异常：{exc}"}

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
