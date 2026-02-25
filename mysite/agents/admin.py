from django.contrib import admin
from django.utils.html import format_html
from .models import AgentTask, AgentReport, ContentPlan, DailyMetric, SeoKeywordCluster, SeoRankSnapshot


@admin.register(AgentTask)
class AgentTaskAdmin(admin.ModelAdmin):
    list_display  = ["agent_type", "status_badge", "triggered_by", "created_at", "duration_display"]
    list_filter   = ["agent_type", "status", "triggered_by"]
    readonly_fields = [
        "agent_type", "status", "triggered_by",
        "input_context", "raw_response", "error_message",
        "created_at", "finished_at",
    ]
    ordering = ["-created_at"]

    def status_badge(self, obj):
        colors = {
            "pending": "#888",
            "running": "#f90",
            "done": "#0a0",
            "error": "#c00",
        }
        color = colors.get(obj.status, "#888")
        return format_html(
            '<span style="color:{};font-weight:bold">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = "Статус"

    def duration_display(self, obj):
        s = obj.duration_seconds
        if s is None:
            return "—"
        return f"{s}с"
    duration_display.short_description = "Длительность"


@admin.register(AgentReport)
class AgentReportAdmin(admin.ModelAdmin):
    list_display  = ["task", "summary_preview", "created_at"]
    readonly_fields = ["task", "summary", "recommendations", "created_at"]
    ordering = ["-created_at"]

    def summary_preview(self, obj):
        return obj.summary[:120] + "…" if len(obj.summary) > 120 else obj.summary
    summary_preview.short_description = "Резюме"


@admin.register(DailyMetric)
class DailyMetricAdmin(admin.ModelAdmin):
    list_display  = ["date", "total_requests", "processed", "unprocessed", "updated_at"]
    readonly_fields = [
        "date", "total_requests", "processed", "unprocessed",
        "top_services", "masters_load", "created_at", "updated_at",
    ]
    ordering = ["-date"]


@admin.register(ContentPlan)
class ContentPlanAdmin(admin.ModelAdmin):
    list_display   = [
        "week_start", "platform", "day_of_week_display",
        "post_type", "theme_preview", "is_published", "created_at",
    ]
    list_filter    = ["platform", "post_type", "is_published", "week_start"]
    list_editable  = ["is_published"]
    search_fields  = ["theme", "description", "hashtags"]
    readonly_fields = ["created_by_task", "created_at"]
    ordering       = ["-week_start", "day_of_week", "platform"]

    def theme_preview(self, obj):
        return obj.theme[:60] + ("…" if len(obj.theme) > 60 else "")
    theme_preview.short_description = "Тема"

    def day_of_week_display(self, obj):
        return obj.get_day_of_week_display()
    day_of_week_display.short_description = "День"


@admin.register(SeoKeywordCluster)
class SeoKeywordClusterAdmin(admin.ModelAdmin):
    list_display  = ["name", "service_slug", "target_url", "is_active", "created_at"]
    list_filter   = ["is_active"]
    list_editable = ["is_active"]
    search_fields = ["name", "service_slug", "target_url"]
    ordering      = ["name"]


@admin.register(SeoRankSnapshot)
class SeoRankSnapshotAdmin(admin.ModelAdmin):
    list_display  = [
        "week_start", "page_url_display", "query_preview",
        "clicks", "impressions", "ctr_display", "avg_position", "source",
    ]
    list_filter   = ["week_start", "source"]
    search_fields = ["page_url", "query"]
    ordering      = ["-week_start", "-clicks"]
    readonly_fields = [
        "week_start", "page_url", "query",
        "clicks", "impressions", "ctr", "avg_position", "source", "created_at",
    ]

    def page_url_display(self, obj):
        return obj.page_url or "—"
    page_url_display.short_description = "URL страницы"

    def query_preview(self, obj):
        return obj.query[:60] + ("…" if len(obj.query) > 60 else "") if obj.query else "—"
    query_preview.short_description = "Запрос"

    def ctr_display(self, obj):
        return f"{obj.ctr:.1%}" if obj.ctr else "0%"
    ctr_display.short_description = "CTR"
