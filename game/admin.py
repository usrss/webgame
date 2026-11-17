"""Django admin as the moderation console (Phase 5)."""

from django.contrib import admin, messages
from django.db.models import Count, Q

from .models import (
    Accessory,
    EvolutionStage,
    Fish,
    FishEquipment,
    FishReport,
    FishSpecies,
    PearlTransaction,
    PlayerProfile,
    Question,
    QuestionAttempt,
    QuizBand,
    QuizSet,
    SpeciesStageName,
    Tank,
    TankBan,
)
from .quiz.sets import deactivate_set
from .services import award_pearls, regenerate_join_code


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
        "quiz_source",
        "created_at",
    ]
    search_fields = ["name", "join_code", "owner__username"]
    list_filter = ["created_at", "quiz_grade", "quiz_source"]
    readonly_fields = ["join_code", "created_at"]
    actions = ["regenerate_codes"]
    fieldsets = [
        (None, {"fields": ["name", "owner", "join_code", "capacity", "created_at"]}),
        (
            "Quiz",
            {
                "fields": [
                    "quiz_grade",
                    "quiz_subjects",
                    "quiz_source",
                    "quiz_set",
                    "quiz_difficulty_mode",
                    "quiz_fixed_difficulty",
                ]
            },
        ),
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


class FishEquipmentInline(admin.TabularInline):
    model = FishEquipment
    extra = 0
    fields = ["slot", "accessory"]
    autocomplete_fields = []


@admin.register(Fish)
class FishAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "species",
        "owner",
        "tank",
        "level",
        "stage",
        "unresolved_reports",
        "created_at",
    ]
    search_fields = ["name", "owner__username", "tank__name"]
    list_filter = [HasUnresolvedReportsFilter, "species", "stage", "level"]
    list_select_related = ["owner", "tank", "species"]
    readonly_fields = ["created_at", "renamed_at"]
    inlines = [FishEquipmentInline]
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

    list_display = [
        "prompt",
        "subject",
        "grade",
        "difficulty",
        "active",
        "created_at",
    ]
    list_filter = ["subject", "grade", "active", "difficulty", "quiz_set"]
    search_fields = ["prompt", "explanation"]
    readonly_fields = ["created_at"]
    actions = ["activate", "deactivate"]
    fieldsets = [
        (None, {"fields": ["subject", "grade", "prompt", "choices"]}),
        ("Answer", {"fields": ["correct_index", "explanation", "active"]}),
        (
            "Custom quiz",
            {"fields": ["quiz_set", "item_number", "difficulty"]},
        ),
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
        "difficulty",
        "correct",
        "issued_at",
        "answered_at",
    ]
    list_filter = ["correct", "subject", "grade", "difficulty", "issued_at"]
    search_fields = ["user__username", "fish__name", "prompt"]
    list_select_related = ["user", "fish"]
    date_hierarchy = "issued_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]


class QuizBandInline(admin.TabularInline):
    model = QuizBand
    extra = 0
    can_delete = False
    fields = ["difficulty", "start", "end"]
    readonly_fields = ["difficulty", "start", "end"]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(QuizSet)
class QuizSetAdmin(admin.ModelAdmin):
    """Read-mostly moderation view; uploaded files are never stored."""

    list_display = ["name", "owner", "status", "source_format", "question_count", "created_at"]
    list_filter = ["status", "source_format", "created_at"]
    search_fields = ["name", "owner__username"]
    readonly_fields = [
        "owner",
        "source_filename",
        "source_format",
        "created_at",
        "question_count",
    ]
    list_select_related = ["owner"]
    inlines = [QuizBandInline]
    actions = ["deactivate_sets"]
    fieldsets = [
        (None, {"fields": ["owner", "name", "status"]}),
        ("Upload", {"fields": ["source_filename", "source_format", "created_at"]}),
        ("Counts", {"fields": ["question_count"]}),
    ]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("owner")
            .annotate(total_questions=Count("questions"))
        )

    @admin.display(description="Questions", ordering="total_questions")
    def question_count(self, obj):
        return obj.total_questions

    @admin.action(description="Deactivate set (tanks revert to built-in)")
    def deactivate_sets(self, request, queryset):
        updated = 0
        for quiz_set in queryset:
            deactivate_set(quiz_set)
            updated += 1
        self.message_user(
            request, f"Deactivated {updated} quiz set(s).", messages.SUCCESS
        )


class SpeciesStageNameInline(admin.TabularInline):
    model = SpeciesStageName
    extra = 0
    fields = ["stage_number", "name"]
    readonly_fields = ["stage_number", "name"]

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FishSpecies)
class FishSpeciesAdmin(admin.ModelAdmin):
    list_display = ["order", "name", "key", "active"]
    list_filter = ["active"]
    search_fields = ["name", "key"]
    readonly_fields = ["key", "name", "description", "order"]
    inlines = [SpeciesStageNameInline]
    actions = ["activate", "deactivate"]

    @admin.action(description="Activate selected species")
    def activate(self, request, queryset):
        updated = queryset.update(active=True)
        self.message_user(request, f"Activated {updated} species.", messages.SUCCESS)

    @admin.action(description="Deactivate selected species")
    def deactivate(self, request, queryset):
        updated = queryset.update(active=False)
        self.message_user(request, f"Deactivated {updated} species.", messages.SUCCESS)


@admin.register(Accessory)
class AccessoryAdmin(admin.ModelAdmin):
    list_display = ["name", "slot", "rarity", "unlock_type", "price", "unlock_stage", "active"]
    list_filter = ["slot", "rarity", "unlock_type", "active"]
    search_fields = ["name", "key"]
    readonly_fields = ["key", "slot"]


@admin.register(PlayerProfile)
class PlayerProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "pearls"]
    search_fields = ["user__username"]
    readonly_fields = ["user"]
    actions = ["grant_pearls"]

    @admin.action(description="Grant 10 pearls (audited)")
    def grant_pearls(self, request, queryset):
        for profile in queryset.select_related("user"):
            award_pearls(profile.user, 10, "admin_grant")
        self.message_user(
            request, f"Granted 10 pearls to {queryset.count()} player(s).", messages.SUCCESS
        )


@admin.register(PearlTransaction)
class PearlTransactionAdmin(admin.ModelAdmin):
    list_display = ["user", "amount", "reason", "created_at"]
    list_filter = ["reason", "created_at"]
    search_fields = ["user__username"]
    date_hierarchy = "created_at"

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
