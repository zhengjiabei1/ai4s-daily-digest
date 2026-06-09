"""LLM-based summarization using OpenAI-compatible API (DeepSeek / OpenAI / GLM / etc).

Supports any provider with an OpenAI-compatible /v1/chat/completions endpoint.
"""

import json
import time
from typing import Optional

import requests
from loguru import logger

from processor.normalizer import Article

SYSTEM_PROMPT = """你是一个专业的 AI 新闻编辑。从大量文章中筛选最重要的新闻，只关注两大主题，各占一半权重。

【主题一：AI for Science（AI4S）— 50%】
- 物质科学：新材料发现、催化剂、电池、半导体、大原子模型（DPA4）、MatterGen 等
- 生命科学：蛋白质结构预测/设计（AlphaFold、MMFold）、药物发现、基因组学、抗体设计、脑科学
- 数学与物理：定理证明、物理模拟、量子计算
- 重点关注机构：AISI（北京科学智能研究院）、深势科技/DP Technology、分子之心、智源研究院、清华、北大、浙大、复旦、Stanford、MIT、CMU、Berkeley、Google DeepMind、Microsoft Research
- 顶刊论文：Nature / Science / Cell / PNAS / NeurIPS / ICML / ICLR

【主题二：通用 AI 技术进展 — 50%】
- 主流大模型发布与更新：GPT/ChatGPT、Claude、Gemini、DeepSeek、千问/Qwen、豆包、文心、智谱/GLM、Kimi、LLaMA、Mistral、Grok 等
- 科技巨头 AI 动作：OpenAI、Anthropic、Google、Microsoft、Meta、字节跳动、阿里、华为、腾讯、百度、NVIDIA
- 重要开源项目与工具：Agent 框架、推理框架、MCP 等
- 重大融资/收购（> 1 亿美元）、重要政策法规

以下打低分（1-3）：纯营销PR、小公司无影响力产品、灌水论文、与AI无关内容

对每篇文章：
1. **title_cn**: 英文翻译为中文（15字以内），中文保持原样
2. **summary_cn**: 60-100字中文摘要，信息充实
3. **category**: 科研论文 | 大模型发布 | 开源工具 | 行业动态 | 融资收购 | 政策监管
4. **score**: 1-10（10=GPT重大更新/Nature论文/AISI级成果，6-7=重要进展，4-5=值得关注，1-3=边缘）

返回 JSON 数组，不要其他文字。"""


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
