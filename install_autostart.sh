#!/bin/bash
# ==============================================================================
# FarLink Agent Autostart & Framebuffer Display Installer for Raspberry Pi 5 Lite
# ==============================================================================
set -e

echo "=== [1/5] Memeriksa Hak Akses Root ==="
if [ "$EUID" -ne 0 ]; then
  echo "[!] Jalankan script ini sebagai root: sudo bash install_autostart.sh"
  exit 1
fi

AGENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "[+] Direktori FarLink Agent: $AGENT_DIR"

echo "=== [2/5] Menginstal Dependensi Sistem (RPi OS Lite) ==="
if command -v apt-get &> /dev/null; then
  apt-get update -y
  apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    python3-pil \
    iperf3 \
    fonts-dejavu-core
fi

echo "=== [3/5] Menyiapkan Python Virtual Environment ==="
cd "$AGENT_DIR"
if [ ! -d "venv" ]; then
  python3 -m venv venv
fi
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

# Pastikan hak akses framebuffer /dev/fb* dan GPIO aman
chmod 666 /dev/fb0 2>/dev/null || true
chmod 666 /dev/fb1 2>/dev/null || true

echo "=== [4/5] Memasang systemd service untuk Autostart ==="
SERVICE_FILE="/etc/systemd/system/farlink-agent.service"
cat <<EOF > "$SERVICE_FILE"
[Unit]
Description=FarLink Edge & Go Agent Service (Raspberry Pi 5)
After=network-online.target local-fs.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$AGENT_DIR
ExecStart=$AGENT_DIR/venv/bin/python3 -m app.main
Restart=always
RestartSec=5s
EnvironmentFile=-/etc/farlink/agent.env
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo "=== [5/5] Mengaktifkan dan Menjalankan Service ==="
systemctl daemon-reload
systemctl enable farlink-agent.service
systemctl restart farlink-agent.service

echo ""
echo "======================================================================"
echo " FarLink Agent berhasil dipasang dan otomatis berjalan saat boot!"
echo " Status Service: systemctl status farlink-agent"
echo " Live Log      : journalctl -u farlink-agent -f"
echo " Stop Service  : sudo systemctl stop farlink-agent"
echo " Restart       : sudo systemctl restart farlink-agent"
echo "======================================================================"
