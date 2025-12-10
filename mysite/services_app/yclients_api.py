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