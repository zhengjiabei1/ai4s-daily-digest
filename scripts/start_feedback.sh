#!/bin/bash
# Start the feedback server + ngrok tunnel for AISI News.
# Called by launchd at login to keep the feedback service always online.
set -e

PROJECT_DIR="/Users/zhengjiabei/Downloads/NEWS"
cd "$PROJECT_DIR"

# Load environment
if [ -f .env.bot ]; then
  set -a
  source .env.bot
  set +a
fi

export FEEDBACK_ADMIN_PASSWORD="${FEEDBACK_ADMIN_PASSWORD:-ainews2024}"

# Kill any existing instances
lsof -ti:5099 | xargs kill -9 2>/dev/null || true
sleep 1

# Start feedback server on port 5099
nohup ./venv/bin/python scripts/feedback_server.py --port 5099 \
  > logs/feedback_server.log 2>&1 &
echo "Feedback server PID: $!"

sleep 2

# Start ngrok tunnel
if command -v ngrok &>/dev/null; then
  pkill -f "ngrok http 5099" 2>/dev/null || true
  sleep 1
  nohup ngrok http 5099 --log=stdout \
    > logs/ngrok.log 2>&1 &
  echo "ngrok PID: $!"
  sleep 3
  # Print the public URL for convenience
  grep -o 'https://[a-z0-9.-]*\.ngrok[^"]*' logs/ngrok.log | head -1
else
  echo "WARNING: ngrok not found, feedback service is localhost only"
fi

echo "Feedback service started!"
