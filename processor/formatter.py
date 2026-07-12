"""Feishu card formatter — two sections: 【AI for Science】 + 【通用 AI】."""

import json
from datetime import date
from typing import Any

from processor.normalizer import Article

MAX_CARD_BYTES = 30_000
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def build_card(articles: list[Article], digest_date: date) -> dict[str, Any]:
    """Two-section card with feedback buttons."""
    date_str = digest_date.strftime("%Y-%m-%d")
    weekday = WEEKDAYS[digest_date.weekday()]

    ai4s = [a for a in articles if "AI for Science" in a.category or a.category.startswith("AI4S")]
    general = [a for a in articles if "通用" in a.category]

    lines = []
    for section_title, section_articles in [("【AI for Science】", ai4s), ("【通用 AI】", general)]:
        if not section_articles:
            continue
        lines.append(f"**{section_title}**")
        for i, a in enumerate(section_articles, 1):
            summary = a.final_summary()
            if len(summary) > 120:
                summary = summary[:120] + "…"
            url = a.url or ""
            title = a.display_title()
            if url:
                lines.append(f"{i}. **{title}**  \n{summary}\n{url}")
            else:
                lines.append(f"{i}. **{title}**  \n{summary}")
            lines.append("")

    content = "\n".join(lines)

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"AISI 每日新闻简报 · {date_str}（{weekday}）",
            },
            "template": "blue",
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": content}},
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md",
                "content": "<font color='grey'>**您认为本次新闻内容是否有用？**</font>"}},
            {"tag": "action", "actions": [
                {"tag": "button", "text": {"tag": "plain_text", "content": "👍 有用"},
                 "type": "primary",
                 "value": json.dumps({"action": "feedback", "useful": True, "date": date_str})},
                {"tag": "button", "text": {"tag": "plain_text", "content": "👎 没有用"},
                 "type": "default",
                 "value": json.dumps({"action": "feedback", "useful": False, "date": date_str})},
            ]},
            {"tag": "hr"},
            {"tag": "action", "actions": [
                {"tag": "button", "text": {"tag": "plain_text", "content": "✍️ 提出改进意见"},
                 "type": "default",
                 "value": json.dumps({"action": "feedback_text", "date": date_str})},
            ]},
            {"tag": "div", "text": {"tag": "lark_md",
                "content": "<font color='grey'>点击上方「提出改进意见」按钮后，直接输入您的建议即可提交 🙏</font>"}},
        ],
    }
    return _trim_to_limit(card, articles)


def _trim_to_limit(card, articles):
    import json
    s = json.dumps(card, ensure_ascii=False)
    if len(s.encode("utf-8")) <= MAX_CARD_BYTES:
        return card
    remaining = sorted(articles, key=lambda a: a.score, reverse=True)
    while len(json.dumps(card, ensure_ascii=False).encode("utf-8")) > MAX_CARD_BYTES and len(remaining) > 1:
        remaining.pop()
        card = build_card(remaining, date.today())
    return card
