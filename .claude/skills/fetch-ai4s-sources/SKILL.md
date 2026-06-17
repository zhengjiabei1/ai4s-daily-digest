---
name: fetch-ai4s-sources
description: Fetch news content from AI4S institution websites (AISI, Tsinghua AIR, BAAI, etc.) that lack RSS feeds. Saves structured articles to data/skill_fetched.json for the Python news pipeline to consume in the next run.
---

# Fetch AI4S Sources

This skill scrapes official AI4S institution pages that our Python pipeline can't reach (JavaScript-rendered sites, WeChat article pages, etc.), formats the results, and saves them so the daily digest script picks them up.

## Workflow

1. Fetch each target URL using curl with a browser User-Agent, or use the web-fetch skill for JS-rendered pages
2. Extract article titles, URLs, and summaries from the HTML
3. Write structured JSON to `data/skill_fetched.json` in the format the pipeline expects
4. The next `python main.py` run will merge these articles with RSS-sourced ones

## Target Institutions

| Institution | URL to fetch |
|---|---|
| AISI (北京科学智能研究院) | http://www.bjaisi.com/ |
| DeepModeling Blog | https://deepmodeling.com/blog |
| 深势科技 | https://www.dp.tech/publish |
| 上海AI实验室 | https://www.shlab.org.cn/info |
| BAAI 智源 | https://www.baai.ac.cn/zh-cn/news |
| 清华 AIR | https://air.tsinghua.edu.cn/airxw/airxw.htm |

## Output format (data/skill_fetched.json)

```json
[
  {
    "title": "文章标题",
    "url": "https://...",
    "source_name": "AISI北京科学智能研究院",
    "default_category": "AI for Science",
    "summary": "原文摘要"
  }
]
```

## Usage

Just say "fetch AI4S sources" or "补充抓取官方机构新闻". I will:
1. Scrape each institution page
2. Extract articles
3. Save to the shared data file
4. Then you can run `python main.py` to include them in the next digest
