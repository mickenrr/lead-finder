#!/usr/bin/env python3
"""
Lead Finder Dashboard — веб-панель управления воркером
Запуск: python3 /opt/lead_finder/dashboard.py
Доступ: http://200.165.230.105:5000
"""

from flask import Flask, jsonify, request, Response
import subprocess
import re
import json
import csv
import io
import requests as _req
from datetime import datetime
from pathlib import Path

app = Flask(__name__)
BASE          = Path("/opt/lead_finder")
ENVFILE       = BASE / ".env"
ACCOUNTS_FILE = BASE / "accounts.json"
SETTINGS_FILE = BASE / "settings.json"
DAILY_TARGET  = 200

# ── Приоритетный каталог ОКВЭДов (13 кодов) ─────────────────────────────────
OKVED_CATALOG = [
    # Приоритет 1 — точные резиденты Сколково
    {"code": "72.19", "name": "Науч. исследования и разработки (физика, химия, инженерия, IT)", "priority": 1},
    {"code": "26.51", "name": "Производство приборов для измерений и навигации",                  "priority": 1},
    {"code": "26.60", "name": "Производство медицинской аппаратуры и оборудования",               "priority": 1},
    {"code": "21.20", "name": "Производство лекарственных препаратов",                            "priority": 1},
    {"code": "26.30", "name": "Производство телекоммуникационного оборудования",                  "priority": 1},
    {"code": "26.20", "name": "Производство компьютеров и периферийного оборудования",            "priority": 1},
    # Приоритет 2 — потенциальные резиденты
    {"code": "62.01", "name": "Разработка компьютерного ПО (много компаний, в т.ч. гиганты)",    "priority": 2},
    {"code": "26.70", "name": "Производство оптических приборов и фотоаппаратуры",               "priority": 2},
    {"code": "26.10", "name": "Производство электронных компонентов",                             "priority": 2},
    {"code": "71.20", "name": "Технические испытания и анализ",                                   "priority": 2},
    {"code": "62.02", "name": "Консультирование в области ИТ",                                    "priority": 2},
    {"code": "63.11", "name": "Обработка данных, размещение информации",                          "priority": 2},
    {"code": "62.09", "name": "Деятельность в области ИТ прочая",                                "priority": 2},
]

# ── Полный справочник ОКВЭДов ─────────────────────────────────────────────────
OKVED_FULL_CATALOG = [
    # ── Раздел C: Обрабатывающие производства ─────────────────────────────────
    {"code": "20.11", "name": "Производство промышленных газов",                                   "section": "C"},
    {"code": "20.12", "name": "Производство красителей и пигментов",                              "section": "C"},
    {"code": "20.13", "name": "Производство прочих неорганических химических веществ",             "section": "C"},
    {"code": "20.14", "name": "Производство прочих органических химических веществ",               "section": "C"},
    {"code": "20.16", "name": "Производство пластмасс в первичных формах",                        "section": "C"},
    {"code": "20.17", "name": "Производство синтетического каучука",                              "section": "C"},
    {"code": "20.59", "name": "Производство химических продуктов прочих",                         "section": "C"},
    {"code": "21.10", "name": "Производство основных фармацевтических субстанций",                 "section": "C"},
    {"code": "21.20", "name": "Производство лекарственных препаратов",                            "section": "C"},
    {"code": "26.10", "name": "Производство электронных компонентов",                             "section": "C"},
    {"code": "26.20", "name": "Производство компьютеров и периферийного оборудования",            "section": "C"},
    {"code": "26.30", "name": "Производство коммуникационного оборудования",                      "section": "C"},
    {"code": "26.40", "name": "Производство бытовой электроники",                                 "section": "C"},
    {"code": "26.51", "name": "Производство приборов для измерений, испытаний и навигации",       "section": "C"},
    {"code": "26.52", "name": "Производство часов",                                               "section": "C"},
    {"code": "26.60", "name": "Производство медицинской аппаратуры и оборудования",               "section": "C"},
    {"code": "26.70", "name": "Производство оптических приборов и фотоаппаратуры",               "section": "C"},
    {"code": "26.80", "name": "Производство магнитных и оптических носителей информации",         "section": "C"},
    {"code": "27.11", "name": "Производство электродвигателей, генераторов и трансформаторов",    "section": "C"},
    {"code": "27.12", "name": "Производство электрической распределительной аппаратуры",          "section": "C"},
    {"code": "27.20", "name": "Производство аккумуляторов и батарей",                            "section": "C"},
    {"code": "27.31", "name": "Производство волоконно-оптических кабелей",                        "section": "C"},
    {"code": "27.32", "name": "Производство прочих электрических проводов и кабелей",             "section": "C"},
    {"code": "27.40", "name": "Производство электрических ламп и светильников",                   "section": "C"},
    {"code": "27.51", "name": "Производство бытовых электрических приборов",                      "section": "C"},
    {"code": "27.90", "name": "Производство прочего электрического оборудования",                 "section": "C"},
    {"code": "28.11", "name": "Производство двигателей и турбин",                                 "section": "C"},
    {"code": "28.12", "name": "Производство гидравлического и пневматического оборудования",      "section": "C"},
    {"code": "28.13", "name": "Производство прочих насосов и компрессоров",                       "section": "C"},
    {"code": "28.14", "name": "Производство прочих кранов и клапанов",                           "section": "C"},
    {"code": "28.15", "name": "Производство подшипников, зубчатых передач",                       "section": "C"},
    {"code": "28.22", "name": "Производство подъёмно-транспортного оборудования",                 "section": "C"},
    {"code": "28.23", "name": "Производство офисных машин и оборудования",                        "section": "C"},
    {"code": "28.25", "name": "Производство промышленного холодильного оборудования",             "section": "C"},
    {"code": "28.29", "name": "Производство машин общего назначения прочих",                      "section": "C"},
    {"code": "28.41", "name": "Производство металлообрабатывающего оборудования",                 "section": "C"},
    {"code": "28.49", "name": "Производство прочих станков",                                      "section": "C"},
    {"code": "28.91", "name": "Производство машин для добычи полезных ископаемых",                "section": "C"},
    {"code": "28.92", "name": "Производство землеройных машин",                                   "section": "C"},
    {"code": "28.96", "name": "Производство оборудования для переработки пластмасс",              "section": "C"},
    {"code": "28.99", "name": "Производство машин специального назначения прочих",                "section": "C"},
    {"code": "30.10", "name": "Строительство судов и плавучих конструкций",                       "section": "C"},
    {"code": "30.30", "name": "Производство летательных и космических аппаратов",                 "section": "C"},
    {"code": "30.40", "name": "Производство военных транспортных средств",                        "section": "C"},
    {"code": "32.50", "name": "Производство медицинских инструментов и оборудования",             "section": "C"},
    # ── Раздел J: Информация и связь ──────────────────────────────────────────
    {"code": "58.29", "name": "Издание прочего программного обеспечения",                         "section": "J"},
    {"code": "61.10", "name": "Деятельность в области проводной электросвязи",                    "section": "J"},
    {"code": "61.20", "name": "Деятельность в области беспроводной электросвязи",                 "section": "J"},
    {"code": "61.30", "name": "Деятельность в области спутниковой электросвязи",                  "section": "J"},
    {"code": "61.90", "name": "Деятельность в области электросвязи прочая",                       "section": "J"},
    {"code": "62.01", "name": "Разработка компьютерного программного обеспечения",                "section": "J"},
    {"code": "62.02", "name": "Консультирование и работы в области ИТ",                           "section": "J"},
    {"code": "62.02.1","name": "Планирование и проектирование компьютерных систем",               "section": "J"},
    {"code": "62.03", "name": "Управление компьютерным оборудованием",                            "section": "J"},
    {"code": "62.09", "name": "Деятельность в области информационных технологий прочая",          "section": "J"},
    {"code": "63.11", "name": "Обработка данных, размещение информации",                          "section": "J"},
    {"code": "63.11.1","name": "Деятельность по созданию и использованию баз данных",             "section": "J"},
    {"code": "63.12", "name": "Деятельность web-порталов",                                        "section": "J"},
    # ── Раздел M: Профессиональная и научная деятельность ────────────────────
    {"code": "70.22", "name": "Консультирование по вопросам управления",                          "section": "M"},
    {"code": "71.12", "name": "Деятельность в области инженерных изысканий",                      "section": "M"},
    {"code": "71.20", "name": "Технические испытания, исследования, анализ",                      "section": "M"},
    {"code": "72.11", "name": "Исследования и разработки в области биотехнологий",                "section": "M"},
    {"code": "72.19", "name": "Научные исследования и разработки прочие (физика, химия, IT)",     "section": "M"},
    {"code": "72.20", "name": "Исследования и разработки в области общественных наук",            "section": "M"},
    {"code": "73.10", "name": "Рекламная деятельность",                                           "section": "M"},
    {"code": "73.20", "name": "Исследование конъюнктуры рынка",                                   "section": "M"},
    {"code": "74.10", "name": "Деятельность в области промышленного дизайна",                     "section": "M"},
    {"code": "74.30", "name": "Деятельность по письменному и устному переводу",                   "section": "M"},
    {"code": "74.90", "name": "Деятельность профессиональная, научная и техническая прочая",      "section": "M"},
    # ── Раздел P: Образование ────────────────────────────────────────────────
    {"code": "85.30", "name": "Обучение профессиям (техникумы, колледжи)",                        "section": "P"},
    {"code": "85.41", "name": "Дополнительное образование детей и взрослых",                      "section": "P"},
    {"code": "85.42", "name": "Дополнительное профессиональное образование",                      "section": "P"},
    # ── Раздел Q: Здравоохранение ─────────────────────────────────────────────
    {"code": "86.10", "name": "Деятельность больничных организаций",                              "section": "Q"},
    {"code": "86.21", "name": "Общая врачебная практика",                                         "section": "Q"},
    {"code": "86.90", "name": "Деятельность в области здравоохранения прочая",                    "section": "Q"},
]

_FULL_CATALOG_SECTION_NAMES = {
    "C": "Раздел C — Обрабатывающие производства",
    "J": "Раздел J — Информация и связь",
    "M": "Раздел M — Профессиональная и научная деятельность",
    "P": "Раздел P — Образование",
    "Q": "Раздел Q — Здравоохранение",
}

DEFAULT_INCOME_TAX_RULE = {
    "mode":       "any",   # "any" | "last" | "all" | "k_of_n"
    "years":      3,
    "min_amount": 5_000_000,
    "k":          1,
}

DEFAULT_ADVANCED_FINANCE = {
    "transport_tax_min": 0,
    "property_tax_min":  0,
    "insurance_min":     0,
    "vat_min":           0,
}

DEFAULT_SETTINGS = {
    "okved_codes":       ["72.19", "26.51", "26.60", "21.20", "26.30"],
    "revenue_max":       1_000_000_000,
    "revenue_min":       0,
    "income_tax_rule":   dict(DEFAULT_INCOME_TAX_RULE),
    "advanced_finance":  dict(DEFAULT_ADVANCED_FINANCE),
}

def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            s = json.loads(SETTINGS_FILE.read_text())
            # Миграция старого формата income_tax_min → income_tax_rule
            if "income_tax_min" in s and "income_tax_rule" not in s:
                s["income_tax_rule"] = {**DEFAULT_INCOME_TAX_RULE,
                                        "min_amount": s.pop("income_tax_min")}
            # заполняем отсутствующие ключи дефолтами
            for k, v in DEFAULT_SETTINGS.items():
                if k not in s:
                    s[k] = v
                elif isinstance(v, dict):
                    for kk, vv in v.items():
                        s[k].setdefault(kk, vv)
            return s
        except Exception:
            pass
    return {k: (v.copy() if isinstance(v, dict) else v) for k, v in DEFAULT_SETTINGS.items()}

def save_settings(data: dict) -> None:
    SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


# ─────────────────────────────────────────────────────────────────────────────
# Утилиты воркера
# ─────────────────────────────────────────────────────────────────────────────

def get_pids():
    r = subprocess.run(["pgrep", "-f", "lead_finder.py"], capture_output=True, text=True)
    raw = r.stdout.strip()
    return [p for p in raw.split("\n") if p] if raw else []

def is_running():
    return len(get_pids()) > 0

def last_log_lines(n: int = 80) -> list:
    log = BASE / "w1" / "worker.log"
    if not log.exists():
        return []
    r = subprocess.run(["tail", f"-{n}", str(log)], capture_output=True, text=True)
    return r.stdout.strip().split("\n") if r.stdout.strip() else []


# ─────────────────────────────────────────────────────────────────────────────
# Детальный парсинг лога
# ─────────────────────────────────────────────────────────────────────────────

REASON_LABELS = {
    "Маленькая выручка/мало налогов": "Мало налога на прибыль",
    "Интересные, но ярд":             "Выручка > 1 млрд",
    "Нет КД":                         "Нет сайта",
}

def parse_log_analytics(worker: str = "w1") -> dict:
    """Полный парсинг лога: статистика по ОКВЭДам, причины отсева."""
    log = BASE / worker / "worker.log"
    empty = {
        "stats":              {"checked":0,"created":0,"duplicate":0,"rejected":0,"error":0,"okved_fail":0},
        "okved_data":         {},
        "rejection_reasons":  {},
    }
    if not log.exists():
        return empty

    r = subprocess.run(["grep", "PIPELINE_EVENT:", str(log)], capture_output=True, text=True)
    if not r.stdout.strip():
        return empty

    stats       = dict(empty["stats"])   # накопленный итог по всем сессиям
    sess_stats  = {k: 0 for k in empty["stats"]}  # пик текущей сессии
    in_session  = False
    okved_data  = {}
    rej_raw     = {}
    cur_okved   = None

    for line in r.stdout.split("\n"):
        if "PIPELINE_EVENT:" not in line:
            continue
        try:
            payload = json.loads(line.split("PIPELINE_EVENT:", 1)[1])
        except Exception:
            continue

        t = payload.get("type", "")

        if t == "started":
            # Сбрасываем предыдущую сессию в итог и начинаем новую
            if in_session:
                for k in stats:
                    stats[k] += sess_stats.get(k, 0)
            sess_stats = {k: 0 for k in stats}
            in_session = True

        elif t == "stats_update":
            # Берём максимум внутри сессии (счётчики растут монотонно)
            for k in sess_stats:
                sess_stats[k] = max(sess_stats[k], payload.get(k, 0))

        elif t == "page_scraped":
            code = payload.get("okved") or payload.get("code", "")
            if code:
                cur_okved = code
                if code not in okved_data:
                    okved_data[code] = {"companies": 0, "created": 0, "rejected": 0, "duplicate": 0}
                okved_data[code]["companies"] += payload.get("count", 0)

        elif t == "company_result":
            res    = payload.get("result", "")
            reason = payload.get("reason", "")
            if res == "rejected" and reason:
                lbl = REASON_LABELS.get(reason, reason)
                rej_raw[lbl] = rej_raw.get(lbl, 0) + 1
            if cur_okved and cur_okved in okved_data:
                if res in ("created", "rejected", "duplicate"):
                    okved_data[cur_okved][res] += 1

    # Сливаем последнюю (текущую) сессию в итог
    if in_session:
        for k in stats:
            stats[k] += sess_stats.get(k, 0)

    # Добавляем okved_fail и дубли в причины отсева
    if stats["okved_fail"] > 0:
        rej_raw["Не тот ОКВЭД"] = rej_raw.get("Не тот ОКВЭД", 0) + stats["okved_fail"]
    if stats["duplicate"] > 0:
        rej_raw["Уже есть в Brizo"] = rej_raw.get("Уже есть в Brizo", 0) + stats["duplicate"]
    if stats["error"] > 0:
        rej_raw["Ошибки / прокси"] = rej_raw.get("Ошибки / прокси", 0) + stats["error"]

    conv = round(stats["created"] / stats["checked"] * 100, 1) if stats["checked"] else 0
    stats["conversion"] = conv

    # Конверсия по каждому ОКВЭДу
    for code, d in okved_data.items():
        total = d["created"] + d["rejected"] + d["duplicate"]
        d["conversion"] = round(d["created"] / total * 100, 1) if total > 0 else 0

    return {
        "stats":             stats,
        "okved_data":        okved_data,
        "rejection_reasons": rej_raw,
    }


# ─────────────────────────────────────────────────────────────────────────────
# .env и история аккаунтов
# ─────────────────────────────────────────────────────────────────────────────

def read_env() -> dict:
    env = {}
    if not ENVFILE.exists():
        return env
    for line in ENVFILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()
    return env

def write_env_key(key: str, value: str) -> None:
    content = ENVFILE.read_text() if ENVFILE.exists() else ""
    pattern = re.compile(rf"^{re.escape(key)}\s*=.*$", re.MULTILINE)
    new_line = f"{key}={value}"
    content = pattern.sub(new_line, content) if pattern.search(content) else content.rstrip("\n") + f"\n{new_line}\n"
    ENVFILE.write_text(content)

def load_accounts() -> dict:
    if ACCOUNTS_FILE.exists():
        try:
            return json.loads(ACCOUNTS_FILE.read_text())
        except Exception:
            pass
    email = read_env().get("BRIZO_EMAIL", "")
    data = {"current": email,
            "history": [{"email": email, "added": datetime.now().strftime("%d.%m.%Y")}] if email else []}
    ACCOUNTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return data

def save_accounts(data: dict) -> None:
    ACCOUNTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))

def add_to_history(email: str) -> None:
    data = load_accounts()
    data["history"] = [h for h in data["history"] if h["email"] != email]
    data["history"].insert(0, {"email": email, "added": datetime.now().strftime("%d.%m.%Y")})
    data["history"] = data["history"][:10]
    data["current"] = email
    save_accounts(data)

def brizo_check_login(url: str, email: str, password: str) -> dict:
    try:
        resp = _req.post(url.rstrip("/") + "/api/v4/auth/token",
                         json={"email": email, "password": password}, timeout=10)
        if resp.status_code == 200:
            d = resp.json()
            name = d.get("user", {}).get("name") or d.get("name") or email
            return {"ok": True, "name": name}
        return {"ok": False, "err": "Неверный логин или пароль" if resp.status_code in (401,403,422)
                else f"Brizo вернул {resp.status_code}"}
    except Exception as e:
        return {"ok": False, "err": f"Нет связи с Brizo: {e}"}


# ─────────────────────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    pids     = get_pids()
    accounts = load_accounts()
    return jsonify({
        "running":       is_running(),
        "process_count": len(pids),
        "time":          datetime.now().strftime("%H:%M:%S"),
        "account_email": accounts.get("current", "—"),
    })

@app.route("/api/analytics")
def api_analytics():
    data = parse_log_analytics("w1")
    data["daily_target"] = DAILY_TARGET
    return jsonify(data)

@app.route("/api/logs")
def api_logs():
    return jsonify({"lines": last_log_lines(80)})

@app.route("/api/start", methods=["POST"])
def api_start():
    if is_running():
        return jsonify({"ok": False, "msg": "Воркер уже запущен"})
    subprocess.Popen("nohup /opt/lead_finder/w1/run.sh >> /opt/lead_finder/w1/worker.log 2>&1 &", shell=True)
    return jsonify({"ok": True, "msg": "Запускаем воркер…"})

@app.route("/api/stop", methods=["POST"])
def api_stop():
    subprocess.run(["pkill", "-f", "lead_finder.py"], capture_output=True)
    return jsonify({"ok": True, "msg": "Воркер остановлен"})

@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    return jsonify({
        "settings":    load_settings(),
        "catalog":     OKVED_CATALOG,
        "full_catalog": OKVED_FULL_CATALOG,
        "section_names": _FULL_CATALOG_SECTION_NAMES,
    })

@app.route("/api/settings", methods=["POST"])
def api_settings_post():
    data = request.json or {}
    s = load_settings()
    if "okved_codes" in data:
        codes = [c for c in data["okved_codes"] if isinstance(c, str) and c.strip()]
        if codes:
            s["okved_codes"] = codes
    for key in ("revenue_max", "revenue_min"):
        if key in data:
            try:
                s[key] = int(data[key])
            except (ValueError, TypeError):
                pass
    # income_tax_rule
    if "income_tax_rule" in data and isinstance(data["income_tax_rule"], dict):
        r = data["income_tax_rule"]
        rule = s.setdefault("income_tax_rule", dict(DEFAULT_INCOME_TAX_RULE))
        if r.get("mode") in ("any", "last", "all", "k_of_n"):
            rule["mode"] = r["mode"]
        for rk in ("years", "min_amount", "k"):
            if rk in r:
                try:
                    rule[rk] = int(r[rk])
                except (ValueError, TypeError):
                    pass
    # advanced_finance
    if "advanced_finance" in data and isinstance(data["advanced_finance"], dict):
        af = s.setdefault("advanced_finance", dict(DEFAULT_ADVANCED_FINANCE))
        for fk in ("transport_tax_min", "property_tax_min", "insurance_min", "vat_min"):
            if fk in data["advanced_finance"]:
                try:
                    af[fk] = int(data["advanced_finance"][fk])
                except (ValueError, TypeError):
                    pass
    save_settings(s)
    return jsonify({"ok": True, "settings": s})

@app.route("/api/restart", methods=["POST"])
def api_restart():
    import time as _t
    subprocess.run(["pkill", "-f", "lead_finder.py"], capture_output=True)
    _t.sleep(1)
    subprocess.Popen(
        "setsid bash /opt/lead_finder/w1/run.sh >> /opt/lead_finder/w1/worker.log 2>&1 &",
        shell=True,
    )
    return jsonify({"ok": True, "msg": "Воркер перезапущен с новыми настройками"})

@app.route("/api/account", methods=["GET"])
def api_account_get():
    acc = load_accounts()
    return jsonify({"current": acc.get("current",""), "history": acc.get("history",[])})

@app.route("/api/account", methods=["POST"])
def api_account_set():
    body     = request.get_json(force=True) or {}
    email    = (body.get("email") or "").strip()
    password = (body.get("password") or "").strip()
    if not email or not password:
        return jsonify({"ok": False, "msg": "Введите email и пароль"})
    env   = read_env()
    check = brizo_check_login(env.get("BRIZO_URL","https://sad1.brizo.ru"), email, password)
    if not check["ok"]:
        return jsonify({"ok": False, "msg": check["err"]})
    write_env_key("BRIZO_EMAIL", email)
    write_env_key("BRIZO_PASSWORD", password)
    add_to_history(email)
    was_running = is_running()
    if was_running:
        import time
        subprocess.run(["pkill", "-f", "lead_finder.py"], capture_output=True)
        time.sleep(2)
        subprocess.Popen("nohup /opt/lead_finder/w1/run.sh >> /opt/lead_finder/w1/worker.log 2>&1 &", shell=True)
    return jsonify({"ok": True, "msg": f"Аккаунт сохранён.{' Воркер перезапущен.' if was_running else ''}", "email": email})


# ─────────────────────────────────────────────────────────────────────────────
# HTML
# ─────────────────────────────────────────────────────────────────────────────

HTML = r"""<!doctype html>
<html lang="ru" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lead Finder · Analytics</title>
<script>(function(){var t=localStorage.getItem('lf-theme')||'dark';document.documentElement.setAttribute('data-theme',t);})();</script>
<style>
:root{--bg:#080c12;--s1:#0d1626;--s2:#111d30;--border:#1c2a40;--border2:#243350;--text:#d6e0f5;--text2:#8fa0bf;--muted:#3d5070;--green:#2ecc71;--green2:#1fa855;--red:#e74c5a;--yellow:#f39c12;--blue:#3d8ef8;--blue2:#2060cc;--cyan:#1abc9c;--r:12px;--mono:'Menlo','Consolas',monospace;--shadow:0 2px 20px rgba(0,0,0,.3);}
[data-theme="light"]{--bg:#f0f4fc;--s1:#ffffff;--s2:#f4f7fd;--border:#dde4f5;--border2:#c8d4ee;--text:#1a2535;--text2:#4a6080;--shadow:0 2px 20px rgba(30,60,120,.08);}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--bg);color:var(--text);font-family:-apple-system,'Segoe UI',sans-serif;font-size:14px;line-height:1.5;min-height:100vh;transition:background .2s,color .2s;}
body::before{content:'';position:fixed;inset:0;background-image:radial-gradient(rgba(61,142,248,.04) 1px,transparent 1px);background-size:28px 28px;pointer-events:none;z-index:0;}
[data-theme="light"] body::before{background-image:radial-gradient(rgba(61,142,248,.07) 1px,transparent 1px);}
header,main,.overlay{position:relative;z-index:1;}
header{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;padding:13px 28px;background:rgba(13,22,38,.95);backdrop-filter:blur(10px);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:20;transition:background .2s;}
[data-theme="light"] header{background:rgba(240,244,252,.95);}
.brand{display:flex;align-items:center;gap:10px;}
.brand-icon{width:32px;height:32px;border-radius:8px;background:linear-gradient(135deg,#1a3060,var(--blue2));display:flex;align-items:center;justify-content:center;flex-shrink:0;box-shadow:0 0 0 1px rgba(61,142,248,.3),0 3px 10px rgba(32,96,204,.4);}
.brand-icon svg{width:15px;height:15px;color:#90b8ff;}
.brand-name{font-weight:800;font-size:15px;letter-spacing:-.4px;}
.brand-sub{font-size:11px;color:var(--text2);margin-top:-1px;}
.header-right{display:flex;align-items:center;gap:10px;flex-wrap:wrap;}
.time-tag{color:var(--muted);font-size:12px;font-family:var(--mono);}
.account-area{display:flex;align-items:center;gap:7px;}
.account-label{font-size:11px;color:var(--muted);}
.account-email{font-size:12px;font-weight:600;max-width:170px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.btn-change{display:inline-flex;align-items:center;gap:5px;padding:4px 9px;background:none;border:1px solid var(--border2);border-radius:6px;color:var(--text2);font-size:11px;cursor:pointer;transition:border-color .15s,color .15s;}
.btn-change:hover{border-color:var(--blue);color:var(--blue);}
.btn-change svg{width:11px;height:11px;}
.theme-btn{width:32px;height:32px;border-radius:8px;background:none;border:1px solid var(--border2);display:flex;align-items:center;justify-content:center;cursor:pointer;color:var(--text2);transition:border-color .15s,color .15s;}
.theme-btn:hover{border-color:var(--blue);color:var(--blue);}
.theme-btn svg{width:15px;height:15px;}
.status-pill{display:inline-flex;align-items:center;gap:6px;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:600;}
.status-pill.running{background:rgba(46,204,113,.1);color:var(--green);border:1px solid rgba(46,204,113,.25);}
.status-pill.stopped{background:rgba(231,76,90,.1);color:var(--red);border:1px solid rgba(231,76,90,.25);}
.status-dot{width:7px;height:7px;border-radius:50%;background:currentColor;}
.status-pill.running .status-dot{animation:pdot 1.8s ease-in-out infinite;box-shadow:0 0 5px currentColor;}
@keyframes pdot{0%,100%{opacity:1}50%{opacity:.35}}
.overlay{position:fixed;inset:0;background:rgba(4,8,16,.8);backdrop-filter:blur(8px);display:none;align-items:center;justify-content:center;z-index:50;}
.overlay.open{display:flex;}
.modal{background:var(--s1);border:1px solid var(--border2);border-radius:16px;padding:28px 30px;width:100%;max-width:410px;box-shadow:0 24px 70px rgba(0,0,0,.6);animation:mopen .22s cubic-bezier(.34,1.4,.64,1);}
@keyframes mopen{from{opacity:0;transform:translateY(14px) scale(.97)}to{opacity:1;transform:none}}
.modal-title{font-size:16px;font-weight:800;margin-bottom:5px;}
.modal-sub{color:var(--text2);font-size:13px;margin-bottom:22px;line-height:1.5;}
.confirm-box{display:flex;align-items:center;gap:11px;padding:12px 14px;border-radius:10px;background:rgba(255,255,255,.03);border:1px solid var(--border2);margin-bottom:22px;}
.conf-avatar{width:34px;height:34px;border-radius:50%;background:rgba(61,142,248,.15);color:var(--blue);font-size:13px;font-weight:800;display:flex;align-items:center;justify-content:center;flex-shrink:0;border:1px solid rgba(61,142,248,.2);}
.conf-email{font-size:13px;font-weight:600;}
.conf-lbl{font-size:11px;color:var(--text2);}
.conf-actions{display:flex;gap:10px;}
.btn-no{flex:1;padding:11px;background:rgba(255,255,255,.05);color:var(--text);border:1px solid var(--border2);border-radius:8px;font-size:14px;cursor:pointer;}
.btn-yes{flex:1;padding:11px;background:linear-gradient(135deg,var(--blue2),var(--blue));color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:700;cursor:pointer;}
.sec-lbl{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:9px;}
.hist-list{display:flex;flex-direction:column;gap:5px;margin-bottom:20px;}
.hist-item{display:flex;align-items:center;gap:9px;padding:9px 11px;border-radius:8px;background:rgba(255,255,255,.03);border:1px solid var(--border);cursor:pointer;transition:border-color .15s,background .15s;}
.hist-item:hover{border-color:var(--blue);background:rgba(61,142,248,.05);}
.hist-item.sel{border-color:var(--blue);background:rgba(61,142,248,.08);}
.hist-av{width:26px;height:26px;border-radius:50%;background:rgba(255,255,255,.06);color:var(--text2);font-size:10px;font-weight:700;display:flex;align-items:center;justify-content:center;flex-shrink:0;}
.hist-item.sel .hist-av{background:rgba(61,142,248,.2);color:var(--blue);}
.hist-email{font-size:13px;font-weight:500;}
.hist-date{font-size:11px;color:var(--text2);}
.divider{border:none;border-top:1px solid var(--border);margin:16px 0;}
.field{margin-bottom:11px;}
.field label{display:block;font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.8px;margin-bottom:5px;}
.field input{width:100%;padding:10px 12px;background:rgba(255,255,255,.04);border:1px solid var(--border2);border-radius:8px;color:var(--text);font-size:14px;outline:none;transition:border-color .15s,box-shadow .15s;}
[data-theme="light"] .field input{background:var(--s2);}
.field input:focus{border-color:var(--blue);box-shadow:0 0 0 3px rgba(61,142,248,.1);}
.field input::placeholder{color:var(--muted);}
.m-actions{display:flex;gap:10px;margin-top:18px;}
.btn-save{flex:1;padding:11px;background:linear-gradient(135deg,var(--green2),var(--green));color:#02100a;border:none;border-radius:8px;font-size:14px;font-weight:800;cursor:pointer;transition:opacity .15s;}
.btn-save:hover{opacity:.85;}
.btn-save:disabled{opacity:.4;cursor:default;}
.btn-back{padding:11px 16px;background:rgba(255,255,255,.05);color:var(--text);border:1px solid var(--border2);border-radius:8px;font-size:14px;cursor:pointer;}
.m-msg{margin-top:11px;font-size:12px;padding:8px 12px;border-radius:7px;display:none;}
.m-msg.ok{background:rgba(46,204,113,.1);color:var(--green);display:block;border:1px solid rgba(46,204,113,.2);}
.m-msg.err{background:rgba(231,76,90,.1);color:var(--red);display:block;border:1px solid rgba(231,76,90,.2);}
main{max-width:1000px;margin:0 auto;padding:26px 20px 48px;}
.view{display:none;}
.view.active{display:block;}
.controls{display:flex;gap:10px;align-items:center;margin-bottom:22px;}
.btn{padding:9px 20px;border:none;border-radius:8px;font-size:14px;font-weight:700;cursor:pointer;display:inline-flex;align-items:center;gap:7px;transition:opacity .15s,transform .1s,box-shadow .15s;}
.btn:active{transform:scale(.96);}
.btn:disabled{opacity:.35;cursor:default;}
.btn-start{background:linear-gradient(135deg,var(--green2),var(--green));color:#02100a;box-shadow:0 3px 12px rgba(46,204,113,.2);}
.btn-start:hover:not(:disabled){box-shadow:0 3px 20px rgba(46,204,113,.4);}
.btn-stop{background:linear-gradient(135deg,#a02030,var(--red));color:#fff;box-shadow:0 3px 12px rgba(231,76,90,.2);}
.btn-report{background:none;border:1px solid var(--border2);color:var(--text2);padding:9px 18px;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;gap:7px;margin-left:auto;transition:border-color .15s,color .15s;}
.btn-report:hover{border-color:var(--blue);color:var(--blue);}
.btn-report svg{width:14px;height:14px;}
.toast{padding:7px 13px;border-radius:7px;font-size:13px;background:var(--s1);border:1px solid var(--border2);color:var(--text);opacity:0;transition:opacity .25s;}
.toast.show{opacity:1;}
.kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin-bottom:20px;}
.kpi-card{background:var(--s1);border:1px solid var(--border);border-radius:var(--r);padding:18px 20px;position:relative;overflow:hidden;box-shadow:var(--shadow);}
.kpi-card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;}
.kpi-card.kc-green::before{background:linear-gradient(90deg,var(--green2),var(--green));}
.kpi-card.kc-blue::before{background:linear-gradient(90deg,var(--blue2),var(--blue));}
.kpi-card.kc-yellow::before{background:linear-gradient(90deg,#c0780a,var(--yellow));}
.kpi-card.kc-cyan::before{background:linear-gradient(90deg,#0e7a66,var(--cyan));}
.kpi-label{font-size:10px;color:var(--text2);text-transform:uppercase;letter-spacing:.9px;margin-bottom:8px;}
.kpi-value{font-size:36px;font-weight:900;letter-spacing:-1.5px;line-height:1;}
.kpi-value.cv-green{color:var(--green);}
.kpi-value.cv-blue{color:var(--blue);}
.kpi-value.cv-yellow{color:var(--yellow);}
.kpi-value.cv-cyan{color:var(--cyan);}
.kpi-sub{font-size:11px;color:var(--muted);margin-top:5px;}
.progress-card{background:var(--s1);border:1px solid var(--border);border-radius:var(--r);padding:18px 22px;margin-bottom:20px;box-shadow:var(--shadow);}
.progress-head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px;}
.progress-title{font-size:12px;color:var(--text2);text-transform:uppercase;letter-spacing:.7px;}
.progress-frac{font-family:var(--mono);font-size:14px;font-weight:700;color:var(--text);}
.progress-frac span{color:var(--muted);font-weight:400;}
.progress-bg{height:8px;border-radius:4px;background:rgba(255,255,255,.06);overflow:hidden;}
[data-theme="light"] .progress-bg{background:var(--border);}
.progress-fill{height:100%;border-radius:4px;background:linear-gradient(90deg,var(--green2),var(--green),#6ee89a,var(--green));background-size:300% 100%;animation:shimmer 3s linear infinite;transition:width .7s cubic-bezier(.4,0,.2,1);min-width:3px;}
@keyframes shimmer{0%{background-position:100% 0}100%{background-position:-200% 0}}
.progress-sub{font-size:11px;color:var(--muted);margin-top:6px;}
.progress-done{font-size:11px;color:var(--green);margin-top:6px;}
.charts-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px;}
@media(max-width:680px){.charts-grid{grid-template-columns:1fr;}}
.chart-card{background:var(--s1);border:1px solid var(--border);border-radius:var(--r);padding:20px 22px;box-shadow:var(--shadow);}
.chart-title{font-size:13px;font-weight:700;margin-bottom:4px;}
.chart-sub{font-size:11px;color:var(--text2);margin-bottom:18px;}
.okved-bars{display:flex;flex-direction:column;gap:10px;}
.okved-row{display:flex;align-items:center;gap:10px;}
.okved-code{font-size:11px;font-family:var(--mono);color:var(--text2);width:44px;flex-shrink:0;text-align:right;}
.okved-bar-wrap{flex:1;height:20px;background:rgba(255,255,255,.04);border-radius:4px;overflow:hidden;position:relative;}
[data-theme="light"] .okved-bar-wrap{background:var(--border);}
.okved-bar-bg{height:100%;border-radius:4px;background:rgba(61,142,248,.18);position:absolute;top:0;left:0;}
.okved-bar-cr{height:100%;border-radius:4px;background:rgba(46,204,113,.55);position:absolute;top:0;left:0;}
.okved-count{font-size:11px;font-family:var(--mono);color:var(--text2);width:36px;flex-shrink:0;}
.okved-conv{font-size:10px;width:36px;flex-shrink:0;text-align:right;font-family:var(--mono);}
.okved-conv.good{color:var(--green);}
.okved-conv.ok{color:var(--yellow);}
.okved-conv.low{color:var(--muted);}
.okved-empty{color:var(--muted);font-size:13px;padding:20px 0;text-align:center;}
.chart-legend{display:flex;gap:14px;margin-top:14px;}
.cleg-item{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--text2);}
.cleg-dot{width:10px;height:10px;border-radius:2px;}
.donut-wrap{display:flex;gap:20px;align-items:center;}
.donut-container{position:relative;flex-shrink:0;}
.donut-center{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;pointer-events:none;}
.donut-main{font-size:26px;font-weight:900;line-height:1;letter-spacing:-1px;}
.donut-lbl{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px;margin-top:3px;}
.legend-list{display:flex;flex-direction:column;gap:8px;flex:1;min-width:0;}
.legend-row{display:flex;align-items:center;gap:8px;}
.leg-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0;}
.leg-name{font-size:11px;color:var(--text2);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.leg-val{font-size:12px;font-weight:700;font-family:var(--mono);color:var(--text);flex-shrink:0;}
.leg-pct{font-size:10px;color:var(--muted);margin-left:2px;flex-shrink:0;}
.log-toggle-btn{display:inline-flex;align-items:center;gap:7px;padding:9px 15px;border:1px solid var(--border);border-radius:9px;background:none;color:var(--text2);font-size:13px;cursor:pointer;transition:border-color .15s,color .15s;margin-bottom:14px;}
.log-toggle-btn:hover{border-color:var(--blue);color:var(--blue);}
.log-toggle-btn svg{width:14px;height:14px;}
.log-panel{background:var(--s1);border:1px solid var(--border);border-radius:var(--r);display:none;}
.log-panel.open{display:block;}
.log-header{padding:12px 18px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;}
.log-title{font-weight:700;font-size:13px;}
.log-close{background:none;border:none;color:var(--muted);cursor:pointer;font-size:18px;line-height:1;padding:0 4px;}
.log-close:hover{color:var(--text);}
.log-body{padding:14px 18px;max-height:380px;overflow-y:auto;font-family:var(--mono);font-size:11px;line-height:1.75;color:#5a7090;white-space:pre-wrap;word-break:break-all;}
.log-body::-webkit-scrollbar{width:4px;}
.log-body::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px;}
.lo{color:var(--green);}
.le{color:var(--red);}
.lw{color:var(--yellow);}
/* Reports */
.rpt-header{display:flex;align-items:center;gap:14px;margin-bottom:22px;}
.set-section{background:var(--s1);border:1px solid var(--border);border-radius:14px;padding:22px 24px;margin-bottom:18px;}
.set-section-title{font-size:15px;font-weight:700;margin-bottom:16px;letter-spacing:-.3px;}
.set-hint{border-radius:10px;padding:14px 16px;margin-bottom:14px;}
.set-hint-p1{background:rgba(46,204,113,.08);border:1px solid rgba(46,204,113,.25);}
.set-hint-p2{background:rgba(61,142,248,.08);border:1px solid rgba(61,142,248,.2);}
.set-hint-label{font-size:13px;font-weight:700;margin-bottom:4px;}
.set-hint-text{font-size:12px;color:var(--text2);margin-bottom:10px;line-height:1.5;}
.set-hint-codes{display:flex;flex-wrap:wrap;gap:6px;}
.set-hint-chip{padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700;letter-spacing:.3px;}
.set-hint-p1 .set-hint-chip{background:rgba(46,204,113,.18);color:var(--green);}
.set-hint-p2 .set-hint-chip{background:rgba(61,142,248,.18);color:var(--blue);}
.set-okved-list{display:flex;flex-direction:column;gap:8px;margin-top:4px;}
.set-okved-row{display:flex;align-items:center;gap:12px;padding:11px 14px;border-radius:10px;border:1px solid var(--border);background:var(--bg);cursor:pointer;transition:border-color .15s,background .15s;user-select:none;}
.set-okved-row:hover{border-color:var(--blue);}
.set-okved-row.active{border-color:var(--green);background:rgba(46,204,113,.06);}
.set-okved-row.active .set-okved-check{background:var(--green);border-color:var(--green);}
.set-okved-row.active .set-okved-check::after{content:"✓";color:#fff;font-size:11px;font-weight:800;}
.set-okved-check{width:20px;height:20px;border-radius:6px;border:2px solid var(--border2);background:var(--s1);display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:background .15s,border-color .15s;}
.set-okved-code{font-size:13px;font-weight:800;font-variant-numeric:tabular-nums;color:var(--blue);min-width:38px;}
.set-okved-name{font-size:13px;color:var(--text2);flex:1;}
.set-okved-badge{font-size:10px;font-weight:700;padding:2px 7px;border-radius:10px;flex-shrink:0;}
.badge-p1{background:rgba(46,204,113,.15);color:var(--green);}
.badge-p2{background:rgba(61,142,248,.12);color:var(--blue);}
.set-fin-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;}
.set-fin-block{background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:16px;}
.set-fin-label{font-size:13px;font-weight:700;margin-bottom:5px;}
.set-fin-hint{font-size:11px;color:var(--text2);margin-bottom:12px;line-height:1.5;}
.set-fin-row{display:flex;align-items:center;gap:8px;}
.set-input{flex:1;background:var(--s1);border:1px solid var(--border2);border-radius:8px;padding:9px 12px;color:var(--text);font-size:15px;font-weight:700;outline:none;transition:border-color .15s;width:0;}
.set-input:focus{border-color:var(--blue);}
.set-unit{font-size:12px;font-weight:600;color:var(--text2);white-space:nowrap;}
.set-actions{display:flex;align-items:center;flex-wrap:wrap;gap:10px;margin-top:4px;}
/* Полный справочник ОКВЭД */
.set-full-okved-area{margin-top:14px;}
.set-full-toggle{display:flex;align-items:center;gap:7px;background:none;border:1px dashed var(--border);color:var(--text2);border-radius:9px;padding:9px 16px;font-size:13px;cursor:pointer;width:100%;transition:all .18s;}
.set-full-toggle:hover{border-color:var(--blue);color:var(--blue);background:rgba(61,142,248,.06);}
.set-full-toggle svg{transition:transform .25s;}
.set-full-toggle.open svg{transform:rotate(180deg);}
.set-full-panel{display:none;margin-top:12px;border:1px solid var(--border);border-radius:12px;overflow:hidden;}
.set-full-panel.open{display:block;}
.set-full-search{width:100%;box-sizing:border-box;padding:11px 16px;border:none;border-bottom:1px solid var(--border);background:var(--s2);color:var(--text1);font-size:13px;outline:none;}
.set-full-search:focus{background:var(--s1);}
.set-full-list-inner{max-height:380px;overflow-y:auto;}
.set-full-group-header{padding:8px 16px 4px;font-size:11px;font-weight:700;letter-spacing:.5px;color:var(--text2);background:var(--s2);border-bottom:1px solid var(--border);text-transform:uppercase;}
.set-full-row{display:flex;align-items:center;gap:12px;padding:8px 16px;border-bottom:1px solid var(--border);cursor:pointer;transition:background .14s;}
.set-full-row:last-child{border-bottom:none;}
.set-full-row:hover{background:rgba(61,142,248,.07);}
.set-full-row.active{background:rgba(46,204,113,.07);}
.set-full-check{width:18px;height:18px;border-radius:5px;border:2px solid var(--border);flex-shrink:0;display:flex;align-items:center;justify-content:center;transition:all .14s;}
.set-full-row.active .set-full-check{background:var(--green);border-color:var(--green);}
.set-full-code{font-size:12px;font-weight:700;color:var(--blue);min-width:56px;flex-shrink:0;}
.set-full-name{font-size:12px;color:var(--text1);line-height:1.4;}
/* Правило налога на прибыль */
.set-tax-rule{margin-top:20px;padding:18px 20px;background:var(--s2);border:1px solid var(--border);border-radius:12px;}
.set-input-sm{width:58px!important;padding:7px 8px!important;font-size:13px!important;}
.set-tax-modes{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:14px;}
@media(max-width:680px){.set-tax-modes{grid-template-columns:repeat(2,1fr);}}
.set-tax-btn{padding:10px 8px;border:2px solid var(--border);border-radius:9px;background:var(--s1);color:var(--text2);font-size:12px;line-height:1.4;text-align:center;cursor:pointer;transition:all .17s;}
.set-tax-btn small{font-size:10px;opacity:.7;display:block;}
.set-tax-btn:hover{border-color:var(--blue);color:var(--blue);}
.set-tax-btn.active{border-color:var(--green);color:var(--green);background:rgba(46,204,113,.08);font-weight:700;}
.set-tax-params{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--text2);flex-wrap:wrap;margin-top:4px;}
/* Расширенные настройки */
.set-adv-area{margin-top:18px;}
.set-adv-toggle{display:flex;align-items:center;gap:7px;background:none;border:none;color:var(--text2);font-size:13px;cursor:pointer;padding:4px 0;transition:color .16s;}
.set-adv-toggle:hover{color:var(--text1);}
.set-adv-toggle svg{transition:transform .25s;}
.set-adv-toggle.open svg{transform:rotate(180deg);}
.set-adv-panel{display:none;margin-top:14px;padding:16px 18px;background:var(--s2);border:1px solid var(--border);border-radius:12px;}
.set-adv-panel.open{display:block;}
.set-adv-note{font-size:12px;color:var(--text2);margin-bottom:14px;line-height:1.5;}
.btn-back-dash{display:inline-flex;align-items:center;gap:6px;padding:8px 14px;border:1px solid var(--border2);border-radius:8px;background:none;color:var(--text2);font-size:13px;font-weight:600;cursor:pointer;transition:border-color .15s,color .15s;}
.btn-back-dash:hover{border-color:var(--blue);color:var(--blue);}
.btn-back-dash svg{width:13px;height:13px;}
.rpt-title{font-size:18px;font-weight:800;letter-spacing:-.4px;}
.period-row{display:flex;align-items:center;gap:10px;margin-bottom:24px;flex-wrap:wrap;}
.period-tabs{display:flex;gap:4px;background:var(--s1);border:1px solid var(--border);border-radius:9px;padding:3px;}
.period-tab{padding:6px 14px;border-radius:6px;border:none;background:none;color:var(--text2);font-size:13px;font-weight:600;cursor:pointer;transition:background .15s,color .15s;}
.period-tab.active{background:var(--blue);color:#fff;}
.period-tab:not(.active):hover{background:rgba(61,142,248,.1);color:var(--blue);}
.btn-dl{margin-left:auto;display:inline-flex;align-items:center;gap:7px;padding:9px 18px;background:linear-gradient(135deg,var(--green2),var(--green));color:#02100a;border:none;border-radius:8px;font-size:13px;font-weight:800;cursor:pointer;text-decoration:none;box-shadow:0 3px 12px rgba(46,204,113,.25);}
.btn-dl svg{width:14px;height:14px;}
.rpt-section{background:var(--s1);border:1px solid var(--border);border-radius:var(--r);margin-bottom:16px;overflow:hidden;box-shadow:var(--shadow);}
.rpt-section-head{padding:14px 20px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;}
.rpt-section-title{font-size:13px;font-weight:700;}
.rpt-section-sub{font-size:11px;color:var(--text2);}
.rpt-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));}
.rpt-kpi{padding:16px 20px;border-right:1px solid var(--border);}
.rpt-kpi:last-child{border-right:none;}
.rpt-kpi-lbl{font-size:10px;color:var(--text2);text-transform:uppercase;letter-spacing:.7px;margin-bottom:6px;}
.rpt-kpi-val{font-size:24px;font-weight:900;letter-spacing:-1px;line-height:1;}
.rpt-kpi-val.cv-blue{color:var(--blue);}
.rpt-kpi-val.cv-green{color:var(--green);}
.rpt-kpi-val.cv-yellow{color:var(--yellow);}
.rpt-kpi-val.cv-cyan{color:var(--cyan);}
.tbl-wrap{overflow-x:auto;}
table.rpt{width:100%;border-collapse:collapse;font-size:13px;}
table.rpt th{padding:10px 16px;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.8px;color:var(--text2);border-bottom:1px solid var(--border);font-weight:600;white-space:nowrap;}
table.rpt td{padding:10px 16px;border-bottom:1px solid var(--border);}
table.rpt tr:last-child td{border-bottom:none;}
table.rpt tr:hover td{background:rgba(61,142,248,.04);}
table.rpt td.mono{font-family:var(--mono);font-size:12px;}
table.rpt td.num{font-family:var(--mono);font-size:13px;font-weight:700;}
table.rpt td.pct-good{color:var(--green);font-family:var(--mono);font-weight:700;}
table.rpt td.pct-ok{color:var(--yellow);font-family:var(--mono);font-weight:700;}
table.rpt td.pct-low{color:var(--muted);font-family:var(--mono);}
.rpt-empty{padding:28px;text-align:center;color:var(--muted);font-size:13px;}
</style>
</head>
<body>
<header>
  <div class="brand">
    <div class="brand-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg></div>
    <div><div class="brand-name">Lead Finder</div><div class="brand-sub">Brizo CRM · автопоиск лидов</div></div>
  </div>
  <div class="header-right">
    <span class="time-tag" id="clock">—</span>
    <button class="theme-btn" id="theme-btn" onclick="toggleTheme()" title="Сменить тему">
      <svg id="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>
      <svg id="icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="display:none"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
    </button>
    <div class="account-area">
      <span class="account-label">Аккаунт:</span>
      <span class="account-email" id="header-email">…</span>
      <button class="btn-change" onclick="openConfirmModal()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4Z"/></svg>
        Сменить
      </button>
    </div>
    <div class="status-pill stopped" id="status-pill"><div class="status-dot"></div><span id="status-text">Загрузка…</span></div>
  </div>
</header>

<div class="overlay" id="ov-confirm">
  <div class="modal">
    <div class="modal-title">Сменить аккаунт?</div>
    <div class="modal-sub">Сделки будут создаваться от имени другого пользователя Brizo. Текущий аккаунт сохранится в истории.</div>
    <div class="confirm-box"><div class="conf-avatar" id="conf-avatar">?</div><div><div class="conf-email" id="conf-email">—</div><div class="conf-lbl">сейчас активен</div></div></div>
    <div class="conf-actions"><button class="btn-no" onclick="closeAll()">Нет, оставить</button><button class="btn-yes" onclick="openSelectModal()">Да, сменить →</button></div>
  </div>
</div>
<div class="overlay" id="ov-select">
  <div class="modal">
    <div class="modal-title">Выбор аккаунта</div>
    <div class="modal-sub">Выберите из истории или введите данные нового аккаунта.</div>
    <div id="hist-section"><div class="sec-lbl">Ранее использовались</div><div class="hist-list" id="hist-list"><div style="color:var(--muted);font-size:13px">Загрузка…</div></div><hr class="divider"></div>
    <div class="sec-lbl" id="form-lbl">Новый аккаунт</div>
    <div class="field"><label>Email</label><input type="email" id="s-email" placeholder="you@example.com" autocomplete="username"></div>
    <div class="field"><label>Пароль</label><input type="password" id="s-pwd" placeholder="••••••••" autocomplete="current-password"></div>
    <div class="m-actions"><button class="btn-back" onclick="backToConfirm()">← Назад</button><button class="btn-save" id="btn-save" onclick="saveAccount()">Подключить аккаунт</button></div>
    <div class="m-msg" id="s-msg"></div>
  </div>
</div>

<main>
<div class="view active" id="view-dash">
  <div class="controls">
    <button class="btn btn-start" id="btn-start" onclick="doStart()"><svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>Запустить</button>
    <button class="btn btn-stop" id="btn-stop" onclick="doStop()"><svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>Остановить</button>
    <span class="toast" id="toast"></span>
    <button class="btn-report" onclick="showView('report')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
      Отчётность
    </button>
    <button class="btn-report" onclick="showView('settings')" style="margin-left:6px">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
      Настройки
    </button>
  </div>
  <div class="kpi-row">
    <div class="kpi-card kc-blue"><div class="kpi-label">Проверено компаний</div><div class="kpi-value cv-blue" id="kpi-checked">—</div><div class="kpi-sub">с начала запуска</div></div>
    <div class="kpi-card kc-green"><div class="kpi-label">Добавлено в Brizo</div><div class="kpi-value cv-green" id="kpi-created">—</div><div class="kpi-sub">лидов создано</div></div>
    <div class="kpi-card kc-yellow"><div class="kpi-label">Конверсия</div><div class="kpi-value cv-yellow" id="kpi-conv">—</div><div class="kpi-sub">прошло квалификацию</div></div>
    <div class="kpi-card kc-cyan"><div class="kpi-label">Отклонено / дублей</div><div class="kpi-value cv-cyan" id="kpi-rejected">—</div><div class="kpi-sub" id="kpi-rej-sub">компаний</div></div>
  </div>
  <div class="progress-card">
    <div class="progress-head"><span class="progress-title">Прогресс к суточной цели</span><span class="progress-frac"><span id="pg-n">0</span><span> / <span id="pg-t">200</span> сделок</span></span></div>
    <div class="progress-bg"><div class="progress-fill" id="pg-fill" style="width:0%"></div></div>
    <div id="pg-sub" class="progress-sub">Загрузка…</div>
  </div>
  <div class="charts-grid">
    <div class="chart-card">
      <div class="chart-title">Статистика по ОКВЭДам</div>
      <div class="chart-sub">Компаний проверено · конверсия в целевые лиды</div>
      <div class="okved-bars" id="okved-bars"><div class="okved-empty">Данные накапливаются…</div></div>
      <div class="chart-legend"><div class="cleg-item"><div class="cleg-dot" style="background:rgba(61,142,248,.4)"></div>Проверено</div><div class="cleg-item"><div class="cleg-dot" style="background:rgba(46,204,113,.55)"></div>Создано</div></div>
    </div>
    <div class="chart-card">
      <div class="chart-title">Причины отсева</div>
      <div class="chart-sub">Почему компании не становятся лидами</div>
      <div class="donut-wrap">
        <div class="donut-container" style="width:130px;height:130px;">
          <svg id="rej-donut" viewBox="0 0 130 130" width="130" height="130" style="filter:drop-shadow(0 0 10px rgba(61,142,248,.12))"></svg>
          <div class="donut-center"><div class="donut-main" id="rej-total" style="color:var(--text2)">0</div><div class="donut-lbl">отсеяно</div></div>
        </div>
        <div class="legend-list" id="rej-legend"><div style="color:var(--muted);font-size:12px">Данные накапливаются…</div></div>
      </div>
    </div>
  </div>
  <div id="set-toast" style="display:none;position:fixed;bottom:24px;right:24px;background:var(--green);color:#fff;padding:10px 18px;border-radius:8px;font-size:13px;font-weight:600;z-index:9999"></div>
<button class="log-toggle-btn" onclick="toggleLog()"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 8h10M7 12h8M7 16h5"/></svg><span id="log-btn-txt">Показать лог воркера</span></button>
  <div class="log-panel" id="log-panel">
    <div class="log-header"><span class="log-title">Лог воркера</span><button class="log-close" onclick="toggleLog()">✕</button></div>
    <div class="log-body" id="log-body"></div>
  </div>
</div>

<div class="view" id="view-report">
  <div class="rpt-header">
    <button class="btn-back-dash" onclick="showView('dash')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>Дашборд</button>
    <div class="rpt-title">Отчётность</div>
  </div>
  <div class="period-row">
    <div class="period-tabs">
      <button class="period-tab active" data-p="all" onclick="setPeriod(this)">Всё время</button>
      <button class="period-tab" data-p="30d" onclick="setPeriod(this)">30 дней</button>
      <button class="period-tab" data-p="7d" onclick="setPeriod(this)">7 дней</button>
      <button class="period-tab" data-p="24h" onclick="setPeriod(this)">24 часа</button>
    </div>
    <a class="btn-dl" id="dl-btn" href="/api/report/download?period=all" download>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
      Скачать Excel
    </a>
  </div>
  <div class="rpt-section">
    <div class="rpt-section-head"><div class="rpt-section-title">Сводка</div><div class="rpt-section-sub" id="rpt-gen-at">Загрузка…</div></div>
    <div class="rpt-kpis">
      <div class="rpt-kpi"><div class="rpt-kpi-lbl">Проверено</div><div class="rpt-kpi-val cv-blue" id="rpt-checked">—</div></div>
      <div class="rpt-kpi"><div class="rpt-kpi-lbl">Создано в Brizo</div><div class="rpt-kpi-val cv-green" id="rpt-created">—</div></div>
      <div class="rpt-kpi"><div class="rpt-kpi-lbl">Конверсия</div><div class="rpt-kpi-val cv-yellow" id="rpt-conv">—</div></div>
      <div class="rpt-kpi"><div class="rpt-kpi-lbl">Дублей</div><div class="rpt-kpi-val cv-cyan" id="rpt-dup">—</div></div>
      <div class="rpt-kpi"><div class="rpt-kpi-lbl">Отклонено</div><div class="rpt-kpi-val" id="rpt-rej" style="color:var(--text2)">—</div></div>
    </div>
  </div>
  <div class="rpt-section">
    <div class="rpt-section-head"><div class="rpt-section-title">Статистика по ОКВЭДам</div><div class="rpt-section-sub">Конверсия выше → ОКВЭД приоритетнее</div></div>
    <div class="tbl-wrap"><table class="rpt"><thead><tr><th>ОКВЭД</th><th>Проверено</th><th>Создано</th><th>Дублей</th><th>Отклонено</th><th>Конверсия</th></tr></thead><tbody id="rpt-okved-body"><tr><td colspan="6" class="rpt-empty">Загрузка…</td></tr></tbody></table></div>
  </div>
  <div class="rpt-section">
    <div class="rpt-section-head"><div class="rpt-section-title">Причины отсева</div><div class="rpt-section-sub">Почему компании не стали лидами</div></div>
    <div class="tbl-wrap"><table class="rpt"><thead><tr><th>Причина</th><th>Компаний</th><th>Доля</th></tr></thead><tbody id="rpt-rej-body"><tr><td colspan="3" class="rpt-empty">Загрузка…</td></tr></tbody></table></div>
  </div>
</div>

<div class="view" id="view-settings">
  <div class="rpt-header">
    <button class="btn-back-dash" onclick="showView('dash')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>Дашборд</button>
    <div class="rpt-title">Настройки парсера</div>
  </div>

  <div class="set-section">
    <div class="set-section-title">ОКВЭДы для поиска</div>

    <div class="set-hint set-hint-p1">
      <div class="set-hint-label">⭐ Приоритет 1 — точные резиденты Сколково</div>
      <div class="set-hint-text">Производственные и R&amp;D компании — наиболее вероятные резиденты. Рекомендуется держать включёнными всегда.</div>
      <div class="set-hint-codes" id="hint-p1-codes"></div>
    </div>

    <div class="set-hint set-hint-p2">
      <div class="set-hint-label">🔎 Приоритет 2 — потенциальные резиденты</div>
      <div class="set-hint-text">ИТ-компании и смежные отрасли. Конверсия ниже, но объём компаний значительно больше.</div>
      <div class="set-hint-codes" id="hint-p2-codes"></div>
    </div>

    <div class="set-okved-list" id="set-okved-list"></div>

    <!-- Кнопка раскрытия полного справочника -->
    <div class="set-full-okved-area">
      <button class="set-full-toggle" id="full-okved-btn" onclick="toggleFullOkved()">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
        Добавить из полного справочника ОКВЭД
      </button>
      <div class="set-full-panel" id="set-full-panel">
        <input class="set-full-search" type="text" id="full-okved-search"
               placeholder="Поиск по коду или названию..." oninput="filterFullOkved()">
        <div id="set-full-list"></div>
      </div>
    </div>
  </div>

  <div class="set-section">
    <div class="set-section-title">Финансовые критерии отбора</div>
    <div class="set-fin-grid">
      <div class="set-fin-block">
        <div class="set-fin-label">Выручка — до</div>
        <div class="set-fin-hint">Компании с выручкой выше отклоняются как слишком крупные</div>
        <div class="set-fin-row">
          <input class="set-input" type="number" id="fin-rev-max" min="0.1" max="100" step="0.1" value="1">
          <span class="set-unit">млрд ₽</span>
        </div>
      </div>
      <div class="set-fin-block">
        <div class="set-fin-label">Выручка — от</div>
        <div class="set-fin-hint">Компании с выручкой ниже пропускаются (0 = без порога)</div>
        <div class="set-fin-row">
          <input class="set-input" type="number" id="fin-rev-min" min="0" max="10000" step="1" value="0">
          <span class="set-unit">млн ₽</span>
        </div>
      </div>
    </div>

    <!-- Блок правила налога на прибыль -->
    <div class="set-tax-rule">
      <div class="set-fin-label" style="margin-bottom:10px">Налог на прибыль — условие отбора</div>
      <div class="set-fin-row" style="margin-bottom:14px;gap:10px;align-items:center">
        <span style="font-size:13px;color:var(--text2);white-space:nowrap">Минимум</span>
        <input class="set-input set-input-sm" type="number" id="fin-tax-min" min="0.1" max="1000" step="0.1" value="5">
        <span class="set-unit">млн ₽</span>
      </div>
      <div class="set-tax-modes" id="tax-modes">
        <button class="set-tax-btn active" data-mode="any"    onclick="setTaxMode('any',this)">Хотя бы раз<br><small>за N лет</small></button>
        <button class="set-tax-btn"        data-mode="last"   onclick="setTaxMode('last',this)">Только<br><small>последний год</small></button>
        <button class="set-tax-btn"        data-mode="all"    onclick="setTaxMode('all',this)">Все N лет<br><small>подряд</small></button>
        <button class="set-tax-btn"        data-mode="k_of_n" onclick="setTaxMode('k_of_n',this)">Минимум K<br><small>из N лет</small></button>
      </div>
      <div class="set-tax-params" id="tax-params-years">
        <span>за последние</span>
        <input class="set-input set-input-sm" type="number" id="fin-tax-years" min="1" max="5" value="3">
        <span>лет</span>
      </div>
      <div class="set-tax-params" id="tax-params-k" style="display:none">
        <span>минимум</span>
        <input class="set-input set-input-sm" type="number" id="fin-tax-k" min="1" max="5" value="1">
        <span>из последних</span>
        <input class="set-input set-input-sm" type="number" id="fin-tax-k-n" min="1" max="5" value="3">
        <span>лет</span>
      </div>
    </div>

    <!-- Расширенные настройки -->
    <div class="set-adv-area">
      <button class="set-adv-toggle" id="adv-fin-btn" onclick="toggleAdvFinance()">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
        Расширенные финансовые критерии
      </button>
      <div class="set-adv-panel" id="set-adv-panel">
        <div class="set-adv-note">
          Применяются если данные доступны в Checko. Значение <strong>0</strong> = не проверять.
        </div>
        <div class="set-fin-grid">
          <div class="set-fin-block">
            <div class="set-fin-label">Транспортный налог — от</div>
            <div class="set-fin-row">
              <input class="set-input" type="number" id="fin-transport-min" min="0" step="0.1" value="0">
              <span class="set-unit">млн ₽</span>
            </div>
          </div>
          <div class="set-fin-block">
            <div class="set-fin-label">Налог на имущество — от</div>
            <div class="set-fin-row">
              <input class="set-input" type="number" id="fin-property-min" min="0" step="0.1" value="0">
              <span class="set-unit">млн ₽</span>
            </div>
          </div>
          <div class="set-fin-block">
            <div class="set-fin-label">Страховые взносы — от</div>
            <div class="set-fin-row">
              <input class="set-input" type="number" id="fin-insurance-min" min="0" step="1" value="0">
              <span class="set-unit">млн ₽</span>
            </div>
          </div>
          <div class="set-fin-block">
            <div class="set-fin-label">НДС (входящий) — от</div>
            <div class="set-fin-row">
              <input class="set-input" type="number" id="fin-vat-min" min="0" step="1" value="0">
              <span class="set-unit">млн ₽</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div class="set-actions">
    <button class="btn btn-start" onclick="saveSettings()">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
      Сохранить настройки
    </button>
    <button class="btn btn-stop" onclick="saveAndRestart()" style="margin-left:8px">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>
      Сохранить и перезапустить воркер
    </button>
  </div>
</div>

</main>

<script>
let curEmail='',logOpen=false,selHistEmail=null,curPeriod='all';
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function ini(e){return(e||'').split('@')[0].slice(0,2).toUpperCase()||'?';}
function pct(v,t){return t>0?Math.round(v/t*100)+'%':'0%';}
function numFmt(n){return n>=1000?(n/1000).toFixed(1).replace(/\.0$/,'')+'k':String(n);}
function showToast(m,ms=3000){const t=document.getElementById('toast');t.textContent=m;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),ms);}
function colorLine(l){const e=esc(l);if(l.includes('Сделка #'))return'<span class="lo">'+e+'</span>';if(l.includes('429')||l.includes('❌'))return'<span class="le">'+e+'</span>';if(l.includes('WARNING')||l.includes('⚠'))return'<span class="lw">'+e+'</span>';return e;}
function toggleTheme(){const h=document.documentElement,isL=h.getAttribute('data-theme')==='light',n=isL?'dark':'light';h.setAttribute('data-theme',n);localStorage.setItem('lf-theme',n);updateThemeIcons(n);}
function updateThemeIcons(t){document.getElementById('icon-sun').style.display=t==='dark'?'block':'none';document.getElementById('icon-moon').style.display=t==='light'?'block':'none';}
updateThemeIcons(document.documentElement.getAttribute('data-theme')||'dark');
function showView(id){document.querySelectorAll('.view').forEach(v=>v.classList.remove('active'));document.getElementById('view-'+id).classList.add('active');if(id==='report')loadReport();if(id==='settings')loadSettings();}

// ── Настройки ──────────────────────────────────────────────────────────────
let _catalog=[], _fullCatalog=[], _sectionNames={}, _activeCodes=new Set();
let _curTaxMode='any';

async function loadSettings(){
  try{
    const d=await fetch('/api/settings').then(r=>r.json());
    _catalog=d.catalog||[];
    _fullCatalog=d.full_catalog||[];
    _sectionNames=d.section_names||{};
    const s=d.settings||{};
    _activeCodes=new Set(s.okved_codes||[]);

    // Памятки с кодами
    const p1=_catalog.filter(o=>o.priority===1), p2=_catalog.filter(o=>o.priority===2);
    document.getElementById('hint-p1-codes').innerHTML=p1.map(o=>'<span class="set-hint-chip">'+esc(o.code)+'</span>').join('');
    document.getElementById('hint-p2-codes').innerHTML=p2.map(o=>'<span class="set-hint-chip">'+esc(o.code)+'</span>').join('');

    // Список приоритетных чекбоксов
    document.getElementById('set-okved-list').innerHTML=_catalog.map(o=>{
      const active=_activeCodes.has(o.code);
      const badge=o.priority===1?'<span class="set-okved-badge badge-p1">⭐ Приоритет 1</span>':'<span class="set-okved-badge badge-p2">🔎 Приоритет 2</span>';
      return'<div class="set-okved-row'+(active?' active':'')+'" onclick="toggleOkved(\''+esc(o.code)+'\',this)">'
        +'<div class="set-okved-check">'+(active?'<span style="color:#fff;font-size:11px;font-weight:800">✓</span>':'')+'</div>'
        +'<div class="set-okved-code">'+esc(o.code)+'</div>'
        +'<div class="set-okved-name">'+esc(o.name)+'</div>'
        +badge+'</div>';
    }).join('');

    // Финансовые пороги
    document.getElementById('fin-rev-max').value=((s.revenue_max||1e9)/1e9).toFixed(1);
    document.getElementById('fin-rev-min').value=Math.round((s.revenue_min||0)/1e6);

    // Правило налога на прибыль
    const rule=s.income_tax_rule||{mode:'any',years:3,min_amount:5e6,k:1};
    document.getElementById('fin-tax-min').value=(rule.min_amount/1e6).toFixed(1);
    document.getElementById('fin-tax-years').value=rule.years||3;
    document.getElementById('fin-tax-k').value=rule.k||1;
    document.getElementById('fin-tax-k-n').value=rule.years||3;
    _applyTaxMode(rule.mode||'any');

    // Расширенные финансы
    const af=s.advanced_finance||{};
    document.getElementById('fin-transport-min').value=((af.transport_tax_min||0)/1e6).toFixed(1);
    document.getElementById('fin-property-min').value=((af.property_tax_min||0)/1e6).toFixed(1);
    document.getElementById('fin-insurance-min').value=Math.round((af.insurance_min||0)/1e6);
    document.getElementById('fin-vat-min').value=Math.round((af.vat_min||0)/1e6);

    // Построить полный список (скрытый)
    _buildFullOkvedList();
  }catch(e){console.error('loadSettings',e);}
}

// ── Переключение приоритетных ОКВЭДов ────────────────────────────────────
function toggleOkved(code,el){
  if(_activeCodes.has(code)){
    _activeCodes.delete(code);el.classList.remove('active');
    el.querySelector('.set-okved-check').innerHTML='';
  } else {
    _activeCodes.add(code);el.classList.add('active');
    el.querySelector('.set-okved-check').innerHTML='<span style="color:#fff;font-size:11px;font-weight:800">✓</span>';
  }
  // Обновить строку в полном списке если открыт
  const fr=document.querySelector('.set-full-row[data-code="'+esc(code)+'"]');
  if(fr)_syncFullRow(fr,code);
}

// ── Полный справочник ОКВЭД ───────────────────────────────────────────────
function _buildFullOkvedList(filter=''){
  const q=filter.trim().toLowerCase();
  const container=document.getElementById('set-full-list');
  const sections={};
  _fullCatalog.forEach(o=>{
    if(q && !o.code.toLowerCase().includes(q) && !o.name.toLowerCase().includes(q)) return;
    if(!sections[o.section]) sections[o.section]=[];
    sections[o.section].push(o);
  });
  if(!Object.keys(sections).length){
    container.innerHTML='<div class="set-full-list-inner" style="padding:16px;text-align:center;color:var(--text2);font-size:13px">Ничего не найдено</div>';
    return;
  }
  let html='<div class="set-full-list-inner">';
  Object.keys(sections).sort().forEach(sec=>{
    html+='<div class="set-full-group-header">'+esc(_sectionNames[sec]||sec)+'</div>';
    sections[sec].forEach(o=>{
      const active=_activeCodes.has(o.code);
      html+='<div class="set-full-row'+(active?' active':'')+'" data-code="'+esc(o.code)+'" onclick="toggleFullOkved_item(\''+esc(o.code)+'\',this)">'
        +'<div class="set-full-check">'+(active?'<span style="color:#fff;font-size:10px;font-weight:800">✓</span>':'')+'</div>'
        +'<div class="set-full-code">'+esc(o.code)+'</div>'
        +'<div class="set-full-name">'+esc(o.name)+'</div>'
        +'</div>';
    });
  });
  html+='</div>';
  container.innerHTML=html;
}

function _syncFullRow(el,code){
  const active=_activeCodes.has(code);
  el.classList.toggle('active',active);
  el.querySelector('.set-full-check').innerHTML=active?'<span style="color:#fff;font-size:10px;font-weight:800">✓</span>':'';
}

function toggleFullOkved_item(code,el){
  if(_activeCodes.has(code)) _activeCodes.delete(code);
  else _activeCodes.add(code);
  _syncFullRow(el,code);
  // Обновить строку в приоритетном списке если там есть
  const pr=document.querySelector('.set-okved-row');
  if(pr){
    document.querySelectorAll('.set-okved-row').forEach(row=>{
      const rc=row.querySelector('.set-okved-code');
      if(rc && rc.textContent===code){
        const active=_activeCodes.has(code);
        row.classList.toggle('active',active);
        row.querySelector('.set-okved-check').innerHTML=active?'<span style="color:#fff;font-size:11px;font-weight:800">✓</span>':'';
      }
    });
  }
}

function toggleFullOkved(){
  const panel=document.getElementById('set-full-panel');
  const btn=document.getElementById('full-okved-btn');
  const isOpen=panel.classList.toggle('open');
  btn.classList.toggle('open',isOpen);
  if(isOpen) _buildFullOkvedList();
}

function filterFullOkved(){
  _buildFullOkvedList(document.getElementById('full-okved-search').value);
}

// ── Режим налога на прибыль ───────────────────────────────────────────────
function _applyTaxMode(mode){
  _curTaxMode=mode;
  document.querySelectorAll('.set-tax-btn').forEach(b=>{
    b.classList.toggle('active',b.dataset.mode===mode);
  });
  const showYears=mode==='any'||mode==='all';
  const showK=mode==='k_of_n';
  document.getElementById('tax-params-years').style.display=showYears?'flex':'none';
  document.getElementById('tax-params-k').style.display=showK?'flex':'none';
}

function setTaxMode(mode,el){_applyTaxMode(mode);}

// ── Расширенные настройки ─────────────────────────────────────────────────
function toggleAdvFinance(){
  const panel=document.getElementById('set-adv-panel');
  const btn=document.getElementById('adv-fin-btn');
  const isOpen=panel.classList.toggle('open');
  btn.classList.toggle('open',isOpen);
}

// ── Тост ──────────────────────────────────────────────────────────────────
function showSetToast(msg,isErr){
  const t=document.getElementById('set-toast');
  t.textContent=msg;t.style.background=isErr?'#e74c3c':'var(--green)';t.style.display='block';
  setTimeout(()=>{t.style.display='none';},3500);
}

// ── Сохранение / перезапуск ───────────────────────────────────────────────
async function saveSettings(){
  const codes=[..._activeCodes];
  if(!codes.length){showSetToast('Выберите хотя бы один ОКВЭД',true);return;}

  const taxYears=parseInt(document.getElementById('fin-tax-years').value)||3;
  const taxK=parseInt(document.getElementById('fin-tax-k').value)||1;
  const taxKN=parseInt(document.getElementById('fin-tax-k-n').value)||3;

  const payload={
    okved_codes: codes,
    revenue_max: Math.round(parseFloat(document.getElementById('fin-rev-max').value||1)*1e9),
    revenue_min: Math.round(parseFloat(document.getElementById('fin-rev-min').value||0)*1e6),
    income_tax_rule: {
      mode:       _curTaxMode,
      years:      _curTaxMode==='k_of_n'?taxKN:taxYears,
      min_amount: Math.round(parseFloat(document.getElementById('fin-tax-min').value||5)*1e6),
      k:          taxK,
    },
    advanced_finance: {
      transport_tax_min: Math.round(parseFloat(document.getElementById('fin-transport-min').value||0)*1e6),
      property_tax_min:  Math.round(parseFloat(document.getElementById('fin-property-min').value||0)*1e6),
      insurance_min:     Math.round(parseFloat(document.getElementById('fin-insurance-min').value||0)*1e6),
      vat_min:           Math.round(parseFloat(document.getElementById('fin-vat-min').value||0)*1e6),
    },
  };
  try{
    const r=await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const d=await r.json();
    if(d.ok) showSetToast('✓ Настройки сохранены');
    else showSetToast('Ошибка: '+(d.error||'?'),true);
  }catch(e){showSetToast('Ошибка сохранения',true);}
}

async function saveAndRestart(){
  await saveSettings();
  try{
    const r=await fetch('/api/restart',{method:'POST'});
    const d=await r.json();
    showSetToast(d.msg||'Воркер перезапущен');
    setTimeout(()=>showView('dash'),2000);
  }catch(e){showSetToast('Ошибка перезапуска',true);}
}
const RC=['#3d8ef8','#e74c5a','#f39c12','#9b59b6','#1abc9c','#e67e22'];
function drawDonut(svgId,segs,cx,cy,R,r){const svg=document.getElementById(svgId);const total=segs.reduce((s,x)=>s+x.v,0);if(!total){svg.innerHTML='<circle cx="'+cx+'" cy="'+cy+'" r="'+((R+r)/2)+'" fill="none" stroke="#1c2a40" stroke-width="'+(R-r)+'"/>';return;}let a=-Math.PI/2,paths='',gap=0.03;for(const s of segs){if(s.v<=0)continue;const sl=s.v/total*Math.PI*2-gap;if(sl<=0)continue;const ea=a+sl,lg=sl>Math.PI?1:0;const px=(ag,rd)=>[cx+rd*Math.cos(ag),cy+rd*Math.sin(ag)];const[x1,y1]=px(a,R),[x2,y2]=px(ea,R),[ix1,iy1]=px(a,r),[ix2,iy2]=px(ea,r);paths+='<path d="M'+x1+','+y1+'A'+R+','+R+' 0 '+lg+' 1 '+x2+','+y2+'L'+ix2+','+iy2+'A'+r+','+r+' 0 '+lg+' 0 '+ix1+','+iy1+'Z" fill="'+s.c+'"/>';a+=sl+gap;}svg.innerHTML=paths;}
async function loadStatus(){try{const d=await fetch('/api/status').then(r=>r.json());document.getElementById('clock').textContent=d.time;curEmail=d.account_email||'—';document.getElementById('header-email').textContent=curEmail;const p=document.getElementById('status-pill');p.className='status-pill '+(d.running?'running':'stopped');document.getElementById('status-text').textContent=d.running?'Работает · '+d.process_count+' проц.':'Остановлено';}catch(e){document.getElementById('status-text').textContent='Нет связи';}}
async function loadAnalytics(){try{const d=await fetch('/api/analytics').then(r=>r.json());const s=d.stats||{};const checked=s.checked||0,created=s.created||0,dup=s.duplicate||0,rej=s.rejected||0,conv=s.conversion||0,tg=d.daily_target||200;document.getElementById('kpi-checked').textContent=numFmt(checked);document.getElementById('kpi-created').textContent=numFmt(created);document.getElementById('kpi-conv').textContent=conv>0?conv+'%':'0%';document.getElementById('kpi-rejected').textContent=numFmt(rej+dup);document.getElementById('kpi-rej-sub').textContent=dup+' дублей · '+rej+' не прошли';const fp=Math.min(created/tg*100,100);document.getElementById('pg-fill').style.width=fp+'%';document.getElementById('pg-n').textContent=created;document.getElementById('pg-t').textContent=tg;const rem=Math.max(0,tg-created);const sub=document.getElementById('pg-sub');if(rem>0){sub.className='progress-sub';sub.textContent='Осталось: '+rem+' сделок ('+Math.round(fp)+'% выполнено)';}else{sub.className='progress-done';sub.textContent='🎉 Цель на сегодня выполнена!';}const od=d.okved_data||{},bars=document.getElementById('okved-bars');const entries=Object.entries(od).sort((a,b)=>b[1].companies-a[1].companies);if(!entries.length){bars.innerHTML='<div class="okved-empty">Данные накапливаются…</div>';}else{const maxC=Math.max(...entries.map(e=>e[1].companies),1);bars.innerHTML=entries.slice(0,8).map(([code,x])=>{const bgW=Math.round(x.companies/maxC*100);const crW=x.companies>0?Math.round(x.created/x.companies*100):0;const cc=x.conversion>=10?'good':x.conversion>=3?'ok':'low';return'<div class="okved-row"><div class="okved-code">'+esc(code)+'</div><div class="okved-bar-wrap"><div class="okved-bar-bg" style="width:'+bgW+'%"></div><div class="okved-bar-cr" style="width:'+crW+'%"></div></div><div class="okved-count">'+x.companies+'</div><div class="okved-conv '+cc+'">'+(x.companies?x.conversion+'%':'—')+'</div></div>';}).join('');}const rr=d.rejection_reasons||{},re=Object.entries(rr).sort((a,b)=>b[1]-a[1]);const rt=re.reduce((s,e)=>s+e[1],0);document.getElementById('rej-total').textContent=numFmt(rt);drawDonut('rej-donut',re.map(([n,v],i)=>({v,c:RC[i%RC.length]})),65,65,57,38);const leg=document.getElementById('rej-legend');if(!re.length){leg.innerHTML='<div style="color:var(--muted);font-size:12px">Данные накапливаются…</div>';}else{leg.innerHTML=re.map(([n,v],i)=>'<div class="legend-row"><div class="leg-dot" style="background:'+RC[i%RC.length]+'"></div><div class="leg-name" title="'+esc(n)+'">'+esc(n)+'</div><span class="leg-val">'+v+'</span><span class="leg-pct">'+pct(v,rt)+'</span></div>').join('');}if(logOpen)loadLog();}catch(e){console.error(e);}}
function setPeriod(btn){document.querySelectorAll('.period-tab').forEach(b=>b.classList.remove('active'));btn.classList.add('active');curPeriod=btn.dataset.p;document.getElementById('dl-btn').href='/api/report/download?period='+curPeriod;loadReport();}
async function loadReport(){try{const d=await fetch('/api/report?period='+curPeriod).then(r=>r.json());const s=d.stats||{};document.getElementById('rpt-gen-at').textContent='Сформирован: '+(d.generated_at||'—');document.getElementById('rpt-checked').textContent=numFmt(s.checked||0);document.getElementById('rpt-created').textContent=numFmt(s.created||0);document.getElementById('rpt-conv').textContent=(s.conversion||0)+'%';document.getElementById('rpt-dup').textContent=numFmt(s.duplicate||0);document.getElementById('rpt-rej').textContent=numFmt(s.rejected||0);const od=d.okved_data||{};const rows=Object.entries(od).sort((a,b)=>b[1].companies-a[1].companies);const ob=document.getElementById('rpt-okved-body');if(!rows.length){ob.innerHTML='<tr><td colspan="6" class="rpt-empty">Нет данных</td></tr>';}else{ob.innerHTML=rows.map(([code,x])=>{const cc=x.conversion>=10?'pct-good':x.conversion>=3?'pct-ok':'pct-low';return'<tr><td class="mono">'+esc(code)+'</td><td class="num">'+x.companies+'</td><td class="num" style="color:var(--green)">'+x.created+'</td><td class="num" style="color:var(--cyan)">'+x.duplicate+'</td><td class="num" style="color:var(--text2)">'+x.rejected+'</td><td class="'+cc+'">'+(x.companies?x.conversion+'%':'—')+'</td></tr>';}).join('');}const rr=d.rejection_reasons||{},rrows=Object.entries(rr).sort((a,b)=>b[1]-a[1]);const rtotal=rrows.reduce((s,e)=>s+e[1],0);const rb=document.getElementById('rpt-rej-body');if(!rrows.length){rb.innerHTML='<tr><td colspan="3" class="rpt-empty">Нет данных</td></tr>';}else{rb.innerHTML=rrows.map(([n,v])=>'<tr><td>'+esc(n)+'</td><td class="num">'+v+'</td><td class="mono" style="color:var(--muted)">'+pct(v,rtotal)+'</td></tr>').join('');}}catch(e){console.error(e);}}
async function doStart(){document.getElementById('btn-start').disabled=true;showToast('Запускаем…');const d=await fetch('/api/start',{method:'POST'}).then(r=>r.json());showToast(d.msg);setTimeout(loadStatus,2000);setTimeout(loadAnalytics,3000);setTimeout(()=>document.getElementById('btn-start').disabled=false,4000);}
async function doStop(){document.getElementById('btn-stop').disabled=true;showToast('Останавливаем…');const d=await fetch('/api/stop',{method:'POST'}).then(r=>r.json());showToast(d.msg);setTimeout(loadStatus,1500);setTimeout(()=>document.getElementById('btn-stop').disabled=false,3000);}
async function loadLog(){const d=await fetch('/api/logs').then(r=>r.json());const b=document.getElementById('log-body');b.innerHTML=d.lines.map(colorLine).join('\n');b.scrollTop=b.scrollHeight;}
async function toggleLog(){logOpen=!logOpen;document.getElementById('log-panel').classList.toggle('open',logOpen);document.getElementById('log-btn-txt').textContent=logOpen?'Скрыть лог':'Показать лог воркера';if(logOpen)await loadLog();}
function closeAll(){document.getElementById('ov-confirm').classList.remove('open');document.getElementById('ov-select').classList.remove('open');selHistEmail=null;}
document.querySelectorAll('.overlay').forEach(o=>o.addEventListener('click',e=>{if(e.target===o)closeAll();}));
function openConfirmModal(){document.getElementById('conf-avatar').textContent=ini(curEmail);document.getElementById('conf-email').textContent=curEmail;document.getElementById('ov-confirm').classList.add('open');}
async function openSelectModal(){document.getElementById('ov-confirm').classList.remove('open');document.getElementById('ov-select').classList.add('open');document.getElementById('s-email').value='';document.getElementById('s-pwd').value='';document.getElementById('s-msg').className='m-msg';document.getElementById('form-lbl').textContent='Новый аккаунт';selHistEmail=null;try{const d=await fetch('/api/account').then(r=>r.json());renderHist(d.history||[],d.current);}catch(e){}setTimeout(()=>document.getElementById('s-email').focus(),100);}
function renderHist(hist,cur){const sec=document.getElementById('hist-section');const others=hist.filter(h=>h.email!==cur);if(!others.length){sec.style.display='none';return;}sec.style.display='block';document.getElementById('hist-list').innerHTML=others.map(h=>'<div class="hist-item" id="hi-'+CSS.escape(h.email)+'" onclick="selHist(\''+h.email.replace(/\'/g,"\\'")+'\')"><div class="hist-av">'+ini(h.email)+'</div><div><div class="hist-email">'+esc(h.email)+'</div><div class="hist-date">'+esc(h.added)+'</div></div></div>').join('');}
function selHist(email){selHistEmail=email;document.querySelectorAll('.hist-item').forEach(el=>el.classList.toggle('sel',el.id==='hi-'+CSS.escape(email)));document.getElementById('s-email').value=email;document.getElementById('form-lbl').textContent='Подтвердите паролем';document.getElementById('s-pwd').value='';document.getElementById('s-pwd').focus();}
function backToConfirm(){document.getElementById('ov-select').classList.remove('open');openConfirmModal();}
document.getElementById('s-pwd').addEventListener('keydown',e=>{if(e.key==='Enter')saveAccount();});
async function saveAccount(){const email=document.getElementById('s-email').value.trim();const pwd=document.getElementById('s-pwd').value.trim();const btn=document.getElementById('btn-save');const msg=document.getElementById('s-msg');if(!email||!pwd){msg.className='m-msg err';msg.textContent='Заполните email и пароль';return;}btn.disabled=true;btn.textContent='Проверяем…';msg.className='m-msg';try{const d=await fetch('/api/account',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,password:pwd})}).then(r=>r.json());if(d.ok){msg.className='m-msg ok';msg.textContent='✅ '+d.msg;document.getElementById('header-email').textContent=d.email;curEmail=d.email;setTimeout(closeAll,1600);setTimeout(loadStatus,1800);}else{msg.className='m-msg err';msg.textContent='❌ '+d.msg;}}catch(e){msg.className='m-msg err';msg.textContent='❌ Ошибка соединения';}btn.disabled=false;btn.textContent='Подключить аккаунт';}
loadStatus();loadAnalytics();setInterval(loadStatus,10000);setInterval(loadAnalytics,15000);
</script>
</body>
</html>"""


@app.route("/api/report")
def api_report():
    data = parse_log_analytics("w1")
    data["daily_target"] = DAILY_TARGET
    data["generated_at"] = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    return jsonify(data)


@app.route("/api/report/download")
def api_report_download():
    period = request.args.get("period", "all")
    data = parse_log_analytics("w1")
    stats = data.get("stats", {})
    okved_data = data.get("okved_data", {})
    rej_reasons = data.get("rejection_reasons", {})

    period_labels = {
        "24h": "Последние 24 часа",
        "7d":  "Последние 7 дней",
        "30d": "Последние 30 дней",
        "all": "Весь период работы",
    }

    out = io.StringIO()
    w = csv.writer(out)

    w.writerow(["ОТЧЁТ LEAD FINDER"])
    w.writerow(["Дата формирования", datetime.now().strftime("%d.%m.%Y %H:%M")])
    w.writerow(["Период", period_labels.get(period, "Весь период")])
    w.writerow([])

    w.writerow(["СВОДКА"])
    w.writerow(["Проверено компаний", stats.get("checked", 0)])
    w.writerow(["Добавлено в Brizo", stats.get("created", 0)])
    w.writerow(["Дублей в базе", stats.get("duplicate", 0)])
    w.writerow(["Отклонено", stats.get("rejected", 0)])
    w.writerow(["Ошибок / прокси", stats.get("error", 0)])
    w.writerow(["Конверсия, %", stats.get("conversion", 0)])
    w.writerow([])

    w.writerow(["СТАТИСТИКА ПО ОКВЭД"])
    w.writerow(["ОКВЭД", "Проверено", "Создано", "Дублей", "Отклонено", "Конверсия, %"])
    for code, d in sorted(okved_data.items(), key=lambda x: -x[1].get("companies", 0)):
        w.writerow([code, d.get("companies", 0), d.get("created", 0),
                    d.get("duplicate", 0), d.get("rejected", 0), d.get("conversion", 0)])
    w.writerow([])

    w.writerow(["ПРИЧИНЫ ОТСЕВА"])
    w.writerow(["Причина", "Компаний"])
    for reason, count in sorted(rej_reasons.items(), key=lambda x: -x[1]):
        w.writerow([reason, count])

    content = out.getvalue().encode("utf-8-sig")
    date_str = datetime.now().strftime("%d.%m.%Y")
    filename = f"leadfinder_{date_str}.csv"

    return Response(
        content,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\""},
    )


@app.route("/")
def index():
    return HTML


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
