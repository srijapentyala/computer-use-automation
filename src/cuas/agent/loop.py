"""Observe → decide → act discovery loop."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from cuas.agent.compiler import TraceStep, compile_capability
from cuas.agent.llm import LLM, Decision
from cuas.config import Policy
from cuas.evidence import EvidenceLog
from cuas.handoff.session import LiveSession
from cuas.models import ActionType, Capability, OutcomeKind, RiskClass, RunResult
from cuas.models.observation import Observation
from cuas.safety.guardrails import Guardrails, PolicyViolation
from cuas.safety.redact import redact_text
from cuas.surface.web import WebSurface


class DiscoveryRunner:
    def __init__(
        self,
        surface: WebSurface,
        llm: LLM,
        policy: Policy,
        *,
        session: LiveSession | None = None,
        evidence: EvidenceLog | None = None,
        start_url: str,
    ):
        self.surface = surface
        self.llm = llm
        self.policy = policy
        self.guard = Guardrails(policy)
        self.session = session or LiveSession()
        self.evidence = evidence or EvidenceLog(Path("runs"), uuid4().hex[:8])
        self.start_url = start_url
        self.trace: list[TraceStep] = []
        self.history: list[str] = []
        self.fingerprints: list[str] = []

    async def run(self, goal: str) -> tuple[RunResult, Capability | None]:
        self.evidence.write("discovery_start", goal=goal, url=self.start_url)
        self.guard.check_url(self.start_url)
        await self.surface.goto(self.start_url)

        for i in range(self.policy.max_steps):
            await self.session.wait_if_human_in_control()
            if self.session.owner.value == "none":
                return (
                    RunResult(
                        kind=OutcomeKind.FAILURE,
                        goal=goal,
                        evidence_dir=str(self.evidence.dir),
                        steps_executed=len(self.trace),
                        llm_calls=getattr(self.llm, "calls", 0),
                    ),
                    None,
                )

            obs = await self.surface.observe()
            self.evidence.write(
                "observe",
                url=obs.url,
                fingerprint=obs.fingerprint,
                n_elements=len(obs.elements),
                errors=obs.errors,
            )
            if self._is_loop(obs):
                return await self._escalate(
                    goal, obs, f"observation repeated {self.policy.loop_repeat_limit} times"
                )

            try:
                decision = await self.llm.decide(goal, obs, self.history)
            except Exception as exc:  # noqa: BLE001
                self.evidence.write("llm_error", error=str(exc))
                return await self._escalate(goal, obs, f"LLM error: {exc}")

            hidden = "pass" in (decision.thought or "").lower()
            if decision.ref:
                try:
                    adj = obs.element(decision.ref).adjacent_text.lower()
                    hidden = hidden or "password" in adj
                except KeyError:
                    pass
            shown_value = "[REDACTED]" if hidden else redact_text(decision.value or "")
            self.history.append(
                f"{decision.action} ref={decision.ref} value={shown_value} "
                f"// {redact_text(decision.thought)}"
            )
            self.evidence.write(
                "decide",
                thought=decision.thought,
                action=decision.action,
                ref=decision.ref,
                parameter=decision.parameter,
                business_code=decision.business_code,
            )

            if decision.action == ActionType.DONE.value:
                await self.surface.screenshot(str(self.evidence.screenshot_path("final")))
                return self._finish(goal, decision)

            if decision.action == ActionType.ESCALATE.value:
                return await self._escalate(goal, obs, decision.reason or decision.thought)

            try:
                await self._apply(decision, obs)
            except PolicyViolation as exc:
                self.evidence.write("policy_block", code=exc.code, message=str(exc))
                if exc.code == "IRREVERSIBLE_BLOCKED":
                    return await self._escalate(goal, obs, str(exc))
                return (
                    RunResult(
                        kind=OutcomeKind.FAILURE,
                        goal=goal,
                        error=None,
                        evidence_dir=str(self.evidence.dir),
                        steps_executed=len(self.trace),
                        llm_calls=getattr(self.llm, "calls", 0),
                    ),
                    None,
                )
            except Exception as exc:  # noqa: BLE001
                shot = self.evidence.screenshot_path("act_error")
                await self.surface.screenshot(str(shot))
                self.evidence.write("act_error", error=str(exc), screenshot=str(shot))
                return await self._escalate(goal, obs, f"act failed: {exc}")

        return await self._escalate(goal, await self.surface.observe(), "max steps exceeded")

    def _is_loop(self, obs: Observation) -> bool:
        """Stuck = same screen AND the same action, several times in a row.

        Filling a form does not change much of the a11y tree; that is progress,
        not a loop. We only trip this when the agent is repeating itself.
        """
        self.fingerprints.append(obs.fingerprint)
        n = self.policy.loop_repeat_limit
        if len(self.history) < n:
            return False
        tail_fp = self.fingerprints[-n:]
        tail_act = [h.split()[0] for h in self.history[-n:]]
        return len(set(tail_fp)) == 1 and len(set(tail_act)) == 1

    async def _apply(self, decision: Decision, obs: Observation) -> None:
        action = ActionType(decision.action)
        element = obs.element(decision.ref) if decision.ref else None
        target = self.surface.locators_for_ref(obs, decision.ref) if decision.ref else None
        risk = self.guard.check_decision(
            action.value,
            obs,
            element=element,
            navigate_url=None,
            allow_irreversible=False,
        )
        await self.surface.act(action, target=target, value=decision.value, key=decision.key)
        self.trace.append(
            TraceStep(
                action,
                target=target,
                value=decision.value,
                parameter=decision.parameter,
                extract_as=decision.extract_as,
                thought=decision.thought,
                risk=risk,
            )
        )

    def _finish(self, goal: str, decision: Decision) -> tuple[RunResult, Capability | None]:
        cap = compile_capability(
            goal,
            self.trace,
            outputs=decision.outputs,
            entry_url=self.start_url,
            business_code=decision.business_code,
        )
        kind = OutcomeKind.BUSINESS if decision.business_code else OutcomeKind.SUCCESS
        result = RunResult(
            kind=kind,
            capability_id=cap.id,
            goal=goal,
            outputs=decision.outputs,
            business_code=decision.business_code,
            evidence_dir=str(self.evidence.dir),
            steps_executed=len(self.trace),
            llm_calls=getattr(self.llm, "calls", 0),
        )
        self.evidence.write("discovery_done", result=result.model_dump())
        return result, cap

    async def _escalate(
        self, goal: str, obs: Observation, reason: str
    ) -> tuple[RunResult, Capability | None]:
        shot = self.evidence.screenshot_path("stuck")
        try:
            await self.surface.screenshot(str(shot))
        except Exception:  # noqa: BLE001
            shot = None
        req = self.session.request_intervention(
            reason,
            goal=goal,
            step_id=f"s{len(self.trace)}",
            observation_summary=obs.summary(),
            screenshot_path=str(shot) if shot else None,
        )
        self.evidence.write("escalated", reason=reason, intervention_id=req.id)
        return (
            RunResult(
                kind=OutcomeKind.ESCALATED,
                goal=goal,
                intervention_id=req.id,
                evidence_dir=str(self.evidence.dir),
                steps_executed=len(self.trace),
                llm_calls=getattr(self.llm, "calls", 0),
            ),
            None,
        )

