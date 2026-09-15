# Brizo Lead Parser

Автоматический сбор и квалификация лидов из CRM Brizo с обогащением данных через Checko.

## Структура

```
parser/
├── main.py        # Точка входа — запускает весь пайплайн
├── brizo.py       # Авторизация и парсинг лидов из Brizo (Playwright)
├── checko.py      # Обогащение данных по ИНН через checko.ru
├── qualifier.py   # Правила квалификации лидов
├── .env           # Учётные данные (не коммитить в git!)
└── output/        # Создаётся автоматически при первом запуске
    ├── qualified_leads.csv
    ├── rejected_leads.csv
    └── qualified_leads.json
```

## Установка

```bash
pip install playwright beautifulsoup4 requests python-dotenv
playwright install chromium
```

## Настройка

Заполни `.env`:

```
BRIZO_URL=https://sad1.brizo.ru
BRIZO_EMAIL=your@email.com
BRIZO_PASSWORD=yourpassword
CHECKO_URL=https://checko.ru
```

## Запуск

```bash
cd parser
python main.py
```

## Логика квалификации

Правила в `qualifier.py`. По умолчанию лид отклоняется если:
- Статус компании содержит: «ликвидирована», «ликвидируется», «банкротство»
- Нет ИНН
- Имя короче 3 символов

## Важно

- `.env` содержит пароли — **не добавляй в git**. Убедись, что `.env` есть в `.gitignore`.
- Checko делает паузу 1.5 сек между запросами, чтобы не получить бан. Значение меняется параметром `delay` в `enrich_leads()`.
