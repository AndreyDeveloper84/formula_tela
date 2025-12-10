"""
YClients API Integration
Документация: https://yclients.docs.apiary.io/
User Token: 7fcdd6c3643da0f14a4cdddbce34c9de
"""

import requests
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from django.conf import settings
from django.core.cache import cache
import logging

logger = logging.getLogger(__name__)


class YClientsAPIError(Exception):
    """Базовое исключение для ошибок YClients API"""
    pass


class YClientsAPI:
    """
    Клиент для работы с YClients REST API
    
    Использование:
        # С готовым User Token
        api = YClientsAPI(user_token="wuks7e8d...")
        
        # Или получить токен через логин/пароль
        api = YClientsAPI.from_credentials(
            login="your_login",
            password="your_password"
        )
        
        services = api.get_services()
        staff = api.get_staff(service_id=123)
        times = api.get_available_times(service_id=123, staff_id=456, date="2025-01-15")
        booking = api.create_booking(...)
    """
    
    BASE_URL = "https://api.yclients.com/api/v1"
    AUTH_URL = "https://api.yclients.com/api/v1/auth"
    
    def __init__(
        self, 
        partner_token: str = None,
        user_token: str = None,
        company_id: str = None
    ):
        """
        Инициализация API клиента
        
        Args:
            partner_token: Токен партнера (опционально, для некоторых запросов)
            user_token: Токен пользователя (ОБЯЗАТЕЛЬНО для большинства запросов)
            company_id: ID компании в YClients (если не передан, берётся из settings)
        """
        self.partner_token = partner_token or getattr(
            settings, 'YCLIENTS_PARTNER_TOKEN', 'gmn9rncz9nhr66yj23yc'
        )
        self.user_token = user_token or getattr(
            settings, 'YCLIENTS_USER_TOKEN', None
        )
        self.company_id = company_id or getattr(
            settings, 'YCLIENTS_COMPANY_ID', '884045'
        )
        
        if not self.user_token:
            logger.warning(
                "⚠️  User Token не указан! Большинство запросов не будут работать. "
                "Укажите YCLIENTS_USER_TOKEN в settings или используйте from_credentials()"
            )
        
        # YClients требует специальный формат Authorization:
        # Authorization: Bearer <partner_token>, User <user_token>
        # Согласно документации: https://yclients.docs.apiary.io/
        auth_value = f"Bearer {self.partner_token}"
        if self.user_token:
            auth_value += f", User {self.user_token}"
        
        self.headers = {
            "Accept": "application/vnd.yclients.v2+json",
            "Authorization": auth_value,
            "Content-Type": "application/json",
        }
    
    @classmethod
    def from_credentials(cls, login: str, password: str, company_id: str = None):
        """
        Создать API клиент, авторизовавшись по логину и паролю
        
        Args:
            login: Логин в YClients (email или телефон)
            password: Пароль
            company_id: ID компании (опционально)
            
        Returns:
            YClientsAPI с полученным User Token
            
        Example:
            api = YClientsAPI.from_credentials(
                login="your@email.com",
                password="your_password"
            )
        """
        partner_token = getattr(settings, 'YCLIENTS_PARTNER_TOKEN', 'gmn9rncz9nhr66yj23yc')
        
        # Получаем User Token через авторизацию
        logger.info(f"Авторизация в YClients: {login}")
        
        response = requests.post(
            cls.AUTH_URL,
            headers={
                "Accept": "application/vnd.yclients.v2+json",
                "Authorization": f"Bearer {partner_token}",
                "Content-Type": "application/json",
            },
            json={
                "login": login,
                "password": password,
            },
            timeout=10
        )
        
        response.raise_for_status()
        data = response.json()
        
        if not data.get('success'):
            raise YClientsAPIError(f"Ошибка авторизации: {data.get('meta', {}).get('message')}")
        
        user_token = data['data']['user_token']
        logger.info(f"✅ Успешная авторизация! User Token получен.")
        
        return cls(
            partner_token=partner_token,
            user_token=user_token,
            company_id=company_id
        )
    
    def _request(
        self, 
        method: str, 
        endpoint: str, 
        data: Dict = None,
        params: Dict = None,
        use_cache: bool = False,
        cache_timeout: int = 300
    ) -> Dict[str, Any]:
        """
        Универсальный метод для HTTP-запросов к API
        
        Args:
            method: HTTP метод (GET, POST, PUT, DELETE)
            endpoint: Путь API (например, "/company/884045/services")
            data: Данные для POST/PUT запросов
            params: Query параметры для GET запросов
            use_cache: Использовать ли кеширование (для GET запросов)
            cache_timeout: Время жизни кеша в секундах
            
        Returns:
            Dict с ответом от API
            
        Raises:
            YClientsAPIError: При ошибках API
        """
        url = f"{self.BASE_URL}{endpoint}"
        
        # Проверяем кеш (только для GET запросов)
        if use_cache and method.upper() == "GET":
            cache_key = f"yclients:{endpoint}:{str(params)}"
            cached = cache.get(cache_key)
            if cached:
                logger.debug(f"YClients API: Cache HIT for {endpoint}")
                return cached
        
        try:
            logger.info(f"YClients API: {method} {url}")
            
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                json=data,
                params=params,
                timeout=10
            )
            
            # Логируем ответ
            logger.debug(f"YClients API Response: {response.status_code}")
            
            # Проверяем статус
            response.raise_for_status()
            
            result = response.json()
            
            # Сохраняем в кеш (только для успешных GET запросов)
            if use_cache and method.upper() == "GET":
                cache.set(cache_key, result, cache_timeout)
            
            return result
            
        except requests.exceptions.Timeout:
            logger.error(f"YClients API Timeout: {url}")
            raise YClientsAPIError("Сервер YClients не отвечает. Попробуйте позже.")
            
        except requests.exceptions.HTTPError as e:
            logger.error(f"YClients API HTTPError: {e.response.status_code} - {e.response.text}")
            
            # Обрабатываем разные коды ошибок
            if e.response.status_code == 401:
                raise YClientsAPIError("Ошибка авторизации в YClients. Проверьте токен.")
            elif e.response.status_code == 404:
                raise YClientsAPIError("Ресурс не найден в YClients.")
            elif e.response.status_code == 429:
                raise YClientsAPIError("Превышен лимит запросов к YClients. Попробуйте позже.")
            else:
                raise YClientsAPIError(f"Ошибка YClients API: {e.response.status_code}")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"YClients API RequestException: {str(e)}")
            raise YClientsAPIError(f"Ошибка соединения с YClients: {str(e)}")
        
        except Exception as e:
            logger.error(f"YClients API Unexpected Error: {str(e)}")
            raise YClientsAPIError(f"Неожиданная ошибка: {str(e)}")
    
    # ============================================================
    # УСЛУГИ (Services)
    # ============================================================
    
    def get_services(self, category_id: int = None) -> List[Dict]:
        """
        Получить список всех услуг компании
        
        Args:
            category_id: Фильтр по категории (опционально)
            
        Returns:
            Список словарей с данными услуг:
            [
                {
                    "id": 123,
                    "title": "Массаж",
                    "category_id": 1,
                    "price_min": 2000,
                    "price_max": 5000,
                    "discount": 10,
                    "duration": 60,
                    ...
                }
            ]
        """
        endpoint = f"/company/{self.company_id}/services"
        params = {"category_id": category_id} if category_id else None
        
        response = self._request("GET", endpoint, params=params, use_cache=True, cache_timeout=600)
        
        # API возвращает {"success": true, "data": [...]}
        return response.get("data", [])
    
    def get_service(self, service_id: int) -> Dict:
        """
        Получить информацию о конкретной услуге
        
        Args:
            service_id: ID услуги в YClients
            
        Returns:
            Словарь с данными услуги
        """
        endpoint = f"/company/{self.company_id}/services/{service_id}"
        response = self._request("GET", endpoint, use_cache=True)
        return response.get("data", {})
    
    # ============================================================
    # СОТРУДНИКИ (Staff)
    # ============================================================
    
    def get_staff(self, service_id: int = None) -> List[Dict]:
        """
        Получить список сотрудников (мастеров)
        
        Args:
            service_id: Фильтр по услуге (вернёт только тех, кто делает эту услугу)
            
        Returns:
            Список словарей с данными мастеров:
            [
                {
                    "id": 456,
                    "name": "Сазонова Инна",
                    "specialization": "Массажист",
                    "avatar": "https://...",
                    "rating": 4.9,
                    ...
                }
            ]
        """
        endpoint = f"/company/{self.company_id}/staff"
        params = {}
        
        if service_id:
            params["service_id"] = service_id
        
        response = self._request("GET", endpoint, params=params, use_cache=True, cache_timeout=600)
        return response.get("data", [])
    
    # ============================================================
    # ДОСТУПНОЕ ВРЕМЯ (Available Times)
    # ============================================================
    
    def get_available_times(
        self,
        service_id: int,
        staff_id: int,
        date: str,
        datetime_from: str = None,
        datetime_to: str = None
    ) -> List[str]:
        """
        Получить список свободных временных слотов
        
        Args:
            service_id: ID услуги
            staff_id: ID мастера
            date: Дата в формате "YYYY-MM-DD" (например, "2025-01-15")
            datetime_from: Начало диапазона (опционально)
            datetime_to: Конец диапазона (опционально)
            
        Returns:
            Список строк с временем в формате "HH:MM":
            ["09:00", "10:00", "11:00", "14:00", "16:00"]
        """
        # Правильный endpoint согласно документации
        endpoint = f"/book_times/{self.company_id}/{staff_id}/{service_id}/{date}"
        
        params = {}
        
        if datetime_from:
            params["datetime_from"] = datetime_from
        if datetime_to:
            params["datetime_to"] = datetime_to
        
        response = self._request("GET", endpoint, params=params, use_cache=True, cache_timeout=60)
        
        # API возвращает массив объектов времени
        # [{"time": "09:00", "seance_length": 60, ...}, ...]
        data = response.get("data", [])
        
        # Извлекаем только время
        if isinstance(data, list):
            times = [item.get("time", item.get("datetime", "")) for item in data if isinstance(item, dict)]
            # Форматируем в HH:MM если пришло полное datetime
            times = [t.split("T")[1][:5] if "T" in t else t[:5] for t in times if t]
            return times
        elif isinstance(data, dict):
            # Альтернативный формат: {"2025-01-15": ["09:00", "10:00", ...]}
            return data.get(date, [])
        else:
            return []
    
    # ============================================================
    # СОЗДАНИЕ ЗАПИСИ (Create Booking)
    # ============================================================
    
    def create_booking(
        self,
        service_id: int,
        staff_id: int,
        datetime_str: str,
        client_name: str,
        client_phone: str,
        client_email: str = None,
        comment: str = None,
        send_sms: bool = True,
        notify_by_email: int = 0,
        notify_by_sms: int = 24
    ) -> Dict:
        """
        Создать запись клиента на услугу
        
        Args:
            service_id: ID услуги в YClients
            staff_id: ID мастера
            datetime_str: Дата и время в формате "YYYY-MM-DD HH:MM:SS" 
                         (например, "2025-01-15 14:00:00")
            client_name: Имя клиента
            client_phone: Телефон клиента (формат: +79991234567 или 79991234567)
            client_email: Email клиента (опционально)
            comment: Комментарий к записи (опционально)
            send_sms: Отправить SMS клиенту (по умолчанию True)
            notify_by_email: За сколько часов отправить email-напоминание (0 = не отправлять)
            notify_by_sms: За сколько часов отправить SMS-напоминание (по умолчанию 24)
            
        Returns:
            Словарь с данными созданной записи:
            {
                "id": 789,
                "company_id": 884045,
                "datetime": "2025-01-15 14:00:00",
                "client": {...},
                "services": [...],
                ...
            }
            
        Raises:
            YClientsAPIError: При ошибках создания записи
        """
        endpoint = f"/book_record/{self.company_id}"
        
        # Формируем данные для записи
        data = {
            "appointments": [
                {
                    "id": 0,  # 0 для новой записи
                    "services": [service_id],
                    "staff_id": staff_id,
                    "datetime": datetime_str,
                }
            ],
            "client": {
                "name": client_name,
                "phone": client_phone,
            },
            "send_sms": send_sms,
            "notify_by_email": notify_by_email,
            "notify_by_sms": notify_by_sms,
        }
        
        # Добавляем опциональные поля
        if client_email:
            data["client"]["email"] = client_email
        
        if comment:
            data["comment"] = comment
        
        try:
            response = self._request("POST", endpoint, data=data)
            
            # Проверяем успешность создания
            if response.get("success"):
                logger.info(f"✅ Booking created: {response.get('data', {}).get('id')}")
                return response.get("data", {})
            else:
                error_msg = response.get("meta", {}).get("message", "Неизвестная ошибка")
                logger.error(f"❌ Booking failed: {error_msg}")
                raise YClientsAPIError(f"Не удалось создать запись: {error_msg}")
                
        except YClientsAPIError:
            raise
        except Exception as e:
            logger.error(f"❌ Unexpected error in create_booking: {str(e)}")
            raise YClientsAPIError(f"Ошибка при создании записи: {str(e)}")
    
    # ============================================================
    # КЛИЕНТЫ (Clients)
    # ============================================================
    
    def search_client(self, phone: str) -> Optional[Dict]:
        """
        Найти клиента по номеру телефона
        
        Args:
            phone: Телефон клиента
            
        Returns:
            Словарь с данными клиента или None, если не найден
        """
        endpoint = f"/clients/{self.company_id}/search"
        params = {"phone": phone}
        
        try:
            response = self._request("GET", endpoint, params=params)
            clients = response.get("data", [])
            return clients[0] if clients else None
        except YClientsAPIError:
            return None
    
    # ============================================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ============================================================
    
    def get_service_duration(self, service_id: int) -> int:
        """
        Получить длительность услуги в минутах
        
        Args:
            service_id: ID услуги
            
        Returns:
            Длительность в минутах
        """
        service = self.get_service(service_id)
        return service.get("duration", 60)
    
    def format_phone(self, phone: str) -> str:
        """
        Форматировать телефон в нужный формат для YClients
        
        Args:
            phone: Номер телефона в любом формате
            
        Returns:
            Телефон в формате 79991234567 (без +)
        """
        # Убираем все символы кроме цифр
        digits = ''.join(filter(str.isdigit, phone))
        
        # Если начинается с 8, заменяем на 7
        if digits.startswith('8'):
            digits = '7' + digits[1:]
        
        # Если не начинается с 7, добавляем 7
        if not digits.startswith('7'):
            digits = '7' + digits
        
        return digits


# ============================================================
# УДОБНЫЕ ФУНКЦИИ-ХЕЛПЕРЫ
# ============================================================

def get_yclients_api() -> YClientsAPI:
    """
    Получить инстанс YClients API с настройками из settings
    
    Usage:
        api = get_yclients_api()
        services = api.get_services()
    """
    return YClientsAPI()


def sync_services_from_yclients():
    """
    Синхронизировать услуги из YClients в Django базу
    
    Можно вызывать из management команды или крона
    
    Usage:
        python manage.py shell
        >>> from services_app.yclients_api import sync_services_from_yclients
        >>> sync_services_from_yclients()
    """
    from services_app.models import Service, ServiceOption
    
    api = get_yclients_api()
    yclients_services = api.get_services()
    
    logger.info(f"Found {len(yclients_services)} services in YClients")
    
    for yc_service in yclients_services:
        # Ищем или создаём услугу в Django
        service, created = Service.objects.get_or_create(
            name=yc_service["title"],
            defaults={
                "description": yc_service.get("comment", ""),
                "is_active": True,
            }
        )
        
        # Создаём/обновляем ServiceOption
        option, opt_created = ServiceOption.objects.update_or_create(
            service=service,
            duration_min=yc_service.get("duration", 60),
            defaults={
                "price": yc_service.get("price_min", 0),
                "yclients_service_id": str(yc_service["id"]),
                "is_active": True,
            }
        )
        
        action = "created" if created else "updated"
        logger.info(f"✅ Service {action}: {service.name}")
    
    logger.info("✅ Sync completed!")