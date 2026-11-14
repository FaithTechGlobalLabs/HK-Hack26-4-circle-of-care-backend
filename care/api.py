"""Small JSON API for the Next.js request board. Same data and rules as the Django board pages."""

import json
from functools import wraps

from django.conf import settings
from django.db.models import Count, Max, Min
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from resources.models import Category

from .forms import OfferForm
from .models import CareRequest
from .views import record_offer


def passcode_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if settings.BOARD_PASSCODE and request.headers.get("X-Board-Passcode") != settings.BOARD_PASSCODE:
            return JsonResponse({"error": "passcode_required"}, status=401)
        return view(request, *args, **kwargs)

    return wrapper


def _filtered(request, queryset):
    posts = queryset.select_related("conversation").prefetch_related("offers")
    if category := request.GET.get("category"):
        posts = posts.filter(category=category)
    if district := request.GET.get("district"):
        posts = posts.filter(district__iexact=district)
    districts = sorted(set(queryset.exclude(district="").values_list("district", flat=True)))
    categories = [{"value": value, "label": label} for value, label in Category.choices]
    return posts, categories, districts


def serialize_offering(post: CareRequest) -> dict:
    return {
        "id": post.pk,
        "ref": post.ref,
        "category": post.category,
        "category_label": post.get_category_display() or "General",
        "district": post.district,
        "offers": post.need_labels(),
        "availability": post.availability,
        "contact_phone": post.contact_phone,
        "contact_link": post.contact_link,
        "summary": post.summary,
        "created_at": post.created_at.isoformat(),
    }


def serialize(req: CareRequest) -> dict:
    offers_count = req.offers.count()
    return {
        "id": req.pk,
        "ref": req.ref,
        "category": req.category,
        "category_label": req.get_category_display() or "General",
        "district": req.district,
        "urgency": req.urgency,
        "urgency_label": req.get_urgency_display(),
        "needs": req.need_labels(),
        "household": req.household_labels(),
        "summary": req.summary,
        "contact_phone": req.contact_phone,
        "contact_link": req.contact_link,
        "helpers_wanted": req.helpers_wanted,
        "offers_count": offers_count,
        "still_needed": max(0, req.helpers_wanted - offers_count),
        "created_at": req.created_at.isoformat(),
    }


def serialize_post(post: CareRequest) -> dict:
    """One board post of either kind, with the fuller write-up. Never the chat messages themselves."""
    times = post.conversation.current_messages().aggregate(
        count=Count("pk"), first=Min("created_at"), last=Max("created_at")
    )
    return {
        "id": post.pk,
        "ref": post.ref,
        "kind": post.kind,
        "kind_label": post.get_kind_display(),
        "category": post.category,
        "category_label": post.get_category_display() or "General",
        "district": post.district,
        "urgency": post.urgency,
        "urgency_label": post.get_urgency_display(),
        "status": post.status,
        "status_label": post.get_status_display(),
        "needs": post.need_labels(),
        "household": post.household_labels(),
        "availability": post.availability,
        "summary": post.summary,
        "details": post.details,
        "helpers_wanted": post.helpers_wanted,
        "contact_phone": post.contact_phone,
        "contact_link": post.contact_link,
        "language": "Cantonese" if post.conversation.language == "zh" else "English",
        "message_count": times["count"],
        "started_at": _iso(times["first"]),
        "last_message_at": _iso(times["last"]),
        "created_at": post.created_at.isoformat(),
        "updated_at": post.updated_at.isoformat(),
    }


def _iso(value):
    return value.isoformat() if value else None


def _not_found():
    return JsonResponse({"error": "This request is no longer on the board."}, status=404)


@require_GET
@passcode_required
def request_list(request):
    posts, categories, districts = _filtered(request, CareRequest.objects.on_board().needs_help())
    return JsonResponse({"requests": [serialize(r) for r in posts], "categories": categories, "districts": districts})


@require_GET
@passcode_required
def offering_list(request):
    posts, categories, districts = _filtered(request, CareRequest.objects.on_board().offering_help())
    return JsonResponse(
        {"offerings": [serialize_offering(p) for p in posts], "categories": categories, "districts": districts}
    )


@require_GET
@passcode_required
def request_detail(request, pk):
    req = CareRequest.objects.on_board().needs_help().filter(pk=pk).first()
    return JsonResponse(serialize(req)) if req else _not_found()


@require_GET
@passcode_required
def post_detail(request, pk):
    post = CareRequest.objects.on_board().select_related("conversation").filter(pk=pk).first()
    if not post:
        return JsonResponse({"error": "This post is no longer on the board."}, status=404)
    return JsonResponse(serialize_post(post))


@csrf_exempt
@require_POST
@passcode_required
def create_offer(request, pk):
    req = CareRequest.objects.on_board().needs_help().filter(pk=pk).first()
    if not req:
        return _not_found()
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"errors": {"__all__": ["Send the form as JSON."]}}, status=400)
    form = OfferForm(data)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)
    record_offer(req, form)
    return JsonResponse({"ok": True, "still_needed": req.offers_still_needed()}, status=201)
