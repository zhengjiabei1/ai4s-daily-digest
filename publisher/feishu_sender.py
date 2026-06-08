"""Feishu (Lark) message sender for interactive cards and text messages.

Supports sending to both group chats (chat_id starting with 'oc_')
and individual users (open_id starting with 'ou_').
"""

import json
import time

import requests
from loguru import logger

FEISHU_SEND_URL = "https://open.feishu.cn/open-apis/im/v1/messages"


def _detect_id_type(receive_id: str) -> str:
    """Auto-detect the Feishu receive_id type.

    - chat_id: starts with 'oc_'
    - open_id: starts with 'ou_' (user's open_id)
    - user_id: starts with other patterns
    """
    if receive_id.startswith("oc_"):
        return "chat_id"
    elif receive_id.startswith("ou_"):
        return "open_id"
    elif receive_id.startswith("on_"):
        return "union_id"
    else:
        return "user_id"


def send_card(
    card: dict,
    chat_id: str,
    token: str,
    max_retries: int = 3,
) -> bool:
    """Send an interactive card message to a Feishu chat or user.

    Args:
        card: Feishu card JSON as a dict.
        chat_id: Target ID (chat_id for groups, open_id for users).
        token: Valid tenant access token.
        max_retries: Maximum send attempts.

    Returns:
        True if the message was sent successfully, False otherwise.
    """
    card_str = json.dumps(card, ensure_ascii=False)
    receive_id_type = _detect_id_type(chat_id)

    payload = {
        "receive_id": chat_id,
        "msg_type": "interactive",
        "content": card_str,
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }

    params = {"receive_id_type": receive_id_type}

    for attempt in range(max_retries):
        try:
            resp = requests.post(
                FEISHU_SEND_URL,
                params=params,
                json=payload,
                headers=headers,
                timeout=15,
            )
            data = resp.json()
            code = data.get("code", -1)

            if code == 0:
                logger.info(
                    f"Card sent successfully to {receive_id_type}={chat_id}: "
                    f"message_id={data.get('data', {}).get('message_id', '?')}"
                )
                return True
            else:
                logger.error(
                    f"Feishu send failed: code={code} msg={data.get('msg', '')}"
                )
                # Non-retryable errors
                if code in (10003, 10012, 230001, 230002):
                    logger.error(f"Non-retryable error code={code}, aborting")
                    return False

        except requests.RequestException as e:
            logger.error(
                f"Feishu send request failed (attempt {attempt + 1}): {e}"
            )

        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)

    logger.error(f"Failed to send card after {max_retries} attempts")
    return False


def send_text(
    text: str,
    chat_id: str,
    token: str,
    max_retries: int = 2,
) -> bool:
    """Send a plain text message to a Feishu chat or user.

    Args:
        text: Plain text message content.
        chat_id: Target ID (chat_id for groups, open_id for users).
        token: Valid tenant access token.
        max_retries: Maximum send attempts.

    Returns:
        True if sent successfully, False otherwise.
    """
    receive_id_type = _detect_id_type(chat_id)

    payload = {
        "receive_id": chat_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}, ensure_ascii=False),
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }

    params = {"receive_id_type": receive_id_type}

    for attempt in range(max_retries):
        try:
            resp = requests.post(
                FEISHU_SEND_URL,
                params=params,
                json=payload,
                headers=headers,
                timeout=15,
            )
            data = resp.json()
            code = data.get("code", -1)

            if code == 0:
                logger.info(
                    f"Text sent successfully to {receive_id_type}={chat_id}"
                )
                return True
            else:
                logger.error(
                    f"Feishu send text failed: code={code} msg={data.get('msg', '')}"
                )
                return False

        except requests.RequestException as e:
            logger.error(
                f"Feishu send text request failed (attempt {attempt + 1}): {e}"
            )

        if attempt < max_retries - 1:
            time.sleep(1)

    return False
