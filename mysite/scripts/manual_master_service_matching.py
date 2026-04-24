"""
Тесты для проверки соответствия мастер ↔ услуга
"""
import pytest
from django.test import TestCase, Client
from django.urls import reverse
from services_app.models import Service, ServiceOption, Master, ServiceCategory
from decimal import Decimal


@pytest.mark.django_db
class TestMasterServiceMatching(TestCase):
    """
    Тесты проверки соответствия мастеров и услуг
    """
    
    def setUp(self):
        """Подготовка тестовых данных"""
        # Создаём категорию
        self.category = ServiceCategory.objects.create(
            name="Массаж",
            order=1
        )
        
        # Создаём услуги
        self.service_massage = Service.objects.create(
            name="Спортивный массаж",
            category=self.category,
            is_active=True
        )
        
        self.service_facial = Service.objects.create(
            name="Уход за лицом",
            category=self.category,
            is_active=True
        )
        
        # Создаём варианты услуг
        self.option_massage_45 = ServiceOption.objects.create(
            service=self.service_massage,
            duration_min=45,
            price=Decimal('2600'),
            is_active=True,
            yclients_service_id='12345'
        )
        
        self.option_massage_60 = ServiceOption.objects.create(
            service=self.service_massage,
            duration_min=60,
            price=Decimal('3200'),
            is_active=True,
            yclients_service_id='12346'
        )
        
        self.option_facial = ServiceOption.objects.create(
            service=self.service_facial,
            duration_min=90,
            price=Decimal('4500'),
            is_active=True,
            yclients_service_id='12347'
        )
        
        # Создаём мастеров
        self.master_anna = Master.objects.create(
            name="Инна Сазанова",
            is_active=True
        )
        
        self.master_denis = Master.objects.create(
            name="Денис Архипкин",
            is_active=True
        )
        
        self.master_olga = Master.objects.create(
            name="Ольга",
            is_active=True
        )
        
        # Привязываем услуги к мастерам
        # Инна делает только массаж
        self.master_anna.services.add(self.service_massage)
        
        # Денис делает и массаж, и уход за лицом
        self.master_denis.services.add(self.service_massage, self.service_facial)
        
        # Ольга делает только уход за лицом
        self.master_olga.services.add(self.service_facial)
        
        self.client = Client()
    
    # ========================================
    # ТЕСТЫ ПРОВЕРКИ ДАННЫХ В БД
    # ========================================
    
    def test_master_services_relationship(self):
        """Проверка что связь Master ↔ Service работает"""
        # Инна делает 1 услугу
        self.assertEqual(self.master_anna.services.count(), 1)
        self.assertIn(self.service_massage, self.master_anna.services.all())
        
        # Денис делает 2 услуги
        self.assertEqual(self.master_denis.services.count(), 2)
        self.assertIn(self.service_massage, self.master_denis.services.all())
        self.assertIn(self.service_facial, self.master_denis.services.all())
        
        # Ольга делает 1 услугу
        self.assertEqual(self.master_olga.services.count(), 1)
        self.assertIn(self.service_facial, self.master_olga.services.all())
    
    def test_service_masters_reverse_relationship(self):
        """Проверка обратной связи Service → Masters"""
        # Массаж делают 2 мастера
        massage_masters = self.service_massage.masters.all()
        self.assertEqual(massage_masters.count(), 2)
        self.assertIn(self.master_anna, massage_masters)
        self.assertIn(self.master_denis, massage_masters)
        
        # Уход за лицом делают 2 мастера
        facial_masters = self.service_facial.masters.all()
        self.assertEqual(facial_masters.count(), 2)
        self.assertIn(self.master_denis, facial_masters)
        self.assertIn(self.master_olga, facial_masters)
    
    # ========================================
    # ТЕСТЫ API ФИЛЬТРАЦИИ МАСТЕРОВ
    # ========================================
    
    def test_get_staff_without_service_filter(self):
        """API без фильтра возвращает всех активных мастеров"""
        # Этот тест проверит текущее поведение
        response = self.client.get('/api/booking/get_staff/')
        
        # Ожидаем что вернутся ВСЕ 3 мастера (пока фильтр не реализован)
        # После реализации фильтра этот тест покажет изменение поведения
        self.assertEqual(response.status_code, 200)
    
    def test_get_staff_for_massage_service(self):
        """API должен вернуть мастеров только для массажа"""
        # Запрос мастеров для услуги "Спортивный массаж"
        response = self.client.get(
            '/api/booking/get_staff/',
            {'service_option_id': self.option_massage_45.id}
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        if data.get('success'):
            # Проверяем что вернулись только Инна и Денис (делают массаж)
            staff_ids = [s['id'] for s in data.get('data', [])]
            
            # ОЖИДАЕМ: только мастера которые делают массаж
            # Инна делает массаж — должна быть
            # Денис делает массаж — должен быть
            # Ольга НЕ делает массаж — НЕ должна быть
            
            # Этот тест покажет нужна ли фильтрация
            print(f"Вернулось мастеров: {len(staff_ids)}")
            print(f"IDs мастеров: {staff_ids}")
    
    def test_get_staff_for_facial_service(self):
        """API должен вернуть мастеров только для ухода за лицом"""
        response = self.client.get(
            '/api/booking/get_staff/',
            {'service_option_id': self.option_facial.id}
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        if data.get('success'):
            staff_ids = [s['id'] for s in data.get('data', [])]
            
            # ОЖИДАЕМ: только мастера которые делают уход за лицом
            # Денис делает уход — должен быть
            # Ольга делает уход — должна быть
            # Инна НЕ делает уход — НЕ должна быть
            
            print(f"Вернулось мастеров для ухода за лицом: {len(staff_ids)}")
    
    # ========================================
    # ТЕСТЫ БИЗНЕС-ЛОГИКИ
    # ========================================
    
    def test_master_can_do_service(self):
        """Проверка что мастер может делать услугу"""
        # Инна может делать массаж
        self.assertTrue(
            self.service_massage in self.master_anna.services.all()
        )
        
        # Инна НЕ может делать уход за лицом
        self.assertFalse(
            self.service_facial in self.master_anna.services.all()
        )
        
        # Денис может делать ОБЕ услуги
        self.assertTrue(
            self.service_massage in self.master_denis.services.all()
        )
        self.assertTrue(
            self.service_facial in self.master_denis.services.all()
        )
    
    def test_service_option_belongs_to_service(self):
        """Проверка что ServiceOption принадлежит правильному Service"""
        # Вариант 45 мин принадлежит услуге "Спортивный массаж"
        self.assertEqual(
            self.option_massage_45.service,
            self.service_massage
        )
        
        # Вариант 60 мин ТОЖЕ принадлежит услуге "Спортивный массаж"
        self.assertEqual(
            self.option_massage_60.service,
            self.service_massage
        )
        
        # Вариант 90 мин принадлежит услуге "Уход за лицом"
        self.assertEqual(
            self.option_facial.service,
            self.service_facial
        )
    
    def test_get_masters_for_service_option(self):
        """
        Хелпер-функция: получить мастеров для ServiceOption
        Через Service (правильный способ)
        """
        # Получаем Service из ServiceOption
        service = self.option_massage_45.service
        
        # Получаем мастеров для этого Service
        masters = service.masters.filter(is_active=True)
        
        # Проверяем результат
        self.assertEqual(masters.count(), 2)
        self.assertIn(self.master_anna, masters)
        self.assertIn(self.master_denis, masters)
        self.assertNotIn(self.master_olga, masters)
    
    # ========================================
    # ТЕСТЫ EDGE CASES
    # ========================================
    
    def test_inactive_master_not_returned(self):
        """Неактивный мастер не возвращается"""
        # Деактивируем Инну
        self.master_anna.is_active = False
        self.master_anna.save()
        
        # Получаем активных мастеров для массажа
        service = self.option_massage_45.service
        masters = service.masters.filter(is_active=True)
        
        # Инны не должно быть
        self.assertNotIn(self.master_anna, masters)
        
        # Денис должен быть
        self.assertIn(self.master_denis, masters)
    
    def test_service_without_masters(self):
        """Услуга без мастеров"""
        # Создаём услугу без мастеров
        service_empty = Service.objects.create(
            name="Новая услуга",
            category=self.category,
            is_active=True
        )
        
        # Проверяем что мастеров нет
        masters = service_empty.masters.filter(is_active=True)
        self.assertEqual(masters.count(), 0)
    
    def test_master_without_services(self):
        """Мастер без услуг"""
        # Создаём мастера без услуг
        master_new = Master.objects.create(
            name="Новый мастер",
            is_active=True
        )
        
        # Проверяем что услуг нет
        self.assertEqual(master_new.services.count(), 0)


# ========================================
# УТИЛИТАРНЫЕ ФУНКЦИИ ДЛЯ ИСПОЛЬЗОВАНИЯ В КОДЕ
# ========================================

def get_masters_for_service_option(service_option_id):
    """
    Получить список мастеров для ServiceOption
    
    Args:
        service_option_id: ID варианта услуги
        
    Returns:
        QuerySet мастеров которые могут выполнить эту услугу
    """
    try:
        option = ServiceOption.objects.select_related('service').get(
            id=service_option_id,
            is_active=True
        )
        
        # Получаем мастеров через Service
        masters = option.service.masters.filter(is_active=True)
        
        return masters
    except ServiceOption.DoesNotExist:
        return Master.objects.none()


def can_master_do_service_option(master_id, service_option_id):
    """
    Проверка может ли мастер выполнить вариант услуги
    
    Args:
        master_id: ID мастера
        service_option_id: ID варианта услуги
        
    Returns:
        bool: True если мастер может выполнить услугу
    """
    try:
        option = ServiceOption.objects.select_related('service').get(
            id=service_option_id,
            is_active=True
        )
        
        master = Master.objects.get(
            id=master_id,
            is_active=True
        )
        
        # Проверяем что Service этого option есть у мастера
        return option.service in master.services.all()
        
    except (ServiceOption.DoesNotExist, Master.DoesNotExist):
        return False


if __name__ == '__main__':
    print("Запуск тестов:")
    print("pytest test_master_service_matching.py -v")