import sqlite3
import time
import os
from typing import Dict, Any

DB_FILE = os.path.join(os.path.dirname(__file__), "termforyou.sqlite3")

def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """初始化 SQLite 数据库及统计表"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS host_stats (
                host_alias TEXT PRIMARY KEY,
                connection_count INTEGER NOT NULL DEFAULT 0,
                last_connected_at INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.commit()

def get_all_host_stats() -> Dict[str, Dict[str, Any]]:
    """获取所有主机的连接统计"""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT host_alias, connection_count, last_connected_at FROM host_stats")
        rows = cursor.fetchall()
        return {
            row["host_alias"]: {
                "connection_count": row["connection_count"],
                "last_connected_at": row["last_connected_at"]
            }
            for row in rows
        }

def record_manual_connection(host_alias: str) -> Dict[str, Any]:
    """记录一次手动连接，连接次数 +1，更新最后连接时间戳"""
    init_db()
    now_ts = int(time.time())
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO host_stats (host_alias, connection_count, last_connected_at)
            VALUES (?, 1, ?)
            ON CONFLICT(host_alias) DO UPDATE SET
                connection_count = host_stats.connection_count + 1,
                last_connected_at = excluded.last_connected_at
        """, (host_alias, now_ts))
        conn.commit()

        cursor.execute(
            "SELECT host_alias, connection_count, last_connected_at FROM host_stats WHERE host_alias = ?",
            (host_alias,)
        )
        row = cursor.fetchone()
        if row:
            return {
                "host_alias": row["host_alias"],
                "connection_count": row["connection_count"],
                "last_connected_at": row["last_connected_at"]
            }
        return {
            "host_alias": host_alias,
            "connection_count": 1,
            "last_connected_at": now_ts
        }
