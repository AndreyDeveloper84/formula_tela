from django import forms

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
