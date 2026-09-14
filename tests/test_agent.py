"""Comprehensive unit tests for FarLink Agent core modules."""
import os
import tempfile
import unittest
from app.database import Database
from app.device_identity import DeviceIdentity
from app.config_manager import ConfigManager
from app.sync_manager import SyncManager
from app.api_client import ApiClient
from app.health_monitor import HealthMonitor
from app.network_diagnostics import NetworkDiagnostics
from app.lcd_display import LCDDisplay
from app.button_handler import ButtonHandler
from app.constants import SyncStatus


class TestFarlinkAgent(unittest.TestCase):
    def setUp(self):
        self.fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.fd)
        self.db = Database(self.db_path)
        self.api = ApiClient("http://mock-api.local")

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_device_identity_persistence(self):
        ident1 = DeviceIdentity(self.db)
        uuid1 = ident1.device_uuid
        claim1 = ident1.claim_code
        self.assertIsNotNone(uuid1)
        self.assertTrue(claim1.startswith("FL-"))

        # Second instance with same DB should retain identity
        ident2 = DeviceIdentity(self.db)
        self.assertEqual(ident2.device_uuid, uuid1)
        self.assertEqual(ident2.claim_code, claim1)

        # Token and status persistence
        ident1.set_token("test_secret_token_123")
        ident1.set_status("ACTIVE")
        self.assertEqual(ident2.get_token(), "test_secret_token_123")
        self.assertEqual(ident2.get_status(), "ACTIVE")

    def test_config_manager_atomic_and_rollback(self):
        cfg_mgr = ConfigManager(self.db, self.api)
        self.assertEqual(cfg_mgr.get_active_version(), 1)

        # Apply valid v2
        v2 = {"version": 2, "heartbeat_interval": 30}
        self.assertTrue(cfg_mgr.apply_config(v2))
        self.assertEqual(cfg_mgr.get_active_version(), 2)

        # Reject invalid config (missing version)
        invalid_cfg = {"heartbeat_interval": 10}
        self.assertFalse(cfg_mgr.apply_config(invalid_cfg))
        self.assertEqual(cfg_mgr.get_active_version(), 2)

        # Apply valid v3
        v3 = {"version": 3, "heartbeat_interval": 15}
        self.assertTrue(cfg_mgr.apply_config(v3))
        self.assertEqual(cfg_mgr.get_active_version(), 3)

        # Rollback to v2
        self.assertTrue(cfg_mgr.rollback())
        self.assertEqual(cfg_mgr.get_active_version(), 2)

    def test_sync_queue_offline_enqueuing(self):
        sync_mgr = SyncManager(self.db, self.api)

        res = {
            "id": "test-res-001",
            "test_type": "speedtest",
            "download_mbps": 55.4,
            "upload_mbps": 12.8,
            "latency_ms": 14.2,
        }
        qid = sync_mgr.enqueue_result(res)
        self.assertEqual(qid, "test-res-001")

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status, entity_id FROM sync_queue WHERE entity_id = 'test-res-001'")
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["status"], SyncStatus.PENDING.value)
            self.assertEqual(row["entity_id"], "test-res-001")

    def test_health_monitor_metrics(self):
        hm = HealthMonitor()
        metrics = hm.get_metrics()
        self.assertIn("cpu_usage", metrics)
        self.assertIn("ram_usage", metrics)
        self.assertIn("disk_usage", metrics)
        self.assertIn("uptime", metrics)
        self.assertIn("ip_address", metrics)
        self.assertGreaterEqual(metrics["uptime"], 0)

    def test_network_diagnostics_interfaces(self):
        ifaces = NetworkDiagnostics.get_interface_stats()
        self.assertIsInstance(ifaces, list)
        self.assertGreater(len(ifaces), 0)
        self.assertIn("interface", ifaces[0])

    def test_lcd_and_buttons_mock(self):
        lcd = LCDDisplay()
        lcd.display_status("Test Line 1", "Test Line 2")
        lcd.show_test_result(dl_mbps=100.0, ul_mbps=50.0, latency=5.2)
        lcd.clear()

        start_pressed = False
        reset_pressed = False

        def on_start():
            nonlocal start_pressed
            start_pressed = True

        def on_reset():
            nonlocal reset_pressed
            reset_pressed = True

        btn = ButtonHandler(
            pin_start=5,
            pin_reset=6,
            on_start_press=on_start,
            on_reset_press=on_reset,
        )
        btn.trigger_mock_start()
        btn.trigger_mock_reset()
        self.assertTrue(start_pressed)
        self.assertTrue(reset_pressed)
        btn.cleanup()


if __name__ == "__main__":
    unittest.main()
