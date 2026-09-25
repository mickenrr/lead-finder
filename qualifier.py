import warnings

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

load_dotenv()

REVENUE_LIMIT  = 1_000_000_000   # 1 млрд руб.
INCOME_TAX_MIN = 5_000_000       # 5 млн руб. — хотя бы раз за последние 3 года
MODEL          = "claude-haiku-4-5"


def _check_income_tax_rule(amounts: list, rule: dict) -> bool:
    """
    Проверяет выполнение правила налога на прибыль.

    amounts — список сумм налога, упорядоченный от новых к старым (amounts[0] = последний год).
    rule — словарь из settings["income_tax_rule"]:
        mode:       "any"    — хотя бы раз за N лет (дефолт)
                    "last"   — только последний год
                    "all"    — все N лет подряд
                    "k_of_n" — минимум K из N лет
        years:      сколько лет брать (для any/all/k_of_n)
        min_amount: минимальная сумма налога
        k:          минимальное кол-во лет (для k_of_n)
    """
    if not amounts:
        return False
    min_amt = rule.get("min_amount", INCOME_TAX_MIN)
    years   = rule.get("years", 3)
    mode    = rule.get("mode", "any")
    relevant = amounts[:years]

    if mode == "last":
        return relevant[0] >= min_amt
    elif mode == "all":
        return all(a >= min_amt for a in relevant)
    elif mode == "k_of_n":
        k = rule.get("k", 1)
        return sum(1 for a in relevant if a >= min_amt) >= k
    else:  # "any"
        return any(a >= min_amt for a in relevant)


def qualify_company(
    company_data: dict,
    revenue_max: int = REVENUE_LIMIT,
    income_tax_min: int = INCOME_TAX_MIN,   # backward compat (deprecated)
    income_tax_rule: dict | None = None,
    advanced_finance: dict | None = None,
) -> tuple[bool, str]:
    """Check sequential qualification criteria. Returns (passed, reason).

    revenue_max      — компании с выручкой >= этого значения отклоняются
    income_tax_rule  — словарь с правилом проверки налога (из settings.json).
                       Если None, используется income_tax_min в режиме "any / 3 года".
    advanced_finance — расширенные критерии (transport_tax_min и т.п.); 0 = не проверять.
    """

    # 1. Выручка — должна быть ниже порога (если известна)
    revenue = company_data.get("revenue")
    if revenue is not None and revenue >= revenue_max:
        return (False, "Интересные, но ярд")

    # 2. Налог на прибыль — по правилу из настроек
    amounts = company_data.get("income_tax_amounts") or []
    if not amounts and company_data.get("income_tax_amount") is not None:
        amounts = [company_data["income_tax_amount"]]

    if income_tax_rule:
        ok = _check_income_tax_rule(amounts, income_tax_rule)
    else:
        # Старая логика: хотя бы раз за 3 года >= income_tax_min
        ok = bool(amounts) and any(a >= income_tax_min for a in amounts[:3])

    if not ok:
        return (False, "Маленькая выручка/мало налогов")

    # 2.5. Общая сумма налогов «Итого» за последний год — должна быть >= 5 млн
    # Данные берутся из /taxes/data (authoritative). Если страница недоступна — не проверяем.
    taxes_total = company_data.get("taxes_total_from_data")
    if taxes_total is not None and taxes_total < INCOME_TAX_MIN:
        return (False, "Маленькая выручка/мало налогов")

    # 3. Расширенные финансовые критерии (если заданы и данные доступны)
    if advanced_finance:
        for field, key in [
            ("transport_tax",  "transport_tax_min"),
            ("property_tax",   "property_tax_min"),
            ("insurance",      "insurance_min"),
            ("vat",            "vat_min"),
        ]:
            threshold = advanced_finance.get(key, 0)
            if threshold > 0:
                val = company_data.get(field)
                if val is not None and val < threshold:
                    return (False, f"Низкий {field}: {val} < {threshold}")

    return (True, "Подходит")


def _keyword_target_check(text: str) -> bool:
    """
    Simple keyword fallback used when Anthropic API is unavailable.
    Returns False only for obvious resellers / integrators / service brokers.
    Returns True for everything else (own product assumed).
    """
    lower = text.lower()

    # Strong non-target signals
    non_target = [
        "официальный дилер", "официальный представитель",
        "дистрибьютор", "дистрибутор",
        "системный интегратор",
        "интернет-магазин", "интернет магазин", "онлайн-магазин",
        "агентство недвижимости", "продажа недвижимости", "аренда недвижимости",
        "перепродажа",
        # ticket / travel agencies
        "авиабилет", "авиа билет", "железнодорожных билетов", "продажа билетов",
        "консолидатор", "туроператор", "турагент", "туристическое агентство",
        # pure services / labour brokers
        "монтажные работы", "строительно-монтажные", "клининг",
        "охранное агентство", "охранные услуги",
        # retailers / shops
        "купить в нашем магазин", "наш интернет магазин", "корзина",
        "каталог товаров", "добавить в корзину",
    ]
    # Strong target signals — own product / manufacturing / development
    target = [
        "собственное производство", "собственной разработки",
        "наш продукт", "наши продукты",
        "производим", "производитель",
        "разрабатываем", "наша разработка",
        "собственный продукт",
        "патент", "патентован",
        "собственная разработка",
        "собственные технологии", "наши технологии",
        "инновацион",
    ]

    for kw in target:
        if kw in lower:
            return True
    for kw in non_target:
        if kw in lower:
            return False
    return True  # ambiguous — treat as target


# ИТ и наука (вне раздела C)
_SKOLKOVO_EXTRA = {
    "62.01", "62.02", "62.09", "63.11",
    "71.20", "72.11", "72.19",
}


def check_okved_skolkovo(okved_codes: list[str]) -> bool:
    """
    Возвращает True если хотя бы один ОКВЭД входит в список Сколково:
    — раздел C «Обрабатывающие производства» (коды 10–33)
    — ИТ: 62.01, 62.02, 62.09, 63.11
    — Наука: 71.20, 72.11, 72.19
    """
    import re as _re
    for code in okved_codes:
        if code in _SKOLKOVO_EXTRA:
            return True
        m = _re.match(r'^(\d+)\.', code)
        if m and 10 <= int(m.group(1)) <= 33:
            return True
    return False


def qualify_leads(leads: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (qualified, rejected) lists with qualification_reason attached."""
    qualified, rejected = [], []
    for lead in leads:
        passed, reason = qualify_company(lead)
        lead["qualification_reason"] = reason
        if passed:
            qualified.append(lead)
        else:
            rejected.append(lead)
    return qualified, rejected
