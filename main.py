#!/usr/bin/env python3
"""Daily AI News Aggregator and Feishu Push System.

Pushes a digest of yesterday's AI news to Feishu.
The first run for a date fetches, summarizes, and saves the card to cache.
Any re-run for the same date replays the cached card — identical output,
zero extra cost.  Yesterday's news does not change.
"""

import os
import sys
from datetime import date, datetime, timedelta

from loguru import logger

from processor.date_filter import filter_by_date
from processor.deduplicator import deduplicate
from processor.formatter import build_card
from processor.normalizer import normalize
from processor.summarizer import summarize_with_llm
from publisher.feishu_auth import get_tenant_access_token
from publisher.feishu_sender import send_card
from sources.registry import SourceRegistry
from utils.config_loader import load_config
from utils.daily_state import get_cached_card, save_card
from utils.logger import setup_logging


def main():
    config = load_config()
    setup_logging(
        log_dir=config.get("logging", {}).get("log_dir", "logs"),
        level=config.get("logging", {}).get("level", "INFO"),
    )

    # Target: yesterday
    today = date.today()
    yesterday = today - timedelta(days=1)

    logger.info("=" * 60)
    logger.info(f"每日新闻速递 - 推送 {yesterday} 的新闻")
    logger.info("=" * 60)

    # ---- Cache hit: replay identical card ----
    cached = get_cached_card(yesterday)
    if cached is not None:
        logger.info(f"{yesterday} 已有缓存，直接推送（不重新抓取）")
        return _push(cached, config, yesterday)

    # ---- Cache miss: full pipeline ----
    registry = SourceRegistry(config)

    # 1. Fetch
    logger.info("第 1 步：抓取新闻...")
    raw_articles = registry.fetch_all()
    if not raw_articles:
        logger.error("没有抓取到任何文章")
        sys.exit(1)

    # 2. Normalize
    logger.info("第 2 步：格式化...")
    articles = normalize(raw_articles)

    # 3. Filter to yesterday
    logger.info("第 3 步：筛选前一天的内容...")
    yesterday_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    articles = filter_by_date(articles, target_date=yesterday_dt, days_window=3)
    if not articles:
        logger.warning(f"没有找到 {yesterday} 的新闻，跳过推送")
        return 0

    # 4. Deduplicate
    logger.info("第 4 步：去重...")
    dedup_threshold = config.get("processing", {}).get("dedup_threshold", 85)
    articles = deduplicate(articles, threshold=dedup_threshold)

    # 5. LLM
    logger.info("第 5 步：AI 摘要和分类...")
    llm_config = config.get("llm", config.get("anthropic", {}))
    api_key = llm_config.get("api_key", "")
    if api_key.startswith("${"):
        api_key = os.environ.get(api_key.strip("${}"), "")

    if api_key:
        try:
            articles = summarize_with_llm(
                articles,
                api_key=api_key,
                api_base=llm_config.get("api_base", "https://api.deepseek.com/v1"),
                model=llm_config.get("model", "deepseek-v4-flash"),
                max_tokens=llm_config.get("max_tokens", 4096),
                temperature=llm_config.get("temperature", 0),
                batch_size=config.get("processing", {}).get("batch_size_for_llm", 15),
            )
        except Exception as e:
            logger.error(f"LLM 摘要失败: {e}")
    else:
        logger.warning("未配置 LLM API Key，使用原始摘要")

    # 6. Diversity-first selection: ensure balanced coverage across themes
    min_score = config.get("processing", {}).get("min_score", 4)
    articles.sort(key=lambda a: a.score, reverse=True)
    high_impact = [a for a in articles if a.score >= min_score]
    max_primary = config.get("processing", {}).get("max_articles_for_primary_card", 10)

    if not high_impact:
        logger.warning(f"没有 >= {min_score} 分的文章，使用得分最高的 {max_primary} 篇")
        high_impact = articles[:max_primary]

    primary_articles = _select_diverse(high_impact, max_primary)

    logger.info(
        f"高分文章（>= {min_score}）：{len(high_impact)} 篇，"
        f"推送 {len(primary_articles)} 篇"
    )

    # 7. Build card
    logger.info("第 6 步：生成飞书卡片...")
    card = build_card(primary_articles, digest_date=yesterday)

    # 8. Save to cache — so re-runs are identical
    save_card(yesterday, card)
    logger.info(f"已缓存 {yesterday} 的卡片，之后重复运行不会变化")

    return _push(card, config, yesterday)


def _select_diverse(articles: list, max_count: int) -> list:
    """Select articles with balanced coverage across two themes."""
    group_ai4s = {"科研论文"}
    group_general_ai = {"大模型发布", "开源工具", "行业动态", "融资收购", "政策监管"}

    groups = {
        "ai4s": ([a for a in articles if a.category in group_ai4s], 6),
        "general_ai": ([a for a in articles if a.category in group_general_ai], 2),
    }

    for key in groups:
        groups[key] = (sorted(groups[key][0], key=lambda a: a.score, reverse=True), groups[key][1])

    selected = []
    used = set()

    for key, (group_articles, quota) in groups.items():
        taken = 0
        for a in group_articles:
            if taken >= quota or len(selected) >= max_count:
                break
            if id(a) not in used:
                selected.append(a)
                used.add(id(a))
                taken += 1

    if len(selected) < max_count:
        remaining = [a for a in articles if id(a) not in used]
        remaining.sort(key=lambda a: a.score, reverse=True)
        for a in remaining:
            if len(selected) >= max_count:
                break
            selected.append(a)

    selected.sort(key=lambda a: a.score, reverse=True)

    cat_counts = {}
    for a in selected:
        cat_counts[a.category] = cat_counts.get(a.category, 0) + 1
    logger.info(f"多样性分布: {cat_counts}")

    return selected


def _push(card: dict, config: dict, target_date: date) -> int:
    """Authenticate and push the card to Feishu. Return 0 on success, 1 on failure."""
    logger.info("连接飞书...")
    feishu_config = config.get("feishu", {})
    try:
        token = get_tenant_access_token(
            app_id=feishu_config["app_id"],
            app_secret=feishu_config["app_secret"],
        )
    except Exception as e:
        logger.error(f"飞书认证失败: {e}")
        sys.exit(1)

    logger.info("推送消息...")
    chat_id = feishu_config.get("chat_id", "")
    if not chat_id:
        logger.error("未配置 chat_id / open_id")
        sys.exit(1)

    success = send_card(card, chat_id=chat_id, token=token)
    if success:
        logger.info(f"✅ {target_date} 每日新闻推送成功！")
        return 0
    else:
        logger.error(f"❌ {target_date} 每日新闻推送失败！")
        return 1


if __name__ == "__main__":
    sys.exit(main())
