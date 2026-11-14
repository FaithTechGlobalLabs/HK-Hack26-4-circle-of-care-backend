from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from care.models import CareRequest, Conversation, Offer

# Made-up requests so the board has something on it for the demo. All live under "demo:" addresses.
DEMO_REQUESTS = [
    dict(category="food", district="Tsuen Wan", urgency="normal", needs=["meals"], household=["new_baby", "children"],
         helpers_wanted=6, hours_ago=3,
         summary="A mother in Tsuen Wan has just had her second baby and would like weekday dinners for two weeks while her husband is at work."),
    dict(category="social", district="Sham Shui Po", urgency="normal", needs=["visit"], household=["elderly", "alone"],
         helpers_wanted=2, hours_ago=20,
         summary="An 82-year-old woman lives alone in Sham Shui Po. Her daughter works long shifts and would like someone to visit on Thursday afternoons."),
    dict(category="spiritual", district="Kowloon City", urgency="high", needs=["prayer", "meals"], household=["illness", "children"],
         helpers_wanted=3, hours_ago=6,
         summary="A father in Kowloon City says his wife has just started chemotherapy. They would value prayer and a few cooked meals for their two children."),
    dict(category="housing", district="Kwun Tong", urgency="high", needs=["moving"], household=["children"],
         helpers_wanted=3, hours_ago=28,
         summary="A family has been given a public housing flat in Kwun Tong and needs two or three people to help carry boxes on Saturday morning."),
    dict(category="heart", district="Sha Tin", urgency="normal", needs=["listening"], household=["carer", "elderly"],
         helpers_wanted=1, hours_ago=50,
         summary="A woman in Sha Tin caring for her father with dementia feels worn out and would like someone to check in on her now and then."),
    dict(category="food", district="Eastern", urgency="high", needs=["groceries", "money"], household=["children"],
         helpers_wanted=1, hours_ago=2,
         summary="A single father in Eastern lost his job last month and is struggling to buy groceries for his two children this week."),
    dict(category="social", district="Tuen Mun", urgency="normal", needs=["transport"], household=["elderly", "illness"],
         helpers_wanted=1, hours_ago=70,
         summary="An elderly man in Tuen Mun who uses a walking frame needs a lift to a hospital follow-up appointment next Tuesday morning."),
]


class Command(BaseCommand):
    help = "Put example requests on the board for demos. Re-running replaces the previous demo data."

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true", help="Only remove demo data.")

    def handle(self, *args, clear=False, **options):
        removed, _ = Conversation.objects.filter(address__startswith="demo:").delete()
        if clear:
            self.stdout.write(f"Removed demo data ({removed} rows).")
            return

        now = timezone.now()
        for index, item in enumerate(DEMO_REQUESTS, start=1):
            item = dict(item)
            created = now - timedelta(hours=item.pop("hours_ago"))
            conversation = Conversation.objects.create(
                channel=Conversation.Channel.SIMULATOR, address=f"demo:{index}", consent=Conversation.Consent.YES
            )
            request = CareRequest.objects.create(
                conversation=conversation, status=CareRequest.Status.OPEN, shared=True, **item
            )
            CareRequest.objects.filter(pk=request.pk).update(created_at=created)

        meals = CareRequest.objects.get(conversation__address="demo:1")
        for name, church in [("Ken", "Sample church, Tsuen Wan"), ("Priscilla", "Sample church, Tsuen Wan")]:
            Offer.objects.create(request=meals, helper_name=name, helper_contact="(demo)", church=church)

        self.stdout.write(self.style.SUCCESS(f"Added {len(DEMO_REQUESTS)} demo requests to the board."))
