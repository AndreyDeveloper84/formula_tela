"""Version 1 of the services_app catalog API.

Versioning rule: never break v1. New behaviours that would break a v1
consumer ship as v2 under a separate URL prefix. The bot infrastructure
pins by URL prefix (``/api/v1/catalog/...``).
"""
