from django.contrib import admin

from .models import Resource


@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "provider_type", "phone", "active", "is_sample", "last_checked"]
    list_filter = ["category", "provider_type", "active", "is_sample", "is_24h"]
    list_editable = ["active"]
    search_fields = ["name", "name_zh", "organisation", "summary", "keywords", "slug"]
    prepopulated_fields = {"slug": ["name"]}
    fieldsets = [
        (None, {"fields": ["name", "slug", "category", "provider_type", "organisation"]}),
        ("What they offer", {"fields": ["summary", "who_for", "keywords", "districts", "is_24h"]}),
        ("Contact", {"fields": ["phone", "website"]}),
        (
            "Chinese",
            {"fields": ["name_zh", "organisation_zh", "summary_zh", "who_for_zh"], "classes": ["collapse"]},
        ),
        ("Status", {"fields": ["active", "is_sample", "last_checked", "notes"]}),
    ]
