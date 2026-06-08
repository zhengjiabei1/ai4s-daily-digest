#!/usr/bin/env python3
"""Test script to verify Feishu message sending works.

Sends a simple text message to the configured group chat.

Usage:
    python3 scripts/test_send.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger

from publisher.feishu_auth import get_tenant_access_token
from publisher.feishu_sender import send_text
from utils.config_loader import load_config
from utils.logger import setup_logging


def main():
    config = load_config()
    setup_logging(level="INFO")

    feishu = config.get("feishu", {})
    chat_id = feishu.get("chat_id", "")

    if chat_id == "oc_xxxxxxxxxxxxxxxx":
        logger.error(
            "请先运行 'python3 scripts/find_chat_id.py' 获取 chat_id，"
            "然后更新 config.yaml"
        )
        sys.exit(1)

    logger.info("获取 Token...")
    try:
        token = get_tenant_access_token(
            feishu["app_id"], feishu["app_secret"]
        )
    except Exception as e:
        logger.error(f"认证失败: {e}")
        sys.exit(1)

    logger.info(f"向群聊 {chat_id} 发送测试消息...")
    success = send_text(
        "👋 你好！我是 AI 新闻助手，每日推送已配置成功！\n\n明天起将准时为你推送 AI 领域最新资讯。",
        chat_id=chat_id,
        token=token,
    )

    if success:
        logger.info("✅ 测试消息发送成功！")
    else:
        logger.error("❌ 测试消息发送失败，请检查 Bot 权限和群聊配置。")


if __name__ == "__main__":
    main()
