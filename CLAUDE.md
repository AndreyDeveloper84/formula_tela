# CLAUDE.md

Guidelines for AI assistants working on the Formula Tela (Формула Тела) codebase.

## Project Overview

Beauty salon website for "Формула Тела" (Formula Tela) — a massage and beauty studio in Penza, Russia (formulatela58.ru). Built with Django 5.2, it provides online service catalog, appointment booking via YClients API integration, and a full CMS via Django Admin.

## Tech Stack

- **Backend:** Python 3.12, Django 5.2
- **Database:** PostgreSQL 16 (production/staging), SQLite (local/CI)
- **Cache:** Redis 7
- **API Integration:** YClients REST API v2 (booking, staff, services)
- **Frontend:** Django templates, Bootstrap 5, vanilla JS, CSS (no build step)
- **Containerization:** Docker, docker-compose
- **Testing:** pytest + pytest-django
- **Deployment:** GitHub Actions SSH to VPS, gunicorn + systemd

## Repository Structure

```
formula_tela/
├── CLAUDE.md              # This file
├── Dockerfile             # Python 3.12 slim image
├── docker-compose.yml     # db (postgres), redis, web (django)
├── requirements.txt       # Python dependencies (root level)
├── pytest.ini             # Pytest configuration
├── .env                   # Environment variables (DO NOT commit secrets)
├── .github/workflows/
│   ├── ci.yml             # CI: lint, migrate, collectstatic (push to dev/main)
│   ├── deploy-staging.yml # Deploy dev branch to staging via SSH
│   └── deploy.yml         # Deploy main branch to production via SSH
└── mysite/                # Django project root (manage.py lives here)
    ├── manage.py
    ├── mysite/            # Django settings package
    │   ├── settings/
    │   │   ├── __init__.py    # Auto-selects settings via DJANGO_ENV
    │   │   ├── base.py        # Shared settings (all envs)
    │   │   ├── local.py       # Local dev (DEBUG=True, no SSL)
    │   │   ├── dev.py         # CI (SSL enabled, DEBUG from env)
    │   │   ├── staging.py     # Staging (stg.formulatela58.ru)
    │   │   └── production.py  # Production (formulatela58.ru)
    │   ├── urls.py        # Root URL config
    │   ├── wsgi.py
    │   └── asgi.py
    ├── services_app/      # Core app: services, masters, bundles, promotions
    │   ├── models.py      # Service, ServiceOption, ServiceCategory, Master, etc.
    │   ├── admin.py       # Full admin configuration with inlines
    │   ├── views.py       # Commented out (views in website app)
    │   ├── yclients_api.py     # YClients API client class
    │   ├── forms.py       # CSV import form
    │   ├── signals.py     # Django signals (currently empty)
    │   ├── templatetags/
    │   │   └── service_extras.py  # Filters: option_label, discount
    │   ├── management/commands/
    │   │   └── import_price_list.py
    │   └── migrations/
    ├── website/           # Main frontend app: views, templates, URLs
    │   ├── views.py       # All page views + JSON API endpoints
    │   ├── urls.py        # URL routing (pages + API)
    │   ├── context_processors.py  # Global SiteSettings context
    │   ├── templatetags/
    │   │   └── faq_tags.py
    │   └── templates/website/
    │       ├── base.html
    │       ├── home.html
    │       ├── services.html
    │       ├── service_detail.html
    │       ├── category_services.html
    │       ├── masters.html
    │       ├── contacts.html
    │       ├── promotions.html
    │       ├── bundles.html
    │       └── components/
    │           ├── header.html
    │           └── footer.html
    ├── booking/           # Booking app (minimal, mostly handled via website views)
    │   ├── views.py
    │   └── urls.py
    ├── static/            # Static assets (no build pipeline)
    │   ├── css/main.css   # Main stylesheet
    │   ├── js/main.js     # Main JavaScript
    │   ├── fonts/
    │   ├── images/
    │   └── video/
    ├── media/             # User-uploaded files
    └── tests/             # Pytest test suite
        ├── test_healthz.py
        ├── test_admin.py
        ├── test_db_user.py
        └── test_migrations_clean.py
```

## Key Django Apps

### `services_app` — Data Models (no views)
Contains all business models. Views are in `website` app.

**Core models:**
- `Service` — A salon service (massage type) with SEO fields, slug, images, related services
- `ServiceOption` — Price/duration variant of a service (linked to YClients via `yclients_service_id`)
- `ServiceCategory` — Category grouping services (with slug for URLs)
- `ServiceBlock` — CMS content blocks for service landing pages (text, FAQ, CTA, accordion, etc.)
- `ServiceMedia` — Photo/video gallery items for service pages (carousel support)
- `Master` — Staff member with bio, education, accordion-style detail fields
- `Bundle` / `BundleItem` — Service packages with parallel scheduling support
- `Promotion` — Active promotions with discount percentages
- `FAQ` — Frequently asked questions (category-scoped)
- `Review` — Client reviews
- `SiteSettings` — Singleton for site-wide settings (name, phone, social links)
- `BookingRequest` / `BundleRequest` — Form submissions saved to DB + Telegram notification

### `website` — Views, Templates, API Endpoints
All user-facing views and JSON API endpoints live here.

**Pages:** home, services, service_detail (by slug or ID with 301 redirect), category_services, masters, contacts, promotions, bundles

**API endpoints (JSON):**
- `GET /api/booking/get_staff/` — Masters for a service option
- `GET /api/booking/available_dates/` — Available dates for a master
- `GET /api/booking/available_times/` — Available time slots (with duration filtering)
- `POST /api/booking/create/` — Create booking via YClients
- `GET /api/booking/service_options/` — Options for a service
- `POST /api/bundle/request/` — Bundle request form submission
- `GET /api/wizard/categories/` — Categories for booking wizard
- `GET /api/wizard/categories/<id>/services/` — Services for wizard
- `POST /api/wizard/booking/` — Wizard booking submission

### `booking` — Minimal booking page
Just renders a booking template. Most booking logic is in `website/views.py`.

## Development Setup

```bash
# 1. Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run migrations (uses SQLite by default locally)
cd mysite
mkdir -p data
python manage.py migrate

# 4. Create superuser (for admin access)
python manage.py createsuperuser

# 5. Run dev server
python manage.py runserver
```

### Docker setup
```bash
docker-compose up --build
# Django at http://localhost:8000
# Postgres at localhost:5432
# Redis at localhost:6379
```

## Settings Configuration

Settings are selected automatically via `DJANGO_ENV` environment variable:
- `local` (default) — `settings/local.py` — DEBUG=True, SQLite, no SSL
- `staging` / `stg` — `settings/staging.py` — SSL enabled, PostgreSQL
- `production` / `prod` — `settings/production.py` — Full security, PostgreSQL

Key environment variables (in `.env`):
- `DJANGO_SECRET_KEY` — Required in production
- `DJANGO_DEBUG` — Boolean
- `DJANGO_ALLOWED_HOSTS` — Comma-separated
- `DJANGO_CSRF_TRUSTED_ORIGINS` — Comma-separated with scheme
- `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`
- `YCLIENTS_PARTNER_TOKEN`, `YCLIENTS_USER_TOKEN`, `YCLIENTS_COMPANY_ID`
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

## Testing

```bash
# Run all tests (from repo root)
pytest

# Run specific test file
pytest mysite/tests/test_healthz.py

# Run with verbose output
pytest -v
```

**pytest.ini configuration:**
- `DJANGO_SETTINGS_MODULE = mysite.settings` (auto-selects based on DJANGO_ENV)
- `pythonpath = mysite`
- `testpaths = mysite/tests`

**Existing tests:**
- `test_healthz.py` — Health check endpoint returns 200
- `test_admin.py` — Admin login page accessible
- `test_migrations_clean.py` — No unapplied migrations exist
- `test_db_user.py` — Database user tests

Tests use SQLite in CI (configured via `DB_ENGINE` env var in `.github/workflows/ci.yml`).

## CI/CD Pipeline

### CI (`ci.yml`)
Triggers on push/PR to `dev` and `main`:
1. Python 3.12 setup
2. Install dependencies from `requirements.txt`
3. `python manage.py check`
4. `python manage.py migrate --noinput`
5. `python manage.py collectstatic --noinput`
6. Tests are currently commented out

### Staging Deploy (`deploy-staging.yml`)
Triggers on push to `dev`:
1. Runs quick tests
2. SSH to VPS, backup DB, git pull `dev`, migrate, collectstatic, restart gunicorn

### Production Deploy (`deploy.yml`)
Triggers on push to `main`:
1. Runs tests
2. SSH to VPS, backup DB, git pull `main`, migrate, collectstatic, restart gunicorn
3. Health check (fails build if unhealthy)

## Git Workflow

- `main` — Production branch, deploys to formulatela58.ru
- `dev` — Development/staging branch, deploys to stg.formulatela58.ru
- Feature branches merge into `dev`, then `dev` merges into `main`

## Code Conventions

### Language
- Code: Python/English (variable names, function names, class names in English)
- UI strings, verbose_name, help_text: Russian (Cyrillic)
- Comments: Mix of Russian and English (prefer consistency with surrounding code)
- Commit messages: English with conventional commit prefixes (`feat:`, `fix:`, `refactor:`)

### Django Patterns
- **Models:** All business models in `services_app/models.py`. Use `verbose_name` for all fields (Russian). All models have `Meta.verbose_name` / `verbose_name_plural`.
- **Admin:** Rich admin with `fieldsets`, `inlines`, `list_editable`, `filter_horizontal`, `autocomplete_fields`. Images get preview via `format_html`.
- **Views:** Function-based views. API endpoints return `JsonResponse` with `{success: bool, data: ...}` pattern.
- **URLs:** Use `app_name` namespacing. SEO-friendly slugs for services (`/uslugi/<slug>/`).
- **Templates:** Extend `base.html`, use component includes from `components/`. Use `{% load service_extras %}` for custom filters.
- **Static files:** Plain CSS/JS in `mysite/static/`. No build pipeline (no webpack/vite).

### Model Conventions
- Use `is_active` boolean for soft-delete pattern
- Use `order` field (PositiveIntegerField) for manual sorting
- Use `created_at` / `updated_at` auto-timestamps where appropriate
- SEO fields: `slug`, `seo_title`, `seo_description`, `seo_h1`
- Image fields: provide both `image` (desktop) and `image_mobile` variants

### API Convention
All JSON API endpoints follow this pattern:
```python
# Success
{"success": True, "data": {...}}

# Error
{"success": False, "error": "description"}
```

### YClients Integration
- API client: `services_app/yclients_api.py` — `YClientsAPI` class
- Factory function: `get_yclients_api()` reads credentials from Django settings
- Service options link to YClients via `ServiceOption.yclients_service_id`
- Booking flow: select service option -> get staff -> get dates -> get times -> create booking

## Common Tasks

### Adding a new service field
1. Add field to `Service` model in `mysite/services_app/models.py`
2. Add to admin fieldsets in `mysite/services_app/admin.py`
3. Run `python manage.py makemigrations services_app`
4. Run `python manage.py migrate`
5. Update template in `mysite/website/templates/website/service_detail.html`
6. Pass new field through context in `mysite/website/views.py` (`_render_service_detail`)

### Adding a new page
1. Add view function in `mysite/website/views.py`
2. Add URL pattern in `mysite/website/urls.py`
3. Create template in `mysite/website/templates/website/`
4. Extend `base.html`, include header/footer components

### Adding a new API endpoint
1. Add view function in `mysite/website/views.py` with `@require_GET` or `@require_POST`
2. Return `JsonResponse({success: True, data: ...})`
3. Add URL pattern in `mysite/website/urls.py` under the API section

### Running migrations
```bash
cd mysite
python manage.py makemigrations
python manage.py migrate
```

## Important Notes

- **No `.env` in commits** — `.env` is gitignored but exists in the working directory. Never commit real secrets.
- **YClients API** requires `User-Agent` and `X-Partner-Id` headers to avoid WAF 403 errors.
- **Static files** have no build pipeline. Edit CSS/JS directly in `mysite/static/`.
- **Templates** use Django template language, not Jinja2.
- **The `services_app/views.py`** is mostly commented out — all active views are in `website/views.py`.
- **Telegram notifications** are sent for new booking/bundle requests if `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are configured.
- **SEO** is important — service pages have Schema.org markup, OpenGraph tags, canonical URLs, breadcrumbs.
