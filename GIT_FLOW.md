# Git Flow Strategy

## Ветки

### `dev` (разработка)
- Основная ветка для разработки
- Все изменения пушим сюда
- Автоматический деплой на сервер (staging)
- GitHub Actions: `deploy-staging.yml`

### `main` (production)
- Стабильная версия для пользователей
- Обновляется только через Pull Request из `dev`
- Деплой в production с manual approve
- GitHub Actions: `deploy.yml`

---

## Рабочий процесс (Workflow)

### 1. Разработка новой фичи

```bash
# Убедись что ты на ветке dev
git checkout dev
git pull origin dev

# Создаём feature branch (опционально)
git checkout -b feature/yclients-api

# Пишем код...
# ...

# Коммитим
git add .
git commit -m "feat: Add YClients API integration"

# Пушим в dev
git checkout dev
git merge feature/yclients-api
git push origin dev
```

**GitHub Actions автоматически задеплоит на сервер!** ✅

---

### 2. Тестирование на staging

После пуша в `dev`:
1. GitHub Actions запустит `deploy-staging.yml`
2. Код задеплоится на сервер (ветка dev)
3. Проверяем сайт: https://formulatela58.ru/
4. Если всё работает → переходим к шагу 3

---

### 3. Релиз в production

Когда всё протестировано и работает:

```bash
# Переходим на main
git checkout main
git pull origin main

# Мержим dev в main
git merge dev

# Пушим в main
git push origin main
```

**GitHub Actions запустит `deploy.yml`** с deploy approval! 🎯

---

## Структура CI/CD

```
┌─────────┐
│   dev   │ ← git push origin dev
└────┬────┘
     │ GitHub Actions: deploy-staging.yml
     │ ✅ Автоматический деплой
     ↓
┌─────────────┐
│   Staging   │ ← https://formulatela58.ru (dev branch)
└─────────────┘
     │ Тестируем...
     │ Всё работает? → Pull Request: dev → main
     ↓
┌─────────┐
│  main   │ ← git push origin main (или merge PR)
└────┬────┘
     │ GitHub Actions: deploy.yml
     │ ⚠️ Manual Approve требуется!
     ↓
┌──────────────┐
│  Production  │ ← https://formulatela58.ru (main branch)
└──────────────┘
```

---

## Быстрые команды

### Пуш изменений в dev (ежедневная разработка)

**⚠️ ВАЖНО:** При использовании `git add` в Windows могут возникать ошибки с путями. 
См. [GIT_ADD_GUIDE.md](GIT_ADD_GUIDE.md) для правильного подхода.

```bash
# Безопасный способ: добавление конкретных файлов
git add mysite/services_app/yclients_api.py
git add mysite/website/views.py
git add mysite/website/templates/website/service_detail.html

# Или добавление всех измененных файлов (осторожно!)
git add -u

# Коммит
git commit -m "feat: Description"

# Пуш
git push origin dev
```

### Релиз в production (когда всё готово)
```bash
git checkout main
git merge dev
git push origin main
```

### Откат к предыдущей версии
```bash
# На сервере
cd /home/taximeter/mysite/formula_tela
git checkout main  # или dev
git reset --hard HEAD~1  # откат на 1 коммит назад
sudo systemctl restart formula_tela
```

---

## Настройка GitHub Environments

### Staging Environment
- **Name:** `staging`
- **Секреты:** SSH_HOST, SSH_USER, SSH_PORT, SSH_KEY
- **Approval:** Не требуется (автоматический деплой)

### Production Environment
- **Name:** `production`
- **Секреты:** те же самые
- **Approval:** ✅ Требуется подтверждение вручную
- **Protection rules:** 
  - Required reviewers: 1
  - Deployment branch: только `main`

---

## Health Check

### Staging
- Health check необязателен (`continue-on-error: true`)
- Если упал - деплой всё равно проходит
- Нужно для тестирования

### Production
- Health check обязателен
- Если упал - деплой останавливается
- Нужно для безопасности

---

## Troubleshooting

### Деплой упал - что делать?

1. **Смотрим логи GitHub Actions:**
   - https://github.com/AndreyDeveloper84/formula_tela/actions

2. **Смотрим логи на сервере:**
   ```bash
   ssh taximeter@сервер
   sudo journalctl -u formula_tela -n 50 --no-pager
   ```

3. **Откатываемся назад (если нужно):**
   ```bash
   cd /home/taximeter/mysite/formula_tela
   git reset --hard HEAD~1
   sudo systemctl restart formula_tela
   ```

---

## Полезные ссылки

- **GitHub Actions:** https://github.com/AndreyDeveloper84/formula_tela/actions
- **Staging сайт:** https://formulatela58.ru/ (dev)
- **Production сайт:** https://formulatela58.ru/ (main, когда запустим)

## Дополнительные руководства

- **[GIT_ADD_GUIDE.md](GIT_ADD_GUIDE.md)** - Руководство по безопасному использованию `git add` в Windows
  - Решение проблем с путями
  - Проверка существования файлов
  - Обработка ошибок
