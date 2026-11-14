from django.db import models


class Category(models.TextChoices):
    HOUSING = "housing", "Housing"
    FOOD = "food", "Food"
    MEDICAL = "medical", "Medical"
    SOCIAL = "social", "Social"
    SPIRITUAL = "spiritual", "Spiritual"
    HEART = "heart", "Heart"


class ProviderType(models.TextChoices):
    GOVERNMENT = "gov", "Government"
    CHARITY = "ngo", "Charity / NGO"
    CHURCH = "church", "Church"


class ResourceQuerySet(models.QuerySet):
    def usable(self):
        """Resources the bot may recommend."""
        return self.filter(active=True)


class Resource(models.Model):
    """One service a person can be pointed to. The bot only ever recommends rows from here,
    and phone numbers in its replies are filled in from these rows, never written by the AI."""

    slug = models.SlugField(unique=True, help_text="Short id the AI uses to refer to this resource.")
    category = models.CharField(max_length=20, choices=Category.choices)
    provider_type = models.CharField(max_length=10, choices=ProviderType.choices)

    name = models.CharField(max_length=200)
    name_zh = models.CharField("Name (Chinese)", max_length=200, blank=True)
    organisation = models.CharField(max_length=200, blank=True)
    organisation_zh = models.CharField("Organisation (Chinese)", max_length=200, blank=True)
    summary = models.TextField(help_text="One or two plain sentences on what they offer.")
    summary_zh = models.TextField("Summary (Chinese)", blank=True)
    who_for = models.CharField("Who it's for", max_length=300, blank=True)
    who_for_zh = models.CharField("Who it's for (Chinese)", max_length=300, blank=True)

    phone = models.CharField(max_length=40, blank=True)
    website = models.URLField(blank=True)
    districts = models.CharField(
        max_length=300, blank=True, help_text="Comma-separated districts. Empty means all of Hong Kong."
    )
    keywords = models.CharField(
        max_length=400, blank=True, help_text="Extra words people might use, comma-separated."
    )
    is_24h = models.BooleanField("Open 24 hours", default=False)

    active = models.BooleanField(default=True, help_text="Untick to stop the bot recommending it.")
    is_sample = models.BooleanField(
        default=False, help_text="Made-up example listing for the demo. Replace with a real one."
    )
    last_checked = models.DateField(
        null=True, blank=True, help_text="When someone last confirmed the phone number and details."
    )
    notes = models.TextField(blank=True, help_text="Internal notes. Never shown to the AI.")

    updated_at = models.DateTimeField(auto_now=True)

    objects = ResourceQuerySet.as_manager()

    class Meta:
        ordering = ["category", "name"]

    def __str__(self):
        return self.name

    def catalog_line(self):
        """Compact line describing this resource to the AI."""
        provider = self.get_provider_type_display()
        if self.organisation:
            provider += f", {self.organisation}"
        parts = [f"[{self.slug}] {self.name} ({provider})", self.get_category_display(), self.summary]
        if self.who_for:
            parts.append(f"For: {self.who_for}")
        parts.append(f"Districts: {self.districts}" if self.districts else "All Hong Kong")
        if self.is_24h:
            parts.append("24 hours")
        if self.keywords:
            parts.append(f"Keywords: {self.keywords}")
        return " | ".join(parts)

    def whatsapp_line(self, language="en"):
        """How this resource appears at the end of a WhatsApp reply."""
        zh = language == "zh"
        name = (self.name_zh if zh and self.name_zh else self.name)
        organisation = self.organisation_zh if zh and self.organisation_zh else self.organisation
        contact = self.phone or self.website
        line = f"• {name}"
        if contact:
            line += f": {contact}"
        elif organisation:
            line += f" ({organisation})"
        if self.is_24h:
            line += " (24小時)" if zh else " (24 hours)"
        return line
