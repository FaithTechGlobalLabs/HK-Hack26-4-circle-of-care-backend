from datetime import timedelta

from django.db import models
from django.utils import timezone

from resources.models import Category

# WhatsApp only lets a business send free-form messages within 24 hours of the person's last message.
WHATSAPP_REPLY_WINDOW = timedelta(hours=24)


class Need(models.TextChoices):
    MEALS = "meals", "Meals"
    GROCERIES = "groceries", "Groceries"
    VISIT = "visit", "Visits / company"
    PRAYER = "prayer", "Prayer"
    ERRANDS = "errands", "Errands"
    MOVING = "moving", "Moving help"
    CHILDCARE = "childcare", "Childcare"
    TUTORING = "tutoring", "Tutoring"
    TRANSPORT = "transport", "Transport"
    MEDICAL = "medical", "Medical help"
    HOUSING = "housing", "Housing help"
    MONEY = "money", "Money / grants"
    LISTENING = "listening", "Someone to talk to"
    OTHER = "other", "Other"


class Household(models.TextChoices):
    ALONE = "alone", "Lives alone"
    CHILDREN = "children", "Children"
    ELDERLY = "elderly", "Someone 65+"
    ILLNESS = "illness", "Illness or disability"
    NEW_BABY = "new_baby", "New baby"
    CARER = "carer", "Caring for someone"


class Conversation(models.Model):
    """One WhatsApp number (or one simulator session) talking to the bot."""

    class Channel(models.TextChoices):
        WHATSAPP = "whatsapp", "WhatsApp"
        SIMULATOR = "simulator", "Simulator"

    class Consent(models.TextChoices):
        UNKNOWN = "unknown", "Not asked yet"
        YES = "yes", "Yes, share with volunteers"
        NO = "no", "No, keep private"

    channel = models.CharField(max_length=20, choices=Channel.choices)
    address = models.CharField(
        max_length=80, unique=True, help_text="WhatsApp address (whatsapp:+852...) or simulator id. Private."
    )
    language = models.CharField(max_length=10, default="en")
    consent = models.CharField(max_length=10, choices=Consent.choices, default=Consent.UNKNOWN)
    consent_asked = models.BooleanField(default=False, help_text="The sharing question has been asked for the current request.")
    crisis_flagged = models.BooleanField(default=False)
    current_request = models.ForeignKey(
        "CareRequest", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        help_text="The request or offer the bot is working on now.",
    )
    thread_started_at = models.DateTimeField(
        null=True, blank=True, help_text="When they last sent \"new request\". The bot only reads messages after this."
    )
    last_user_message_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-last_user_message_at"]

    def __str__(self):
        return f"Conversation {self.pk} ({self.get_channel_display()})"

    def start_new_request(self):
        """Leave earlier requests as they are and start the next one from a clean slate."""
        self.current_request = None
        self.consent = self.Consent.UNKNOWN
        self.consent_asked = False
        self.crisis_flagged = False
        self.thread_started_at = timezone.now()
        self.save(update_fields=["current_request", "consent", "consent_asked", "crisis_flagged", "thread_started_at"])

    def current_messages(self):
        """Messages since the person last started a new request."""
        if self.thread_started_at:
            return self.messages.filter(created_at__gte=self.thread_started_at)
        return self.messages.all()

    def can_message(self):
        """True while we're allowed to send a free-form WhatsApp message."""
        if self.channel != self.Channel.WHATSAPP or not self.last_user_message_at:
            return False
        return timezone.now() - self.last_user_message_at < WHATSAPP_REPLY_WINDOW


class Message(models.Model):
    class Role(models.TextChoices):
        USER = "user", "Person"
        ASSISTANT = "assistant", "Bot"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=Role.choices)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]


class CareRequestQuerySet(models.QuerySet):
    def on_board(self):
        return self.filter(status=CareRequest.Status.OPEN, shared=True)

    def needs_help(self):
        return self.filter(kind=CareRequest.Kind.NEED)

    def offering_help(self):
        return self.filter(kind=CareRequest.Kind.OFFER)


class CareRequest(models.Model):
    """One post built from a WhatsApp conversation: someone who needs help, or someone offering it.
    Shown on the board only after the person agrees to share."""

    class Kind(models.TextChoices):
        NEED = "need", "Needs help"
        OFFER = "offer", "Offering help"

    class Status(models.TextChoices):
        DRAFT = "draft", "Gathering details"
        OPEN = "open", "On the board"
        MATCHED = "matched", "Helper found"
        CLOSED = "closed", "Closed"

    class Urgency(models.TextChoices):
        LOW = "low", "This month"
        NORMAL = "normal", "This week"
        HIGH = "high", "Today or tomorrow"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="requests")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.NEED)
    category = models.CharField(max_length=20, choices=Category.choices, blank=True)
    urgency = models.CharField(max_length=10, choices=Urgency.choices, default=Urgency.NORMAL)
    district = models.CharField(max_length=60, blank=True)
    needs = models.JSONField(default=list, blank=True, help_text="What would help, or what they can offer.")
    availability = models.CharField(max_length=120, blank=True, help_text="For offers: when they're free.")
    household = models.JSONField(default=list, blank=True)
    summary = models.TextField(blank=True, help_text="Written by the AI with no names, phone numbers or addresses.")
    details = models.TextField(
        blank=True, help_text="A fuller anonymous write-up for volunteers, written by the AI. Same privacy rules as the summary."
    )
    helpers_wanted = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    shared = models.BooleanField(default=False, help_text="The person agreed to share this summary with volunteers.")
    share_contact = models.BooleanField(
        default=False, help_text="They agreed to show their WhatsApp number to volunteers on the board."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CareRequestQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "board post"

    def __str__(self):
        return f"{self.ref} {self.get_kind_display()}: {self.get_category_display() or 'unsorted'}"

    @property
    def ref(self):
        prefix = "O" if self.kind == self.Kind.OFFER else "R"
        return f"{prefix}-{1000 + self.pk}" if self.pk else f"{prefix}-new"

    @property
    def contact_phone(self):
        """The WhatsApp number to show volunteers, or "" if not agreed or not a WhatsApp chat."""
        conversation = self.conversation
        if not self.share_contact or conversation.channel != Conversation.Channel.WHATSAPP:
            return ""
        return conversation.address.removeprefix("whatsapp:")

    @property
    def contact_link(self):
        digits = "".join(ch for ch in self.contact_phone if ch.isdigit())
        return f"https://wa.me/{digits}" if digits else ""

    def need_labels(self):
        labels = dict(Need.choices)
        return [labels.get(n, n) for n in self.needs]

    def household_labels(self):
        labels = dict(Household.choices)
        return [labels.get(h, h) for h in self.household]

    def offers_still_needed(self):
        return max(0, self.helpers_wanted - self.offers.count())


class Offer(models.Model):
    request = models.ForeignKey(CareRequest, on_delete=models.CASCADE, related_name="offers")
    helper_name = models.CharField(max_length=120)
    helper_contact = models.CharField(max_length=120, help_text="Phone or WhatsApp. Seen by coordinators only.")
    church = models.CharField(max_length=120, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.helper_name} → {self.request.ref}"
