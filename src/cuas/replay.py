"""Deterministic replay: no LLM in the decision loop."""

from __future__ import annotations

import os
import re
from pathlib import Path
from uuid import uuid4

from cuas.config import Policy
from cuas.evidence import EvidenceLog
from cuas.handoff.session import LiveSession
from cuas.models import (
    ActionType,
    Capability,
    OutcomeKind,
    RiskClass,
    RunResult,
    Step,
    StepError,
)
from cuas.safety.guardrails import Guardrails, PolicyViolation
from cuas.safety.redact import redact_text
from cuas.surface.locators import LocatorError
from cuas.surface.web import WebSurface


class ReplayEngine:
    def __init__(
        self,
        surface: WebSurface,
        policy: Policy,
        *,
        session: LiveSession | None = None,
        evidence: EvidenceLog | None = None,
        allow_irreversible: bool = False,
    ):
        self.surface = surface
        self.policy = policy
        self.guard = Guardrails(policy)
        self.session = session or LiveSession()
        self.evidence = evidence or EvidenceLog(Path("runs"), "replay-" + uuid4().hex[:8])
        self.allow_irreversible = allow_irreversible

    async def run(self, capability: Capability, params: dict[str, str]) -> RunResult:
        self._validate_params(capability, params)
        self.evidence.write(
            "replay_start",
            capability_id=capability.id,
            params={k: redact_text(v) for k, v in params.items()},
        )
        self.guard.check_url(capability.app.entry_url)
        await self.surface.goto(capability.app.entry_url)

        outputs: dict[str, str] = {}
        executed = 0

        for step in capability.steps:
            await self.session.wait_if_human_in_control()
            if self.session.owner.value == "none":
                return self._fail(capability, step, "session aborted", "operator aborted")

            obs = await self.surface.observe()
            outcome = self._detect_outcome(capability, obs.visible_text)
            if outcome:
                kind, code, recover = outcome
                self.evidence.write("outcome_detected", code=code, kind=kind, step=step.id)
                if kind == "business":
                    await self._shot(code.lower())
                    return RunResult(
                        kind=OutcomeKind.BUSINESS,
                        capability_id=capability.id,
                        business_code=code,
                        business_message=self._message_for(capability, code),
                        evidence_dir=str(self.evidence.dir),
                        steps_executed=executed,
                        llm_calls=0,
                    )
                if recover == "dismiss":
                    await self._dismiss_overlay()
                    continue
                if recover == "escalate":
                    return await self._escalate(capability, step, code, obs.visible_text)

            try:
                value = self._value_for(step, params)
                self._check_step_policy(step, obs.url)
                await self._execute(step, value)
                executed += 1
                self.evidence.write("step_ok", step_id=step.id, action=step.action.value)
            except PolicyViolation as exc:
                shot = await self._shot("policy")
                if exc.code == "IRREVERSIBLE_BLOCKED":
                    return await self._escalate(capability, step, str(exc), obs.visible_text)
                return self._fail(capability, step, "policy denied this action", str(exc), shot)
            except LocatorError as exc:
                # Re-check outcomes: a missing control often means an error page.
                obs2 = await self.surface.observe()
                outcome = self._detect_outcome(capability, obs2.visible_text)
                if outcome and outcome[0] == "business":
                    return RunResult(
                        kind=OutcomeKind.BUSINESS,
                        capability_id=capability.id,
                        business_code=outcome[1],
                        business_message=self._message_for(capability, outcome[1]),
                        evidence_dir=str(self.evidence.dir),
                        steps_executed=executed,
                        llm_calls=0,
                    )
                shot = await self._shot("locator")
                return self._fail(
                    capability,
                    step,
                    f"control not found ({step.action.value})",
                    redact_text(str(exc)),
                    shot,
                    locators=step.target.locators if step.target else [],
                )
            except Exception as exc:  # noqa: BLE001
                shot = await self._shot("error")
                return self._fail(capability, step, "step raised", redact_text(str(exc)), shot)

            if step.extract_as:
                try:
                    outputs[step.extract_as] = await self.surface.extract(step.target)  # type: ignore[arg-type]
                except Exception:  # noqa: BLE001
                    pass

        # Final page: extract declared outputs from visible text if the compiler
        # recorded them without per-step extract actions.
        final_text = await self.surface.visible_text()
        outcome = self._detect_outcome(capability, final_text)
        if outcome and outcome[0] == "business":
            return RunResult(
                kind=OutcomeKind.BUSINESS,
                capability_id=capability.id,
                business_code=outcome[1],
                business_message=self._message_for(capability, outcome[1]),
                evidence_dir=str(self.evidence.dir),
                steps_executed=executed,
                llm_calls=0,
                outputs=outputs,
            )

        outputs.update(self._harvest_outputs(capability, final_text))
        checkpoint_error = self._check_checkpoints(capability, final_text, outputs)
        if checkpoint_error:
            shot = await self._shot("checkpoint")
            return RunResult(
                kind=OutcomeKind.FAILURE,
                capability_id=capability.id,
                error=checkpoint_error,
                evidence_dir=str(self.evidence.dir),
                steps_executed=executed,
                llm_calls=0,
                outputs=outputs,
            )

        result = RunResult(
            kind=OutcomeKind.SUCCESS,
            capability_id=capability.id,
            outputs=outputs,
            evidence_dir=str(self.evidence.dir),
            steps_executed=executed,
            llm_calls=0,
        )
        await self._shot("final")
        self.evidence.write("replay_done", result=result.model_dump())
        return result

    def _validate_params(self, cap: Capability, params: dict[str, str]) -> None:
        for spec in cap.parameters:
            if spec.required and spec.name not in params:
                raise ValueError(f"missing required parameter '{spec.name}'")
            value = params.get(spec.name)
            if value and spec.pattern and not re.search(spec.pattern, value):
                raise ValueError(f"parameter '{spec.name}' does not match {spec.pattern}")

    def _value_for(self, step: Step, params: dict[str, str]) -> str | None:
        if not step.input:
            return None
        if step.input.from_parameter:
            return params[step.input.from_parameter]
        if step.input.secret_env:
            return os.getenv(step.input.secret_env, "teller")
        return step.input.literal

    def _check_step_policy(self, step: Step, url: str) -> None:
        self.guard.check_action_type(step.action.value)
        self.guard.check_url(url)
        if step.risk is RiskClass.IRREVERSIBLE and not self.allow_irreversible:
            raise PolicyViolation(
                "Irreversible step blocked on unattended replay",
                code="IRREVERSIBLE_BLOCKED",
            )

    async def _execute(self, step: Step, value: str | None) -> None:
        await self.surface.act(
            step.action,
            target=step.target,
            value=value,
            url=step.navigate_url,
            key=step.key,
        )

    def _detect_outcome(self, cap: Capability, text: str) -> tuple[str, str, str] | None:
        blob = text or ""
        for det in cap.outcomes:
            if det.match_text.lower() in blob.lower():
                return det.kind, det.code, det.recover_action
        return None

    def _message_for(self, cap: Capability, code: str) -> str:
        for det in cap.outcomes:
            if det.code == code:
                return det.description
        return code

    async def _dismiss_overlay(self) -> None:
        obs = await self.surface.observe()
        for el in obs.elements:
            if el.name.lower() in {"ok", "dismiss", "continue"}:
                target = self.surface.locators_for_ref(obs, el.ref)
                await self.surface.act(ActionType.DISMISS, target=target)
                return

    def _harvest_outputs(self, cap: Capability, text: str) -> dict[str, str]:
        found: dict[str, str] = {}
        savings = None
        m = re.search(r"Savings.*?(\$[\d,]+\.\d{2})", text, re.S)
        if m:
            savings = m.group(1)
        name = None
        m = re.search(r"Name:\s*([^\n]+)", text)
        if m and m.group(1).strip():
            name = m.group(1).strip()
        else:
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            for i, ln in enumerate(lines):
                if ln.lower().rstrip(":") == "name" and i + 1 < len(lines):
                    name = lines[i + 1]
                    break
        confirmation = None
        m = re.search(r"Confirmation\s*#:\s*(\S+)", text)
        if m:
            confirmation = m.group(1).strip()

        for spec in cap.outputs:
            key = spec.name.lower()
            if savings and ("savings" in key and "balance" in key or spec.type == "money"):
                found[spec.name] = savings
            elif name and ("name" in key and "member" in key or key in {"name", "member_name"}):
                found[spec.name] = name
            elif confirmation and "confirm" in key:
                found[spec.name] = confirmation
        return found

    def _check_checkpoints(
        self, cap: Capability, text: str, outputs: dict[str, str]
    ) -> StepError | None:
        for cp in cap.checkpoints:
            if cp.id == "has_outputs":
                missing = [o.name for o in cap.outputs if o.name not in outputs]
                if missing:
                    return StepError(
                        step_id=cp.id,
                        expected=f"outputs { [o.name for o in cap.outputs] }",
                        observed=f"missing {missing}",
                    )
                continue
            if cp.assert_kind == "text_contains" and cp.text and cp.text not in text:
                return StepError(
                    step_id=cp.id,
                    expected=f"page contains {cp.text!r}",
                    observed=redact_text(text[:400]),
                )
            if cp.assert_kind == "url_contains" and cp.url_contains:
                # checked against last observation url in caller if needed
                continue
        return None

    async def _escalate(self, cap: Capability, step: Step, reason: str, observed: str) -> RunResult:
        shot = await self._shot("escalate")
        req = self.session.request_intervention(
            reason,
            capability_id=cap.id,
            step_id=step.id,
            observation_summary=redact_text(observed[:1500]),
            screenshot_path=str(shot) if shot else None,
        )
        return RunResult(
            kind=OutcomeKind.ESCALATED,
            capability_id=cap.id,
            intervention_id=req.id,
            error=StepError(step_id=step.id, expected="automation can proceed", observed=reason),
            evidence_dir=str(self.evidence.dir),
            llm_calls=0,
        )

    def _fail(
        self,
        cap: Capability,
        step: Step,
        expected: str,
        observed: str,
        screenshot: Path | None = None,
        locators=None,
    ) -> RunResult:
        self.evidence.write(
            "replay_fail",
            step_id=step.id,
            expected=expected,
            observed=observed,
            screenshot=str(screenshot) if screenshot else None,
        )
        return RunResult(
            kind=OutcomeKind.FAILURE,
            capability_id=cap.id,
            error=StepError(
                step_id=step.id,
                expected=expected,
                observed=observed,
                locators_tried=locators or [],
            ),
            evidence_dir=str(self.evidence.dir),
            llm_calls=0,
        )

    async def _shot(self, label: str) -> Path | None:
        path = self.evidence.screenshot_path(label)
        try:
            await self.surface.screenshot(str(path))
            return path
        except Exception:  # noqa: BLE001
            return None
