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
