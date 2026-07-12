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


def handle_card_action(event):
    """卡片按钮被点击 → 记录反馈 → 回复确认"""
    action_data = event.event  # P2CardActionTriggerData
    if not action_data:
        return

    # Extract action value from button
    action_value = {}
    try:
        value_raw = getattr(action_data, "action_value", "{}") or "{}"
        action_value = json.loads(value_raw)
    except Exception:
        pass

    user_id = getattr(action_data, "open_id", "") or ""
    msg_id = getattr(action_data, "open_message_id", "") or ""

    useful = action_value.get("useful")
    label = "有用" if useful else "没有用" if useful is not None else "评价"

    # Save to feedback log
    entry = {
        "timestamp": datetime.now().isoformat(),
        "user_id": user_id,
        "action": action_value.get("action", "card_click"),
        "useful": useful,
        "date": action_value.get("date", ""),
    }
    FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(FEEDBACK_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    logger.info(f"📮 按钮反馈: {label} from {user_id}")

    # Reply to confirm
    if msg_id:
        _reply_to_message(msg_id, f"感谢您的反馈（{label}）！新闻小助手会持续优化 🙏")


def main():
    from utils.logger import setup_logging
    setup_logging(level="INFO")
    logger.info("=== 卡片回调监听启动（长连接模式）===")

    from lark_oapi.event.dispatcher_handler import EventDispatcherHandlerBuilder
    from lark_oapi.ws import Client

    builder = EventDispatcherHandlerBuilder(encrypt_key="", verification_token="")
    builder.register_p2_card_action_trigger(handle_card_action)
    handler = builder.build()

    client = Client(app_id=AID, app_secret=ASEC, event_handler=handler)
    logger.info("长连接已就绪 — 卡片按钮点击将实时接收")
    client.start()


if __name__ == "__main__":
    main()
