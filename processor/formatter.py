"""Feishu interactive card formatter — matches AISI newsletter style.

Format:
  N. 【category tag】蓝色加粗标题
  详细内容段落（日期、机构、突破、意义）...（链接）
"""

from datetime import date
from typing import Any

from processor.normalizer import Article

MAX_CARD_BYTES = 30_000
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def build_card(articles: list[Article], digest_date: date) -> dict[str, Any]:
    """Build a Feishu card in AISI newsletter style.

    Header: "AI for Science & AISI 每日新闻简报 · YYYY-MM-DD（周X）"
    Each item: numbered, with category tag, bold title, detailed paragraph, URL.
    """
    date_str = digest_date.strftime("%Y-%m-%d")
    weekday = WEEKDAYS[digest_date.weekday()]
    lines = []

    for i, article in enumerate(articles, 1):
        tag = getattr(article, "tag", "") or ""
        tag_str = f"【{tag}】" if tag else ""

        summary = article.final_summary()
        url = article.url or ""

        # Title line: bold blue with tag
        lines.append(
            f"<font color='blue'>**{i}. {tag_str}{article.display_title()}**</font>"
        )

        # Content paragraph (longer, detailed)
        if url:
            lines.append(f"{summary}（{url}）")
        else:
            lines.append(summary)

        # Blank line between items
        lines.append("")

    content = "\n".join(lines)

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"AI for Science & AISI 每日新闻简报 · {date_str}（{weekday}）",
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


def _trim_to_limit(card: dict[str, Any], articles: list[Article]) -> dict[str, Any]:
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
