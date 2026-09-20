# Evidence

Checked-in runs against the local Heritage Core teller console.

| Folder | What it shows |
| --- | --- |
| `discovery/` | Observe→decide→act loop, compiled capability, final screenshot |
| `replay_success/` | Same capability, `member_id=12345`, **0 LLM calls**, outputs `$2,450.00` |
| `replay_not_found/` | Same capability, `member_id=99999`, **business outcome** `MEMBER_NOT_FOUND`, 0 LLM calls |
| `replay_tenant/` | Same flow on First CU branded chrome via locator overrides, 0 LLM calls |
| `handoff/` | Live session: policy blocks Submit Transfer, human acts on the **same** Playwright page, hand-back |

The replay evidence is the production path and does not use a model.

Discovery in this folder is a **genuine LLM-driven run** on the live Heritage Core UI via TAMUS AI Chat (`protected.gemini-2.5-flash-lite`, 8 model calls). Replay folders are the production path: **0 LLM calls**.

Recapture replays / handoff / tenant (keeps the TAMUS discovery):

```bash
python scripts/capture_evidence.py
```

`evidence/discovery/llm.txt` records which provider produced that capture.
