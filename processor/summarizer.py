"""LLM-based summarization using OpenAI-compatible API (DeepSeek / OpenAI / GLM / etc).

Supports any provider with an OpenAI-compatible /v1/chat/completions endpoint.
"""

import json
import time
from typing import Optional

import requests
from loguru import logger

from processor.normalizer import Article

SYSTEM_PROMPT = """你是一个 AI for Science（AI4S）专业新闻编辑。你的核心使命是筛选 AI 驱动科学发现的重大进展，同时适度关注通用 AI 技术中真正有影响力的事件。评分必须明显偏向 AI4S 内容。

【核心关注：AI for Science（AI4S）— 评分优先】
- 物质科学：新材料发现、催化剂、电池、半导体、大原子模型（DPA4）、MatterGen、AI 驱动的材料基因组等
- 生命科学：蛋白质结构预测与设计（AlphaFold、MMFold、RFdiffusion 等）、药物发现与设计（分子生成、ADMET 预测）、基因组学、抗体设计（纳米抗体、双抗）、脑科学（Brainμ 等多模态模型）
- 数学与物理：定理证明、物理模拟、量子计算、气候建模
- 重点关注机构的一切成果：AISI（北京科学智能研究院）、深势科技/DP Technology、分子之心/许锦波团队、智源研究院、清华、北大、浙大、复旦、上交、Stanford、MIT、CMU、Berkeley、Google DeepMind、Microsoft Research、Meta AI
- 顶刊/顶会 AI4S 论文：Nature / Science / Cell / PNAS / Nature Methods / Nature Machine Intelligence / NeurIPS / ICML / ICLR
- AI4S 基础设施：科学智能平台、算力中心、科学大模型

【次要关注：通用 AI 技术 — 严格筛选，只选真正重磅的】
- 顶级大模型重大发布：GPT 系列、Claude 系列、Gemini 系列、DeepSeek 系列的重大版本
- 中国主流大模型的重要更新：千问/Qwen、豆包、文心、智谱/GLM、Kimi 的里程碑版本
- 科技巨头对 AI 行业有重大影响的战略动作
- 非常重磅的开源项目（如 LangChain、MCP、PyTorch 级别）
- 超 5 亿美元的重大融资/收购

以下内容直接打 1-3 分：
- 普通产品更新、小版本迭代、营销 PR
- 不知名公司、没有实质性突破的内容
- 灌水论文、与 AI 无关的新闻

对每篇文章：
1. **tag**: 简短主题标签，如 "AI4S·材料"、"AI4S·生物医药"、"通用AI·模型"、"通用AI·商业"、"AISI·材料"、"科研论文·顶刊" 等（6字内）
2. **title_cn**: 英文翻译为中文（15字以内），中文保持原样
3. **summary_cn**: 100-200字中文详细摘要，包含日期、机构、具体突破、为什么重要——像新闻简报
4. **category**: 科研论文 | 大模型发布 | 开源工具 | 行业动态 | 融资收购 | 政策监管
5. **score**: AI4S 内容评分标准从宽（有实质性科学价值的即使中等影响力也可给 5-6 分），通用 AI 必须非常重磅才给 6 分以上：
   - 8-10：顶刊论文、AISI/DeepMind 级成果、GPT/Claude 系列重大发布
   - 6-7：好的 AI4S 论文/成果、主流大模型里程碑更新
   - 4-5：值得关注的 AI4S 新闻、大模型版本更新
   - 1-3：普通内容、边缘新闻

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
            article.llm_summary = r.get("summary_cn", "")[:300]
            article.score = float(r.get("score", 5))
            article.llm_score = int(r.get("score", 5))
            if "category" in r:
                article.category = r["category"]
            if "tag" in r:
                article.tag = r["tag"][:10]


def _apply_heuristic_fallback(batch: list[Article]) -> None:
    """Apply heuristic scoring when LLM is unavailable."""
    for article in batch:
        article.title_cn = article.title
        article.llm_summary = article.summary[:200] if article.summary else ""
        article.score = 5.0
        article.llm_score = 5
