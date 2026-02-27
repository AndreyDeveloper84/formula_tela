from django.contrib import admin
from django.utils.html import format_html
from .models import (
    AgentTask, AgentReport, ContentPlan, DailyMetric,
    SeoKeywordCluster, SeoRankSnapshot, SeoClusterSnapshot,
    LandingPage, SeoTask,
)


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
    list_display  = ["name", "geo", "service_category", "keywords_count", "is_active", "created_at"]
    list_filter   = ["is_active", "geo", "service_category"]
    search_fields = ["name"]  # JSONField не поддерживает search_fields
    list_editable = ["is_active"]
    readonly_fields = ["created_at"]

    def keywords_count(self, obj):
        return len(obj.keywords) if obj.keywords else 0
    keywords_count.short_description = "Ключей"


@admin.register(SeoRankSnapshot)
class SeoRankSnapshotAdmin(admin.ModelAdmin):
    list_display  = [
        "page_url_display", "query_preview", "week_start",
        "clicks", "impressions", "ctr_display", "avg_position", "source",
    ]
    list_filter   = ["source", "week_start"]
    date_hierarchy = "week_start"
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
        return obj.query[:60] + ("..." if len(obj.query) > 60 else "") if obj.query else "—"
    query_preview.short_description = "Запрос"

    def ctr_display(self, obj):
        return f"{obj.ctr:.1%}" if obj.ctr else "0%"
    ctr_display.short_description = "CTR"
    ctr_display.admin_order_field = "ctr"

    def has_add_permission(self, request):
        return False  # снапшоты создаёт только агент

    def has_change_permission(self, request, obj=None):
        return False  # снапшоты нельзя редактировать вручную


@admin.register(SeoClusterSnapshot)
class SeoClusterSnapshotAdmin(admin.ModelAdmin):
    list_display = [
        "cluster", "date", "total_clicks", "total_impressions",
        "ctr_display", "avg_position", "matched_queries",
    ]
    list_filter = ["date", "cluster"]
    date_hierarchy = "date"
    search_fields = ["cluster__name"]
    ordering = ["-date", "-total_clicks"]
    readonly_fields = [
        "cluster", "date", "total_clicks", "total_impressions",
        "avg_ctr", "avg_position", "matched_queries",
    ]

    def ctr_display(self, obj):
        return f"{obj.avg_ctr:.1%}" if obj.avg_ctr else "0%"
    ctr_display.short_description = "CTR"
    ctr_display.admin_order_field = "avg_ctr"

    def has_add_permission(self, request):
        return False  # снапшоты создаёт только задача

    def has_change_permission(self, request, obj=None):
        return False  # снапшоты нельзя редактировать вручную


@admin.register(LandingPage)
class LandingPageAdmin(admin.ModelAdmin):
    list_display    = ["h1", "slug", "status_badge", "cluster", "generated_by_agent", "created_at"]
    list_filter     = ["status", "generated_by_agent"]
    search_fields   = ["h1", "slug", "meta_title"]
    readonly_fields = ["generated_by_agent", "created_at", "published_at"]
    actions         = ["action_publish", "action_send_to_review", "action_reject"]

    def status_badge(self, obj):
        colors = {
            "draft":     "#888",
            "review":    "#f0ad4e",
            "published": "#5cb85c",
            "rejected":  "#d9534f",
        }
        color = colors.get(obj.status, "#888")
        return format_html(
            '<span style="color: white; background: {}; padding: 2px 8px; border-radius: 3px;">{}</span>',
            color,
            obj.get_status_display(),
        )
    status_badge.short_description = "Статус"
    status_badge.admin_order_field = "status"

    @admin.action(description="Opublikovat")
    def action_publish(self, request, queryset):
        from django.utils import timezone
        to_publish = queryset.filter(status="review")
        count = to_publish.update(
            status="published",
            published_at=timezone.now(),
            moderated_by=request.user,
        )
        skipped = queryset.count() - count
        self.message_user(request, f"Published: {count}. Skipped: {skipped}.")

    @admin.action(description="Send to review")
    def action_send_to_review(self, request, queryset):
        count = queryset.filter(status="draft").update(status="review")
        self.message_user(request, f"Sent to review: {count}.")

    @admin.action(description="Reject")
    def action_reject(self, request, queryset):
        count = queryset.exclude(status="published").update(status="rejected")
        self.message_user(request, f"Rejected: {count}.")


@admin.register(SeoTask)
class SeoTaskAdmin(admin.ModelAdmin):
    list_display    = ["priority_badge", "task_type", "status", "title", "target_url", "created_at"]
    list_filter     = ["task_type", "priority", "status"]
    search_fields   = ["title", "target_url"]
    list_editable   = ["status"]
    readonly_fields = ["created_at", "payload"]
    ordering        = ["-priority", "-created_at"]

    def priority_badge(self, obj):
        icons = {"high": "!", "medium": "~", "low": "."}
        return f"{icons.get(obj.priority, '')} {obj.get_priority_display()}"
    priority_badge.short_description = "Prioritet"
    priority_badge.admin_order_field = "priority"
