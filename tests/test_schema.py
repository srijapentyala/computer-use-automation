from cuas.models import Capability, OutcomeKind, RunResult


def test_capability_round_trip_schema():
    raw = {
        "id": "heritage_core.lookup_savings_balance",
        "name": "Look up member savings balance",
        "description": "demo",
        "app": {
            "vendor": "heritage",
            "app_id": "heritage_core",
            "entry_url": "http://127.0.0.1:8787/",
        },
        "parameters": [{"name": "member_id", "type": "string"}],
        "outputs": [{"name": "savings_balance", "type": "money"}],
        "steps": [
            {
                "id": "s1",
                "action": "click",
                "target": {
                    "locators": [
                        {
                            "strategy": "role_name",
                            "role": "link",
                            "name": "Member Search",
                            "why": "nav label",
                        }
                    ],
                    "frame": "nav",
                },
            }
        ],
        "outcomes": [
            {
                "code": "MEMBER_NOT_FOUND",
                "kind": "business",
                "description": "missing",
                "match_text": "No matching member found",
            }
        ],
    }
    cap = Capability.model_validate(raw)
    again = Capability.model_validate_json(cap.model_dump_json())
    assert again.id == cap.id
    assert again.steps[0].target.frame == "nav"


def test_business_outcome_is_ok_for_caller():
    result = RunResult(
        kind=OutcomeKind.BUSINESS,
        business_code="MEMBER_NOT_FOUND",
        capability_id="heritage_core.lookup_savings_balance",
    )
    assert result.ok
    assert result.kind is not OutcomeKind.FAILURE
