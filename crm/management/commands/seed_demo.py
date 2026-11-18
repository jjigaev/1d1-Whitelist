from django.core.management.base import BaseCommand

from crm.models import Manager


class Command(BaseCommand):
    help = "Create two demo managers without clearing existing data."

    def handle(self, *args, **options):
        created_count = 0
        for name in ("Demo Manager 1", "Demo Manager 2"):
            if not Manager.objects.filter(name=name).exists():
                Manager.objects.create(name=name)
                created_count += 1

        self.stdout.write(
            self.style.SUCCESS(f"Demo managers ready. Created: {created_count}.")
        )
