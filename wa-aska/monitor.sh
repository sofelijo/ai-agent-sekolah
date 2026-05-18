#!/bin/bash

# Monitor Script - Real-time monitoring untuk server dan ngrok
# Usage: bash monitor.sh

echo "=================================================="
echo "ASKA WhatsApp Bot - Real-time Monitor"
echo "=================================================="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check ngrok status
echo -e "${YELLOW}🔍 Checking Ngrok Status...${NC}"
if curl -s http://127.0.0.1:4040/api/tunnels > /dev/null 2>&1; then
    NGROK_URL=$(curl -s http://127.0.0.1:4040/api/tunnels | python3 -c "import sys, json; print(json.load(sys.stdin)['tunnels'][0]['public_url'])" 2>/dev/null)
    if [ -n "$NGROK_URL" ]; then
        echo -e "${GREEN}✅ Ngrok Active${NC}"
        echo "   URL: $NGROK_URL"
        echo "   Webhook: $NGROK_URL/webhook"
    else
        echo -e "${RED}❌ Ngrok not responding${NC}"
    fi
else
    echo -e "${RED}❌ Ngrok not running${NC}"
    echo "   Start with: ngrok http 8000"
fi

echo ""

# Check server status
echo -e "${YELLOW}🔍 Checking Server Status...${NC}"
if curl -s http://127.0.0.1:8000/health > /dev/null 2>&1; then
    HEALTH=$(curl -s http://127.0.0.1:8000/health)
    echo -e "${GREEN}✅ Server Active${NC}"
    echo "   Health: $(echo $HEALTH | python3 -c "import sys, json; data=json.load(sys.stdin); print(f\"Status={data['status']}, Cache={data['cache_size']}\")")"
else
    echo -e "${RED}❌ Server not responding${NC}"
    echo "   Start with: bash start.sh"
fi

echo ""

# Show recent logs
echo -e "${YELLOW}📜 Recent Server Logs (last 10 lines):${NC}"
echo "=================================================="
if [ -f "bot.log" ]; then
    tail -10 bot.log
else
    echo "No logs yet"
fi

echo ""
echo "=================================================="
echo -e "${YELLOW}💡 Commands:${NC}"
echo "   Monitor logs: tail -f bot.log"
echo "   Check cache: curl http://127.0.0.1:8000/health | python3 -m json.tool"
echo "   Ngrok web UI: http://127.0.0.1:4040"
echo "=================================================="
