# webhook-relay

A webhook delivery platform: accepts events over HTTP and reliably relays them to registered subscriber URLs, with HMAC-signed payloads and automatic retries with backoff.

Built as a learning project to practice backend architecture (Django/DRF), asynchronous processing (Celery/Redis), and the operational side of running it (Docker, CI).

## How it works

```
POST /events/  →  Event saved  →  fan-out  →  Delivery per matching Subscriber  →  Celery worker POSTs to subscriber.url
                                                                                          │
                                                                            success ──────┤────── failure
                                                                                          │            │
                                                                                     status=SUCCESS   attempts left? → retry later (backoff)
                                                                                                        no attempts left → status=FAILED
```

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
- Docker Compose (Postgres + Redis)
- GitHub Actions (CI)

## Running locally

Requires Docker and a Python 3.13 virtualenv.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in local values
python manage.py migrate
```

Start everything (Postgres, Redis, Django, Celery worker, Celery beat) with one command:

```bash
make dev
```

This opens a tmux session with `runserver`, the Celery worker, and Celery beat each in their own pane. Stop everything with:

```bash
make stop
```

## API

**Create an event:**
```bash
curl -X POST http://127.0.0.1:8000/events/ \
  -H "Content-Type: application/json" \
  -d '{"event_type": "order.paid", "payload": {"order_id": 123}}'
```

**Register a subscriber:**
```bash
curl -X POST http://127.0.0.1:8000/events/subscribers/ \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/webhook", "subscribed_events": ["order.paid"]}'
```
The response includes a `secret` — save it, it's only shown once. Use it to verify the `X-Signature` header on incoming deliveries.

## Tests

```bash
pytest
```

