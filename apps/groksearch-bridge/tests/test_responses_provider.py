from travelmind_groksearch_bridge.responses_provider import build_responses_payload, extract_responses_text


def test_build_responses_payload_translates_messages() -> None:
    payload = build_responses_payload(
        {
            "model": "Console/grok-4.20-multi-agent-0309",
            "messages": [
                {"role": "system", "content": "Search carefully."},
                {"role": "user", "content": "Shanghai attractions"},
            ],
            "stream": True,
        }
    )

    assert payload == {
        "model": "Console/grok-4.20-multi-agent-0309",
        "instructions": "Search carefully.",
        "input": [{"role": "user", "content": "Shanghai attractions"}],
        "stream": True,
    }


def test_extract_responses_text_supports_nested_output() -> None:
    assert extract_responses_text(
        {
            "output": [
                {"content": [{"type": "output_text", "text": "hello "}]},
                {"content": [{"type": "output_text", "text": "world"}]},
            ]
        }
    ) == "hello world"
