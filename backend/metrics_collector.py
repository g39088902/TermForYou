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
        if password:
            self._credentials[host_alias] = password

    def _get_lock(self, host_alias: str) -> asyncio.Lock:
        if host_alias not in self._locks:
            self._locks[host_alias] = asyncio.Lock()
        return self._locks[host_alias]

    async def _get_connection(self, host_alias: str) -> Optional[asyncssh.SSHClientConnection]:
        conn = self._connections.get(host_alias)
        if conn and not conn.is_closed():
            return conn

        host_info = find_host_by_alias(host_alias)
        if not host_info:
            return None

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
            return new_conn
        except Exception as e:
            # 连接失败清理缓存
            self._connections.pop(host_alias, None)
            return None

    async def fetch_metrics(self, host_alias: str) -> Dict[str, Any]:
        """获取指定主机的 CPU、内存、磁盘、流量等实时性能指标"""
        async with self._get_lock(host_alias):
            now = time.time()
            cached = self._last_result.get(host_alias)
            # 如果 1.5 秒内刚采集过，直接返回避免重复开销
            if cached and (now - cached.get("timestamp", 0) < 1.5):
                return cached

            conn = await self._get_connection(host_alias)
            if not conn:
                return {
                    "status": "error",
                    "message": "无法建立 SSH 连接或未完成身份认证",
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

# 全局单例
metrics_service = HostMetricsService()
