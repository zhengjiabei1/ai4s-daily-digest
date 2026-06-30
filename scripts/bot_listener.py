"""AISI 新闻助手 — 飞书可对话调整 Bot。

在飞书私聊中：
- 说"推送一份" → 立刻跑 main.py 推送
- 说"AI4S 多一篇" → 改配额
- 说"加 Nature 源" → 改 config
- 其他消息 → DeepSeek 分析后回复 + 尝试执行

每 15 秒轮询 P2P 私聊。
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import yaml
from loguru import logger

AID = os.environ["FEISHU_APP_ID"]
ASEC = os.environ["FEISHU_APP_SECRET"]
DKEY = os.environ["DEEPSEEK_API_KEY"]
P2P_CHAT_ID = os.environ.get("FEISHU_P2P_CHAT_ID", "oc_bb0fffd0df15eb069fca2ae766504c7e")
USER_OPEN_ID = "ou_77209a49330aea6375d44a224cd49882"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = Path("data/p2p_seen.json")
CONFIG_FILE = Path("config.yaml")

_cache = {"t": "", "e": 0}


def _tok():
    now = time.time()
    if _cache["e"] > now + 300:
        return _cache["t"]
    r = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": AID, "app_secret": ASEC},
        headers={"Content-Type": "application/json; charset=utf-8"}, timeout=15,
    )
    d = r.json()
    _cache["t"] = d["tenant_access_token"]
    _cache["e"] = now + d.get("expire", 7200)
    return _cache["t"]


def _reply(msg_id, text):
    r = requests.post(
        f"https://open.feishu.cn/open-apis/im/v1/messages/{msg_id}/reply",
        json={"content": json.dumps({"text": text}, ensure_ascii=False), "msg_type": "text"},
        headers={"Authorization": f"Bearer {_tok()}", "Content-Type": "application/json; charset=utf-8"},
        timeout=15,
    )
    logger.info(f"sent: code={r.json().get('code')} {text[:60]}")


def _send_text(receive_id, id_type, text):
    requests.post(
        f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={id_type}",
        json={"receive_id": receive_id, "msg_type": "text",
              "content": json.dumps({"text": text}, ensure_ascii=False)},
        headers={"Authorization": f"Bearer {_tok()}", "Content-Type": "application/json; charset=utf-8"},
        timeout=15,
    )


def _analyze(text: str) -> dict:
    """Use DeepSeek to understand intent and generate action."""
    prompt = f"""你是AISI新闻助手。分析用户消息，判断下一步要做什么。

用户消息: {text}

当前系统：
- 每天10:30从12个RSS源抓取AI新闻，DeepSeek摘要，推送到飞书
- AI for Science 4篇 + 通用 AI 2篇
- 日期严格限制昨天

根据消息，返回JSON：
{{"intent": "push|config_quota|config_source|config_time|chat", "reply": "简短回复用户（40字内）", "action_detail": "具体操作说明"}}

如果用户让推送，intent=push。
如果用户让改配额/比例/数量，intent=config_quota。
如果用户让加/删来源，intent=config_source。
如果用户让改推送时间，intent=config_time。
如果只是聊天、提问、打招呼，intent=chat。

只返回JSON，不要其他文字。"""
    try:
        r = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            json={"model": "deepseek-v4-flash", "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 300, "temperature": 0},
            headers={"Authorization": f"Bearer {DKEY}"}, timeout=15,
        )
        raw = r.json()["choices"][0]["message"]["content"].strip()
        s = raw.find("{"); e = raw.rfind("}") + 1
        return json.loads(raw[s:e]) if s >= 0 and e > s else {"intent": "chat", "reply": raw[:100]}
    except Exception as e:
        return {"intent": "chat", "reply": f"收到，但分析出错: {str(e)[:50]}"}


def _execute(analysis: dict) -> str:
    """Execute the intended action. Return a human-readable result."""
    intent = analysis.get("intent", "chat")
    detail = analysis.get("action_detail", "")

    if intent == "push":
        return _action_push()

    elif intent == "config_quota":
        return _action_quota(analysis, detail)

    elif intent == "config_source":
        return _action_source(analysis, detail)

    elif intent == "config_time":
        return "时间修改需要编辑 .github/workflows/daily-digest.yml 中的 cron 表达式。请在这里告诉我。"

    else:
        return None  # chat — just reply, no action


def _action_push() -> str:
    """Run the pipeline and return result."""
    try:
        result = subprocess.run(
            ["python3", "main.py"],
            cwd=PROJECT_ROOT,
            capture_output=True, text=True, timeout=300,
            env={**os.environ,
                 "FEISHU_APP_ID": AID, "FEISHU_APP_SECRET": ASEC,
                 "FEISHU_CHAT_ID": USER_OPEN_ID,
                 "DEEPSEEK_API_KEY": DKEY},
        )
        # Extract key info
        output = result.stdout + result.stderr
        date_match = re.search(r"推送 (\d{4}-\d{2}-\d{2}) 的新闻", output)
        diversity_match = re.search(r"多样性分布: (.+)", output)
        date_filter_match = re.search(r"Date filter.*: kept (\d+), dropped (\d+)", output)
        success = "推送成功" in output

        lines = []
        if date_match:
            lines.append(f"日期: {date_match.group(1)}")
        if date_filter_match:
            lines.append(f"筛选: 保留{date_filter_match.group(1)}篇, 丢弃{date_filter_match.group(2)}篇")
        if diversity_match:
            lines.append(f"分布: {diversity_match.group(1)}")
        lines.append("已推送到你私聊" if success else "推送失败，检查日志")

        return "\n".join(lines)
    except Exception as e:
        return f"推送执行失败: {str(e)[:100]}"


def _action_quota(analysis: dict, detail: str) -> str:
    """Modify AI4S/general quota in main.py."""
    try:
        main_path = os.path.join(PROJECT_ROOT, "main.py")
        with open(main_path) as f:
            content = f.read()

        # Find the quota line: "ai4s": (... , 4)
        match = re.search(r'"ai4s":\s*\(.+?,\s*(\d+)\)', content)
        if not match:
            return "找不到配额设置，请检查 main.py"
        current_ai4s = int(match.group(1))

        match_g = re.search(r'"general(?:_ai)?":\s*\(.+?,\s*(\d+)\)', content)
        current_general = int(match_g.group(1)) if match_g else 2

        # Parse the user's intent
        text = analysis.get("reply", "") + " " + detail
        new_ai4s = current_ai4s
        new_general = current_general

        if "多" in text or "增加" in text or "加" in text:
            if "ai4s" in text.lower() or "科学" in text or "AI4S" in text:
                new_ai4s += 1
            elif "通用" in text:
                new_general += 1
        elif "少" in text or "减少" in text or "减" in text:
            if "ai4s" in text.lower() or "科学" in text or "AI4S" in text:
                new_ai4s = max(1, new_ai4s - 1)
            elif "通用" in text:
                new_general = max(0, new_general - 1)
        else:
            # Try to parse explicit numbers
            nums = re.findall(r'(\d+)\s*[篇条]?\s*(ai4s|科学|AI4S)', text, re.IGNORECASE)
            for n, t in nums:
                new_ai4s = int(n)
            nums2 = re.findall(r'(\d+)\s*[篇条]?\s*(通用|general)', text, re.IGNORECASE)
            for n, t in nums2:
                new_general = int(n)

        if new_ai4s == current_ai4s and new_general == current_general:
            return f"配额未变: AI4S={current_ai4s}, 通用={current_general}"

        # Apply
        content = re.sub(
            r'("ai4s":\s*\(.+?,\s*)\d+(\))',
            rf'\g<1>{new_ai4s}\g<2>', content
        )
        content = re.sub(
            r'("general(?:_ai)?":\s*\(.+?,\s*)\d+(\))',
            rf'\g<1>{new_general}\g<2>', content
        )
        with open(main_path, "w") as f:
            f.write(content)

        # Also update max_articles_for_primary_card in config.yaml
        total = new_ai4s + new_general
        with open(CONFIG_FILE) as f:
            config = yaml.safe_load(f)
        config["processing"]["max_articles_for_primary_card"] = total
        with open(CONFIG_FILE, "w") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        return f"已修改: AI4S {current_ai4s}→{new_ai4s}, 通用 {current_general}→{new_general}, 共{total}篇"
    except Exception as e:
        return f"配额修改失败: {str(e)[:100]}"


def _action_source(analysis: dict, detail: str) -> str:
    """Add or remove a news source."""
    return "来源管理请在此对话中告诉我具体需求，我来操作。"


def _load_seen():
    try: return set(json.loads(STATE_FILE.read_text())) if STATE_FILE.exists() else set()
    except: return set()


def _save_seen(s):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(list(s)[-500:]))


def poll():
    seen = _load_seen()
    token = _tok()
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}

    r = requests.get(
        "https://open.feishu.cn/open-apis/im/v1/messages",
        params={"container_id_type": "chat", "container_id": P2P_CHAT_ID,
                "page_size": 5, "sort_type": "ByCreateTimeDesc"},
        headers=h, timeout=10,
    )
    if r.json().get("code") != 0:
        return seen

    for m in r.json().get("data", {}).get("items", []):
        mid = m.get("message_id", "")
        if mid in seen:
            continue
        seen.add(mid)

        if m.get("sender", {}).get("id") == AID:
            continue

        body = m.get("body", {}).get("content", "")
        text = ""
        try: text = json.loads(body).get("text", "").strip()
        except: pass
        if not text:
            continue

        logger.info(f"收到: {text[:80]}")

        # Analyze + execute
        analysis = _analyze(text)
        reply_text = analysis.get("reply", "收到")
        action_result = _execute(analysis)

        if action_result:
            reply_text += f"\n\n操作结果: {action_result}"

        _reply(mid, reply_text)

    _save_seen(seen)
    return seen


def main():
    from utils.logger import setup_logging
    setup_logging(level="INFO")
    logger.info("=== AISI Bot (可对话调整) 启动 ===")

    # Send startup notification
    _send_text(USER_OPEN_ID, "open_id",
               "AISI新闻助手已上线。你可以在这里:\n"
               "- 说「推送一份」→ 立刻推送\n"
               "- 说「AI4S多一篇」→ 修改配额\n"
               "- 说「加xxx源」→ 添加新闻来源\n"
               "- 直接提需求，我来调整")

    while True:
        try:
            poll()
            time.sleep(15)
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"轮询异常: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
