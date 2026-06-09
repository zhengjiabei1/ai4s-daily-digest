"""LLM-based summarization using OpenAI-compatible API (DeepSeek / OpenAI / GLM / etc).

Supports any provider with an OpenAI-compatible /v1/chat/completions endpoint.
"""

import json
import time
from typing import Optional

import requests
from loguru import logger

from processor.normalizer import Article

SYSTEM_PROMPT = """你是一个 AI 新闻编辑，同时关注 AI for Science（AI4S）与通用 AI 重大进展。评分要合理，不要过于严格。

【AI for Science（AI4S）— 重点关注】
- 物质科学：新材料发现、催化剂、电池、半导体、大原子模型（DPA4）、MatterGen
- 生命科学：蛋白质结构预测/设计（AlphaFold、MMFold）、药物发现、基因组学、抗体设计、脑科学
- 数学物理：定理证明、物理模拟、量子计算
- 重点机构：AISI、深势科技、分子之心、智源研究院、清华、北大、浙大、Stanford、MIT、DeepMind
- 顶刊顶会：Nature、Science、Cell、NeurIPS、ICML、ICLR

【通用 AI 重大进展 — 同等重视】
- 主流大模型发布更新：GPT/ChatGPT、Claude、Gemini、DeepSeek、千问/Qwen、豆包、文心、智谱/GLM、Kimi、LLaMA、Mistral、Grok
- 科技巨头重要 AI 动作：OpenAI、Anthropic、Google、Microsoft、Meta、字节、阿里、华为、腾讯、NVIDIA
- 重磅开源项目与工具
- 重大融资（> 1 亿美元）/ IPO / 收购

评分标准（宽松一些，好内容给 5-9 分很常见）：
- 8-10：GPT/Claude 重大发布、Nature/Science 论文、AISI/DeepMind 级成果、超 5 亿美元融资
- 6-7：主流大模型更新、好的 AI4S 论文、大公司重要 AI 产品、超 1 亿美元融资
- 4-5：普通的 AI 新闻、值得关注的新工具/论文、一般行业动态 —— 大部分内容应该在这个范围
- 1-3：纯营销稿、灌水论文、与 AI 无关、完全不值得推送

每篇文章：
1. **tag**: 主题标签如 "AI4S·材料"、"通用AI·模型"、"通用AI·商业"（6字内）
2. **title_cn**: 英文翻译为中文（15字内），中文保持原样
3. **summary_cn**: 100-200字中文新闻简报，包含日期、机构、突破、意义
4. **category**: 科研论文 | 大模型发布 | 开源工具 | 行业动态 | 融资收购 | 政策监管
5. **score**: 按上述标准打分

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
                if results is not None and len(results) > 0:
                    # Success — apply and break
                    _apply_llm_results(batch, results, batch_start)
                    logger.info(f"LLM batch {batch_start}: OK {len(results)} results, score sample: {[r.get('score','?') for r in results[:3]]}")
                    break
                else:
                    logger.info(f"LLM batch {batch_start}: parse returned {type(results).__name__} len={len(results) if results else 'N/A'}, raw[200]: {content[:200]}")
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
        # Fallback: if no exact index match, try sequential match
        if r is None and i < len(results):
            r = results[i]
            if not isinstance(r, dict) or "index" not in r:
                r = None

        if r is not None:
            article.title_cn = r.get("title_cn", "")[:30]
            article.llm_summary = r.get("summary_cn", "")[:300]
            article.score = float(r.get("score", 5))
            article.llm_score = int(r.get("score", 5))
            if "category" in r:
                article.category = r["category"]
            if "tag" in r:
                article.tag = r["tag"][:10]
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
