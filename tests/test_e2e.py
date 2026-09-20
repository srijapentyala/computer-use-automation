"""End-to-end: scripted discovery, deterministic replay, not-found outcome, handoff."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cuas.agent.llm import ScriptedLLM
from cuas.agent.loop import DiscoveryRunner
from cuas.config import Policy
from cuas.evidence import EvidenceLog
from cuas.handoff.session import LiveSession
from cuas.models import ControlOwner, OutcomeKind
from cuas.replay import ReplayEngine
from cuas.surface.web import WebSurface

POLICY = Policy.load(Path(__file__).resolve().parents[1] / "policies" / "default.yaml")
GOAL = "look up member 12345 and read their current savings balance"


@pytest.mark.asyncio
async def test_scripted_discovery_then_replay_success(corebank_url, tmp_path):
    os.environ["COREBANK_USER"] = "teller"
    os.environ["COREBANK_PASSWORD"] = "teller"
    surface, browser, context = await WebSurface.launch(headless=True)
    try:
        evidence = EvidenceLog(tmp_path, "discover")
        runner = DiscoveryRunner(
            surface,
            ScriptedLLM(),
            POLICY,
            evidence=evidence,
            start_url=corebank_url,
        )
        result, cap = await runner.run(GOAL)
        assert result.kind is OutcomeKind.SUCCESS, result
        assert cap is not None
        assert "savings_balance" in result.outputs
        assert result.outputs["savings_balance"].startswith("$")
        assert any(p.name == "member_id" for p in cap.parameters)
        (tmp_path / "cap.json").write_text(cap.model_dump_json(indent=2))
    finally:
        await context.close()
        await browser.close()

    surface, browser, context = await WebSurface.launch(headless=True)
    try:
        engine = ReplayEngine(
            surface, POLICY, evidence=EvidenceLog(tmp_path, "replay-ok")
        )
        replayed = await engine.run(cap, {"member_id": "12345"})
        assert replayed.kind is OutcomeKind.SUCCESS, replayed
        assert replayed.llm_calls == 0
        assert replayed.outputs["savings_balance"] == result.outputs["savings_balance"]
    finally:
        await context.close()
        await browser.close()


@pytest.mark.asyncio
async def test_replay_member_not_found_is_business_outcome(corebank_url, tmp_path):
    os.environ["COREBANK_USER"] = "teller"
    os.environ["COREBANK_PASSWORD"] = "teller"
    surface, browser, context = await WebSurface.launch(headless=True)
    try:
        runner = DiscoveryRunner(
            surface,
            ScriptedLLM(),
            POLICY,
            evidence=EvidenceLog(tmp_path, "discover2"),
            start_url=corebank_url,
        )
        result, cap = await runner.run(GOAL)
        assert cap is not None
    finally:
        await context.close()
        await browser.close()

    surface, browser, context = await WebSurface.launch(headless=True)
    try:
        engine = ReplayEngine(
            surface, POLICY, evidence=EvidenceLog(tmp_path, "replay-miss")
        )
        replayed = await engine.run(cap, {"member_id": "99999"})
        assert replayed.kind is OutcomeKind.BUSINESS
        assert replayed.business_code == "MEMBER_NOT_FOUND"
        assert replayed.ok
        assert replayed.llm_calls == 0
    finally:
        await context.close()
        await browser.close()


@pytest.mark.asyncio
async def test_handoff_pauses_live_session_and_resumes(corebank_url):
    session = LiveSession()
    surface, browser, context = await WebSurface.launch(headless=True)
    try:
        await surface.goto(corebank_url)
        req = session.request_intervention("stuck on login", goal=GOAL)
        assert session.owner is ControlOwner.HUMAN

        # Human uses the SAME page object.
        obs = await surface.observe()
        op = next(e for e in obs.elements if "Operator ID" in e.adjacent_text)
        await surface.act(
            __import__("cuas.models", fromlist=["ActionType"]).ActionType.TYPE,
            target=surface.locators_for_ref(obs, op.ref),
            value="teller",
        )
        session.record_human({"type": "type", "ref": op.ref, "value": "[REDACTED]"})
        session.hand_back("typed operator id")
        assert session.in_automation
        assert req.status == "resolved"
        obs2 = await surface.observe()
        assert any("Operator ID" in e.adjacent_text and e.value == "teller" for e in obs2.elements)
    finally:
        await context.close()
        await browser.close()
