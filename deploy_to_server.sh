#!/bin/bash
# deploy_to_server.sh — развёртывание Lead Finder на Selectel сервере Bryanna
# Запускать ЛОКАЛЬНО: bash deploy_to_server.sh
# Требует: sshpass, ssh, scp

set -e

SERVER_IP="87.228.80.174"
SERVER_USER="root"
SERVER_PASS="oEt1RPj6p6aH"
REMOTE_DIR="/opt/lead_finder"
PORT=22  # или 2222

SSH="sshpass -p '$SERVER_PASS' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15 -p $PORT $SERVER_USER@$SERVER_IP"
SCP="sshpass -p '$SERVER_PASS' scp -o StrictHostKeyChecking=no -P $PORT"

echo "=== 1. Копируем файлы на сервер ==="
$SCP \
  lead_finder.py \
  app_finder.py \
  checko.py \
  qualifier.py \
  brizo.py \
  requirements_finder.txt \
  $SERVER_USER@$SERVER_IP:$REMOTE_DIR/ 2>/dev/null || {
    # Если папки нет — создаём
    sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no -p $PORT $SERVER_USER@$SERVER_IP "mkdir -p $REMOTE_DIR"
    $SCP \
      lead_finder.py app_finder.py checko.py qualifier.py brizo.py requirements_finder.txt \
      $SERVER_USER@$SERVER_IP:$REMOTE_DIR/
}

# proxies.txt (если есть)
[ -f proxies.txt ] && $SCP proxies.txt $SERVER_USER@$SERVER_IP:$REMOTE_DIR/ || true

# .env — ОБЯЗАТЕЛЬНО (без него ничего не работает)
if [ ! -f .env ]; then
  echo "ОШИБКА: файл .env не найден рядом со скриптом!"
  exit 1
fi
$SCP .env $SERVER_USER@$SERVER_IP:$REMOTE_DIR/

echo "=== 2. Настройка сервера ==="
sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no -p $PORT $SERVER_USER@$SERVER_IP << 'REMOTE'
set -e
REMOTE_DIR="/opt/lead_finder"
cd "$REMOTE_DIR"

echo "--- Python и pip ---"
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv screen 2>&1 | tail -5

echo "--- Виртуальное окружение ---"
python3 -m venv venv
source venv/bin/activate

echo "--- Зависимости ---"
pip install --quiet -r requirements_finder.txt

echo "--- Проверка импортов ---"
python3 -c "
import sys; sys.path.insert(0, '.')
from lead_finder import log
print('lead_finder imports OK')
" && echo "✓ OK" || echo "✗ Ошибка импорта — проверь .env"

echo "--- systemd сервис для app_finder ---"
cat > /etc/systemd/system/lead-finder.service << 'EOF'
[Unit]
Description=Lead Finder Web UI
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/lead_finder
Environment=PATH=/opt/lead_finder/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/opt/lead_finder/venv/bin/python3 /opt/lead_finder/app_finder.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable lead-finder
systemctl restart lead-finder

sleep 3
systemctl status lead-finder --no-pager | head -20

echo ""
echo "========================================"
echo "✅ Lead Finder задеплоен!"
echo "   Веб-интерфейс: http://$HOSTNAME:8082"
echo "   (Нужно открыть порт 8082 в Selectel Security Group)"
echo "========================================"
REMOTE

echo ""
echo "=== Готово! ==="
echo "Открой в браузере: http://$SERVER_IP:8082"
