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
from cuas.models import Capability, OutcomeKind
from cuas.replay import ReplayEngine
from cuas.surface.web import WebSurface

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from capture_handoff import capture_handoff  # noqa: E402
EVIDENCE = ROOT / "evidence"
ART = ROOT / "artifacts"
POLICY = Policy.load(ROOT / "policies" / "default.yaml")
GOAL = "look up member 12345 and read their current savings balance"


def _choose_llm(settings: Settings) -> str:
    return os.getenv("CUAS_LLM") or "scripted"


def start_core(port: int, brand: str = "heritage") -> str:
    app = create_app(brand)
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
    raise RuntimeError(f"corebank {brand} did not start on {port}")


async def _replay(cap: Capability, params: dict[str, str], folder: str):
    dest = EVIDENCE / folder
    shutil.rmtree(dest, ignore_errors=True)
    surface, browser, context = await WebSurface.launch(headless=True)
    try:
        ev = EvidenceLog(EVIDENCE, folder)
        engine = ReplayEngine(surface, POLICY, evidence=ev)
        r = await engine.run(cap, params)
        ev.dump_text("result.json", r.model_dump_json(indent=2))
        print(folder, r.kind, r.outputs or r.business_code, "llm_calls", r.llm_calls)
        return r
    finally:
        await context.close()
        await browser.close()


async def main() -> None:
    load_dotenv(ROOT / ".env")
    os.environ.setdefault("COREBANK_USER", "teller")
    os.environ.setdefault("COREBANK_PASSWORD", "teller")
    url = start_core(8787, "heritage")
    settings = Settings()
    llm_kind = _choose_llm(settings)
    recapture_discovery = bool(os.getenv("CUAS_LLM"))
    print(f"discovery llm={llm_kind} recapture={recapture_discovery}")

    EVIDENCE.mkdir(exist_ok=True)
    ART.mkdir(exist_ok=True)
    cap_path = ART / "heritage_core.lookup_savings_balance.json"

    if recapture_discovery:
        shutil.rmtree(EVIDENCE / "discovery", ignore_errors=True)
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
    else:
        cap = Capability.model_validate_json(cap_path.read_text())

    cap = Capability.model_validate_json(cap_path.read_text())
    r_ok = await _replay(cap, {"member_id": "12345"}, "replay_success")
    if r_ok.kind is not OutcomeKind.SUCCESS:
        raise SystemExit("expected successful replay")
    r_miss = await _replay(cap, {"member_id": "99999"}, "replay_not_found")
    if r_miss.business_code != "MEMBER_NOT_FOUND":
        raise SystemExit("expected MEMBER_NOT_FOUND")

    await capture_handoff(url, EVIDENCE / "handoff")
    print("handoff captured")

    variant_url = start_core(8786, "first_cu")
    tenant_path = ART / "heritage_core.lookup_savings_balance.first_cu.json"
    tenant_cap = Capability.model_validate_json(tenant_path.read_text())
    tenant_cap.tenant.overrides["entry_url"] = variant_url
    shutil.rmtree(EVIDENCE / "replay_tenant", ignore_errors=True)
    surface, browser, context = await WebSurface.launch(headless=True)
    try:
        ev = EvidenceLog(EVIDENCE, "replay_tenant")
        engine = ReplayEngine(surface, POLICY, evidence=ev)
        r = await engine.run(tenant_cap, {"member_id": "12345"})
        ev.dump_text("result.json", r.model_dump_json(indent=2))
        print("replay_tenant", r.kind, r.outputs, "llm_calls", r.llm_calls)
        if r.kind is not OutcomeKind.SUCCESS:
            raise SystemExit("expected tenant override replay to succeed")
    finally:
        await context.close()
        await browser.close()

    print(json.dumps({"artifact": str(cap_path)}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
