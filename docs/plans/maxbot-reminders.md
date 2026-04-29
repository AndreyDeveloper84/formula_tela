# MAX-бот — система напоминаний с подтверждением

## Цель

Снизить no-show: напоминать клиенту о записи и просить подтвердить приход.
Если клиент не реагирует — менеджер видит это и звонит сам.

## Когда напоминать

| Триггер | Время отправки | Текст |
|---|---|---|
| T-24h | накануне в 19:00 | «Напоминаем: завтра в 14:00 у Сазоновой Инны массаж. Подтвердите, что придёте» |
| T-2h  | за 2ч до визита (с 09:00 до 21:00) | «Через 2 часа запись у Сазоновой Инны. Ждём вас!» |

Кнопки на T-24h:
- ✅ Подтверждаю → reminder.status = confirmed
- 🔄 Перенести → free-text → менеджер свяжется
- ❌ Отменить запись → cancellation flow (отдельная задача, пока — BotInquiry для менеджера)

T-2h — без кнопок, просто напоминание (если клиент уже подтвердил), либо с теми же кнопками если status=pending.

## Эскалация

Если за **12ч до визита** `reminder.status == pending` (T-24h отправлен но не подтверждён) → Telegram-алерт менеджеру с подсказкой позвонить клиенту.

## Модель данных

```python
class BookingReminder(models.Model):
    """Напоминание о YClients-записи. Создаётся при confirm_booking
    (когда мы получили yclients_record_id), удаляется/закрывается
    после визита."""

    class Kind(models.TextChoices):
        DAY_BEFORE = "day_before", "За день до визита (T-24h)"
        TWO_HOURS = "two_hours", "За 2 часа до визита (T-2h)"

    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает действия клиента"
        CONFIRMED = "confirmed", "Клиент подтвердил"
        RESCHEDULE_REQUESTED = "reschedule", "Клиент просит перенести"
        CANCELLED = "cancelled", "Клиент отменил"
        SENT_NO_REPLY = "sent_no_reply", "Отправлено, без ответа"
        ESCALATED = "escalated", "Менеджер уведомлён"

    bot_user = models.ForeignKey("services_app.BotUser", on_delete=models.CASCADE)
    yclients_record_id = models.CharField(max_length=64, db_index=True)
    visit_at = models.DateTimeField()  # plan time of visit
    kind = models.CharField(max_length=16, choices=Kind.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    scheduled_at = models.DateTimeField()  # когда планировали отправить
    sent_at = models.DateTimeField(null=True, blank=True)
    replied_at = models.DateTimeField(null=True, blank=True)
    master_name = models.CharField(max_length=120, blank=True)  # snapshot для текста
    service_name = models.CharField(max_length=200, blank=True)

    class Meta:
        unique_together = [("yclients_record_id", "kind")]
        indexes = [models.Index(fields=["status", "scheduled_at"])]
```

## Создание напоминаний

В `payments/booking_service.py::YClientsBookingService.create_record(order)` после
успешного `yclients_record_id` — НЕ туда (там нет bot_user). Реальная точка
создания: `maxbot/ai_action_service.py::execute_confirm_booking` после native
booking. Хук туда:

```python
async def _create_reminders(bot_user, yclients_record_id, visit_at, master, service):
    """Создать 2 reminder-а — T-24h и T-2h."""
    from datetime import timedelta
    day_before = visit_at - timedelta(hours=24)
    two_hours = visit_at - timedelta(hours=2)
    # T-24h: округлить до 19:00 предыдущего дня
    day_before_19 = day_before.replace(hour=19, minute=0, second=0, microsecond=0)
    if day_before_19 < timezone.now():
        return  # запись слишком близкая
    await sync_to_async(BookingReminder.objects.bulk_create)([
        BookingReminder(
            bot_user=bot_user, yclients_record_id=yclients_record_id,
            visit_at=visit_at, kind="day_before",
            scheduled_at=day_before_19,
            master_name=master.name, service_name=service.name,
        ),
        BookingReminder(
            bot_user=bot_user, yclients_record_id=yclients_record_id,
            visit_at=visit_at, kind="two_hours",
            scheduled_at=two_hours,
            master_name=master.name, service_name=service.name,
        ),
    ], ignore_conflicts=True)
```

## Celery beat

```python
"send-bot-reminders-every-15min": {
    "task": "maxbot.tasks.send_due_reminders",
    "schedule": crontab(minute="*/15"),  # каждые 15 минут
},
"escalate-stale-reminders-hourly": {
    "task": "maxbot.tasks.escalate_stale_reminders",
    "schedule": crontab(minute=0),
},
```

`send_due_reminders`:
- `BookingReminder.objects.filter(status=PENDING, scheduled_at__lte=now)`
- Для каждого: вызвать MAX API `bot.send_message` с текстом + кнопками (T-24h)
  или без кнопок (T-2h если уже confirmed)
- `sent_at = now, status = SENT_NO_REPLY` (default до клика)
- Idempotent (sent_at = null check)

`escalate_stale_reminders`:
- `BookingReminder.objects.filter(kind=DAY_BEFORE, status=SENT_NO_REPLY,
   visit_at__lte=now+12h, escalated=False)`
- Telegram-алерт менеджеру: «Клиент Х не подтвердил запись на завтра 14:00. Позвоните?»
- `status = ESCALATED`

## Callback handlers

Payload format:
- `cb:rem:confirm:{reminder_id}` → status=CONFIRMED, replied_at=now, ответ боту
- `cb:rem:reschedule:{reminder_id}` → status=RESCHEDULE_REQUESTED + BotInquiry для менеджера
- `cb:rem:cancel:{reminder_id}` → status=CANCELLED + BotInquiry для менеджера

Handler в `maxbot/handlers/reminders.py`. Зарегистрировать router в `main.py`.

## Что МОЖНО упустить в MVP (Phase 1)

- Отмена записи в YClients автоматически — пока только BotInquiry менеджеру
- Перенос — то же
- Локализация по timezone клиента — все в Europe/Moscow (Пенза)

## Тесты

1. `test_booking_reminder_model.py` — модель + unique_together
2. `test_create_reminders_on_confirm.py` — после execute_confirm_booking создаётся 2 reminder
3. `test_send_due_reminders.py` — Celery task, идемпотентность, формат текста
4. `test_escalate_stale_reminders.py` — после 12ч до визита + SENT_NO_REPLY → ESCALATED
5. `test_reminder_callbacks.py` — кнопки → status update + ответ

## Порядок реализации

1. Модель + migration (~30 мин)
2. Хук создания в execute_confirm_booking (~30 мин)
3. Celery task send_due_reminders (~1.5h)
4. Celery task escalate (~1h)
5. Callback handlers (~1.5h)
6. Тесты (~1.5h)

**Итого ~6h**.
