"""Offline queue and synchronization manager for test results."""
import json
import uuid
from typing import Optional, Any
from app.api_client import ApiClient
from app.database import Database, get_utc_now
from app.logger import setup_logger
from app.constants import SyncStatus, DEFAULT_MAX_RETRIES

logger = setup_logger("sync_manager")


class SyncManager:
    def __init__(self, db: Database, api_client: ApiClient, identity: Optional[Any] = None):
        self.db = db
        self.api_client = api_client
        self.identity = identity

    def enqueue_result(self, result_dict: dict) -> str:
        """Store test result in local SQLite and queue for sync."""
        if self.identity and "device_uuid" not in result_dict:
            result_dict["device_uuid"] = self.identity.device_uuid

        result_id = result_dict.get("id") or str(uuid.uuid4())
        now = get_utc_now()

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            # 1. Insert into test_results
            cursor.execute(
                """
                INSERT INTO test_results (
                    id, test_type, started_at, finished_at,
                    download_mbps, upload_mbps, latency_ms, jitter_ms,
                    packet_loss, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result_id,
                    result_dict.get("test_type", "speedtest"),
                    result_dict.get("started_at", now),
                    result_dict.get("finished_at", now),
                    result_dict.get("download_mbps"),
                    result_dict.get("upload_mbps"),
                    result_dict.get("latency_ms"),
                    result_dict.get("jitter_ms"),
                    result_dict.get("packet_loss"),
                    json.dumps(result_dict),
                    now,
                ),
            )

            # 2. Insert into sync_queue
            cursor.execute(
                """
                INSERT INTO sync_queue (
                    id, entity_type, entity_id, payload_json, status, retry_count, created_at, updated_at
                ) VALUES (?, 'test_result', ?, ?, ?, 0, ?, ?)
                """,
                (str(uuid.uuid4()), result_id, json.dumps(result_dict), SyncStatus.PENDING.value, now, now),
            )
        logger.info(f"Test result {result_id} queued locally for sync")
        return result_id

    def sync_pending(self) -> int:
        """Attempt to push all pending items to cloud backend."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, entity_type, entity_id, payload_json, retry_count FROM sync_queue WHERE status = ? LIMIT 20",
                (SyncStatus.PENDING.value,),
            )
            items = cursor.fetchall()

        synced_count = 0
        for item in items:
            queue_id = item["id"]
            payload = json.loads(item["payload_json"])
            retries = item["retry_count"]

            try:
                # Idempotency guaranteed by sending unique test result ID
                resp = self.api_client.post("agent/results/sync", json=payload, max_retries=1)
                if resp.status_code in (200, 201):
                    self._update_queue_status(queue_id, SyncStatus.SYNCED.value)
                    synced_count += 1
                else:
                    self._mark_queue_failed(queue_id, retries + 1, f"HTTP {resp.status_code}")
            except Exception as e:
                self._mark_queue_failed(queue_id, retries + 1, str(e))

        if synced_count > 0:
            logger.info(f"Successfully synced {synced_count} pending results")
        return synced_count

    def _update_queue_status(self, queue_id: str, status: str) -> None:
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE sync_queue SET status = ?, updated_at = ? WHERE id = ?",
                (status, get_utc_now(), queue_id),
            )

    def _mark_queue_failed(self, queue_id: str, retry_count: int, error_msg: str) -> None:
        status = SyncStatus.FAILED.value if retry_count >= DEFAULT_MAX_RETRIES else SyncStatus.PENDING.value
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE sync_queue SET status = ?, retry_count = ?, last_error = ?, updated_at = ? WHERE id = ?",
                (status, retry_count, error_msg, get_utc_now(), queue_id),
            )
