from typing import List, Optional
from pydantic import BaseModel

class SshHostInfo(BaseModel):
    id: str                 # 唯一标识（通常与 host_alias 相同）
    host_alias: str         # Host 别名 (如 my-server)
    hostname: str           # 目标 IP 或域名 (HostName)
    user: str               # 登录用户名 (User，缺省 root 或当前用户)
    port: int               # SSH 端口 (Port，缺省 22)
    identity_files: List[str] = [] # 指定的密钥路径 (IdentityFile)
    proxy_jump: Optional[str] = None # 跳板机
    auth_hint: str = "key"  # "key" | "password" | "agent"

class TerminalAuthPayload(BaseModel):
    password: Optional[str] = None
    passphrase: Optional[str] = None
    cols: int = 120
    rows: int = 34
    term: str = "xterm-256color"
