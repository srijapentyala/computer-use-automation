# Computer-use automation system

LLM discovers how to complete a task in a real UI that has no API. A successful run is compiled into a typed, versioned **capability**. Production invocations **replay that capability with zero model calls**.

This is a take-home for interface.ai: the backend integration layer that gives an AI agent hands against legacy bank/credit-union software.

```
goal → observe/decide/act (LLM) → capability artifact → deterministic replay (no LLM)
```

The stand-in target is **Heritage Core**, a deliberately hostile teller console: iframe chrome, nested tables, no test IDs, unlabeled inputs, and real runtime exceptions (member-not-found, closed membership, validation errors, a batch interstitial, session expiry, irreversible funds transfer).

## Setup

Python 3.11+ (3.12 recommended).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m playwright install chromium
cp .env.example .env   # then add OPENAI_API_KEY (or ANTHROPIC_API_KEY)
```

Replay, tests, and the operator handoff **do not need a model key**. Discovery against a live LLM does.

Without a paid key, `--llm scripted` still drives the **live** UI through the same observe→decide→act loop, compiler, and replay path. You can also point discovery at a local Ollama model (`--llm ollama`, default `llama3.2:3b`) or any OpenAI-compatible server. A hosted model (`--llm openai` / `--llm anthropic`) is optional.

## Demo path

Terminal 1 — start the stand-in core:

```bash
cuas target
# Heritage Core on http://127.0.0.1:8787/  (teller / teller)
```

Terminal 2 — discover a goal (LLM). This writes a capability JSON and a run folder under `runs/`:

```bash
cuas discover \
  --goal "look up member 12345 and read their current savings balance" \
  --url http://127.0.0.1:8787/ \
  --llm openai \
  --out artifacts
```

Same command, no API key (offline / CI):

```bash
cuas discover \
  --goal "look up member 12345 and read their current savings balance" \
  --url http://127.0.0.1:8787/ \
  --llm scripted \
  --out artifacts \
  --start-target
```

`--start-target` boots Heritage Core in-process if you do not already have `cuas target` running.

Replay the resulting artifact. **No LLM is invoked.**

```bash
cuas replay \
  --artifact artifacts/heritage_core.lookup_savings_balance.json \
  --param member_id=12345 \
  --start-target
```

Replay a business exception (this is a successful *outcome*, not a crash):

```bash
cuas replay \
  --artifact artifacts/heritage_core.lookup_savings_balance.json \
  --param member_id=99999
```

Expected: `kind=business_outcome`, `business_code=MEMBER_NOT_FOUND`.

Agent-facing catalog (stretch):

```bash
cuas catalog --artifacts artifacts
# GET http://127.0.0.1:8789/capabilities
```

## Tests

```bash
pytest -q
```

The e2e tests boot Heritage Core, run scripted discovery against the live UI, replay the compiled artifact, replay a missing member ID, and exercise live-session handoff on the same Playwright page.

Checked-in `evidence/` is a live-UI discovery (scripted adapter) plus deterministic replays. To recapture:

```bash
# no paid key
python scripts/capture_evidence.py

# local model (brew install ollama && ollama pull llama3.2:3b && ollama serve)
CUAS_LLM=ollama python scripts/capture_evidence.py
```

## Layout

| Path | What |
| --- | --- |
| `src/cuas/` | Agent loop, artifact schema, replay engine, guardrails, handoff |
| `src/corebank/` | Heritage Core stand-in (legacy teller UI) |
| `policies/default.yaml` | Allowlist, denied actions, irreversible patterns |
| `artifacts/` | Saved capabilities |
| `evidence/` | Checked-in discovery + replay logs from a real run |
| `REPORT.md` | Design write-up (required headings) |

## Safety notes

- Only `127.0.0.1` / `localhost` are allowlisted.
- Funds transfer is classified irreversible and is blocked unattended; the system escalates.
- Passwords, SSNs, PANs, and account numbers are redacted from logs and are not stored on artifacts. Login credentials replay from `COREBANK_USER` / `COREBANK_PASSWORD` (defaults: `teller` / `teller`).
- Do not point this at a real bank, or at any site whose terms forbid automation.
