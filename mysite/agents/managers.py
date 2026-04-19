"""Custom QuerySet classes для agents.

Использование:
    LandingPage.objects.published()
    LandingPage.objects.needs_qc()  # draft + review
    LandingPage.objects.by_cluster(cluster).draft()
"""
from django.db import models


class LandingPageQuerySet(models.QuerySet):
    def published(self):
        from agents.models import LandingPage
        return self.filter(status=LandingPage.STATUS_PUBLISHED)

    def draft(self):
        from agents.models import LandingPage
        return self.filter(status=LandingPage.STATUS_DRAFT)

    def pending_review(self):
        from agents.models import LandingPage
        return self.filter(status=LandingPage.STATUS_REVIEW)

    def rejected(self):
        from agents.models import LandingPage
        return self.filter(status=LandingPage.STATUS_REJECTED)

    def needs_qc(self):
        # Семантический alias на draft + review — используется в SEOLandingQCAgent.
        from agents.models import LandingPage
        return self.filter(status__in=[LandingPage.STATUS_DRAFT, LandingPage.STATUS_REVIEW])

    def by_cluster(self, cluster):
        return self.filter(cluster=cluster)

    def by_slug(self, slug):
        return self.filter(slug=slug)
