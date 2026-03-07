# CLAUDE.md — Formula Tela (Формула Тела)

## Project Overview

Beauty salon website for **Формула Тела** (formulatela58.ru) built with Django 5.2+. Features online appointment booking (via YClients API integration), service catalog with SEO landing pages, staff management, bundles/packages, promotions, and client reviews.

**Language**: The codebase uses Russian for model verbose names, admin labels, comments, and UI text. Commit messages and code identifiers use English.

## Tech Stack

- **Framework**: Django 5.2+ with Django Templates
- **Python**: 3.12
- **Database**: PostgreSQL 16 (production/docker), SQLite (local dev/CI)
- **Cache/Queue**: Redis 7
- **External API**: YClients REST API v2 (booking, staff, services)
- **Key packages**: django-csp, djangorestframework, Pillow, httpx, python-dotenv, psycopg2-binary
- **Testing**: pytest + pytest-django + model-bakery
- **Containerization**: Docker + docker-compose

## Project Structure

```
formula_tela/
├── mysite/                     # Django project root (manage.py lives here)
│   ├── manage.py
│   ├── mysite/                 # Django settings package
│   │   ├── settings/
│   │   │   ├── __init__.py     # Auto-selects env via DJANGO_ENV
│   │   │   ├── base.py         # Shared settings (DB, apps, middleware, CSP)
│   │   │   ├── local.py        # Local dev (DEBUG=True, no SSL)
│   │   │   ├── dev.py          # Staging (SSL enabled)
│   │   │   ├── staging.py      # Staging alias
│   │   │   └── production.py   # Production (strict security)
│   │   ├── urls.py             # Root URL config
│   │   ├── wsgi.py
│   │   └── asgi.py
│   ├── services_app/           # Core app: services, categories, masters, bundles
│   │   ├── models.py           # Service, ServiceOption, ServiceCategory, ServiceBlock,
│   │   │                       # ServiceMedia, Master, Bundle, FAQ, Promotion, Review, etc.
│   │   ├── admin.py            # Admin with inlines (ServiceBlock, ServiceMedia, etc.)
│   │   ├── views.py
│   │   ├── yclients_api.py     # YClients API client class
│   │   ├── signals.py
│   │   ├── templatetags/
│   │   │   └── service_extras.py
│   │   └── migrations/
│   ├── website/                # Frontend app: views, templates, template tags
│   │   ├── views.py            # Page views + JSON API endpoints
│   │   ├── urls.py             # Routes: pages + /api/booking/* + /api/wizard/*
│   │   ├── context_processors.py
│   │   ├── templatetags/
│   │   │   ├── faq_tags.py
│   │   │   ├── media_tags.py
│   │   │   └── social_tags.py
│   │   └── templates/website/
│   │       ├── base.html
│   │       ├── home.html
│   │       ├── services.html
│   │       ├── service_detail.html  # SEO landing page with blocks/media
│   │       ├── category_services.html
│   │       ├── masters.html
│   │       ├── contacts.html
│   │       ├── bundles.html
│   │       ├── promotions.html
│   │       └── components/     # header.html, footer.html
│   ├── booking/                # Booking app (thin — mostly template)
│   │   ├── views.py
│   │   └── templates/booking/booking.html
│   ├── tests/                  # pytest test suite
│   │   ├── test_healthz.py
│   │   ├── test_migrations_clean.py
│   │   ├── test_admin.py
│   │   └── test_db_user.py
│   ├── static/                 # Static assets (images, CSS, JS)
│   └── media/                  # User-uploaded files
├── .github/workflows/
│   ├── ci.yml                  # CI: checks, migrate, collectstatic (SQLite)
│   ├── deploy-staging.yml      # Auto-deploy dev → staging
│   └── deploy.yml              # Deploy main → production (manual approve)
├── Dockerfile                  # Python 3.12-slim
├── docker-compose.yml          # db (postgres), redis, web (django)
├── requirements.txt            # Pinned dependencies
├── pytest.ini                  # pytest config
└── .env                        # Local env vars (not committed)
```

## Key Django Apps

| App | Purpose |
|---|---|
| `services_app` | Core domain models: Service, ServiceOption, ServiceCategory, ServiceBlock (SEO landing page builder), ServiceMedia (gallery/carousel), Master, Bundle, FAQ, Promotion, Review, BookingRequest, SiteSettings |
| `website` | All frontend views, templates, template tags, and JSON API endpoints for booking wizard |
| `booking` | Legacy booking page (single view/template) |

## Development Setup

```bash
# 1. Virtual environment
python -m venv venv && source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create data directory (SQLite)
mkdir -p mysite/data

# 4. Run migrations
python mysite/manage.py migrate

# 5. Create superuser
python mysite/manage.py createsuperuser

# 6. Run dev server
python mysite/manage.py runserver
```

Settings are auto-selected by `DJANGO_ENV` env var: `local` (default), `staging`, `production`.

### Docker

```bash
docker-compose up --build    # PostgreSQL + Redis + Django on :8000
```

## Running Tests

```bash
# From repo root:
pytest -q

# Or via Django:
python mysite/manage.py test
```

**pytest.ini** config: `DJANGO_SETTINGS_MODULE=mysite.settings`, `pythonpath=mysite`, `testpaths=mysite/tests`.

Tests use SQLite. CI runs `python manage.py check`, `migrate`, and `collectstatic` but pytest is currently commented out in CI.

## URL Structure

### Pages
- `/` — Home
- `/services/` — Service categories catalog
- `/services/<category_id>/` — Category detail with services
- `/uslugi/<slug>/` — SEO service landing page (slug-based)
- `/service/<id>/` — Service detail (legacy, redirects 301 to slug)
- `/masters/` — Staff listing
- `/contacts/` — Contact page
- `/bundles/` — Service bundles
- `/promotions/` — Active promotions
- `/booking/` — Booking page
- `/admin/` — Django admin
- `/healthz/` — Health check endpoint

### API Endpoints (JSON)
- `/api/booking/get_staff/` — Staff for service
- `/api/booking/available_dates/` — Available dates
- `/api/booking/available_times/` — Available time slots
- `/api/booking/create/` — Create booking
- `/api/booking/service_options/` — Service options
- `/api/bundle/request/` — Bundle request submission
- `/api/wizard/categories/` — Wizard: category list
- `/api/wizard/categories/<id>/services/` — Wizard: services in category
- `/api/wizard/booking/` — Wizard: create booking

## Git & Branching

- **`main`** — Production branch. Deploy via PR from `dev` with manual approval.
- **`dev`** — Development/staging branch. Auto-deploys on push.
- Feature branches: `feature/<name>` merged into `dev`.

### Commit Message Convention

Use conventional commits prefix: `feat:`, `fix:`, `refactor:`, `chore:`, etc.

```
feat: add ServiceMedia gallery with carousel support
fix(yclients): add User-Agent header to bypass WAF 403
```

## Environment Variables

Key env vars (set in `.env` or docker-compose):

| Variable | Purpose |
|---|---|
| `DJANGO_ENV` | `local` / `staging` / `production` |
| `DJANGO_SECRET_KEY` | Secret key (required in prod) |
| `DJANGO_DEBUG` | `True` / `False` |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hosts |
| `DB_ENGINE` | `django.db.backends.postgresql` or `sqlite3` |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | Database connection |
| `YCLIENTS_PARTNER_TOKEN` | YClients API partner token |
| `YCLIENTS_USER_TOKEN` | YClients API user token |
| `YCLIENTS_COMPANY_ID` | YClients company ID |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Telegram notifications |

## Key Conventions

- **Models use `is_active` + `order` fields** for soft-delete and sorting across most entities.
- **SEO fields** on Service: `slug`, `seo_h1`, `seo_title`, `seo_description`, `subtitle`.
- **ServiceBlock** is a page builder — supports block types: text, accent, checklist, identification, cta, price_table, accordion, faq, special_formats, subscriptions, navigation, html.
- **ServiceMedia** supports single images and carousel groups, with separate desktop/mobile versions and positional insertion on mobile.
- **YClients API** integration in `services_app/yclients_api.py` — handles staff, services, dates, time slots, and booking creation.
- **Template structure**: `base.html` → page templates. Components in `components/` subfolder.
- **Admin customization**: Extensive use of inlines, fieldsets, and filter_horizontal widgets.
- **No REST framework views** — API endpoints are plain Django views returning `JsonResponse`.
- **Static files**: images in `mysite/static/images/`, served by Django in dev, collected to `staticfiles/` in prod.

## Important Notes

- The `requirements.txt` file has unusual spacing (UTF-16 encoding artifacts) — use `pip install -r requirements.txt` which handles this.
- Multiple diagnostic/sync scripts exist in `mysite/` root (e.g., `diagnose_and_sync.py`, `import_masters_from_yclients.py`) — these are one-off management scripts.
- The `v-massaj/` directory contains the original static HTML mockup used as design reference.
- `.env` file is gitignored and must be created locally with required tokens.
