"""Feishu card formatter — two-section layout: AI4S + 通用AI."""

from datetime import date
from typing import Any

from processor.normalizer import Article

MAX_CARD_BYTES = 30_000
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

AI4S_CATEGORIES = {"科研论文"}
GENERAL_AI_CATEGORIES = {"大模型发布", "开源工具", "行业动态", "融资收购", "政策监管"}


def build_card(articles: list[Article], digest_date: date) -> dict[str, Any]:
    """Two-section card: 【AI4S】then 【通用AI】."""
    date_str = digest_date.strftime("%Y-%m-%d")
    weekday = WEEKDAYS[digest_date.weekday()]

    ai4s = [a for a in articles if a.category in AI4S_CATEGORIES]
    general = [a for a in articles if a.category in GENERAL_AI_CATEGORIES]

    lines = []

    # ── AI4S section ──
    if ai4s:
        lines.append(f"**【AI4S】**")
        for i, a in enumerate(ai4s, 1):
            summary = a.final_summary()
            if len(summary) > 120:
                summary = summary[:120] + "…"
            url = a.url or ""
            title = a.display_title()
            if url:
                lines.append(f"{i}. **{title}**  \n{summary}（{url}）")
            else:
                lines.append(f"{i}. **{title}**  \n{summary}")
            lines.append("")

    # ── 通用 AI section ──
    if general:
        lines.append(f"**【通用AI】**")
        for i, a in enumerate(general, 1):
            summary = a.final_summary()
            if len(summary) > 120:
                summary = summary[:120] + "…"
            url = a.url or ""
            title = a.display_title()
            if url:
                lines.append(f"{i}. **{title}**  \n{summary}（{url}）")
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
        ],
    }
    return _trim_to_limit(card, ai4s + general)


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
