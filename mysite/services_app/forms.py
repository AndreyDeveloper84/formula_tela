from django import forms
from django.core.validators import RegexValidator
from services_app.models import ServiceOption
from services_app.yclients_api import get_yclients_api, YClientsAPIError
from datetime import datetime, timedelta
import re


class ServiceCSVImportForm(forms.Form):
    file = forms.FileField(label="CSV файл")
    update_existing = forms.BooleanField(
        required=False, initial=True,
        label="Обновлять существующие услуги (по name внутри категории)"
    )
    delimiter = forms.ChoiceField(
        choices=[(",", "Запятая ,"), (";", "Точка с запятой ;"), ("\t", "Табуляция \\t")],
        initial=",", label="Разделитель"
    )


"""
Формы для записи клиентов через YClients
"""

class BookingStepForm(forms.Form):
    """
    Базовая форма для пошаговой записи
    """
    pass


class BookingStep1Form(BookingStepForm):
    """
    Шаг 1: Выбор услуги
    """
    service_option = forms.ModelChoiceField(
        queryset=ServiceOption.objects.filter(is_active=True).select_related('service'),
        label="Выберите услугу",
        widget=forms.RadioSelect,
        empty_label=None,
        error_messages={
            'required': 'Пожалуйста, выберите услугу',
            'invalid_choice': 'Выбранная услуга недоступна',
        }
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Группируем услуги по категориям для удобства
        self.fields['service_option'].queryset = (
            ServiceOption.objects
            .filter(is_active=True, service__is_active=True)
            .select_related('service', 'service__category')
            .order_by('service__category__order', 'service__name', 'order')
        )


class BookingStep2Form(BookingStepForm):
    """
    Шаг 2: Выбор мастера
    """
    staff_id = forms.ChoiceField(
        label="Выберите мастера",
        widget=forms.RadioSelect,
        error_messages={
            'required': 'Пожалуйста, выберите мастера',
        }
    )
    
    def __init__(self, service_option_id=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        if service_option_id:
            try:
                # Получаем вариант услуги
                option = ServiceOption.objects.get(pk=service_option_id)
                
                # Получаем мастеров из YClients
                api = get_yclients_api()
                
                # Если у услуги есть yclients_service_id, фильтруем мастеров
                if option.yclients_service_id:
                    staff_list = api.get_staff(service_id=int(option.yclients_service_id))
                else:
                    staff_list = api.get_staff()
                
                # Формируем choices
                choices = [(0, "Любой мастер")]
                choices += [(str(s['id']), s['name']) for s in staff_list if s.get('bookable', True)]
                
                self.fields['staff_id'].choices = choices
                
            except ServiceOption.DoesNotExist:
                self.fields['staff_id'].choices = [(0, "Услуга не найдена")]
            except YClientsAPIError as e:
                self.fields['staff_id'].choices = [(0, f"Ошибка загрузки мастеров: {str(e)}")]


class BookingStep3Form(BookingStepForm):
    """
    Шаг 3: Выбор даты и времени
    """
    date = forms.DateField(
        label="Выберите дату",
        widget=forms.DateInput(attrs={'type': 'date', 'min': datetime.now().date().isoformat()}),
        error_messages={
            'required': 'Пожалуйста, выберите дату',
            'invalid': 'Некорректная дата',
        }
    )
    
    time = forms.ChoiceField(
        label="Выберите время",
        widget=forms.RadioSelect,
        error_messages={
            'required': 'Пожалуйста, выберите время',
        }
    )
    
    def __init__(self, service_option_id=None, staff_id=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Если передана дата, загружаем доступное время
        if 'data' in kwargs and kwargs['data'].get('date') and service_option_id and staff_id:
            date_str = kwargs['data']['date']
            
            try:
                option = ServiceOption.objects.get(pk=service_option_id)
                
                if option.yclients_service_id:
                    api = get_yclients_api()
                    
                    # Конвертируем дату в нужный формат
                    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                    date_formatted = date_obj.strftime('%Y-%m-%d')
                    
                    # Получаем доступное время
                    times = api.get_available_times(
                        service_id=int(option.yclients_service_id),
                        staff_id=int(staff_id),
                        date=date_formatted
                    )
                    
                    if times:
                        self.fields['time'].choices = [(t, t) for t in times]
                    else:
                        self.fields['time'].choices = [('', 'Нет свободного времени на эту дату')]
                else:
                    self.fields['time'].choices = [('', 'Услуга не привязана к YClients')]
                    
            except ServiceOption.DoesNotExist:
                self.fields['time'].choices = [('', 'Услуга не найдена')]
            except YClientsAPIError as e:
                self.fields['time'].choices = [('', f'Ошибка загрузки времени: {str(e)}')]
        else:
            self.fields['time'].choices = [('', 'Сначала выберите дату')]
    
    def clean_date(self):
        """Проверяем, что дата не в прошлом"""
        date = self.cleaned_data.get('date')
        if date and date < datetime.now().date():
            raise forms.ValidationError('Нельзя выбрать прошедшую дату')
        return date


class BookingStep4Form(BookingStepForm):
    """
    Шаг 4: Данные клиента
    """
    
    phone_validator = RegexValidator(
        regex=r'^(\+7|8)?[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}$',
        message='Введите корректный номер телефона (например: +7 999 123-45-67 или 89991234567)'
    )
    
    name = forms.CharField(
        label="Ваше имя",
        max_length=100,
        widget=forms.TextInput(attrs={
            'placeholder': 'Введите ваше имя',
            'class': 'form-control'
        }),
        error_messages={
            'required': 'Пожалуйста, введите ваше имя',
            'max_length': 'Имя слишком длинное (максимум 100 символов)',
        }
    )
    
    phone = forms.CharField(
        label="Телефон",
        max_length=18,
        validators=[phone_validator],
        widget=forms.TextInput(attrs={
            'placeholder': '+7 (999) 123-45-67',
            'type': 'tel',
            'class': 'form-control'
        }),
        error_messages={
            'required': 'Пожалуйста, введите номер телефона',
        }
    )
    
    email = forms.EmailField(
        label="Email (необязательно)",
        required=False,
        widget=forms.EmailInput(attrs={
            'placeholder': 'your@email.com',
            'class': 'form-control'
        }),
        error_messages={
            'invalid': 'Введите корректный email адрес',
        }
    )
    
    comment = forms.CharField(
        label="Комментарий к записи (необязательно)",
        required=False,
        widget=forms.Textarea(attrs={
            'placeholder': 'Если у вас есть пожелания или особые указания...',
            'rows': 3,
            'class': 'form-control'
        }),
        max_length=500
    )
    
    agree_to_terms = forms.BooleanField(
        label="Я согласен(на) на обработку персональных данных",
        required=True,
        error_messages={
            'required': 'Необходимо согласие на обработку персональных данных',
        }
    )
    
    def clean_phone(self):
        """Нормализуем телефон"""
        phone = self.cleaned_data.get('phone')
        if phone:
            # Убираем все символы кроме цифр
            digits = re.sub(r'\D', '', phone)
            
            # Если начинается с 8, меняем на 7
            if digits.startswith('8'):
                digits = '7' + digits[1:]
            
            # Если не начинается с 7, добавляем
            if not digits.startswith('7'):
                digits = '7' + digits
            
            # Проверяем длину (должно быть 11 цифр)
            if len(digits) != 11:
                raise forms.ValidationError('Номер телефона должен содержать 11 цифр')
            
            return digits
        return phone
    
    def clean_name(self):
        """Проверяем имя"""
        name = self.cleaned_data.get('name')
        if name:
            # Убираем лишние пробелы
            name = ' '.join(name.split())
            
            # Проверяем что есть хотя бы одна буква
            if not any(c.isalpha() for c in name):
                raise forms.ValidationError('Имя должно содержать хотя бы одну букву')
            
            return name
        return name


# ============================================================
# ПОЛНАЯ ФОРМА (однострочная, если нужна)
# ============================================================

class BookingFullForm(forms.Form):
    """
    Полная форма записи (все поля сразу)
    Используется, если не нужна пошаговость
    """
    
    service_option = forms.ModelChoiceField(
        queryset=ServiceOption.objects.filter(is_active=True).select_related('service'),
        label="Услуга",
        error_messages={'required': 'Выберите услугу'}
    )
    
    staff_id = forms.ChoiceField(
        label="Мастер",
        error_messages={'required': 'Выберите мастера'}
    )
    
    date = forms.DateField(
        label="Дата",
        widget=forms.DateInput(attrs={'type': 'date'}),
        error_messages={'required': 'Выберите дату', 'invalid': 'Некорректная дата'}
    )
    
    time = forms.ChoiceField(
        label="Время",
        error_messages={'required': 'Выберите время'}
    )
    
    name = forms.CharField(
        label="Имя",
        max_length=100,
        error_messages={'required': 'Введите имя'}
    )
    
    phone = forms.CharField(
        label="Телефон",
        max_length=18,
        error_messages={'required': 'Введите телефон'}
    )
    
    email = forms.EmailField(
        label="Email",
        required=False
    )
    
    comment = forms.CharField(
        label="Комментарий",
        required=False,
        widget=forms.Textarea(attrs={'rows': 3})
    )
    
    agree_to_terms = forms.BooleanField(
        label="Согласие на обработку персональных данных",
        required=True,
        error_messages={'required': 'Необходимо согласие'}
    )