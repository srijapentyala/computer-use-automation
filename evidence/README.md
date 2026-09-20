# Evidence

Checked-in runs against the local Heritage Core teller console.

| Folder | What it shows |
| --- | --- |
| `discovery/` | Observe→decide→act loop, compiled capability, final screenshot |
| `replay_success/` | Same capability, `member_id=12345`, **0 LLM calls**, outputs `$2,450.00` |
| `replay_not_found/` | Same capability, `member_id=99999`, **business outcome** `MEMBER_NOT_FOUND`, 0 LLM calls |
| `handoff/` | Control-transfer record: automation pauses, human acts on the live session, hand-back |

The replay evidence is the production path and does not use a model.

Discovery in this folder is a **genuine LLM-driven run** on the live Heritage Core UI via TAMUS AI Chat (`protected.gemini-2.5-flash-lite`, 8 model calls). Replay folders are the production path: **0 LLM calls**.

Recapture:

```bash
# TAMUS AI Chat (OpenAI-compatible)
# .env: OPENAI_API_KEY, OPENAI_BASE_URL=https://chat-api.tamu.ai/api,
#       OPENAI_MODEL=protected.gemini-2.5-flash-lite
CUAS_LLM=openai python scripts/capture_evidence.py
```

`evidence/discovery/llm.txt` records which provider produced that capture.
