from django import forms

from .models import Offer


class OfferForm(forms.ModelForm):
    class Meta:
        model = Offer
        fields = ["helper_name", "helper_contact", "church", "note"]
        labels = {
            "helper_name": "Your name",
            "helper_contact": "Your phone or WhatsApp",
            "church": "Church or care group (optional)",
            "note": "Anything the coordinator should know? (optional)",
        }
        widgets = {"note": forms.Textarea(attrs={"rows": 3})}
