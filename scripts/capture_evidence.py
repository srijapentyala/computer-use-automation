"""Capture discovery + replay evidence folders for /evidence."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import threading
import time
from pathlib import Path

import httpx
import uvicorn

from dotenv import load_dotenv

from corebank.app import create_app
from cuas.agent.llm import build_llm
from cuas.agent.loop import DiscoveryRunner
from cuas.catalog import Catalog
from cuas.config import Policy, Settings
from cuas.evidence import EvidenceLog
from cuas.models import OutcomeKind
from cuas.replay import ReplayEngine
from cuas.surface.web import WebSurface

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"
ART = ROOT / "artifacts"
POLICY = Policy.load(ROOT / "policies" / "default.yaml")
GOAL = "look up member 12345 and read their current savings balance"


def _choose_llm(settings: Settings) -> str:
    # Explicit only. A leftover/unpaid cloud key must not wipe good evidence.
    return os.getenv("CUAS_LLM") or "scripted"


def start_core(port: int = 8787) -> str:
    app = create_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"
    deadline = time.time() + 8
    while time.time() < deadline:
        try:
            if httpx.get(url + "health", timeout=0.2).status_code == 200:
                return url
        except Exception:
            time.sleep(0.05)
    raise RuntimeError("corebank did not start")


async def main() -> None:
    load_dotenv(ROOT / ".env")
    os.environ.setdefault("COREBANK_USER", "teller")
    os.environ.setdefault("COREBANK_PASSWORD", "teller")
    url = start_core(8787)
    settings = Settings()
    llm_kind = _choose_llm(settings)
    print(f"discovery llm={llm_kind}")

    EVIDENCE.mkdir(exist_ok=True)
    ART.mkdir(exist_ok=True)
    for name in ["discovery", "replay_success", "replay_not_found"]:
        shutil.rmtree(EVIDENCE / name, ignore_errors=True)

    surface, browser, context = await WebSurface.launch(headless=True)
    try:
        evidence = EvidenceLog(EVIDENCE, "discovery")
        runner = DiscoveryRunner(
            surface,
            build_llm(llm_kind, settings),
            POLICY,
            evidence=evidence,
            start_url=url,
        )
        result, cap = await runner.run(GOAL)
        print("discovery", result.kind, result.outputs, result.business_code)
        if cap is None:
            raise SystemExit("discovery failed; not writing artifact")
        Catalog(ART).save(cap)
        evidence.dump_text("capability.json", cap.model_dump_json(indent=2))
        evidence.dump_text("result.json", result.model_dump_json(indent=2))
        evidence.dump_text(
            "llm.txt",
            f"provider={llm_kind} model={getattr(runner.llm, 'model', llm_kind)} calls={result.llm_calls}\n",
        )
    finally:
        await context.close()
        await browser.close()

    surface, browser, context = await WebSurface.launch(headless=True)
    try:
        ev = EvidenceLog(EVIDENCE, "replay_success")
        engine = ReplayEngine(surface, POLICY, evidence=ev)
        r = await engine.run(cap, {"member_id": "12345"})
        ev.dump_text("result.json", r.model_dump_json(indent=2))
        print("replay_success", r.kind, r.outputs, "llm_calls", r.llm_calls)
        if r.kind is not OutcomeKind.SUCCESS:
            raise SystemExit("expected successful replay")
    finally:
        await context.close()
        await browser.close()

    surface, browser, context = await WebSurface.launch(headless=True)
    try:
        ev = EvidenceLog(EVIDENCE, "replay_not_found")
        engine = ReplayEngine(surface, POLICY, evidence=ev)
        r = await engine.run(cap, {"member_id": "99999"})
        ev.dump_text("result.json", r.model_dump_json(indent=2))
        print("replay_not_found", r.kind, r.business_code, "llm_calls", r.llm_calls)
        if r.business_code != "MEMBER_NOT_FOUND":
            raise SystemExit("expected MEMBER_NOT_FOUND")
    finally:
        await context.close()
        await browser.close()

    print(json.dumps({"artifact": str(ART / f"{cap.id}.json")}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
