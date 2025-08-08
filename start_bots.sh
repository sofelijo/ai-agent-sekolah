#!/bin/bash
source /root/ai-agent-sekolah/venv/bin/activate

python /root/ai-agent-sekolah/bot_sekolah.py > /root/ai-agent-sekolah/log_bot_sekolah.log 2>&1 &
PID1=$!

python /root/ai-agent-sekolah/bot_data.py > /root/ai-agent-sekolah/log_bot_data.log 2>&1 &
PID2=$!

wait $PID1 $PID2
