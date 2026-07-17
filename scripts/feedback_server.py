#!/usr/bin/env python3
"""AISI 新闻反馈服务 — 表单页面 + SQLite 存储 + 管理后台表格。

提供:
  GET  /form?date=YYYY-MM-DD   → 反馈表单页面
  POST /api/feedback            → 提交反馈，写入 SQLite
  GET  /admin?key=xxx           → 管理后台（统计卡片 + 表格 + CSV 导出）
  GET  /api/feedback/list       → JSON 数据（后台用）
  GET  /api/feedback/export     → CSV 导出
  GET  /api/health              → 健康检查

启动:
  python3 scripts/feedback_server.py --port 5099
"""

import argparse
import csv
import io
import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_FILE = Path(os.environ.get("FEEDBACK_DB_PATH", str(PROJECT_ROOT / "data" / "feedback.db")))
ADMIN_KEY = os.environ.get("FEEDBACK_ADMIN_PASSWORD", "ainews2024")

# ── Database ────────────────────────────────────────────────────────────────


def get_db() -> sqlite3.Connection:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL DEFAULT '',
            useful INTEGER NOT NULL DEFAULT 0,
            score_ai4s INTEGER NOT NULL DEFAULT 0,
            score_general INTEGER NOT NULL DEFAULT 0,
            preferences TEXT NOT NULL DEFAULT '',
            suggestion TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.commit()
    return conn


# ── HTML Templates ──────────────────────────────────────────────────────────

FORM_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>AISI 新闻反馈</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
  background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);min-height:100vh;
  display:flex;align-items:center;justify-content:center;padding:20px}
.card{background:#fff;border-radius:20px;padding:36px 32px;max-width:440px;width:100%;
  box-shadow:0 20px 60px rgba(0,0,0,.18)}
h2{font-size:22px;color:#1f2937;margin-bottom:4px}
.sub{font-size:14px;color:#6b7280;margin-bottom:28px}
.group{margin-bottom:22px}
.group label{display:block;font-size:15px;font-weight:600;color:#374151;margin-bottom:8px}
.radio-group{display:flex;gap:10px}
.radio-group label{padding:10px 18px;border:2px solid #e5e7eb;border-radius:10px;
  cursor:pointer;font-size:14px;font-weight:400;transition:.2s;user-select:none}
.radio-group input{display:none}
.radio-group input:checked+span{color:#667eea}
.radio-group label:has(input:checked){border-color:#667eea;background:#f5f3ff}
.stars{display:flex;gap:6px}
.star{font-size:32px;cursor:pointer;color:#d1d5db;transition:.15s;user-select:none}
.star.active,.star:hover{color:#f59e0b}
.star:hover~.star{color:#d1d5db}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{padding:8px 16px;border:2px solid #e5e7eb;border-radius:20px;cursor:pointer;
  font-size:13px;transition:.2s;user-select:none}
.chip.active{border-color:#667eea;background:#f5f3ff;color:#667eea;font-weight:600}
.chip input{display:none}
textarea{width:100%;height:80px;padding:12px;border:2px solid #e5e7eb;border-radius:10px;
  font-size:14px;resize:none;font-family:inherit;transition:.2s}
textarea:focus{outline:none;border-color:#667eea}
.btn-submit{width:100%;padding:14px;background:linear-gradient(135deg,#667eea,#764ba2);
  color:#fff;border:none;border-radius:12px;font-size:16px;font-weight:600;cursor:pointer;
  transition:.2s;margin-top:8px}
.btn-submit:hover{transform:translateY(-1px);box-shadow:0 8px 25px rgba(102,126,234,.4)}
.btn-submit:disabled{opacity:.5;cursor:not-allowed;transform:none;box-shadow:none}
.thanks{display:none;text-align:center;padding:40px 0}
.thanks .icon{font-size:56px;margin-bottom:16px}
.thanks h2{color:#059669;margin-bottom:8px}
.thanks p{color:#6b7280}
.error-msg{color:#dc2626;font-size:13px;margin-top:4px;display:none}
</style>
</head>
<body>
<div class="card">
  <div id="step1">
    <h2>📋 AISI 新闻反馈</h2>
    <div class="sub" id="formDate">日期：--</div>

    <div class="group">
      <label>1. 本次新闻内容对您有用吗？</label>
      <div class="radio-group" id="usefulGroup">
        <label><input type="radio" name="useful" value="1"><span>👍 有用</span></label>
        <label><input type="radio" name="useful" value="0"><span>😐 一般</span></label>
        <label><input type="radio" name="useful" value="-1"><span>👎 没用</span></label>
      </div>
    </div>

    <div class="group">
      <label>2. 【AI for Science】部分评分</label>
      <div class="stars" id="starsAi4s">
        <span class="star" data-v="1">★</span><span class="star" data-v="2">★</span>
        <span class="star" data-v="3">★</span><span class="star" data-v="4">★</span><span class="star" data-v="5">★</span>
      </div>
    </div>

    <div class="group">
      <label>3. 【通用 AI】部分评分</label>
      <div class="stars" id="starsGeneral">
        <span class="star" data-v="1">★</span><span class="star" data-v="2">★</span>
        <span class="star" data-v="3">★</span><span class="star" data-v="4">★</span><span class="star" data-v="5">★</span>
      </div>
    </div>

    <div class="group">
      <label>4. 希望增加哪类内容？（可多选）</label>
      <div class="chips" id="prefChips">
        <label class="chip"><input type="checkbox" value="科研论文"><span>📄 科研论文</span></label>
        <label class="chip"><input type="checkbox" value="产品发布"><span>🚀 产品发布</span></label>
        <label class="chip"><input type="checkbox" value="政策解读"><span>📜 政策解读</span></label>
        <label class="chip"><input type="checkbox" value="开源项目"><span>💻 开源项目</span></label>
        <label class="chip"><input type="checkbox" value="行业动态"><span>📊 行业动态</span></label>
        <label class="chip"><input type="checkbox" value="技术教程"><span>📖 技术教程</span></label>
      </div>
    </div>

    <div class="group">
      <label>5. 具体建议（选填）</label>
      <textarea id="suggestion" placeholder="请写下您的宝贵意见……"></textarea>
    </div>

    <button class="btn-submit" id="submitBtn" onclick="submit()">提交反馈</button>
    <div class="error-msg" id="errorMsg"></div>
  </div>

  <div id="step2" class="thanks">
    <div class="icon">🎉</div>
    <h2>感谢您的反馈！</h2>
    <p>新闻小助手会持续优化内容质量 🙏</p>
    <p style="font-size:12px;margin-top:16px;color:#9ca3af">可关闭此页面</p>
  </div>
</div>

<script>
var scoreAi4s=0,scoreGeneral=0,date='';

(function(){
  var p=new URLSearchParams(window.location.search);
  date=p.get('date')||'';
  document.getElementById('formDate').textContent='日期：'+(date||'--');
})();

// Star ratings
document.querySelectorAll('.stars').forEach(function(g){
  g.addEventListener('click',function(e){
    if(!e.target.classList.contains('star'))return;
    var v=parseInt(e.target.dataset.v);
    g.querySelectorAll('.star').forEach(function(s,i){
      s.classList.toggle('active',i<v);
    });
    if(g.id==='starsAi4s')scoreAi4s=v;else scoreGeneral=v;
  });
});

// Chips toggle
document.querySelectorAll('.chip').forEach(function(c){
  c.addEventListener('click',function(){
    this.classList.toggle('active');
  });
});

// Radio button visual
document.querySelectorAll('.radio-group input').forEach(function(r){
  r.addEventListener('change',function(){});
});

function showError(msg){
  var el=document.getElementById('errorMsg');
  el.textContent=msg;el.style.display='block';
  setTimeout(function(){el.style.display='none'},3000);
}

async function submit(){
  var useful=document.querySelector('input[name="useful"]:checked');
  if(!useful){showError('请选择"有用/一般/没用"');return;}
  if(!scoreAi4s){showError('请给 AI for Science 部分打分');return;}
  if(!scoreGeneral){showError('请给 通用 AI 部分打分');return;}

  var prefs=[];
  document.querySelectorAll('#prefChips .chip.active input').forEach(function(cb){prefs.push(cb.value);});

  var btn=document.getElementById('submitBtn');
  btn.disabled=true;btn.textContent='提交中...';

  try{
    var r=await fetch('/api/feedback',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        date:date,
        useful:parseInt(useful.value),
        score_ai4s:scoreAi4s,
        score_general:scoreGeneral,
        preferences:prefs.join(','),
        suggestion:document.getElementById('suggestion').value.trim()
      })
    });
    var j=await r.json();
    if(j.ok){
      document.getElementById('step1').style.display='none';
      document.getElementById('step2').style.display='block';
    }else{
      showError(j.error||'提交失败，请重试');
      btn.disabled=false;btn.textContent='提交反馈';
    }
  }catch(e){
    showError('网络错误，请重试');
    btn.disabled=false;btn.textContent='提交反馈';
  }
}
</script>
</body></html>"""

ADMIN_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>反馈管理后台 — AISI 新闻</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
  background:#f3f4f6;min-height:100vh;padding:24px}
.container{max-width:1100px;margin:0 auto}
h1{font-size:24px;color:#1f2937;margin-bottom:4px}
.subtitle{font-size:14px;color:#6b7280;margin-bottom:24px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:28px}
.stat-card{background:#fff;border-radius:14px;padding:20px 24px;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.stat-card .label{font-size:13px;color:#6b7280;margin-bottom:4px}
.stat-card .value{font-size:28px;font-weight:700;color:#1f2937}
.stat-card .value.green{color:#059669}
.stat-card .value.amber{color:#d97706}
.toolbar{display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap;align-items:center}
.toolbar select,.toolbar input{padding:8px 14px;border:1px solid #d1d5db;border-radius:8px;font-size:14px}
.toolbar button{padding:8px 18px;background:#667eea;color:#fff;border:none;border-radius:8px;
  font-size:14px;cursor:pointer;font-weight:600}
.toolbar button:hover{background:#5a6fd6}
table{width:100%;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.06)}
th,td{padding:12px 16px;text-align:left;font-size:14px}
th{background:#f9fafb;color:#6b7280;font-weight:600;border-bottom:1px solid #e5e7eb}
td{border-bottom:1px solid #f3f4f6;color:#374151}
tr:hover td{background:#f9fafb}
.badge{padding:2px 8px;border-radius:12px;font-size:12px;font-weight:600}
.badge-good{background:#ecfdf5;color:#059669}
.badge-ok{background:#fffbeb;color:#d97706}
.badge-bad{background:#fef2f2;color:#dc2626}
.stars-display{color:#f59e0b;font-size:14px;letter-spacing:2px}
.empty{text-align:center;padding:60px 24px;color:#9ca3af}
.empty .icon{font-size:48px;margin-bottom:12px}
</style>
</head>
<body>
<div class="container">
  <h1>📊 AISI 新闻反馈 — 管理后台</h1>
  <div class="subtitle" id="lastRefresh">加载中...</div>

  <div class="stats" id="stats"></div>

  <div class="toolbar">
    <select id="dateFilter" onchange="load()">
      <option value="">全部日期</option>
    </select>
    <button onclick="exportCSV()">📥 导出 CSV</button>
    <button onclick="load()" style="background:#6b7280">🔄 刷新</button>
  </div>

  <table id="tableWrap">
    <thead>
      <tr>
        <th>日期</th><th>有用度</th><th>AI4S 评分</th><th>通用AI 评分</th>
        <th>偏好</th><th>建议</th><th>时间</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
</div>

<script>
function usefulBadge(v){
  if(v===1)return'<span class="badge badge-good">👍 有用</span>';
  if(v===0)return'<span class="badge badge-ok">😐 一般</span>';
  return'<span class="badge badge-bad">👎 没用</span>';
}
function stars(v){
  var s='';for(var i=0;i<5;i++)s+=i<v?'★':'☆';
  return'<span class="stars-display">'+s+'</span>';
}

async function load(){
  var d=document.getElementById('dateFilter').value;
  var url='/api/feedback/list';
  if(d)url+='?date='+encodeURIComponent(d);
  var r=await fetch(url);
  var j=await r.json();

  // Stats
  var total=j.length, useful=0, avgAi4s=0, avgGen=0;
  j.forEach(function(f){
    if(f.useful===1)useful++;
    avgAi4s+=f.score_ai4s;avgGen+=f.score_general;
  });
  avgAi4s=total?(avgAi4s/total).toFixed(1):'-';
  avgGen=total?(avgGen/total).toFixed(1):'-';
  var rate=total?Math.round(useful/total*100):'-';

  document.getElementById('stats').innerHTML=
    '<div class="stat-card"><div class="label">总反馈数</div><div class="value">'+total+'</div></div>'+
    '<div class="stat-card"><div class="label">有用率</div><div class="value green">'+(rate==='-'?'-':rate+'%')+'</div></div>'+
    '<div class="stat-card"><div class="label">AI4S 均分</div><div class="value amber">'+avgAi4s+'</div></div>'+
    '<div class="stat-card"><div class="label">通用AI 均分</div><div class="value amber">'+avgGen+'</div></div>';

  // Table
  var tbody=document.getElementById('tbody');
  if(!j.length){
    tbody.innerHTML='<tr><td colspan="7"><div class="empty"><div class="icon">📭</div>暂无反馈数据</div></td></tr>';
    return;
  }
  tbody.innerHTML=j.map(function(f){
    return'<tr>'+
      '<td>'+h(f.date||'-')+'</td>'+
      '<td>'+usefulBadge(f.useful)+'</td>'+
      '<td>'+stars(f.score_ai4s)+'</td>'+
      '<td>'+stars(f.score_general)+'</td>'+
      '<td>'+h((f.preferences||'-').replace(/,/g,', '))+'</td>'+
      '<td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="'+h(f.suggestion||'')+'">'+h((f.suggestion||'-').substring(0,40))+'</td>'+
      '<td style="font-size:12px;color:#9ca3af">'+(f.created_at||'').substring(5,16)+'</td>'+
      '</tr>';
  }).join('');

  // Populate date filter
  var dates=[...new Set(j.map(function(f){return f.date}).filter(Boolean))];
  var sel=document.getElementById('dateFilter');
  dates.forEach(function(dt){
    if(!sel.querySelector('option[value="'+dt+'"]')){
      var o=document.createElement('option');o.value=dt;o.textContent=dt;sel.appendChild(o);
    }
  });

  document.getElementById('lastRefresh').textContent='最后刷新：'+new Date().toLocaleTimeString('zh-CN');
}

function h(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}

function exportCSV(){
  var d=document.getElementById('dateFilter').value;
  var url='/api/feedback/export';
  if(d)url+='?date='+encodeURIComponent(d);
  window.open(url,'_blank');
}

load();
</script>
</body></html>"""


# ── HTTP Handler ────────────────────────────────────────────────────────────


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        p = urlparse(self.path)
        path = p.path.rstrip("/") or "/"
        qs = parse_qs(p.query)

        if path == "/form":
            self._html(FORM_HTML)
        elif path == "/admin":
            self._serve_admin(qs)
        elif path == "/api/feedback/list":
            self._json(self._list_feedback(qs.get("date", [None])[0]))
        elif path == "/api/feedback/export":
            self._csv_export(qs.get("date", [None])[0])
        elif path == "/api/health":
            self._json(200, {"status": "ok", "db": str(DB_FILE)})
        elif path == "/":
            self._html(FORM_HTML)  # default → form
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        p = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")

        if p.path.rstrip("/") == "/api/feedback":
            self._handle_feedback(body)
        else:
            self._json(404, {"error": "not found"})

    # ── Feedback submit ──

    def _handle_feedback(self, body: dict):
        try:
            date = str(body.get("date", "")).strip()
            useful = int(body.get("useful", 0))
            score_ai4s = max(1, min(5, int(body.get("score_ai4s", 3))))
            score_general = max(1, min(5, int(body.get("score_general", 3))))
            preferences = str(body.get("preferences", "")).strip()[:200]
            suggestion = str(body.get("suggestion", "")).strip()[:1000]
            created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Validate required
            if not date:
                self._json(400, {"ok": False, "error": "缺少日期参数"})
                return

            # Validate useful is -1/0/1
            if useful not in (-1, 0, 1):
                self._json(400, {"ok": False, "error": "useful 必须是 -1, 0, 1"})
                return

            conn = get_db()
            conn.execute(
                """INSERT INTO feedback (date, useful, score_ai4s, score_general,
                   preferences, suggestion, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (date, useful, score_ai4s, score_general, preferences, suggestion, created_at),
            )
            conn.commit()
            conn.close()

            print(f"✅ 反馈: date={date} useful={useful} ai4s={score_ai4s} gen={score_general} pref={preferences}")
            self._json(200, {"ok": True})

        except (ValueError, TypeError) as e:
            self._json(400, {"ok": False, "error": f"参数错误: {e}"})
        except Exception as e:
            self._json(500, {"ok": False, "error": str(e)})

    # ── Admin auth ──

    def _check_admin(self, qs: dict) -> bool:
        """Verify admin key from query string."""
        key = qs.get("key", [""])[0]
        return key == ADMIN_KEY

    def _serve_admin(self, qs: dict):
        if not self._check_admin(qs):
            self.send_response(401)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            login = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>管理后台 — 登录</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,"PingFang SC",sans-serif;background:linear-gradient(135deg,#667eea,#764ba2);
  min-height:100vh;display:flex;align-items:center;justify-content:center}
.card{background:#fff;border-radius:16px;padding:40px 32px;max-width:360px;width:100%;
  box-shadow:0 20px 60px rgba(0,0,0,.15);text-align:center}
h2{font-size:20px;color:#1f2937;margin-bottom:20px}
input{width:100%;padding:12px;border:2px solid #e5e7eb;border-radius:10px;font-size:15px;
  text-align:center;margin-bottom:12px}
input:focus{outline:none;border-color:#667eea}
button{width:100%;padding:12px;background:#667eea;color:#fff;border:none;border-radius:10px;
  font-size:15px;font-weight:600;cursor:pointer}
button:hover{background:#5a6fd6}
.err{color:#dc2626;font-size:13px;margin-top:8px;display:none}
</style></head>
<body>
<div class="card"><h2>🔐 管理后台登录</h2>
<form onsubmit="submitKey(event)">
<input type="password" id="keyInput" placeholder="请输入管理密钥" autofocus>
<button type="submit">进入后台</button>
<div class="err" id="err">密钥错误</div>
</form>
</div>
<script>
function submitKey(e){e.preventDefault();
  var k=document.getElementById('keyInput').value;
  if(k)window.location.href='/admin?key='+encodeURIComponent(k);
  else document.getElementById('err').style.display='block';
}
var m=document.cookie.match(/(?:^|;\\s*)admin_key=([^;]*)/);
if(m)window.location.href='/admin?key='+encodeURIComponent(m[1]);
</script>
</body></html>"""
            self.wfile.write(login.encode("utf-8"))
            return
        # Set a cookie so the user doesn't need to include key in every request
        cookie = f"admin_key={qs.get('key', [''])[0]}; Path=/; HttpOnly; SameSite=Lax"
        self._html(ADMIN_HTML, extra_headers={"Set-Cookie": cookie})

    # ── Data queries ──

    def _list_feedback(self, date_filter: str | None) -> list[dict]:
        conn = get_db()
        if date_filter:
            rows = conn.execute(
                "SELECT * FROM feedback WHERE date = ? ORDER BY created_at DESC",
                (date_filter,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM feedback ORDER BY created_at DESC LIMIT 500"
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ── CSV export ──

    def _csv_export(self, date_filter: str | None):
        data = self._list_feedback(date_filter)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["日期", "有用度", "AI4S评分", "通用AI评分", "偏好", "建议", "提交时间"])
        for r in data:
            useful_map = {1: "有用", 0: "一般", -1: "没用"}
            writer.writerow([
                r["date"], useful_map.get(r["useful"], "?"),
                r["score_ai4s"], r["score_general"],
                r["preferences"], r["suggestion"],
                r["created_at"],
            ])
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8-sig")
        self.send_header("Content-Disposition", "attachment; filename=feedback_export.csv")
        self.end_headers()
        self.wfile.write(output.getvalue().encode("utf-8-sig"))

    # ── Response helpers ──

    def _html(self, content: str, extra_headers: dict | None = None):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def _json(self, status_or_data, body=None):
        if body is not None:
            self.send_response(status_or_data)
            data = body
        else:
            self.send_response(200)
            data = status_or_data
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def log_message(self, fmt, *args):
        pass  # silence access logs


def main():
    ap = argparse.ArgumentParser(description="AISI Feedback Server")
    ap.add_argument("--port", type=int, default=5099)
    ap.add_argument("--host", type=str, default="0.0.0.0")
    args = ap.parse_args()

    # Ensure DB is initialized
    get_db().close()
    print(f"📋 AISI 反馈服务启动")
    print(f"   表单页面: http://localhost:{args.port}/form?date=2026-07-14")
    print(f"   管理后台: http://localhost:{args.port}/admin?key={ADMIN_KEY}")
    print(f"   数据库:   {DB_FILE}")
    print(f"   密钥:     {ADMIN_KEY}")
    print()

    server = HTTPServer((args.host, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 服务已停止")


if __name__ == "__main__":
    main()
