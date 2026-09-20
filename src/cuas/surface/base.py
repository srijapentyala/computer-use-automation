from __future__ import annotations

from typing import Any, Protocol

from cuas.models import ActionType, Locator, Target
from cuas.models.observation import Observation


class SurfaceAdapter(Protocol):
    """Perception + actuation for one kind of UI.

    The recorded flow (Capability) is surface-agnostic at the action layer.
    A web adapter and a future desktop adapter both implement this protocol
    so the agent loop and replay engine do not care how pixels are clicked.
    """

    name: str

    async def observe(self) -> Observation: ...

    async def act(
        self,
        action: ActionType,
        *,
        target: Target | None = None,
        value: str | None = None,
        url: str | None = None,
        key: str | None = None,
    ) -> dict[str, Any]: ...

    async def screenshot(self, path: str) -> None: ...

    async def extract(self, target: Target) -> str: ...

    async def visible_text(self) -> str: ...

    async def goto(self, url: str) -> None: ...

    async def close(self) -> None: ...

    def locators_for_ref(self, observation: Observation, ref: str) -> Target: ...


def locators_from_element(el) -> list[Locator]:
    """Rank locators for an observed control. Shared by live and fake surfaces."""
    from cuas.models import LocatorStrategy

    ranked: list[Locator] = []
    if el.role and el.name:
        ranked.append(
            Locator(
                strategy=LocatorStrategy.ROLE_NAME,
                role=el.role,
                name=el.name,
                nth=0,
                confidence=0.9,
                why="Accessible name is stable across branded tenants of the same vendor app.",
            )
        )
    if el.adjacent_text:
        ranked.append(
            Locator(
                strategy=LocatorStrategy.ADJACENT_TEXT,
                role=el.role or "textbox",
                text=el.adjacent_text.rstrip(":"),
                nth=0,
                confidence=0.82,
                why="Legacy table forms label controls in the previous cell, not via <label>.",
            )
        )
    if el.placeholder:
        ranked.append(
            Locator(
                strategy=LocatorStrategy.PLACEHOLDER,
                placeholder=el.placeholder,
                confidence=0.55,
                why="Placeholder text is a weak but sometimes unique hint.",
            )
        )
    if el.name and not el.role:
        ranked.append(
            Locator(
                strategy=LocatorStrategy.TEXT,
                text=el.name,
                confidence=0.6,
                why="Visible text match for links and buttons without a mapped role.",
            )
        )
    if el.css:
        ranked.append(
            Locator(
                strategy=LocatorStrategy.CSS,
                css=el.css,
                confidence=0.25,
                why="Last-resort CSS; expected to break across tenants and versions.",
            )
        )
    if not ranked:
        ranked.append(
            Locator(
                strategy=LocatorStrategy.CSS,
                css=el.css or "body",
                confidence=0.1,
                why="No robust locator could be derived.",
            )
        )
    return ranked
