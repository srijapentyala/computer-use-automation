from cuas.agent.llm import _el_by_name, heuristic_decision
from cuas.models.observation import InteractiveElement, Observation


def _obs(elements, text=""):
    return Observation(
        url="http://127.0.0.1:8787/",
        visible_text=text,
        elements=elements,
        fingerprint="x",
    )


def test_go_does_not_match_logout():
    obs = _obs(
        [
            InteractiveElement(ref="e0", role="link", name="Logout", frame="nav"),
            InteractiveElement(ref="e7", role="button", name="Go", value="Go", frame="main"),
            InteractiveElement(ref="e4", role="textbox", adjacent_text="Member ID:", value="12345", frame="main"),
        ],
        text="Member Inquiry Member ID: Lookup",
    )
    assert _el_by_name(obs, "go").ref == "e7"
    decision = heuristic_decision(
        "look up member 12345 and read their current savings balance", obs, []
    )
    assert decision.action == "click"
    assert decision.ref == "e7"


def test_view_record_wins_over_go_when_results_visible():
    obs = _obs(
        [
            InteractiveElement(ref="e4", role="textbox", adjacent_text="Member ID:", value="12345", frame="main"),
            InteractiveElement(ref="e7", role="button", name="Go", value="Go", frame="main"),
            InteractiveElement(ref="e8", role="link", name="View Record", frame="main"),
        ],
        text="1 matching record. View Record",
    )
    decision = heuristic_decision(
        "look up member 12345 and read their current savings balance", obs, []
    )
    assert decision.ref == "e8"
