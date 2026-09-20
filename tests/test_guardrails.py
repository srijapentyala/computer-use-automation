from pathlib import Path

from cuas.config import Policy
from cuas.models.observation import InteractiveElement, Observation
from cuas.safety.guardrails import Guardrails, PolicyViolation

POLICY = Policy.load(Path(__file__).resolve().parents[1] / "policies" / "default.yaml")


def _obs(url="http://127.0.0.1:8787/search"):
    return Observation(url=url, title="x", fingerprint="1")


def test_allowlisted_url_ok():
    Guardrails(POLICY).check_url("http://127.0.0.1:8787/search")


def test_blocks_foreign_host():
    try:
        Guardrails(POLICY).check_url("https://evil.example/steal")
        assert False, "expected PolicyViolation"
    except PolicyViolation as exc:
        assert exc.code == "URL_NOT_ALLOWED"


def test_blocks_eval_js():
    try:
        Guardrails(POLICY).check_action_type("eval_js")
        assert False
    except PolicyViolation:
        pass


def test_irreversible_transfer_is_flagged():
    el = InteractiveElement(ref="e0", role="button", name="Submit Transfer", risky=True)
    obs = _obs("http://127.0.0.1:8787/transfer")
    try:
        Guardrails(POLICY).check_decision("click", obs, element=el)
        assert False
    except PolicyViolation as exc:
        assert exc.code == "IRREVERSIBLE_BLOCKED"
