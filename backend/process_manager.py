"""Stateless Python programs sent over SSH; no remote installation required."""

PROCESS_LIST_CODE = r'''
import os, pwd, time, subprocess, re
processes = []
ports_map = {}
try:
    command = subprocess.Popen(['ss', '-H', '-tulnp'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True)
    try:
        ss_out = command.communicate(timeout=2)[0]
    except subprocess.TimeoutExpired:
        command.kill()
        ss_out = command.communicate()[0]
    for line in ss_out.splitlines():
        fields = line.split()
        if len(fields) >= 5:
            port = fields[4].rsplit(':', 1)[-1]
            if port.isdigit():
                for pid in re.findall(r'pid=(\d+)', line):
                    ports_map[int(pid)] = (fields[0], int(port))
except OSError:
    pass
try:
    boot_id = open('/proc/sys/kernel/random/boot_id').read().strip()
    uptime = float(open('/proc/uptime').read().split()[0])
    ticks = os.sysconf('SC_CLK_TCK')
    page_size = os.sysconf('SC_PAGE_SIZE')
    mem_total = next(int(line.split()[1]) * 1024 for line in open('/proc/meminfo') if line.startswith('MemTotal:'))
    for entry in os.listdir('/proc'):
        if not entry.isdigit():
            continue
        try:
            pid = int(entry)
            if pid == os.getpid():
                continue
            path = '/proc/' + entry
            raw = open(path + '/stat').read()
            stat = raw[raw.rfind(')') + 2:].split()
            start = stat[19]
            elapsed = max(0.01, uptime - int(start) / ticks)
            rss = max(0, int(stat[21])) * page_size
            args = open(path + '/cmdline', 'rb').read(8192).replace(b'\0', b' ').decode('utf-8', 'replace').strip()
            name = raw[raw.find('(') + 1:raw.rfind(')')]
            uid = os.stat(path).st_uid
            try:
                user = pwd.getpwuid(uid).pw_name
            except KeyError:
                user = str(uid)
            try:
                cwd = os.readlink(path + '/cwd')
            except OSError:
                cwd = ''
            again = open(path + '/stat').read()
            if again[again.rfind(')') + 2:].split()[19] != start:
                continue
            proto, port = ports_map.get(pid, (None, None))
            processes.append({
                'pid': pid, 'ppid': int(stat[1]), 'name': name, 'cmdline': (args or '[' + name + ']')[:240],
                'user': user, 'state': stat[0], 'identity': boot_id + ':' + start,
                'cpuPercent': round((int(stat[11]) + int(stat[12])) / ticks / elapsed * 100, 1),
                'memPercent': round(rss / max(1, mem_total) * 100, 1), 'memRssMb': round(rss / 1048576, 1),
                'listenPort': port, 'protocol': proto, 'firewallAllowed': None, 'cwd': cwd,
                'uptime': str(int(elapsed)) + 's'
            })
        except (OSError, ValueError, IndexError):
            continue
    processes.sort(key=lambda p: (-p['cpuPercent'], p['pid']))
    data['processes'] = processes[:100]
    data['processesError'] = None
except (OSError, ValueError, StopIteration) as exc:
    data['processes'] = []
    data['processesError'] = '无法读取 /proc 进程列表: ' + str(exc)
'''

PROCESS_SIGNAL_CODE = r'''
import os, sys, json, base64, signal, re
payload = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8'))
pid = payload.get('pid')
identity = payload.get('identity', '')
signame = payload.get('signal')

def fail(kind, message):
    print(json.dumps({'status': 'error', 'error_type': kind, 'message': message}))
    sys.exit(0)

if type(pid) is not int or pid <= 1 or pid > 2147483647 or signame not in ('SIGTERM', 'SIGKILL') or not re.fullmatch(r'[a-f0-9-]{36}:[0-9]+', identity):
    fail('invalid_request', '非法 PID、信号或进程标识')
# Protect the operation itself and its SSH/session ancestors.
ancestor = os.getpid()
protected = {1}
while ancestor > 1 and ancestor not in protected:
    protected.add(ancestor)
    try:
        raw = open('/proc/%s/stat' % ancestor).read()
        ancestor = int(raw[raw.rfind(')') + 2:].split()[1])
    except (OSError, ValueError, IndexError):
        break
if pid in protected:
    fail('protected_process', '不能终止 PID 1 或当前 SSH 操作的进程链')
fd = None
try:
    boot_id = open('/proc/sys/kernel/random/boot_id').read().strip()
    # pidfd binds the signal to this process even if the numeric PID is reused.
    if hasattr(os, 'pidfd_open') and hasattr(signal, 'pidfd_send_signal'):
        try:
            fd = os.pidfd_open(pid)
        except OSError as exc:
            if exc.errno != 38:  # ENOSYS on older kernels: validate stat immediately before kill.
                raise
    raw = open('/proc/%s/stat' % pid).read()
    stat = raw[raw.rfind(')') + 2:].split()
    if boot_id + ':' + stat[19] != identity:
        fail('stale_process', '进程已变化，已取消操作；请刷新列表')
    if stat[0] == 'Z':
        fail('zombie_process', '僵尸进程无法通过信号清除，需要由父进程回收')
    if fd is not None:
        signal.pidfd_send_signal(fd, getattr(signal, signame))
    else:
        os.kill(pid, getattr(signal, signame))
    print(json.dumps({'status': 'ok', 'pid': pid, 'signal': signame, 'message': '已向 PID %s 发送 %s' % (pid, signame)}))
except ProcessLookupError:
    fail('not_found', '进程已退出，请刷新列表')
except FileNotFoundError:
    fail('not_found', '进程已退出或 /proc 不可用，请刷新列表')
except PermissionError:
    fail('permission_denied', '权限不足；如需提权，请显式勾选 sudo 后重试')
except (OSError, ValueError, IndexError) as exc:
    fail('signal_failed', '发送信号失败: ' + str(exc))
finally:
    if fd is not None:
        os.close(fd)
'''
