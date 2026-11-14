import pytest
from django.core.management import call_command
from django.urls import reverse

from care import agent, safety, service, views, whatsapp
from care.models import CareRequest, Conversation, Message


@pytest.fixture
def seeded(db):
    call_command("seed_resources", verbosity=0)


def make_result(**overrides):
    case = {
        "kind": "need",
        "availability": "",
        "category": "food",
        "urgency": "normal",
        "district": "Tsuen Wan",
        "needs": ["meals"],
        "household": ["new_baby"],
        "summary": "A mother in Tsuen Wan has a new baby and would like weekday dinners.",
        "helpers_wanted": 2,
        "ready": True,
    }
    case.update(overrides.pop("case", {}))
    values = {
        "reply": "Congratulations on the baby. Can we share a short summary with church volunteers?",
        "language": "en",
        "resource_slugs": ["stfa"],
        "crisis": False,
        "consent": "unknown",
        "case": case,
    }
    values.update(overrides)
    return agent.AgentResult(**values)


@pytest.fixture
def fake_agent(monkeypatch):
    """Replace the Claude call with a queue of canned answers."""
    answers = []

    def respond(history, case_so_far, consent, crisis_hint=False):
        respond.calls.append({"history": history, "case": case_so_far, "consent": consent, "crisis": crisis_hint})
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    respond.calls = []
    monkeypatch.setattr(agent, "respond", respond)
    return answers, respond


# ---------- safety ----------


@pytest.mark.parametrize("text", ["I want to die", "thinking about suicide", "我想死", "佢打我", "I can't breathe"])
def test_crisis_words_are_caught(text):
    assert safety.looks_like_crisis(text)


@pytest.mark.parametrize("text", ["I need food for my kids", "我需要幫手搬屋", "my mum is lonely"])
def test_ordinary_messages_are_not_crisis(text):
    assert not safety.looks_like_crisis(text)


# ---------- conversation flow ----------


def test_reply_lists_resource_contact_from_database(seeded, fake_agent):
    answers, _ = fake_agent
    answers.append(make_result())

    reply, conversation = service.handle_incoming("simulator", "sim:a", "I just had a baby")

    assert "Short-term Food Assistance" in reply
    assert "2343 2255" in reply  # comes from the resource row, not the AI
    assert list(conversation.messages.values_list("role", flat=True)) == ["user", "assistant"]


def test_request_goes_on_board_only_after_consent(seeded, fake_agent):
    answers, respond = fake_agent
    answers.extend([make_result(), make_result(consent="yes", reply="Thank you, I've shared it.")])

    service.handle_incoming("simulator", "sim:b", "I just had a baby")
    request = CareRequest.objects.get()
    assert request.status == CareRequest.Status.DRAFT and not request.shared

    service.handle_incoming("simulator", "sim:b", "yes please share it")
    request.refresh_from_db()
    assert request.status == CareRequest.Status.OPEN and request.shared
    # The second call saw the history and the case so far
    assert respond.calls[1]["case"]["category"] == "food"
    assert respond.calls[1]["history"][-1] == ("user", "yes please share it")


def test_first_message_is_flagged_for_a_welcome():
    first = agent.build_messages([("user", "hello")], {}, "unknown", crisis_hint=False)
    later = agent.build_messages([("user", "hello"), ("assistant", "hi"), ("user", "food")], {}, "unknown", False)
    assert "first message" in first[-1]["content"]
    assert "first message" not in later[-1]["content"]


def test_offer_of_help_goes_on_offers_side(seeded, fake_agent, client):
    answers, _ = fake_agent
    offer_case = {"kind": "offer", "needs": ["meals"], "household": ["children"], "availability": "Weekends",
                  "summary": "A retired chef in Tsuen Wan can cook dinners on weekends.", "ready": True}
    answers.extend([make_result(resource_slugs=[], case=offer_case),
                    make_result(resource_slugs=[], consent="yes", case=offer_case)])
    service.handle_incoming("simulator", "sim:o", "I can cook on weekends")
    service.handle_incoming("simulator", "sim:o", "yes share it")

    post = CareRequest.objects.get()
    assert post.kind == CareRequest.Kind.OFFER and post.ref.startswith("O-")
    assert post.household == [] and post.availability == "Weekends"
    assert "retired chef" in client.get(reverse("offerings")).content.decode()
    assert "retired chef" not in client.get(reverse("board")).content.decode()
    api = client.get(reverse("api_offerings")).json()["offerings"]
    assert api[0]["offers"] == ["Meals"] and api[0]["availability"] == "Weekends"


def test_saying_dont_share_takes_request_off_board(seeded, fake_agent):
    answers, _ = fake_agent
    answers.extend([make_result(consent="yes"), make_result(consent="no")])
    service.handle_incoming("simulator", "sim:c", "need dinners")
    assert CareRequest.objects.on_board().count() == 1
    service.handle_incoming("simulator", "sim:c", "don't share")
    request = CareRequest.objects.get()
    assert request.status == CareRequest.Status.DRAFT and not request.shared


def test_crisis_conversations_stay_off_the_board(seeded, fake_agent):
    answers, _ = fake_agent
    answers.append(make_result(crisis=True, consent="yes"))
    service.handle_incoming("simulator", "sim:x", "I can't go on, I need food")
    assert CareRequest.objects.on_board().count() == 0


def test_crisis_adds_999_and_hotlines_even_if_ai_forgets(seeded, fake_agent):
    answers, respond = fake_agent
    answers.append(make_result(resource_slugs=[], case={"category": "heart", "needs": ["listening"]}))

    reply, conversation = service.handle_incoming("simulator", "sim:d", "I want to die")

    assert respond.calls[0]["crisis"] is True
    assert reply.startswith("If you or someone else is in danger right now, please call 999.")
    assert "18111" in reply
    assert conversation.crisis_flagged


def test_ai_failure_still_sends_safe_reply(seeded, fake_agent):
    answers, _ = fake_agent
    answers.append(agent.AgentError("down"))

    reply, conversation = service.handle_incoming("simulator", "sim:e", "我想死")

    assert "999" in reply and "18111" in reply
    assert conversation.crisis_flagged
    assert conversation.current_request is None


def test_build_messages_alternates_roles_and_adds_case_note():
    messages = agent.build_messages(
        [("assistant", "hello"), ("user", "a"), ("user", "b"), ("assistant", "ok"), ("user", "c")],
        {"category": "food"}, "unknown", crisis_hint=True,
    )
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "system"]
    assert messages[0]["content"] == "a\nb"
    assert "possible crisis" in messages[-1]["content"]


# ---------- WhatsApp webhook ----------


def test_webhook_replies_over_whatsapp(seeded, fake_agent, client, settings, monkeypatch):
    settings.TWILIO_VALIDATE_SIGNATURE = False
    answers, _ = fake_agent
    answers.append(make_result())
    sent = []
    monkeypatch.setattr(views, "run_in_background", lambda fn, *args: fn(*args))
    monkeypatch.setattr(whatsapp, "send", lambda to, body: sent.append((to, body)) or True)

    response = client.post(reverse("twilio_webhook"), {"From": "whatsapp:+85291234567", "Body": "hi"})

    assert response.status_code == 200 and "<Response>" in response.content.decode()
    assert sent and sent[0][0] == "whatsapp:+85291234567"
    assert Conversation.objects.get().channel == "whatsapp"


def test_webhook_rejects_bad_signature(db, client, settings):
    settings.TWILIO_VALIDATE_SIGNATURE = True
    settings.TWILIO_AUTH_TOKEN = "secret"
    response = client.post(reverse("twilio_webhook"), {"From": "whatsapp:+852", "Body": "hi"})
    assert response.status_code == 403
    assert Message.objects.count() == 0


def test_long_replies_are_split():
    body = "\n\n".join(["x" * 900, "y" * 900, "z" * 100])
    chunks = whatsapp.split(body)
    assert len(chunks) == 2 and all(len(c) <= whatsapp.CHUNK for c in chunks)


# ---------- board ----------


@pytest.fixture
def open_request(db):
    conversation = Conversation.objects.create(channel="simulator", address="sim:board", consent="yes")
    return CareRequest.objects.create(
        conversation=conversation, category="food", district="Tsuen Wan", needs=["meals"],
        summary="A family needs dinners.", helpers_wanted=1, status="open", shared=True,
    )


def test_board_hides_unshared_requests(open_request, client):
    hidden_conv = Conversation.objects.create(channel="simulator", address="sim:hidden")
    CareRequest.objects.create(conversation=hidden_conv, category="food", summary="Private one", status="draft")
    page = client.get(reverse("board")).content.decode()
    assert "A family needs dinners." in page
    assert "Private one" not in page


def test_board_passcode(open_request, client, settings):
    settings.BOARD_PASSCODE = "grace"
    assert client.get(reverse("board")).status_code == 302
    client.post(reverse("board_login"), {"passcode": "grace"})
    assert client.get(reverse("board")).status_code == 200


def test_clean_result_drops_values_we_dont_understand():
    result = agent.clean_result(
        {
            "reply": " Hi ",
            "language": "fr",
            "resource_slugs": ["a", "b", "c", "d"],
            "crisis": "yes",
            "consent": "maybe",
            "case": {"category": "pets", "needs": ["meals", "unicorns"], "helpers_wanted": "lots", "ready": 1},
        },
        fallback_language="zh",
    )
    assert result.reply == "Hi" and result.language == "zh"
    assert result.resource_slugs == ["a", "b", "c"]
    assert result.crisis is False and result.consent == "unknown"
    assert result.case["category"] == "unclear" and result.case["needs"] == ["meals"]
    assert result.case["helpers_wanted"] == 1 and result.case["ready"] is False


def test_clean_result_needs_a_reply():
    with pytest.raises(agent.AgentError):
        agent.clean_result({"reply": "  "})


def test_services_are_not_repeated_in_later_replies(seeded, fake_agent):
    answers, _ = fake_agent
    answers.extend([make_result(), make_result()])
    first, _ = service.handle_incoming("simulator", "sim:r", "need dinners")
    second, _ = service.handle_incoming("simulator", "sim:r", "just me")
    assert "2343 2255" in first
    assert "2343 2255" not in second


# ---------- JSON API ----------


def test_api_lists_board_requests(open_request, client):
    data = client.get(reverse("api_requests")).json()
    assert [r["summary"] for r in data["requests"]] == ["A family needs dinners."]
    assert data["requests"][0]["still_needed"] == 1
    assert data["districts"] == ["Tsuen Wan"] and len(data["categories"]) == 6


def test_api_offer(open_request, client):
    url = reverse("api_offers", args=[open_request.pk])
    bad = client.post(url, {"helper_name": ""}, content_type="application/json")
    assert bad.status_code == 400 and "helper_name" in bad.json()["errors"]
    ok = client.post(url, {"helper_name": "Ken", "helper_contact": "9123 4567"}, content_type="application/json")
    assert ok.status_code == 201 and ok.json()["still_needed"] == 0
    assert client.get(reverse("api_request", args=[open_request.pk])).status_code == 404  # now matched


def test_api_passcode(open_request, client, settings):
    settings.BOARD_PASSCODE = "grace"
    assert client.get(reverse("api_requests")).status_code == 401
    assert client.get(reverse("api_requests"), headers={"X-Board-Passcode": "grace"}).status_code == 200


def test_new_request_starts_a_second_request(seeded, fake_agent):
    answers, respond = fake_agent
    answers.extend([make_result(consent="yes"), make_result(case={"category": "medical", "needs": ["transport"]})])

    service.handle_incoming("simulator", "sim:n", "need dinners")
    reply, conversation = service.handle_incoming("simulator", "sim:n", "New request!")
    assert "start a new one" in reply and len(respond.calls) == 1  # no AI call for the keyword
    service.handle_incoming("simulator", "sim:n", "I need a lift to hospital")

    first, second = conversation.requests.order_by("created_at")
    assert first.category == "food" and first.status == CareRequest.Status.OPEN  # still on the board
    assert second.category == "medical" and not second.shared
    conversation.refresh_from_db()
    assert conversation.current_request == second and conversation.consent == "unknown"
    # The AI only saw the new thread, not the earlier request
    assert respond.calls[1]["case"] == {}
    assert [text for _, text in respond.calls[1]["history"]][-1] == "I need a lift to hospital"
    assert "need dinners" not in [text for _, text in respond.calls[1]["history"]]


def test_first_reply_asks_to_share_once(seeded, fake_agent):
    answers, _ = fake_agent
    answers.extend([make_result(case={"category": "unclear", "needs": [], "summary": ""}), make_result()])
    first, _ = service.handle_incoming("simulator", "sim:q", "hello")
    second, _ = service.handle_incoming("simulator", "sim:q", "I need dinners")
    assert first.endswith(service.CONSENT_QUESTION["en"])
    assert service.CONSENT_QUESTION["en"] not in second


def test_crisis_reply_does_not_ask_to_share(seeded, fake_agent):
    answers, _ = fake_agent
    answers.append(make_result(crisis=True))
    reply, conversation = service.handle_incoming("simulator", "sim:k", "I want to die")
    assert service.CONSENT_QUESTION["en"] not in reply and not conversation.consent_asked


def test_new_topic_opens_a_separate_request_and_asks_again(seeded, fake_agent):
    answers, _ = fake_agent
    answers.extend([
        make_result(consent="yes"),
        make_result(new_request=True, consent="yes", case={"category": "medical", "needs": ["transport"]}),
    ])
    service.handle_incoming("simulator", "sim:t", "need dinners, yes share")
    reply, conversation = service.handle_incoming("simulator", "sim:t", "also I need a lift to hospital")

    first, second = conversation.requests.order_by("created_at")
    assert first.category == "food" and first.shared
    assert second.category == "medical" and not second.shared  # needs its own yes
    assert reply.endswith(service.CONSENT_QUESTION["en"])


@pytest.mark.parametrize("text,expected", [
    ("Sure, I broke my leg", "yes"), ("yes", "yes"), ("OK!", "yes"), ("可以", "yes"), ("好呀", "yes"),
    ("no thanks", "no"), ("Please don't share", "no"), ("唔好", "no"), ("not sure", None),
    ("I need food", None), ("okayyy", None), ("nobody is home", None), ("just don't share it", "no"),
])
def test_reading_the_sharing_answer(text, expected):
    from care import consent
    assert consent.read_answer(text) == expected


def test_sure_counts_as_yes_even_if_ai_misses_it(seeded, fake_agent):
    answers, _ = fake_agent
    answers.extend([make_result(case={"category": "unclear", "needs": [], "summary": ""}), make_result()])
    service.handle_incoming("simulator", "sim:s", "new request")  # asks the sharing question
    service.handle_incoming("simulator", "sim:s", "hello")
    service.handle_incoming("simulator", "sim:s", "Sure, I broke my leg")
    conversation = Conversation.objects.get(address="sim:s")
    assert conversation.consent == "yes"
    assert conversation.current_request.shared


def test_board_shows_whatsapp_number_only_when_agreed(seeded, fake_agent, client):
    answers, _ = fake_agent
    answers.extend([make_result(), make_result(consent="yes")])
    service.handle_incoming("whatsapp", "whatsapp:+85291234567", "I just had a baby in Tsuen Wan")
    data = client.get(reverse("api_requests")).json()["requests"]
    assert data == []  # not shared yet

    service.handle_incoming("whatsapp", "whatsapp:+85291234567", "yes")
    row = client.get(reverse("api_requests")).json()["requests"][0]
    assert row["contact_phone"] == "+85291234567" and row["contact_link"] == "https://wa.me/85291234567"
    assert "+85291234567" in client.get(reverse("board")).content.decode()


def test_posts_shared_before_the_new_promise_keep_number_hidden(open_request, client):
    open_request.conversation.channel = "whatsapp"
    open_request.conversation.save()
    row = client.get(reverse("api_requests")).json()["requests"][0]
    assert row["contact_phone"] == ""
    assert "Contact through a coordinator" in client.get(reverse("board")).content.decode()
