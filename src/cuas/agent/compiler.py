"""Compile a successful discovery trace into a versioned Capability artifact."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from cuas.models import (
    ActionType,
    AppBinding,
    Capability,
    Checkpoint,
    OutcomeDetector,
    OutputSpec,
    ParameterSpec,
    RiskClass,
    Step,
    StepInput,
    Target,
    WaitSpec,
)
from cuas.safety.redact import redact_text

KNOWN_OUTCOMES = [
    OutcomeDetector(
        code="MEMBER_NOT_FOUND",
        kind="business",
        description="No member record matches the supplied member ID.",
        match_text="No matching member found",
    ),
    OutcomeDetector(
        code="MEMBER_CLOSED",
        kind="business",
        description="Membership exists but is closed; inquiry only.",
        match_text="Membership is closed",
    ),
    OutcomeDetector(
        code="VALIDATION_ERROR",
        kind="business",
        description="Form failed field validation.",
        match_text="Please correct the highlighted fields",
    ),
    OutcomeDetector(
        code="INSUFFICIENT_FUNDS",
        kind="business",
        description="Transfer amount exceeds available balance.",
        match_text="Insufficient funds",
    ),
    OutcomeDetector(
        code="SESSION_EXPIRED",
        kind="recoverable",
        description="Teller session timed out.",
        match_text="Your session has expired",
        recover_action="escalate",
    ),
    OutcomeDetector(
        code="BATCH_INTERSTITIAL",
        kind="recoverable",
        description="Nightly core-processing overlay.",
        match_text="Core processing window in progress",
        recover_action="dismiss",
    ),
]


class TraceStep:
    def __init__(
        self,
        action: ActionType,
        *,
        target: Target | None = None,
        value: str | None = None,
        parameter: str | None = None,
        extract_as: str | None = None,
        url: str | None = None,
        thought: str = "",
        risk: RiskClass = RiskClass.READ,
    ):
        self.action = action
        self.target = target
        self.value = value
        self.parameter = parameter
        self.extract_as = extract_as
        self.url = url
        self.thought = thought
        self.risk = risk


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text[:48] or "capability"


def compile_capability(
    goal: str,
    trace: list[TraceStep],
    *,
    outputs: dict[str, Any] | None = None,
    entry_url: str,
    business_code: str | None = None,
) -> Capability:
    steps: list[Step] = []
    params: dict[str, ParameterSpec] = {}
    output_specs: list[OutputSpec] = []
    max_risk = RiskClass.READ

    for i, event in enumerate(trace):
        if event.action in {ActionType.DONE, ActionType.ESCALATE}:
            continue
        sid = f"s{i+1}_{event.action.value}"
        inp = None
        if event.action is ActionType.TYPE:
            thought = (event.thought or "").lower()
            label = ""
            if event.target and event.target.locators:
                loc0 = event.target.locators[0]
                label = (loc0.text or loc0.name or "").lower()
            if "pass" in thought or "pass" in label:
                inp = StepInput(secret_env="COREBANK_PASSWORD")
            elif "operator" in thought or "sign in" in thought or "operator" in label:
                inp = StepInput(secret_env="COREBANK_USER")
            else:
                name = event.parameter or _infer_param(goal, event.value or "")
                if name:
                    params[name] = ParameterSpec(
                        name=name,
                        type="string",
                        description=(
                            "Caller-supplied member identifier."
                            if name == "member_id"
                            else "Caller-supplied input captured during discovery."
                        ),
                        example=event.value,
                        pattern=r"^[0-9]{4,8}$" if name == "member_id" else None,
                    )
                    inp = StepInput(from_parameter=name)
                else:
                    inp = StepInput(literal=event.value)
        if event.risk is RiskClass.IRREVERSIBLE:
            max_risk = RiskClass.IRREVERSIBLE
        elif event.risk is RiskClass.REVERSIBLE and max_risk is RiskClass.READ:
            max_risk = RiskClass.REVERSIBLE
        steps.append(
            Step(
                id=sid,
                action=event.action,
                description=redact_text(event.thought) or event.action.value,
                target=event.target,
                input=inp,
                extract_as=event.extract_as,
                navigate_url=event.url if event.action is ActionType.NAVIGATE else None,
                risk=event.risk,
            )
        )

    for name, value in (outputs or {}).items():
        output_specs.append(
            OutputSpec(
                name=name,
                type="money" if str(value).startswith("$") else "string",
                description=f"Extracted during discovery (example redacted in logs).",
            )
        )

    checkpoints: list[Checkpoint] = []
    if outputs:
        checkpoints.append(
            Checkpoint(
                id="has_outputs",
                description="Replay produced the declared outputs or a known business outcome.",
                assert_kind="text_contains",
                text="",
            )
        )
        out_names = {n.lower() for n in (outputs or {})}
        moneyish = any(str(v).startswith("$") for v in (outputs or {}).values())
        if moneyish or any(
            "balance" in n or "member_name" in n or n == "name" for n in out_names
        ):
            checkpoints.append(
                Checkpoint(
                    id="on_member_record",
                    description="Member record screen is showing.",
                    assert_kind="text_contains",
                    text="Member Record",
                )
            )
        if any("confirm" in n for n in out_names):
            checkpoints.append(
                Checkpoint(
                    id="on_confirmation",
                    description="Confirmation screen is showing.",
                    assert_kind="text_contains",
                    text="New Account Confirmation",
                )
            )

    if "balance" in goal.lower() and steps:
        last_click = next((s for s in reversed(steps) if s.action is ActionType.CLICK), None)
        if last_click:
            last_click.wait = WaitSpec(until="text", text="Member Record", timeout_ms=8000)
        go = next(
            (
                s
                for s in steps
                if s.action is ActionType.CLICK
                and s.target
                and any((loc.name or "").lower() == "go" for loc in s.target.locators)
            ),
            None,
        )
        if go:
            go.wait = WaitSpec(until="text", text="matching", timeout_ms=8000)

    cap_id = "heritage_core." + slugify(goal if "member" in goal.lower() else "flow")
    if "balance" in goal.lower():
        cap_id = "heritage_core.lookup_savings_balance"
        name = "Look up member savings balance"
    elif "sub-account" in goal.lower() or "sub account" in goal.lower():
        cap_id = "heritage_core.open_subaccount"
        name = "Open a new sub-account"
    else:
        name = goal[:80]

    return Capability(
        id=cap_id,
        name=name,
        description=(
            f"Recorded flow for: {goal}. Replay substitutes parameters, uses ranked "
            "locators (no LLM), and maps known UI texts to business outcomes."
        ),
        goal_template=re.sub(r"\b\d{4,8}\b", "{member_id}", goal),
        app=AppBinding(
            vendor="heritage",
            app_id="heritage_core",
            surface="web",
            entry_url=entry_url,
            profile="heritage_core",
        ),
        parameters=list(params.values()),
        outputs=output_specs,
        risk=max_risk,
        steps=steps,
        checkpoints=[c for c in checkpoints if c.text or c.id == "has_outputs"],
        outcomes=list(KNOWN_OUTCOMES),
        recorded_from_goal=goal,
        recorded_at=datetime.now(timezone.utc).isoformat(),
        status="approved",
    )


def _infer_param(goal: str, value: str) -> str | None:
    if not value:
        return None
    if re.fullmatch(r"\d{4,8}", value) and value in goal:
        return "member_id"
    if re.fullmatch(r"\d+(?:\.\d{2})?", value) and value in goal:
        return "opening_deposit"
    return None
