import json
import logging
import threading
from functools import wraps

from django.conf import settings
from django.db import close_old_connections
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from resources.models import Category

from . import service, whatsapp
from .models import CareRequest, Conversation

log = logging.getLogger("care")

EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
MEDIA_ONLY_REPLY = "Sorry, I can only read text messages for now. Could you type what's happening? 抱歉，暫時只能閱讀文字訊息。"
HELPER_FOUND = {
    "en": "Good news: someone from a local church has offered to help with your request. A coordinator will contact you soon.",
    "zh": "好消息：有教會義工表示願意幫手。協調員會盡快聯絡你。",
}


def home(request):
    return render(request, "care/home.html")


# ---------- WhatsApp ----------


def run_in_background(fn, *args):
    """Twilio gives up after 15 seconds, so we answer at once and send the reply separately."""

    def target():
        close_old_connections()
        try:
            fn(*args)
        except Exception:
            log.exception("Background job failed")
        finally:
            close_old_connections()

    threading.Thread(target=target, daemon=True).start()


def reply_on_whatsapp(address, text):
    reply, _ = service.handle_incoming(Conversation.Channel.WHATSAPP, address, text)
    whatsapp.send(address, reply)


@csrf_exempt
@require_POST
def twilio_webhook(request):
    if not whatsapp.signature_is_valid(request):
        log.warning("Rejected a webhook call with a bad Twilio signature")
        return HttpResponseForbidden("Invalid signature")

    address = request.POST.get("From", "")
    body = request.POST.get("Body", "").strip()
    if not address:
        return HttpResponse(EMPTY_TWIML, content_type="text/xml")
    if not body:
        run_in_background(whatsapp.send, address, MEDIA_ONLY_REPLY)
    else:
        run_in_background(reply_on_whatsapp, address, body)
    return HttpResponse(EMPTY_TWIML, content_type="text/xml")


# ---------- Simulator (test the bot in a browser, no Twilio needed) ----------


def _simulator_address(request):
    if not request.session.session_key:
        request.session.save()
    return f"sim:{request.session.session_key}"


def simulator(request):
    conversation = Conversation.objects.filter(address=_simulator_address(request)).first()
    history = conversation.current_messages() if conversation else []
    return render(
        request,
        "care/simulator.html",
        {"history": history, "case": conversation.current_request if conversation else None,
         "conversation": conversation},
    )


@require_POST
def simulator_send(request):
    try:
        text = json.loads(request.body).get("text", "").strip()
    except json.JSONDecodeError:
        return JsonResponse({"error": "Bad request"}, status=400)
    if not text:
        return JsonResponse({"error": "Type a message first."}, status=400)
    reply, conversation = service.handle_incoming(
        Conversation.Channel.SIMULATOR, _simulator_address(request), text
    )
    case = conversation.current_request
    return JsonResponse({
        "reply": reply,
        "consent": conversation.get_consent_display(),
        "crisis": conversation.crisis_flagged,
        "case": None if not case else {
            "ref": case.ref,
            "kind": case.get_kind_display(),
            "availability": case.availability,
            "status": case.get_status_display(),
            "category": case.get_category_display() or "Not sure yet",
            "district": case.district or "Not known yet",
            "needs": case.need_labels(),
            "household": case.household_labels(),
            "urgency": case.get_urgency_display(),
            "helpers_wanted": case.helpers_wanted,
            "summary": case.summary,
            "details": case.details,
            "on_board": case.shared and case.status == CareRequest.Status.OPEN,
        },
    })


@require_POST
def simulator_reset(request):
    Conversation.objects.filter(address=_simulator_address(request)).delete()
    return redirect("simulator")


# ---------- Request board ----------


def board_access(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if settings.BOARD_PASSCODE and not request.session.get("board_ok"):
            return redirect(f"/board/login/?next={request.path}")
        return view(request, *args, **kwargs)

    return wrapper


def board_login(request):
    error = ""
    if request.method == "POST":
        if request.POST.get("passcode", "") == settings.BOARD_PASSCODE:
            request.session["board_ok"] = True
            next_url = request.GET.get("next", "/board/")
            return redirect(next_url if next_url.startswith("/") else "/board/")
        error = "That passcode didn't work. Ask your church coordinator for it."
    return render(request, "care/board_login.html", {"error": error})


def _filtered_board(request, queryset):
    category = request.GET.get("category", "")
    district = request.GET.get("district", "")
    posts = queryset.select_related("conversation").prefetch_related("offers")
    if category:
        posts = posts.filter(category=category)
    if district:
        posts = posts.filter(district__iexact=district)
    districts = sorted(set(queryset.exclude(district="").values_list("district", flat=True)))
    return {
        "posts": posts,
        "categories": Category.choices,
        "category": category,
        "districts": districts,
        "district": district,
    }


@board_access
def board(request):
    context = _filtered_board(request, CareRequest.objects.on_board().needs_help())
    return render(request, "care/board.html", {**context, "tab": "need"})


@board_access
def offerings(request):
    context = _filtered_board(request, CareRequest.objects.on_board().offering_help())
    return render(request, "care/board.html", {**context, "tab": "offer"})


def record_offer(care_request, form):
    """Save a volunteer's offer, close the request when enough people have offered, and tell the person."""
    new_offer = form.save(commit=False)
    new_offer.request = care_request
    new_offer.save()
    if care_request.offers_still_needed() == 0:
        care_request.status = CareRequest.Status.MATCHED
        care_request.save(update_fields=["status", "updated_at"])
    _tell_person_about_offer(care_request.conversation)
    return new_offer


def _tell_person_about_offer(conversation):
    if conversation.can_message():
        text = HELPER_FOUND["zh" if conversation.language == "zh" else "en"]
        run_in_background(whatsapp.send, conversation.address, text)
