"""Sending WhatsApp messages through Twilio."""

import logging

from django.conf import settings
from twilio.base.exceptions import TwilioRestException
from twilio.request_validator import RequestValidator
from twilio.rest import Client

log = logging.getLogger("care")

# Twilio's limit is 1600 characters per WhatsApp message; leave some room.
CHUNK = 1500


def is_configured() -> bool:
    return bool(settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN)


def send(to: str, body: str) -> bool:
    if not is_configured():
        log.warning("Twilio is not configured; not sending to %s", to)
        return False
    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    try:
        for chunk in split(body):
            client.messages.create(from_=settings.TWILIO_WHATSAPP_FROM, to=to, body=chunk)
    except TwilioRestException as exc:
        log.error("Twilio send to %s failed: %s", to, exc)
        return False
    return True


def split(body: str) -> list[str]:
    """Split on paragraph breaks so long replies arrive as a few readable messages."""
    chunks, current = [], ""
    for paragraph in body.split("\n\n"):
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= CHUNK:
            current = candidate
            continue
        if current:
            chunks.append(current)
        while len(paragraph) > CHUNK:
            chunks.append(paragraph[:CHUNK])
            paragraph = paragraph[CHUNK:]
        current = paragraph
    if current:
        chunks.append(current)
    return chunks


def signature_is_valid(request) -> bool:
    if not settings.TWILIO_VALIDATE_SIGNATURE:
        return True
    validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
    return validator.validate(
        request.build_absolute_uri(),
        request.POST.dict(),
        request.headers.get("X-Twilio-Signature", ""),
    )
