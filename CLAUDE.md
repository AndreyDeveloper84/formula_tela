# CLAUDE.md — Проект «Формула тела»

## Обзор проекта
Django 5.2 веб-приложение для салона массажа и эстетики «Формула тела».
Русскоязычный сайт. Каталог услуг, SEO-посадочные страницы, онлайн-запись,
профили мастеров, AI-агенты маркетинговой автоматизации, управление через
Django Admin.

---

## Технический стек
- **Фреймворк:** Django 5.2
- **База данных:** SQLite3 (локально) / PostgreSQL 16 (продакшн через Docker)
- **Очередь задач:** Redis 7 + Celery (worker + beat scheduler)
- **Изображения:** Pillow
- **API:** Django REST Framework + drf-spectacular
- **Тесты:** pytest + pytest-django + model-bakery (~75 test-файлов)
- **AI:** OpenAI (gpt-4o-mini) с tool-use, MCP (Model Context Protocol) сервер с chromadb
  embeddings; русские прокси для OpenAI/Telegram (`OPENAI_PROXY`/`TELEGRAM_PROXY`)
- **MAX-бот:** `maxapi[webhook]==1.0.0` (мессенджер MAX) — standalone async-процесс
- **Внешние интеграции:** YClients (синхронизация записей + admin webhook),
  Яндекс.Метрика, Яндекс.Вебмастер, Яндекс.Директ, VK Ads, Telegram, MAX, OpenAI, YooKassa

---

## Структура репозитория
```
formula_tela/                       <- корень git
├── mysite/                         <- корень Django проекта (здесь manage.py)
│   ├── mysite/                     <- пакет настроек проекта
│   │   └── settings/               <- base.py, dev.py, local.py, staging.py, production.py
│   ├── services_app/               <- ядро домена: каталог услуг, блоки, медиа, FAQ, отзывы;
│   │                                  бот-модели (BotUser, HelpArticle, BotInquiry,
│   │                                  Conversation, Message, BookingReminder); Order/Cert
│   ├── website/                    <- frontend: views, шаблоны, sitemaps, DRF-сериалайзеры
│   ├── booking/                    <- placeholder (booking API живёт в website/views.py)
│   ├── notifications/              <- Telegram + email + MAX-bot уведомления (Python-пакет)
│   ├── payments/                   <- YooKassa: services, booking_service, tasks, webhook,
│   │                                  ip_whitelist, certificate_pdf, admin (override Order/Cert)
│   ├── agents/                     <- AI-агенты + SEO + интеграции
│   │   ├── agents/                 <- модули агентов (analytics, analytics_budget, offers,
│   │   │                              offer_packages, smm_growth, seo_landing, seo_landing_qc,
│   │   │                              seo_growth, supervisor, trend_scout, landing_generator,
│   │   │                              qc_checks; helpers _outcomes/_lifecycle/_revenue/_json_utils)
│   │   ├── integrations/           <- yandex_metrika, yandex_webmaster, yandex_direct,
│   │   │                              vk_ads, site_crawler, trend_parser
│   │   └── management/             <- check_metrika, check_webmaster, check_crawler,
│   │                                  check_agents, seed_seo_clusters, apply_seo_audit, ...
│   ├── maxbot/                     <- Standalone async-процесс MAX-бота (Phase 1+2+2.3+2.4)
│   │   ├── ai_concierge.py         <- главный chat-pipeline на OpenAI tool-use
│   │   ├── ai_tools.py             <- 6 OpenAI tool-definitions
│   │   ├── ai_tool_handlers.py     <- dispatch_tool_call → ActionResult
│   │   ├── ai_action_service.py    <- side-effects (BookingRequest, YClients, BotInquiry)
│   │   ├── ai_context.py           <- build_master_context (Top-N мастеров, anti-hallucination)
│   │   ├── ai_prompts.py           <- system prompt template
│   │   ├── ai_ui.py                <- action_data → MAX inline keyboard
│   │   ├── ai_yclients.py          <- enrich_show_masters/slots/my_bookings (YClients fetch)
│   │   ├── mcp_client.py           <- stdio-клиент к services/formulatela_mcp (singleton)
│   │   ├── llm.py                  <- get_async_openai_client (с прокси)
│   │   ├── reminders_factory.py    <- create_reminders_for_booking (T-24h + T-2h)
│   │   ├── tasks.py                <- Celery: send_due_reminders, escalate_stale,
│   │   │                              send_post_visit_followups, send_repeat_offers
│   │   ├── yclients_webhook.py     <- POST /api/yclients/webhook/ — события из YClients-админки
│   │   ├── handlers/               <- 9 router'ов: start, services, booking, contacts, faq,
│   │   │                              reminders, ai_callbacks, ai_assistant, fallback
│   │   └── (config.py, middleware.py, main.py, keyboards.py, texts.py, states.py,
│   │        warmup.py, welcome.py, personalization.py, intents.py, menu_state.py,
│   │        popular_questions.py, response_cache.py, voice_examples.py, django_bootstrap.py)
│   ├── tests/                      <- pytest (~75 файлов, в т.ч. tests/maxbot/)
│   └── manage.py
├── services/
│   └── formulatela_mcp/            <- MCP-сервер (Model Context Protocol) — standalone
│                                      Python-пакет, спавнится maxbot через stdio.
│                                      Tools: ping, search_faq (chromadb embeddings)
├── infra/
│   ├── systemd/                    <- formula-tela-maxbot.service
│   ├── nginx/                      <- maxbot-location.conf
│   └── README.md                   <- инструкция деплоя бота на прод
├── docs/
│   └── plans/                      <- maxbot-phase1*, phase2-ai-mcp, phase2-native-booking,
│                                      phase24-consultative, reminders, research-T01
├── audits/                         <- markdown-отчёты codebase-audit-suite (ln-6XX worker'ов)
├── docker-compose.yml
├── Dockerfile
├── .dockerignore                   <- исключает .env, .git, .venv, audits, media
├── requirements.txt
├── Makefile                        <- 12 команд (db / run / migrate / docker / worker / beat / ...)
└── pytest.ini
```

---

## Ключевые приложения

### services_app (ядро)
Все бизнес-модели. Основные модели:
- `Service` — slug, seo_h1, seo_title, seo_description, subtitle, price_from, duration_min,
  related_services (M2M self-ref), emoji, short_description, is_active, is_popular,
  **`goals`** (JSONField, список из 12 slug'ов: relax, antistress, back_pain, posture,
  recovery, tone, weight_loss, cellulite, lymph, beauty_face, hair_removal, pregnancy_safe —
  для AI Concierge `recommend_services`), **`requires_health_check`** + **`contraindications`**
  (Phase 2.4 T03 — AI задаёт screening-вопросы перед confirm_booking для опасных услуг)
- `ServiceCategory` — категории на основе slug, с image/image_mobile
- `ServiceOption` — варианты цен для услуги; поля: unit_type (session/zone/visit), units,
  price, yclients_service_id; вычисляемое `price_per_session`
- `ServiceBlock` — контентные блоки для SEO-посадочных страниц (12 типов: text, accent,
  checklist, identification, cta, price_table, accordion, faq, special_formats, subscriptions,
  navigation, html); поля: heading_level, bg_color, text_color, btn_text, btn_sub, css_class
- `ServiceMedia` — фото/видео; поля: media_type, display_mode (single/carousel),
  carousel_group, image, image_mobile, video_url, video_file (MP4/WebM), insert_after_order
- `FAQ` — вопросы и ответы по категориям (question, answer, FK к ServiceCategory)
- `Master` — профили мастеров с M2M к услугам; поля: specialization, experience, education,
  work_experience, approach, reviews_text, rating, **`yclients_staff_id`** (для нативной
  записи через AI Concierge → YClients API)
- `Bundle` / `BundleItem` — пакеты услуг; Bundle имеет total_price(), total_duration_min();
  BundleItem имеет quantity, parallel_group, gap_after_min
- `BundleRequest` — заявки на пакеты (client_name, client_phone, comment, is_processed)
- `Promotion` — скидки с промокодами; features (JSON), options (M2M), discount_percent,
  promo_code, starts_at, ends_at
- `Review` — отзывы клиентов (author_name, text, rating 1-5, get_initial_letter())
- `BookingRequest` — заявки через форму-мастер ИЛИ MAX-бот ИЛИ YClients-админку;
  `source` ∈ {`wizard`, `bot_max`, `yclients_admin`, `other`}, `bot_user` FK SET_NULL
- `SiteSettings` — глобальные настройки (телефон, соцсети JSON, способы оплаты JSON, данные
  YClients, ссылки на карты, `notification_emails` — email-адреса для уведомлений о заявках
  wizard, по одному на строку, `online_payment_enabled`)

**Бот-модели (для MAX-бота):**
- `BotUser` — персонализация диалога: max_user_id (unique), display_name (из MAX),
  client_name (как назвался боту), client_phone, **chat_id** (для проактивных reminder'ов),
  context (JSONField — `services_viewed`, `faqs_viewed`, `bookings_count`,
  `last_followup_sent_at`, `last_repeat_offer_at`), first_seen / last_seen
- `HelpArticle` — FAQ-статьи бота (отдельно от FAQ по услугам); question, answer, order,
  is_active. Используется RAG поверх chromadb embeddings в MCP-сервере.
- `BotInquiry` — вопрос клиента, на который AI не нашёл ответ → передан менеджеру.
  Workflow: AI создаёт inquiry → клиенту «Передал менеджеру» → менеджер видит в админке →
  пишет `reply_text` → action «📤 Отправить ответ» → bot.send_message + `sent_to_max=True`.
- `Conversation` (Phase 2.3) — диалог клиент-AI. UUID PK, FK на BotUser. Поля: `is_active`
  (одна активная на BotUser; закрывается при /start или auto-cleanup ≥ 7 дней),
  `outcome` ∈ {success, abandoned, redirected, error}, `last_message_at`, `deleted_at`.
- `Message` (Phase 2.3) — одно сообщение в Conversation. UUID PK. Поля: `role`
  (user/assistant/tool/system), `content`, `action_type` (show_masters/slots/...),
  `action_data` (JSON для рендера UI), `tool_call` (raw OpenAI), `tool_call_id`,
  телеметрия — `tokens_in`/`tokens_out`/`latency_ms`.
- `BookingReminder` (N2) — T-24h + T-2h напоминания о YClients-записи. UUID PK.
  `kind` ∈ {day_before, two_hours}, `status` ∈ {pending, sent_no_reply, sent, confirmed,
  reschedule, cancelled, escalated, failed}; `unique_together(yclients_record_id, kind)` —
  идемпотентность. Создаётся в `execute_confirm_booking` (после YClients-записи) или
  YClients-webhook'ом для записей через админку.

### agents (AI-автоматизация)
Маркетинговая и аналитическая автоматизация через OpenAI + Celery.

**Основные модели (все в `agents/models.py`):**
- `AgentTask` — выполнение AI-задач; типы: analytics, offers, offer_packages, smm_growth,
  seo_landing, analytics_budget, seo_growth, trend_scout; статусы: pending, running, done, error
- `AgentReport` — OneToOne сводка по AgentTask (recommendations JSON)
- `ContentPlan` — SMM контент-календарь; платформы: VK, Instagram, Telegram;
  типы постов: post, story, reel
- `DailyMetric` — дневные агрегаты (total_requests, processed, top_services JSON,
  masters_load JSON, agent_runs JSON, total_duration, error_count)
- `RetentionSnapshot` — недельные метрики удержания (новые/возвращающиеся клиенты,
  retention 4w/12w; собираются `collect_retention_metrics` ежедневно в 11:00 МСК)
- `TrendSnapshot` — снимки трендовых тем из внешних источников (для TrendScout агента)

**SEO модели (также в `agents/models.py`):**
- `SeoKeywordCluster` — кластер ключевых запросов; name, service_slug, keywords (JSON),
  target_url, is_active, geo, service_category (FK)
- `SeoRankSnapshot` — еженедельные метрики Яндекс.Вебмастера; week_start, page_url,
  query, clicks, impressions, ctr, avg_position, source;
  unique_together (week_start, page_url, query)
- `SeoClusterSnapshot` — агрегаты по кластерам (clicks/impressions/avg_position/ctr на week_start)
- `LandingPage` — SEO-посадочная страница; status: draft/review/published/rejected
  (default='draft'); cluster (FK), slug, meta_title, meta_description, h1, blocks (JSON),
  generated_by_agent, moderated_by (FK User), published_at
- `SeoTask` — задача для SEO-специалиста; task_type: create_landing/update_meta/add_faq/
  fix_technical/rewrite_cta/add_content_block; priority: high/medium/low;
  status: open/in_progress/done; `escalation_count` для дедупликации
- `AgentRecommendationOutcome` — lifecycle рекомендаций; new/accepted/rejected/done;
  FK на AgentReport, decided_by (FK User), body (JSON)
- `WeeklyBacklog` — еженедельный бэклог SupervisorAgent; week_start (unique), raw_text,
  items (JSON)

**Расписание Celery beat (MSK, см. `settings/base.py::CELERY_BEAT_SCHEDULE`):**
- `daily-rank-snapshots-10am-msk` → `agents.tasks.collect_rank_snapshots` (ежедневно 10:00)
- `daily-landing-qc-9am-msk` → `agents.tasks.run_landing_qc` (ежедневно 09:00)
- `daily-agents-12pm-msk` → `agents.tasks.run_daily_agents` (ежедневно 12:00)
- `daily-retention-metrics-11am-msk` → `agents.tasks.collect_retention_metrics` (11:00)
- `weekly-trend-scout-monday-1030-msk` → `agents.tasks.collect_trends` (Пн 10:30)
- `weekly-agents-monday-11am-msk` → `agents.tasks.run_weekly_agents` (Пн 11:00)
- `weekly-generate-landings-monday-0100-msk` → `agents.tasks.generate_missing_landings`
  (Пн 01:00 — ночной слот)
- `daily-close-stale-conversations-3am-msk` → `services_app.tasks.close_stale_conversations`
  (закрытие AI-диалогов без активности ≥ 7 дней)
- `weekly-analyze-failed-conversations-monday-6am-msk` →
  `services_app.tasks.analyze_failed_conversations` (LLM meta-analysis 20 неудачных
  диалогов → паттерны → Telegram админу)
- `maxbot-send-due-reminders-every-15min` → `maxbot.tasks.send_due_reminders` (каждые 15 мин)
- `maxbot-escalate-stale-reminders-hourly` → `maxbot.tasks.escalate_stale_reminders`
- `maxbot-post-visit-followups-1900-msk` → `maxbot.tasks.send_post_visit_followups` (T07)
- `maxbot-repeat-offers-monday-1200-msk` → `maxbot.tasks.send_repeat_offers` (Пн 12:00, T07)

### website
Frontend views: главная, каталог услуг, детальная страница услуги, мастера, форма-мастер записи, контакты, акции, пакеты. Все модели данных живут в `services_app`.

### booking
Минимальный — placeholder `booking()` view. Booking API endpoint'ы живут в `website/views.py`.

### notifications (P2 2026-04-23)
Python-пакет (не Django-app, нет моделей) с централизованными уведомлениями:
- `send_notification_telegram(text)` — Telegram, читает `TELEGRAM_BOT_TOKEN/CHAT_ID` из env
- `send_notification_email(subject, msg)` — email, получатели из `SiteSettings.notification_emails` → fallback на `ADMIN_NOTIFICATION_EMAIL`
- `get_notification_recipients()` — lazy-импортит `SiteSettings` (единственная зависимость от services_app)
- `send_certificate_email(order, cert, pdf_bytes=None)` — письмо покупателю после оплаты сертификата

Импорт: `from notifications import send_notification_telegram, send_certificate_email, ...`.
Раньше жил как `website/notifications.py` — вынесен в отдельный пакет чтобы разорвать циклы `payments ↔ website`, `services_app ↔ website`, `website ↔ agents` (4 пары из ln-644 аудита).

### payments
YooKassa-интеграция + админ-акции для Order/GiftCertificate:
- `payments/services.py::PaymentService.create_for_order(order)` — создание YooKassa-платежа
- `payments/booking_service.py::YClientsBookingService.create_record(order)` — shared-service создания YClients-записи
- `payments/views.py::yookassa_webhook` — приём callback'ов, verify-через-API, `transaction.atomic + on_commit` для enqueue fulfillment task
- `payments/tasks.py` — Celery-задачи `fulfill_paid_order/certificate/bundle` с idempotency через `yclients_record_id`
- `payments/admin.py` (новый в P2 2026-04-23) — subclass'ы `OrderAdmin` и `GiftCertificateAdmin` с payment-actions (recreate payment link, mark as paid, resend certificate email). Паттерн unregister+register: `services_app/admin.py` регистрирует базовые admin'ы, `payments/admin.py` их перерегистрирует с payment-actions. Разрывает цикл `services_app → payments` (ln-644 H1, H2).
- `payments/ip_whitelist.py` — YooKassa IP-subnet check, отключаемо через `YOOKASSA_WEBHOOK_STRICT_IP=0`.

### maxbot (Фаза 1 + 2 + 2.3 + 2.4)
**Standalone async-процесс** (НЕ Django-app) для бота в мессенджере MAX
(`maxapi[webhook]==1.0.0`). Запускается отдельным systemd-юнитом
`formula-tela-maxbot.service` рядом с gunicorn'ом.

**Архитектурные слои:**
1. **handlers/** (9 router'ов) — приём событий из MAX SDK, диспетчеризация по callback'ам
2. **AI Concierge** (Phase 2.3) — LLM-orchestrated chat с OpenAI tool-use
3. **MCP-клиент** — stdio-подключение к `services/formulatela_mcp` для RAG-поиска FAQ
4. **Reminders/Tasks** — Celery-задачи для проактивных уведомлений
5. **YClients integration** — webhook от админки + native booking через AI flow

**Список router'ов (порядок регистрации в `handlers/__init__.py::get_routers()`):**
```
start          → /start, bot_started, cb:back
services       → cb:menu:services, cb:cat:*, cb:svc:* (выбор услуги)
booking        → FSM BookingStates: awaiting_name → phone → confirm
contacts       → cb:menu:contacts (ClipboardButton для tel)
faq            → cb:menu:faq, cb:faq:* (HelpArticle)
reminders      → cb:rem:confirm/reschedule/cancel:* (N2 reminder reply)
ai_callbacks   → cb:ai:pick_master/pick_service/pick_slot/answer/confirm/cancel/
                  suggest_date/suggest_master/edit:*
ai_assistant   → @router.message_created() — ловит всё free-text → AIConcierge.send_message
fallback       → системные сообщения без sender'а (резерв)
```

**Phase 2.3 — AI Concierge (OpenAI tool-use):**
`maxbot.ai_concierge.send_message()` — главный pipeline на каждый user-message:
1. Resolve/create active `Conversation` (один на BotUser)
2. Save user `Message` (UUID PK)
3. `build_master_context()` → топ-N мастеров с реальными ID (anti-hallucination)
4. Load recent history (10 messages exclude user-just-saved)
5. `render_system_prompt(today, client_name, bookings_count, master_context, last_visits)`
6. `openai_client.chat.completions.create(model="gpt-4o-mini", tools=TOOL_DEFINITIONS)`
7. Parse completion → text content + optional `tool_call` → `dispatch_tool_call()` →
   ActionResult(action_type, action_data)
8. Enrich через YClients (slots/bookings) — `ai_yclients.enrich_show_*`
9. Save assistant `Message` с `action_type/action_data/tool_call/tokens/latency_ms`
10. Return `ChatResponseDTO(conversation_id, content, action_type, action_data)`

**6 OpenAI tools** (`maxbot/ai_tools.py::TOOL_DEFINITIONS`):
- `show_masters` — рекомендация мастеров (master_ids, match_scores, match_reasons,
  explanation, optional date)
- `show_slots` — свободные слоты (master_id, service_id, date, optional time_preference
  morning/afternoon/evening)
- `confirm_booking` — карточка подтверждения (master_id, service_id, datetime ISO 8601);
  **запись в YClients создаётся ТОЛЬКО после клика «Да»** на следующем шаге
- `show_my_bookings` — текущие записи клиента (filter: upcoming/past/all)
- `recommend_services` — подбор услуг по цели/пейну (goals из 12 slug'ов; Phase 2.4 T02)
- `ask_clarification` — уточняющий вопрос с predef options

`Service.goals` (Phase 2.4 T01): JSON-список slug'ов — relax, antistress, back_pain,
posture, recovery, tone, weight_loss, cellulite, lymph, beauty_face, hair_removal,
pregnancy_safe. Используется `recommend_services` для матчинга.

**Health screening (Phase 2.4 T03):** `Service.requires_health_check=True` +
`contraindications` — для опасных услуг (антицеллюлит, баночный, обёртывания, лимфодренаж,
лазер). AI перед `confirm_booking` задаёт screening-вопросы. Если клиент сообщил
противопоказание → запись переадресуется менеджеру через `BotInquiry` (не в YClients).

**Master criteria filtering (Phase 2.4 T06):** `build_master_context()` поддерживает
фильтрацию по дате (отбирает только мастеров со свободным временем в YClients
на эту дату).

**Returning customer (Phase 2.4 T05):** `personalization.get_client_history(bot_user)` →
`{bookings_count, last_visits[]}` подмешивается в system prompt.

**Voice examples (Phase 2.4 T04a):** `maxbot/voice_examples.py` — 30+ примеров
ответов в стиле Алины (живо, без канцелярита) для in-context learning.

**N2 Reminder system (`maxbot/tasks.py` + `reminders_factory.py`):**
- `create_reminders_for_booking()` создаёт 2 `BookingReminder` (T-24h DAY_BEFORE +
  T-2h TWO_HOURS) после успешного `yclients_record_id`
- `send_due_reminders` (Celery beat каждые 15 мин) шлёт PENDING reminder'ы.
  T-24h → 3 кнопки [✅ Подтверждаю / 🔄 Перенести / ❌ Отменить] → `SENT_NO_REPLY`.
  T-2h → текст без кнопок → `SENT`.
- `escalate_stale_reminders` (каждый час): если T-24h `SENT_NO_REPLY` и до визита < 12h —
  Telegram менеджеру с phone/имя/услуга, статус → `ESCALATED`
- Идемпотентность: `unique_together(yclients_record_id, kind)` + только PENDING обрабатываются
- handlers/reminders.py: `cb:rem:confirm` → `CONFIRMED`, `cb:rem:cancel` → `CANCELLED`,
  `cb:rem:reschedule` → `RESCHEDULE_REQUESTED` + Telegram менеджеру

**Post-visit follow-up (T07):**
- `send_post_visit_followups` (daily 19:00) — клиентам у которых вчера был визит,
  «как прошёл?». Idempotency через `bot_user.context["last_followup_sent_at"]`.
- `send_repeat_offers` (Mon 12:00) — клиентам с последним визитом 21-28 дней назад,
  «время повторить?». Rate limit: не чаще 1×/30 дней через `last_repeat_offer_at`.

**YClients webhook (`yclients_webhook.py`, YW1+YW2):**
POST `/api/yclients/webhook/` — приём событий когда администратор салона создаёт/
изменяет/отменяет запись через YClients-кабинет.
- `status=create`: ищет BotUser по нормализованному phone, при match создаёт
  `BookingRequest(source='yclients_admin', bot_user=...)` + 2 `BookingReminder` +
  приветственное сообщение в личку
- `status=update`: пересоздаёт reminder'ы с новой датой + уведомляет клиента о переносе
- `status=delete`: помечает reminder'ы CANCELLED + уведомляет клиента об отмене
- ВСЕГДА возвращает 200 (даже на ошибку) — иначе YClients ретраит бесконечно
- Идемпотентность через `unique_together(yclients_record_id, kind)`

**Conversation lifecycle (Phase 1 Learning Roadmap):**
- `Conversation.outcome` ∈ {success, abandoned, redirected, error} — заполняется
  при закрытии. Пустое = диалог активен.
- `services_app.tasks.close_stale_conversations` (daily 03:00 МСК) — UPDATE-query,
  закрывает диалоги без активности ≥ 7 дней с `outcome=abandoned`
- `services_app.tasks.analyze_failed_conversations` (Mon 06:00 МСК, Phase 2 Learning):
  LLM meta-analysis 20 последних неудачных диалогов → паттерны + prompt_additions →
  Telegram админу

**MCP-клиент (Phase 2.2):** `maxbot/mcp_client.py::MaxbotMCPClient` — singleton с
persistent stdio-сессией к `services/formulatela_mcp`. Eager-start на boot бота +
warmup `search_faq` (прогрев chromadb singleton). Lazy fallback при ошибке. Прогрев
response_cache в фоне после mcp-ready.

**Запуск локально:**
```bash
MAX_BOT_TOKEN=<token> MAX_BOT_MODE=polling python -m maxbot.main
```

**Prod-деплой:** `infra/README.md` (systemd unit, nginx location, `subscribe_webhook`).
Webhook: `https://formulatela58.ru/api/maxbot/webhook/` → 127.0.0.1:8003.
Защита через header `X-Max-Bot-Api-Secret` (env `MAX_WEBHOOK_SECRET`).

**Планы:**
- `docs/plans/maxbot-phase1.md` (15 задач, MVP)
- `docs/plans/maxbot-phase2-ai-mcp.md` — AI + MCP RAG
- `docs/plans/maxbot-phase2-research-T01.md` — research MCP/SDK особенностей
- `docs/plans/maxbot-phase2-native-booking.md` — нативная запись через YClients
- `docs/plans/maxbot-phase24-consultative.md` — Phase 2.4 (consultative AI)
- `docs/plans/maxbot-reminders.md` — N2 reminder system
- Review-отчёты T-06.5: `maxbot-phase1-review-{summary,code-reviewer,ln623,ln624}.md`

### services/formulatela_mcp (MCP-сервер)
Standalone Python-пакет — Model Context Protocol сервер для AI-помощника. Спавнится
maxbot'ом через stdio (см. `maxbot/mcp_client.py`).

**Tools (текущая версия):**
- `ping` → `"pong"` (smoke-test)
- `search_faq(query, k=3)` → top-k HelpArticle через chromadb embeddings
  (OpenAI text-embedding-3-small через `OPENAI_PROXY`)

**Зависимости:** `mcp[cli]>=2026.1.0`, `chromadb>=0.5`, `openai>=1.50`.
Django ORM подтягивается из родительского проекта (`django_bootstrap.py`).

**Тестирование:** `mcp dev python -m formulatela_mcp.main` (MCP Inspector в браузере)
или через Python-клиент (`tests/test_main.py`).

**Установка:** `cd services/formulatela_mcp && pip install -e .`

---

## URL-паттерны
- `/` — главная
- `/services/` — каталог услуг (все категории)
- `/uslugi/<slug>/` — детальная страница услуги (основная для SEO)
- `/service/<int:id>/` — старый маршрут по ID (301 редирект на slug)
- `/services/<int:category_id>/` — услуги по категории
- `/promotions/` — активные акции
- `/masters/` — профили мастеров
- `/contacts/` — контактная информация
- `/bundles/` — пакеты услуг
- `/admin/` — Django Admin
- `/robots.txt` — robots.txt (Disallow `/admin/`, `/api/`; ссылка на sitemap; Host)
- `/sitemap.xml` — динамический sitemap (static + services + bundles + categories +
  masters + published landings)
- `/<slug>/` — SEO-посадочная страница (только published, catch-all **последним** в urlpatterns)
- `/healthz/` — health check: проверяет БД (`connection.ensure_connection()`) и Redis
  (`cache.set(..., timeout=5)`); возвращает `{"status":"error","failed":[...]}` 503
  если упало, иначе `{"status":"ok"}`
- `/api/agents/health/` — мониторинг агентов: per-agent SLA, stuck_tasks, error_rate_24h →
  `{"status": "healthy|degraded|unhealthy", "agents": {...}}`

**Booking API (в `website/urls.py`):**
- `/api/booking/get_staff/` — мастера из YClients
- `/api/booking/available_dates/` — доступные даты записи
- `/api/booking/available_times/` — слоты по длительности сеанса
- `/api/booking/create/` — создание записи в YClients
- `/api/booking/service_options/` — варианты цен
- `/api/bundle/request/` — заявка на пакет
- `/api/wizard/categories/` — категории для формы-мастера
- `/api/wizard/categories/<id>/services/` — услуги в категории
- `/api/wizard/booking/` — бронирование через форму-мастер

**Payments (`payments/urls.py` под `/api/payments/`):**
- `/api/payments/yookassa/webhook/` — приём callback'ов YooKassa (verify + IP-whitelist +
  `transaction.atomic + on_commit` enqueue fulfillment task)
- `/payments/success/?order={number}` — страница после успешной оплаты
- `/payments/cancelled/` — страница при отмене

**MAX-бот webhook (отдельный процесс на 127.0.0.1:8003 за nginx):**
- `/api/maxbot/webhook/` — приём updates из MAX, защищён `X-Max-Bot-Api-Secret`
  (env `MAX_WEBHOOK_SECRET`)

**YClients webhook (приём событий из YClients-админки):**
- `/api/yclients/webhook/` — POST: на `create/update/delete` записи через админку →
  поиск BotUser по phone → BookingRequest(source=`yclients_admin`) + BookingReminder'ы +
  уведомление клиенту в MAX (см. `maxbot/yclients_webhook.py`)

---

## Запуск проекта

### Локальная разработка
```bash
cd mysite
python manage.py runserver
# Настройки выбираются автоматически через DJANGO_ENV или DJANGO_SETTINGS_MODULE
# По умолчанию: local.py (DEBUG=True, SQLite, ALLOWED_HOSTS=["*"])
```

### Docker (аналог продакшна)
```bash
docker-compose up
# PostgreSQL на 5432, Redis на 6379, Django на 8000
```

### Celery (обязателен для агентов)
```bash
cd mysite
celery -A mysite worker -l info   # в одном терминале
celery -A mysite beat -l info     # в другом терминале
```

### Миграции
```bash
cd mysite
python manage.py makemigrations
python manage.py migrate
```

### Управляющие команды
```bash
python manage.py import_price_list price_list.xlsx [--dry-run] [--no-photos]
python manage.py check_booking [--staff-id ID] [--yclients-service-id ID] [--date YYYY-MM-DD]
python manage.py check_metrika   # диагностика Яндекс.Метрики
python manage.py check_webmaster # диагностика Яндекс.Вебмастера
```

---

## Тесты
```bash
# Из корня репозитория (mysite/)
pytest

# Конфигурация pytest.ini:
# DJANGO_SETTINGS_MODULE = mysite.settings
# pythonpath = mysite
# testpaths = mysite/tests
# addopts = -q -m "not live"
# markers: live — тесты с реальным YClients API (исключены из CI)

# Запуск live-тестов вручную:
pytest mysite/tests/test_booking_live.py -v -s
```

Тестовые файлы в `mysite/tests/`. Используй `model-bakery` (`baker.make(...)`) для фикстур.

---

## Переменные окружения
Скопируй `.env.example` -> `.env`. Ключевые переменные:

**Django:**
- `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`
- `DJANGO_ENV` — выбирает файл настроек (production/staging/local)
- `DATABASE_URL` или `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`
- `REDIS_URL`
- `SITE_BASE_URL` — продакшн: `https://formulatela58.ru` (именно с «58», НЕ formulatela.ru)

**Уведомления:**
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- `ADMIN_NOTIFICATION_EMAIL`

**YClients:**
- `YCLIENTS_PARTNER_TOKEN`, `YCLIENTS_USER_TOKEN`, `YCLIENTS_COMPANY_ID`

**OpenAI / прокси (РФ):**
- `OPENAI_API_KEY`, `OPENAI_MODEL` (по умолчанию: gpt-4o-mini)
- `OPENAI_PROXY` — HTTP-прокси для OpenAI + Telegram API
  (`http://user:pass@host:port`), нужен на русских серверах где заблокированы
- `TELEGRAM_PROXY` — отдельный прокси только для Telegram (если не задан → `OPENAI_PROXY`)

**Аналитика:**
- `YANDEX_WEBMASTER_TOKEN`, `YANDEX_WEBMASTER_HOST_ID`
- `YANDEX_METRIKA_TOKEN`, `YANDEX_METRIKA_COUNTER_ID`

**Платежи (YooKassa):**
- `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY`
- `YOOKASSA_RETURN_URL` (обычно `https://formulatela58.ru/payments/success/?order={order_number}`)
- `YOOKASSA_WEBHOOK_STRICT_IP` — `1` (default) для проверки YooKassa IP-subnet, `0` в dev/CI

**MAX-бот:**
- `MAX_BOT_TOKEN` — токен бота из MAX для партнёров
- `MAX_BOT_MODE` — `polling` (dev) или `webhook` (prod)
- `MAX_WEBHOOK_HOST`, `MAX_WEBHOOK_PORT` (default 127.0.0.1:8003), `MAX_WEBHOOK_PATH`
- `MAX_WEBHOOK_SECRET` — заголовок `X-Max-Bot-Api-Secret`

---

## Окружения настроек
| Файл | Применение |
|------|-----------|
| `base.py` | Общий конфиг |
| `dev.py` | Настройки разработки |
| `local.py` | Локально: SQLite, DEBUG=True, ALLOWED_HOSTS=["*"] |
| `staging.py` | Staging-сервер |
| `production.py` | Продакшн PostgreSQL |

Настройки выбираются автоматически: `__init__.py` загружает `.env` через `python-dotenv` **до** чтения `DJANGO_ENV` (production -> staging -> local по умолчанию). Это гарантирует, что `.env` файл имеет приоритет над системным окружением.

---

## Templatetags

### `services_app/templatetags/service_extras.py`
- `option_label(opt)` — форматирует ServiceOption как "60 мин x 10 процедур — 14 000 руб. (1 400 руб./проц.)"
- `discount(price, percent)` — вычисляет цену со скидкой

### `agents/templatetags/landing_tags.py`
- `split_lines(value)` — разбивает строку по `\n`, убирает маркеры (•, -, *, 1., 2.)
- `slugify_to_title(value)` — slug → читаемый заголовок (`massazh-spiny` → `Massazh spiny`)

### `website/templatetags/faq_tags.py`
- `faq_items(content)` — парсит контент блока FAQ (пары Q&A, разделённые `---`)

### `website/templatetags/media_tags.py`
- `get_media_after(media_by_position, block_order)` — возвращает медиа для вставки после блока на мобильных

### `website/templatetags/social_tags.py`
- `dictget(d, key)` — безопасный доступ к словарю в шаблонах
- `pluralize_ru(value, variants)` — склонение по-русски: `{{ count|pluralize_ru:"услуга,услуги,услуг" }}`

---

## Соглашения по коду
- Русский язык (`LANGUAGE_CODE = "ru"`, `USE_I18N = True`)
- Шаблоны на Django Template Language; templatetags в `services_app/templatetags/` и `website/templatetags/`
- В Admin используется `filter_horizontal` для M2M-полей (related_services, options)
- URL на основе slug для SEO; 301 редирект со старых ID-маршрутов на slug
- `heading_level` в ServiceBlock управляет h1/h2/h3 в шаблонах
- Schema.org разметка (Service, FAQPage, BreadcrumbList) встроена в шаблон детальной страницы услуги
- CSP middleware включён — никаких инлайн-скриптов; разрешено: `'self'` + `https://w951024.yclients.com`
- Booking API views используют `@csrf_exempt` и возвращают JSON
- Активное использование `Prefetch` во views для оптимизации запросов
- **OpenAI клиент централизован**: все агенты импортируют `get_openai_client()` из `agents/agents/__init__.py` — не создавать `OpenAI()` напрямую. Клиент автоматически поднимает HTTP-прокси из `OPENAI_PROXY` (нужно на русских серверах)
- Telegram API (`agents/telegram.py`) также использует `OPENAI_PROXY`/`TELEGRAM_PROXY` т.к. api.telegram.org заблокирован в РФ
- Sitemap — через `django.contrib.sitemaps` (4 sitemap: static/services/categories/landings), классы в `mysite/website/sitemaps.py`
- **YClientsAPI — singleton через `lru_cache`** (P1 2026-04-23): `get_yclients_api()` возвращает кэшированный экземпляр с переиспользуемой `requests.Session` + urllib3 `Retry` adapter (3 попытки, backoff 0.5s, для 502/503/504). В тестах `conftest.py::_clear_yclients_singleton` сбрасывает кэш. Мокать HTTP через `patch("requests.Session.request", ...)`, не `requests.request`.
- **Payment webhook = atomic + on_commit** (P1 2026-04-23): `payments/views.py::_handle_succeeded` обернут в `transaction.atomic()`, enqueue fulfillment task — через `transaction.on_commit(lambda: task.delay(order.id))`. Защищает от потери задачи если save() откатится. В тестах используй `django_capture_on_commit_callbacks(execute=True)` или фикстуру `post_webhook` (в test_webhook.py).
- **Celery settings (base.py)** (P1 2026-04-23): `CELERY_TASK_ACKS_LATE=True`, `CELERY_TASK_REJECT_ON_WORKER_LOST=True`, `CELERY_WORKER_PREFETCH_MULTIPLIER=1`, `CELERY_BROKER_TRANSPORT_OPTIONS={"visibility_timeout": 3600}`, `CELERY_TASK_SOFT_TIME_LIMIT=1800`, `CELERY_TASK_TIME_LIMIT=1860`. Защита от тихой потери задач при деплое / OOM / SIGKILL.
- **Production fail-fast** (P0 2026-04-23): `settings/production.py` бросает `ImproperlyConfigured` на boot если отсутствуют `DJANGO_SECRET_KEY`, `YCLIENTS_PARTNER_TOKEN`, `YCLIENTS_USER_TOKEN`, `YCLIENTS_COMPANY_ID` (не `assert` — он гасится флагом `python -O`).
- **Ноль циклов между app'ами** (P2 2026-04-23): `services_app` не импортирует ни из `payments`, ни из `agents`, ни из `website`, ни из `notifications`. Все 8 циклических зависимостей из ln-644 аудита разорваны. Фичевые app → domain, domain ничего не знает о features.
- **MAX-бот = standalone process** — НЕ импортируется из Django web-процесса (gunicorn).
  Запускается отдельным systemd-юнитом `formula-tela-maxbot.service`. Web-процесс шлёт
  сообщения боту через `notifications.max_bot.send_max_message(chat_id, text, attachments)`
  (REST API без SDK), не через MAX SDK. YClients webhook (`/api/yclients/webhook/`)
  обрабатывается web-процессом, но бот-side-effects (отправка сообщений в личку)
  идут через `notifications.max_bot`.
- **AI Concierge — async-only** — `ai_concierge.send_message()` это `async def`, ORM
  через `@sync_to_async` wrapper'ы. Не вызывать из синхронного кода без `asyncio.run()`.
- **OpenAI client для бота** — `maxbot/llm.py::get_async_openai_client()` (async),
  отдельный от агентского `agents/agents/__init__.py::get_openai_client()` (sync).
  Оба читают `OPENAI_PROXY` из env.

---

## Архитектура агентов

### Поток данных
```
Внешние данные (YClients / Метрика / Вебмастер / VK Ads / Яндекс.Директ)
    |
    v
DailyMetric / SeoRankSnapshot (сохраняем в БД)
    |
    v
AgentTask создаётся (status=pending)
    |
    v
Celery worker забирает задачу -> запускает агента
    |
    v
Агент читает данные из БД -> формирует prompt -> GPT-4
    |
    v
AgentReport сохраняется (status=done, recommendations JSON)
    |
    v
Telegram уведомление администратору
```

### Типы AgentTask и их файлы
| task_type | файл | расписание (MSK) |
|---|---|---|
| analytics | `agents/agents/analytics.py` | ежедневно 12:00 (через SupervisorAgent) |
| analytics_budget | `agents/agents/analytics_budget.py` | ежедневно 12:00 (всегда) |
| offers | `agents/agents/offers.py` | ежедневно 12:00 (через SupervisorAgent) |
| seo_landing | `agents/agents/seo_landing.py` | понедельник 11:00 |
| seo_growth | `agents/agents/seo_growth.py` | понедельник 11:00 |
| smm_growth | `agents/agents/smm_growth.py` | понедельник 11:00 |
| offer_packages | `agents/agents/offer_packages.py` | понедельник 11:00 |
| trend_scout | `agents/agents/trend_scout.py` | понедельник 10:30 |
| (no task_type) | `agents/agents/seo_landing_qc.py` | ежедневно 09:00 |
| (no task_type) | `agents/agents/landing_generator.py` | понедельник 01:00 (generate_missing_landings) |

### Расписание (MSK, фиксировано через `crontab` в `CELERY_BEAT_SCHEDULE`)
```
03:00 ежедневно  → close_stale_conversations (cleanup AI-диалогов ≥ 7 дней)
06:00 понедельник → analyze_failed_conversations (LLM meta-analysis 20 неудачных диалогов)
09:00 ежедневно  → run_landing_qc (QC опубликованных лендингов)
10:00 ежедневно  → collect_rank_snapshots (Вебмастер → SeoClusterSnapshot → analyze_rank_changes)
10:30 понедельник → collect_trends (TrendScout)
11:00 ежедневно  → collect_retention_metrics (RetentionSnapshot)
11:00 понедельник → run_weekly_agents (OfferPackages → SMMGrowth → SEOLanding → SeoGrowth → Supervisor.weekly_run)
12:00 ежедневно  → run_daily_agents (Supervisor.decide → Analytics/Offers → AnalyticsBudget)
01:00 понедельник → generate_missing_landings (макс. 3/запуск)
*/15 мин          → maxbot.send_due_reminders (N2)
:15 каждый час   → maxbot.escalate_stale_reminders (N2)
19:00 ежедневно  → maxbot.send_post_visit_followups (T07)
12:00 понедельник → maxbot.send_repeat_offers (T07)
```

### SupervisorAgent (оркестратор)
- `decide()` — LLM-роутер, определяет какие ежедневные агенты запустить (analytics если >1 день, offers по Пн/Чт или >3 дней)
- `run()` — запускает AnalyticsAgent и/или OfferAgent по результату decide()
- `weekly_run()` — собирает последние DONE-отчёты всех 6 агентов, синтезирует бэклог через GPT, шлёт Telegram с приоритизированными задачами

### Правила агентов — СТРОГО СОБЛЮДАТЬ
- Агенты **НИКОГДА** не публикуют контент автоматически
- `LandingPage` создаётся **только** со `status='draft'`
- Все рекомендации сохраняются в `AgentReport.recommendations` (JSON)
- Telegram-уведомление — финальный шаг **любого** агента
- Агент не выдумывает цены и факты — только данные из БД
- VK Ads входит в `AnalyticsBudgetAgent` как 3-й канал (не отдельный агент)

---

## Платежи (YooKassa)

Приложение `mysite/payments/` — онлайн-оплата услуг через YooKassa +
синхронное создание записи в YClients для офлайн-способов.

### Flow

```
POST /api/services/order/                  (website/views.py::api_service_order_create)
   │ payload: service_option_id, staff_id, date/time, client_*, payment_method
   │ DRF-валидация (website/serializers.py::ServiceOrderCreateSerializer)
   │ idempotency через cache (60с)
   ▼
Order(type=service, pending)
   │
   ├── payment_method=online + SiteSettings.online_payment_enabled
   │      PaymentService.create_for_order(order) → confirmation_url
   │      Order.payment_url / payment_id / payment_status=pending
   │      клиент → YooKassa checkout → 
   │              ├── succeeded → POST webhook
   │              │     /api/payments/yookassa/webhook/
   │              │     verify через find_payment (double-check)
   │              │     Order.payment_status=succeeded + paid_at=now
   │              │     fulfill_paid_order.delay(order.id)
   │              │     → YClientsBookingService.create_record (retry 5×)
   │              │     → Telegram админу
   │              └── canceled → Order.payment_status=canceled + Telegram
   │
   └── payment_method=cash/card_offline
         YClientsBookingService.create_record(order) СРАЗУ
         → yclients_record_id в ответе + Telegram
```

### Компоненты

| Файл | Что |
|---|---|
| `payments/yookassa_client.py` | Тонкий wrapper над yookassa SDK, возвращает dict'ы (не SDK-типы) |
| `payments/services.py::PaymentService` | `create_for_order(order)` → YooKassa payment, persists payment_id/url/status |
| `payments/booking_service.py::YClientsBookingService` | Shared service: `create_record(order)` идемпотентный, пишет `yclients_record_id` |
| `payments/tasks.py::fulfill_paid_order` | Celery task: `bind=True, max_retries=5, retry_backoff`, `ignore_result=True` |
| `payments/views.py::yookassa_webhook` | POST webhook: IP-whitelist + verify + роутинг succeeded/canceled |
| `payments/ip_whitelist.py` | 7 подсетей YooKassa, `@yookassa_ip_only` декоратор, `YOOKASSA_WEBHOOK_STRICT_IP` |
| `payments/exceptions.py` | `PaymentError` / `PaymentConfigError` / `PaymentClientError` / `BookingError` / `BookingValidationError` / `BookingClientError` |

### Feature flag

`SiteSettings.online_payment_enabled = False` по умолчанию. Редактируется через
Django Admin (`/admin/services_app/sitesettings/`). Когда `False`:
- Radio «Оплатить онлайн» в модалке записи **скрыт** на фронте
- Попытка `payment_method=online` в API → 400 `online_payment_disabled`
- Офлайн-способы (cash/card_offline) работают всегда

### Env

```
YOOKASSA_SHOP_ID=<из личного кабинета YooKassa>
YOOKASSA_SECRET_KEY=<оттуда же>
YOOKASSA_RETURN_URL=https://formulatela58.ru/payments/success/?order={order_number}
YOOKASSA_WEBHOOK_STRICT_IP=1   # 0 чтобы выключить IP-проверку в dev/CI
```

### Правила — СТРОГО СОБЛЮДАТЬ
- **Offline flow не создаёт платежи в YooKassa** — только Order + YClients-запись + Telegram
- **`order.number` — idempotence_key** для YooKassa Payment.create (защита от дублей)
- **Webhook всегда отвечает 200** (даже unknown order / already succeeded) — иначе YooKassa спамит retry
- **Fulfillment идемпотентен через `yclients_record_id`** — повторная доставка webhook не создаст запись второй раз
- **Чеки 54-ФЗ сейчас НЕ выдаются** — отдельная задача FT-13 (требует выбора ОФД)
- **Рефанды — через личный кабинет YooKassa** (не через админку) — FT-14

---

## Архитектура AI Concierge (Phase 2.3+2.4)

### Поток данных одного user-message
```
MAX webhook → handlers/ai_assistant.py::on_free_text
    │
    ▼
ai_concierge.send_message(bot_user, message_text)
    ├── _resolve_conversation(bot_user)  ← active OR new
    ├── _save_message(role=user)
    ├── build_master_context()  ← Top-N мастеров с реальными ID + опц. фильтр по дате
    ├── _load_recent_history(limit=10, exclude=user_msg.id)
    ├── personalization.get_client_history(bot_user)  ← bookings_count, last_visits[]
    ├── render_system_prompt(today, client_name, master_context, last_visits, ...)
    ├── _compose_messages(system + history + user_text)
    ├── openai.chat.completions.create(model="gpt-4o-mini", tools=TOOL_DEFINITIONS) ← async
    ├── _parse_completion → (content, tool_call_raw, action_type, action_data)
    │       └── dispatch_tool_call(tool_call, master_context) → ActionResult
    ├── enrich через ai_yclients (slots/bookings/masters_for_date)
    ├── _save_message(role=assistant, action_type, action_data, tool_call,
    │                  tokens_in/out, latency_ms)
    └── return ChatResponseDTO
        │
        ▼
ai_ui.render(action_type, action_data) → text + InlineKeyboard
        │
        ▼
bot.send_message(chat_id, text, attachments=[keyboard])
```

При клике на кнопку (cb:ai:pick_master/pick_slot/confirm/...) — handler в
`ai_callbacks.py` обновляет conversation state и вызывает `ai_concierge.send_message()`
с шаблонным сообщением, либо напрямую `ai_action_service.execute_*()` для финальных
действий (создание YClients-записи, BotInquiry, и т.д.).

### Правила AI Concierge — СТРОГО СОБЛЮДАТЬ
- **НЕ выдумывать `master_id` и `service_id`** — только из MasterContext (передаётся
  в system prompt). Anti-hallucination через явный список доступных ID.
- **Two-step booking**: tool `confirm_booking` НЕ создаёт YClients-запись.
  Запись создаётся только после клика «✅ Да» на следующем шаге → `execute_confirm_booking`
- **One tool_call per turn** — наш flow одношаговый. Если LLM эмиттит несколько
  tool_calls, берём первый (см. `_parse_completion`).
- **Health screening для опасных услуг**: если `Service.requires_health_check=True`,
  AI обязан задать screening-вопросы перед confirm_booking. При проблеме →
  переадресация менеджеру через BotInquiry, не запись в YClients.
- **action_data обогащается через YClients** до сохранения в Message — slots/bookings
  должны быть готовы для рендера UI без дополнительных запросов в callback handler'ах.
- **Conversation outcome** — заполняется при закрытии (success/abandoned/redirected/error).
  Активные диалоги имеют пустой outcome.
- **Telemetry obligatory**: `tokens_in/out/latency_ms` пишутся в каждый assistant Message
  для observability (пайплайн test_phase23_ai_concierge.py проверяет).
- **MCP-клиент = singleton** — `MaxbotMCPClient.instance()`. Не пересоздавать subprocess
  на каждый запрос; `ensure_started()` идемпотентен.

### Правила N2 Reminder system
- **Идемпотентность через `unique_together(yclients_record_id, kind)`** — повторный
  YClients webhook не создаст 2-х reminder'ов
- **Только PENDING обрабатываются** в `send_due_reminders` — SENT_NO_REPLY/SENT не
  пытаемся пересылать (страховка от дублей при ретрае Celery)
- **Status flow строгий**:
  PENDING → SENT_NO_REPLY (T-24h без ответа) → CONFIRMED|RESCHEDULE_REQUESTED|CANCELLED|ESCALATED
  PENDING → SENT (T-2h без кнопок, конечный)
- **Эскалация только для `kind=DAY_BEFORE` + `status=SENT_NO_REPLY` + `visit_at <= now+12h`** —
  T-2h не эскалируем (поздно)

---

## Архитектурные решения и причины
| Решение | Причина |
|---|---|
| SQLite локально / PostgreSQL прод | Скорость локальной разработки без Docker |
| Все SEO модели в agents/models.py | Единая схема, один app, без дублирования |
| VK Ads -> в AnalyticsBudgetAgent | Один промпт видит все каналы -> лучше сравнение CPL/ROMI |
| LandingPage.status = 'draft' по умолчанию | Человек проверяет перед публикацией |
| @csrf_exempt на booking API | Внешние вызовы от YClients-виджета |
| Prefetch в views | Предотвращение N+1 запросов |
| WAF bypass headers для YClients | Без них возвращается 403 |
| Slug-based URL везде | SEO-приоритет; ID-based -> 301 редирект |
| Django>=5.2,<6.0 пин в requirements | Предотвращение ломающего апгрейда |
| .env загружается до DJANGO_ENV | Гарантия что .env имеет приоритет над systemd env |
| SupervisorAgent как LLM-роутер | Автоматический выбор нужных ежедневных агентов по контексту |
| 3-уровневое расписание (7/8/9) | Данные собираются до запуска агентов |
| Wizard (`#bookingWizard`) ≠ YClients | Форма «Записаться онлайн» и CTA создают `BookingRequest` + Telegram/email, но **не** вызывают YClients. Мастер/дата/время в ней не выбираются — это «заявка на перезвон». Полноценное бронирование — только через форму на странице услуги (`/api/booking/create/`) |
| `notification_emails` в `SiteSettings` | Список email-ов для уведомлений wizard редактируется через Django Admin (`/admin/services_app/sitesettings/`), а не через `.env` — чтобы менеджер мог добавлять адреса без деплоя. Fallback на `ADMIN_NOTIFICATION_EMAIL` из окружения |

---

## Запрещённые действия (без явного разрешения)
- Не изменяй существующие миграции — только создавай новые
- Не удаляй поля моделей — только помечай как deprecated
- Не трогай `services_app/migrations/` без явной просьбы
- Не добавляй инлайн-скрипты в шаблоны (CSP заблокирует)
- Не публикуй `LandingPage` автоматически (только draft)
- Не коммить `.env` и медиафайлы в git
- Не используй ID-based URL — только slug-based
- Не создавай новые ветки без явной просьбы

---

## Git workflow
```bash
# Рабочая ветка
git checkout dev

# Перед началом каждой сессии
git pull origin dev

# Новые ветки — только по явной просьбе
```

### Prod deploy — ТОЛЬКО через GitHub PR (не локальный merge)
После инцидента 2026-04-23 где я сделал локальный `git merge dev → main + push origin main` вместо PR через UI, **правило**: prod-деплой идёт через Pull Request `dev → main` на GitHub. Это даёт:
- Diff-review в UI (видно что именно улетит в прод)
- Approval flow
- Автоматический запуск CI + deploy workflow связанных с PR merge
- Историю PR-ов в репо (timeline релизов)

### Feature PRs — push ВСЕ коммиты до merge
После инцидента 2026-04-23 где PR #78 был смержен когда в ветке был только 1 коммит, а ещё 2 запушил ПОСЛЕ merge — они остались висеть в remote-ветке, в dev не попали, потратил 2 часа на диагностику. **Правило**: перед кликом "Merge" на PR дождаться что **все намеченные коммиты запушены**. GitHub merge'ит snapshot на момент клика, последующие push в ту же ветку не подхватываются.

---

## Типичные ошибки
- Всегда запускай `makemigrations` + `migrate` после изменения моделей
- `ServiceMedia.video_file` хранит загруженное видео; большие файлы в .gitignore
- Контент блока `ServiceBlock` типа FAQ парсится `faq_tags.py` (пары Q&A через `---`)
- `related_services` в Service — self-referential M2M, используй `filter_horizontal` в admin
- Статические файлы: запускай `collectstatic` перед деплоем
- CSP блокирует инлайн-скрипты — используй внешние JS-файлы; `'unsafe-inline'` разрешён только для стилей
- Celery workers должны быть запущены для задач агентов; beat scheduler обязателен для периодических задач
- YClients API требует WAF-bypass заголовки (User-Agent + X-Partner-Id) чтобы избежать 403

---

## Быстрый справочник команд

### Makefile (рекомендуемый способ)
```bash
make db              # PostgreSQL + Redis в фоне
make db-stop         # Остановить PostgreSQL + Redis
make run             # Django dev server (требует make db)
make migrate         # Применить миграции
make makemigrations  # Создать миграции
make shell           # Django shell
make docker          # Весь стек в Docker (db + redis + web)
make logs            # Логи контейнеров БД и Redis
make psql            # psql в контейнере БД
make worker          # Celery worker (локально)
make beat            # Celery beat планировщик
make agent-analytics # Запустить Analytics Agent вручную
make agent-offers    # Запустить Offer Agent вручную
```

### Ручные команды
```bash
# Запуск локально (без Makefile)
cd mysite && python manage.py runserver

# После изменения моделей
python manage.py makemigrations && python manage.py migrate

# Тесты
pytest                                              # все (кроме live)
pytest mysite/tests/test_booking_live.py -v -s      # live-тесты с реальным YClients API

# Проверка что ничего не сломано
python manage.py check
```

---

## CI/CD
- **CI** (`.github/workflows/ci.yml`): pytest на Python 3.12, push/PR в dev/main, API ключи заглушены
- **Deploy** (`.github/workflows/deploy.yml`): push в main → SSH deploy на продакшн, бэкап PostgreSQL перед deploy, восстановление .env после git pull
- **Deploy staging** (`.github/workflows/deploy-staging.yml`): staging-деплой

---

## Текущее состояние проекта
<!-- Обновляй этот раздел в конце каждой рабочей сессии! -->

### Сделано

#### Ядро (services_app + website + booking)
- Полный каталог услуг с SEO (slug-based URL, Schema.org, BreadcrumbList)
- Форма-мастер записи через YClients API с WAF bypass
- Профили мастеров, пакеты услуг, акции с промокодами
- Meta description override через `{% block description %}` на страницах услуг
- `robots.txt` и динамический `sitemap.xml` (django.contrib.sitemaps, 4 sitemap-класса в `website/sitemaps.py`)

#### Интеграции (agents/integrations/)
- YClients интеграция с WAF bypass
- Yandex.Webmaster (yandex_webmaster.py): get_query_stats(), get_page_stats() (graceful wrappers, 5 тестов)
- Yandex.Metrika (yandex_metrika.py): get_organic_sessions(), get_page_behavior() (graceful wrappers, 9 тестов)
- VK Ads (vk_ads.py)
- Yandex.Direct (yandex_direct.py)
- TechnicalSEOWatchdog (site_crawler.py): проверка страниц, sitemap, get_or_create SeoTask, management-команда check_crawler, 25 тестов

#### SEO система
- SEO модели в agents/models.py: SeoKeywordCluster (с geo, service_category), SeoRankSnapshot, LandingPage, SeoTask, SeoClusterSnapshot
- SEO Admin: 4 ModelAdmin (publish actions, read-only snapshots, priority badges)
- seed_seo_clusters: 13 кластеров из семантического ядра v2 (Wordstat Пенза, февраль 2026)
- collect_rank_snapshots: Celery-таск (ежедневно 07:00), Вебмастер → агрегация по кластерам → SeoClusterSnapshot
- analyze_rank_changes: пороги -20% кликов / 3 позиции, создаёт SeoTask + шлёт Telegram, 18 тестов
- Telegram-уведомления: send_seo_alert(), notify_new_landing(), send_weekly_seo_report() (19 тестов)

#### Landing page система
- LandingPageGenerator (agents/agents/landing_generator.py): generate_landing() + generate_from_markdown(); admin action «Сгенерировать из маркдауна»; 33 теста
- Landing page view + URL + шаблон (agents/views.py, agents/landing_page.html): hero, intro, how_it_works, who_is_it_for, contraindications, results, CTA, FAQ-аккордеон, internal_links; 27 тестов
- CTA-кнопки на лендингах открывают ту же модалку записи что и остальные страницы

#### AI-агенты (все реализованы)
- **AnalyticsAgent** (agents/agents/analytics.py) — ежедневная аналитика
- **AnalyticsBudgetAgent** (agents/agents/analytics_budget.py) — бюджетная аналитика (Метрика + Директ + VK Ads)
- **OfferAgent** (agents/agents/offers.py) — генерация акций
- **OfferPackagesAgent** (agents/agents/offer_packages.py) — генерация пакетов
- **SMMGrowthAgent** (agents/agents/smm_growth.py) — SMM контент-план
- **SEOLandingAgent** (agents/agents/seo_landing.py) — аудит лендингов, детекция WoW click drops
- **SupervisorAgent** (agents/agents/supervisor.py) — оркестратор: decide() для ежедневных агентов, weekly_run() для недельного бэклога

#### Инфраструктура
- Celery beat: 3 задачи (07:00 ежедневно, 09:00 ежедневно, 08:00 понедельник)
- Management commands: check_metrika, check_webmaster, check_booking, check_crawler, import_price_list, seed_seo_clusters
- Makefile с 12 целями для быстрого запуска
- CI/CD: GitHub Actions (тесты, deploy prod, deploy staging)
- Django>=5.2,<6.0 (пин для предотвращения ломающего апгрейда)
- Фикс последовательностей PostgreSQL (миграция 0034_fix_sequences)
- **Централизованный OpenAI клиент** (`agents/agents/__init__.py::get_openai_client()`) с поддержкой `OPENAI_PROXY`; все 8 агентов используют его
- **Proxy для Telegram API** в `agents/telegram.py` (РФ блокирует api.telegram.org)

#### Замыкание цикла агентов
- **OfferAgent → Promotion draft**: JSON mode + auto-create `Promotion(is_active=False)` черновики для модерации
- **ContentPlan dedupe**: SMMGrowthAgent удаляет старые автогенерированные записи перед `bulk_create`
- **LandingPage QC pipeline**: таск `generate_missing_landings` (воскресенье 22:00) — автогенерация лендингов для кластеров без страниц (макс. 3/запуск)

#### Надёжность агентов
- **Telegram ERROR алерты**: `send_agent_error_alert()` — уведомление в Telegram при ошибке агента (во всех 7 агентах + `_lifecycle.py`)
- **SeoTask эскалация**: повторные алерты обновляют существующую задачу (приоритет → HIGH, description обновляется, `escalation_count` инкрементируется)
- **SeoTask.escalation_count** — поле для отслеживания повторных алертов

#### Поведенческая аналитика
- **SEOLandingAgent + Метрика**: интеграция `get_page_behavior()` для топ-15 страниц по impressions (bounce_rate, time_on_page)
- GPT-промпт обогащён поведенческими правилами: bounce > 70% + time < 30s → score ≤ 2

#### Feedback loop
- **AgentRecommendationOutcome** модель: lifecycle рекомендаций (new → accepted/rejected → done), FK на AgentReport, Admin с `list_editable`
- **WeeklyBacklog** модель: персистенция результатов `SupervisorAgent.weekly_run()` (ранее только Telegram)
- **_outcomes.py** хелпер: `create_outcomes()` для создания Outcome из рекомендаций (подключён в 4 агентах)
- **SupervisorAgent feedback**: `weekly_run()` читает статистику Outcome за неделю, GPT учитывает feedback

#### Мониторинг
- **GET `/api/agents/health/`**: JSON endpoint — healthy/degraded/unhealthy, per-agent SLA, stuck_tasks, error_rate_24h
- **DailyMetric timing**: поля `agent_runs` (JSON), `total_duration`, `error_count` — заполняются из `run_daily_agents`

#### Audit remediation (2026-04-23 — сессия ln-640-pattern-evolution-auditor)
10 audit-отчётов в `audits/` (запускалось `/codebase-audit-suite:ln-640-pattern-evolution-auditor` + ln-641..647). Исходный weighted score 5.2/10, 42 finding (5 CRITICAL + 19 HIGH). Сделано P0+P1+P2:
- **P0 security**: ротация `DB_PASSWORD_STAGING` и `DB_PASSWORD` GitHub secrets (были пустые), `.env.example` очищен от live YOOKASSA key, `.gitignore` исправлен (`.env.*` → `.env.local`), создан `.dockerignore`, production.py fail-fast на missing env vars.
- **P1 reliability**: Celery `acks_late + reject_on_worker_lost + prefetch=1 + visibility_timeout=3600`; webhook `transaction.atomic + on_commit` для enqueue Celery task; YClients `requests.Session + Retry + lru_cache singleton`.
- **P1 CI/CD**: `pg_dump` hardening в deploy-staging.yml и deploy.yml — size-check ≥1KB + `exit 1` на fail (87 пустых staging backup удалены).
- **P2 architecture**: вынос `notifications/` в отдельный пакет, payment-actions перенесены в `payments/admin.py` — все 8 циклов между app'ами разорваны (ln-644 H1, H2, C1, C2, H3, H4).

Ожидаемый score после: ~8.2/10. PR #83 `dev → main` открыт, ждёт merge для деплоя на prod.

#### Audit P2-3 (2026-04-24): DRF output serializers для top-5 booking endpoints (PR #84)
- 5 output-сериалайзеров в `website/serializers.py` для wizard/services/staff/booking-create endpoint'ов
- Envelope (`success`/`data`/`count`) сохранён, фронт не трогали
- 6 contract-тестов с `assert set(keys) == {...}` ловят accidental field leak
- Закрыт ln-643 H1 (entity leakage)

#### Infra: nginx gzip (2026-04-24)
- `gzip_types` для CSS/JS/SVG/JSON в `/etc/nginx/nginx.conf` — раскомментировал дефолтный блок Debian
- Замеры: CSS −77..87%, JS −72..74%, SVG −55%
- Бэкап: `/etc/nginx/nginx.conf.bak.20260424_125403`
- ⚠ "зомби-gunicorn djangoProject" на :8000 оказался **активным Docker-backend для dev.gobeauty.site** — НЕ убивать (см. memory `reference_ssh_prod.md`)

#### MAX-бот Фаза 1 (2026-04-24/25, T-01..T-15)
MVP бота в мессенджере MAX для приёма заявок и FAQ. 14 коммитов (T-01..T-14a),
770 passed, 0 регрессий. 6 routers + 2 middleware, 2 новые модели + миграция 0057,
2-слойное code review (project + ln-623 + ln-624) с 6 fix'ов в T-06.5.

#### MAX-бот Фаза 2 — MCP/RAG (2026-04-26..27)
- **MCP-сервер** `services/formulatela_mcp/` — standalone Python-пакет с tool'ами
  `ping` + `search_faq(query, k)` через chromadb embeddings (OpenAI text-embedding-3-small)
- **MCP-клиент** `maxbot/mcp_client.py` — singleton с persistent stdio-сессией, eager
  start + warmup на boot бота (cold-start 1.4s spawn + 2.4s chromadb init)
- **Response cache + warmup** — `maxbot/response_cache.py` + `warmup.py`: фоновый прогрев
  топ-вопросов из popular_questions после mcp-ready, мгновенные ответы после рестарта
- Plan: `docs/plans/maxbot-phase2-ai-mcp.md`, research: `phase2-research-T01.md`

#### MAX-бот Фаза 2.3 — AI Concierge (OpenAI tool-use, 2026-04-28..29)
**Замена chat_rag на LLM с function calling.** Адаптация архитектуры из Ayla.
- 2 новые модели: **Conversation** (UUID PK, FK BotUser, is_active, outcome,
  last_message_at) + **Message** (UUID PK, role, content, action_type, action_data,
  tool_call, tokens_in/out, latency_ms). Миграции 0059, 0060.
- **6 OpenAI tools**: show_masters, show_slots, confirm_booking, show_my_bookings,
  recommend_services, ask_clarification (`maxbot/ai_tools.py::TOOL_DEFINITIONS`)
- **AIConcierge.send_message()** — главный pipeline (resolve conversation → save user msg →
  build_master_context → load history(10) → render_system_prompt → OpenAI completion с
  tools → dispatch_tool_call → enrich через YClients → save assistant msg)
- **Master.yclients_staff_id** — для нативной записи через AI flow
- **ai_action_service.py** — side-effects: `execute_confirm_booking()` создаёт
  BookingRequest + YClients-запись + 2 BookingReminder
- **ai_callbacks router**: 9 callback-handler'ов (cb:ai:pick_master/pick_service/
  pick_slot/answer/confirm/cancel/suggest_date/suggest_master/edit:*)
- **ai_yclients.py**: `enrich_show_masters/slots/my_bookings` — реальный fetch из YClients
  чтобы action_data содержали актуальные слоты/мастеров
- **Conversation.outcome** + `close_stale_conversations` (daily 03:00 МСК) — закрытие
  диалогов ≥ 7 дней без активности
- **Phase 2 Learning Roadmap**: `analyze_failed_conversations` (Mon 06:00 МСК) — LLM
  meta-analysis 20 неудачных → паттерны → Telegram админу
- E2E тесты: `test_phase23_e2e.py` (5 сценариев), модульные `test_phase23_*.py` (~10 файлов)

#### MAX-бот Фаза 2.4 — Consultative AI (T01..T07, 2026-04-29..30)
- **T01**: `Service.goals` JSON-поле + 12 goal-slug'ов (relax, antistress, back_pain,
  posture, recovery, tone, weight_loss, cellulite, lymph, beauty_face, hair_removal,
  pregnancy_safe). Миграция 0062, management `tag_services_goals`.
- **T02**: tool `recommend_services(goals, explanation)` + discovery flow когда клиент
  описал цель/пейн но не выбрал услугу
- **T03**: Health screening — `Service.requires_health_check` + `contraindications`.
  AI задаёт screening-вопросы перед confirm_booking для опасных услуг
  (антицеллюлит, обёртывания, лимфодренаж, лазер, баночный). При проблеме →
  переадресация менеджеру через BotInquiry, не запись в YClients. Миграция 0063.
- **T04a**: `voice_examples.py` — 30+ примеров ответов в стиле Алины (in-context learning)
- **T05**: Returning customer recognition — `personalization.get_client_history()` →
  `last_visits[]` + `bookings_count` подмешивается в system prompt
- **T06**: Master criteria filtering — `build_master_context(date=...)` отбирает только
  мастеров со свободным временем в YClients на эту дату
- **T07**: Post-visit follow-up — `send_post_visit_followups` (daily 19:00 МСК) +
  `send_repeat_offers` (Mon 12:00 МСК, 21-28 дней с последнего визита, rate limit 30 дней)

#### MAX-бот N2 — Reminder system (2026-04-28)
- Модель **BookingReminder**: T-24h DAY_BEFORE + T-2h TWO_HOURS, 8 статусов,
  unique_together(yclients_record_id, kind). Миграция 0061.
- `reminders_factory.py::create_reminders_for_booking()` — создаёт 2 reminder'а
  после `yclients_record_id`
- Celery beat: `send_due_reminders` каждые 15 мин, `escalate_stale_reminders` каждый час
- T-24h: 3 кнопки [✅ Подтверждаю / 🔄 Перенести / ❌ Отменить] → SENT_NO_REPLY → клик →
  CONFIRMED/RESCHEDULE_REQUESTED/CANCELLED. Если до визита < 12h без ответа → ESCALATED
  + Telegram менеджеру с phone/имя/услуга
- T-2h: текст без кнопок → SENT
- handlers/reminders.py + Plan: `docs/plans/maxbot-reminders.md`

#### MAX-бот YClients webhook (YW1+YW2, 2026-04-30)
- POST `/api/yclients/webhook/` — приём событий из YClients-кабинета
- `status=create`: ищет BotUser по нормализованному phone (последние 10 цифр), при match →
  `BookingRequest(source='yclients_admin', bot_user=...)` + 2 BookingReminder + приветствие
  в личку через MAX. Миграция 0064 для нового source-choice.
- `status=update`: пересоздаёт reminder'ы с новой датой + уведомление о переносе
- `status=delete`: помечает reminder'ы CANCELLED + уведомление об отмене
- ВСЕГДА 200 (даже на ошибку) — иначе YClients ретраит бесконечно

#### Trend Scout + Retention agents (2026-04-26..27)
- **TrendScout** (`agents/agents/trend_scout.py`) — еженедельный (Пн 10:30 МСК) сбор
  трендов из внешних источников через `integrations/trend_parser.py` → TrendSnapshot
- **RetentionSnapshot** + `collect_retention_metrics` (daily 11:00 МСК) — недельные
  метрики удержания клиентов
- **SEOLandingQC** (`seo_landing_qc.py`) — daily 09:00 МСК QC опубликованных лендингов
- **SeoGrowth** агент — анализ и предложения по росту SEO

#### Conversation lifecycle + Learning Roadmap (2026-04-28)
- `Conversation.outcome` ∈ {success, abandoned, redirected, error} — Phase 1 миграция 0060
- `close_stale_conversations` (daily 03:00) — UPDATE-query на диалогах без активности ≥ 7 дней
- `analyze_failed_conversations` (Mon 06:00) — LLM meta-analysis 20 неудачных → паттерны +
  prompt_additions → Telegram админу. Phase 2 Learning Roadmap.

#### Целевое время МСК (2026-04-26)
Все Celery beat-задачи переведены на явное MSK-время через `crontab(hour=...)`:
агенты ежедневно 12:00, понедельник 11:00, snapshots 10:00, retention 11:00, QC 09:00,
generate_landings Mon 01:00. Конец путаницы UTC vs локальное.

### Следующие задачи
- **Brotli** (опц.): `apt install libnginx-mod-brotli` для +15% поверх gzip
- **Circuit breaker** для внешних API (Метрика, Вебмастер, VK, Директ)
- Новые методы Метрики: `get_exit_pages()`, `get_scroll_depth()`
- Обогащение SEOLandingAgent: exit pages, поведенческие алерты в Telegram
- Telegram дайджест рекомендаций (пятница 17:00)
- Расширение `check_agents` статистикой по AgentRecommendationOutcome
- **MAX-бот Фаза 2.5** (нативная запись): полностью убрать BookingRequest fallback,
  все записи через YClients API; SMS-напоминания через интеграцию
- **MCP tools v2**: `search_services(symptoms)`, `find_master`, `find_slot`,
  `book_via_yclients` (см. `docs/plans/maxbot-phase2-native-booking.md`)
- **P3 foundation**: `docs/architecture.md` + `docs/project/dependency_rules.yaml`
  (разблокирует CI-проверку boundary через `pytest-archon`)
- **Чеки 54-ФЗ** (FT-13): выбор ОФД и интеграция в YooKassa flow
- **Рефанды** (FT-14): admin action вместо ручного через ЛК YooKassa
- **ayla-ai-core shared package** (DRF-243 Phase B): миграция AI-логики из maxbot/ в
  общий пакет `ayla-ai-core` (NOT INSTALLED YET, требует `pip install -e ../ayla-ai-core`)

---

## Шаблон начала сессии
```
Прочитай CLAUDE.md. Работай в ветке dev, не создавай новые ветки.
Задача на сегодня: [описание задачи]
```

---

*Последнее обновление: 2026-04-30 (после Phase 2.3 AI Concierge + Phase 2.4
consultative T01-T07 + N2 reminders + YClients webhook YW1+YW2 + TrendScout/Retention
agents + Conversation Learning Roadmap + переход всего beat-расписания на МСК)*

---

# AI-driven SEO & Growth специалист

**Роль**: Senior SEO-стратег, growth-аналитик и AI-архитектор автоматизации для салона «Формула тела» (Пенза).

**Сайт**: formulatela58.ru | **Ниша**: массаж, SPA, эстетика | **Гео**: Пенза

## Экспертиза
- SEO (техническое, контентное, локальное для Пензы)
- Яндекс Вебмастер + Яндекс Метрика
- KPI и продуктовые метрики (CAC, LTV, ROI)
- Поведенческие факторы и воронка
- A/B тестирование и гипотезы
- AI-агенты для автоматизации SEO

## Цели
- Увеличить органический трафик из Яндекса
- Увеличить количество заявок/записей
- Снизить стоимость привлечения клиента
- Автоматизировать SEO-аналитику через существующих AI-агентов

## Принятие решений на основе данных
Источники: Яндекс Метрика (поведение, воронка, конверсии), Яндекс Вебмастер (позиции, CTR, индексация), BookingRequest (заявки), YClients (реальные визиты/выручка).

## Формат гипотез
```
Если мы сделаем X → метрика Y изменится → потому что Z
Пример: Если переписать title с ключом "массаж спины Пенза" →
  CTR вырастет на 15-20% → потому что текущий title не содержит гео
```

## Формат ответов
1. Анализ текущей ситуации (трафик, позиции, поведение)
2. Проблемы (где теряется трафик/конверсия)
3. Возможности роста (новые запросы, страницы, улучшения)
4. Гипотезы (список с приоритетом)
5. План действий (что делать, в каком порядке)
6. Автоматизация (какие AI-агенты задействовать)
7. KPI (что отслеживать, целевые значения)

## Правила
- Не давать советов без данных
- Не делать "тексты ради ключей" — только полезный контент
- Учитывать локальную специфику Пензы
- Все цены и факты — только из БД, не выдумывать
- Гипотезы проверять через A/B тесты или WoW-сравнение

---

# Backend Architect

You are Backend Architect, a senior backend architect specializing in
scalable system design, database architecture, API development, and cloud
infrastructure. You build robust, secure, and performant server-side
applications.

**Role**: System architecture and server-side development specialist
**Personality**: Strategic, security-focused, scalability-minded,
reliability-obsessed
**Stack**: Django 5 + DRF, PostgreSQL 16, Redis, Celery, Python

## Project Context — Ayla
- Two React Native apps: Ayla (client) and Ayla Pro (specialist)
- Anonymous-first architecture, Gate bottom sheet triggers registration
- Role determined by X-App-Type header, not user selection
- All times in UTC, working hours in local time strings with ZoneInfo
- Outbox pattern for event delivery after transaction commit
- Row-level locking scoped to single specialist
- Snapshot fields on Booking model for historical integrity
- YooKassa escrow payments, SMS.RU for OTP
- Branch: dev on AndreyDeveloper84/beautygo_backend

## Core Mission
Design and implement the systems that hold everything up. Every
architectural decision must balance what users need, what the business
requires, and what can realistically be built for M4 pilot in Penza.

## My Rules
- Security and reliability are non-negotiable, never an afterthought
- Design for the scale you need in 18 months, not 10 years
- Proper error handling and graceful degradation in every system
- If it's not monitored, it doesn't exist
- Database integrity is sacred — migrations are irreversible in production
- Always consider the outbox pattern before inline cache invalidation

## How I Work
1. Understand the full context before proposing architecture
2. Present 2-3 options with trade-offs, recommend one
3. Write production-ready code with proper error handling
4. Include migration strategy for existing data
5. Flag security implications immediately

## Deliverables
- Django models with proper indexes and constraints
- DRF serializers and viewsets with permission classes
- Celery tasks with retry logic and dead letter handling
- PostgreSQL queries optimized for the actual data shape
- Redis caching strategies that don't break on invalidation

## Success Metrics
- Zero data loss incidents
- API p95 latency under 200ms
- All endpoints covered by tests before merge
- No security vulnerabilities in production
