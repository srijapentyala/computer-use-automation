"""Capture a real live-session handoff against Heritage Core.

Automation reaches an irreversible control, policy blocks it, the operator
acts on the *same* Playwright page, then hands control back.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from cuas.config import Policy
from cuas.evidence import EvidenceLog
from cuas.handoff.session import LiveSession
from cuas.models import ActionType
from cuas.safety.guardrails import Guardrails, PolicyViolation
from cuas.surface.web import WebSurface

ROOT = Path(__file__).resolve().parents[1]
POLICY = Policy.load(ROOT / "policies" / "default.yaml")


async def _click_name(surface: WebSurface, name: str) -> None:
    obs = await surface.observe()
    needle = name.lower()
    el = next((e for e in obs.elements if (e.name or "").lower() == needle), None)
    if el is None:
        el = next(
            (
                e
                for e in obs.elements
                if needle in (e.name or "").lower() or needle in (e.adjacent_text or "").lower()
            ),
            None,
        )
    if el is None:
        raise RuntimeError(
            f"no control matching {name!r}; saw "
            + ", ".join(f"{e.ref}:{e.role}:{e.name}" for e in obs.elements[:20])
        )
    await surface.act(ActionType.CLICK, target=surface.locators_for_ref(obs, el.ref))


async def _type_adjacent(surface: WebSurface, label: str, value: str) -> None:
    obs = await surface.observe()
    el = next(e for e in obs.elements if label.lower() in (e.adjacent_text or "").lower())
    await surface.act(
        ActionType.TYPE, target=surface.locators_for_ref(obs, el.ref), value=value
    )


async def capture_handoff(url: str, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    for child in dest.iterdir():
        if child.is_file():
            child.unlink()
    evidence = EvidenceLog(dest.parent, dest.name)
    session = LiveSession(session_id="live-handoff", store_dir=dest)
    surface, browser, context = await WebSurface.launch(headless=True)
    guard = Guardrails(POLICY)
    try:
        await surface.goto(url)
        await _type_adjacent(surface, "Operator ID", "teller")
        await _type_adjacent(surface, "Password", "teller")
        await _click_name(surface, "Sign On")
        await _click_name(surface, "Member Search")
        await _type_adjacent(surface, "Member ID", "12345")
        await _click_name(surface, "Go")
        await surface.wait_for_text("View Record", timeout_ms=8000)
        await _click_name(surface, "View Record")
        await surface.wait_for_text("Member Record", timeout_ms=8000)
        await _click_name(surface, "Funds Transfer")
        try:
            await surface.wait_for_text("Post Transfer", timeout_ms=8000)
        except Exception:
            blob = await surface.visible_text()
            raise RuntimeError(
                f"transfer form not reached (need member in session); url={surface.page.url!r} text={blob[:900]!r}"
            ) from None

        obs = await surface.observe()
        submit = next(e for e in obs.elements if "submit transfer" in (e.name or "").lower())
        try:
            guard.check_decision("click", obs, element=submit)
            raise RuntimeError("expected irreversible block")
        except PolicyViolation as exc:
            assert exc.code == "IRREVERSIBLE_BLOCKED"
            evidence.write("policy_block", code=exc.code, message=str(exc))

        shot = evidence.screenshot_path("escalate")
        await surface.screenshot(str(shot))
        req = session.request_intervention(
            "Irreversible action blocked by policy: Submit Transfer",
            capability_id="heritage_core.funds_transfer",
            goal="post a funds transfer for member 12345",
            step_id="s8_click",
            observation_summary=obs.summary(),
            screenshot_path=str(shot),
        )
        evidence.write("escalated", reason=req.reason, intervention_id=req.id)

        session.take_control("operator-alice")
        obs2 = await surface.observe()
        search = next(e for e in obs2.elements if "member search" in (e.name or "").lower())
        await surface.act(ActionType.CLICK, target=surface.locators_for_ref(obs2, search.ref))
        session.record_human(
            {
                "type": "click",
                "ref": search.ref,
                "note": "opened member search instead of posting the transfer",
            }
        )
        after = evidence.screenshot_path("after_human")
        await surface.screenshot(str(after))
        session.hand_back("operator declined the irreversible post; resume on search")
        evidence.write("handoff_resumed", intervention_id=req.id)

        final = await surface.observe()
        assert session.in_automation
        assert "Submit Transfer" not in (final.visible_text or "")
        assert any("Member Inquiry" in (final.visible_text or "") or "Lookup" in (h or "") for h in (final.headings or [final.visible_text]))

        evidence.dump_text(
            "result.json",
            json.dumps(
                {
                    "kind": "escalated_then_resumed",
                    "intervention_id": req.id,
                    "owner_after": session.owner.value,
                    "human_actions": session.human_actions,
                    "resolution": session.intervention.resolution if session.intervention else None,
                    "llm_calls": 0,
                    "same_playwright_page": True,
                },
                indent=2,
            ),
        )
        return dest / "live-handoff.json"
    finally:
        await context.close()
        await browser.close()


async def main() -> None:
    import threading
    import time

    import httpx
    import uvicorn

    from corebank.app import create_app

    app = create_app("heritage")
    config = uvicorn.Config(app, host="127.0.0.1", port=8787, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    url = "http://127.0.0.1:8787/"
    deadline = time.time() + 8
    while time.time() < deadline:
        try:
            if httpx.get(url + "health", timeout=0.2).status_code == 200:
                break
        except Exception:
            time.sleep(0.05)
    else:
        raise RuntimeError("corebank did not start")
    dest = ROOT / "evidence" / "handoff"
    path = await capture_handoff(url, dest)
    print(path)


if __name__ == "__main__":
    asyncio.run(main())
