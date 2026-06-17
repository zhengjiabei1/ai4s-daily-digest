"""LLM-based summarization using OpenAI-compatible API (DeepSeek / OpenAI / GLM / etc).

Supports any provider with an OpenAI-compatible /v1/chat/completions endpoint.
"""

import json
import time
from typing import Optional

import requests
from loguru import logger

from processor.normalizer import Article

SYSTEM_PROMPT = """你是 AI 新闻编辑。所有输出**全部中文**。必须严格区分「AI for Science」和「通用 AI」。

===== 判断标准 =====
这条新闻的核心是「用 AI 解决某个科学领域的具体问题」还是「AI 技术本身的进展」？

【AI4S = 用 AI 做科学】AI 应用于数学、物理、化学、材料、生物、医药、脑科学、地球科学、能源、天文、环境等领域的科学研究。关键词：蛋白质、药物、分子、材料、基因组、抗体、催化剂、电池、半导体、量子、神经科学、天气预报、碳核算、科学大模型。

【通用 AI = AI 技术本身】大模型发布/更新、AI 产品、AI 开源工具、AI 公司融资、AI 政策监管。关键词：GPT、Claude、Gemini、DeepSeek、千问、文心、智谱、Kimi、OpenAI、Anthropic、字节、阿里、NVIDIA、MCP、LangChain。

===== 重要：AISI/智源/深势/分子之心/磐石/浦江等机构的成果，即使涉及模型发布，只要它的应用场景是科学问题（材料、药物、蛋白质等），就属于 AI4S。=====

每篇文章：
1. **category**: 从以下 7 个值中**严格选一个**，不要自创：
   AI4S · 生物医药 | AI4S · 材料科学 | AI4S · 物理 | AI4S · 化学 | AI4S · 脑科学 | AI4S · 地球能源 | 通用 AI
2. **tag**: 中文标签（6字内），如 "AI4S · 蛋白质设计"、"DeepMind · AlphaFold"、"AISI · DPA4"、"通用 · GPT发布"、"通用 · 融资"
3. **title_cn**: 中文标题（20字内），有信息量
4. **summary_cn**: 80-120字中文摘要，谁做了什么、为什么重要
5. **score**: 1-10（AI4S 内容放宽评分，4-7分常见；通用 AI 只给真正重磅的 6+分，普通新闻 3-5分）

返回 JSON：[{"index": 0, "category": "AI4S · 生物医药", "tag": "…", "title_cn": "…", "summary_cn": "…", "score": N}, …]
每个元素必须有 index 字段。"""


def summarize_with_llm(
    articles: list[Article],
    api_key: str,
    api_base: str = "https://api.deepseek.com/v1",
    model: str = "deepseek-v4-flash",
    max_tokens: int = 4096,
    temperature: float = 0.3,
    batch_size: int = 25,
    max_retries: int = 3,
) -> list[Article]:
    """Use an OpenAI-compatible LLM to summarize, categorize, and rank articles.

    Works with: DeepSeek, OpenAI, GLM (Zhipu), Moonshot, Qwen, etc.
    Any provider with a /v1/chat/completions endpoint.

    Args:
        articles: List of normalized articles to process.
        api_key: API key for the LLM provider.
        api_base: Base URL for the API (e.g. "https://api.deepseek.com/v1").
        model: Model name (e.g. "deepseek-v4-flash", "gpt-4o", "glm-4-flash").
        max_tokens: Maximum output tokens per API call.
        temperature: Sampling temperature.
        batch_size: Articles per API call.
        max_retries: Maximum retry attempts per batch.

    Returns:
        The same articles list, updated in place with LLM fields.
    """
    if not articles:
        return articles

    api_base = api_base.rstrip("/")
    total_cost_est = 0.0

    for batch_start in range(0, len(articles), batch_size):
        batch = articles[batch_start : batch_start + batch_size]
        user_prompt = _build_batch_prompt(batch, batch_start)

        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    f"{api_base}/chat/completions",
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                    },
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=120,
                )
                resp.raise_for_status()
                data = resp.json()

                content = data["choices"][0]["message"]["content"]

                # Track token usage
                usage = data.get("usage", {})
                in_tokens = usage.get("prompt_tokens", 0)
                out_tokens = usage.get("completion_tokens", 0)
                # Cost estimates (per 1M tokens):
                # DeepSeek Flash: ¥0.12/¥0.48 input/output  (~$0.017/$0.066)
                # DeepSeek Pro: ¥0.60/¥2.40 input/output (~$0.083/$0.33)
                if "deepseek-v4-flash" in model or "deepseek-chat" in model:
                    cost = (in_tokens * 0.12 + out_tokens * 0.48) / 1_000_000
                    cost_currency = "¥"
                else:
                    cost = 0
                    cost_currency = "$"
                total_cost_est += cost
                logger.debug(
                    f"LLM batch {batch_start}: "
                    f"in={in_tokens} out={out_tokens} "
                    f"cost≈{cost_currency}{cost:.4f}"
                )

                # Parse the JSON response
                results = _parse_llm_response(content)
                if results is not None and len(results) > 0:
                    _apply_llm_results(batch, results, batch_start)
                    logger.debug(f"LLM batch {batch_start}: {len(results)} results, scores sample: {[r.get('score','?') for r in results[:3]]}")
                    break
                else:
                    logger.warning(f"LLM batch {batch_start}: empty/invalid JSON, raw[200]: {content[:200]}")
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"LLM batch {batch_start}: failed to parse JSON, "
                            f"retry {attempt + 1}/{max_retries}"
                        )
                        time.sleep(2 ** attempt)
                        continue
                    else:
                        logger.error(
                            f"LLM batch {batch_start}: failed to parse after "
                            f"{max_retries} attempts, using heuristic fallback"
                        )
                        _apply_heuristic_fallback(batch)
                        break

            except requests.RequestException as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"LLM batch {batch_start}: API error '{e}', "
                        f"retry {attempt + 1}/{max_retries}"
                    )
                    time.sleep(2 ** attempt)
                else:
                    logger.error(
                        f"LLM batch {batch_start}: failed after {max_retries} "
                        f"attempts: {e}. Using heuristic fallback."
                    )
                    _apply_heuristic_fallback(batch)
                    break

    logger.info(
        f"LLM summarization complete: {len(articles)} articles, "
        f"estimated cost ≈ {total_cost_est:.4f}"
    )
    return articles


def _build_batch_prompt(batch: list[Article], offset: int) -> str:
    """Build the user prompt for a batch of articles."""
    lines = ["处理以下 AI 新闻文章。对每篇提供 tag、title_cn、summary_cn、category、score。\n"]
    for i, article in enumerate(batch):
        idx = offset + i
        summary_text = article.summary[:300] if article.summary else "(无摘要)"
        lines.append(
            f"[{idx}] 标题: {article.title}\n"
            f"    来源: {article.source_name}\n"
            f"    原文摘要: {summary_text}\n"
        )
    return "\n".join(lines)


def _parse_llm_response(content: str) -> Optional[list[dict]]:
    """Parse the JSON array from the LLM response.

    Handles: markdown fences, leading/trailing text, truncated output,
    trailing commas before closing bracket.
    """
    text = content.strip()

    # Remove markdown code fences
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start) if "```" in text[start:] else len(text)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start) if "```" in text[start:] else len(text)
        text = text[start:end].strip()

    # Find JSON array boundaries
    array_start = text.find("[")
    array_end = text.rfind("]")
    if array_start == -1:
        logger.debug(f"No JSON array found in response: {content[:300]}...")
        return None
    if array_end == -1:
        # Truncated output — use end of text as fallback
        array_end = len(text)

    text = text[array_start : array_end + 1]

    # Fix common issues
    # Remove trailing comma before closing bracket: }, ]
    text = text.replace(", \n]", "\n]").replace(",\n]", "\n]").replace(", ]", " ]").replace(",]", "]")

    try:
        data = json.loads(text)
        if isinstance(data, list):
            if len(data) == 0:
                logger.debug("Parsed empty JSON array, treating as failure")
                return None
            return data
    except json.JSONDecodeError as e:
        logger.debug(f"JSON parse error: {e}")
        # Try to fix truncated JSON: remove last incomplete item and add ]
        last_brace = text.rfind("}")
        if last_brace > 0:
            fixed = text[:last_brace + 1] + "\n]"
            try:
                data = json.loads(fixed)
                if isinstance(data, list) and len(data) > 0:
                    logger.debug(f"Fixed truncated JSON, recovered {len(data)} items")
                    return data
            except json.JSONDecodeError:
                pass
        logger.debug(f"Raw (first 500 chars): {text[:500]}")

    return None


def _apply_llm_results(
    batch: list[Article], results: list[dict], offset: int
) -> None:
    """Apply parsed LLM results to the batch of articles."""
    result_map = {}
    for item in results:
        if isinstance(item, dict) and "index" in item:
            result_map[item["index"]] = item

    for i, article in enumerate(batch):
        # Match by prompt index OR sequential position
        llm_idx = offset + i
        r = result_map.get(llm_idx)
        # Fallback: if no exact index match, use sequential order
        if r is None and i < len(results):
            r = results[i]

        if r is not None:
            article.title_cn = r.get("title_cn", "")[:50]
            article.llm_summary = r.get("summary_cn", "")[:500]
            article.score = float(r.get("score", 5))
            article.llm_score = int(r.get("score", 5))
            if "category" in r:
                article.category = r["category"]
            if "tag" in r:
                article.tag = r["tag"][:20]
        else:
            logger.warning(f"No LLM result for article {llm_idx}, using fallback")
            article.title_cn = article.title
            article.llm_summary = article.summary[:200] if article.summary else ""
            article.score = 5.0
            article.llm_score = 5


def _apply_heuristic_fallback(batch: list[Article]) -> None:
    """Apply heuristic scoring when LLM is unavailable."""
    for article in batch:
        article.title_cn = article.title
        article.llm_summary = article.summary[:200] if article.summary else ""
        article.score = 5.0
        article.llm_score = 5
