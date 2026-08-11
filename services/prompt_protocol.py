"""Lightweight output protocol for lenient Prompt Studio execution."""
from __future__ import annotations

import dataclasses
import re


PROMPT_KINDS = {"tagged_prompt", "plain_prompt", "protocol_garbage"}


@dataclasses.dataclass(frozen=True)
class LenientPromptOutput:
    """Deterministic classification of one model response."""

    kind: str
    prompt: str = ""
    summary: str = ""
    warnings: list[str] = dataclasses.field(default_factory=list)
    issues: list[str] = dataclasses.field(default_factory=list)


def parse_lenient_output(raw: str) -> LenientPromptOutput:
    """Extract a target prompt without treating malformed protocols as prose."""
    text = str(raw or "").strip()
    if not text:
        return _garbage("模型输出为空")

    prompt_match = re.search(
        r"<PROMPT\s*>\s*(.*?)\s*</PROMPT\s*>", text,
        flags=re.IGNORECASE | re.DOTALL)
    if prompt_match:
        prompt = _strip_fence(prompt_match.group(1)).strip()
        if not prompt:
            return _garbage("PROMPT 区块为空")
        summary_match = re.search(
            r"<SUMMARY\s*>\s*(.*?)\s*</SUMMARY\s*>", text,
            flags=re.IGNORECASE | re.DOTALL)
        summary = (_strip_fence(summary_match.group(1)).strip()
                   if summary_match else "")
        return LenientPromptOutput(
            kind="tagged_prompt", prompt=prompt, summary=summary)

    if re.search(r"</?(?:PROMPT|SUMMARY)\b", text, flags=re.IGNORECASE):
        return _garbage("提示词标签不完整")
    if _looks_like_json_or_protocol(text):
        return _garbage("输出看起来是损坏的 JSON 或协议说明，不能作为提示词")

    plain = _strip_fence(text).strip()
    if not _looks_like_prompt(plain):
        return _garbage("输出不具备可用提示词内容")
    return LenientPromptOutput(
        kind="plain_prompt", prompt=plain,
        warnings=["模型未遵循标签协议，已按普通提示词接收"])


def _garbage(message: str) -> LenientPromptOutput:
    return LenientPromptOutput(kind="protocol_garbage", issues=[message])


def _strip_fence(value: str) -> str:
    text = str(value or "").strip()
    fenced = re.fullmatch(
        r"```(?:text|markdown|md)?\s*\n?(.*?)\n?```", text,
        flags=re.IGNORECASE | re.DOTALL)
    return fenced.group(1).strip() if fenced else text


def _looks_like_json_or_protocol(text: str) -> bool:
    stripped = text.lstrip()
    if stripped.startswith(("{", "[", "```json")):
        return True
    markers = (
        '"prompt"', '"summary"', '"requested_changes"', '"intent_scope"',
        "json should contain", "valid json", "json schema", "schema requires",
        "return json", "output schema",
    )
    folded = text.casefold()
    return any(marker in folded for marker in markers)


def _looks_like_prompt(text: str) -> bool:
    if len(text) < 3:
        return False
    return any(character.isalpha() for character in text)
