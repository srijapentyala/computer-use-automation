"""In-memory surface used by unit tests — same protocol, no browser."""

from __future__ import annotations

from typing import Any

from cuas.models import ActionType, Target
from cuas.models.observation import InteractiveElement, Observation
from cuas.surface.base import locators_from_element


class FakeSurface:
    name = "fake"

    def __init__(self, pages: dict[str, Observation], start: str):
        self.pages = pages
        self.current = start
        self.typed: dict[str, str] = {}
        self.actions: list[str] = []
        self._screenshots: list[str] = []

    async def observe(self) -> Observation:
        obs = self.pages[self.current]
        for el in obs.elements:
            if el.ref in self.typed:
                el.value = self.typed[el.ref]
        return obs

    def locators_for_ref(self, observation: Observation, ref: str) -> Target:
        el = observation.element(ref)
        return Target(locators=locators_from_element(el), frame=el.frame)

    async def act(
        self,
        action: ActionType,
        *,
        target: Target | None = None,
        value: str | None = None,
        url: str | None = None,
        key: str | None = None,
    ) -> dict[str, Any]:
        self.actions.append(action.value)
        if action is ActionType.NAVIGATE and url:
            self.current = url
            return {"navigated": url}
        if action is ActionType.TYPE and target:
            # Store against adjacent text so tests can inspect it.
            key_name = target.locators[0].text or target.locators[0].name or "field"
            self.typed[key_name] = value or ""
            return {"typed": True}
        if action is ActionType.CLICK:
            return {"clicked": True}
        return {"ok": True}

    async def screenshot(self, path: str) -> None:
        self._screenshots.append(path)

    async def extract(self, target: Target) -> str:
        return self.pages[self.current].visible_text

    async def visible_text(self) -> str:
        return self.pages[self.current].visible_text

    async def goto(self, url: str) -> None:
        self.current = url

    async def close(self) -> None:
        return None
