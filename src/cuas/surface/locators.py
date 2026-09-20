"""Resolve ranked locators against a Playwright frame."""

from __future__ import annotations

import re

from playwright.async_api import Frame, Locator as PwLocator, Page

from cuas.models import Locator, LocatorStrategy, Target


class LocatorError(Exception):
    def __init__(self, message: str, *, tried: list[Locator]):
        super().__init__(message)
        self.tried = tried


def frame_by_name(page: Page, name: str | None) -> Page | Frame:
    if not name:
        return page
    for frame in page.frames:
        if frame.name == name:
            return frame
    # iframe element name/id fallback
    for frame in page.frames:
        if name in (frame.url or "") or name in (frame.name or ""):
            return frame
    raise LocatorError(f"frame '{name}' not found", tried=[])


def _candidate(root: Page | Frame, loc: Locator) -> PwLocator:
    if loc.strategy is LocatorStrategy.ROLE_NAME:
        role = loc.role or "generic"
        kwargs: dict = {}
        if loc.name:
            kwargs["name"] = re.compile(rf"^{re.escape(loc.name)}$", re.I)
        return root.get_by_role(role, **kwargs)
    if loc.strategy is LocatorStrategy.ADJACENT_TEXT:
        label = loc.text or ""
        # Table-cell labelling: the control lives in the cell after the label cell.
        labeled = root.locator("td,th").filter(
            has_text=re.compile(rf"^{re.escape(label)}\s*:?\s*$", re.I)
        )
        following = labeled.locator("xpath=following-sibling::td[1]").locator(
            "input, textarea, select, button, a"
        )
        return following
    if loc.strategy is LocatorStrategy.PLACEHOLDER:
        return root.get_by_placeholder(loc.placeholder or "", exact=False)
    if loc.strategy is LocatorStrategy.TEXT:
        return root.get_by_text(loc.text or "", exact=True)
    if loc.strategy is LocatorStrategy.CSS:
        return root.locator(loc.css or "body")
    raise LocatorError(f"unknown strategy {loc.strategy}", tried=[loc])


async def resolve(page: Page, target: Target, timeout_ms: int = 8000) -> PwLocator:
    root = frame_by_name(page, target.frame)
    errors: list[str] = []
    for loc in target.locators:
        try:
            handle = _candidate(root, loc)
            count = await handle.count()
            if count == 0:
                errors.append(f"{loc.strategy.value}: 0 matches")
                continue
            chosen = handle.nth(loc.nth)
            await chosen.wait_for(state="visible", timeout=timeout_ms)
            return chosen
        except Exception as exc:  # noqa: BLE001 — collect and try the next locator
            errors.append(f"{loc.strategy.value}: {exc}")
            continue
    raise LocatorError(
        "none of the ranked locators resolved: " + " | ".join(errors),
        tried=list(target.locators),
    )
