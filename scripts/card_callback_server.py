"""Feishu Card Feedback HTTP Server (ngrok tunnel mode).

URL buttons open a feedback webpage:
- "有用"/"没有用" 按钮 → 记录并显示感谢
- "填写修改建议" → 表单提交，通过飞书 API 发回

Run: python3 scripts/card_callback_server.py --port 5099
"""

import json
import os
import sys
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FEEDBACK_FILE = Path("data/feedback.jsonl")
AID = os.environ["FEISHU_APP_ID"]
ASEC = os.environ["FEISHU_APP_SECRET"]

HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>AISI 新闻反馈</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.card{background:#fff;border-radius:16px;padding:32px 28px;max-width:380px;width:100%;box-shadow:0 20px 60px rgba(0,0,0,.15);text-align:center}
h2{font-size:20px;color:#1f2937;margin-bottom:8px}
.sub{font-size:14px;color:#6b7280;margin-bottom:24px}
.btns{display:flex;gap:12px;margin-bottom:20px}
.btns button{flex:1;padding:14px;border:none;border-radius:12px;font-size:18px;cursor:pointer;transition:.2s}
.btn-yes{background:#ecfdf5;color:#059669;font-weight:600}
.btn-yes:hover{background:#d1fae5}
.btn-no{background:#fef2f2;color:#dc2626;font-weight:600}
.btn-no:hover{background:#fee2e2}
.section{margin-top:16px;padding-top:16px;border-top:1px solid #e5e7eb}
.section textarea{width:100%;height:80px;padding:12px;border:1px solid #d1d5db;border-radius:10px;font-size:14px;resize:none;font-family:inherit}
.btn-submit{margin-top:10px;width:100%;padding:12px;background:#667eea;color:#fff;border:none;border-radius:10px;font-size:15px;cursor:pointer;font-weight:600}
.btn-submit:hover{background:#5a6fd6}
.thanks{display:none;padding:40px 0}
.thanks h2{color:#059669;font-size:22px}
.thanks p{color:#6b7280;font-size:14px;margin-top:8px}
</style></head>
<body>
<div class="card">
  <div id="step1">
    <h2>AISI 每日新闻简报</h2>
    <div class="sub">您认为本次新闻内容是否有用？</div>
    <div class="btns">
      <button class="btn-yes" onclick="feedback(true)">👍 有用</button>
      <button class="btn-no" onclick="feedback(false)">👎 没有用</button>
    </div>
    <div class="section">
      <div class="sub" style="margin-bottom:8px">改进建议（选填）</div>
      <textarea id="suggestion" placeholder="请写下您的宝贵意见……"></textarea>
      <button class="btn-submit" onclick="submitFeedback()">提交反馈</button>
    </div>
  </div>
  <div id="step2" class="thanks">
    <h2>感谢反馈！</h2>
    <p>新闻小助手会持续优化 🙏</p>
    <p style="font-size:12px;margin-top:16px;color:#9ca3af">可关闭此页面</p>
  </div>
</div>
<script>
function feedback(useful) {
  fetch('/api/feedback?useful='+useful+'&date='+encodeURIComponent(new URLSearchParams(window.location.search).get('date')||''))
  document.getElementById('step1').style.display='none'
  document.getElementById('step2').style.display='block'
}
async function submitFeedback() {
  var text=document.getElementById('suggestion').value.trim()
  if(!text){feedback('');return}
  var d=new URLSearchParams(window.location.search).get('date')||''
  var r=await fetch('/api/suggest',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:text,date:d})})
  var j=await r.json()
  if(j.ok){document.getElementById('step1').style.display='none';document.getElementById('step2').style.display='block'}
}
</script>
</body></html>"""


def _tok():
    r = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": AID, "app_secret": ASEC},
        headers={"Content-Type": "application/json; charset=utf-8"}, timeout=15,
    )
    return r.json()["tenant_access_token"]


def _send_to_user(text: str):
    """Send suggestion as P2P message to 郑佳蓓."""
    requests.post(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id",
        json={
            "receive_id": "ou_77209a49330aea6375d44a224cd49882",
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        },
        headers={"Authorization": f"Bearer {_tok()}", "Content-Type": "application/json; charset=utf-8"},
        timeout=15,
    )


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        p = urlparse(self.path)
        if p.path == "/api/feedback":
            qs = parse_qs(p.query)
            useful = qs.get("useful", ["unknown"])[0]
            date = qs.get("date", [""])[0]
            entry = {"timestamp": datetime.now().isoformat(), "useful": useful == "true", "date": date}
            FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(FEEDBACK_FILE, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            print(f"✅ 反馈: useful={useful} date={date}")
            self._html(HTML.replace("<!--", "").replace("-->", ""))
        elif p.path == "/api/health":
            self._json(200, {"status": "ok"})
        else:
            self._html(HTML.replace("<!--", "").replace("-->", ""))

    def do_POST(self):
        p = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length == 0:
            self._json(200, {})
            return
        body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")

        # Feishu URL verification challenge
        if "challenge" in body:
            rsp = {"challenge": body["challenge"]}
            print(f"verification: {body['challenge'][:20]}...")
            self._json(200, rsp)
            return

        # Card button action callback
        action = body.get("action", {})
        value_raw = action.get("value", "") or ""
        open_id = body.get("open_id", "")
        msg_id = body.get("open_message_id", "")

        # Handle feedback
        useful = None
        if "useful" in value_raw:
            try: useful = json.loads(value_raw).get("useful")
            except: useful = "true" in value_raw
        elif value_raw == "useful": useful = True
        elif value_raw == "notuseful": useful = False

        label = "有用" if useful else "没有用" if useful is not None else "?"

        entry = {
            "timestamp": datetime.now().isoformat(),
            "user_id": open_id,
            "action": "card_click",
            "useful": useful,
            "value_raw": value_raw,
        }
        FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(FEEDBACK_FILE, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(f"📮 卡片按钮: {label} from {open_id}")

        # Reply as toast (Feishu requires this format)
        resp = {
            "toast": {"type": "success", "content": f"感谢反馈（{label}）！"},
            "card": {"type": "raw", "data": ""},  # no card update, just toast
        }
        if p.path == "/api/suggest":
            text = body.get("text", "").strip()
            date = body.get("date", "")
            if text:
                _send_to_user(f"[新闻反馈] ({date}) {text}")
                print(f"📝 建议: {text[:60]}")
            resp["toast"]["content"] = f"反馈已提交！"
        self._json(200, resp)

    def _html(self, content):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def _json(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(body, ensure_ascii=False).encode("utf-8"))

    def log_message(self, fmt, *args):
        pass


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5099)
    args = ap.parse_args()
    print(f"反馈服务在 :{args.port}")
    HTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
