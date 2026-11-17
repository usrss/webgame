"""URLs for the game app (namespace ``game``)."""

from django.urls import path
from django.views.generic import RedirectView

from . import debug_views, quiz_views, views, wardrobe_views

app_name = "game"

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="game:tank_list", permanent=False), name="home"),
    path("tanks/", views.tank_list, name="tank_list"),
    path("tanks/create/", views.tank_create, name="tank_create"),
    path("tanks/join/", views.tank_join, name="tank_join"),
    path("tanks/<int:tank_id>/", views.tank_detail, name="tank_detail"),
    path("tanks/<int:tank_id>/state/", views.tank_state, name="tank_state"),
    path("tanks/<int:tank_id>/feed/", views.tank_feed, name="tank_feed"),
    # Owner tools and moderation (Phase 5).
    path("tanks/<int:tank_id>/settings/", views.tank_settings, name="tank_settings"),
    path(
        "tanks/<int:tank_id>/regenerate-code/",
        views.tank_regenerate_code,
        name="tank_regenerate_code",
    ),
    path("tanks/<int:tank_id>/kick/<int:fish_id>/", views.tank_kick, name="tank_kick"),
    path("tanks/<int:tank_id>/unban/<int:user_id>/", views.tank_unban, name="tank_unban"),
    path(
        "tanks/<int:tank_id>/rename/<int:fish_id>/",
        views.tank_rename_fish,
        name="tank_rename_fish",
    ),
    path("tanks/<int:tank_id>/delete/", views.tank_delete, name="tank_delete"),
    path("tanks/<int:tank_id>/leave/", views.tank_leave, name="tank_leave"),
    path(
        "tanks/<int:tank_id>/rename-me/", views.tank_rename_me, name="tank_rename_me"
    ),
    path(
        "tanks/<int:tank_id>/report/<int:fish_id>/",
        views.tank_report,
        name="tank_report",
    ),
    # Quiz-based feeding (Phase 7).
    path("tanks/<int:tank_id>/quiz/next/", views.tank_quiz_next, name="tank_quiz_next"),
    path(
        "tanks/<int:tank_id>/quiz/answer/",
        views.tank_quiz_answer,
        name="tank_quiz_answer",
    ),
    path(
        "tanks/<int:tank_id>/quiz/settings/",
        views.tank_quiz_settings,
        name="tank_quiz_settings",
    ),
    # Wardrobe and pearls (Phase 9).
    path(
        "tanks/<int:tank_id>/wardrobe/state/",
        wardrobe_views.wardrobe_state,
        name="wardrobe_state",
    ),
    path(
        "tanks/<int:tank_id>/wardrobe/equip/",
        wardrobe_views.wardrobe_equip,
        name="wardrobe_equip",
    ),
    path("wardrobe/buy/", wardrobe_views.wardrobe_buy, name="wardrobe_buy"),
    # Custom quiz uploads and management (Phase 8).
    path("debug/art/", debug_views.art_debug, name="art_debug"),
    path("quizzes/", quiz_views.quiz_set_list, name="quiz_set_list"),
    path("quizzes/upload/", quiz_views.quiz_upload, name="quiz_upload"),
    path(
        "quizzes/template/<str:fmt>/",
        quiz_views.quiz_template,
        name="quiz_template",
    ),
    path(
        "quizzes/<int:quiz_set_id>/",
        quiz_views.quiz_set_detail,
        name="quiz_set_detail",
    ),
    path(
        "quizzes/<int:quiz_set_id>/confirm/",
        quiz_views.quiz_set_confirm,
        name="quiz_set_confirm",
    ),
    path(
        "quizzes/<int:quiz_set_id>/bands/",
        quiz_views.quiz_set_bands,
        name="quiz_set_bands",
    ),
    path(
        "quizzes/<int:quiz_set_id>/rename/",
        quiz_views.quiz_set_rename,
        name="quiz_set_rename",
    ),
    path(
        "quizzes/<int:quiz_set_id>/questions/<int:question_id>/toggle/",
        quiz_views.quiz_question_toggle,
        name="quiz_question_toggle",
    ),
    path(
        "quizzes/<int:quiz_set_id>/delete/",
        quiz_views.quiz_set_delete,
        name="quiz_set_delete",
    ),
]
