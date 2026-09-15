# Официальный образ Playwright с предустановленным Chromium
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

WORKDIR /app

# Устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код (без .env и кэша)
COPY . .
RUN rm -f .env

# Chromium уже установлен в базовом образе, указываем путь
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Railway/Render подставят PORT автоматически
EXPOSE 8082

CMD ["python", "app.py"]
