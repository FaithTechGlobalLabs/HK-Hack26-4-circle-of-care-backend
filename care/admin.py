from django.contrib import admin

from .models import CareRequest, Conversation, Message, Offer


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    can_delete = False
    readonly_fields = ["created_at", "role", "text"]
    fields = readonly_fields


class OfferInline(admin.TabularInline):
    model = Offer
    extra = 0


@admin.register(CareRequest)
class CareRequestAdmin(admin.ModelAdmin):
    list_display = ["ref", "category", "district", "urgency", "status", "shared", "offer_count", "created_at"]
    list_filter = ["status", "shared", "category", "urgency"]
    search_fields = ["summary", "district"]
    readonly_fields = ["conversation", "created_at", "updated_at"]
    inlines = [OfferInline]

    @admin.display(description="Offers")
    def offer_count(self, obj):
        return obj.offers.count()


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ["__str__", "channel", "language", "consent", "crisis_flagged", "last_user_message_at"]
    list_filter = ["channel", "consent", "crisis_flagged", "language"]
    readonly_fields = ["channel", "address", "created_at", "last_user_message_at"]
    inlines = [MessageInline]


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = ["helper_name", "church", "request", "created_at"]
    search_fields = ["helper_name", "church"]
