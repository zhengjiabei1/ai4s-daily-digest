"""Tiny Feishu Card Callback Server.

Receives button clicks from Feishu interactive cards,
saves feedback to data/feedback.jsonl.

Deploy on Bohrium:
  python3 scripts/card_callback_server.py --port 5099

Then configure Feishu:
  Open Platform -> Card -> Card Callback URL: http://lvho1491141.bohrium.tech:5099/api/card/callback
"""

import json
import os
import sys
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from argparse import ArgumentParser

FEEDBACK_FILE = Path("data/feedback.jsonl")


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._json(200, {"status": "ok", "service": "aisi-card-callback"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid json"})
            return

        # Handle Feishu URL verification (GET with challenge)
        if "challenge" in data:
            self._json(200, {"challenge": data["challenge"]})
            return

        # Extract action value from card button
        action_value = {}
        try:
            action = data.get("action", {})
            value_str = action.get("value", "{}")
            action_value = json.loads(value_str) if isinstance(value_str, str) else value_str
        except Exception:
            pass

        # Save feedback
        entry = {
            "timestamp": datetime.now().isoformat(),
            "user_id": data.get("open_id", ""),
            "action": action_value.get("action", "unknown"),
            "useful": action_value.get("useful"),
            "date": action_value.get("date", ""),
            "raw": body[:500],
        }
        FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(FEEDBACK_FILE, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        print(f"[{entry['timestamp']}] Feedback: useful={entry['useful']} from {entry['user_id']}")

        # Return success toast message to Feishu
        self._json(200, {"toast": {"type": "success", "content": "感谢反馈！新闻小助手会继续优化"}})

    def _json(self, status: int, body: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(body, ensure_ascii=False).encode("utf-8"))

    def log_message(self, format, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]}")


def main():
    parser = ArgumentParser()
    parser.add_argument("--port", type=int, default=5099)
    args = parser.parse_args()

    server = HTTPServer(("0.0.0.0", args.port), CallbackHandler)
    print(f"Card callback server on :{args.port}")
    print(f"Set Feishu card callback URL to: http://lvho1491141.bohrium.tech:{args.port}/api/card/callback")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")


if __name__ == "__main__":
    main()
