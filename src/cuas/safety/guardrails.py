from __future__ import annotations

from urllib.parse import urlparse

from cuas.config import Policy
from cuas.models import ActionType, RiskClass
from cuas.models.observation import InteractiveElement, Observation


class PolicyViolation(Exception):
    def __init__(self, message: str, *, code: str = "POLICY"):
        super().__init__(message)
        self.code = code


class Guardrails:
    def __init__(self, policy: Policy):
        self.policy = policy

    def check_url(self, url: str) -> None:
        if not self.policy.url_allowed(url):
            raise PolicyViolation(
                f"URL is outside the allowlist: {url}",
                code="URL_NOT_ALLOWED",
            )

    def check_action_type(self, action: str) -> None:
        if not self.policy.action_allowed(action):
            raise PolicyViolation(
                f"Action type '{action}' is not permitted by policy",
                code="ACTION_NOT_ALLOWED",
            )

    def risk_for(
        self,
        action: str,
        *,
        element: InteractiveElement | None = None,
        url: str = "",
        name: str = "",
    ) -> RiskClass:
        label = name or (element.name if element else "") or (element.adjacent_text if element else "")
        target_url = url or (element.css if element else "")
        if action in {ActionType.EXTRACT.value, ActionType.WAIT.value, ActionType.SCREENSHOT.value}:
            return RiskClass.READ
        if self.policy.is_irreversible(name=label, url=target_url) or (element and element.risky):
            return RiskClass.IRREVERSIBLE
        if action in {ActionType.TYPE.value, ActionType.CLICK.value, ActionType.SELECT.value}:
            return RiskClass.REVERSIBLE
        return RiskClass.READ

    def check_decision(
        self,
        action: str,
        observation: Observation,
        *,
        element: InteractiveElement | None = None,
        navigate_url: str | None = None,
        allow_irreversible: bool = False,
    ) -> RiskClass:
        self.check_action_type(action)
        self.check_url(observation.url)
        if navigate_url:
            self.check_url(navigate_url)
            host = urlparse(navigate_url).netloc
            if not self.policy.host_allowed(host):
                raise PolicyViolation(
                    f"Navigation host is not allowlisted: {host}",
                    code="HOST_NOT_ALLOWED",
                )
        risk = self.risk_for(action, element=element, url=observation.url)
        if risk is RiskClass.IRREVERSIBLE and not allow_irreversible:
            raise PolicyViolation(
                "Irreversible action requires a human decision (policy on_match=escalate)",
                code="IRREVERSIBLE_BLOCKED",
            )
        return risk
