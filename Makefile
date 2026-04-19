.PHONY: db db-stop run migrate makemigrations shell docker logs psql worker beat agent-analytics agent-offers

db:           ## Запустить PostgreSQL + Redis в фоне
	docker-compose up db redis -d

db-stop:      ## Остановить PostgreSQL + Redis
	docker-compose stop db redis

run:          ## Django dev server (требует `make db`)
	cd mysite && python manage.py runserver

migrate:      ## Применить миграции
	cd mysite && python manage.py migrate

makemigrations: ## Создать миграции
	cd mysite && python manage.py makemigrations

shell:        ## Django shell
	cd mysite && python manage.py shell

docker:       ## Поднять весь стек в Docker (db + redis + web)
	docker-compose up

logs:         ## Логи контейнеров БД и Redis
	docker-compose logs -f db redis

psql:         ## Открыть psql в контейнере БД
	docker-compose exec db psql -U mysite_user -d mysite_db

worker:       ## Celery worker (локально, требует `make db`)
	cd mysite && celery -A mysite worker -Q formula_tela -l info

beat:         ## Celery beat планировщик (локально, требует `make db`)
	cd mysite && celery -A mysite beat -l info

agent-analytics: ## Запустить Analytics Agent вручную
	cd mysite && PYTHONIOENCODING=utf-8 DJANGO_SETTINGS_MODULE=mysite.settings python -c "import django; django.setup(); from agents.agents.analytics import AnalyticsAgent; t=AnalyticsAgent().run(); print('Status:', t.status)"

agent-offers:    ## Запустить Offer Agent вручную
	cd mysite && PYTHONIOENCODING=utf-8 DJANGO_SETTINGS_MODULE=mysite.settings python -c "import django; django.setup(); from agents.agents.offers import OfferAgent; t=OfferAgent().run(); print('Status:', t.status)"
