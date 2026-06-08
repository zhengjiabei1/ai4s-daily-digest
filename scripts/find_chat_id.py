#!/usr/bin/env python3
"""Utility script to find Feishu users and chats the bot can reach.

Usage:
    python3 scripts/find_chat_id.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from loguru import logger

from publisher.feishu_auth import get_tenant_access_token
from utils.config_loader import load_config
from utils.logger import setup_logging


def main():
    config = load_config()
    setup_logging(level="INFO")

    feishu = config.get("feishu", {})
    app_id = feishu.get("app_id", "")
    app_secret = feishu.get("app_secret", "")

    logger.info("获取 Feishu 访问 Token...")
    try:
        token = get_tenant_access_token(app_id, app_secret)
    except Exception as e:
        logger.error(f"认证失败: {e}")
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }

    # ===== 1. Search for users by name =====
    print("\n" + "=" * 70)
    print("📇 查找飞书用户...")
    print("=" * 70)

    # First, try to get all users visible to the app
    users_found = []
    page_token = None
    while True:
        params = {"page_size": 50, "department_id_type": "open_department_id"}
        if page_token:
            params["page_token"] = page_token

        resp = requests.get(
            "https://open.feishu.cn/open-apis/contact/v3/users",
            params=params,
            headers=headers,
            timeout=15,
        )
        data = resp.json()
        code = data.get("code", -1)

        if code != 0:
            logger.warning(f"获取用户列表失败: code={code} msg={data.get('msg')}")
            break

        user_data = data.get("data", {})
        items = user_data.get("items", [])
        for user in items:
            name = user.get("name", "")
            open_id = user.get("open_id", "")
            user_id = user.get("user_id", "")
            if name and open_id:
                users_found.append({
                    "name": name,
                    "open_id": open_id,
                    "user_id": user_id,
                })

        if not user_data.get("has_more"):
            break
        page_token = user_data.get("page_token")

    if users_found:
        print(f"\n找到 {len(users_found)} 个用户：\n")
        for i, user in enumerate(users_found, 1):
            print(f"  [{i}] {user['name']}")
            print(f"      open_id: {user['open_id']}")
            print(f"      user_id: {user.get('user_id', 'N/A')}")
            print()

        print("提示：使用 open_id 可向该用户发送私聊消息")
        print("将 open_id 填入 config.yaml 的 feishu.chat_id 字段即可")
    else:
        print("\n未找到任何用户，请检查：")
        print("  1. 飞书开发者后台 → 权限管理 → 确认已开通 '通讯录' 权限")
        print("  2. 在飞书客户端中向 Bot 发送一条消息（如 '你好'）")

    # ===== 2. Also try to list chats =====
    print("=" * 70)
    print("💬 查找 Bot 所在群聊...")
    print("=" * 70)

    all_chats = []
    page_token = None
    while True:
        params = {"page_size": 50}
        if page_token:
            params["page_token"] = page_token

        resp = requests.get(
            "https://open.feishu.cn/open-apis/im/v1/chats",
            params=params,
            headers=headers,
            timeout=15,
        )
        data = resp.json()

        if data.get("code") != 0:
            logger.warning(f"获取群聊列表: code={data.get('code')} msg={data.get('msg')}")
            break

        chat_data = data.get("data", {})
        items = chat_data.get("items", [])
        all_chats.extend(items)

        if not chat_data.get("has_more"):
            break
        page_token = chat_data.get("page_token")

    if all_chats:
        for i, chat in enumerate(all_chats, 1):
            chat_id = chat.get("chat_id", "?")
            name = chat.get("name", "(未命名)")
            chat_type = chat.get("chat_type", "?")
            type_label = "群聊" if chat_type == "group" else "私聊"
            print(f"\n  [{i}] 名称: {name}")
            print(f"      类型: {type_label}")
            print(f"      chat_id: {chat_id}")
    else:
        print("\nBot 尚未加入任何群聊。")

    print("\n" + "=" * 70)
    print("📋 配置说明：")
    print("  - 私聊推送：将 open_id 填入 config.yaml 的 feishu.chat_id")
    print("  - 群聊推送：将群聊的 chat_id 填入 config.yaml 的 feishu.chat_id")
    print("=" * 70)


if __name__ == "__main__":
    main()
