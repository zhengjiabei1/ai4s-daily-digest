#!/usr/bin/env python3
"""Quick health check for the daily news digest system.

Tells you at a glance:
- Whether today's push has happened
- Last push date and status
- If a push is overdue
"""

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_FILE = PROJECT_ROOT / "data" / "digest_cache.json"
LOGS_DIR = PROJECT_ROOT / "logs"


def main():
    today = date.today()
    yesterday = today.replace(day=today.day - 1) if today.day > 1 else today

    print("=" * 50)
    print("📰 AISI 新闻推送 — 健康检查")
    print(f"   当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)
    print()

    # 1. Cache status
    cache = {}
    if CACHE_FILE.exists():
        try:
            cache = json.loads(CACHE_FILE.read_text())
        except Exception:
            pass

    yesterday_str = yesterday.strftime("%Y-%m-%d")
    cached_dates = sorted(cache.keys(), reverse=True)

    print(f"📦 缓存状态 (digest_cache.json):")
    print(f"   已缓存日期: {', '.join(cached_dates[:5]) if cached_dates else '(空)'}")

    if yesterday_str in cache:
        print(f"   ✅ 昨天（{yesterday_str}）已缓存 — 推送应该已完成")
    else:
        print(f"   ❌ 昨天（{yesterday_str}）无缓存 — 今天的推送可能未执行！")

    # 2. Recent logs
    print()
    print(f"📋 最近日志:")
    log_files = sorted(LOGS_DIR.glob("digest_*.log"), reverse=True)
    for lf in log_files[:5]:
        size_kb = lf.stat().st_size // 1024
        # Check if the log contains a success line
        content = lf.read_text(errors="replace")
        success = "推送成功" in content
        status = "✅" if success else "⚠️"
        date_in_log = lf.stem.replace("digest_", "")
        print(f"   {status} {date_in_log}  ({size_kb} KB)")

    # 3. Check log for today
    today_log = LOGS_DIR / f"digest_{today.strftime('%Y-%m-%d')}.log"
    print()
    if today_log.exists():
        content = today_log.read_text(errors="replace")
        push_date = ""
        for line in content.split("\n"):
            if "推送" in line and "的新闻" in line:
                push_date = line.strip()
                break
        print(f"   📅 今日推送日期: {push_date}")
        if "推送成功" in content:
            print(f"   ✅ 今日推送成功")
        else:
            print(f"   ⚠️ 今日有运行但未显示成功")
    else:
        print(f"   ⏳ 今日尚无推送日志 — 可能尚未执行")

    # 4. Feedback service
    import urllib.request, urllib.error
    print()
    print(f"📝 反馈服务:")
    feishu_feedback_url = os.environ.get("FEEDBACK_BASE_URL", "http://localhost:5099")
    try:
        req = urllib.request.Request(f"{feishu_feedback_url}/api/health")
        urllib.request.urlopen(req, timeout=5)
        print(f"   ✅ 反馈服务在线（{feishu_feedback_url}）")
        print(f"   📋 管理后台: {feishu_feedback_url}/admin?key=xxx")
    except Exception:
        print(f"   ⚠️ 反馈服务不可达（{feishu_feedback_url}）")

    # 5. Summary
    print()
    print("=" * 50)
    if yesterday_str in cache:
        print("✅ 系统正常：昨天的新闻已推送。")
        return 0
    else:
        now = datetime.now()
        if now.hour >= 11:
            print("🚨 推送延迟！今天的推送尚未执行，建议手动运行：")
            print("   cd ~/Downloads/NEWS && bash scripts/run_daily.sh")
        else:
            print("⏳ 还在等待中：通常上午 10:00-11:00 执行推送。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
