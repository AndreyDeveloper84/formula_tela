# -*- coding: utf-8 -*-
"""
Замена footer в base.html.
Запускать из mysite/mysite/:
    python fix_footer.py
"""
import re

filepath = "website/templates/website/base.html"

with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

new_footer = """    <!-- ========================= footer start ========================= -->
    <footer class="footer">
        <div class="container mb-112">
            <div class="row">
                <h3 class="wow fadeInUp" data-wow-delay=".2s">\u041a\u043e\u043d\u0442\u0430\u043a\u0442\u044b</h3>
                <div class="d-flex">
                    <div class="map wow fadeInUp" data-wow-delay=".6s">
                        <img src="{% static 'i/map-mob.jpg' %}" class="responsive mobb" alt="\u0410\u0434\u0440\u0435\u0441" loading="lazy">
                        <img src="{% static 'i/map.jpg' %}" class="responsive mn" alt="\u0410\u0434\u0440\u0435\u0441" loading="lazy">
                    </div>
                    <div class="in wow fadeInUp" data-wow-delay="1s">
                        <div class="heading semi upcs mb-30">{{ settings.salon_name|default:"\u0421\u0442\u0443\u0434\u0438\u044f \u044d\u0441\u0442\u0435\u0442\u0438\u043a\u0438 \u0424\u043e\u0440\u043c\u0443\u043b\u0430 \u0422\u0435\u043b\u0430" }}</div>
                        <ul class="contacts f20 mb-30">
                            <li>\u0410\u0434\u0440\u0435\u0441: {{ settings.address|default:"\u0433. \u041f\u0435\u043d\u0437\u0430, \u0443\u043b. \u041f\u0443\u0448\u043a\u0438\u043d\u0430, 45" }}</li>
                            <li>{{ settings.working_hours|default:"\u0415\u0436\u0435\u0434\u043d\u0435\u0432\u043d\u043e: \u0441 10:00-21:00" }}</li>
                            <li><a href="tel:{{ settings.contact_phone|default:'8 (8412) 39-34-33' }}">{{ settings.contact_phone|default:"8 (8412) 39-34-33" }}</a></li>
                        </ul>
                        <div class="mx250">
                            <a href="{% url 'website:services' %}" class="btn-black t-btn">\u0417\u0430\u043f\u0438\u0441\u0430\u0442\u044c\u0441\u044f \u043d\u0430 \u043f\u0440\u043e\u0446\u0435\u0434\u0443\u0440\u044b</a>
                            {% if settings.yandex_maps_link %}
                                <a href="{{ settings.yandex_maps_link }}" class="btn-white2 t-btn" target="_blank">\u041f\u043e\u0441\u0442\u0440\u043e\u0438\u0442\u044c \u043c\u0430\u0440\u0448\u0440\u0443\u0442</a>
                            {% elif settings.google_maps_link %}
                                <a href="{{ settings.google_maps_link }}" class="btn-white2 t-btn" target="_blank">\u041f\u043e\u0441\u0442\u0440\u043e\u0438\u0442\u044c \u043c\u0430\u0440\u0448\u0440\u0443\u0442</a>
                            {% else %}
                                <a href="#" class="btn-white2 t-btn">\u041f\u043e\u0441\u0442\u0440\u043e\u0438\u0442\u044c \u043c\u0430\u0440\u0448\u0440\u0443\u0442</a>
                            {% endif %}
                        </div>
                    </div>
                </div>
            </div>
        </div>
        <div class="container mb-56">
            <div class="row mb-30">
                <div class="col-xl-8 social wow fadeInUp" data-wow-delay="1.4s">
                    {% with tg=settings.social_media|dictget:"telegram" vk=settings.social_media|dictget:"vk" mx=settings.social_media|dictget:"max" wa=settings.social_media|dictget:"whatsapp" ig=settings.social_media|dictget:"instagram" %}
                    {% if tg %}<a href="{{ tg }}" class="btn-white2 t-btn" target="_blank">Telegram</a>{% endif %}
                    {% if vk %}<a href="{{ vk }}" class="btn-white2 t-btn" target="_blank">\u0412\u043a\u043e\u043d\u0442\u0430\u043a\u0442\u0435</a>{% endif %}
                    {% if mx %}<a href="{{ mx }}" class="btn-white2 t-btn" target="_blank">Max</a>{% endif %}
                    {% if wa %}<a href="{{ wa }}" class="btn-white2 t-btn" target="_blank">WhatsApp</a>{% endif %}
                    {% if ig %}<a href="{{ ig }}" class="btn-white2 t-btn" target="_blank">Instagram</a>{% endif %}
                    {% endwith %}
                </div>
                <div class="col-xl-4 confid text-end wow fadeInUp" data-wow-delay="1.6s">
                    <a href="#" class="btn-white2 t-btn">\u041f\u043e\u043b\u0438\u0442\u0438\u043a\u0430 \u043a\u043e\u043d\u0444\u0438\u0434\u0435\u043d\u0446\u0438\u0430\u043b\u044c\u043d\u043e\u0441\u0442\u0438</a>
                </div>
            </div>
            <div class="row wow fadeInUp" data-wow-delay="1.8s">
                <div class="col-md-12 copyright-area text-center">
                    <div class="row align-items-center">
                        <div class="col-md-12">
                            <p class="mb-40 f20">\u0426\u0435\u043d\u044b, \u0443\u043a\u0430\u0437\u0430\u043d\u043d\u044b\u0435 \u043d\u0430 \u0441\u0430\u0439\u0442\u0435 \u0438 \u0432 \u0441\u043e\u0446\u0438\u0430\u043b\u044c\u043d\u044b\u0445 \u0441\u0435\u0442\u044f\u0445 \u043f\u0440\u0438\u0432\u0435\u0434\u0435\u043d\u044b \u043a\u0430\u043a \u0441\u043f\u0440\u0430\u0432\u043e\u0447\u043d\u0430\u044f \u0438\u043d\u0444\u043e\u0440\u043c\u0430\u0446\u0438\u044f \u0438 \u043d\u0435 \u044f\u0432\u043b\u044f\u044e\u0442\u0441\u044f \u043f\u0443\u0431\u043b\u0438\u0447\u043d\u043e\u0439 \u043e\u0444\u0435\u0440\u0442\u043e\u0439. \u041c\u043e\u0433\u0443\u0442 \u0431\u044b\u0442\u044c \u0438\u0437\u043c\u0435\u043d\u0435\u043d\u044b \u0432 \u043b\u044e\u0431\u043e\u0435 \u0432\u0440\u0435\u043c\u044f \u0431\u0435\u0437 \u043f\u0440\u0435\u0434\u0443\u043f\u0440\u0435\u0436\u0434\u0435\u043d\u0438\u044f. \u0414\u043b\u044f \u043f\u043e\u0434\u0440\u043e\u0431\u043d\u043e\u0439 \u0438\u043d\u0444\u043e\u0440\u043c\u0430\u0446\u0438\u0438 \u043e \u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u0438 \u0443\u0441\u043b\u0443\u0433 \u043e\u0431\u0440\u0430\u0449\u0430\u0439\u0442\u0435\u0441\u044c \u043a \u0430\u0434\u043c\u0438\u043d\u0438\u0441\u0442\u0440\u0430\u0442\u043e\u0440\u0430\u043c.</p>
                            <div class="semi op50">{{ settings.copyright|default:"\u0424\u041e\u0420\u041c\u0423\u041b\u0410 \u0422\u0415\u041b\u0410" }} {% now "Y" %}</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </footer>
    <!-- ========================= footer end ========================= -->"""

# Ищем блок от "footer start" до "footer end" и заменяем
pattern = r'    <!-- =+ footer start =+ -->.*?<!-- =+ footer end =+ -->'
result = re.sub(pattern, new_footer, content, flags=re.DOTALL)

if result == content:
    print("WARNING: Footer pattern not found! Check base.html manually.")
else:
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(result)
    print("OK! Footer replaced successfully.")
    print("Restart the server: python manage.py runserver 8080")
