# Dockerfile
# Базовый образ — это как операционная система для контейнера
FROM python:3.12-slim

# Говорим Python не буферизовать вывод (чтобы видеть логи сразу)
ENV PYTHONUNBUFFERED=1

# Создаём рабочую директорию (как cd /app)
WORKDIR /app

# Копируем файл с зависимостями
COPY requirements.txt .

# Устанавливаем зависимости
# --no-cache-dir = не сохранять кеш (меньше размер образа)
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код приложения
COPY mysite/ ./mysite/

# Открываем порт 8000 (на нём будет работать Django)
EXPOSE 8000

# Команда, которая запустится при старте контейнера
CMD ["python", "mysite/manage.py", "runserver", "0.0.0.0:8000"]