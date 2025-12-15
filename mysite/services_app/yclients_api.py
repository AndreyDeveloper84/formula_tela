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
        data: Optional[Dict] = None,
        headers = None,
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

        request_headers = {
            'Accept': 'application/vnd.yclients.v2+json',
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.partner_token}, User {self.user_token}'
        }
        
        if headers:
            request_headers.update(headers)
        
        try:
            logger.info(f"📤 API Request: {method} {url}")
            logger.info(f"   Params: {params}")
            if data:
                logger.info(f"   Data: {data}")
            response = requests.request(
                method=method,
                url=url,
                headers=request_headers,
                params=params,
                json=data,
                timeout=30
            )
            logger.info(f"📥 API Response: {response.status_code} ({response.elapsed.total_seconds():.2f}s)")
            logger.info(f"   Length: {len(response.text)} bytes")
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
            if isinstance(json_response, dict):
                logger.info(f"   success: {json_response.get('success')}")
                data_type = type(json_response.get('data'))
                logger.info(f"   data type: {data_type}")
                if isinstance(json_response.get('data'), list):
                    logger.info(f"   data length: {len(json_response.get('data', []))}")
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

    def get_staff(self, service_id: Optional[int] = None) -> List[dict]:
        """
        Получить список сотрудников.

        Args:
            service_id: Фильтр по ID услуги в YClients (опционально)
                       Если указан, возвращает только мастеров, которые могут оказывать эту услугу
            
        Returns:
            List[dict]: Список мастеров с полями id, name, specialization, rating, avatar
        """
        logger.info(f"👥 Запрос списка мастеров" + (f" для услуги {service_id}" if service_id else ""))
        
        try:
            if service_id:
                # ✅ НАДЕЖНЫЙ ПОДХОД: Получаем мастеров через book_staff и проверяем услуги каждого
                # Это гарантирует, что вернутся только те мастера, которые действительно оказывают услугу
                return self._get_staff_fallback_filter(service_id)
            else:
                # Обычный список всех мастеров
                endpoint = f'/company/{self.company_id}/staff'
                logger.debug(f"📤 Запрос: GET {endpoint}")
                response = self._request('GET', endpoint)
                
                logger.debug(f"📥 Raw staff response type: {type(response)}")
                
                staff_list = []
                
                # Обрабатываем ответ
                if isinstance(response, dict):
                    if 'data' in response:
                        data = response['data']
                        if isinstance(data, list):
                            staff_list = data
                        elif isinstance(data, dict) and 'staff' in data:
                            staff_list = data['staff'] if isinstance(data['staff'], list) else []
                    elif 'staff' in response:
                        staff_list = response['staff'] if isinstance(response['staff'], list) else []
                elif isinstance(response, list):
                    staff_list = response
                
                logger.debug(f"📋 Извлечено мастеров из ответа: {len(staff_list)}")
                
                # Форматируем данные
                result = []
                for staff in staff_list:
                    # Пропускаем неактивных
                    if 'active' in staff and not staff.get('active', True):
                        continue
                    
                    # Пропускаем тех, кто не принимает запись онлайн
                    if 'bookable' in staff and not staff.get('bookable', True):
                        continue
                    
                    # Пропускаем скрытых/уволенных мастеров
                    if staff.get('hidden', 0) == 1 or staff.get('fired', 0) == 1:
                        continue
                    
                    result.append({
                        'id': staff.get('id'),
                        'name': staff.get('name', ''),
                        'specialization': staff.get('specialization', ''),
                        'rating': staff.get('rating', 0),
                        'avatar': staff.get('avatar', ''),
                        'position': staff.get('position', {}).get('title', '') if isinstance(staff.get('position'), dict) else ''
                    })
                
                logger.info(f"✅ Отфильтровано активных мастеров: {len(result)} из {len(staff_list)}")
                
                return result
        
        except Exception as e:
            logger.error(f"❌ Ошибка получения мастеров: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []

    def _get_staff_fallback_filter(self, service_id: int) -> List[dict]:
        """
        Fallback метод: получает мастеров через book_staff и проверяет услуги каждого
        Используется, если основной метод не сработал
        """
        logger.info(f"🔄 Используем fallback метод для фильтрации мастеров по услуге {service_id}")
        
        try:
            # Получаем мастеров через book_staff
            endpoint = f'/book_staff/{self.company_id}'
            params = {'service_id': service_id}
            response = self._request('GET', endpoint, params=params)
            
            staff_list = []
            if isinstance(response, dict):
                if 'data' in response:
                    data = response['data']
                    if isinstance(data, list):
                        staff_list = data
                    elif isinstance(data, dict) and 'staff' in data:
                        staff_list = data['staff'] if isinstance(data['staff'], list) else []
                elif 'staff' in response:
                    staff_list = response['staff'] if isinstance(response['staff'], list) else []
            elif isinstance(response, list):
                staff_list = response
            
            # Проверяем услуги каждого мастера
            result = []
            for staff in staff_list:
                # Пропускаем неактивных
                if 'active' in staff and not staff.get('active', True):
                    continue
                
                if 'bookable' in staff and not staff.get('bookable', True):
                    continue
                
                if staff.get('hidden', 0) == 1 or staff.get('fired', 0) == 1:
                    continue
                
                staff_id = staff.get('id')
                if not staff_id:
                    continue
                
                # Проверяем услуги мастера
                try:
                    staff_services = self.get_staff_services(staff_id)
                    service_ids = [s.get('id') for s in staff_services if s.get('id')]
                    
                    if service_id not in service_ids:
                        logger.debug(f"⏭️ Мастер {staff.get('name', 'Unknown')} (ID: {staff_id}) не оказывает услугу {service_id}")
                        continue
                    
                    logger.debug(f"✅ Мастер {staff.get('name', 'Unknown')} (ID: {staff_id}) оказывает услугу {service_id}")
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось получить услуги для мастера {staff_id}: {e}")
                    continue
                
                result.append({
                    'id': staff.get('id'),
                    'name': staff.get('name', ''),
                    'specialization': staff.get('specialization', ''),
                    'rating': staff.get('rating', 0),
                    'avatar': staff.get('avatar', ''),
                    'position': staff.get('position', {}).get('title', '') if isinstance(staff.get('position'), dict) else ''
                })
            
            logger.info(f"✅ Fallback: отфильтровано мастеров для услуги {service_id}: {len(result)} из {len(staff_list)}")
            return result
            
        except Exception as e:
            logger.error(f"❌ Ошибка в fallback методе: {e}")
            return []

    def get_staff_services(self, staff_id: int) -> List[Dict]:
        """
        Получить услуги конкретного сотрудника
        
        Args:
            staff_id: ID сотрудника
        
        Returns:
            List[Dict]: Список услуг сотрудника
        """
        logger.info(f"📋 Запрос услуг для мастера {staff_id}")
        
        try:
            # YClients API v2: GET /company/{company_id}/services?staff_id={staff_id}
            endpoint = f'/company/{self.company_id}/services'
            params = {'staff_id': staff_id}
            
            response = self._request('GET', endpoint, params=params)
            
            if not response.get('success', False):
                error_msg = response.get('meta', {}).get('message', 'Unknown error')
                logger.error(f"❌ API вернул ошибку: {error_msg}")
                return []
            
            services = response.get('data', [])
            logger.info(f"✅ Получено услуг: {len(services)}")
            
            return services
            
        except YClientsAPIError as e:
            logger.error(f"❌ Ошибка получения услуг мастера: {e}")
            return []

    def get_services(self, staff_id: Optional[int] = None, category_id: Optional[int] = None) -> List[dict]:
        """
        Получить список услуг компании
        
        Args:
            staff_id: Фильтр по ID сотрудника (опционально)
            category_id: Фильтр по ID категории (опционально)
        
        Returns:
            List[dict]: Список услуг
        """
        logger.info(f"📋 Запрос списка услуг компании")
        if staff_id:
            logger.info(f"   Фильтр по мастеру: {staff_id}")
        if category_id:
            logger.info(f"   Фильтр по категории: {category_id}")
        
        params = {}
        if staff_id:
            params['staff_id'] = staff_id
        if category_id:
            params['category_id'] = category_id
        
        try:
            endpoint = f'/company/{self.company_id}/services'
            response = self._request('GET', endpoint, params=params if params else None)
            
            if not response.get('success', False):
                error_msg = response.get('meta', {}).get('message', 'Unknown error')
                logger.error(f"❌ API вернул ошибку: {error_msg}")
                return []
            
            services = response.get('data', [])
            logger.info(f"✅ Получено услуг: {len(services)}")
            
            return services
            
        except YClientsAPIError as e:
            logger.error(f"❌ Ошибка получения услуг: {e}")
            return []

    def get_book_dates(self, staff_id: Optional[int] = None, service_ids: Optional[List[int]] = None) -> List[str]:
        """
        Получить список доступных дат для записи.
        
        Args:
            staff_id: ID мастера (опционально)
            service_ids: Массив ID услуг (опционально)
            
        Returns:
            List[str]: Список дат в формате "YYYY-MM-DD"
        """
        logger.info(f"🔍 Запрос доступных дат для мастера: {staff_id}")
        
        params = {}
        if staff_id:
            params['staff_id'] = staff_id
        if service_ids:
            params['service_ids'] = ','.join(map(str, service_ids))
        
        try:
            response = self._request(
                'GET',
                f'/book_dates/{self.company_id}',
                params=params
            )
            
            logger.debug(f"Raw book_dates response: {response}")
            
            # YClients возвращает {'success': True, 'data': {'booking_dates': [...]}}
            dates = []
            
            if isinstance(response, dict):
                # Проверяем наличие вложенной структуры
                if 'data' in response:
                    data = response['data']
                    
                    # Ищем booking_dates
                    if 'booking_dates' in data:
                        dates = data['booking_dates']
                    # Или working_dates как запасной вариант
                    elif 'working_dates' in data:
                        dates = data['working_dates']
                        
            elif isinstance(response, list):
                # Если вернули список напрямую (старый формат API)
                for item in response:
                    if isinstance(item, dict) and 'date' in item:
                        dates.append(item['date'])
                    elif isinstance(item, str):
                        dates.append(item)
            
            # Убеждаемся что dates это список строк
            if not isinstance(dates, list):
                dates = []
            
            logger.info(f"✅ Найдено доступных дат: {len(dates)}")
            if dates:
                logger.debug(f"Первые 5 дат: {dates[:5]}")
            
            # Сортируем даты
            dates.sort()
            
            return dates
            
        except Exception as e:
            logger.error(f"❌ Ошибка при получении доступных дат: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []

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