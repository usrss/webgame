import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


def seed_after_migrate(sender, app_config, **kwargs):
    """Load species/accessories whenever the database schema is migrated."""
    from .seeding import seed_content

    summary = seed_content()
    logger.info(
        "Seeded %s species and %s accessories.",
        summary["species"]["total"],
        summary["accessories"]["total"],
    )


class GameConfig(AppConfig):
    name = 'game'

    def ready(self):
        from django.db.models.signals import post_migrate

        post_migrate.connect(
            seed_after_migrate, sender=self, dispatch_uid="game.seed_after_migrate"
        )
