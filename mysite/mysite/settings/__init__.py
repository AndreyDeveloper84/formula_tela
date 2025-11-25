# По умолчанию используем dev, если переменная не задана
import os as _os

_profile = _os.getenv("DJANGO_SETTINGS_MODULE_DEFAULT", "mysite.settings.dev")

if _profile.endswith(".dev"):
    from .dev import *     # noqa
elif _profile.endswith(".production"):
    from .production import *  # noqa
else:
    # fallback на dev
    from .dev import *     # noqa
