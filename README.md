# Vera AI Challenge — Shivansh Kumar Singh

A clean, deterministic, context-grounded implementation of the magicpin Vera merchant assistant challenge.

## What this version optimizes

- **Four-context grounding:** category + merchant + trigger + customer are used at composition time.
- **No hallucinated offers/research:** messages only use supplied context values.
- **25 known trigger families + unseen-trigger fallback:** new context can arrive after submission without hard-coded merchant IDs.
- **Customer consent gate:** customer-facing sends require a compatible consent scope.
- **Correct addressee:** customer messages address the customer, while merchant messages address the merchant.
- **Decision quality:** simultaneous triggers are ranked and only the best trigger per merchant/customer is sent per tick.
- **Suppression + concurrency safety:** suppression keys are reserved atomically to avoid duplicate sends.
- **Replay handling:** detects WhatsApp Business auto-replies, committed intent, opt-outs, hostile/off-topic replies, and unknown conversation IDs.
- **Operational safety:** no external API dependency, fast responses, teardown support, body length guard, URL stripping, anti-repetition guard.

## Required endpoints

- `POST /v1/context`
- `POST /v1/tick`
- `POST /v1/reply`
- `GET /v1/healthz`
- `GET /v1/metadata`
- Optional: `POST /v1/teardown`

## Local run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export TEAM_NAME="Shivansh Kumar Singh"
export TEAM_MEMBERS="Shivansh Kumar Singh"
export CONTACT_EMAIL="YOUR_REAL_EMAIL"

uvicorn main:app --host 0.0.0.0 --port 8080
```

Check:

- `http://127.0.0.1:8080/v1/healthz`
- `http://127.0.0.1:8080/v1/metadata`
- `http://127.0.0.1:8080/docs`

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

If you have the official/reference challenge dataset:

```bash
python self_test_dataset.py /path/to/magicpin-ai-challenge/dataset
```

## Render deployment

A `render.yaml` is included. Create a Render Blueprint/Web Service from this repository and set:

- `TEAM_NAME`
- `TEAM_MEMBERS`
- `CONTACT_EMAIL`

The start command is:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

After deployment, submit the **base URL** (for example `https://your-service.onrender.com`), not `/v1/healthz` or `/docs`.

## Design tradeoff

This build deliberately avoids an external LLM dependency. The benefit is deterministic, low-latency, privacy-preserving behavior with strong grounding. The generic fallback still handles new trigger kinds by extracting safe scalar facts from the newly pushed context.
