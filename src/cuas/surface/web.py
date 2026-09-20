"""Playwright web surface: observe via frames + a11y-ish control inventory."""

from __future__ import annotations

import hashlib
import re
import time
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from cuas.models import ActionType, Target
from cuas.models.observation import InteractiveElement, Observation
from cuas.surface.base import locators_from_element
from cuas.surface.locators import LocatorError, resolve

COLLECT_JS = """() => {
  const visible = (el) => {
    const s = window.getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const adjacent = (el) => {
    if (el.id) {
      const lab = document.querySelector(`label[for="${el.id}"]`);
      if (lab) return lab.innerText.trim();
    }
    const td = el.closest('td');
    if (td) {
      const prev = td.previousElementSibling;
      if (prev) return prev.innerText.trim();
    }
    const labelled = el.getAttribute('aria-label');
    return labelled || '';
  };
  const cssPath = (el) => {
    if (el.name) return `${el.tagName.toLowerCase()}[name="${el.name}"]`;
    if (el.id) return `#${el.id}`;
    const tag = el.tagName.toLowerCase();
    const parent = el.parentElement;
    if (!parent) return tag;
    const same = [...parent.children].filter((c) => c.tagName === el.tagName);
    const idx = same.indexOf(el) + 1;
    return `${tag}:nth-of-type(${idx})`;
  };
  const roleOf = (el) => {
    const explicit = el.getAttribute('role');
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === 'a') return 'link';
    if (tag === 'button') return 'button';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'input') {
      const t = (el.getAttribute('type') || 'text').toLowerCase();
      if (t === 'submit' || t === 'button' || t === 'reset') return 'button';
      if (t === 'checkbox') return 'checkbox';
      if (t === 'radio') return 'radio';
      if (t === 'password') return 'textbox';
      return 'textbox';
    }
    return 'generic';
  };
  const sel = 'a[href], button, input, select, textarea';
  const nodes = [...document.querySelectorAll(sel)].filter(visible);
  const elements = nodes.map((el) => {
    const role = roleOf(el);
    const name = (el.getAttribute('aria-label')
      || (el.tagName === 'INPUT' && (el.type === 'submit' || el.type === 'button') ? el.value : '')
      || (el.innerText || '').trim()
      || '').trim();
    return {
      role,
      name,
      adjacent: adjacent(el),
      placeholder: el.getAttribute('placeholder') || '',
      value: (el.type === 'password') ? '' : (el.value || ''),
      tag: el.tagName.toLowerCase(),
      css: cssPath(el),
      disabled: !!el.disabled,
    };
  });
  const banners = [...document.querySelectorAll('.err, .overlay, [role=alert]')]
    .map((el) => el.innerText.trim())
    .filter(Boolean);
  const headings = [...document.querySelectorAll('.banner, h1, h2, caption')]
    .map((el) => el.innerText.trim())
    .filter(Boolean);
  return {
    title: document.title,
    text: document.body ? document.body.innerText : '',
    elements,
    banners,
    headings,
  };
}"""


RISKY_NAME = re.compile(
    r"(?i)(transfer|close account|close membership|cannot be undone|post(ing)? )",
)


class WebSurface:
    name = "web"

    def __init__(self, page: Page):
        self.page = page
        self._last_obs: Observation | None = None

    @classmethod
    async def launch(
        cls,
        *,
        headless: bool = True,
        start_url: str | None = None,
    ) -> tuple["WebSurface", Browser, BrowserContext]:
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=headless)
        context = await browser.new_context(viewport={"width": 1200, "height": 800})
        page = await context.new_page()
        surface = cls(page)
        surface._pw = pw  # type: ignore[attr-defined]
        if start_url:
            await surface.goto(start_url)
        return surface, browser, context

    async def goto(self, url: str) -> None:
        await self.page.goto(url, wait_until="domcontentloaded")

    async def observe(self) -> Observation:
        await self.page.wait_for_timeout(200)
        for frame in self.page.frames:
            if frame.name in {"main", "nav"}:
                try:
                    await frame.wait_for_load_state("domcontentloaded", timeout=2000)
                except Exception:
                    pass
        frames = self.page.frames
        frame_names = [f.name for f in frames if f.name]
        elements: list[InteractiveElement] = []
        headings: list[str] = []
        errors: list[str] = []
        dialogs: list[str] = []
        text_parts: list[str] = []
        ref_i = 0
        for frame in frames:
            try:
                raw = await frame.evaluate(COLLECT_JS)
            except Exception:  # noqa: BLE001 — detached/about:blank frames
                continue
            text_parts.append(raw.get("text") or "")
            headings.extend(raw.get("headings") or [])
            for banner in raw.get("banners") or []:
                if re.search(r"(?i)(processing window|dialog|cannot be undone)", banner):
                    dialogs.append(banner)
                if re.search(r"(?i)(error|not found|expired|invalid|correct the|insufficient)", banner):
                    errors.append(banner)
                elif banner not in errors and banner not in dialogs:
                    errors.append(banner)
            fname = frame.name or None
            # Skip chrome-level duplicates on the shell document if frames exist.
            if fname is None and frame_names:
                continue
            for item in raw.get("elements") or []:
                el = InteractiveElement(
                    ref=f"e{ref_i}",
                    role=item.get("role") or "generic",
                    name=item.get("name") or "",
                    adjacent_text=item.get("adjacent") or "",
                    placeholder=item.get("placeholder") or "",
                    value=item.get("value") or "",
                    tag=item.get("tag") or "",
                    frame=fname,
                    css=item.get("css") or "",
                    disabled=bool(item.get("disabled")),
                    risky=bool(RISKY_NAME.search((item.get("name") or "") + " " + (item.get("adjacent") or ""))),
                )
                elements.append(el)
                ref_i += 1
        visible = "\n".join(p for p in text_parts if p).strip()
        # Include non-secret field values so typing is visible to the loop detector.
        control_fp = ",".join(
            f"{e.ref}:{e.role}:{e.name}:{e.adjacent_text}:{e.value}:{e.frame}"
            for e in elements
        )
        fp_src = self.page.url + "\n" + visible[:2000] + "\n" + control_fp
        obs = Observation(
            url=self.page.url,
            title=await self.page.title(),
            frame_names=frame_names,
            elements=elements,
            visible_text=visible,
            headings=headings,
            errors=errors,
            dialogs=dialogs,
            fingerprint=hashlib.sha256(fp_src.encode()).hexdigest()[:16],
        )
        self._last_obs = obs
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
        if action is ActionType.NAVIGATE:
            if not url:
                raise LocatorError("navigate requires a url", tried=[])
            await self.goto(url)
            return {"navigated": url}
        if action is ActionType.WAIT:
            await self.page.wait_for_timeout(int(value or 400))
            return {"waited": True}
        if action is ActionType.SCREENSHOT:
            return {"screenshot": True}
        if target is None:
            raise LocatorError(f"{action.value} requires a target", tried=[])
        handle = await resolve(self.page, target)
        if action in {ActionType.CLICK, ActionType.DISMISS}:
            await handle.click()
            try:
                await self.page.wait_for_load_state("domcontentloaded", timeout=4000)
            except Exception:  # noqa: BLE001
                pass
            await self.page.wait_for_timeout(400)
            return {"clicked": True}
        if action is ActionType.TYPE:
            await handle.click()
            await handle.fill(value or "")
            return {"typed": True}
        if action is ActionType.SELECT:
            await handle.select_option(value or "")
            return {"selected": value}
        if action is ActionType.PRESS:
            await handle.press(key or "Enter")
            return {"pressed": key or "Enter"}
        if action is ActionType.EXTRACT:
            text = (await handle.inner_text()).strip()
            if not text:
                text = (await handle.input_value()) if await handle.evaluate("el => 'value' in el") else ""
            return {"text": text}
        raise LocatorError(f"unsupported action {action}", tried=target.locators)

    async def extract(self, target: Target) -> str:
        handle = await resolve(self.page, target)
        try:
            text = (await handle.inner_text()).strip()
            if text:
                return text
        except Exception:  # noqa: BLE001
            pass
        try:
            return (await handle.input_value()).strip()
        except Exception:  # noqa: BLE001
            return ""

    async def visible_text(self) -> str:
        parts = []
        for frame in self.page.frames:
            try:
                parts.append(await frame.inner_text("body"))
            except Exception:  # noqa: BLE001
                continue
        return "\n".join(parts)

    async def wait_for_text(self, text: str, timeout_ms: int = 8000) -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        needle = (text or "").lower()
        last = ""
        while time.monotonic() < deadline:
            last = await self.visible_text()
            if needle and needle in last.lower():
                return
            await self.page.wait_for_timeout(150)
        raise LocatorError(f"timed out waiting for text {text!r}", tried=[])

    async def wait_for_url(self, fragment: str, timeout_ms: int = 8000) -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            if fragment in (self.page.url or ""):
                return
            await self.page.wait_for_timeout(150)
        raise LocatorError(f"timed out waiting for url containing {fragment!r}", tried=[])

    async def screenshot(self, path: str) -> None:
        await self.page.screenshot(path=path, full_page=True)

    async def close(self) -> None:
        return None
