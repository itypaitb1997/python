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

    def test_offline_server_unreachable_clean_handling(self):
        # Point to unreachable port/IP
        offline_api = ApiClient("http://127.0.0.1:59999/api", timeout=1)
        self.assertFalse(offline_api.check_connection(timeout=1))
        self.assertFalse(offline_api.is_connected)

    def test_auth_offline_clean_fallback(self):
        offline_api = ApiClient("http://127.0.0.1:59999/api", timeout=1)
        ident = DeviceIdentity(self.db)
        from app.auth import AuthManager
        auth_mgr = AuthManager(offline_api, ident)
        # Should return False cleanly without raising exception
        success = auth_mgr.register_device()
        self.assertFalse(success)
        self.assertFalse(offline_api.is_connected)

    def test_sync_manager_offline_queue_retention(self):
        offline_api = ApiClient("http://127.0.0.1:59999/api", timeout=1)
        sync_mgr = SyncManager(self.db, offline_api)

        # Enqueue 2 items
        sync_mgr.enqueue_result({"id": "res-1", "download_mbps": 40.0, "upload_mbps": 10.0})
        sync_mgr.enqueue_result({"id": "res-2", "download_mbps": 50.0, "upload_mbps": 20.0})

        self.assertGreaterEqual(sync_mgr.get_pending_count(), 2)

        # Syncing while offline should cleanly return 0 and keep items in SQLite
        synced = sync_mgr.sync_pending()
        self.assertEqual(synced, 0)
        self.assertGreaterEqual(sync_mgr.get_pending_count(), 2)

    def test_enqueue_result_schema_adaptive(self):
        """Verify enqueue_result handles schema differences gracefully without crashing."""
        offline_api = ApiClient("http://127.0.0.1:59999/api", timeout=1)
        ident = DeviceIdentity(self.db)
        sync_mgr = SyncManager(self.db, offline_api, identity=ident)

        res = {
            "id": "test-adaptive-1",
            "test_type": "network_check",
            "download_mbps": 55.4,
            "upload_mbps": 22.1,
            "latency_ms": 14.2,
            "jitter_ms": 1.8,
            "packet_loss": 0.0,
        }
        res_id = sync_mgr.enqueue_result(res)
        self.assertEqual(res_id, "test-adaptive-1")

        # Verify saved in SQLite
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM test_results WHERE id = ?", ("test-adaptive-1",))
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["download_mbps"], 55.4)
            self.assertEqual(row["upload_mbps"], 22.1)

    def test_cli_matrix_display_rendering(self):
        from app.cli_display import CLIDisplay
        ident = DeviceIdentity(self.db)
        health = HealthMonitor()
        active_cfg = {"version": 1}

        # Should render offline cleanly with FARLINK GO logo and English notice
        CLIDisplay.render(
            identity=ident,
            health=health,
            db=self.db,
            active_config=active_cfg,
            api_url="http://192.168.1.2:5000/api",
            server_connected=False,
            notification="Testing offline mode in English",
            pending_sync_count=3,
        )

        # Also test with server_connected=True
        CLIDisplay.render(
            identity=ident,
            health=health,
            db=self.db,
            active_config=active_cfg,
            api_url="http://192.168.1.2:5000/api",
            server_connected=True,
            notification="Testing online mode in English",
            pending_sync_count=0,
        )

    def test_lcd_matrix_card_rendering(self):
        lcd = LCDDisplay()
        card_text = lcd.render_matrix_card(
            claim_code="FLG-TEST01",
            server_connected=False,
            dl_mbps=88.5,
            ul_mbps=42.1,
            latency=11.2,
            notification="Server offline - Standalone mode",
        )
        self.assertIn("FARLINK GO", card_text)
        self.assertIn("DISCONNECTED", card_text)
        self.assertIn("STANDALONE OFFLINE", card_text)

    def test_config_gpio_pins_protected(self):
        cfg_mgr = ConfigManager(self.db, self.api)
        malicious_cfg = {
            "version": 4,
            "heartbeat_interval": 45,
            "pin_start": 99,
            "pin_reset": 100,
            "FARLINK_PIN_START": 99,
            "FARLINK_PIN_RESET": 100,
        }
        self.assertTrue(cfg_mgr.apply_config(malicious_cfg))
        active = cfg_mgr.active_config
        self.assertNotIn("pin_start", active)
        self.assertNotIn("pin_reset", active)
        self.assertNotIn("FARLINK_PIN_START", active)
        self.assertNotIn("FARLINK_PIN_RESET", active)
        self.assertEqual(active["heartbeat_interval"], 45)

    def test_sqlite_logging_persistence(self):
        from app.logger import setup_logger
        test_logger = setup_logger("test_sqlite_log", level=10, db_path=self.db_path)
        test_logger.info("Test message for SQLite log storage")
        test_logger.warning("Warning message in SQLite log")

        logs = self.db.get_agent_logs(limit=10)
        self.assertTrue(len(logs) >= 2)
        messages = [l["message"] for l in logs]
        self.assertTrue(any("Test message for SQLite log storage" in m for m in messages))
        self.assertTrue(any("Warning message in SQLite log" in m for m in messages))

    def test_edge_dual_connection_measurement(self):
        from app.test_runner import TestRunner
        runner = TestRunner()
        # Run edge dual test with mock / loopback master
        res = runner.run_edge_dual_test(master_ip="127.0.0.1", iperf_duration=1)
        self.assertEqual(res["test_type"], "edge_dual")
        self.assertIn("master_connection", res)
        self.assertIn("internet_connection", res)
        self.assertEqual(res["master_connection"]["target"], "127.0.0.1")
        self.assertIn("latency_ms", res["master_connection"])
        self.assertIn("latency_ms", res["internet_connection"])


if __name__ == "__main__":
    unittest.main()


