from cuas.agent.compiler import TraceStep, compile_capability
from cuas.models import ActionType, Locator, LocatorStrategy, RiskClass, Target


def _target(label: str) -> Target:
    return Target(
        locators=[
            Locator(
                strategy=LocatorStrategy.ADJACENT_TEXT,
                role="textbox",
                text=label,
                confidence=0.8,
                why="test",
            )
        ],
        frame="main",
    )


def test_compiler_parameterizes_member_id_and_redacts_password():
    trace = [
        TraceStep(
            ActionType.TYPE,
            target=_target("Operator ID"),
            value="teller",
            thought="Sign in as teller.",
            risk=RiskClass.REVERSIBLE,
        ),
        TraceStep(
            ActionType.TYPE,
            target=_target("Password"),
            value="teller",
            thought="Enter operator password.",
            risk=RiskClass.REVERSIBLE,
        ),
        TraceStep(
            ActionType.CLICK,
            target=_target("Go"),
            thought="Submit sign-on.",
        ),
        TraceStep(
            ActionType.TYPE,
            target=_target("Member ID"),
            value="12345",
            parameter="member_id",
            thought="Fill member ID from the goal.",
        ),
    ]
    cap = compile_capability(
        "look up member 12345 and read their current savings balance",
        trace,
        outputs={"savings_balance": "$2,450.00", "member_name": "Jane A. Doe"},
        entry_url="http://127.0.0.1:8787/",
    )
    assert cap.id == "heritage_core.lookup_savings_balance"
    names = {p.name for p in cap.parameters}
    assert names == {"member_id"}
    secrets = [s.input.secret_env for s in cap.steps if s.input and s.input.secret_env]
    assert "COREBANK_PASSWORD" in secrets
    assert "COREBANK_USER" in secrets
    dumped = cap.model_dump_json()
    assert "teller" not in dumped or cap.steps[0].input.secret_env == "COREBANK_USER"
    assert any(o.code == "MEMBER_NOT_FOUND" for o in cap.outcomes)
    assert cap.schema_version == "1.0.0"
