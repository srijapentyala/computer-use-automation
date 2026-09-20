from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from cuas.agent.prompts import SYSTEM_PROMPT, user_prompt
from cuas.config import Settings
from cuas.models.observation import Observation


@dataclass
class Decision:
    thought: str
    action: str
    ref: str | None = None
    value: str | None = None
    parameter: str | None = None
    key: str | None = None
    extract_as: str | None = None
    business_code: str | None = None
    outputs: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def _message_content(resp: Any) -> str:
    """TAMUS AI Chat sometimes returns SSE text even when stream=false."""
    if hasattr(resp, "choices") and resp.choices:
        msg = resp.choices[0].message
        return (getattr(msg, "content", None) or "") or "{}"
    if isinstance(resp, str):
        parts: list[str] = []
        for line in resp.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                continue
            choices = obj.get("choices") or []
            if not choices:
                continue
            ch = choices[0]
            msg = ch.get("message") or {}
            if msg.get("content"):
                parts.append(str(msg["content"]))
            delta = ch.get("delta") or {}
            if delta.get("content"):
                parts.append(str(delta["content"]))
        return "".join(parts) or "{}"
    return "{}"


def parse_decision(payload: str | dict[str, Any]) -> Decision:
    if isinstance(payload, dict):
        data = payload
    else:
        data = json.loads(_extract_json(payload))
    if "action" not in data and "type" in data:
        data["action"] = data["type"]
    data["action"] = _normalize_action(str(data.get("action") or "escalate"))
    return Decision(
        thought=str(data.get("thought") or ""),
        action=str(data.get("action") or "escalate"),
        ref=data.get("ref"),
        value=data.get("value"),
        parameter=data.get("parameter"),
        key=data.get("key"),
        extract_as=data.get("extract_as"),
        business_code=data.get("business_code"),
        outputs=data.get("outputs") or {},
        reason=data.get("reason"),
        raw=data,
    )


_VALID_ACTIONS = {
    "click",
    "type",
    "select",
    "press",
    "extract",
    "dismiss",
    "done",
    "escalate",
    "wait",
    "navigate",
    "screenshot",
}


def _normalize_action(action: str) -> str:
    raw = (action or "").strip().lower()
    if raw in _VALID_ACTIONS:
        return raw
    for name in _VALID_ACTIONS:
        if raw.startswith(name):
            return name
    return "escalate"


def _extract_json(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


class LLM(Protocol):
    async def decide(
        self, goal: str, observation: Observation, history: list[str]
    ) -> Decision: ...


class OpenAILLM:
    def __init__(self, settings: Settings | None = None):
        from openai import AsyncOpenAI

        settings = settings or Settings()
        kwargs: dict[str, Any] = {"api_key": settings.openai_api_key or os.getenv("OPENAI_API_KEY")}
        if settings.openai_base_url:
            kwargs["base_url"] = settings.openai_base_url
        self.client = AsyncOpenAI(**kwargs)
        self.model = settings.openai_model
        self.calls = 0

    async def decide(self, goal: str, observation: Observation, history: list[str]) -> Decision:
        self.calls += 1
        kwargs: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "stream": False,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": user_prompt(goal, observation.summary(), history),
                },
            ],
        }
        # Gemini/TAMUS and local servers often reject OpenAI json_object mode.
        if self._json_object_mode:
            kwargs["response_format"] = {"type": "json_object"}
        last_error: Exception | None = None
        for _ in range(2):
            try:
                response = await self.client.chat.completions.create(**kwargs)
                content = _message_content(response)
                return parse_decision(content)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue
        raise last_error or RuntimeError("LLM decide failed")

    @property
    def _json_object_mode(self) -> bool:
        host = str(getattr(self.client, "base_url", "") or "")
        if not host or "api.openai.com" in host:
            return True
        return False


class AnthropicLLM:
    def __init__(self, settings: Settings | None = None):
        import anthropic

        settings = settings or Settings()
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.model = settings.anthropic_model
        self.calls = 0

    async def decide(self, goal: str, observation: Observation, history: list[str]) -> Decision:
        self.calls += 1
        msg = await self.client.messages.create(
            model=self.model,
            max_tokens=800,
            temperature=0,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": user_prompt(goal, observation.summary(), history),
                }
            ],
        )
        text = "".join(getattr(b, "text", "") for b in msg.content)
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
        return parse_decision(text)


class ScriptedLLM:
    """Deterministic stand-in for tests and offline demos.

    It is not a model: it pattern-matches the observation. Production discovery
    must use OpenAI or Anthropic. Kept so replay, handoff, and CI stay runnable
    without a paid API key.
    """

    def __init__(self, script: list[Decision] | None = None):
        self.script = list(script or [])
        self.calls = 0

    async def decide(self, goal: str, observation: Observation, history: list[str]) -> Decision:
        self.calls += 1
        if self.script:
            return self.script.pop(0)
        return heuristic_decision(goal, observation, history)


def _el_by_adjacent(obs: Observation, needle: str):
    needle = needle.lower().rstrip(":")
    for el in obs.elements:
        if needle in (el.adjacent_text or "").lower().rstrip(":"):
            return el
    return None


def _el_by_name(obs: Observation, needle: str):
    needle = needle.lower().strip()
    for el in obs.elements:
        name = (el.name or "").lower().strip()
        val = (el.value or "").lower().strip()
        if name == needle or val == needle:
            return el
    return None


def heuristic_decision(goal: str, obs: Observation, history: list[str] | None = None) -> Decision:
    text = (obs.visible_text or "").lower()
    goal_l = goal.lower()

    if "no matching member found" in text:
        return Decision(
            thought="Search returned no member.",
            action="done",
            business_code="MEMBER_NOT_FOUND",
        )
    if "membership is closed" in text and "view record" not in text:
        return Decision(
            thought="Closed membership is a business outcome.",
            action="done",
            business_code="MEMBER_CLOSED",
        )
    if "your session has expired" in text:
        return Decision(thought="Session expired.", action="escalate", reason="SESSION_EXPIRED")
    if "core processing window" in text:
        ok = _el_by_name(obs, "ok")
        return Decision(thought="Dismiss nightly batch overlay.", action="dismiss", ref=ok.ref if ok else None)

    if "sign on" in text and _el_by_adjacent(obs, "operator id"):
        if not _el_by_adjacent(obs, "operator id").value:
            return Decision(
                thought="Sign in as teller.",
                action="type",
                ref=_el_by_adjacent(obs, "operator id").ref,
                value="teller",
            )
        pwd = _el_by_adjacent(obs, "password")
        # Password inputs never echo a value. Look only at recent history so a
        # later re-login (after logout) still types the password again.
        recent = "\n".join((history or [])[-3:]).lower()
        if pwd and "enter operator password" not in recent:
            return Decision(
                thought="Enter operator password.",
                action="type",
                ref=pwd.ref,
                value="teller",
                parameter=None,
            )
        submit = _el_by_name(obs, "sign on")
        return Decision(thought="Submit sign-on.", action="click", ref=submit.ref if submit else None)

    view = _el_by_name(obs, "view record")
    if view:
        return Decision(thought="Open the member record.", action="click", ref=view.ref)

    if "member id" in text and _el_by_adjacent(obs, "member id"):
        field = _el_by_adjacent(obs, "member id")
        if not field.value:
            member_id = _member_id_from_goal(goal) or "12345"
            return Decision(
                thought="Fill member ID from the goal.",
                action="type",
                ref=field.ref,
                value=member_id,
                parameter="member_id",
            )
        go = _el_by_name(obs, "go")
        if go:
            return Decision(thought="Submit member lookup.", action="click", ref=go.ref)

    search = _el_by_name(obs, "member search")
    if search and "member record" not in text and "lookup" not in text:
        return Decision(thought="Go to member search.", action="click", ref=search.ref)

    if "open sub-account" in goal_l or "open a new sub-account" in goal_l:
        if "new account confirmation" in text:
            conf = _extract_after(obs.visible_text, "Confirmation #:")
            return Decision(
                thought="Reached confirmation.",
                action="done",
                outputs={"confirmation_number": conf or "unknown"},
            )
        if "opening a product" in text or "new share" in text:
            dep = _el_by_adjacent(obs, "opening deposit")
            if dep and not dep.value:
                return Decision(
                    thought="Fill opening deposit.",
                    action="type",
                    ref=dep.ref,
                    value=_amount_from_goal(goal) or "25",
                    parameter="opening_deposit",
                )
            submit = _el_by_name(obs, "submit application")
            if submit:
                return Decision(thought="Submit the application.", action="click", ref=submit.ref)
        open_link = _el_by_name(obs, "open sub-account")
        if open_link and "new share" not in text:
            return Decision(thought="Open the sub-account function.", action="click", ref=open_link.ref)

    if "member record" in text or "share / draft" in text:
        savings = _balance_for_product(obs.visible_text, "Savings")
        name = _extract_after(obs.visible_text, "Name:")
        outputs = {}
        if savings:
            outputs["savings_balance"] = savings
        if name:
            outputs["member_name"] = name.strip()
        if outputs:
            return Decision(thought="Extract requested fields from the record.", action="done", outputs=outputs)

    return Decision(
        thought="No grounded next step.",
        action="escalate",
        reason="STUCK_NO_HEURISTIC",
    )


def _member_id_from_goal(goal: str) -> str | None:
    import re

    m = re.search(r"\b(\d{4,8})\b", goal)
    return m.group(1) if m else None


def _amount_from_goal(goal: str) -> str | None:
    import re

    m = re.search(r"\$?\s*(\d+(?:\.\d{2})?)", goal)
    return m.group(1) if m else None


def _extract_after(text: str, label: str) -> str | None:
    for line in text.splitlines():
        if label.lower() in line.lower():
            return line.split(":", 1)[-1].strip()
    # table cells may sit on adjacent lines
    lines = [ln.strip() for ln in text.splitlines()]
    for i, ln in enumerate(lines):
        if ln.lower().rstrip(":") == label.lower().rstrip(":"):
            if i + 1 < len(lines):
                return lines[i + 1]
    return None


def _balance_for_product(text: str, product: str) -> str | None:
    import re

    m = re.search(rf"{product}\s+(SV|CK|MM)-[0-9]+\s+(\$[\d,]+\.\d{{2}})", text)
    if m:
        return m.group(2)
    # looser: product line then a money amount nearby
    m = re.search(rf"{product}.*?(\$[\d,]+\.\d{{2}})", text, re.S)
    return m.group(1) if m else None


def build_llm(kind: str, settings: Settings | None = None) -> LLM:
    kind = kind.lower()
    settings = settings or Settings()
    if kind in {"scripted", "heuristic", "offline"}:
        return ScriptedLLM()
    if kind == "anthropic":
        return AnthropicLLM(settings)
    if kind == "ollama":
        local = settings.model_copy(update={
            "openai_base_url": "http://127.0.0.1:11434/v1",
            "openai_api_key": "ollama",
            "openai_model": os.getenv("OLLAMA_MODEL") or settings.ollama_model,
        })
        return OpenAILLM(local)
    return OpenAILLM(settings)
