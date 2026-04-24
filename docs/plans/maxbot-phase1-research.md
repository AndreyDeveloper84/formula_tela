# T-01 Research Spike: maxapi SDK

**Дата:** 2026-04-24
**Источник:** [github.com/max-messenger/max-botapi-python](https://github.com/max-messenger/max-botapi-python) (клонирован в `/tmp/max-botapi-python`)
**Цель:** зафиксировать точные сигнатуры API для задач T-02..T-15.

---

## 1. Метаданные пакета

| Параметр | Значение |
|---|---|
| Имя пакета (PyPI) | `maxapi` |
| Версия | **0.9.4** |
| Python | `>=3.10` (3.12 поддерживается) |
| Лицензия | MIT |
| Установка | `pip install 'maxapi==0.9.4'` (pin на текущую стабильную) |
| Webhook | `pip install 'maxapi[webhook]==0.9.4'` (добавляет fastapi+uvicorn) |

**Зависимости:**
- `aiohttp>=3.12.14`
- `magic_filter>=1.0.0`
- `pydantic>=1.8.0`
- `aiofiles==24.1.0`
- `puremagic==1.30`
- +`fastapi>=0.68.0`, `uvicorn>=0.15.0` (только для webhook)

**Совместимость с текущим стеком:** OK. Django 5.2 не конфликтует. У нас уже `aiohttp` (не прямо, но через async-код агентов).

---

## 2. Модель кнопок (7 типов)

Импорты из `maxapi.types`:

```python
from maxapi.types import (
    ChatButton,                  # создать чат
    LinkButton,                  # внешний URL (для tel: работает)
    CallbackButton,              # отправляет MessageCallback с payload
    RequestGeoLocationButton,
    MessageButton,               # ответ сообщением
    RequestContactButton,        # запросить телефон (готовое решение!)
    OpenAppButton,               # mini app
    ButtonsPayload,              # ручная сборка без builder
)
```

**Важно для нас:**
- `LinkButton(text='Позвонить', url='tel:88412393433')` — подходит для кнопки звонка в контактах
- `RequestContactButton(text='Поделиться контактом')` — **встроенный способ получить телефон пользователя** без ручного ввода. Упрощает FSM заявки: после имени предлагаем эту кнопку или ручной ввод.
- `CallbackButton(text='...', payload='cb:svc:123')` — payload — строка, лимит не указан (по аналогии с Telegram ~64 байта, лучше короткие)

---

## 3. Сборка клавиатуры (2 способа)

### Builder (рекомендован):
```python
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from maxapi.types import CallbackButton, LinkButton

builder = InlineKeyboardBuilder()
builder.row(
    CallbackButton(text='📅 Записаться', payload='cb:menu:book'),
    CallbackButton(text='ℹ️ Услуги', payload='cb:menu:services'),
)
builder.row(
    CallbackButton(text='📞 Контакты', payload='cb:menu:contacts'),
    CallbackButton(text='❓ FAQ', payload='cb:menu:faq'),
)
await event.message.answer(
    text='Выберите раздел:',
    attachments=[builder.as_markup()],
)
```

### Через payload (более декларативно):
```python
from maxapi.types import ButtonsPayload
buttons = [[CallbackButton(text='A', payload='a'), CallbackButton(text='B', payload='b')]]
await event.message.answer(
    text='...',
    attachments=[ButtonsPayload(buttons=buttons).pack()],
)
```

**Выбираем builder** — читаемее, легче тестировать.

---

## 4. Handlers и события

### Регистрация handler'ов:
```python
from maxapi import Bot, Dispatcher
from maxapi.types import (
    MessageCreated,   # любое текстовое сообщение
    MessageCallback,  # нажатие CallbackButton
    MessageChatCreated,
    CommandStart,     # = Command('start')
    Command,          # произвольная команда
    BotStarted,       # первый контакт с ботом
)

bot = Bot(token='...')
dp = Dispatcher()

@dp.bot_started()
async def on_start(event: BotStarted): ...

@dp.message_created(CommandStart())
async def on_slash_start(event: MessageCreated): ...

@dp.message_created(Command('help'))
async def on_help(event: MessageCreated): ...

@dp.message_created()  # без фильтра — все текстовые сообщения
async def on_any_text(event: MessageCreated): ...

@dp.message_callback()  # все callback-нажатия
async def on_callback(callback: MessageCallback):
    payload = callback.callback.payload  # строка из CallbackButton
    await callback.message.answer('...')
```

### Отправка:
- `event.message.answer(text, attachments=[])` — ответ в тот же чат
- `bot.send_message(chat_id=..., text=..., attachments=[])` — прямая отправка

---

## 5. FSM (встроенный в SDK — `MemoryContext`)

**КРИТИЧНАЯ НАХОДКА:** SDK уже содержит in-memory FSM, **не нужно писать свой на Django cache** для MVP.

### Определение состояний:
```python
from maxapi.context.state_machine import State, StatesGroup

class BookingStates(StatesGroup):
    awaiting_name = State()
    awaiting_phone = State()
    awaiting_confirm = State()
```

### Использование в handler'е (context инжектится автоматически):
```python
from maxapi.context.context import MemoryContext

@dp.message_callback()
async def on_service_click(callback: MessageCallback, context: MemoryContext):
    payload = callback.callback.payload  # "cb:svc:123"
    service_id = int(payload.split(':')[2])

    await context.set_state(BookingStates.awaiting_name)
    await context.update_data(service_id=service_id)
    await callback.message.answer('Как к вам обращаться?')


@dp.message_created()  # обрабатывает текст когда state = awaiting_name
async def on_name_input(event: MessageCreated, context: MemoryContext):
    current_state = await context.get_state()
    if str(current_state) != str(BookingStates.awaiting_name):
        return  # другой handler разберётся

    name = event.message.body.text.strip()
    # validate name...
    await context.update_data(name=name)
    await context.set_state(BookingStates.awaiting_phone)
    await event.message.answer('Ваш телефон?')
```

### Ограничения in-memory FSM:
- **Per-process** — если uvicorn перезапустится (deploy, OOM), state всех активных диалогов **теряется**
- **Не шарится между workers** — при scale-out нужна внешняя storage
- Для MVP Фазы 1 (один worker, одна инстанция, ~50 пользователей) — **приемлемо**
- Миграция на Redis-backed state — задача Фазы 2

---

## 6. Webhook — 2 способа

### High-level (SDK сам поднимает FastAPI+uvicorn):
```python
await dp.handle_webhook(
    bot=bot,
    host='127.0.0.1',
    port=8003,
    log_level='info',
)
```

### Low-level (регистрируем свой FastAPI endpoint):
```python
from maxapi.methods.types.getted_updates import process_update_webhook

@dp.webhook_post('/api/maxbot/webhook/')
async def webhook(request: Request):
    event_json = await request.json()
    event_object = await process_update_webhook(event_json=event_json, bot=bot)
    await dp.handle(event_object)
    return JSONResponse(content={'ok': True})

await dp.init_serve(bot, host='127.0.0.1', port=8003)
```

**Выбираем high-level** — меньше кода, SDK разбирается с path'ом сам. Path для MAX подписки: `https://formulatela58.ru/api/maxbot/webhook/` — SDK по дефолту слушает на `/`, nginx location без rewrite пробросит тело.

### Подписка webhook у MAX (вручную при деплое):
```bash
curl -X POST https://botapi.max.ru/subscriptions \
  -H "Authorization: $MAX_BOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://formulatela58.ru/api/maxbot/webhook/"}'
```

---

## 7. Middleware (для логирования/метрик/auth)

```python
from maxapi.filters.middleware import BaseMiddleware
from maxapi.types import UpdateUnion

class LoggingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event_object: UpdateUnion, data: dict):
        logger.info(f'{event_object.update_type} from user_id={event_object.from_user.user_id}')
        try:
            return await handler(event_object, data)
        except Exception as e:
            logger.exception('handler failed')
            raise

dp.middlewares = [LoggingMiddleware()]
```

Будем использовать для:
- Логирования всех событий
- Ловли exception'ов и отправки алерта через `notifications.send_notification_telegram`
- Инжекта `bot_user` в data (resolve BotUser из `event.from_user.user_id` один раз на event)

---

## 8. Long-polling (для локальной разработки)

```python
async def main():
    await bot.delete_webhook()  # если был установлен
    await dp.start_polling(bot)
```

Используем переменную `MAX_BOT_MODE=polling|webhook` в `.env` для переключения.

---

## 9. Методы API (для прямых вызовов)

Все в `maxapi/methods/`:
- `get_me`, `get_subscriptions`, `subscribe_webhook`, `unsubscribe_webhook`
- `send_message`, `edit_message`, `delete_message`
- `get_chats`, `get_chat_by_id`, `get_members_chat`
- `send_callback` (ответ на callback, если нужно показать notification «Обрабатываем...»)

Пример прямого вызова:
```python
me = await bot.get_me()
subs = await bot.get_subscriptions()
```

---

## 10. Webhook signature verification

**Не найдено в SDK** — похоже что `maxapi` не валидирует подпись, `platform-api.max.ru` по документации тоже не шлёт HMAC.

### Наша стратегия защиты endpoint'а:
1. **Secret path**: `https://formulatela58.ru/api/maxbot/webhook/{SECRET}/` — 32-байтный случайный токен в URL, передаётся MAX только при `subscribe_webhook`. Сравнимо по безопасности с подписью для нашего уровня чувствительности.
2. **nginx rate limit**: `limit_req_zone` на этот path — 20 r/s, чтобы spam-бот не зафлудил
3. **Обработчик игнорирует** любой update, у которого `from_user.user_id` не из MAX rangе (проверка в middleware)

Реализую в T-13 (entrypoint) + T-14 (nginx).

---

## 11. Итог для плана

**Меняется в плане (обновлю `maxbot-phase1.md`):**

1. **§4.2 (структура пакета)** — убираем `state.py` (используем встроенный `MemoryContext`). Оставляем `personalization.py`.

2. **§4.4 (FSM)** — полностью переписываем: используем `StatesGroup` + `MemoryContext` из SDK. Наш `state.py` не нужен.

3. **T-05 задачу** исключаем (FSM-менеджер уже в SDK). Сэкономили 2h.

4. **T-14 (infra)** добавляем генерацию secret-path и subscribe_webhook.

5. **Новая оценка:** 38h - 2h (T-05) = **36h**, 14 задач вместо 15.

---

## 12. Open questions после research

- [ ] Максимальный размер `CallbackButton.payload` — 64 байта? 1024? Нужно найти в доке / тестом. Если 64 — использовать короткие коды (`s:123` вместо `cb:service:123`).
- [ ] `BotStarted` event срабатывает при первом добавлении бота в чат или каждый раз? Влияет на greeting-логику в T-07.
- [ ] `event.from_user.user_id` всегда присутствует в `MessageCreated`? Или только в некоторых типах events?

Проверим эмпирически в T-03 (skeleton) когда запустим локально через long-polling.
