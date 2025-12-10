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
            Ответ API в виде словаря
        
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
            
            response.raise_for_status()
            
            json_response = response.json()
            
            # YClients возвращает {"success": true/false, "data": {...}}
            if not json_response.get("success", False):
                error_msg = json_response.get("meta", {}).get("message", "Unknown error")
                raise YClientsAPIError(f"API returned error: {error_msg}")
            
            return json_response.get("data", {})
            
        except requests.exceptions.Timeout:
            raise YClientsAPIError("API request timeout")
        except requests.exceptions.ConnectionError:
            raise YClientsAPIError("API connection error")
        except requests.exceptions.HTTPError as e:
            raise YClientsAPIError(f"HTTP error {e.response.status_code}: {e.response.text}")
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