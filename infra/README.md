# Infra: deploy artifacts

Конфиги/скрипты которые **должны быть на проде**, версионируем в репо для
воспроизводимости и code-review при изменениях.

## Структура

```
infra/
├── systemd/
│   └── formula-tela-maxbot.service   # systemd unit для MAX-бота (T-14)
└── nginx/
    └── maxbot-location.conf          # nginx location-блок для webhook (T-14)
```

## Деплой MAX-бота на prod (одноразовая установка, T-14)

Все шаги — на сервере `taximeter@app.penza.taxi`. Sudo операции требуют пароль.

### 1. Обновить код и зависимости
```bash
cd /home/taximeter/mysite/formula_tela
git pull origin main          # после merge dev → main
.venv312/bin/pip install -r requirements.txt   # ставит maxapi[webhook]==1.0.0
cd mysite
.venv312/bin/python manage.py migrate          # миграция 0057 BotUser/HelpArticle
```

### 2. Добавить env-переменные
В `/home/taximeter/mysite/formula_tela/.env`:
```
MAX_BOT_TOKEN=<реальный токен из MAX для партнёров>
MAX_BOT_MODE=webhook
MAX_WEBHOOK_HOST=127.0.0.1
MAX_WEBHOOK_PORT=8003
MAX_WEBHOOK_PATH=/api/maxbot/webhook/
MAX_WEBHOOK_SECRET=<сгенерировать 32-байтный секрет, например через `openssl rand -hex 32`>
```

### 3. Установить systemd unit
```bash
sudo cp /home/taximeter/mysite/formula_tela/infra/systemd/formula-tela-maxbot.service \
        /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable formula-tela-maxbot
sudo systemctl start formula-tela-maxbot
sudo systemctl status formula-tela-maxbot     # должен быть active (running)
sudo journalctl -u formula-tela-maxbot -f     # логи в реалтайме
```

### 4. Добавить nginx location
Открыть `/etc/nginx/sites-enabled/formula_tela`, внутри блока `server { listen 443 ssl;
server_name formulatela58.ru; ... }` вставить содержимое
`infra/nginx/maxbot-location.conf` РЯДОМ с другими `location` блоками.

```bash
# Резервная копия
sudo cp /etc/nginx/sites-enabled/formula_tela \
        /etc/nginx/nginx.conf.bak.maxbot.$(date +%Y%m%d_%H%M%S)
# Редактировать руками или через скрипт
sudo nano /etc/nginx/sites-enabled/formula_tela
# Validate + reload
sudo nginx -t && sudo systemctl reload nginx
```

### 5. Подписать webhook у MAX
```bash
WEBHOOK_URL="https://formulatela58.ru/api/maxbot/webhook/"
SECRET="<тот же что в MAX_WEBHOOK_SECRET>"
TOKEN="<тот же что в MAX_BOT_TOKEN>"

curl -X POST "https://botapi.max.ru/subscriptions" \
  -H "Authorization: $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"url\": \"$WEBHOOK_URL\", \"secret\": \"$SECRET\"}"
# Должен вернуть {"success": true}
```

### 6. Smoke на проде
1. Открыть бота в MAX, нажать /start → главное меню (4 кнопки)
2. Нажать «Услуги» → список из БД
3. Нажать любую услугу → «Как к вам обращаться?» (FSM awaiting_name)
4. Ввести имя → «Телефон?»
5. Ввести телефон → подтверждение → создать → проверить:
   ```bash
   /admin/services_app/bookingrequest/    # появилась с source=bot_max
   ```
6. Telegram должен прийти уведомление менеджеру

## Откат
```bash
sudo systemctl stop formula-tela-maxbot
sudo systemctl disable formula-tela-maxbot

# Снять подписку MAX
curl -X DELETE "https://botapi.max.ru/subscriptions?url=https://formulatela58.ru/api/maxbot/webhook/" \
  -H "Authorization: $TOKEN"

# Откатить nginx
sudo cp $(ls -t /etc/nginx/nginx.conf.bak.maxbot.* | head -1) \
        /etc/nginx/sites-enabled/formula_tela
sudo nginx -t && sudo systemctl reload nginx
```

`formula_tela.service` (основной gunicorn сайта) **не зависит** от maxbot —
MAX-бот можно отключать и включать без влияния на сайт.
