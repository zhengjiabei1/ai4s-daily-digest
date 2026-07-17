#!/bin/bash
# Wrapper script for macOS launchd — sources .env.bot, then runs the daily digest.
set -e
cd /Users/zhengjiabei/Downloads/NEWS

# Source environment variables
if [ -f .env.bot ]; then
  set -a
  source .env.bot
  set +a
fi

# Ensure required vars are set
: "${FEISHU_APP_ID:?not set}"
: "${FEISHU_APP_SECRET:?not set}"
: "${DEEPSEEK_API_KEY:?not set}"

# Also push to private chat
export FEISHU_PRIVATE_CHAT_ID="${FEISHU_PRIVATE_CHAT_ID:-ou_77209a49330aea6375d44a224cd49882}"

# Feedback base URL (for card button; use ngrok URL in production)
export FEEDBACK_BASE_URL="${FEEDBACK_BASE_URL:-http://localhost:5099}"

exec ./venv/bin/python main.py "$@"
