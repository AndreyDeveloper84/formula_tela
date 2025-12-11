import requests
import logging
from typing import Dict, List, Optional
from django.conf import settings

logger = logging.getLogger(__name__)


class YClientsAPIError(Exception):
    """Базовое исключение для ошибок YClients API"""
    pass


class YClientsAPI:
    """
    Клиент для работы с YClients REST API v2
    
    Документация: https://developers.yclients.com/ru/
    """
    
    BASE_URL = "https://api.yclients.com/api/v1"
    
    def __init__(self, partner_token: str, user_token: str, company_id: str):
        self.partner_token = partner_token
        self.user_token = user_token
        self.company_id = company_id
        
        self.headers = {
            "Accept": "application/vnd.yclients.v2+json",
            "Authorization": f"Bearer {self.partner_token}, User {self.user_token}",
            "Content-Type": "application/json",
        }
    
    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None
    ) -> Dict:
        """
        Базовый метод для выполнения HTTP-запросов к API
        
        Args:
            method: HTTP-метод (GET, POST, PUT, DELETE)
            endpoint: путь API (например, '/services/123')
            params: query-параметры
            data: тело запроса (для POST/PUT)
        
        Returns:
            ПОЛНЫЙ ответ API в виде словаря (включая success, data, meta)
        
        Raises:
            YClientsAPIError: при ошибке запроса
        """
        url = f"{self.BASE_URL}{endpoint}"
        
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                params=params,
                json=data,
                timeout=30
            )
            
            # Логируем запрос для отладки
            logger.debug(f"YClients API: {method} {url} → {response.status_code}")
            
            # Проверяем HTTP статус
            if response.status_code >= 400:
                logger.error(
                    f"HTTP Error {response.status_code}: {response.text}"
                )
                raise YClientsAPIError(
                    f"HTTP {response.status_code}: {response.text}"
                )
            
            # Парсим JSON
            json_response = response.json()
            
            # ВАЖНО: Возвращаем ПОЛНЫЙ ответ, не только data!
            return json_response
            
        except requests.exceptions.Timeout:
            raise YClientsAPIError("API request timeout")
        except requests.exceptions.ConnectionError:
            raise YClientsAPIError("API connection error")
        except requests.exceptions.HTTPError as e:
            raise YClientsAPIError(f"HTTP error {e.response.status_code}: {e.response.text}")
        except ValueError as e:
            # JSON decode error
            raise YClientsAPIError(f"Invalid JSON response: {str(e)}")
        except Exception as e:
            logger.exception(f"Unexpected error in YClients API request: {e}")
            raise YClientsAPIError(f"Unexpected error: {str(e)}")
    
    @staticmethod
    def authenticate(login: str, password: str, partner_token: str) -> str:
        """
        Авторизация и получение User Token
        
        Args:
            login: логин пользователя (телефон: 79023413065)
            password: пароль
            partner_token: токен партнёра
        
        Returns:
            user_token для дальнейших запросов
        
        Example:
            user_token = YClientsAPI.authenticate(
                login="79023413065",
                password="karzakova1",
                partner_token="gmn9rncz9nhr66yj23yc"
            )
        """
        url = "https://api.yclients.com/api/v1/auth"
        
        headers = {
            "Accept": "application/vnd.yclients.v2+json",
            "Authorization": f"Bearer {partner_token}",
            "Content-Type": "application/json",
        }
        
        data = {
            "login": login,
            "password": password
        }
        
        try:
            response = requests.post(url, json=data, headers=headers, timeout=30)
            response.raise_for_status()
            
            json_response = response.json()
            
            if not json_response.get("success"):
                error_msg = json_response.get("meta", {}).get("message", "Auth failed")
                raise YClientsAPIError(f"Authentication failed: {error_msg}")
            
            user_token = json_response["data"]["user_token"]
            logger.info(f"✅ Successfully authenticated user: {login}")
            
            return user_token
            
        except Exception as e:
            logger.error(f"❌ Authentication failed for {login}: {e}")
            raise YClientsAPIError(f"Authentication error: {str(e)}")
            
    @classmethod
    def from_credentials(
        cls,
        login: str,
        password: str,
        partner_token: Optional[str] = None,
        company_id: Optional[str] = None
    ) -> "YClientsAPI":
        """
        Создать API-клиент через авторизацию по логину/паролю
        
        Args:
            login: логин (телефон)
            password: пароль
            partner_token: токен партнёра (по умолчанию из settings)
            company_id: ID компании (по умолчанию из settings)
        
        Returns:
            Экземпляр YClientsAPI с полученным user_token
        
        Example:
            api = YClientsAPI.from_credentials(
                login="79023413065",
                password="karzakova1"
            )
        """
        from django.conf import settings
        
        partner_token = partner_token or settings.YCLIENTS_PARTNER_TOKEN
        company_id = company_id or settings.YCLIENTS_COMPANY_ID
        
        if not partner_token or not company_id:
            raise YClientsAPIError("Partner token and company ID must be configured")
        
        # Получаем user token через авторизацию
        user_token = cls.authenticate(login, password, partner_token)
        
        # Создаём экземпляр с полученным токеном
        return cls(
            partner_token=partner_token,
            user_token=user_token,
            company_id=company_id
        )

    def get_staff(self) -> List[Dict]:
        """
        Получить список мастеров (сотрудников) компании
        
        Returns:
            Список мастеров:
            [
                {
                    "id": 456,
                    "name": "Ирина Хабибулина",
                    "specialization": "Массажист",
                    "avatar": "https://...",
                    "bookable": True,  # доступен для онлайн-записи
                    "position": {"id": 1, "title": "Мастер"},
                    "rating": 4.8,
                    "votes_count": 125
                },
                ...
            ]
        
        Example:
            staff = api.get_staff()
            bookable_staff = [s for s in staff if s.get('bookable')]
            print(f"Доступно мастеров: {len(bookable_staff)}")
        """
        endpoint = f"/staff/{self.company_id}"
        
        response = self._request('GET', endpoint)
        
        # Возвращаем список мастеров
        if isinstance(response, list):
            return response
        elif isinstance(response, dict) and 'data' in response:
            return response['data']
        else:
            logger.warning(f"Unexpected staff response format: {type(response)}")
            return []

    def get_book_dates(self, staff_id: int) -> Dict:
        """
        Получить доступные даты для записи к мастеру
        """
        endpoint = f"/book_dates/{self.company_id}"
        params = {'staff_id': staff_id}
        
        response = self._request('GET', endpoint, params=params)
        
        # Проверяем success
        if not response.get('success', False):
            error_msg = response.get('meta', {}).get('message', 'Unknown error')
            raise YClientsAPIError(f"Failed to get book dates: {error_msg}")
        
        data = response.get('data', {})
        
        logger.info(
            f"✅ Доступных дат для мастера {staff_id}: "
            f"{len(data.get('booking_dates', []))}"
        )
        
        return data


    def get_available_times(
        self,
        staff_id: int,
        date: str,  # "2025-12-15"
        service_id: Optional[int] = None
    ) -> List[str]:
        """
        Получить свободные временные слоты для записи
        """
        endpoint = f"/book_times/{self.company_id}/{staff_id}/{date}"
        
        params = {}
        if service_id:
            params['service_id'] = service_id
        
        try:
            logger.info(
                f"🔍 Запрос свободного времени: staff={staff_id}, "
                f"date={date}, service_id={service_id}"
            )
            
            response = self._request('GET', endpoint, params=params)
            
            # Проверяем success
            if not response.get('success', False):
                logger.warning(
                    f"⚠️ API вернул success=false для book_times: {response}"
                )
                return []
            
            # Извлекаем data
            data = response.get('data', [])
            
            logger.debug(f"Raw API response data type: {type(data)}")
            logger.debug(f"Raw API response data: {data}")
            
            # Обрабатываем разные форматы
            times = []
            
            if isinstance(data, list):
                # Если список строк ['09:00', '10:00', ...]
                if data and isinstance(data[0], str):
                    times = data
                # Если список словарей [{'time': '09:00'}, ...]
                elif data and isinstance(data[0], dict):
                    for item in data:
                        if 'time' in item:
                            times.append(item['time'])
                        elif 'datetime' in item:
                            # Извлекаем только время из datetime
                            dt = item['datetime']
                            if isinstance(dt, str) and 'T' in dt:
                                times.append(dt.split('T')[1][:5])  # "HH:MM"
                            else:
                                times.append(str(dt))
                        elif 'seance_date' in item:
                            times.append(item['seance_date'])
            elif isinstance(data, dict):
                # Если словарь с ключом 'times' или 'slots' или 'seances'
                times = data.get('times', data.get('slots', data.get('seances', [])))
                
                # Если это список словарей, извлекаем time
                if times and isinstance(times[0], dict):
                    times = [
                        t.get('time', t.get('datetime', str(t)))
                        for t in times
                    ]
            
            logger.info(
                f"✅ Свободных слотов для мастера {staff_id} "
                f"на {date}: {len(times)}"
            )
            
            return times
            
        except YClientsAPIError as e:
            logger.error(
                f"❌ Ошибка получения времени для staff_id={staff_id}, "
                f"date={date}, service_id={service_id}: {e}"
            )
            return []
    

        """
        Создать запись клиента в YClients
        
        Args:
            staff_id: ID мастера
            services: Список ID услуг [123, 456]
            datetime: Дата и время в формате "2025-12-15T10:00:00"
            client: Данные клиента
                {
                    "name": "Иван Петров",
                    "phone": "79001234567",
                    "email": "ivan@example.com"
                }
            comment: Комментарий к записи
            notify_by_sms: За сколько часов отправить SMS (0 = не отправлять)
            notify_by_email: За сколько часов отправить Email (0 = не отправлять)
        
        Returns:
            {
                'id': 1,  # Наш ID
                'record_id': 123456,  # ID в YClients
                'record_hash': 'abc123...'  # Hash записи
            }
        
        Example:
            >>> api = get_yclients_api()
            >>> result = api.create_booking(
            ...     staff_id=4416525,
            ...     services=[10461107, 10461108],  # ID услуг из YClients
            ...     datetime="2025-12-15T10:00:00",
            ...     client={
            ...         "name": "Тест Тестов",
            ...         "phone": "79001234567",
            ...         "email": "test@example.com"
            ...     },
            ...     comment="Тестовая запись"
            ... )
            >>> print(result['record_id'])
            123456
        """
        endpoint = f"/book_record/{self.company_id}"
        
        # Формируем данные запроса согласно документации
        data = {
            "phone": client.get("phone"),
            "fullname": client.get("name"),
            "email": client.get("email", ""),
            "appointments": [
                {
                    "id": 1,  # ID для обратной связи (можем использовать любое число)
                    "services": services,  # Массив ID услуг
                    "staff_id": staff_id,
                    "datetime": datetime
                }
            ],
            "notify_by_sms": notify_by_sms,
            "notify_by_email": notify_by_email
        }
        
        if comment:
            data["comment"] = comment
        
        logger.info(
            f"🔖 Создание записи: staff={staff_id}, "
            f"datetime={datetime}, client={client.get('name')}, "
            f"services={services}"
        )
        
        try:
            response = self._request('POST', endpoint, data=data)
            
            # Проверяем success
            if not response.get('success', False):
                error_msg = response.get('meta', {}).get('message', 'Unknown error')
                raise YClientsAPIError(f"Failed to create booking: {error_msg}")
            
            # Извлекаем данные первой (и единственной) записи
            bookings = response.get('data', [])
            
            if not bookings:
                raise YClientsAPIError("No booking data returned")
            
            booking_data = bookings[0]  # Берём первую запись
            
            logger.info(
                f"✅ Запись создана! "
                f"Record ID: {booking_data.get('record_id')}, "
                f"Hash: {booking_data.get('record_hash')}"
            )
            
            return booking_data
            
        except YClientsAPIError as e:
            logger.error(f"❌ Ошибка создания записи: {e}")
            raise
    
    def create_booking(
        self,
        staff_id: int,
        services: List[int],
        datetime: str,
        client: Dict,
        comment: Optional[str] = None,
        notify_by_sms: int = 0,
        notify_by_email: int = 0
    ) -> Dict:
        """Создать запись клиента в YClients"""
        endpoint = f"/book_record/{self.company_id}"
        
        data = {
            "phone": client.get("phone"),
            "fullname": client.get("name"),
            "email": client.get("email", ""),
            "appointments": [
                {
                    "id": 1,
                    "services": services,
                    "staff_id": staff_id,
                    "datetime": datetime
                }
            ],
            "notify_by_sms": notify_by_sms,
            "notify_by_email": notify_by_email
        }
        
        if comment:
            data["comment"] = comment
        
        logger.info(
            f"🔖 Создание записи: staff={staff_id}, "
            f"datetime={datetime}, services={services}"
        )
        
        try:
            response = self._request('POST', endpoint, data=data)
            
            if not response.get('success', False):
                error_msg = response.get('meta', {}).get('message', 'Unknown error')
                raise YClientsAPIError(f"Failed to create booking: {error_msg}")
            
            bookings = response.get('data', [])
            
            if not bookings:
                raise YClientsAPIError("No booking data returned")
            
            booking_data = bookings[0]
            
            logger.info(
                f"✅ Запись создана! "
                f"Record ID: {booking_data.get('record_id')}"
            )
            
            return booking_data
            
        except YClientsAPIError as e:
            logger.error(f"❌ Ошибка создания записи: {e}")
            raise

def get_yclients_api() -> YClientsAPI:
    """
    Получить готовый экземпляр YClientsAPI из настроек
    
    Использует токены из .env через Django settings
    
    Returns:
        Сконфигурированный YClientsAPI клиент
    
    Example:
        from services_app.yclients_api import get_yclients_api
        
        api = get_yclients_api()
        services = api.get_services()
    """
    from django.conf import settings
    
    # Проверка наличия всех необходимых настроек
    required_settings = {
        'YCLIENTS_PARTNER_TOKEN': settings.YCLIENTS_PARTNER_TOKEN,
        'YCLIENTS_USER_TOKEN': settings.YCLIENTS_USER_TOKEN,
        'YCLIENTS_COMPANY_ID': settings.YCLIENTS_COMPANY_ID,
    }
    
    missing = [k for k, v in required_settings.items() if not v]
    if missing:
        raise YClientsAPIError(
            f"Missing YClients settings: {', '.join(missing)}\n"
            "Please configure them in .env file"
        )
    
    return YClientsAPI(
        partner_token=settings.YCLIENTS_PARTNER_TOKEN,
        user_token=settings.YCLIENTS_USER_TOKEN,
        company_id=settings.YCLIENTS_COMPANY_ID
    )