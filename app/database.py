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
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 30000;")
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
                    device_id TEXT,
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

            # Auto-migrate columns for test_results if database already existed
            cursor.execute("PRAGMA table_info(test_results)")
            existing_cols = {row["name"] for row in cursor.fetchall()}
            if "device_id" not in existing_cols:
                cursor.execute("ALTER TABLE test_results ADD COLUMN device_id TEXT")
            if "download_mbps" not in existing_cols:
                cursor.execute("ALTER TABLE test_results ADD COLUMN download_mbps REAL")
            if "upload_mbps" not in existing_cols:
                cursor.execute("ALTER TABLE test_results ADD COLUMN upload_mbps REAL")
            if "latency_ms" not in existing_cols:
                cursor.execute("ALTER TABLE test_results ADD COLUMN latency_ms REAL")
            if "jitter_ms" not in existing_cols:
                cursor.execute("ALTER TABLE test_results ADD COLUMN jitter_ms REAL")
            if "packet_loss" not in existing_cols:
                cursor.execute("ALTER TABLE test_results ADD COLUMN packet_loss REAL")
            if "result_json" not in existing_cols:
                cursor.execute("ALTER TABLE test_results ADD COLUMN result_json TEXT NOT NULL DEFAULT '{}'")

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

    def get_latest_test_result(self) -> Optional[dict]:
        """Fetch the most recent test result from SQLite."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM test_results ORDER BY finished_at DESC LIMIT 1"
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception:
            return None

    def get_test_results_count(self) -> int:
        """Fetch total count of test results stored in SQLite."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM test_results")
                return cursor.fetchone()[0]
        except Exception:
            return 0

    def get_pending_sync_count(self) -> int:
        """Fetch count of pending items in sync queue."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM sync_queue WHERE status = 'PENDING'")
                return cursor.fetchone()[0]
        except Exception:
            return 0
