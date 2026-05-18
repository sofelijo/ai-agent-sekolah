#!/bin/bash

# Wait for Webhook - Monitor untuk mendeteksi message masuk
# Usage: bash wait_for_message.sh

echo "=========================================="
echo "🎧 Listening for WhatsApp Messages..."
echo "=========================================="
echo ""
echo "Server: http://127.0.0.1:8000"
echo "Ngrok: $(curl -s http://127.0.0.1:4040/api/tunnels | python3 -c "import sys, json; print(json.load(sys.stdin)['tunnels'][0]['public_url'])" 2>/dev/null || echo 'Not running')"
echo ""
echo "Waiting for messages... (Press CTRL+C to stop)"
echo "=========================================="

# Tail logs in real-time with color highlighting
tail -f bot.log 2>/dev/null | grep --line-buffered -E "Received webhook|Processing.*messages|save command|uploaded to|error|Error|INFO" || {
    echo ""
    echo "⚠️  No log file yet. Server might not be running."
    echo "Start server with: bash start.sh"
}
