"""Cross-tenant reuse: one vendor artifact, locator overrides for a branded variant."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

from corebank.app import create_app
from cuas.config import Policy
from cuas.evidence import EvidenceLog
from cuas.models import Capability, OutcomeKind
from cuas.replay import ReplayEngine
from cuas.surface.web import WebSurface
from cuas.tenant import apply_overrides

POLICY = Policy.load(Path(__file__).resolve().parents[1] / "policies" / "default.yaml")
ART = Path(__file__).resolve().parents[1] / "artifacts" / "heritage_core.lookup_savings_balance.json"


@pytest.fixture(scope="module")
def first_cu_url():
    app = create_app("first_cu")
    config = uvicorn.Config(app, host="127.0.0.1", port=8800, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    url = "http://127.0.0.1:8800/"
    deadline = time.time() + 8
    while time.time() < deadline:
        try:
            if httpx.get(url + "health", timeout=0.2).status_code == 200:
                break
        except Exception:
            time.sleep(0.05)
    else:
        raise RuntimeError("First CU variant failed to start")
    yield url
    server.should_exit = True


def _cap() -> Capability:
    return Capability.model_validate_json(ART.read_text())


def test_overrides_rewrite_accessible_names():
    cap = _cap()
    cap.tenant.overrides = {"locator_names": {"s4_click": "Find Member", "s6_click": "Find"}}
    patched = apply_overrides(cap)
    names = {
        s.id: next(loc.name for loc in s.target.locators if loc.name)
        for s in patched.steps
        if s.id in {"s4_click", "s6_click"} and s.target
    }
    assert names["s4_click"] == "Find Member"
    assert names["s6_click"] == "Find"
    original = _cap()
    orig_s4 = next(s for s in original.steps if s.id == "s4_click")
    assert orig_s4.target.locators[0].name == "Member Search"


@pytest.mark.asyncio
async def test_vendor_default_locators_fail_on_relabeled_tenant(first_cu_url, tmp_path):
    os.environ["COREBANK_USER"] = "teller"
    os.environ["COREBANK_PASSWORD"] = "teller"
    cap = _cap()
    cap.app.entry_url = first_cu_url
    surface, browser, context = await WebSurface.launch(headless=True)
    try:
        engine = ReplayEngine(surface, POLICY, evidence=EvidenceLog(tmp_path, "no-ov"))
        result = await engine.run(cap, {"member_id": "12345"})
        assert result.kind is OutcomeKind.FAILURE
        assert result.error and "not found" in result.error.expected.lower()
    finally:
        await context.close()
        await browser.close()


@pytest.mark.asyncio
async def test_tenant_overrides_replay_on_relabeled_variant(first_cu_url, tmp_path):
    os.environ["COREBANK_USER"] = "teller"
    os.environ["COREBANK_PASSWORD"] = "teller"
    cap = _cap()
    cap.tenant.scope = "tenant"
    cap.tenant.tenant_id = "first_cu"
    cap.tenant.overrides = {
        "entry_url": first_cu_url,
        "locator_names": {
            "s4_click": "Find Member",
            "s6_click": "Find",
            "s7_click": "Open Record",
        },
    }
    surface, browser, context = await WebSurface.launch(headless=True)
    try:
        engine = ReplayEngine(surface, POLICY, evidence=EvidenceLog(tmp_path, "ov"))
        result = await engine.run(cap, {"member_id": "12345"})
        assert result.kind is OutcomeKind.SUCCESS, result
        assert result.llm_calls == 0
        assert any(v.startswith("$") for v in result.outputs.values())
    finally:
        await context.close()
        await browser.close()
