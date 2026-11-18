from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Apply migrations, seed demo managers and start the local server."

    def handle(self, *args, **options):
        call_command("migrate", interactive=False)
        call_command("seed_demo")
        call_command("runserver", use_reloader=False)
