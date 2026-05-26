#!/bin/bash
# =============================================================
# Script Diagnosis cepat ketika terjadi 502 Bad Gateway
# Jalankan di server: sudo bash diagnose.sh
# =============================================================

SERVICE_NAME="aska-dashboard"
PORT="8001"

echo "====== [1] Status Gunicorn/Service ======"
systemctl status $SERVICE_NAME --no-pager -l || echo "Service tidak ditemukan!"

echo ""
echo "====== [2] Log Error Terakhir (30 baris) ======"
journalctl -u $SERVICE_NAME -n 30 --no-pager

echo ""
echo "====== [3] Cek Port $PORT ======"
ss -tlnp | grep $PORT || echo "Tidak ada proses di port $PORT!"

echo ""
echo "====== [4] Cek Memory ======"
free -h

echo ""
echo "====== [5] Cek Disk ======"
df -h /

echo ""
echo "====== [6] Log Nginx Error (10 baris) ======"
tail -20 /var/log/nginx/error.log 2>/dev/null || echo "Log nginx tidak ditemukan"

echo ""
echo "====== [7] Proses Python ======"
ps aux | grep -E "gunicorn|python" | grep -v grep || echo "Tidak ada proses python/gunicorn"

echo ""
echo "====== SOLUSI CEPAT ======"
echo "Restart service : systemctl restart $SERVICE_NAME"
echo "Lihat log live  : journalctl -u $SERVICE_NAME -f"
