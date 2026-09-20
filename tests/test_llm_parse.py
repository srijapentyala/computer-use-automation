from cuas.agent.llm import _message_content, _normalize_action, parse_decision


def test_normalize_action_strips_junk():
    assert _normalize_action("click ref=e2 value=Sign On") == "click"
    assert _normalize_action("TYPE") == "type"
    assert _normalize_action("nope") == "escalate"


def test_parse_fenced_json():
    d = parse_decision("```json\n{\"action\":\"done\",\"thought\":\"ok\",\"outputs\":{\"a\":\"1\"}}\n```")
    assert d.action == "done"
    assert d.outputs["a"] == "1"


def test_sse_chunks_are_joined():
    raw = (
        'data: {"choices":[{"delta":{"content":"{\\"action\\":"}}]}\n'
        'data: {"choices":[{"delta":{"content":"\\"done\\"}"}}]}\n'
        "data: [DONE]\n"
    )
    assert _message_content(raw) == '{"action":"done"}'
