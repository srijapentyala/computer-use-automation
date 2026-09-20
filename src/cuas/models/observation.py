from __future__ import annotations

from pydantic import BaseModel, Field


class InteractiveElement(BaseModel):
    """A grounded, numbered control the LLM may choose.

    Replay never uses `ref` — refs are session-local. The ranked locators
    travel with the compiled artifact instead.
    """

    ref: str
    role: str
    name: str = ""
    adjacent_text: str = ""
    placeholder: str = ""
    value: str = ""
    tag: str = ""
    frame: str | None = None
    css: str = ""
    disabled: bool = False
    risky: bool = False


class Observation(BaseModel):
    url: str
    title: str = ""
    frame_names: list[str] = Field(default_factory=list)
    elements: list[InteractiveElement] = Field(default_factory=list)
    visible_text: str = ""
    headings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    dialogs: list[str] = Field(default_factory=list)
    fingerprint: str = ""

    def element(self, ref: str) -> InteractiveElement:
        for el in self.elements:
            if el.ref == ref:
                return el
        raise KeyError(f"unknown element ref {ref}")

    def summary(self, max_text: int = 1800) -> str:
        lines = [
            f"URL: {self.url}",
            f"Title: {self.title}",
            f"Frames: {', '.join(self.frame_names) or '(none)'}",
        ]
        if self.headings:
            lines.append("Headings: " + " | ".join(self.headings[:8]))
        if self.errors:
            lines.append("Errors: " + " | ".join(self.errors))
        if self.dialogs:
            lines.append("Dialogs: " + " | ".join(self.dialogs))
        lines.append("Interactive elements:")
        for el in self.elements:
            bits = [f"[{el.ref}]", el.role]
            if el.name:
                bits.append(f'name="{el.name}"')
            if el.adjacent_text:
                bits.append(f'adjacent="{el.adjacent_text}"')
            if el.placeholder:
                bits.append(f'placeholder="{el.placeholder}"')
            if el.value:
                bits.append(f'value="{el.value}"')
            if el.frame:
                bits.append(f"frame={el.frame}")
            if el.risky:
                bits.append("RISKY")
            if el.disabled:
                bits.append("disabled")
            lines.append("  " + " ".join(bits))
        text = self.visible_text.strip().replace("\n", " / ")
        if len(text) > max_text:
            text = text[:max_text] + "…"
        lines.append("Visible text: " + text)
        return "\n".join(lines)
