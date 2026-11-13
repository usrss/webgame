"""Django admin as the moderation console (Phase 5)."""

from django.contrib import admin, messages
from django.db.models import Count, Q

from .models import (
    EvolutionStage,
    Fish,
    FishReport,
    Question,
    QuestionAttempt,
    Tank,
    TankBan,
)
from .services import regenerate_join_code


class HasUnresolvedReportsFilter(admin.SimpleListFilter):
    title = "unresolved reports"
    parameter_name = "unresolved"

    def lookups(self, request, model_admin):
        return (("yes", "Has unresolved reports"), ("no", "No unresolved reports"))

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(reports__resolved=False).distinct()
        if self.value() == "no":
            return queryset.exclude(reports__resolved=False)
        return queryset


@admin.register(Tank)
class TankAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "owner",
        "join_code",
        "member_count",
        "capacity",
        "quiz_grade",
        "created_at",
    ]
    search_fields = ["name", "join_code", "owner__username"]
    list_filter = ["created_at", "quiz_grade"]
    readonly_fields = ["join_code", "created_at"]
    actions = ["regenerate_codes"]
    fieldsets = [
        (None, {"fields": ["name", "owner", "join_code", "capacity", "created_at"]}),
        ("Quiz (Phase 7)", {"fields": ["quiz_grade", "quiz_subjects"]}),
    ]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("owner")
            .annotate(member_total=Count("fish"))
        )

    @admin.display(description="Members", ordering="member_total")
    def member_count(self, obj):
        return f"{obj.member_total} / {obj.capacity}"

    @admin.action(description="Regenerate join code")
    def regenerate_codes(self, request, queryset):
        updated = 0
        for tank in queryset:
            # Reuse the service (acting as the owner) so uniqueness and locking
            # behave exactly like the in-game action.
            regenerate_join_code(tank, tank.owner)
            updated += 1
        self.message_user(
            request, f"Regenerated the join code for {updated} tank(s).", messages.SUCCESS
        )


@admin.register(EvolutionStage)
class EvolutionStageAdmin(admin.ModelAdmin):
    list_display = ["stage_number", "name", "min_level", "sprite_key"]
    search_fields = ["name", "sprite_key"]
    list_filter = ["stage_number"]


@admin.register(Fish)
class FishAdmin(admin.ModelAdmin):
    list_display = ["name", "owner", "tank", "level", "stage", "unresolved_reports", "created_at"]
    search_fields = ["name", "owner__username", "tank__name"]
    list_filter = [HasUnresolvedReportsFilter, "stage", "level"]
    list_select_related = ["owner", "tank"]
    readonly_fields = ["created_at", "renamed_at"]
    actions = ["reset_names", "delete_selected_fish"]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("owner", "tank")
            .annotate(
                open_reports=Count("reports", filter=Q(reports__resolved=False))
            )
        )

    @admin.display(description="Open reports", ordering="open_reports")
    def unresolved_reports(self, obj):
        return obj.open_reports

    @admin.action(description="Reset name to 'Fish #<id>'")
    def reset_names(self, request, queryset):
        updated = 0
        for fish in queryset:
            fish.name = f"Fish #{fish.pk}"
            fish.save(update_fields=["name"])
            updated += 1
        self.message_user(
            request, f"Reset {updated} fish name(s).", messages.SUCCESS
        )

    @admin.action(description="Delete selected fish")
    def delete_selected_fish(self, request, queryset):
        deleted, _details = queryset.delete()
        self.message_user(request, f"Deleted {deleted} object(s).", messages.SUCCESS)


@admin.register(FishReport)
class FishReportAdmin(admin.ModelAdmin):
    list_display = ["fish", "reporter", "reason", "resolved", "created_at"]
    list_filter = ["resolved", "reason", "created_at"]
    search_fields = ["fish__name", "reporter__username", "note"]
    list_select_related = ["fish", "reporter"]
    readonly_fields = ["created_at"]
    actions = ["mark_resolved"]

    @admin.action(description="Mark selected reports resolved")
    def mark_resolved(self, request, queryset):
        updated = queryset.update(resolved=True)
        self.message_user(
            request, f"Marked {updated} report(s) resolved.", messages.SUCCESS
        )


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    """Staff-only question editing; players never see this model."""

    list_display = ["prompt", "subject", "grade", "active", "created_at"]
    list_filter = ["subject", "grade", "active"]
    search_fields = ["prompt", "explanation"]
    readonly_fields = ["created_at"]
    actions = ["activate", "deactivate"]
    fieldsets = [
        (None, {"fields": ["subject", "grade", "prompt", "choices"]}),
        ("Answer", {"fields": ["correct_index", "explanation", "active"]}),
        (None, {"fields": ["created_at"]}),
    ]

    @admin.action(description="Activate selected questions")
    def activate(self, request, queryset):
        updated = queryset.update(active=True)
        self.message_user(request, f"Activated {updated} question(s).", messages.SUCCESS)

    @admin.action(description="Deactivate selected questions")
    def deactivate(self, request, queryset):
        updated = queryset.update(active=False)
        self.message_user(request, f"Deactivated {updated} question(s).", messages.SUCCESS)


@admin.register(QuestionAttempt)
class QuestionAttemptAdmin(admin.ModelAdmin):
    """Read-only debugging view. ``correct_index`` is never editable here."""

    list_display = [
        "id",
        "user",
        "fish",
        "subject",
        "grade",
        "correct",
        "issued_at",
        "answered_at",
    ]
    list_filter = ["correct", "subject", "grade", "issued_at"]
    search_fields = ["user__username", "fish__name", "prompt"]
    list_select_related = ["user", "fish"]
    date_hierarchy = "issued_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]


@admin.register(TankBan)
class TankBanAdmin(admin.ModelAdmin):
    list_display = ["tank", "user", "banned_by", "created_at"]
    search_fields = ["tank__name", "user__username", "tank__join_code"]
    list_filter = ["created_at"]
    list_select_related = ["tank", "user", "banned_by"]
    readonly_fields = ["created_at"]
