# Evidence

Checked-in runs against the local Heritage Core teller console.

| Folder | What it shows |
| --- | --- |
| `discovery/` | Observe→decide→act loop, compiled capability, final screenshot |
| `replay_success/` | Same capability, `member_id=12345`, **0 LLM calls**, outputs `$2,450.00` |
| `replay_not_found/` | Same capability, `member_id=99999`, **business outcome** `MEMBER_NOT_FOUND`, 0 LLM calls |
| `handoff/` | Control-transfer record: automation pauses, human acts on the live session, hand-back |

The replay evidence is the production path and does not use a model.

Discovery in this folder was captured with `--llm scripted` (grounded heuristic on the live UI) because no model API key was present in the capture environment. The agent loop, surface, compiler, and artifact are the same as the OpenAI/Anthropic path. To replace discovery with a genuine LLM run before you email the repo:

```bash
cp .env.example .env   # set OPENAI_API_KEY
python scripts/capture_evidence.py
```

`evidence/discovery/llm.txt` records which provider produced that capture.
