"""AISI 新闻助手 — 飞书实时回复 Bot（长连接 + P2P 轮询双通道）

长连接：接收群聊 @消息，实时回复
P2P 轮询：15 秒检查私聊消息

运行：python scripts/bot_listener.py
"""

import json, os, sys, time, threading
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from loguru import logger

AID = "cli_aaa8fee4c0389ceb"
ASEC = "sigAQkmdydoiSGW3acRrJg1swFPykKKL"
DKEY = os.environ["DEEPSEEK_API_KEY"]  # required, never hardcoded
P2P_CHAT_ID = "oc_bb0fffd0df15eb069fca2ae766504c7e"
USER_OPEN_ID = "ou_77209a49330aea6375d44a224cd49882"
STATE_FILE = Path("data/p2p_seen.json")

_cache = {"t": "", "e": 0}
def _tok():
    now = time.time()
    if _cache["e"] > now + 300:
        return _cache["t"]
    r = requests.post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": AID, "app_secret": ASEC},
        headers={"Content-Type": "application/json; charset=utf-8"}, timeout=15)
    d = r.json()
    _cache["t"] = d["tenant_access_token"]
    _cache["e"] = now + d.get("expire", 7200)
    return _cache["t"]

def _reply(msg_id, text):
    r = requests.post(f"https://open.feishu.cn/open-apis/im/v1/messages/{msg_id}/reply",
        json={"content": json.dumps({"text": text}, ensure_ascii=False), "msg_type": "text"},
        headers={"Authorization": f"Bearer {_tok()}", "Content-Type": "application/json; charset=utf-8"}, timeout=15)
    logger.info(f"回复 code={r.json().get('code')} {text[:50]}")

def _analyze(text):
    prompt = f"你是AISI每日新闻助手。回复用户消息（50字内）。\n消息: {text}"
    try:
        r = requests.post("https://api.deepseek.com/v1/chat/completions",
            json={"model": "deepseek-v4-flash", "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 150, "temperature": 0},
            headers={"Authorization": f"Bearer {DKEY}"}, timeout=15)
        return r.json()["choices"][0]["message"]["content"].strip()[:200]
    except:
        return f"收到「{text[:30]}…」，反馈已记录。"


# ── 通道 1：长连接（群聊 @ 消息）──

def ws_handler(event):
    """SDK 事件处理器：收到群聊/私聊消息 → AI 回复"""
    ev = event.event
    if not ev or not ev.message:
        return
    msg = ev.message
    msg_id = msg.message_id
    content = msg.content or ""
    body = getattr(msg, "body", None)
    if body and getattr(body, "content", None):
        content = body.content

    text = ""
    try: text = json.loads(content).get("text", "").strip()
    except: pass
    if not text or len(text) < 2:
        return

    sender = ev.sender
    name = "用户"
    if sender and sender.sender_id:
        sid = sender.sender_id
        name = getattr(sid, "name", None) or getattr(sid, "open_id", None) or str(sid)

    if "cli_" in str(name):
        return

    logger.info(f"⚡长连接 [{getattr(msg,'chat_type','?')}] {name}: {text[:60]}")
    reply = _analyze(text)
    _reply(msg_id, reply)


def run_ws():
    """在独立线程运行飞书长连接"""
    from lark_oapi.event.dispatcher_handler import EventDispatcherHandlerBuilder
    from lark_oapi.ws import Client

    builder = EventDispatcherHandlerBuilder(encrypt_key="", verification_token="")
    builder.register_p2_im_message_receive_v1(ws_handler)
    handler = builder.build()

    while True:
        try:
            client = Client(app_id=AID, app_secret=ASEC, event_handler=handler)
            logger.info("长连接: 已连接")
            client.start()
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"长连接断开: {e}, 3 秒后重连")
            time.sleep(3)


# ── 通道 2：P2P 轮询（私聊备份）──

def load_seen():
    try: return set(json.loads(STATE_FILE.read_text())) if STATE_FILE.exists() else set()
    except: return set()

def save_seen(s):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(list(s)[-500:]))

def poll_p2p():
    """15 秒轮询 P2P 私聊"""
    seen = load_seen()
    while True:
        try:
            t = _tok()
            h = {"Authorization": f"Bearer {t}", "Content-Type": "application/json; charset=utf-8"}
            r = requests.get("https://open.feishu.cn/open-apis/im/v1/messages",
                params={"container_id_type": "chat", "container_id": P2P_CHAT_ID,
                        "page_size": 5, "sort_type": "ByCreateTimeDesc"},
                headers=h, timeout=10)
            if r.json().get("code") == 0:
                for m in r.json().get("data", {}).get("items", []):
                    mid = m.get("message_id", "")
                    if mid in seen:
                        continue
                    seen.add(mid)
                    if m.get("sender", {}).get("id") == AID:
                        continue
                    body = m.get("body", {}).get("content", "")
                    text = ""
                    try: text = json.loads(body).get("text", "").strip()
                    except: pass
                    if text:
                        logger.info(f"📨私聊: {text[:60]}")
                        _reply(mid, _analyze(text))
                save_seen(seen)
            time.sleep(15)
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"P2P轮询错误: {e}")
            time.sleep(5)


# ── 主入口 ──

def main():
    from utils.logger import setup_logging
    setup_logging(level="INFO")
    logger.info("=== AISI Bot 启动（长连接 + P2P 轮询） ===")

    # 通道 1：长连接在独立线程
    ws_thread = threading.Thread(target=run_ws, daemon=True)
    ws_thread.start()

    # 通道 2：P2P 轮询在主线程
    poll_p2p()

if __name__ == "__main__":
    main()
