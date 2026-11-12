from typing import List, Optional, Literal
from pydantic import BaseModel, Field

class SshHostInfo(BaseModel):
    id: str                 # 唯一标识（通常与 host_alias 相同）
    host_alias: str         # Host 别名 (如 my-server)
    hostname: str           # 目标 IP 或域名 (HostName)
    user: str               # 登录用户名 (User，缺省 root 或当前用户)
    port: int               # SSH 端口 (Port，缺省 22)
    identity_files: List[str] = [] # 指定的密钥路径 (IdentityFile)
    proxy_jump: Optional[str] = None # 跳板机
    auth_hint: str = "key"  # "key" | "password" | "agent"
    connection_count: int = 0 # 用户手动连接次数
    last_connected_at: Optional[int] = None # 最后连接时间戳 (Unix Timestamp 秒)

class CreateHostPayload(BaseModel):
    host_alias: str
    hostname: str
    user: str = "root"
    port: int = 22

class TerminalAuthPayload(BaseModel):
    password: Optional[str] = None
    passphrase: Optional[str] = None
    cols: int = 120
    rows: int = 34
    term: str = "xterm-256color"
    docker_container: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    sudo: bool = False

class ProcessSignalPayload(BaseModel):
    pid: int = Field(strict=True, ge=2, le=2147483647)
    signal: Literal["SIGTERM", "SIGKILL"]
    identity: str = Field(pattern=r"^[a-f0-9-]{36}:[0-9]+$")
    sudo: bool = Field(default=False, strict=True)

class DockerRestartPayload(BaseModel):
    sudo: bool = False

class DockerActionPayload(DockerRestartPayload):
    action: Literal["start", "stop"]

class DockerPortInfo(BaseModel):
    hostPort: int = 0  # 0 means exposed in the container but not published on the host
    hostIp: str = ""
    containerPort: int
    protocol: Literal["tcp", "udp", "sctp"] = "tcp"

class DockerMountInfo(BaseModel):
    hostPath: str
    containerPath: str
    type: str
    readOnly: bool

class DockerNetworkInfo(BaseModel):
    name: str
    ipAddress: str = ""
    ipv6Address: str = ""

class DockerContainerInfo(BaseModel):
    id: str
    name: str
    image: str
    status: str
    ports: List[DockerPortInfo] = Field(default_factory=list)
    volumes: List[DockerMountInfo] = Field(default_factory=list)
    diskUsage: Optional[str] = None
    createdAt: str
    detailsAvailable: bool = False
    networkMode: Optional[str] = None
    networks: List[DockerNetworkInfo] = Field(default_factory=list)
    restartPolicy: Optional[str] = None
    restartMaxRetries: Optional[int] = None
    restartCount: Optional[int] = None
    healthStatus: Optional[str] = None
    startedAt: Optional[str] = None
    finishedAt: Optional[str] = None
    exitCode: Optional[int] = None
    oomKilled: Optional[bool] = None
    memoryLimitBytes: Optional[int] = None
    cpuLimit: Optional[float] = None
    cpusetCpus: Optional[str] = None
    privileged: Optional[bool] = None
    readOnlyRootfs: Optional[bool] = None
    runUser: Optional[str] = None
    composeProject: Optional[str] = None
    composeService: Optional[str] = None

class SetCredentialPayload(BaseModel):
    password: str

class WriteFilePayload(BaseModel):
    path: str
    content: str
    sudo_write: bool = False

class MkdirPayload(BaseModel):
    path: str
    mode: str = "0755"
    sudo: bool = False

class TouchFilePayload(BaseModel):
    path: str
    content: str = ""
    sudo: bool = False

class RenameFilePayload(BaseModel):
    old_path: str
    new_path: str
    sudo: bool = False

class CopyFilePayload(BaseModel):
    src_path: str
    dest_path: str
    sudo: bool = False

class DeleteFilesPayload(BaseModel):
    paths: List[str]
    sudo: bool = False

class ChmodFilePayload(BaseModel):
    path: str
    octal: str
    recursive: bool = False
    owner: Optional[str] = None
    group: Optional[str] = None
    sudo: bool = False

class ArchiveFilesPayload(BaseModel):
    paths: List[str]
    output_path: Optional[str] = None
    target_dir: Optional[str] = None
    action: str = "compress"  # "compress" | "extract"
    sudo: bool = False

class SingleDirSizePayload(BaseModel):
    path: str
    sudo: bool = False

class DownloadBatchPayload(BaseModel):
    paths: List[str]
