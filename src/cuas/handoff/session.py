"""Pause automation, cede the live session to a human, resume on the same page."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from cuas.models import ControlOwner, InterventionRequest


class LiveSession:
    """Control-transfer object shared by the agent, replay engine, and operator.

    The Playwright page (or fake surface) never changes identity across a
    handoff. Only `owner` flips. That is the seam the assignment asks for.
    """

    def __init__(self, session_id: str | None = None, *, store_dir: Path | None = None):
        self.session_id = session_id or uuid4().hex[:10]
        self.owner = ControlOwner.AUTOMATION
        self.intervention: InterventionRequest | None = None
        self.store_dir = Path(store_dir or "runs/handoff")
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self._resume = asyncio.Event()
        self._resume.set()
        self.human_actions: list[dict[str, Any]] = []

    @property
    def in_automation(self) -> bool:
        return self.owner is ControlOwner.AUTOMATION

    async def wait_if_human_in_control(self) -> None:
        await self._resume.wait()

    def request_intervention(
        self,
        reason: str,
        *,
        goal: str | None = None,
        capability_id: str | None = None,
        step_id: str | None = None,
        observation_summary: str = "",
        screenshot_path: str | None = None,
    ) -> InterventionRequest:
        req = InterventionRequest(
            id=uuid4().hex[:12],
            session_id=self.session_id,
            reason=reason,
            capability_id=capability_id,
            goal=goal,
            step_id=step_id,
            observation_summary=observation_summary,
            screenshot_path=screenshot_path,
            created_at=datetime.now(timezone.utc).isoformat(),
            status="open",
        )
        self.intervention = req
        self.owner = ControlOwner.HUMAN
        self._resume.clear()
        self._persist()
        return req

    def take_control(self, operator_id: str = "operator") -> None:
        if not self.intervention:
            raise RuntimeError("no open intervention")
        self.owner = ControlOwner.HUMAN
        self.intervention.status = "in_control"
        self.record_human({"type": "take_control", "operator": operator_id})
        self._persist()

    def record_human(self, action: dict[str, Any]) -> None:
        stamped = {"ts": datetime.now(timezone.utc).isoformat(), **action}
        self.human_actions.append(stamped)
        if self.intervention:
            self.intervention.human_actions.append(stamped)
        self._persist()

    def hand_back(self, resolution: str = "human completed the blocked step") -> None:
        if self.intervention:
            self.intervention.status = "resolved"
            self.intervention.resolution = resolution
        self.owner = ControlOwner.AUTOMATION
        self._persist()
        self._resume.set()

    def abort(self, reason: str) -> None:
        if self.intervention:
            self.intervention.status = "aborted"
            self.intervention.resolution = reason
        self.owner = ControlOwner.NONE
        self._persist()
        self._resume.set()

    def _persist(self) -> None:
        payload = {
            "session_id": self.session_id,
            "owner": self.owner.value,
            "intervention": self.intervention.model_dump() if self.intervention else None,
            "human_actions": self.human_actions,
        }
        path = self.store_dir / f"{self.session_id}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
