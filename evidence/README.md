# Evidence

Checked-in runs against the local Heritage Core teller console.

| Folder | What it shows |
| --- | --- |
| `discovery/` | Observe→decide→act loop, compiled capability, final screenshot |
| `replay_success/` | Same capability, `member_id=12345`, **0 LLM calls**, outputs `$2,450.00` |
| `replay_not_found/` | Same capability, `member_id=99999`, **business outcome** `MEMBER_NOT_FOUND`, 0 LLM calls |
| `handoff/` | Control-transfer record: automation pauses, human acts on the live session, hand-back |

The replay evidence is the production path and does not use a model.

Discovery in this folder is a **live browser run** of the same observe→decide→act loop used by OpenAI/Anthropic/Ollama. The decide step used the grounded `scripted` adapter (no paid API). Replay folders are the production path: **0 LLM calls**.

To recapture with a local model instead:

```bash
brew install ollama && ollama serve &
ollama pull llama3.2:3b
CUAS_LLM=ollama python scripts/capture_evidence.py
```

`evidence/discovery/llm.txt` records which provider produced that capture.
