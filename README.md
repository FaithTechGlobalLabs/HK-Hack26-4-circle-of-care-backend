# Circle of Care 關懷圈

HK Hackathon 2026, Challenge 4: Circle of Care. This is the backend (Django: WhatsApp bot, admin, API).
The volunteer board frontend (Next.js) is in
[HK-Hack26-circle-of-care-frontend](https://github.com/FaithTechHongKong/HK-Hack26-circle-of-care-frontend).

People in need message one WhatsApp number. The AI (DeepSeek by default, Claude optional) replies straight away, points them to services from our
resource list, and builds a request record. As soon as it knows what would help, a short anonymous summary goes
on a request board where church volunteers can offer to help. The person can reply "don't share" to take it down.

```
WhatsApp ─▶ Twilio ─▶ /twilio/whatsapp/ ─▶ AI (reply + request record) ─▶ Twilio ─▶ WhatsApp
                                                │
                                                └─▶ CareRequest ─▶ /board/ (volunteers) ─▶ Offer ─▶ admin
```

## Run it locally

```bash
cp .env.example .env          # add DEEPSEEK_API_KEY at least
docker compose up -d          # optional Postgres; then set DATABASE_URL in .env (see .env.example)
uv sync
uv run python manage.py migrate
uv run python manage.py seed_resources   # 35 services (real HK ones + sample church listings)
uv run python manage.py seed_demo        # 7 example requests on the board (seed_demo --clear removes them)
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

Leave `DATABASE_URL` empty to use SQLite instead of Docker.

- http://localhost:8000/simulator/ chats with the bot in the browser. It runs the same code as WhatsApp, so you
  don't need Twilio to test.
- http://localhost:8000/board/ is the volunteer request board.
- http://localhost:8000/admin/ is where you edit resources, read conversations and connect helpers.

Set `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY` to use Claude instead of DeepSeek. Without any key the bot still answers with a safe holding message and the crisis hotlines.

## Connect WhatsApp (Twilio Sandbox, no Meta approval)

1. Create a Twilio account. In the Console go to **Messaging › Try it out › Send a WhatsApp message**. Note the
   sandbox number and the join code (for example `join happy-river`).
2. Put `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` and `TWILIO_WHATSAPP_FROM` (the sandbox number, with the
   `whatsapp:` prefix) in `.env`.
3. Expose your local server: `ngrok http 8000`. Add the ngrok host to `DJANGO_ALLOWED_HOSTS` and
   `https://<host>` to `DJANGO_CSRF_TRUSTED_ORIGINS`, then restart runserver.
4. In the sandbox settings, set **When a message comes in** to `https://<ngrok host>/twilio/whatsapp/` (POST).
5. From your phone, send the join code to the sandbox number, then say hi.

Each tester has to send the join code first. Sandbox sessions lapse after a few days without messages; send the
code again to rejoin.

## How the bot works

- `care/agent.py` makes one AI call per message. A JSON answer returns the WhatsApp reply, up to three
  resource ids, a crisis flag, the person's consent and an updated request record together. Every answer is
  checked and anything unexpected is dropped before it touches the database.
- The bot never writes phone numbers itself. `care/service.py` adds each recommended service's name and number
  from the database, so a wrong number can only come from the resource list, which staff control in admin.
- `care/safety.py` runs a keyword check before the AI. If it fires, the reply always starts with "call 999" and
  includes 18111, even if the AI is slow or down.
- A request goes on the board as soon as the AI knows the category and at least one need. The bot tells the
  person, and "don't share" takes it off again. Crisis conversations never go on the public board.
- When a volunteer offers help, the person gets a WhatsApp update if they messaged in the last 24 hours (WhatsApp
  doesn't allow free-form business messages after that without an approved template).

## Before real use

- Check every phone number and website in admin (`Resource › last checked`). The starter list was typed from
  memory, and the church listings are samples (`is_sample`).
- Replace the shared board passcode (`BOARD_PASSCODE`) with real volunteer accounts.
- Move off the sandbox to a WhatsApp Business number (Meta business verification + message templates).
- Decide who the coordinators are and how they contact people (the admin shows the WhatsApp address).

## Tests

```bash
uv run pytest
```
