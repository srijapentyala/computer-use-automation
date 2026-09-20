import asyncio

import pytest

from cuas.handoff.session import LiveSession
from cuas.models import ControlOwner


def test_control_transfer_pause_and_resume():
    session = LiveSession(session_id="test")
    assert session.in_automation
    req = session.request_intervention(
        "locator failed",
        goal="lookup",
        step_id="s4",
        observation_summary="error banner visible",
    )
    assert session.owner is ControlOwner.HUMAN
    assert req.status == "open"
    assert not session._resume.is_set()

    session.take_control("alice")
    session.record_human({"type": "click", "ref": "e2"})
    assert session.intervention.status == "in_control"
    assert session.human_actions[-1]["type"] == "click"

    session.hand_back("clicked View Record")
    assert session.owner is ControlOwner.AUTOMATION
    assert session._resume.is_set()
    assert session.intervention.status == "resolved"
    assert session.intervention.resolution


@pytest.mark.asyncio
async def test_wait_unblocks_after_operator_hands_back():
    session = LiveSession(session_id="wait")
    session.request_intervention("irreversible blocked", goal="transfer")

    async def operator():
        await asyncio.sleep(0.05)
        session.take_control("alice")
        session.hand_back("declined the post")

    asyncio.create_task(operator())
    await session.wait_if_human_in_control(timeout=2)
    assert session.in_automation
    assert session.intervention.status == "resolved"
