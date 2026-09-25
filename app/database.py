"""Local SQLite Database for offline-first resilience."""
import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator, Optional


import subprocess


def get_rtc_now_str() -> str:
    """Read hardware RTC timestamp (Raspberry Pi /dev/rtc0, sysfs, or hwclock)."""
    # 1. Direct sysfs check for /sys/class/rtc/rtc0
    try:
        date_file = "/sys/class/rtc/rtc0/date"
        time_file = "/sys/class/rtc/rtc0/time"
        if os.path.exists(date_file) and os.path.exists(time_file):
            with open(date_file, "r") as fd, open(time_file, "r") as ft:
                d_str = fd.read().strip()
                t_str = ft.read().strip()
                if d_str and t_str:
                    return f"{d_str}T{t_str}+00:00"
    except Exception:
        pass

    # 2. Linux hwclock fallback
    try:
        res = subprocess.run(["hwclock", "-r", "-u"], capture_output=True, text=True, timeout=1)
        if res.returncode == 0 and res.stdout.strip():
            parts = res.stdout.strip().split()
            if len(parts) >= 2:
                return f"{parts[0]}T{parts[1]}"
    except Exception:
        pass

    # 3. Standard UTC clock fallback
    return datetime.now(timezone.utc).isoformat()


def get_utc_now() -> str:
    """Return UTC ISO8601 timestamp backed by hardware RTC if present."""
    return get_rtc_now_str()


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
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
        except Exception:
            pass
        try:
            conn.execute("PRAGMA busy_timeout = 30000;")
        except Exception:
            pass
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
                    rtc_time TEXT,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

            # Auto-migrate columns for test_results if database already existed
            cursor.execute("PRAGMA table_info(test_results)")
            existing_cols = {row["name"] for row in cursor.fetchall()}
            if "device_id" not in existing_cols:
                cursor.execute("ALTER TABLE test_results ADD COLUMN device_id TEXT")
            if "rtc_time" not in existing_cols:
                cursor.execute("ALTER TABLE test_results ADD COLUMN rtc_time TEXT")
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

    def insert_agent_log(
        self,
        level: str,
        module: str,
        message: str,
        error_code: Optional[str] = None
    ) -> None:
        """Insert a log record into the local SQLite agent_logs table."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO agent_logs (level, module, message, error_code, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (level, module, message, error_code, get_utc_now()),
                )
        except Exception:
            pass

    def get_agent_logs(self, limit: int = 100, since_id: int = 0) -> list:
        """Fetch stored agent logs from SQLite."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if since_id > 0:
                    cursor.execute(
                        """
                        SELECT id, level, module, message, error_code, created_at
                        FROM agent_logs
                        WHERE id > ?
                        ORDER BY id ASC
                        LIMIT ?
                        """,
                        (since_id, limit),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT id, level, module, message, error_code, created_at
                        FROM agent_logs
                        ORDER BY id DESC
                        LIMIT ?
                        """,
                        (limit,),
                    )
                rows = cursor.fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    def get_latest_agent_log_id(self) -> int:
        """Get the highest ID in agent_logs."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT MAX(id) FROM agent_logs")
                val = cursor.fetchone()[0]
                return val or 0
        except Exception:
            return 0
