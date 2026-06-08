"""Feishu interactive card JSON formatter.

Format: flat list, one line per article, no emojis, no stats line, no footer.
Format: 序号. <blue bold title>：简介（[原文](url)）
"""

from datetime import date
from typing import Any

from processor.normalizer import Article

MAX_CARD_BYTES = 30_000


def build_card(
    articles: list[Article],
    digest_date: date,
) -> dict[str, Any]:
    """Build a Feishu interactive card.

    - Header: "每日新闻速递 | YYYY-MM-DD"
    - Each item: blue bold title, summary, clickable link
    - No footer, no stats line, no emojis
    """
    date_str = digest_date.strftime("%Y-%m-%d")
    lines = []

    for i, article in enumerate(articles, 1):
        summary = article.final_summary()
        if len(summary) > 120:
            summary = summary[:120] + "..."
        url = article.url or ""

        if url:
            lines.append(
                f"<font color='blue'>**{i}. {article.display_title()}**</font>"
                f"：{summary}（{url}）"
            )
        else:
            lines.append(
                f"<font color='blue'>**{i}. {article.display_title()}**</font>"
                f"：{summary}"
            )

    content = "\n\n".join(lines)

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"AISI 每日速递 | {date_str}",
            },
            "template": "blue",
        },
        "elements": [
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": content},
            },
        ],
    }

    card = _trim_to_limit(card, articles)
    return card


def _trim_to_limit(
    card: dict[str, Any], articles: list[Article]
) -> dict[str, Any]:
    """Trim by removing lowest-scored articles until under 30KB."""
    import json

    card_str = json.dumps(card, ensure_ascii=False)
    if len(card_str.encode("utf-8")) <= MAX_CARD_BYTES:
        return card

    remaining = sorted(articles, key=lambda a: a.score, reverse=True)
    while len(card_str.encode("utf-8")) > MAX_CARD_BYTES and len(remaining) > 1:
        remaining.pop()
        new_card = build_card(remaining, date.today())
        card_str = json.dumps(new_card, ensure_ascii=False)
        card = new_card

    return card
