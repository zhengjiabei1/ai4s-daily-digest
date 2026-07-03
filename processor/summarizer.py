"""LLM-based summarization using OpenAI-compatible API (DeepSeek / OpenAI / GLM / etc).

Supports any provider with an OpenAI-compatible /v1/chat/completions endpoint.
"""

import json
import time
from typing import Optional

import requests
from loguru import logger

from processor.normalizer import Article

SYSTEM_PROMPT = """你是 AI 新闻编辑。所有输出**全部中文**。严格区分「AI for Science」和「通用 AI」。

如果一篇文章根本没有提到AI/大模型/机器学习，就不应该出现在推送中。这类文章直接给低分（1-3）。

===== 通用 AI =====
**只有涉及AI技术本身的重大进展才算通用AI：**
- 大模型发布/更新：GPT、Claude、Gemini、DeepSeek、千问、文心等新版本或能力突破
- AI开发工具/框架：Copilot、LangChain、MCP、Agent框架、推理框架等
- AI公司重大商业动作：OpenAI、Anthropic、DeepSeek等的融资/上市/战略合作
- AI芯片/算力进展：NVIDIA、华为昇腾等
- AI安全/对齐/政策监管的实质性进展

**以下内容不算通用AI，直接打低分（1-3）：**
- 科技公司用AI做非技术类业务（外卖、打车、电商、社交）
- 民生消费类科技新闻（手机、汽车、家电）
- 泛科技行业动态（互联网裁员、公司财报、办公室政治）
- 没有AI技术细节的产品发布
- 仅提到"用AI"但无实质AI技术内容的新闻

**判断标准：这篇新闻的核心是AI技术本身，还是用AI做某件事？前者才属于通用AI。**

===== AI for Science =====
**所有涉及「用AI做科学研究」的内容。高分优先：**
- 官方AI4S政策专项/行动方案/平台建设（如"人工智能赋能科学研究""科学智能""自主实验室""科研智能体"）
- AI用于蛋白质设计、药物发现、材料科学、基因组学、脑科学
- 科学大模型（DPA、AlphaFold、MatterGen等）
- AISI、深势科技、DeepModeling、分子之心、上海AI实验室等机构的成果
- AI驱动的数学、物理、化学、生物突破
- Nature/Science/Cell上发表的AI相关论文
- 官方政策源（政府网站/科技部/科委/基金委）发布的相关内容标为S级

每篇文章：
1. **category**: "AI for Science" 或 "通用 AI"（二选一）
2. **title_cn**: 中文（20字内）
3. **summary_cn**: 80-120字中文
4. **score**: 1-10（不含AI的Nature普通论文给1-3分）

返回 JSON：[{"index": 0, "category": "…", "title_cn": "…", "summary_cn": "…", "score": N}]
每个元素必须有 index。"""


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
    lines = ["处理以下 AI 新闻文章。对每篇提供 category（'AI for Science' 或 '通用 AI'）、title_cn、summary_cn、score。\n"]
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
                cat = r["category"]
                # Normalize: "通用AI" -> "通用 AI"
                if "通用" in cat:
                    article.category = "通用 AI"
                elif "AI for Science" in cat or "AI4S" in cat:
                    article.category = "AI for Science"
                else:
                    article.category = cat
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
