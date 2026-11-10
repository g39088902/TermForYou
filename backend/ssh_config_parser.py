import os
import re
from typing import List, Dict, Optional
from models import SshHostInfo

def get_ssh_config_path() -> str:
    return os.path.expanduser("~/.ssh/config")

def parse_ssh_config() -> List[SshHostInfo]:
    """
    解析本机 ~/.ssh/config 文件。
    完全遵循 VS Code Remote - SSH 的读取规范。
    """
    config_path = get_ssh_config_path()
    if not os.path.exists(config_path):
        return []

    hosts: List[SshHostInfo] = []
    current_host: Optional[Dict] = None

    with open(config_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            clean_line = line.strip()
            # 忽略空行和注释
            if not clean_line or clean_line.startswith("#"):
                continue

            parts = re.split(r"\s+", clean_line, maxsplit=1)
            if len(parts) < 2:
                continue

            key = parts[0].lower()
            val = parts[1].strip()

            if key == "host":
                # 保存前一个 Host
                if current_host and current_host.get("host_alias") != "*":
                    hosts.append(_dict_to_model(current_host))

                # 如果 Host 包含了通配符或多个 alias，取第一个作为主 alias
                alias = val.split()[0]
                current_host = {
                    "id": alias,
                    "host_alias": alias,
                    "hostname": alias, # 默认先设为 alias，后面 HostName 覆盖
                    "user": "root",
                    "port": 22,
                    "identity_files": [],
                    "proxy_jump": None
                }
            elif current_host is not None:
                if key == "hostname":
                    current_host["hostname"] = val
                elif key == "user":
                    current_host["user"] = val
                elif key == "port":
                    try:
                        current_host["port"] = int(val)
                    except ValueError:
                        pass
                elif key == "identityfile":
                    expanded_key = os.path.expanduser(val.strip('"\''))
                    current_host["identity_files"].append(expanded_key)
                elif key == "proxyjump":
                    current_host["proxy_jump"] = val

    if current_host and current_host.get("host_alias") != "*":
        hosts.append(_dict_to_model(current_host))

    return hosts

def _dict_to_model(data: Dict) -> SshHostInfo:
    auth_hint = "key" if data["identity_files"] else "agent"
    return SshHostInfo(
        id=data["id"],
        host_alias=data["host_alias"],
        hostname=data["hostname"],
        user=data["user"],
        port=data["port"],
        identity_files=data["identity_files"],
        proxy_jump=data["proxy_jump"],
        auth_hint=auth_hint
    )

def find_host_by_alias(alias: str) -> Optional[SshHostInfo]:
    all_hosts = parse_ssh_config()
    for h in all_hosts:
        if h.host_alias == alias or h.id == alias:
            return h
    return None

def delete_host_from_ssh_config(target_alias: str) -> bool:
    """
    从 ~/.ssh/config 中持久删除指定 host_alias 的 Host 配置块。
    操作前自动将原文件备份为 ~/.ssh/config.bak。
    """
    config_path = get_ssh_config_path()
    if not os.path.exists(config_path):
        return False

    with open(config_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    new_lines = []
    i = 0
    deleted = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # 遇到非注释的 Host 关键字行
        if not stripped.startswith("#") and re.match(r"^host\s+", stripped, re.IGNORECASE):
            parts = re.split(r"\s+", stripped, maxsplit=1)
            aliases = parts[1].split() if len(parts) > 1 else []

            if target_alias in aliases:
                deleted = True
                if len(aliases) > 1:
                    # 仅移除这一个 alias，保留该块其他 alias
                    remaining = [a for a in aliases if a != target_alias]
                    indent = line[:line.lower().find("host")]
                    new_lines.append(f"{indent}Host {' '.join(remaining)}\n")
                    i += 1
                    continue
                else:
                    # 单一 alias，跳过整个 block 直到下一个 Host 行或文件末尾
                    i += 1
                    while i < len(lines):
                        next_line = lines[i]
                        next_stripped = next_line.strip()
                        if not next_stripped.startswith("#") and re.match(r"^host\s+", next_stripped, re.IGNORECASE):
                            break
                        i += 1
                    continue

        new_lines.append(line)
        i += 1

    if deleted:
        # 备份原文件
        try:
            bak_path = config_path + ".bak"
            with open(bak_path, "w", encoding="utf-8") as f_bak:
                f_bak.writelines(lines)
        except Exception:
            pass

        # 写入更新后的内容
        with open(config_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

    return deleted

def add_host_to_ssh_config(host_alias: str, hostname: str, port: int = 22, user: str = "root") -> bool:
    """
    向 ~/.ssh/config 持久追加或更新服务器配置。
    """
    config_path = get_ssh_config_path()
    os.makedirs(os.path.dirname(config_path), exist_ok=True)

    # 如果已存在同名 host 先移除旧块
    if os.path.exists(config_path):
        delete_host_from_ssh_config(host_alias)

    block = f"\nHost {host_alias}\n  HostName {hostname}\n  Port {port}\n  User {user}\n"
    with open(config_path, "a", encoding="utf-8") as f:
        f.write(block)

    return True
