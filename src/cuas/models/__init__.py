from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class OutcomeKind(str, Enum):
    SUCCESS = "success"
    BUSINESS = "business_outcome"
    RECOVERED = "recovered"
    ESCALATED = "escalated"
    FAILURE = "failure"


class ActionType(str, Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    SELECT = "select"
    PRESS = "press"
    EXTRACT = "extract"
    DISMISS = "dismiss"
    WAIT = "wait"
    SCREENSHOT = "screenshot"
    DONE = "done"
    ESCALATE = "escalate"


class LocatorStrategy(str, Enum):
    """How to re-find a control on a later run.

    Ordered from most portable (accessibility / nearby human-visible text)
    to least (raw CSS). Replay tries them in list order.
    """

    ROLE_NAME = "role_name"
    ADJACENT_TEXT = "adjacent_text"
    PLACEHOLDER = "placeholder"
    TEXT = "text"
    CSS = "css"


class ControlOwner(str, Enum):
    AUTOMATION = "automation"
    HUMAN = "human"
    NONE = "none"


class RiskClass(str, Enum):
    READ = "read"
    REVERSIBLE = "reversible"
    IRREVERSIBLE = "irreversible"


class Locator(BaseModel):
    strategy: LocatorStrategy
    role: str | None = None
    name: str | None = None
    text: str | None = None
    placeholder: str | None = None
    css: str | None = None
    nth: int = 0
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    why: str = ""


class Target(BaseModel):
    """A control, identified by ranked locators, optionally inside a named frame."""

    locators: list[Locator] = Field(min_length=1)
    frame: str | None = None


class WaitSpec(BaseModel):
    until: Literal["visible", "hidden", "text", "url_contains", "timeout"] = "visible"
    text: str | None = None
    url_contains: str | None = None
    timeout_ms: int = 8000


class Checkpoint(BaseModel):
    id: str
    after_step: str | None = None
    description: str
    assert_kind: Literal["text_contains", "url_contains", "element_visible"] = "text_contains"
    text: str | None = None
    url_contains: str | None = None
    target: Target | None = None


class OutcomeDetector(BaseModel):
    code: str
    kind: Literal["business", "recoverable"]
    description: str
    match_text: str
    recover_action: Literal["none", "dismiss", "escalate"] = "none"


class ParameterSpec(BaseModel):
    name: str
    type: Literal["string", "number", "money", "enum"] = "string"
    required: bool = True
    description: str = ""
    pattern: str | None = None
    enum: list[str] | None = None
    example: str | None = None
    sensitive: bool = False


class OutputSpec(BaseModel):
    name: str
    type: Literal["string", "number", "money"] = "string"
    description: str = ""
    sensitive: bool = False


class StepInput(BaseModel):
    """Where a type/select value comes from at replay time."""

    from_parameter: str | None = None
    literal: str | None = None
    secret_env: str | None = None


class Step(BaseModel):
    id: str
    action: ActionType
    description: str = ""
    target: Target | None = None
    input: StepInput | None = None
    extract_as: str | None = None
    navigate_url: str | None = None
    key: str | None = None
    wait: WaitSpec = Field(default_factory=WaitSpec)
    risk: RiskClass = RiskClass.READ
    notes: str = ""


class AppBinding(BaseModel):
    vendor: str
    app_id: str
    surface: Literal["web", "desktop"] = "web"
    entry_url: str
    profile: str = ""


class TenantBinding(BaseModel):
    """Vendor-default artifacts apply to every tenant of this app.

    A tenant may attach locator/url overrides without re-recording the flow.
    """

    scope: Literal["vendor_default", "tenant"] = "vendor_default"
    tenant_id: str | None = None
    overrides: dict[str, Any] = Field(default_factory=dict)


class Capability(BaseModel):
    """A reviewable, agent-invocable, deterministically replayable flow.

    Decoupled from the raw model transcript. This is the production contract.
    """

    schema_version: str = "1.0.0"
    id: str
    name: str
    description: str
    version: int = 1
    status: Literal["draft", "approved"] = "draft"
    goal_template: str = ""
    app: AppBinding
    tenant: TenantBinding = Field(default_factory=TenantBinding)
    parameters: list[ParameterSpec] = Field(default_factory=list)
    outputs: list[OutputSpec] = Field(default_factory=list)
    risk: RiskClass = RiskClass.READ
    steps: list[Step]
    checkpoints: list[Checkpoint] = Field(default_factory=list)
    outcomes: list[OutcomeDetector] = Field(default_factory=list)
    recorded_from_goal: str | None = None
    recorded_at: str | None = None


class StepError(BaseModel):
    step_id: str
    expected: str
    observed: str
    locators_tried: list[Locator] = Field(default_factory=list)


class RunResult(BaseModel):
    kind: OutcomeKind
    capability_id: str | None = None
    goal: str | None = None
    outputs: dict[str, Any] = Field(default_factory=dict)
    business_code: str | None = None
    business_message: str | None = None
    error: StepError | None = None
    intervention_id: str | None = None
    evidence_dir: str | None = None
    steps_executed: int = 0
    llm_calls: int = 0

    @property
    def ok(self) -> bool:
        return self.kind in {OutcomeKind.SUCCESS, OutcomeKind.BUSINESS}


class InterventionRequest(BaseModel):
    id: str
    session_id: str
    reason: str
    capability_id: str | None = None
    goal: str | None = None
    step_id: str | None = None
    observation_summary: str = ""
    screenshot_path: str | None = None
    created_at: str
    status: Literal["open", "in_control", "resolved", "aborted"] = "open"
    human_actions: list[dict[str, Any]] = Field(default_factory=list)
    resolution: str | None = None
