"""Feishu Event Subscription Webhook (Vercel Serverless).

Deploy to Vercel → get public URL → configure in Feishu Event Subscriptions.

Handles:
- URL verification (GET challenge)
- im.message.receive_v1 — receives group chat messages
- Analyzes feedback with DeepSeek, replies to the user
"""

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from io import BytesIO

import requests

FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
FEISHU_VERIFICATION_TOKEN = os.environ.get("FEISHU_VERIFICATION_TOKEN", "")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

FEISHU_AUTH_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
FEISHU_REPLY_URL = "https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply"
FEISHU_SEND_URL = "https://open.feishu.cn/open-apis/im/v1/messages"


# ── Auth ─────────────────────────────────────────────────────────


def _get_feishu_token() -> str:
    if hasattr(_get_feishu_token, "_cached") and _get_feishu_token._cached:
        token, expires = _get_feishu_token._cached
        if time.time() < expires - 300:
            return token
    resp = requests.post(
        FEISHU_AUTH_URL,
        json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=15,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Auth failed: {data.get('msg')}")
    token = data["tenant_access_token"]
    _get_feishu_token._cached = (token, time.time() + data.get("expire", 7200))
    return token


# ── DeepSeek Analysis ────────────────────────────────────────────


def _analyze(message_text: str, sender: str) -> dict:
    if not DEEPSEEK_API_KEY:
        return {"action": "unknown", "summary": "DeepSeek not configured"}

    prompt = f"""分析这条对「AISI 每日新闻速递」的反馈意见。判断用户的需求类型和具体修改内容。

反馈人: {sender}
内容: {message_text}

用以下 JSON 格式回复（只返回 JSON）：
{{"action": "source|score|quota|format|push|other", "summary": "一句话总结（20字内）", "detail": "具体修改建议（50字内）"}}"""

    try:
        resp = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            json={"model": "deepseek-v4-flash", "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 200, "temperature": 0},
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
            timeout=30,
        )
        text = resp.json()["choices"][0]["message"]["content"]
        s = text.find("{"); e = text.rfind("}") + 1
        return json.loads(text[s:e]) if s >= 0 and e > s else {}
    except Exception as e:
        return {"action": "unknown", "summary": f"分析出错: {e}"}


# ── Reply ────────────────────────────────────────────────────────


def _reply(message_id: str, text: str, token: str) -> bool:
    try:
        r = requests.post(
            FEISHU_REPLY_URL.format(message_id=message_id),
            json={"content": json.dumps({"text": text}, ensure_ascii=False), "msg_type": "text"},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
            timeout=15,
        )
        return r.json().get("code") == 0
    except Exception:
        return False


# ── Main Handler ─────────────────────────────────────────────────


class WebhookHandler:
    @staticmethod
    def handle(method: str, query: dict, headers: dict, body: str) -> dict:
        """Process incoming request. Returns Vercel-compatible response dict."""

        # ── URL Verification (Feishu event subscription setup) ──
        if method == "GET" or (method == "POST" and query.get("type") == "url_verification"):
            # Check for challenge in body
            try:
                data = json.loads(body) if body else {}
                if data.get("type") == "url_verification":
                    return _json_response(200, {"challenge": data.get("challenge", "")})
            except Exception:
                pass
            return _json_response(200, {"code": 0, "msg": "webhook alive"})

        # ── POST: Event handling ──
        if method != "POST":
            return _json_response(405, {"error": "method not allowed"})

        try:
            event_data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            return _json_response(400, {"error": "invalid json"})

        # Event verification
        header = event_data.get("header", {})
        event_type = header.get("event_type", "")

        if event_type != "im.message.receive_v1":
            return _json_response(200, {"code": 0, "msg": "event ignored"})

        # Extract message
        event = event_data.get("event", {})
        msg = event.get("message", {})
        content_str = msg.get("content", "{}")
        message_id = msg.get("message_id", "")
        chat_id = msg.get("chat_id", "")

        text = ""
        try:
            c = json.loads(content_str)
            text = c.get("text", "").strip()
        except Exception:
            text = content_str

        if not text:
            return _json_response(200, {"code": 0, "msg": "empty message"})

        # Analyze and reply
        sender = event.get("sender", {}).get("sender_id", {})
        sender_name = sender.get("name", "用户") if isinstance(sender, dict) else str(sender)

        analysis = _analyze(text, sender_name)

        # Build polite reply
        summary = analysis.get("summary", "收到反馈")
        detail = analysis.get("detail", "")
        reply_text = f"[AISI 新闻助手收到反馈]\n{summary}"
        if detail:
            reply_text += f"\n\n具体建议: {detail}"
        reply_text += "\n\n反馈已记录，将据此优化推送内容。感谢！"

        try:
            token = _get_feishu_token()
            _reply(message_id, reply_text, token)
        except Exception as e:
            print(f"Reply error: {e}")

        # Log for debugging
        print(json.dumps({"sender": sender_name, "chat": chat_id, "msg": text, "analysis": analysis},
                         ensure_ascii=False))

        return _json_response(200, {"code": 0, "msg": "ok"})


def _json_response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json; charset=utf-8"},
        "body": json.dumps(body, ensure_ascii=False),
    }


# ── Vercel entry point ───────────────────────────────────────────


def handler(event: dict, context=None) -> dict:
    """Vercel Python serverless handler."""
    method = (event.get("httpMethod") or event.get("method") or "GET").upper()
    query = event.get("queryStringParameters") or {}

    # Get headers (normalize to lowercase for Vercel)
    raw_headers = event.get("headers") or {}
    headers = {k.lower(): v for k, v in raw_headers.items()}

    # Get body
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        import base64
        body = base64.b64decode(body).decode("utf-8", errors="replace")

    return WebhookHandler.handle(method, query, headers, body)


# ── Local dev server ─────────────────────────────────────────────

if __name__ == "__main__":
    from http.server import HTTPServer as _HTTPServer

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            result = WebhookHandler.handle("GET", {}, dict(self.headers), "")
            self._respond(result)
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            result = WebhookHandler.handle("POST", query, dict(self.headers), body)
            self._respond(result)
        def _respond(self, result):
            self.send_response(result["statusCode"])
            for k, v in result.get("headers", {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(result["body"].encode("utf-8"))

    port = int(os.environ.get("PORT", 8080))
    print(f"Webhook server on http://localhost:{port}/api/webhook")
    _HTTPServer(("0.0.0.0", port), _Handler).serve_forever()
