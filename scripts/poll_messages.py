"""Feishu message poller: checks ALL chats for new messages, analyzes feedback, replies.

Runs in GitHub Actions every 10 minutes. No webhook URL needed.
"""

import json
import os
import sys
from pathlib import Path

import requests

FEISHU_APP_ID = os.environ["FEISHU_APP_ID"]
FEISHU_APP_SECRET = os.environ["FEISHU_APP_SECRET"]
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

STATE_FILE = "data/poller_state.json"
AUTH_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
CHATS_URL = "https://open.feishu.cn/open-apis/im/v1/chats"
MSG_LIST_URL = "https://open.feishu.cn/open-apis/im/v1/messages"
REPLY_URL = "https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply"


def get_token() -> str:
    resp = requests.post(
        AUTH_URL,
        json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=15,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Auth: {data.get('msg')}")
    return data["tenant_access_token"]


def load_state() -> dict:
    path = Path(STATE_FILE)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {"seen_ids": []}


def save_state(state: dict) -> None:
    path = Path(STATE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False))


def list_chats(token: str) -> list:
    """List all chats the bot belongs to."""
    all_chats = []
    page_token = None
    while True:
        params = {"page_size": 50}
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(CHATS_URL, params=params,
                           headers={"Authorization": f"Bearer {token}"}, timeout=15)
        data = resp.json()
        if data.get("code") != 0:
            print(f"List chats failed: {data.get('msg')}")
            break
        d = data.get("data", {})
        all_chats.extend(d.get("items", []))
        if not d.get("has_more"):
            break
        page_token = d.get("page_token")
    return all_chats


def get_messages(token: str, chat_id: str, page_size: int = 5) -> list:
    """Fetch recent messages from a chat."""
    id_type = "chat_id" if chat_id.startswith("oc_") else "open_id"
    resp = requests.get(
        MSG_LIST_URL,
        params={"receive_id_type": id_type, "receive_id": chat_id,
                "page_size": page_size, "sort_type": "ByCreateTimeDesc"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    data = resp.json()
    if data.get("code") != 0:
        return []
    return data.get("data", {}).get("items", [])


def extract_text(msg: dict) -> str:
    try:
        content = json.loads(msg.get("content", "{}"))
        return content.get("text", "").strip()
    except Exception:
        return ""


def analyze(text: str, sender: str) -> dict:
    if not DEEPSEEK_API_KEY:
        return {"summary": "LLM not available", "detail": ""}
    prompt = f"""分析这条对「AISI 每日新闻速递」的反馈。判断需求类型和建议。

发送者: {sender}
内容: {text}

用JSON回复:
{{"summary": "一句话总结(20字)", "detail": "修改建议(50字)", "action": "source|format|score|quota|other"}}"""
    try:
        resp = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            json={"model": "deepseek-v4-flash", "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 200, "temperature": 0},
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
            timeout=30,
        )
        t = resp.json()["choices"][0]["message"]["content"]
        s = t.find("{"); e = t.rfind("}") + 1
        return json.loads(t[s:e]) if s >= 0 and e > s else {}
    except Exception as e:
        return {"summary": str(e)[:50], "detail": ""}


def reply(token: str, message_id: str, text: str) -> bool:
    try:
        resp = requests.post(
            REPLY_URL.format(message_id=message_id),
            json={"content": json.dumps({"text": text}, ensure_ascii=False), "msg_type": "text"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        ok = resp.json().get("code") == 0
        print(f"  reply {'OK' if ok else 'FAILED'}")
        return ok
    except Exception as e:
        print(f"  reply err: {e}")
        return False


def main():
    state = load_state()
    seen = set(state.get("seen_ids", []))
    token = get_token()

    # Discover all chats
    chats = list_chats(token)
    print(f"Found {len(chats)} chats")

    total_new = 0
    for chat in chats:
        chat_id = chat.get("chat_id", "")
        chat_name = chat.get("name", chat_id)[:30]
        messages = get_messages(token, chat_id, page_size=5)

        for msg in messages:
            msg_id = msg.get("message_id", "")
            if msg_id in seen:
                continue

            msg_type = msg.get("msg_type", "")
            text = extract_text(msg) if msg_type == "text" else ""
            sender_id = msg.get("sender", {}).get("id", "unknown")

            seen.add(msg_id)

            # Skip bot's own messages and empty/textless
            if sender_id == FEISHU_APP_ID or not text or len(text) < 2:
                continue

            print(f"[{chat_name}] {sender_id}: {text[:80]}")

            analysis = analyze(text, sender_id)
            summary = analysis.get("summary", "收到反馈")
            detail = analysis.get("detail", "")
            reply_text = f"[AISI 新闻助手收到反馈]\n{summary}"
            if detail:
                reply_text += f"\n\n建议: {detail}"
            reply_text += "\n\n已记录，将优化推送。感谢！"

            reply(token, msg_id, reply_text)
            total_new += 1

    # Trim state
    state["seen_ids"] = list(seen)[-200:]
    save_state(state)

    print(f"Done. Processed {total_new} new messages.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
