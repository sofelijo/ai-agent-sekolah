#!/bin/bash
# =============================================================
# Script Setup & Diagnosis ASKA Dashboard di VPS Ubuntu
# Jalankan sebagai root: sudo bash setup-server.sh
# =============================================================

set -e

REPO_PATH="/opt/ai-agent-sekolah"   # ← Sesuaikan dengan path repo di server
SERVICE_NAME="aska-dashboard"
PORT="8001"

echo "======================================================"
echo " ASKA Dashboard - Setup Systemd Service"
echo "======================================================"

# --- 1. Cek apakah service sudah ada ---
if systemctl list-unit-files | grep -q "$SERVICE_NAME.service"; then
    echo "[INFO] Service $SERVICE_NAME sudah ada. Reloading..."
    systemctl stop $SERVICE_NAME || true
else
    echo "[INFO] Membuat service baru..."
fi

# --- 2. Copy service file ---
cp "$(dirname "$0")/aska-dashboard.service" /etc/systemd/system/$SERVICE_NAME.service
echo "[OK] Service file di-copy ke /etc/systemd/system/"

# --- 3. Pastikan log file ada ---
touch /var/log/aska-dashboard-access.log
touch /var/log/aska-dashboard-error.log
chown www-data:www-data /var/log/aska-dashboard-access.log
chown www-data:www-data /var/log/aska-dashboard-error.log
echo "[OK] Log files disiapkan"

# --- 4. Reload & enable service ---
systemctl daemon-reload
systemctl enable $SERVICE_NAME.service
systemctl start $SERVICE_NAME.service

echo ""
echo "======================================================"
echo " Status Service:"
echo "======================================================"
systemctl status $SERVICE_NAME.service --no-pager

echo ""
echo "======================================================"
echo " Diagnosa Port $PORT:"
echo "======================================================"
sleep 2
if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:$PORT/ | grep -qE "200|302|301"; then
    echo "[OK] App berjalan di port $PORT"
else
    echo "[WARN] App tidak merespons di port $PORT. Cek log:"
    echo "  journalctl -u $SERVICE_NAME -n 30 --no-pager"
fi

echo ""
echo "======================================================"
echo " Perintah berguna:"
echo "======================================================"
echo "  Lihat log realtime : journalctl -u $SERVICE_NAME -f"
echo "  Restart manual     : systemctl restart $SERVICE_NAME"
echo "  Stop service       : systemctl stop $SERVICE_NAME"
echo "  Status             : systemctl status $SERVICE_NAME"
echo "======================================================"
