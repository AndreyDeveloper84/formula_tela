from decimal import Decimal
from django import template
from django.contrib.humanize.templatetags.humanize import intcomma

register = template.Library()

# правильные формы слов для русского
FORMS = {
    "session": ("процедура", "процедуры", "процедур"),
    "zone":    ("зона", "зоны", "зон"),
    "visit":   ("визит", "визита", "визитов"),
}
DEFAULT_FORMS = ("единица", "единицы", "единиц")

def _plural_ru(n: int, forms):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]

def _rub(val):
    # аккуратное форматирование ₽ для int/float/Decimal
    if val is None:
        return ""
    if isinstance(val, Decimal):
        q = val.quantize(Decimal("1")) if val == val.to_integral() else val.quantize(Decimal("1.00"))
        num = intcomma(q)
    else:
        num = intcomma(val)
    return f"{num} ₽"

@register.filter
def option_label(opt):
    """Строка вида:
    '60 мин × 10 процедур — 14 000 ₽ (1 400 ₽/проц.)'
    Для единицы (units=1) покажет: '60 мин — 2 500 ₽'
    """
    if not opt:
        return ""
    forms = FORMS.get(getattr(opt, "unit_type", ""), DEFAULT_FORMS)

    base = f"{opt.duration_min} мин"
    units = getattr(opt, "units", 1) or 1

    # часть про количество единиц
    units_part = f" × {units} {_plural_ru(units, forms)}" if units > 1 else ""

    # цена итого
    price_part = _rub(getattr(opt, "price", None))

    # цена за единицу (если их >1)
    per_unit_part = ""
    if units > 1 and getattr(opt, "price", None):
        per = (opt.price / units) if units else None
        per_unit_part = f" ({_rub(per)} за {_plural_ru(1, forms)})"

    return f"{base}{units_part} — {price_part}{per_unit_part}"
