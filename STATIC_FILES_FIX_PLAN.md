# План исправления проблемы со статическими файлами на stage

## 🚨 Критическая проблема

На stage (`stg.formulatela58.ru`) все статические файлы возвращают **404 Not Found**:
- CSS файлы (`bootstrap-5.0.0-beta1.min.css`, `owl.carousel.min.css`, `main.css`)
- JavaScript файлы (`wow.min.js`, `imagesloaded.min.js`, `main.js`)
- Шрифты (`NTSomic-*.woff2`, `NTSomic-*.woff`)
- Изображения (`calendar.png`, `close.png`, `favicon.png`, `banner2-mob.jpg`)

**Последствия:**
- Верстка не работает (нет CSS)
- JavaScript не работает (нет JS файлов)
- Календарь не работает (нет flatpickr и других библиотек)
- Форма бронирования не функциональна

---

## 🔍 Диагностика

### 1. Проверить настройки Django

**На сервере stage:**

```bash
cd /path/to/app/mysite
source venv/bin/activate
export DJANGO_SETTINGS_MODULE=mysite.settings.staging
python manage.py shell
```

В shell:
```python
from django.conf import settings
print("STATIC_URL:", settings.STATIC_URL)
print("STATIC_ROOT:", settings.STATIC_ROOT)
print("STATICFILES_DIRS:", settings.STATICFILES_DIRS)
print("DEBUG:", settings.DEBUG)
```

**Ожидаемые значения:**
- `STATIC_URL = "/static/"`
- `STATIC_ROOT = "/path/to/app/staticfiles"` (или из env)
- `DEBUG = False`

### 2. Проверить наличие статических файлов

```bash
# Проверить, что collectstatic выполнился
ls -lh /path/to/app/staticfiles/
ls -lh /path/to/app/staticfiles/css/
ls -lh /path/to/app/staticfiles/js/
ls -lh /path/to/app/staticfiles/fonts/
ls -lh /path/to/app/staticfiles/images/

# Проверить конкретные файлы
ls -lh /path/to/app/staticfiles/css/main.css
ls -lh /path/to/app/staticfiles/js/main.js
ls -lh /path/to/app/staticfiles/fonts/NTSomic-Regular.woff2
```

**Если файлов нет:**
- `collectstatic` не выполнился или выполнился неправильно
- Нужно запустить вручную

### 3. Проверить конфигурацию nginx

**Найти конфиг nginx для stage:**

```bash
# Обычно находится в одном из этих мест:
/etc/nginx/sites-available/stg.formulatela58.ru
/etc/nginx/conf.d/stg.formulatela58.ru.conf
/etc/nginx/nginx.conf

# Или найти по имени сервиса
sudo find /etc/nginx -name "*formula*" -o -name "*stg*"
```

**Проверить наличие location для /static/:**

```bash
sudo cat /etc/nginx/sites-available/stg.formulatela58.ru | grep -A 5 "location /static"
```

**Должно быть что-то вроде:**

```nginx
location /static/ {
    alias /path/to/app/staticfiles/;
    expires 30d;
    add_header Cache-Control "public, immutable";
}
```

**Если location нет или путь неправильный:**
- Нужно добавить/исправить конфигурацию nginx

### 4. Проверить права доступа

```bash
# Проверить права на директорию staticfiles
ls -ld /path/to/app/staticfiles
ls -ld /path/to/app/staticfiles/css

# Должны быть права на чтение для nginx пользователя (обычно www-data или nginx)
# Если нет - исправить:
sudo chown -R www-data:www-data /path/to/app/staticfiles
sudo chmod -R 755 /path/to/app/staticfiles
```

### 5. Проверить логи nginx

```bash
# Проверить ошибки nginx
sudo tail -f /var/log/nginx/error.log

# Или для конкретного сайта
sudo tail -f /var/log/nginx/stg.formulatela58.ru.error.log
```

---

## 🔧 Решения

### Решение 1: Пересобрать статические файлы

**Если файлы отсутствуют или устарели:**

```bash
cd /path/to/app/mysite
source venv/bin/activate
export DJANGO_SETTINGS_MODULE=mysite.settings.staging

# Очистить старые файлы (опционально)
rm -rf staticfiles/*

# Собрать статику заново
python manage.py collectstatic --noinput --clear --verbosity 2

# Проверить результат
ls -lh staticfiles/css/main.css
```

**Или через GitHub Actions:**
- Уже добавлено в workflow, но можно запустить вручную через `workflow_dispatch`

### Решение 2: Настроить nginx для раздачи статики

**Если location /static/ отсутствует или неправильный:**

1. **Найти конфиг nginx для stage**

2. **Добавить или исправить location:**

```nginx
server {
    listen 80;
    server_name stg.formulatela58.ru;
    
    # ... другие настройки ...
    
    # Статические файлы
    location /static/ {
        alias /path/to/app/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, immutable";
        access_log off;
    }
    
    # Медиа файлы (если нужно)
    location /media/ {
        alias /path/to/app/media/;
        expires 7d;
        add_header Cache-Control "public";
    }
    
    # Django приложение
    location / {
        proxy_pass http://127.0.0.1:8000;  # или другой порт gunicorn
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

3. **Проверить конфиг:**

```bash
sudo nginx -t
```

4. **Перезагрузить nginx:**

```bash
sudo systemctl reload nginx
# или
sudo service nginx reload
```

### Решение 3: Исправить права доступа

**Если nginx не может читать файлы:**

```bash
# Узнать пользователя nginx
ps aux | grep nginx | head -1

# Обычно это www-data или nginx
# Установить правильные права
sudo chown -R www-data:www-data /path/to/app/staticfiles
sudo chmod -R 755 /path/to/app/staticfiles

# Проверить
ls -ld /path/to/app/staticfiles
```

### Решение 4: Временное решение (только для диагностики)

**Если нужно быстро проверить, что файлы есть:**

Можно временно включить раздачу статики через Django (только для диагностики!):

В `mysite/urls.py` изменить:

```python
# ВРЕМЕННО для диагностики - убрать проверку DEBUG
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
```

**⚠️ ВНИМАНИЕ:** Это только для диагностики! В production/staging статику должен раздавать nginx.

---

## 🧪 Проверка после исправления

### 1. Проверить в браузере

Открыть DevTools (F12) → Network tab:
- Обновить страницу (Ctrl+F5)
- Проверить, что все статические файлы загружаются со статусом 200
- Нет 404 ошибок

### 2. Проверить прямые URL

В браузере открыть:
- `https://stg.formulatela58.ru/static/css/main.css` → должен показать CSS
- `https://stg.formulatela58.ru/static/js/main.js` → должен показать JS
- `https://stg.formulatela58.ru/static/fonts/NTSomic-Regular.woff2` → должен загрузиться шрифт

### 3. Проверить верстку

- Форма должна быть в grid layout (3x2)
- Все элементы выровнены
- CSS стили применяются
- JavaScript работает (календарь, загрузка дат)

---

## 📋 Чеклист исправления

- [ ] Проверить настройки Django (STATIC_URL, STATIC_ROOT)
- [ ] Проверить наличие файлов в staticfiles/
- [ ] Запустить collectstatic если нужно
- [ ] Проверить конфигурацию nginx
- [ ] Добавить/исправить location /static/ в nginx
- [ ] Проверить права доступа на staticfiles/
- [ ] Перезагрузить nginx
- [ ] Проверить в браузере (Network tab)
- [ ] Проверить прямые URL статических файлов
- [ ] Проверить верстку и функциональность

---

## 🚀 Быстрые команды для исправления

### Полное исправление (если знаете путь к приложению):

```bash
# 1. Перейти в директорию приложения
cd /path/to/app/mysite

# 2. Активировать venv
source venv/bin/activate

# 3. Установить настройки
export DJANGO_SETTINGS_MODULE=mysite.settings.staging

# 4. Пересобрать статику
python manage.py collectstatic --noinput --clear --verbosity 2

# 5. Установить права (заменить www-data на пользователя nginx если другой)
sudo chown -R www-data:www-data /path/to/app/staticfiles
sudo chmod -R 755 /path/to/app/staticfiles

# 6. Перезагрузить nginx
sudo systemctl reload nginx

# 7. Проверить логи
sudo tail -f /var/log/nginx/error.log
```

---

## 📞 Если проблема остается

1. **Сделать скриншот** Network tab с ошибками
2. **Скопировать конфиг nginx** (без секретов)
3. **Проверить переменные окружения:**
   ```bash
   env | grep STATIC
   env | grep DJANGO
   ```
4. **Проверить, что gunicorn/wsgi работает:**
   ```bash
   sudo systemctl status formula_tela
   # или
   ps aux | grep gunicorn
   ```

---

**Дата создания:** 2025-12-18  
**Приоритет:** 🔴 КРИТИЧЕСКИЙ

