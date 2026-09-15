#!/usr/bin/env python3
"""app_phones.py — Web UI for the add_phones pipeline.

Запуск: python3 app_phones.py → http://localhost:8081
"""

import json
import os
import signal
import subprocess
import threading
import uuid
from flask import Flask, Response, jsonify, redirect, render_template_string, request, session

app = Flask(__name__)
app.secret_key = b'brizo-phones-ui-2026-xZ8kPqT5nM'

PARSER_DIR = os.path.dirname(os.path.abspath(__file__))

_runs: dict = {}


def _classify(line: str) -> str:
    if '═' in line or 'ГОТОВО' in line or 'ADD PHONES' in line: return 'stats'
    if 'Найдено' in line and 'телефонов' in line: return 'ok'
    if 'добавлено' in line.lower(): return 'ok'
    if 'Ищем телефоны' in line: return 'searching'
    if 'Сделка' in line and '/' in line: return 'lead'
    if 'Телефоны не найдены' in line or 'skip' in line.lower() or 'already has' in line: return 'muted'
    if 'ERROR' in line or 'CRITICAL' in line or 'не настроен' in line: return 'error'
    return 'info'


@app.route('/')
def index():
    return render_template_string(INDEX_HTML,
        email=session.get('email', ''),
        password=session.get('password', ''))


@app.route('/start', methods=['POST'])
def start():
    email    = request.form.get('email', '').strip()
    password = request.form.get('password', '').strip()

    session.permanent = True
    session['email']    = email
    session['password'] = password

    run_id = uuid.uuid4().hex[:10]
    cond = threading.Condition()
    run = {'lines': [], 'events': [], 'done': False, 'paused': False,
           'proc': None, 'cond': cond}
    _runs[run_id] = run

    def _worker():
        env = {**os.environ, 'BRIZO_EMAIL': email, 'BRIZO_PASSWORD': password}
        try:
            proc = subprocess.Popen(
                ['python3', 'add_phones.py'],
                cwd=PARSER_DIR, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                start_new_session=True,   # собственная группа процессов → SIGSTOP/SIGCONT по pgid
            )
            run['proc'] = proc
            for raw in iter(proc.stdout.readline, ''):
                line = raw.rstrip('\n')
                with cond:
                    if line.startswith('PIPELINE_EVENT:'):
                        run['events'].append(line[len('PIPELINE_EVENT:'):])
                    else:
                        run['lines'].append(line)
                    cond.notify_all()
            proc.wait()
        except Exception as exc:
            with cond:
                run['lines'].append(f'[ERROR] {exc}')
                cond.notify_all()
        finally:
            with cond:
                run['done'] = True
                cond.notify_all()

    threading.Thread(target=_worker, daemon=True).start()
    return redirect(f'/run/{run_id}')


@app.route('/run/<run_id>')
def run_page(run_id):
    if run_id not in _runs:
        return redirect('/')
    return render_template_string(RUN_HTML, run_id=run_id)


def _send_signal(run_id: str, sig: int) -> bool:
    run = _runs.get(run_id)
    proc = run.get('proc') if run else None
    if not proc or run.get('done'):
        return False
    try:
        os.killpg(os.getpgid(proc.pid), sig)
        return True
    except Exception:
        return False


@app.route('/pause/<run_id>', methods=['POST'])
def pause_run(run_id):
    ok = _send_signal(run_id, signal.SIGSTOP)
    if ok and run_id in _runs:
        _runs[run_id]['paused'] = True
    return jsonify(ok=ok, paused=_runs.get(run_id, {}).get('paused', False))


@app.route('/resume/<run_id>', methods=['POST'])
def resume_run(run_id):
    ok = _send_signal(run_id, signal.SIGCONT)
    if ok and run_id in _runs:
        _runs[run_id]['paused'] = False
    return jsonify(ok=ok, paused=_runs.get(run_id, {}).get('paused', False))


@app.route('/stop/<run_id>', methods=['POST'])
def stop_run(run_id):
    run = _runs.get(run_id)
    proc = run.get('proc') if run else None
    if proc and not run.get('done'):
        try:
            # сначала SIGCONT если процесс на паузе, иначе SIGTERM не дойдёт
            os.killpg(os.getpgid(proc.pid), signal.SIGCONT)
        except Exception:
            pass
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            pass
        if run_id in _runs:
            _runs[run_id]['paused'] = False
    return jsonify(ok=True)


@app.route('/stream/<run_id>')
def stream(run_id):
    run = _runs.get(run_id)
    if not run:
        return Response('data: {}\n\n', status=404, mimetype='text/event-stream')

    def _generate():
        log_idx = 0
        evt_idx = 0
        cond = run['cond']
        while True:
            with cond:
                while (log_idx >= len(run['lines']) and
                       evt_idx >= len(run['events']) and
                       not run['done']):
                    cond.wait(timeout=20)
                new_logs   = run['lines'][log_idx:]
                new_events = run['events'][evt_idx:]
                is_done    = run['done']

            for line in new_logs:
                log_idx += 1
                yield f"data: {json.dumps({'t': line, 'k': _classify(line)})}\n\n"

            for evt_raw in new_events:
                evt_idx += 1
                yield f"event: pipeline\ndata: {evt_raw}\n\n"

            if is_done and log_idx >= len(run['lines']) and evt_idx >= len(run['events']):
                yield f"event: done\ndata: {{}}\n\n"
                break

    return Response(_generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


# ── HTML: login page ──────────────────────────────────────────────────────────

INDEX_HTML = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Brizo Phones</title>
<style>
:root{
  --bg:#0c1220;--card:#131b2e;--border:#1e2d4a;--text:#c8d6f0;--muted:#5a6e96;
  --accent:#22d49a;--accent-h:#16b882;--input:#0e1828;
}
@media(prefers-color-scheme:light){:root{
  --bg:#f0f4fb;--card:#fff;--border:#dde6f5;--text:#1a2540;--muted:#6b7ea8;
  --accent:#16a34a;--accent-h:#15803d;--input:#f5f8ff;
}}
*{box-sizing:border-box;margin:0;padding:0}
body{
  background:var(--bg);color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px;
}
.card{
  background:var(--card);border:1px solid var(--border);border-radius:16px;
  padding:44px 40px;width:100%;max-width:400px;
  box-shadow:0 8px 48px rgba(0,0,0,.25);
}
.logo{
  width:48px;height:48px;background:var(--accent);border-radius:12px;
  display:flex;align-items:center;justify-content:center;font-size:22px;
  margin-bottom:20px;
}
h1{font-size:22px;font-weight:700;letter-spacing:-.3px}
.sub{color:var(--muted);font-size:13px;margin-top:4px;margin-bottom:32px;line-height:1.5}
.field{margin-bottom:18px}
label{
  display:block;font-size:11px;font-weight:700;letter-spacing:.08em;
  text-transform:uppercase;color:var(--muted);margin-bottom:7px
}
input{
  width:100%;padding:11px 14px;
  background:var(--input);border:1.5px solid var(--border);
  border-radius:8px;color:var(--text);font-size:14px;outline:none;
  transition:border-color .15s;
}
input:focus{border-color:var(--accent)}
.pw{position:relative}
.pw input{padding-right:44px}
.eye{position:absolute;right:12px;top:50%;transform:translateY(-50%);
     background:none;border:none;cursor:pointer;color:var(--muted);font-size:16px;padding:4px}
.btn{
  width:100%;padding:13px;background:var(--accent);color:#fff;
  border:none;border-radius:9px;font-size:15px;font-weight:700;cursor:pointer;
  transition:background .15s;margin-top:24px;display:flex;align-items:center;
  justify-content:center;gap:9px;letter-spacing:.01em;
}
.btn:hover{background:var(--accent-h)}
.note{
  margin-top:20px;padding:12px 14px;background:rgba(34,212,154,.07);
  border:1px solid rgba(34,212,154,.18);border-radius:8px;
  font-size:12px;color:var(--muted);line-height:1.6;
}
</style>
</head>
<body>
<div class="card">
  <div class="logo">📞</div>
  <h1>Brizo Phones</h1>
  <div class="sub">Добавление телефонов в контакты из колонки «Парсю»</div>
  <form method="post" action="/start">
    <div class="field">
      <label>Email Brizo</label>
      <input type="email" name="email" value="{{ email }}" placeholder="user@example.ru" required autocomplete="username">
    </div>
    <div class="field">
      <label>Пароль Brizo</label>
      <div class="pw">
        <input type="password" name="password" id="pw" value="{{ password }}" placeholder="••••••••" required autocomplete="current-password">
        <button type="button" class="eye" onclick="this.previousElementSibling.type=this.previousElementSibling.type==='password'?'text':'password'">👁</button>
      </div>
    </div>
    <button type="submit" class="btn">
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5" stroke-linecap="round"><path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72 12.84 12.84 0 00.7 2.81 2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45 12.84 12.84 0 002.81.7A2 2 0 0122 16.92z"/></svg>
      Добавить телефоны
    </button>
  </form>
  <div class="note">
    Программа найдёт ваши сделки в «Парсю», возьмёт ИНН каждого контакта
    и запросит номера через Telegram-бот.
  </div>
</div>
</body>
</html>"""


# ── HTML: run page ────────────────────────────────────────────────────────────

RUN_HTML = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Brizo Phones — запуск</title>
<style>
:root{
  --bg:#0c1220;--surface:#131b2e;--surface2:#0e1525;--border:#1e2d4a;
  --text:#c8d6f0;--muted:#5a6e96;--faint:#3a4e72;
  --accent:#22d49a;--green:#22d49a;--red:#f05252;--yellow:#f5a623;--gray:#3a4e72;--blue:#3d8ef8;
}
@media(prefers-color-scheme:light){:root{
  --bg:#eef2fb;--surface:#fff;--surface2:#f5f8ff;--border:#d5e0f5;
  --text:#1a2540;--muted:#6b7ea8;--faint:#c0cce8;
  --accent:#16a34a;--green:#16a34a;--red:#dc2626;--yellow:#d97706;--gray:#94a3b8;--blue:#2563eb;
}}
*{box-sizing:border-box;margin:0;padding:0}
body{
  background:var(--bg);color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  min-height:100vh;display:flex;flex-direction:column;overflow:hidden;height:100vh;
}

/* Header */
.hdr{
  background:var(--surface);border-bottom:1px solid var(--border);
  padding:0 24px;height:52px;display:flex;align-items:center;gap:14px;flex-shrink:0;
}
.hdr-logo{font-size:18px;font-weight:800;letter-spacing:-.3px;color:var(--text)}
.hdr-logo span{color:var(--accent)}
.hdr-sep{flex:1}
.badge{
  display:flex;align-items:center;gap:6px;padding:4px 12px;border-radius:20px;
  font-size:12px;font-weight:700;letter-spacing:.03em;
}
.badge.running{background:rgba(34,212,154,.12);color:var(--accent)}
.badge.done{background:rgba(61,142,248,.12);color:var(--blue)}
.pulse{width:7px;height:7px;border-radius:50%;background:var(--accent);animation:pulse 1.4s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.4;transform:scale(.8)}}
.back{
  padding:5px 14px;border-radius:8px;border:1px solid var(--border);
  background:none;color:var(--muted);font-size:12px;cursor:pointer;text-decoration:none;
  transition:all .15s;font-weight:600;
}
.back:hover{color:var(--text);border-color:var(--faint)}

/* Stats bar */
.statsbar{
  background:var(--surface2);border-bottom:1px solid var(--border);
  padding:12px 24px;display:flex;align-items:center;gap:0;flex-shrink:0;
}
.stat{
  display:flex;flex-direction:column;align-items:center;padding:0 22px;
  border-right:1px solid var(--border);
}
.stat:first-child{padding-left:0}
.stat:last-child{border-right:none}
.stat-val{font-size:22px;font-weight:800;font-variant-numeric:tabular-nums;line-height:1}
.stat-lbl{font-size:11px;color:var(--muted);margin-top:3px;font-weight:600;letter-spacing:.04em;text-transform:uppercase}
.c-green  .stat-val{color:var(--green)}
.c-blue   .stat-val{color:var(--blue)}
.c-yellow .stat-val{color:var(--yellow)}
.c-muted  .stat-val{color:var(--muted)}
.progress-wrap{flex:1;padding:0 24px}
.progress-track{height:6px;background:var(--border);border-radius:3px;overflow:hidden}
.progress-fill{height:100%;background:var(--accent);border-radius:3px;width:0%;transition:width .4s ease}
.progress-pct{font-size:12px;color:var(--muted);margin-top:5px;text-align:right;font-weight:700}

/* Body */
.body{flex:1;display:flex;overflow:hidden;min-height:0}

/* Deals panel */
.deals-panel{
  flex:1 1 0;min-width:0;display:flex;flex-direction:column;
  border-right:1px solid var(--border);overflow:hidden;
}
.panel-hdr{
  padding:12px 20px;border-bottom:1px solid var(--border);
  font-size:11px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;
  color:var(--muted);display:flex;align-items:center;justify-content:space-between;flex-shrink:0;
}
.deals-scroll{flex:1;overflow-y:auto;padding:10px 12px}
.deals-scroll::-webkit-scrollbar{width:4px}
.deals-scroll::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}

/* Deal card */
.deal-card{
  border:1px solid var(--border);border-radius:10px;margin-bottom:8px;overflow:hidden;
  transition:border-color .2s;
}
.deal-card.active{border-color:var(--accent)}
.deal-hdr{
  display:flex;align-items:center;gap:10px;padding:10px 14px;
  background:var(--surface);
}
.deal-num{
  font-size:11px;color:var(--muted);font-weight:700;font-variant-numeric:tabular-nums;
  min-width:28px;font-family:monospace;
}
.deal-name{font-size:13px;font-weight:700;flex:1;min-width:0;
           white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.deal-badge{
  font-size:11px;font-weight:700;padding:2px 8px;border-radius:10px;flex-shrink:0;
}
.db-waiting{background:rgba(58,78,114,.2);color:var(--muted)}
.db-active{background:rgba(34,212,154,.12);color:var(--accent)}
.db-done{background:rgba(61,142,248,.12);color:var(--blue)}

/* Contact rows */
.contacts{padding:6px 14px 10px;display:flex;flex-direction:column;gap:4px}
.ct-row{
  display:flex;align-items:center;gap:8px;
  padding:5px 8px;border-radius:6px;font-size:12px;
}
.ct-icon{font-size:13px;flex-shrink:0}
.ct-name{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
          font-weight:600}
.ct-status{font-size:11px;font-weight:700;padding:1px 7px;border-radius:8px;flex-shrink:0}
.s-added{background:rgba(34,212,154,.12);color:var(--green)}
.s-skipped{background:rgba(58,78,114,.15);color:var(--muted)}
.s-no_inn{background:rgba(245,166,35,.1);color:var(--yellow)}
.s-no_phones{background:rgba(245,166,35,.1);color:var(--yellow)}
.s-error{background:rgba(240,82,82,.12);color:var(--red)}
.s-searching{background:rgba(34,212,154,.08);color:var(--accent)}

/* Log sidebar */
.log-panel{
  width:38%;flex-shrink:0;display:flex;flex-direction:column;
  background:var(--surface2);overflow:hidden;
}
.log-scroll{
  flex:1;overflow-y:auto;padding:8px 0;
  font-family:'JetBrains Mono',Consolas,'Courier New',monospace;
  font-size:11.5px;line-height:1.6;
}
.log-scroll::-webkit-scrollbar{width:3px}
.log-scroll::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
.log-line{padding:0 14px;white-space:pre-wrap;word-break:break-all;color:var(--muted)}
.log-line.ok,.log-line.searching{color:var(--green)}
.log-line.error{color:var(--red);font-weight:700}
.log-line.stats{color:var(--accent);font-weight:700}
.log-line.lead{color:var(--text);font-weight:700;margin-top:4px}
.log-line.muted{color:var(--faint)}
.log-scroll-btn{
  padding:5px 12px;border-top:1px solid var(--border);
  font-size:11px;color:var(--muted);display:flex;align-items:center;
  justify-content:space-between;flex-shrink:0;
}
.scroll-toggle{
  background:none;border:1px solid var(--border);border-radius:4px;
  color:var(--muted);font-size:10px;padding:2px 8px;cursor:pointer;transition:all .15s;
}
.scroll-toggle:hover{color:var(--text);border-color:var(--faint)}
</style>
</head>
<body>

<div class="hdr">
  <div class="hdr-logo">Brizo<span>Phones</span></div>
  <div class="hdr-sep"></div>
  <div class="badge running" id="badge"><div class="pulse" id="pulse"></div><span id="badgeTxt">В процессе</span></div>
  <button id="btnPause" onclick="togglePause()" class="back" style="margin-left:12px">⏸ Пауза</button>
  <button id="btnStop"  onclick="stopRun()"    class="back" style="margin-left:6px;color:var(--red);border-color:var(--red)">⏹ Стоп</button>
  <a href="/" class="back" style="margin-left:10px">← Новый запуск</a>
</div>

<div class="statsbar">
  <div class="stat c-blue">
    <div class="stat-val" id="sv-deals">—</div>
    <div class="stat-lbl">Сделок</div>
  </div>
  <div class="progress-wrap">
    <div class="progress-track"><div class="progress-fill" id="progress"></div></div>
    <div class="progress-pct" id="progress-pct">0%</div>
  </div>
  <div class="stat c-green">
    <div class="stat-val" id="sv-added">0</div>
    <div class="stat-lbl">Добавлено</div>
  </div>
  <div class="stat c-muted">
    <div class="stat-val" id="sv-skipped">0</div>
    <div class="stat-lbl">Уже есть</div>
  </div>
  <div class="stat c-yellow">
    <div class="stat-val" id="sv-noinn">0</div>
    <div class="stat-lbl">Нет ИНН</div>
  </div>
  <div class="stat c-yellow">
    <div class="stat-val" id="sv-nophones">0</div>
    <div class="stat-lbl">Нет номеров</div>
  </div>
</div>

<div class="body">
  <div class="deals-panel">
    <div class="panel-hdr">
      <span>Сделки</span>
      <span id="deal-count" style="color:var(--faint)">0</span>
    </div>
    <div class="deals-scroll" id="dealsEl"></div>
  </div>

  <div class="log-panel">
    <div class="panel-hdr">
      <span>Логи</span>
      <span id="log-count" style="color:var(--faint)">0 строк</span>
    </div>
    <div class="log-scroll" id="logEl"></div>
    <div class="log-scroll-btn">
      <span id="log-status" style="font-size:10px;color:var(--faint)">ожидание...</span>
      <button class="scroll-toggle" id="scrollBtn" onclick="toggleScroll()">⬇ авто</button>
    </div>
  </div>
</div>

<script>
const RUN_ID = '{{ run_id }}';

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
  if (!confirm('Остановить парсинг телефонов?')) return;
  if (isPaused) { isPaused = false; }  // сначала снять паузу — SIGTERM пройдёт
  await fetch(`/stop/${RUN_ID}`, {method:'POST'});
  isStopped = true;
  _updateControls();
}

function _updateControls() {
  const btnPause = document.getElementById('btnPause');
  const btnStop  = document.getElementById('btnStop');
  const pulse    = document.getElementById('pulse');
  if (isStopped) {
    badge.className = 'badge done';
    badgeTxt.textContent = 'Остановлено';
    if (pulse) pulse.style.display = 'none';
    btnPause.disabled = true;
    btnStop.disabled  = true;
    btnPause.style.opacity = '0.4';
    btnStop.style.opacity  = '0.4';
  } else if (isPaused) {
    badge.className = 'badge';
    badge.style.background = 'rgba(245,166,35,.15)';
    badge.style.color = '#f5a623';
    badgeTxt.textContent = 'На паузе';
    if (pulse) pulse.style.display = 'none';
    btnPause.textContent = '▶ Продолжить';
  } else {
    badge.className = 'badge running';
    badge.style.background = '';
    badge.style.color = '';
    badgeTxt.textContent = 'В процессе';
    if (pulse) { pulse.style.display = ''; }
    btnPause.textContent = '⏸ Пауза';
  }
}

let totalDeals = 0;
let dealsProcessed = 0;
let totalAdded = 0, totalSkipped = 0, totalNoInn = 0, totalNoPhones = 0;
let autoScroll = true;
let logCount = 0;

const dealsEl  = document.getElementById('dealsEl');
const logEl    = document.getElementById('logEl');
const badge    = document.getElementById('badge');
const badgeTxt = document.getElementById('badgeTxt');

function toggleScroll() {
  autoScroll = !autoScroll;
  document.getElementById('scrollBtn').textContent = autoScroll ? '⬇ авто' : '— стоп';
}
logEl.addEventListener('scroll', () => {
  const atBottom = logEl.scrollTop + logEl.clientHeight >= logEl.scrollHeight - 40;
  if (!atBottom) autoScroll = false;
});

const dealCards = {}; // deal_id → {el, contactsEl}

function addDealCard(num, dealId, name) {
  const card = document.createElement('div');
  card.className = 'deal-card';
  card.id = 'deal-' + dealId;

  const hdr = document.createElement('div');
  hdr.className = 'deal-hdr';
  hdr.innerHTML = `
    <div class="deal-num">${String(num).padStart(2,'0')}</div>
    <div class="deal-name">${escHtml(name)}</div>
    <div class="deal-badge db-active" id="db-${dealId}">…</div>
  `;

  const contacts = document.createElement('div');
  contacts.className = 'contacts';
  contacts.id = 'ct-' + dealId;

  card.appendChild(hdr);
  card.appendChild(contacts);
  dealsEl.appendChild(card);
  dealCards[dealId] = { card, contactsEl: contacts };

  dealsEl.scrollTop = dealsEl.scrollHeight;
  document.getElementById('deal-count').textContent = Object.keys(dealCards).length;
}

function addContactRow(dealId, contactId, name, status) {
  const dc = dealCards[dealId];
  if (!dc) return;

  const row = document.createElement('div');
  row.className = 'ct-row';
  row.id = 'ct-row-' + contactId;

  const icons = {added:'✅', skipped:'⏭', no_inn:'⚠️', no_phones:'🔍', error:'❌', searching:'🔄'};
  const labels = {added:'добавлено', skipped:'уже есть', no_inn:'нет ИНН', no_phones:'нет номеров', error:'ошибка', searching:'ищем…'};

  row.innerHTML = `
    <span class="ct-icon">${icons[status]||'·'}</span>
    <span class="ct-name">${escHtml(name)}</span>
    <span class="ct-status s-${status}">${labels[status]||status}</span>
  `;
  dc.contactsEl.appendChild(row);
}

function finishDeal(dealId, added, skipped, noInn, noPhones) {
  const dc = dealCards[dealId];
  if (!dc) return;
  dc.card.classList.remove('active');
  const db = document.getElementById('db-' + dealId);
  if (db) {
    if (added > 0) {
      db.className = 'deal-badge db-done';
      db.textContent = '+' + added + ' тел.';
    } else {
      db.className = 'deal-badge db-waiting';
      db.textContent = 'без изменений';
    }
  }
}

function updateStats() {
  document.getElementById('sv-added').textContent    = totalAdded;
  document.getElementById('sv-skipped').textContent  = totalSkipped;
  document.getElementById('sv-noinn').textContent    = totalNoInn;
  document.getElementById('sv-nophones').textContent = totalNoPhones;
  if (totalDeals > 0) {
    const pct = Math.round(dealsProcessed / totalDeals * 100);
    document.getElementById('progress').style.width = pct + '%';
    document.getElementById('progress-pct').textContent = pct + '%';
  }
}

function appendLog(text, kind) {
  const div = document.createElement('div');
  div.className = 'log-line ' + (kind || 'info');
  div.textContent = text;
  logEl.appendChild(div);
  logCount++;
  document.getElementById('log-count').textContent = logCount + ' строк';
  if (autoScroll) logEl.scrollTop = logEl.scrollHeight;
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// SSE
const es = new EventSource('/stream/' + RUN_ID);

es.onmessage = function(e) {
  const d = JSON.parse(e.data);
  appendLog(d.t, d.k || 'info');
  document.getElementById('log-status').textContent = 'работает…';
};

es.addEventListener('pipeline', function(e) {
  const evt = JSON.parse(e.data);

  if (evt.type === 'total_deals') {
    totalDeals = evt.total;
    document.getElementById('sv-deals').textContent = totalDeals;
    if (totalDeals === 0) {
      dealsEl.innerHTML = '<div style="padding:24px;color:var(--muted);font-size:13px;text-align:center">Сделок в Парсю не найдено</div>';
    }
  }

  if (evt.type === 'deal_start') {
    addDealCard(evt.num, evt.deal_id, evt.name);
    const card = document.getElementById('deal-' + evt.deal_id);
    if (card) card.classList.add('active');
  }

  if (evt.type === 'contact_done') {
    addContactRow(evt.deal_id, evt.contact_id, evt.name, evt.status);
    if (evt.status === 'added') totalAdded++;
    else if (evt.status === 'no_inn') totalNoInn++;
    else if (evt.status === 'no_phones') totalNoPhones++;
    updateStats();
  }

  if (evt.type === 'deal_done') {
    dealsProcessed++;
    totalSkipped += (evt.skipped || 0);
    finishDeal(evt.deal_id, evt.added, evt.skipped, evt.no_inn, evt.no_phones);
    updateStats();
  }
});

es.addEventListener('done', function(e) {
  es.close();
  isStopped = true;
  badge.className = 'badge done';
  badgeTxt.textContent = 'Завершено';
  document.title = 'Brizo Phones — готово';
  document.getElementById('log-status').textContent = 'завершено';
  document.getElementById('progress').style.width = '100%';
  document.getElementById('progress-pct').textContent = '100%';
  document.getElementById('pulse').style.display = 'none';
  document.getElementById('btnPause').disabled = true;
  document.getElementById('btnStop').disabled  = true;
  document.getElementById('btnPause').style.opacity = '0.4';
  document.getElementById('btnStop').style.opacity  = '0.4';
});

es.onerror = function() {
  if (es.readyState === EventSource.CLOSED) return;
  appendLog('[СОЕДИНЕНИЕ ПРЕРВАНО]', 'error');
  document.getElementById('log-status').textContent = 'ошибка соединения';
};
</script>
</body>
</html>"""


if __name__ == '__main__':
    print('Brizo Phones UI → http://localhost:8081')
    app.run(host='0.0.0.0', port=8081, debug=False, threaded=True)
