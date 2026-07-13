"""Feishu Card Feedback HTTP Server (ngrok tunnel mode).

Receives feedback via URL button clicks.
Buttons are URL-type (no Feishu callback config needed):
  GET /api/feedback?useful=true&date=2026-07-12
"""

import json
import os
import sys
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

FEEDBACK_FILE = Path("data/feedback.jsonl")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        p = urlparse(self.path)
        if p.path == "/api/feedback":
            qs = parse_qs(p.query)
            useful = qs.get("useful", ["unknown"])[0]
            date = qs.get("date", [""])[0]

            entry = {
                "timestamp": datetime.now().isoformat(),
                "useful": useful == "true",
                "date": date,
            }
            FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(FEEDBACK_FILE, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            print(f"[{entry['timestamp']}] 反馈: useful={entry['useful']} date={date}")

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                "<html><body style='font-family:sans-serif;text-align:center;padding:40px'>"
                "<h2>感谢反馈！</h2><p>新闻小助手会持续优化 🙏</p>"
                "</body></html>".encode("utf-8")
            )
        elif p.path == "/api/health":
            self._json(200, {"status": "ok"})
        else:
            self._json(200, {"status": "ok"})

    def do_POST(self):
        self._json(200, {"status": "ok"})

    def _json(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(body, ensure_ascii=False).encode("utf-8"))

    def log_message(self, fmt, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]}")


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=5099)
    args = p.parse_args()

    print(f"Card feedback HTTP server on :{args.port}")
    HTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
