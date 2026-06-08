"""LLM-based summarization using OpenAI-compatible API (DeepSeek / OpenAI / GLM / etc).

Supports any provider with an OpenAI-compatible /v1/chat/completions endpoint.
"""

import json
import time
from typing import Optional

import requests
from loguru import logger

from processor.normalizer import Article

SYSTEM_PROMPT = """你是一个专业的 AI for Science（AI4S）新闻编辑。你的任务是筛选报道 AI 在科学研究中的重大进展。

你关注的核心领域：
- AI 驱动的物质科学突破：新材料发现、催化剂设计、电池材料、半导体材料、大原子模型（如 DPA4）、MatterGen 等
- AI 驱动的生命科学突破：蛋白质结构预测与设计（AlphaFold、MMFold 等）、药物发现与设计、基因组学、抗体设计、脑科学
- AI 驱动的数学与物理突破：定理证明、物理模拟、量子计算
- 主流大模型在科学场景的重大应用：GPT/ChatGPT/Claude/Gemini 等用于科研的新能力
- 顶级机构的重大 AI4S 成果：AISI（北京科学智能研究院）、深势科技/DP Technology、分子之心、智源研究院、清华、北大、复旦、浙大、中科大、Stanford、MIT、CMU、Berkeley、Google DeepMind、Microsoft Research、OpenAI、Anthropic、Meta AI 等
- 发表在 Nature / Science / Cell / PNAS / 顶会最佳论文上的 AI 相关工作
- 国内外科技巨头在 AI4S 的战略布局：字节跳动、阿里、华为、腾讯、百度等
- 重大 AI 基础设施与政策：算力中心、科学智能国家战略

以下内容打低分（1-4）：
- 纯消费品类 AI 产品更新、营销文案
- 没有科学应用场景的通用聊天机器人新闻
- 小公司融资新闻（无科学影响力的）
- 与科学研究无关的行业八卦

对每篇文章提供：
1. **title_cn**: 英文标题翻译为中文（15字以内）；中文标题保持原样
2. **summary_cn**: 60-100 字中文摘要，说清楚「谁做了什么、为什么重要、有什么影响」，内容充实
3. **category**: 大模型发布 | 科研论文 | 行业动态 | 开源工具 | 融资收购 | 政策监管
4. **score**: 1-10（10=Nature/Science 级突破或顶级大模型重大科学能力发布，8-9=顶尖机构重要成果，6-7=值得关注，≤5=普通）

返回 JSON 数组：[{"index": 序号, "title_cn": "…", "summary_cn": "…", "category": "…", "score": N}, …]
只返回 JSON 数组，不要任何其他文字。"""


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
                if results is None:
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

                _apply_llm_results(batch, results, batch_start)
                logger.debug(
                    f"LLM batch {batch_start}: processed {len(batch)} articles"
                )
                break  # Success

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
    lines = ["处理以下 AI 新闻文章。对每篇提供 title_cn、summary_cn、category、score。\n"]
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
            return data
    except json.JSONDecodeError as e:
        logger.debug(f"JSON parse error: {e}")
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
        idx = offset + i
        if idx in result_map:
            r = result_map[idx]
            article.title_cn = r.get("title_cn", "")[:30]
            article.llm_summary = r.get("summary_cn", "")[:100]
            article.score = float(r.get("score", 5))
            article.llm_score = int(r.get("score", 5))
            if "category" in r:
                article.category = r["category"]


def _apply_heuristic_fallback(batch: list[Article]) -> None:
    """Apply heuristic scoring when LLM is unavailable."""
    for article in batch:
        article.title_cn = article.title
        article.llm_summary = article.summary[:100] if article.summary else ""
        article.score = 5.0
        article.llm_score = 5
