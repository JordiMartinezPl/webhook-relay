# webhook-relay

A webhook delivery platform: accepts events over HTTP and reliably relays them to registered subscriber URLs, with HMAC-signed payloads and automatic retries with backoff.

Built as a learning project to practice backend architecture (Django/DRF), asynchronous processing (Celery/Redis), and the operational side of running it (Docker, CI).

## How it works

- **`Event`** — something that happened (`event_type` + JSON `payload`), submitted via the API.
- **`Subscriber`** — a registered endpoint (`url`) interested in one or more `event_type`s, with a `secret` used to sign deliveries.
- **`Delivery`** — one row per `(Event, Subscriber)` pair: the unit of work to deliver, tracking `status` and `next_attempt_at`.
- **`DeliveryAttempt`** — one row per actual HTTP attempt for a `Delivery`, keeping a full history (HTTP status or connection error) rather than just the latest state.

### Design decisions worth knowing

- **Transactional outbox pattern**: the API view only ever saves the `Event` and responds — it never makes the outbound HTTP call itself. Fan-out and delivery run asynchronously via Celery, so a slow or broken subscriber can never slow down or break event ingestion.
- **Full delivery history, not just latest status**: `DeliveryAttempt` is append-only, so failures can be debugged after the fact (what error, at what time, how many attempts).
- **HMAC-signed payloads**: each delivery is signed with the subscriber's own secret (`X-Signature` header) so subscribers can verify the request really came from this service and wasn't tampered with in transit. The exact bytes signed are the exact bytes sent — no re-serialization step that could produce a mismatched signature.
- **Retry with backoff, not immediate failure**: failed deliveries are retried on a schedule (`5s, 30s, 60s` by default) up to `MAX_DELIVERY_ATTEMPTS`, driven by a periodic Celery Beat task that polls for deliveries whose `next_attempt_at` has passed — not by Celery's own task-level retry mechanism, to keep retry state visible and queryable in the database at all times.

## Stack

- Django + Django REST Framework
- PostgreSQL
- Celery + Redis (async delivery + scheduled retries)
- pytest / pytest-django
- Docker Compose (Postgres, Redis, Django, Celery worker, Celery beat)
- GitHub Actions (CI)

## Running locally

Requires only Docker.

```bash
cp .env.example .env
make dev
```

This builds and starts everything — Postgres, Redis, Django (`web`), the Celery worker, and Celery beat — with `docker compose up --build`. Stop everything with:

```bash
make stop
```

Run migrations and management commands inside the `web` container:

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
```

## API

All endpoints require a DRF auth token in the `Authorization` header.

**Get a token** (create a user first with `createsuperuser`, then):
```bash
docker compose exec web python manage.py shell -c "
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
user = User.objects.get(username='<your_username>')
token, _ = Token.objects.get_or_create(user=user)
print(token.key)
"
```

**Create an event:**
```bash
curl -X POST http://127.0.0.1:8000/events/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Token <your_token>" \
  -d '{"event_type": "order.paid", "payload": {"order_id": 123}}'
```

**Register a subscriber:**
```bash
curl -X POST http://127.0.0.1:8000/events/subscribers/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Token <your_token>" \
  -d '{"url": "https://example.com/webhook", "subscribed_events": ["order.paid"]}'
```
The response includes a `secret` — save it, it's only shown once. Use it to verify the `X-Signature` header on incoming deliveries.

## Tests

```bash
docker compose exec web pytest
```

