"""Lenient Studio output protocol through its public parser interface."""
from __future__ import annotations

from aps.services.prompt_protocol import parse_lenient_output


def test_complete_tagged_prompt_and_summary_are_accepted() -> None:
    result = parse_lenient_output(
        "<PROMPT>\nA woman walks through blue-hour rain.\n</PROMPT>\n"
        "<SUMMARY>Changed the lighting.</SUMMARY>")
    assert result.kind == "tagged_prompt"
    assert result.prompt == "A woman walks through blue-hour rain."
    assert result.summary == "Changed the lighting."
    assert result.warnings == []


def test_untagged_natural_prompt_is_accepted_with_visible_warning() -> None:
    result = parse_lenient_output(
        "A cinematic close-up of Alice beneath warm station lights.")
    assert result.kind == "plain_prompt"
    assert result.prompt.startswith("A cinematic close-up")
    assert result.warnings == ["模型未遵循标签协议，已按普通提示词接收"]


def test_partial_json_and_partial_tags_are_never_promoted_to_prompt() -> None:
    partial_json = parse_lenient_output(
        '{"prompt":"A woman in rain", "summary":')
    partial_tag = parse_lenient_output("<PROMPT>\nA woman in rain")
    assert partial_json.kind == "protocol_garbage"
    assert partial_json.prompt == ""
    assert partial_tag.kind == "protocol_garbage"
    assert partial_tag.prompt == ""


def test_fenced_tagged_output_and_surrounding_explanation_are_cleaned() -> None:
    result = parse_lenient_output(
        "Here is the requested result:\n```text\n<PROMPT>rainy Tokyo street</PROMPT>\n"
        "<SUMMARY>created</SUMMARY>\n```\n")
    assert result.kind == "tagged_prompt"
    assert result.prompt == "rainy Tokyo street"
    assert result.summary == "created"


def test_schema_explanation_is_protocol_garbage_not_plain_prompt() -> None:
    result = parse_lenient_output(
        "The JSON should contain prompt and summary fields. Please provide valid JSON.")
    assert result.kind == "protocol_garbage"
    assert "协议" in result.issues[0]
