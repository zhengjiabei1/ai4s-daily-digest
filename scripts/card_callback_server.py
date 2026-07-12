"""Feishu Card Action Callback Listener (long-connection mode).

Receives card.button clicks via WebSocket long connection.
No public URL needed — Feishu pushes events to us through the WS channel.

Run: python3 scripts/card_callback_server.py
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from loguru import logger

AID = os.environ["FEISHU_APP_ID"]
ASEC = os.environ["FEISHU_APP_SECRET"]
FEEDBACK_FILE = Path("data/feedback.jsonl")


def _tok():
    r = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": AID, "app_secret": ASEC},
        headers={"Content-Type": "application/json; charset=utf-8"}, timeout=15,
    )
    return r.json()["tenant_access_token"]


def _reply_to_message(msg_id: str, text: str):
    requests.post(
        f"https://open.feishu.cn/open-apis/im/v1/messages/{msg_id}/reply",
        json={"content": json.dumps({"text": text}, ensure_ascii=False), "msg_type": "text"},
        headers={"Authorization": f"Bearer {_tok()}", "Content-Type": "application/json; charset=utf-8"},
        timeout=15,
    )


def main():
    from utils.logger import setup_logging
    setup_logging(level="INFO")
    logger.info("=== 卡片回调 HTTP 服务器启动 ===")

    from http.server import HTTPServer, BaseHTTPRequestHandler

    class CardCallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self._json(200, {"status": "ok"})

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body)
            except Exception:
                self._json(400, {})
                return

            # Feishu URL verification
            if "challenge" in data:
                self._json(200, {"challenge": data["challenge"]})
                return

            # Extract feedback
            action = data.get("action", {})
            value_raw = action.get("value", "") or ""
            useful = value_raw.startswith("useful_")
            label = "有用" if useful else "没有用"
            open_id = data.get("open_id", "")

            entry = {
                "timestamp": datetime.now().isoformat(),
                "user_id": open_id,
                "action": "card_click",
                "useful": useful,
                "date": value_raw.split("_", 1)[-1] if "_" in value_raw else "",
            }
            FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(FEEDBACK_FILE, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            logger.info(f"📮 按钮反馈: {label} from {open_id}")
            self._json(200, {"toast": {"type": "success", "content": f"感谢反馈（{label}）！"}})

        def _json(self, status, body):
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(body, ensure_ascii=False).encode("utf-8"))

        def log_message(self, fmt, *args):
            logger.info(f"HTTP: {args[0]}")

    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=5099)
    args = p.parse_args()

    server = HTTPServer(("0.0.0.0", args.port), CardCallbackHandler)
    logger.info(f"HTTP 服务运行在 :{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("已停止")


if __name__ == "__main__":
    main()
