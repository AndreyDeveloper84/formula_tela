# Beauty Salon Website

A web application for managing a beauty salon, built with Django.

## Features
- Online appointment booking
- Service catalog
- Staff management
- Client profiles
- Schedule management

## Project Structure
```
mysite/
├── manage.py
├── mysite/
│   ├── __init__.py
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── salon/
│   ├── migrations/
│   ├── static/
│   ├── templates/
│   ├── __init__.py
│   ├── admin.py
│   ├── models.py
│   ├── urls.py
│   ├── views.py
│   └── tests.py
└── requirements.txt
```

## Setup
1. Create virtual environment:
```bash
python -m venv venv
venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run migrations:
```bash
python manage.py migrate
```

4. Create superuser:
```bash
python manage.py createsuperuser
```

5. Run development server:
```bash
python manage.py runserver
```

## Admin Access
After creating a superuser, you can access the admin panel at:
```
http://localhost:8000/admin
```

## Testing
```bash
python manage.py test
```

## Contributing
1. Fork the repository
2. Create a new branch
3. Make your changes
4. Submit a pull request

## License
This project is licensed under the MIT License.