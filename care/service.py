"""What happens when a message arrives: save it, ask the AI, update the request, build the reply."""

import logging
import re

from django.db import transaction
from django.utils import timezone

from resources.models import Resource

from . import agent, consent, safety
from .models import CareRequest, Conversation, Message

log = logging.getLogger("care")

HISTORY_LIMIT = 30

NEW_REQUEST_WORDS = {"new request", "新請求", "新请求"}

NEW_REQUEST_REPLY = {
    "en": "Sure, let's start a new one. Do you need some help, or is there something you'd like to offer?",
    "zh": "好，我哋開始一個新嘅請求。你係需要幫手，定係想提供幫助？",
}

CONSENT_QUESTION = {
    "en": "Can we share a short note about this, and your WhatsApp number, with local church volunteers so "
    "someone can get in touch? We won't share your name. Please reply YES or NO.",
    "zh": "我哋可唔可以將一段簡短描述同你嘅 WhatsApp 號碼分享俾附近教會嘅義工，等有人可以聯絡你？"
    "我哋唔會分享你嘅名。請回覆「可以」或「唔可以」。",
}

FALLBACK_REPLY = {
    "en": "Thank you for your message. We've received it and someone will read it soon.",
    "zh": "多謝你嘅訊息，我哋已經收到，好快會有人睇。",
}


def handle_incoming(channel: str, address: str, text: str) -> tuple[str, Conversation]:
    """Returns the reply to send and the conversation it belongs to."""
    text = (text or "").strip()
    with transaction.atomic():
        conversation, _ = Conversation.objects.get_or_create(
            address=address, defaults={"channel": channel, "language": safety.guess_language(text)}
        )
        conversation.last_user_message_at = timezone.now()
        conversation.save(update_fields=["last_user_message_at"])
        Message.objects.create(conversation=conversation, role=Message.Role.USER, text=text)

    if is_new_request(text):
        conversation.start_new_request()
        language = safety.guess_language(text)
        reply = _ask_consent_once(conversation, NEW_REQUEST_REPLY[language], language, crisis=False)
        Message.objects.create(conversation=conversation, role=Message.Role.ASSISTANT, text=reply)
        return reply, conversation

    if conversation.consent_asked and conversation.consent == Conversation.Consent.UNKNOWN:
        answer = consent.read_answer(text)
        if answer:
            conversation.consent = answer
            conversation.save(update_fields=["consent"])

    keyword_crisis = safety.looks_like_crisis(text)
    request = conversation.current_request

    try:
        result = agent.respond(
            history=_history(conversation),
            case_so_far=_case_snapshot(request),
            consent=conversation.consent,
            crisis_hint=keyword_crisis,
        )
    except agent.AgentError as exc:
        log.warning("AI unavailable for conversation %s: %s", conversation.pk, exc)
        result = None

    if result:
        reply = _apply_result(conversation, request, result, keyword_crisis)
    else:
        language = conversation.language
        slugs = safety.CRISIS_SLUGS if keyword_crisis else []
        reply = _compose(FALLBACK_REPLY.get(language, FALLBACK_REPLY["en"]), slugs, language, keyword_crisis)
        reply = _ask_consent_once(conversation, reply, language, keyword_crisis)
        if keyword_crisis:
            conversation.crisis_flagged = True
            conversation.save(update_fields=["crisis_flagged"])

    Message.objects.create(conversation=conversation, role=Message.Role.ASSISTANT, text=reply)
    return reply, conversation


def is_new_request(text: str) -> bool:
    return re.sub(r"[\W_]+", " ", text.lower()).strip() in NEW_REQUEST_WORDS


def _history(conversation):
    recent = conversation.current_messages().order_by("-created_at", "-pk")[:HISTORY_LIMIT]
    return [(m.role, m.text) for m in reversed(recent)]


def _case_snapshot(request: CareRequest | None) -> dict:
    if not request:
        return {}
    return {
        "kind": request.kind,
        "category": request.category or "unclear",
        "availability": request.availability,
        "urgency": request.urgency,
        "district": request.district,
        "needs": request.needs,
        "household": request.household,
        "summary": request.summary,
        "helpers_wanted": request.helpers_wanted,
        "status": request.status,
    }


@transaction.atomic
def _apply_result(conversation, request, result: agent.AgentResult, keyword_crisis: bool) -> str:
    crisis = keyword_crisis or result.crisis

    if result.new_request and request and (request.category or request.needs):
        # A different need in the same chat: keep the earlier request, start a fresh one.
        request = None
        conversation.consent = Conversation.Consent.UNKNOWN
        conversation.consent_asked = False
        conversation.save(update_fields=["consent", "consent_asked"])
    elif result.consent in ("yes", "no"):
        conversation.consent = result.consent

    conversation.language = result.language
    conversation.crisis_flagged = conversation.crisis_flagged or crisis
    conversation.save(update_fields=["language", "consent", "crisis_flagged"])

    case = result.case
    has_content = case["kind"] != "unclear" or case["category"] != "unclear" or case["needs"]
    if has_content:
        request = request or CareRequest(conversation=conversation)
        if case["kind"] != "unclear":
            request.kind = case["kind"]
        request.category = "" if case["category"] == "unclear" else case["category"]
        request.urgency = case["urgency"]
        request.district = case["district"][:60]
        request.needs = case["needs"]
        request.household = case["household"] if request.kind == CareRequest.Kind.NEED else []
        request.availability = case["availability"]
        request.summary = case["summary"]
        request.helpers_wanted = min(max(case["helpers_wanted"], 1), 20)

        # Shown on the board only once the person has agreed to share and we know enough.
        # Crisis conversations stay off the board for coordinators to handle.
        agreed = conversation.consent == Conversation.Consent.YES
        if agreed and case["ready"] and not conversation.crisis_flagged:
            if request.status == CareRequest.Status.DRAFT:
                request.status = CareRequest.Status.OPEN
            request.shared = True
            request.share_contact = True
        elif not agreed or conversation.crisis_flagged:
            request.shared = False
            if request.status == CareRequest.Status.OPEN:
                request.status = CareRequest.Status.DRAFT
        request.save()
        if conversation.current_request_id != request.pk:
            conversation.current_request = request
            conversation.save(update_fields=["current_request"])

    slugs = list(result.resource_slugs)
    if crisis:
        slugs = [s for s in safety.CRISIS_SLUGS[:2] if s not in slugs] + slugs
    already_sent = "\n".join(
        conversation.current_messages().filter(role=Message.Role.ASSISTANT).values_list("text", flat=True)
    )
    reply = _compose(result.reply, slugs[:4], result.language, crisis, already_sent)
    return _ask_consent_once(conversation, reply, result.language, crisis)


def _ask_consent_once(conversation, reply: str, language: str, crisis: bool) -> str:
    """The first reply about each request asks, plainly, whether we may share it. Not in a crisis reply."""
    if crisis or conversation.consent_asked or conversation.consent != Conversation.Consent.UNKNOWN:
        return reply
    conversation.consent_asked = True
    conversation.save(update_fields=["consent_asked"])
    return f"{reply}\n\n{CONSENT_QUESTION.get(language, CONSENT_QUESTION['en'])}"


def _compose(body: str, slugs: list[str], language: str, crisis: bool, already_sent: str = "") -> str:
    """Body, then any services not already shown in this conversation (crisis lines always repeat)."""
    resources = Resource.objects.usable().in_bulk(slugs, field_name="slug")
    lines = []
    for slug in slugs:
        if slug not in resources:
            continue
        line = resources[slug].whatsapp_line(language)
        repeat_ok = crisis and slug in safety.CRISIS_SLUGS
        if repeat_ok or (line not in already_sent and line not in body):
            lines.append(line)
    parts = []
    if crisis:
        parts.append(safety.crisis_note(language))
    parts.append(body)
    if lines:
        parts.append("\n".join(lines))
    return "\n\n".join(parts)
