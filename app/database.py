"""Local SQLite Database for offline-first resilience."""
import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator, Optional


def get_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, db_path: str = "farlink.db"):
        self.db_path = db_path
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self.init_schema()

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # 1. device_state
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS device_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # 2. local_config
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS local_config (
                    version INTEGER PRIMARY KEY,
                    config_json TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)

            # 3. test_results
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS test_results (
                    id TEXT PRIMARY KEY,
                    test_type TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    download_mbps REAL,
                    upload_mbps REAL,
                    latency_ms REAL,
                    jitter_ms REAL,
                    packet_loss REAL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

            # 4. sync_queue
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sync_queue (
                    id TEXT PRIMARY KEY,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # 5. commands
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS commands (
                    id TEXT PRIMARY KEY,
                    command TEXT NOT NULL,
                    payload_json TEXT,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # 6. agent_logs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    level TEXT NOT NULL,
                    module TEXT NOT NULL,
                    message TEXT NOT NULL,
                    error_code TEXT,
                    created_at TEXT NOT NULL
                )
            """)
