"""app_finder.py — Web UI for lead_finder.py.
Runs on http://localhost:8082

Start:
    nohup python3 app_finder.py > /tmp/app_finder.log 2>&1 &
Stop:
    kill $(lsof -ti:8082)
"""

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from flask import (Flask, Response, redirect, render_template_string,
                   request, session, stream_with_context, url_for)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)

_FINDER_DIR = Path(__file__).parent
_FINDER_SCRIPT = _FINDER_DIR / "lead_finder.py"

# ── Per-run state ───────────────────────────────────────────────────────────
# run_id → {"proc": Popen, "q": Queue, "stats": dict, "deals": list, "log": list}
_runs: dict[str, dict] = {}


def _default_okved() -> str:
    return "\n".join([
        # Приоритет 1: 100% профиль Сколково
        "72.19",   # Науч. исследования и разработки прочие
        "26.51",   # Приборы для измерений и навигации
        "26.60",   # Медицинская аппаратура
        "21.20",   # Производство лекарственных препаратов
        "26.30",   # Телекоммуникационное оборудование
        "26.20",   # Компьютеры и периферия
        "62.01",   # Разработка компьютерного ПО
        # Приоритет 2: могут подойти
        "26.70",   # Оптические приборы
        "26.10",   # Электронные компоненты
        "71.20",   # Технические испытания и анализ
        "62.02",   # Консультирование в области ИТ
        "63.11",   # Обработка данных
        "62.09",   # Деятельность в области ИТ прочая
    ])


# ── HTML templates ───────────────────────────────────────────────────────────

_CSS = """
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

/* ── Tokens ─────────────────────────────────────────────────────────────── */
:root {
  --bg:          #F7F5FF;
  --surface:     #FFFFFF;
  --border:      #EAE6F8;
  --border-soft: rgba(97,48,181,.10);
  --text:        #15112B;
  --muted:       #7B748F;
  --accent:      #6130B5;
  --accent-h:    #4e259a;
  --accent-soft: #EDE8FB;
  --green:       #22C55E; --green-soft: #F0FDF4;
  --red:         #EF4444; --red-soft:   #FEF2F2;
  --orange:      #F97316; --orange-soft:#FFF7ED;
  --blue:        #3B82F6; --blue-soft:  #EFF6FF;
  --amber:       #F59E0B; --amber-soft: #FEFCE8;
  --indigo:      #6366F1; --indigo-soft:#EEF2FF;
  --shadow-sm:   0 1px 3px rgba(0,0,0,.04);
  --shadow-md:   0 4px 16px rgba(97,48,181,.08), 0 1px 3px rgba(0,0,0,.04);
  --shadow-lg:   0 8px 32px rgba(97,48,181,.12), 0 2px 8px rgba(0,0,0,.05);
  --r-sm: 10px; --r-md: 16px; --r-lg: 20px;
}
@media (prefers-color-scheme: dark) { :root {
  --bg:#110E22; --surface:#1C1830; --border:#2E2850; --border-soft:rgba(160,130,255,.12);
  --text:#EDE8FF; --muted:#9D95BE; --accent:#9B6DFF; --accent-h:#8A5EE8; --accent-soft:#2A1F50;
  --green:#4ADE80; --green-soft:#0a2e1a; --red:#F87171; --red-soft:#2d1111;
  --orange:#FB923C; --orange-soft:#291506; --blue:#60A5FA; --blue-soft:#0e1f3d;
  --amber:#FCD34D; --amber-soft:#291c00; --indigo:#A5B4FC; --indigo-soft:#1e1b4b;
  --shadow-sm:0 1px 3px rgba(0,0,0,.2); --shadow-md:0 4px 16px rgba(0,0,0,.3); --shadow-lg:0 8px 32px rgba(0,0,0,.4);
}}
:root[data-theme="light"] {
  --bg:#F7F5FF; --surface:#FFFFFF; --border:#EAE6F8; --border-soft:rgba(97,48,181,.10);
  --text:#15112B; --muted:#7B748F; --accent:#6130B5; --accent-h:#4e259a; --accent-soft:#EDE8FB;
  --green:#22C55E; --green-soft:#F0FDF4; --red:#EF4444; --red-soft:#FEF2F2;
  --orange:#F97316; --orange-soft:#FFF7ED; --blue:#3B82F6; --blue-soft:#EFF6FF;
  --amber:#F59E0B; --amber-soft:#FEFCE8; --indigo:#6366F1; --indigo-soft:#EEF2FF;
  --shadow-sm:0 1px 3px rgba(0,0,0,.04); --shadow-md:0 4px 16px rgba(97,48,181,.08),0 1px 3px rgba(0,0,0,.04);
  --shadow-lg:0 8px 32px rgba(97,48,181,.12),0 2px 8px rgba(0,0,0,.05);
}
:root[data-theme="dark"] {
  --bg:#110E22; --surface:#1C1830; --border:#2E2850; --border-soft:rgba(160,130,255,.12);
  --text:#EDE8FF; --muted:#9D95BE; --accent:#9B6DFF; --accent-h:#8A5EE8; --accent-soft:#2A1F50;
  --green:#4ADE80; --green-soft:#0a2e1a; --red:#F87171; --red-soft:#2d1111;
  --orange:#FB923C; --orange-soft:#291506; --blue:#60A5FA; --blue-soft:#0e1f3d;
  --amber:#FCD34D; --amber-soft:#291c00; --indigo:#A5B4FC; --indigo-soft:#1e1b4b;
  --shadow-sm:0 1px 3px rgba(0,0,0,.2); --shadow-md:0 4px 16px rgba(0,0,0,.3); --shadow-lg:0 8px 32px rgba(0,0,0,.4);
}

/* ── Base ───────────────────────────────────────────────────────────────── */
body { font-family:-apple-system,BlinkMacSystemFont,'SF Pro Display','Segoe UI',sans-serif;
       background:var(--bg); color:var(--text); min-height:100vh;
       -webkit-font-smoothing:antialiased; }
a { color:var(--accent); text-decoration:none; }
a:hover { text-decoration:underline; }

/* ── Header ─────────────────────────────────────────────────────────────── */
.header { background:var(--surface); border-bottom:1px solid var(--border);
          padding:13px 28px; display:flex; align-items:center; gap:12px;
          box-shadow:var(--shadow-sm); position:sticky; top:0; z-index:100; }
.header-brand { display:flex; align-items:center; gap:9px; }
.header-logo  { width:28px; height:28px; background:var(--accent); border-radius:8px;
                display:flex; align-items:center; justify-content:center;
                font-size:15px; flex-shrink:0; }
.header h1 { font-size:15px; font-weight:700; letter-spacing:-.02em; color:var(--text); }
.header-meta { margin-left:auto; display:flex; align-items:center; gap:12px; }
.header-email { font-size:12px; color:var(--muted); }
.header-logout { font-size:12px; font-weight:600; color:var(--accent);
                 padding:5px 12px; border:1px solid var(--border);
                 border-radius:20px; transition:background .15s; }
.header-logout:hover { background:var(--accent-soft); text-decoration:none; }

/* ── Page layout ────────────────────────────────────────────────────────── */
.page { padding:28px 32px; }

/* ── Generic card ───────────────────────────────────────────────────────── */
.card { background:var(--surface); border-radius:var(--r-lg);
        box-shadow:var(--shadow-md); padding:28px 32px; }

/* ── Buttons ────────────────────────────────────────────────────────────── */
.btn { display:inline-flex; align-items:center; gap:6px; padding:9px 20px;
       border:none; border-radius:10px; font-size:14px; font-weight:600;
       cursor:pointer; transition:background .15s, transform .1s; }
.btn:active { transform:scale(.98); }
.btn-primary { background:var(--accent); color:#fff; }
.btn-primary:hover { background:var(--accent-h); }
.btn-danger  { background:var(--red); color:#fff; }
.btn-danger:hover { filter:brightness(.9); }
.btn-ghost   { background:var(--accent-soft); color:var(--accent); }
.btn-ghost:hover { background:var(--border); }

/* ── Form basics ────────────────────────────────────────────────────────── */
input, textarea, select {
  width:100%; padding:9px 13px; border:1.5px solid var(--border);
  border-radius:10px; background:var(--surface); color:var(--text);
  font-size:14px; font-family:inherit; outline:none;
  transition:border-color .15s, box-shadow .15s; }
input:focus, textarea:focus, select:focus {
  border-color:var(--accent);
  box-shadow:0 0 0 3px rgba(97,48,181,.12); }
label { font-size:13px; font-weight:600; color:var(--muted); display:block; margin-bottom:6px; }
.form-group { margin-bottom:18px; }
.hint { font-size:12px; color:var(--muted); margin-top:5px; line-height:1.5; }

/* ── Stats bar ──────────────────────────────────────────────────────────── */
.stats { display:flex; flex-wrap:wrap; gap:10px; margin-bottom:24px; }
.stat-box { flex:1 1 110px; background:var(--surface); border-radius:var(--r-md);
            box-shadow:var(--shadow-sm); padding:14px 18px; border:1px solid var(--border); }
.stat-box .num { font-size:26px; font-weight:800; font-variant-numeric:tabular-nums; }
.stat-box .lbl { font-size:11px; font-weight:600; color:var(--muted); margin-top:2px; letter-spacing:.02em; }
.stat-created  .num { color:var(--green);  }
.stat-dup      .num { color:var(--blue);   }
.stat-rejected .num { color:var(--orange); }
.stat-error    .num { color:var(--red);    }

/* ── Deal cards ─────────────────────────────────────────────────────────── */
.deals-section h2 { font-size:15px; font-weight:700; margin-bottom:14px; }
.deal-card { background:var(--surface); border:1px solid var(--border);
             border-radius:var(--r-md); padding:14px 18px; margin-bottom:8px;
             display:flex; align-items:flex-start; gap:14px;
             box-shadow:var(--shadow-sm); transition:box-shadow .15s; }
.deal-card:hover { box-shadow:var(--shadow-md); }
.deal-icon { font-size:20px; flex-shrink:0; margin-top:2px; }
.deal-body { flex:1; min-width:0; }
.deal-name { font-weight:700; font-size:14px; margin-bottom:4px;
             white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.deal-meta { font-size:12px; color:var(--muted); display:flex; flex-wrap:wrap; gap:8px; }
.deal-meta span { white-space:nowrap; }
.badge { display:inline-block; padding:3px 10px; border-radius:20px;
         font-size:11px; font-weight:700; }
.badge-green { background:var(--green-soft); color:#16a34a; }

/* ── Log box ────────────────────────────────────────────────────────────── */
.log-box { background:var(--surface); border:1px solid var(--border);
           border-radius:var(--r-md); padding:16px 18px;
           font-family:ui-monospace,monospace; font-size:12px;
           max-height:300px; overflow-y:auto; margin-top:20px;
           box-shadow:var(--shadow-sm); }
.log-box p { margin-bottom:3px; line-height:1.6; color:var(--muted); word-break:break-all; }
.log-box p.info { color:var(--text); }
.log-box p.warn { color:var(--amber); }
.log-box p.ok   { color:var(--green); }
.log-box p.err  { color:var(--red); }

/* ── Run page header ────────────────────────────────────────────────────── */
.run-header { display:flex; align-items:center; justify-content:space-between;
              margin-bottom:20px; flex-wrap:wrap; gap:12px; }
.run-header h2 { font-size:20px; font-weight:800; letter-spacing:-.02em; }
.status-badge { padding:5px 16px; border-radius:20px; font-size:12px; font-weight:700; letter-spacing:.02em; }
.status-running { background:var(--green-soft); color:#15803d; }
.status-done    { background:var(--accent-soft); color:var(--accent); }
@media (prefers-color-scheme:dark) {
  .status-running { background:#14532d; color:#86efac; }
  .status-done    { background:#2A1F50; color:#c4b5fd; }
}
:root[data-theme="dark"] .status-running { background:#14532d; color:#86efac; }
:root[data-theme="dark"] .status-done    { background:#2A1F50; color:#c4b5fd; }

/* ── OKVED selector ─────────────────────────────────────────────────────── */
.okved-selector { border:1.5px solid var(--border); border-radius:var(--r-md);
                  overflow:hidden; background:var(--surface);
                  box-shadow:var(--shadow-sm); }
.okved-group { border-bottom:1px solid var(--border); }
.okved-group:last-child { border-bottom:none; }
.okved-group.p1 { border-left:3px solid var(--amber); }
.okved-group.p2 { border-left:3px solid var(--indigo); }
.okved-group.p3 { border-left:3px solid var(--muted); }
.group-header { padding:12px 16px 8px; font-size:11px; font-weight:800;
                letter-spacing:.07em; text-transform:uppercase; display:flex;
                align-items:center; gap:8px; user-select:none; }
.priority-1.group-header { background:linear-gradient(90deg,rgba(245,158,11,.07) 0%,transparent 60%); color:#92600a; }
.priority-2.group-header { background:linear-gradient(90deg,rgba(99,102,241,.06) 0%,transparent 60%); color:#4338ca; }
.priority-3.group-header { color:var(--muted); }
:root[data-theme="dark"] .priority-1.group-header { color:#fcd34d; }
:root[data-theme="dark"] .priority-2.group-header { color:#a5b4fc; }
.group-hint { font-size:11px; color:var(--muted); padding:0 16px 10px; line-height:1.5; }
.group-items { padding:4px 0 10px; }
.priority-1 .star { color:var(--amber); }
.priority-2 .star { color:var(--indigo); }
.priority-3 .star { color:var(--muted); }
.okved-item { display:flex; align-items:center; gap:10px; padding:5px 16px;
              cursor:pointer; transition:background .1s; }
.okved-item:hover { background:var(--accent-soft); }
.okved-item input[type=checkbox] { width:16px; height:16px; flex-shrink:0;
                                   accent-color:var(--accent); cursor:pointer; }
.okved-code { font-family:ui-monospace,monospace; font-size:10px; font-weight:800;
              letter-spacing:.04em; padding:2px 8px; border-radius:6px;
              min-width:50px; text-align:center; flex-shrink:0; }
.p1 .okved-code { color:#78510a; background:var(--amber-soft); border:1px solid rgba(245,158,11,.2); }
.p2 .okved-code { color:#3730a3; background:var(--indigo-soft); border:1px solid rgba(99,102,241,.2); }
.p3 .okved-code { color:var(--muted); background:var(--bg); border:1px solid var(--border); }
.okved-desc { font-size:13px; color:var(--text); line-height:1.4; }

/* ── Right-column config cards ──────────────────────────────────────────── */
.cfg-card { background:var(--surface); border-radius:var(--r-md);
            box-shadow:var(--shadow-md); padding:18px 20px;
            border:1px solid var(--border-soft); }
.cfg-card-title { font-size:10px; font-weight:800; letter-spacing:.1em;
                  text-transform:uppercase; color:var(--muted); margin-bottom:16px;
                  display:flex; align-items:center; gap:6px; }
.cfg-field { display:flex; flex-direction:column; gap:3px; }
.cfg-label { font-size:13px; font-weight:600; color:var(--text); }
.cfg-sub   { font-size:11px; color:var(--muted); line-height:1.4; }
.cfg-fmt   { font-size:12px; color:var(--accent); font-weight:700; min-height:18px; margin-top:3px; }
.cfg-input { width:100%; padding:9px 12px; border:1.5px solid var(--border);
             border-radius:10px; background:var(--surface); color:var(--text);
             font-size:14px; font-weight:500; font-family:inherit; outline:none;
             transition:border-color .15s, box-shadow .15s; margin-top:5px; }
.cfg-input:focus { border-color:var(--accent); box-shadow:0 0 0 3px rgba(97,48,181,.12); }
select.cfg-input { cursor:pointer; }

/* ── Toggle switch ──────────────────────────────────────────────────────── */
.sw-row { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.sw-label { font-size:13px; font-weight:600; color:var(--text); }
.sw-wrap  { position:relative; flex-shrink:0; }
.sw-inp   { position:absolute; opacity:0; width:0; height:0; }
.sw-track { display:block; width:42px; height:24px; background:var(--border);
            border-radius:12px; transition:background .2s; position:relative; cursor:pointer; }
.sw-track::after { content:''; position:absolute; top:3px; left:3px; width:18px; height:18px;
                   background:#fff; border-radius:50%; transition:transform .2s;
                   box-shadow:0 1px 5px rgba(0,0,0,.18); }
.sw-inp:checked ~ .sw-track { background:var(--accent); }
.sw-inp:checked ~ .sw-track::after { transform:translateX(18px); }

/* ── Submit button ──────────────────────────────────────────────────────── */
.cfg-submit { width:100%; padding:14px; border:none; border-radius:12px;
              background:var(--accent); color:#fff;
              font-size:15px; font-weight:700; font-family:inherit;
              cursor:pointer; letter-spacing:.01em;
              transition:background .15s, transform .1s, box-shadow .15s;
              box-shadow:0 4px 14px rgba(97,48,181,.35); }
.cfg-submit:hover { background:var(--accent-h); box-shadow:0 6px 20px rgba(97,48,181,.45);
                    transform:translateY(-1px); }
.cfg-submit:active { transform:translateY(0); box-shadow:0 2px 8px rgba(97,48,181,.3); }

/* ── User dropdown ──────────────────────────────────────────────────────── */
.cs-wrap { position:relative; }
.cs-trigger { display:flex; align-items:center; gap:10px; padding:9px 13px;
              border:1.5px solid var(--border); border-radius:10px; background:var(--surface);
              color:var(--text); font-size:14px; cursor:pointer; font-weight:500;
              user-select:none; transition:border-color .15s, box-shadow .15s; }
.cs-trigger:hover { border-color:var(--accent); }
.cs-trigger.open { border-color:var(--accent); box-shadow:0 0 0 3px rgba(97,48,181,.12); }
.cs-arrow { margin-left:auto; font-size:10px; color:var(--muted); transition:transform .2s; }
.cs-trigger.open .cs-arrow { transform:rotate(180deg); }
.cs-dropdown { position:absolute; left:0; right:0; top:calc(100% + 6px);
               background:var(--surface); border:1.5px solid var(--border);
               border-radius:12px; box-shadow:var(--shadow-lg);
               max-height:260px; overflow-y:auto; z-index:300; padding:4px; }
.cs-item { display:flex; align-items:center; gap:10px; padding:8px 10px;
           cursor:pointer; border-radius:8px; transition:background .1s; font-size:13px; font-weight:500; }
.cs-item:hover, .cs-item.active { background:var(--accent-soft); color:var(--accent); }
.cs-ava { width:28px; height:28px; border-radius:50%; flex-shrink:0;
          display:flex; align-items:center; justify-content:center;
          font-size:10px; font-weight:800; color:#fff; overflow:hidden; }
.cs-ava img { width:28px; height:28px; border-radius:50%; object-fit:cover; }

/* ── Login page ─────────────────────────────────────────────────────────── */
.login-body { min-height:100vh; display:flex; flex-direction:column;
              align-items:center; justify-content:center; padding:24px; }
.login-brand { display:flex; align-items:center; gap:10px; margin-bottom:36px; }
.login-brand-mark { width:36px; height:36px; background:var(--accent); border-radius:10px;
                    display:flex; align-items:center; justify-content:center; flex-shrink:0; }
.login-brand h1 { font-size:18px; font-weight:800; letter-spacing:-.02em; color:var(--text); }
.login-card { background:var(--surface); border-radius:var(--r-lg); box-shadow:var(--shadow-lg);
              padding:32px 36px; width:100%; max-width:400px; border:1px solid var(--border-soft); }

/* ── Card icon ──────────────────────────────────────────────────────────── */
.card-icon { width:32px; height:32px; background:var(--accent-soft); border-radius:9px;
             display:flex; align-items:center; justify-content:center; flex-shrink:0; }
.card-icon svg { width:16px; height:16px; stroke:var(--accent); stroke-width:2;
                 fill:none; stroke-linecap:round; stroke-linejoin:round; }

/* ── Priority dot ───────────────────────────────────────────────────────── */
.p-dot { width:8px; height:8px; border-radius:50%; flex-shrink:0; display:inline-block; }
.p-dot-1 { background:var(--amber); }
.p-dot-2 { background:var(--indigo); }
.p-dot-3 { background:var(--muted); opacity:.6; }

/* ── Toggle util (old) ──────────────────────────────────────────────────── */
.toggle-row { display:flex; align-items:center; gap:10px; margin-bottom:18px; }
.toggle-row input[type=checkbox] { width:auto; }
.toggle-row label { margin:0; color:var(--text); font-size:14px; }

/* ── Dashboard ───────────────────────────────────────────────────────────── */
.db-page { padding:20px 24px 36px; }

/* Hero */
.db-hero { position:relative; overflow:hidden; border-radius:var(--r-lg);
           background:linear-gradient(135deg,#5020a8 0%,#7B4FD4 52%,#421d90 100%);
           padding:28px 36px; margin-bottom:16px;
           border:1px solid rgba(255,255,255,.14);
           box-shadow: 0 0 0 1px rgba(97,48,181,.3),
                       0 4px 20px rgba(97,48,181,.45),
                       0 12px 40px rgba(97,48,181,.3),
                       0 32px 80px rgba(97,48,181,.18); }
.db-hero::after { content:''; position:absolute; top:0; left:0; right:0; height:1px;
                  background:linear-gradient(90deg,transparent,rgba(255,255,255,.35) 30%,rgba(255,255,255,.35) 70%,transparent);
                  pointer-events:none; z-index:2; }
.db-hero-blobs { position:absolute; inset:0; pointer-events:none; }
.db-blob { position:absolute; border-radius:50%; background:rgba(255,255,255,.07); }
.db-hero-inner { position:relative; z-index:1;
                 display:flex; align-items:center; justify-content:space-between; gap:24px; }
.db-hero-left  { flex:1 1 0; }
.db-hero-chips { display:flex; gap:8px; margin-bottom:14px; flex-wrap:wrap; }
.db-hero-chip  { background:rgba(255,255,255,.14); color:rgba(255,255,255,.92);
                 font-size:11px; font-weight:700; padding:4px 12px; border-radius:20px;
                 letter-spacing:.05em; border:1px solid rgba(255,255,255,.18); }
.db-hero h2    { font-size:24px; font-weight:900; letter-spacing:-.03em; color:#fff; margin-bottom:6px; }
.db-hero p     { font-size:13px; color:rgba(255,255,255,.65); line-height:1.5; }

/* Decorative bar chart */
.db-bars { display:flex; align-items:flex-end; gap:5px; height:72px; flex-shrink:0; }
.db-bar  { width:13px; border-radius:5px 5px 0 0; background:rgba(255,255,255,.18);
           transition:height .3s; }
.db-bar.hi { background:rgba(255,255,255,.35); }

/* Decorative mini-stats row */
.db-hero-stats { display:flex; gap:20px; margin-top:20px; flex-wrap:wrap; }
.db-hero-stat  { }
.db-hero-stat .n { font-size:22px; font-weight:900; color:#fff; font-variant-numeric:tabular-nums; }
.db-hero-stat .l { font-size:11px; color:rgba(255,255,255,.55); font-weight:600; letter-spacing:.04em; }

/* Grid — explicit placement prevents mis-alignment */
.db-grid { display:grid; grid-template-columns:1fr 1fr 1fr 1fr; gap:14px; }

/* Cards */
.db-card { background:var(--surface); border-radius:var(--r-md);
           box-shadow:var(--shadow-md); padding:18px 20px;
           border:1px solid var(--border-soft); }
.db-card-hd { font-size:10px; font-weight:800; letter-spacing:.1em; text-transform:uppercase;
              color:var(--muted); margin-bottom:14px; display:flex; align-items:center; gap:8px; }

/* ОКВЭД card: explicit col+row placement */
.db-okved   { grid-column:1/3; grid-row:1/3; padding:0; overflow:hidden; }
.db-params  { grid-column:3/4; grid-row:1/2; }
.db-finance { grid-column:4/5; grid-row:1/2; }
.db-mode    { grid-column:3/4; grid-row:2/3; }
.db-resp    { grid-column:4/5; grid-row:2/3; }
.db-okved-hd { padding:16px 20px 0; }
.db-okved .okved-selector { border:none; border-radius:0; box-shadow:none;
                             max-height:420px; overflow-y:auto; }

/* Submit */
.db-submit-row { grid-column:1/-1; grid-row:3; }

/* ── Theme toggle ────────────────────────────────────────────────────────── */
.theme-sw { border:none; background:none; cursor:pointer; padding:0; display:flex;
            align-items:center; gap:6px; flex-shrink:0; outline:none; }
.theme-sw-track { position:relative; width:48px; height:26px; border-radius:13px;
                  background:var(--border); transition:background .25s; }
.theme-sw-thumb { position:absolute; top:3px; left:3px; width:20px; height:20px;
                  border-radius:50%; background:#fff; transition:transform .25s, background .25s;
                  box-shadow:0 1px 5px rgba(0,0,0,.22);
                  display:flex; align-items:center; justify-content:center; }
.theme-sw-thumb svg { width:11px; height:11px; transition:opacity .2s; }
.icon-sun  { stroke:#f59e0b; fill:none; }
.icon-moon { stroke:#818cf8; fill:#818cf8; display:none; }
/* Dark state */
:root[data-theme="dark"] .theme-sw-track { background:var(--accent); }
:root[data-theme="dark"] .theme-sw-thumb { transform:translateX(22px); background:#2a2048; }
:root[data-theme="dark"] .icon-sun  { display:none; }
:root[data-theme="dark"] .icon-moon { display:block; }
@media (prefers-color-scheme:dark) {
  :root:not([data-theme="light"]) .theme-sw-track { background:var(--accent); }
  :root:not([data-theme="light"]) .theme-sw-thumb { transform:translateX(22px); background:#2a2048; }
  :root:not([data-theme="light"]) .icon-sun  { display:none; }
  :root:not([data-theme="light"]) .icon-moon { display:block; }
}

/* Compact form fields inside dashboard cards */
.db-card .cfg-input { margin-top:4px; }
.db-card .cfg-label { font-size:12px; font-weight:600; color:var(--text); }
.db-card .cfg-sub   { font-size:11px; color:var(--muted); line-height:1.4; margin-top:1px; }
.db-card .cfg-fmt   { font-size:12px; color:var(--accent); font-weight:700;
                      min-height:16px; margin-top:3px; }
.db-field-gap { margin-top:10px; }
</style>
<script>
(function(){
  const COLORS=['#7c3aed','#2563eb','#16a34a','#ea580c','#dc2626','#ca8a04','#0891b2','#9333ea','#db2777','#059669'];
  window._ava_color = function(name){
    let h=0; for(let i=0;i<name.length;i++) h=(h*31+name.charCodeAt(i))&0xffff;
    return COLORS[h%COLORS.length];
  };
  window._ava_initials = function(name){
    const p=name.trim().split(' ').filter(Boolean);
    return p.length>=2?(p[0][0]+p[1][0]).toUpperCase():name.slice(0,2).toUpperCase();
  };
})();
function fmtInput(inp){
  const raw = inp.value.replace(/[^0-9]/g,'');
  const n = parseInt(raw||'0',10);
  const fmtEl = document.getElementById(inp.id.replace('-inp','-fmt'));
  if(!fmtEl) return;
  if(!raw){ fmtEl.textContent=''; return; }
  if(n>=1e9) fmtEl.textContent = (n/1e9).toFixed(n%1e9?1:0).replace('.',',')+' млрд ₽';
  else if(n>=1e6) fmtEl.textContent = (n/1e6).toFixed(n%1e6?1:0).replace('.',',')+' млн ₽';
  else fmtEl.textContent = n.toLocaleString('ru')+' ₽';
}
document.addEventListener('DOMContentLoaded',function(){
  document.querySelectorAll('#tax-min-inp').forEach(fmtInput);
});
function _makeAva(name, avatarUrl){
  const d=document.createElement('div');
  d.className='cs-ava';
  if(avatarUrl){
    const img=document.createElement('img');
    img.src=avatarUrl; img.alt=name;
    img.onerror=function(){ img.remove(); _fillInitials(d, name); };
    d.appendChild(img);
  } else {
    _fillInitials(d, name);
  }
  return d;
}
function _fillInitials(el, name){
  el.textContent=window._ava_initials(name);
  el.style.background=window._ava_color(name);
}
function initUserDropdown(users, selectedId){
  const wrap=document.getElementById('cs-wrap');
  if(!wrap) return;
  const trigger=wrap.querySelector('.cs-trigger');
  const drop=wrap.querySelector('.cs-dropdown');
  const hiddenIn=document.getElementById('resp-hidden');
  const trigAva=document.getElementById('cs-trig-ava');
  const trigName=document.getElementById('cs-trig-name');

  // Build list items
  users.forEach(function(u){
    const item=document.createElement('div');
    item.className='cs-item'+(u.id==selectedId?' active':'');
    item.dataset.uid=u.id; item.dataset.name=u.name; item.dataset.avatar=u.avatar||'';
    item.appendChild(_makeAva(u.name, u.avatar||''));
    const span=document.createElement('span'); span.textContent=u.name;
    item.appendChild(span);
    item.addEventListener('click', function(){
      // Update trigger
      trigAva.innerHTML=''; trigAva.appendChild(_makeAva(u.name, u.avatar||''));
      trigName.textContent=u.name;
      hiddenIn.value=u.id;
      // Mark active
      drop.querySelectorAll('.cs-item').forEach(function(i){ i.classList.remove('active'); });
      item.classList.add('active');
      // Close
      drop.hidden=true; trigger.classList.remove('open');
    });
    drop.appendChild(item);
  });

  // Set initial trigger state from selectedId
  const sel=users.find(function(u){ return u.id==selectedId; })||users[0];
  if(sel){
    trigAva.innerHTML=''; trigAva.appendChild(_makeAva(sel.name, sel.avatar||''));
    trigName.textContent=sel.name;
  }

  // Toggle open/close
  trigger.addEventListener('click', function(){
    const isOpen=!drop.hidden;
    drop.hidden=isOpen; trigger.classList.toggle('open',!isOpen);
  });
  // Close on outside click
  document.addEventListener('click', function(e){
    if(!wrap.contains(e.target)){ drop.hidden=true; trigger.classList.remove('open'); }
  });
  drop.hidden=true;
}
</script>
<script>
(function(){
  const root = document.documentElement;
  const saved = localStorage.getItem('theme');
  if (saved) root.setAttribute('data-theme', saved);
})();
function toggleTheme(){
  const root = document.documentElement;
  const cur = root.getAttribute('data-theme');
  const sysDark = window.matchMedia('(prefers-color-scheme:dark)').matches;
  const isDark = cur === 'dark' || (!cur && sysDark);
  const next = isDark ? 'light' : 'dark';
  root.setAttribute('data-theme', next);
  localStorage.setItem('theme', next);
}
</script>
"""

_LOGIN_TMPL = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lead Finder — Вход</title>
""" + _CSS + """
</head><body class="login-body">

<div class="login-brand">
  <div class="login-brand-mark">
    <svg viewBox="0 0 20 20" width="20" height="20" fill="none"
         stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="9" cy="9" r="5.5"/><line x1="14" y1="14" x2="18" y2="18"/>
    </svg>
  </div>
  <h1>Lead Finder</h1>
</div>

<div class="login-card">
  <h2 style="font-size:20px;font-weight:800;margin-bottom:6px;letter-spacing:-.02em">Войти в аккаунт</h2>
  <p style="color:var(--muted);font-size:13px;margin-bottom:28px;line-height:1.5">
    Используйте данные вашего аккаунта Brizo
  </p>
  {% if error %}
  <div style="background:var(--red-soft);color:var(--red);border-radius:10px;
              padding:10px 14px;margin-bottom:20px;font-size:13px;font-weight:500">
    {{ error }}
  </div>
  {% endif %}
  <form method="post" action="/login">
    <div class="form-group">
      <label>Email</label>
      <input type="email" name="email" placeholder="you@brizo.ru"
             value="{{ email or '' }}" required autocomplete="username">
    </div>
    <div class="form-group" style="margin-bottom:24px">
      <label>Пароль</label>
      <input type="password" name="password" placeholder="••••••••" required
             autocomplete="current-password">
    </div>
    <button type="submit" class="btn btn-primary" style="width:100%;justify-content:center;padding:11px 20px;font-size:14px">
      Войти
    </button>
  </form>
</div>

</body></html>"""

_CONFIG_TMPL = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lead Finder — Настройка</title>
""" + _CSS + """
</head><body>
<div class="header">
  <div class="header-brand">
    <div class="header-logo">
      <svg viewBox="0 0 20 20" width="14" height="14" fill="none"
           stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="9" cy="9" r="5.5"/><line x1="14" y1="14" x2="18" y2="18"/>
      </svg>
    </div>
    <h1>Lead Finder</h1>
  </div>
  <div class="header-meta">
    <button class="theme-sw" onclick="toggleTheme()" title="Сменить тему">
      <div class="theme-sw-track">
        <div class="theme-sw-thumb">
          <svg class="icon-sun" viewBox="0 0 24 24" stroke-width="2.5" stroke-linecap="round">
            <circle cx="12" cy="12" r="4"/>
            <line x1="12" y1="2"  x2="12" y2="5"/><line x1="12" y1="19" x2="12" y2="22"/>
            <line x1="4.22" y1="4.22" x2="6.34" y2="6.34"/><line x1="17.66" y1="17.66" x2="19.78" y2="19.78"/>
            <line x1="2"  y1="12" x2="5"  y2="12"/><line x1="19" y1="12" x2="22" y2="12"/>
            <line x1="4.22" y1="19.78" x2="6.34" y2="17.66"/><line x1="17.66" y1="6.34" x2="19.78" y2="4.22"/>
          </svg>
          <svg class="icon-moon" viewBox="0 0 24 24" stroke-width="0">
            <path d="M21 12.79A9 9 0 1 1 11.21 3a7 7 0 0 0 9.79 9.79z"/>
          </svg>
        </div>
      </div>
    </button>
    <span class="header-email">{{ email }}</span>
    <a href="/logout" class="header-logout" style="text-decoration:none">Выйти</a>
  </div>
</div>
<div class="db-page">
<form method="post" action="/start">

  <!-- ══ HERO ══════════════════════════════════════════════════════════════ -->
  <div class="db-hero">
    <div class="db-hero-blobs">
      <div class="db-blob" style="width:260px;height:260px;right:-70px;top:-80px"></div>
      <div class="db-blob" style="width:180px;height:180px;right:120px;bottom:-80px;opacity:.5"></div>
      <div class="db-blob" style="width:120px;height:120px;left:38%;top:-40px;opacity:.4"></div>
    </div>
    <div class="db-hero-inner">
      <div class="db-hero-left">
        <div class="db-hero-chips">
          <span class="db-hero-chip">Checko.ru</span>
          <span class="db-hero-chip">→</span>
          <span class="db-hero-chip">Brizo CRM</span>
        </div>
        <h2>Настройка поиска лидов</h2>
        <p>Автоматический сбор и квалификация компаний по ОКВЭД и финансовым критериям</p>
        <div class="db-hero-stats">
          <div class="db-hero-stat"><div class="n">26</div><div class="l">ОКВЭД КОДОВ</div></div>
          <div class="db-hero-stat"><div class="n">5 млн</div><div class="l">МИН. НАЛОГ</div></div>
          <div class="db-hero-stat"><div class="n">1 млрд</div><div class="l">МАХ. ВЫРУЧКА</div></div>
        </div>
      </div>
      <div class="db-bars">
        <div class="db-bar"     style="height:32%"></div>
        <div class="db-bar"     style="height:55%"></div>
        <div class="db-bar hi"  style="height:78%"></div>
        <div class="db-bar"     style="height:48%"></div>
        <div class="db-bar hi"  style="height:92%"></div>
        <div class="db-bar"     style="height:62%"></div>
        <div class="db-bar hi"  style="height:100%"></div>
        <div class="db-bar"     style="height:70%"></div>
        <div class="db-bar"     style="height:42%"></div>
      </div>
    </div>
  </div>

  <!-- ══ GRID ══════════════════════════════════════════════════════════════ -->
  <div class="db-grid">

    <!-- ── ОКВЭД (2×2) ──────────────────────────────────────────────────── -->
    <div class="db-card db-okved">
      <div class="db-okved-hd">
        <div class="db-card-hd" style="margin-bottom:12px">
          <div class="card-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2"
                 stroke-linecap="round" stroke-linejoin="round" width="16" height="16">
              <rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>
              <rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>
            </svg>
          </div>
          Коды ОКВЭД
        </div>
      </div>
      <div class="okved-selector">
        <div class="okved-group p1">
          <div class="group-header priority-1">
            <span class="p-dot p-dot-1"></span> Приоритет 1 — Ядро Сколково
          </div>
          <div class="group-hint">Приборостроение, медтех, IT-разработка, научные исследования</div>
          <div class="group-items">
            <label class="okved-item"><input type="checkbox" name="okved" value="72.19" checked><span class="okved-code">72.19</span><span class="okved-desc">Научные исследования прочие (физика, химия, инженерия, IT)</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="26.51" checked><span class="okved-code">26.51</span><span class="okved-desc">Производство приборов для измерений, испытаний и навигации</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="26.60" checked><span class="okved-code">26.60</span><span class="okved-desc">Производство медицинской аппаратуры и оборудования</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="21.20" checked><span class="okved-code">21.20</span><span class="okved-desc">Производство лекарственных препаратов (собственные разработки)</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="26.30" checked><span class="okved-code">26.30</span><span class="okved-desc">Производство телекоммуникационного оборудования</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="26.20" checked><span class="okved-code">26.20</span><span class="okved-desc">Производство компьютеров и периферийного оборудования</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="62.01" checked><span class="okved-code">62.01</span><span class="okved-desc">Разработка компьютерного программного обеспечения</span></label>
          </div>
        </div>
        <div class="okved-group p2">
          <div class="group-header priority-2">
            <span class="p-dot p-dot-2"></span> Приоритет 2 — Потенциально подходят
          </div>
          <div class="group-hint">Могут быть резидентами Сколково — если есть собственный продукт</div>
          <div class="group-items">
            <label class="okved-item"><input type="checkbox" name="okved" value="26.70"><span class="okved-code">26.70</span><span class="okved-desc">Производство оптических приборов и фотографического оборудования</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="26.10"><span class="okved-code">26.10</span><span class="okved-desc">Производство электронных компонентов и плат</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="71.20"><span class="okved-code">71.20</span><span class="okved-desc">Технические испытания, исследования, анализ и сертификация</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="62.02"><span class="okved-code">62.02</span><span class="okved-desc">Консультирование и работы в области информационных технологий</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="63.11"><span class="okved-code">63.11</span><span class="okved-desc">Обработка данных, размещение информации и связанная деятельность</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="62.09"><span class="okved-code">62.09</span><span class="okved-desc">Деятельность в области информационных технологий прочая</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="32.50"><span class="okved-code">32.50</span><span class="okved-desc">Производство медицинских инструментов и хирургического оборудования</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="72.11"><span class="okved-code">72.11</span><span class="okved-desc">Исследования и разработки в области биотехнологий</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="26.40"><span class="okved-code">26.40</span><span class="okved-desc">Производство бытовой электроники и аппаратуры</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="26.80"><span class="okved-code">26.80</span><span class="okved-desc">Производство магнитных и оптических носителей информации</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="27"><span class="okved-code">27</span><span class="okved-desc">Производство электрического оборудования</span></label>
          </div>
        </div>
        <div class="okved-group p3">
          <div class="group-header priority-3">
            <span class="p-dot p-dot-3"></span> Прочие — все ОКВЭДы раздела C
          </div>
          <div class="group-hint">Широкий охват, конверсия ниже</div>
          <div class="group-items">
            <label class="okved-item"><input type="checkbox" name="okved" value="10"><span class="okved-code">10</span><span class="okved-desc">Производство пищевых продуктов</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="11"><span class="okved-code">11</span><span class="okved-desc">Производство напитков</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="12"><span class="okved-code">12</span><span class="okved-desc">Производство табачных изделий</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="13"><span class="okved-code">13</span><span class="okved-desc">Производство текстильных изделий</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="14"><span class="okved-code">14</span><span class="okved-desc">Производство одежды</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="15"><span class="okved-code">15</span><span class="okved-desc">Производство кожи и изделий из кожи, производство обуви</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="16"><span class="okved-code">16</span><span class="okved-desc">Обработка древесины, производство изделий из дерева и пробки</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="17"><span class="okved-code">17</span><span class="okved-desc">Производство бумаги и бумажных изделий</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="18"><span class="okved-code">18</span><span class="okved-desc">Деятельность полиграфическая и копирование носителей информации</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="19"><span class="okved-code">19</span><span class="okved-desc">Производство кокса и нефтепродуктов</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="20"><span class="okved-code">20</span><span class="okved-desc">Производство химических веществ и химических продуктов</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="21.10"><span class="okved-code">21.10</span><span class="okved-desc">Производство фармацевтических субстанций и активных веществ</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="22"><span class="okved-code">22</span><span class="okved-desc">Производство резиновых и пластмассовых изделий</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="23"><span class="okved-code">23</span><span class="okved-desc">Производство прочей неметаллической минеральной продукции</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="24"><span class="okved-code">24</span><span class="okved-desc">Производство металлургическое</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="25"><span class="okved-code">25</span><span class="okved-desc">Производство готовых металлических изделий, кроме машин и оборудования</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="28"><span class="okved-code">28</span><span class="okved-desc">Производство машин и оборудования общего и специального назначения</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="29"><span class="okved-code">29</span><span class="okved-desc">Производство автотранспортных средств, прицепов и полуприцепов</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="30"><span class="okved-code">30</span><span class="okved-desc">Производство прочих транспортных средств и оборудования</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="31"><span class="okved-code">31</span><span class="okved-desc">Производство мебели</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="32"><span class="okved-code">32</span><span class="okved-desc">Производство прочих готовых изделий</span></label>
            <label class="okved-item"><input type="checkbox" name="okved" value="33"><span class="okved-code">33</span><span class="okved-desc">Ремонт и монтаж машин и оборудования</span></label>
          </div>
        </div>
      </div>
    </div>

    <!-- ── Параметры поиска ──────────────────────────────────────────────── -->
    <div class="db-card db-params">
      <div class="db-card-hd">
        <div class="card-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round" width="16" height="16">
            <line x1="4" y1="6" x2="20" y2="6"/><line x1="4" y1="12" x2="14" y2="12"/>
            <line x1="4" y1="18" x2="20" y2="18"/><circle cx="17" cy="12" r="3"/>
          </svg>
        </div>
        Параметры
      </div>
      <div class="cfg-field">
        <div class="cfg-label">Лимит сделок</div>
        <div class="cfg-sub">0 = без лимита</div>
        <input type="number" name="max_leads" value="0" min="0" max="9999" class="cfg-input">
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px" class="db-field-gap">
        <div class="cfg-field">
          <div class="cfg-label">С какой стр.</div>
          <div class="cfg-sub">50 пропускает гигантов</div>
          <input type="number" name="start_page" value="50" min="1" max="9999" class="cfg-input">
        </div>
        <div class="cfg-field">
          <div class="cfg-label">Стр. на ОКВЭД</div>
          <div class="cfg-sub">0 = все страницы</div>
          <input type="number" name="max_pages_per_okved" value="10" min="0" max="9999" class="cfg-input">
        </div>
      </div>
    </div>

    <!-- ── Финансовый фильтр ─────────────────────────────────────────────── -->
    <div class="db-card db-finance">
      <div class="db-card-hd">
        <div class="card-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round" width="16" height="16">
            <rect x="3" y="14" width="4" height="7" rx="1"/>
            <rect x="10" y="9"  width="4" height="12" rx="1"/>
            <rect x="17" y="4"  width="4" height="17" rx="1"/>
          </svg>
        </div>
        Финансы
      </div>
      <div class="cfg-field">
        <div class="cfg-label">Выручка (руб.)</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:4px">
          <div>
            <div class="cfg-sub">от</div>
            <input type="text" name="revenue_min" placeholder="любая" value=""
                   class="cfg-input" inputmode="numeric">
          </div>
          <div>
            <div class="cfg-sub">до</div>
            <input type="text" name="revenue_max" placeholder="1 000 000 000" value="1000000000"
                   class="cfg-input" inputmode="numeric">
          </div>
        </div>
      </div>
      <div class="cfg-field db-field-gap">
        <div class="cfg-label">Мин. налог на прибыль</div>
        <div class="cfg-sub">руб. за год</div>
        <input type="text" name="tax_min" value="5000000" class="cfg-input" inputmode="numeric"
               id="tax-min-inp" oninput="fmtInput(this)">
        <div id="tax-min-fmt" class="cfg-fmt"></div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px" class="db-field-gap">
        <div class="cfg-field">
          <div class="cfg-label">Период</div>
          <select name="tax_years" class="cfg-input" style="margin-top:4px">
            <option value="1">1 год</option>
            <option value="2">2 года</option>
            <option value="3" selected>3 года</option>
            <option value="5">5 лет</option>
          </select>
        </div>
        <div class="cfg-field">
          <div class="cfg-label">Условие</div>
          <select name="tax_mode" class="cfg-input" style="margin-top:4px">
            <option value="any" selected>хотя бы 1</option>
            <option value="last">только посл.</option>
            <option value="all">все годы</option>
          </select>
        </div>
      </div>
    </div>

    <!-- ── Режим работы ──────────────────────────────────────────────────── -->
    <div class="db-card db-mode">
      <div class="db-card-hd">
        <div class="card-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round" width="16" height="16">
            <path d="M18.36 6.64A9 9 0 1 1 5.64 6.64"/><line x1="12" y1="2" x2="12" y2="12"/>
          </svg>
        </div>
        Режим
      </div>
      <label class="sw-row">
        <div>
          <div class="sw-label">Автономный</div>
          <div class="cfg-sub">Цикл не останавливается</div>
        </div>
        <div class="sw-wrap">
          <input type="checkbox" name="autonomous" id="auto" value="1" class="sw-inp">
          <span class="sw-track"></span>
        </div>
      </label>
      <label class="sw-row" style="margin-top:14px">
        <div>
          <div class="sw-label">Начать заново</div>
          <div class="cfg-sub">Игнорировать историю</div>
        </div>
        <div class="sw-wrap">
          <input type="checkbox" name="reset_state" id="reset" value="1" class="sw-inp">
          <span class="sw-track"></span>
        </div>
      </label>
    </div>

    <!-- ── Ответственный ─────────────────────────────────────────────────── -->
    <div class="db-card db-resp">
      <div class="db-card-hd">
        <div class="card-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round" width="16" height="16">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
            <circle cx="12" cy="7" r="4"/>
          </svg>
        </div>
        Ответственный
      </div>
      <input type="hidden" name="responsible_id" id="resp-hidden" value="{{ serafim_id }}">
      {% if brizo_users %}
      <div class="cs-wrap" id="cs-wrap">
        <div class="cs-trigger">
          <div class="cs-ava" id="cs-trig-ava"></div>
          <span id="cs-trig-name">Загрузка...</span>
          <span class="cs-arrow">▼</span>
        </div>
        <div class="cs-dropdown"></div>
      </div>
      <script>initUserDropdown({{ brizo_users | tojson }}, {{ serafim_id }});</script>
      {% else %}
      <p class="cfg-sub">Список недоступен</p>
      {% endif %}
    </div>

    <!-- ── Кнопка ────────────────────────────────────────────────────────── -->
    <div class="db-submit-row">
      <button type="submit" class="cfg-submit">Запустить поиск</button>
    </div>

  </div><!-- end grid -->
</form>
</div>
</body></html>"""

_RUN_TMPL = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lead Finder — Запуск</title>
""" + _CSS + """
</head><body>
<div class="header">
  <div class="header-brand">
    <div class="header-logo">
      <svg viewBox="0 0 20 20" width="14" height="14" fill="none"
           stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="9" cy="9" r="5.5"/><line x1="14" y1="14" x2="18" y2="18"/>
      </svg>
    </div>
    <h1>Lead Finder</h1>
  </div>
  <div class="header-meta">
    <button class="theme-sw" onclick="toggleTheme()" title="Сменить тему">
      <div class="theme-sw-track">
        <div class="theme-sw-thumb">
          <svg class="icon-sun" viewBox="0 0 24 24" stroke-width="2.5" stroke-linecap="round">
            <circle cx="12" cy="12" r="4"/>
            <line x1="12" y1="2"  x2="12" y2="5"/><line x1="12" y1="19" x2="12" y2="22"/>
            <line x1="4.22" y1="4.22" x2="6.34" y2="6.34"/><line x1="17.66" y1="17.66" x2="19.78" y2="19.78"/>
            <line x1="2"  y1="12" x2="5"  y2="12"/><line x1="19" y1="12" x2="22" y2="12"/>
            <line x1="4.22" y1="19.78" x2="6.34" y2="17.66"/><line x1="17.66" y1="6.34" x2="19.78" y2="4.22"/>
          </svg>
          <svg class="icon-moon" viewBox="0 0 24 24" stroke-width="0">
            <path d="M21 12.79A9 9 0 1 1 11.21 3a7 7 0 0 0 9.79 9.79z"/>
          </svg>
        </div>
      </div>
    </button>
    <span class="header-email">{{ email }}</span>
    <a href="/logout" class="header-logout" style="text-decoration:none">Выйти</a>
  </div>
</div>
<div class="page">

  <div class="run-header">
    <h2>Поиск лидов</h2>
    <span id="status-badge" class="status-badge status-running">Работает</span>
  </div>

  <!-- Stats bar -->
  <div class="stats">
    <div class="stat-box">
      <div class="num" id="s-checked">0</div><div class="lbl">Проверено</div>
    </div>
    <div class="stat-box stat-created">
      <div class="num" id="s-created">0</div><div class="lbl">Создано</div>
    </div>
    <div class="stat-box stat-dup">
      <div class="num" id="s-duplicate">0</div><div class="lbl">Дублей</div>
    </div>
    <div class="stat-box stat-rejected">
      <div class="num" id="s-rejected">0</div><div class="lbl">Отклонено</div>
    </div>
    <div class="stat-box">
      <div class="num" id="s-okved_fail">0</div><div class="lbl">ОКВЭД</div>
    </div>
    <div class="stat-box stat-error">
      <div class="num" id="s-error">0</div><div class="lbl">Ошибок</div>
    </div>
  </div>

  <!-- Controls -->
  <div style="margin-bottom:20px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
    <button id="btn-pause" onclick="togglePause()" class="btn btn-ghost">Пауза</button>
    <button id="btn-stop"  onclick="stopRun()"    class="btn btn-danger">Стоп</button>
    <a href="/config" class="btn btn-ghost">Новый запуск</a>
  </div>

  <!-- Created deals -->
  <div class="deals-section">
    <h2>Созданные сделки <span id="deals-count">(0)</span></h2>
    <div id="deals-list"></div>
    <p id="no-deals" style="color:var(--muted);font-size:13px">
      Ещё нет созданных сделок...
    </p>
  </div>

  <!-- Log -->
  <div class="log-box" id="log-box">
    <p class="info">Инициализация...</p>
  </div>

</div>

<script>
const RUN_ID = {{ run_id | tojson }};
const BRIZO_URL = {{ brizo_url | tojson }};

let isPaused = false;
let isStopped = false;

async function togglePause() {
  if (isStopped) return;
  const endpoint = isPaused ? 'resume' : 'pause';
  const r = await fetch(`/${endpoint}/${RUN_ID}`, {method:'POST'});
  const d = await r.json();
  isPaused = d.paused;
  _updateControls();
}

async function stopRun() {
  if (isStopped) return;
  if (!confirm('Остановить поиск лидов?')) return;
  await fetch(`/stop/${RUN_ID}`, {
    method: 'POST',
    headers: {'X-Requested-With': 'fetch'}
  });
  isStopped = true;
  _updateControls();
  const badge = document.getElementById('status-badge');
  badge.textContent = 'Остановлено';
  badge.className = 'status-badge status-done';
  evtSource.close();
}

function _updateControls() {
  const btnPause = document.getElementById('btn-pause');
  const btnStop  = document.getElementById('btn-stop');
  const badge    = document.getElementById('status-badge');
  if (isStopped) {
    btnPause.disabled = true;
    btnStop.disabled  = true;
    btnPause.style.opacity = '0.4';
    btnStop.style.opacity  = '0.4';
  } else if (isPaused) {
    badge.textContent = 'На паузе';
    badge.className = 'status-badge';
    badge.style.background = '#fef3c7';
    badge.style.color = '#92400e';
    btnPause.textContent = 'Продолжить';
  } else {
    badge.textContent = 'Работает';
    badge.className = 'status-badge status-running';
    badge.style.background = '';
    badge.style.color = '';
    btnPause.textContent = 'Пауза';
  }
}

const statsFields = ["checked","created","duplicate","rejected","okved_fail","error"];
const dealsList = document.getElementById("deals-list");
const noDeals   = document.getElementById("no-deals");
const dealsCount= document.getElementById("deals-count");
const logBox    = document.getElementById("log-box");
const badge     = document.getElementById("status-badge");
let dealsTotal  = 0;

function formatRub(v) {
  if (!v && v !== 0) return "—";
  const abs = Math.abs(v);
  if (abs >= 1e9) return (v/1e9).toFixed(1) + " млрд";
  if (abs >= 1e6) return (v/1e6).toFixed(1) + " млн";
  if (abs >= 1e3) return (v/1e3).toFixed(0) + " тыс";
  return v.toLocaleString("ru") + " руб";
}

function addLog(text, cls="info") {
  const p = document.createElement("p");
  p.className = cls;
  p.textContent = text;
  logBox.appendChild(p);
  logBox.scrollTop = logBox.scrollHeight;
  if (logBox.children.length > 300) logBox.children[0].remove();
}

function addDealCard(d) {
  noDeals.style.display = "none";
  dealsTotal++;
  dealsCount.textContent = `(${dealsTotal})`;
  const card = document.createElement("div");
  card.className = "deal-card";
  const rev = formatRub(d.revenue);
  const tax = formatRub(d.income_tax);
  card.innerHTML = `
    <div class="deal-icon">🏢</div>
    <div class="deal-body">
      <div class="deal-name">${d.name || d.url}</div>
      <div class="deal-meta">
        <span>ИНН: <b>${d.inn || "—"}</b></span>
        <span>Выручка: ${rev}</span>
        <span>Налог на прибыль: ${tax}</span>
        ${d.website ? `<span><a href="${d.website}" target="_blank">${d.website.replace(/^https?:\\/\\//,"")}</a></span>` : ""}
        ${d.deal_id ? `<span><a href="${BRIZO_URL}/cabinet/deals#deal/${d.deal_id}/main" target="_blank">Сделка #${d.deal_id}</a></span>` : ""}
      </div>
    </div>
    <div><span class="badge badge-green">Создана</span></div>
  `;
  dealsList.insertBefore(card, dealsList.firstChild);
}

const evtSource = new EventSource(`/stream/${RUN_ID}`);

evtSource.addEventListener("log", e => {
  const d = JSON.parse(e.data);
  addLog(d.text, d.level || "info");
});

evtSource.addEventListener("event", e => {
  const d = JSON.parse(e.data);
  if (d.type === "stats_update") {
    statsFields.forEach(f => {
      const el = document.getElementById("s-" + f);
      if (el && d[f] != null) el.textContent = d[f];
    });
  } else if (d.type === "company_checked") {
    addLog(`${d.name || d.url}  ИНН: ${d.inn || "—"}`, "info");
  } else if (d.type === "company_result") {
    if (d.result === "created") {
      addLog(`+ Создана: ${d.name}`, "ok");
      addDealCard(d);
    } else if (d.result === "duplicate") {
      addLog(`= Дубль: ${d.name}`, "info");
    } else if (d.result === "rejected") {
      addLog(`- ${d.name} — ${d.reason}`, "info");
    } else if (d.result === "error") {
      addLog(`! Ошибка: ${d.name || d.url} — ${d.reason}`, "warn");
    }
  } else if (d.type === "page_scraped") {
    addLog(`ОКВЭД ${d.okved} стр.${d.page}/${d.total_pages}: ${d.count} компаний`, "info");
  } else if (d.type === "finished" || d.type === "cycle_done") {
    isStopped = true;
    badge.textContent = "Завершено";
    badge.className = "status-badge status-done";
    badge.style.background = '';
    badge.style.color = '';
    document.getElementById("btn-stop").disabled  = true;
    document.getElementById("btn-pause").disabled = true;
    document.getElementById("btn-stop").style.opacity  = '0.4';
    document.getElementById("btn-pause").style.opacity = '0.4';
    evtSource.close();
    addLog("─── Завершено ───", "ok");
  }
});

evtSource.onerror = () => {
  badge.textContent = "Завершено";
  badge.className = "status-badge status-done";
  evtSource.close();
};
</script>
</body></html>"""


# ── Auth helpers ─────────────────────────────────────────────────────────────

def _check_credentials(email: str, password: str) -> str | None:
    """Try to get a Bearer token from Brizo. Return token string or None."""
    import requests as _r
    try:
        r = _r.post(
            "https://brizo.ru/api/auth",
            json={"email": email, "password": password},
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
            timeout=12,
        )
        if r.status_code == 200:
            return r.json().get("token")
    except Exception:
        pass
    return None


def _fetch_brizo_users(token: str) -> list[dict]:
    """Fetch all CRM members from /api/members. Returns list of {id, name, avatar_url}."""
    import requests as _r
    try:
        r = _r.get(
            "https://sad1.brizo.ru/api/members",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0",
            },
            timeout=12,
        )
        if r.status_code == 200:
            members = r.json().get("data", [])
            return sorted(
                [{
                    "id":         m["id"],
                    "name":       m.get("name") or m.get("email", str(m["id"])),
                    "avatar_url": m.get("avatar_url") or "",
                }
                 for m in members if m.get("id")],
                key=lambda u: u["name"].lower()
            )
    except Exception:
        pass
    return []


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if "email" not in session:
        return redirect(url_for("login_page"))
    return redirect(url_for("config"))


@app.route("/login", methods=["GET", "POST"])
def login_page():
    error = None
    email = ""
    if request.method == "POST":
        email    = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        token = _check_credentials(email, password)
        if token:
            session["email"]    = email
            session["password"] = password
            session["token"]    = token
            session["brizo_users"] = _fetch_brizo_users(token)
            return redirect(url_for("config"))
        error = "Неверный email или пароль — попробуйте ещё раз"
    return render_template_string(_LOGIN_TMPL, error=error, email=email)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


@app.route("/config")
def config():
    if "email" not in session:
        return redirect(url_for("login_page"))
    return render_template_string(
        _CONFIG_TMPL,
        email=session["email"],
        default_codes=_default_okved(),
        brizo_users=session.get("brizo_users", []),
        serafim_id=46897,
    )


@app.route("/start", methods=["POST"])
def start():
    if "email" not in session:
        return redirect(url_for("login_page"))

    # Чекбоксы ОКВЭД — каждый selected checkbox отправляет свой value
    okved_list          = request.form.getlist("okved")
    max_leads           = int(request.form.get("max_leads",          0) or 0)
    start_page          = int(request.form.get("start_page",         1) or 1)
    max_pages_per_okved = int(request.form.get("max_pages_per_okved", 10) or 10)
    autonomous          = bool(request.form.get("autonomous"))
    reset_st            = bool(request.form.get("reset_state"))
    responsible_id      = request.form.get("responsible_id", "").strip()

    # ── Финансовые критерии ──────────────────────────────────────────────────
    def _parse_int(s: str, default: int) -> int:
        try:
            return int(str(s).replace(" ", "").replace("\xa0", "") or default)
        except (ValueError, TypeError):
            return default

    revenue_min = _parse_int(request.form.get("revenue_min", ""), 0)
    revenue_max = _parse_int(request.form.get("revenue_max", ""), 1_000_000_000)
    tax_min     = _parse_int(request.form.get("tax_min", ""),     5_000_000)
    tax_years   = _parse_int(request.form.get("tax_years", "3"),  3)
    tax_mode    = request.form.get("tax_mode", "any")
    if tax_mode not in ("any", "last", "all"):
        tax_mode = "any"

    if not okved_list:
        return redirect(url_for("config"))

    run_id = str(uuid.uuid4())[:8]
    q: queue.Queue = queue.Queue()

    # ── Пишем settings.json для lead_finder ─────────────────────────────────
    settings_path = _FINDER_DIR / "settings.json"
    settings_data: dict = {
        "revenue_max": revenue_max,
        "income_tax_rule": {
            "mode":       tax_mode,
            "years":      tax_years,
            "min_amount": tax_min,
        },
    }
    if revenue_min > 0:
        settings_data["revenue_min"] = revenue_min
    try:
        settings_path.write_text(
            json.dumps(settings_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        app.logger.warning("Не удалось записать settings.json: %s", e)

    cmd = [sys.executable, str(_FINDER_SCRIPT)]
    if max_leads:
        cmd.extend(["--max", str(max_leads)])
    if start_page > 1:
        cmd.extend(["--start-page", str(start_page)])
    cmd.extend(["--max-pages", str(max_pages_per_okved)])
    if autonomous:
        cmd.append("--autonomous")
    if reset_st:
        cmd.append("--reset")
    if responsible_id.isdigit():
        cmd.extend(["--responsible", responsible_id])
    cmd.extend(["--codes"] + okved_list)

    env = os.environ.copy()
    env["BRIZO_EMAIL"]    = session["email"]
    env["BRIZO_PASSWORD"] = session["password"]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
        cwd=str(_FINDER_DIR),
        start_new_session=True,  # собственная группа → SIGSTOP/SIGCONT по pgid
    )

    _runs[run_id] = {
        "proc":   proc,
        "q":      q,
        "active": True,
        "paused": False,
    }

    def _reader():
        try:
            for line in proc.stdout:
                line = line.rstrip()
                if line.startswith("PIPELINE_EVENT:"):
                    try:
                        evt = json.loads(line[len("PIPELINE_EVENT:"):])
                        q.put(("event", evt))
                    except Exception:
                        q.put(("log", {"text": line, "level": "info"}))
                else:
                    level = "warn" if "WARNING" in line or "ERROR" in line else "info"
                    q.put(("log", {"text": line, "level": level}))
        finally:
            q.put(("done", None))
            if run_id in _runs:
                _runs[run_id]["active"] = False

    threading.Thread(target=_reader, daemon=True).start()

    return render_template_string(
        _RUN_TMPL,
        run_id=run_id,
        email=session["email"],
        brizo_url=os.getenv("BRIZO_URL", "https://sad1.brizo.ru"),
    )


@app.route("/stream/<run_id>")
def stream(run_id: str):
    run = _runs.get(run_id)
    if not run:
        return Response("data: {}\n\n", mimetype="text/event-stream")

    def _gen():
        q = run["q"]
        while True:
            try:
                kind, data = q.get(timeout=30)
            except queue.Empty:
                yield ": heartbeat\n\n"
                continue

            if kind == "done":
                yield f"event: event\ndata: {json.dumps({'type': 'finished'})}\n\n"
                break
            elif kind == "event":
                yield f"event: event\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            elif kind == "log":
                yield f"event: log\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(_gen()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _finder_signal(run_id: str, sig: int) -> bool:
    run = _runs.get(run_id)
    proc = run.get("proc") if run else None
    if not proc or not run.get("active"):
        return False
    try:
        os.killpg(os.getpgid(proc.pid), sig)
        return True
    except Exception:
        return False


@app.route("/pause/<run_id>", methods=["POST"])
def pause_run(run_id: str):
    from flask import jsonify
    ok = _finder_signal(run_id, signal.SIGSTOP)
    if ok and run_id in _runs:
        _runs[run_id]["paused"] = True
    return jsonify(ok=ok, paused=_runs.get(run_id, {}).get("paused", False))


@app.route("/resume/<run_id>", methods=["POST"])
def resume_run(run_id: str):
    from flask import jsonify
    ok = _finder_signal(run_id, signal.SIGCONT)
    if ok and run_id in _runs:
        _runs[run_id]["paused"] = False
    return jsonify(ok=ok, paused=_runs.get(run_id, {}).get("paused", False))


@app.route("/stop/<run_id>", methods=["POST"])
def stop(run_id: str):
    from flask import jsonify, request as _req
    run = _runs.get(run_id)
    if run and run.get("proc"):
        try:
            os.killpg(os.getpgid(run["proc"].pid), signal.SIGCONT)  # снять паузу перед kill
        except Exception:
            pass
        try:
            os.killpg(os.getpgid(run["proc"].pid), signal.SIGTERM)
        except Exception:
            pass
        run["active"] = False
        run["paused"] = False
    # Если запрос пришёл от fetch (JS) — возвращаем JSON; если форма — редирект
    if _req.headers.get("Accept", "").startswith("application/json") or \
       _req.headers.get("X-Requested-With") == "fetch":
        return jsonify(ok=True)
    return redirect(url_for("config"))


if __name__ == "__main__":
    # Railway/Render выставляют PORT; локально используем FINDER_PORT или 8082
    port = int(os.getenv("PORT", os.getenv("FINDER_PORT", "8082")))
    print(f"🔍  Lead Finder UI → http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
