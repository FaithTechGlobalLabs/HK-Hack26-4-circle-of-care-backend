import json
from pathlib import Path

from django.core.management.base import BaseCommand

from resources.models import Resource

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "resources.json"


class Command(BaseCommand):
    help = "Load the starter list of Hong Kong resources. Safe to re-run: updates rows by slug."

    def handle(self, *args, **options):
        rows = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        created = 0
        for row in rows:
            slug = row.pop("slug")
            _, was_created = Resource.objects.update_or_create(slug=slug, defaults=row)
            created += was_created
        self.stdout.write(
            self.style.SUCCESS(f"{len(rows)} resources loaded ({created} new). Check every phone number before going live.")
        )
