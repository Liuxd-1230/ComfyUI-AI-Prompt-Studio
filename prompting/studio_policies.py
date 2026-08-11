"""Single prompt-policy owner for ADR 0007 Studio execution lanes."""
from __future__ import annotations


LENIENT_OUTPUT_CONTRACT = """Return only this lightweight envelope:
<PROMPT>
the complete target-ready prompt
</PROMPT>
<SUMMARY>
one short factual summary of what you created or changed
</SUMMARY>
Do not return JSON, Markdown fences, schema explanations, analysis, or alternatives.
The PROMPT block must be complete and directly usable by the target model."""

LENIENT_CREATE_POLICY = """Create one complete target-ready prompt from the latest
request and supplied reference data. Preserve every explicit identity, count,
relationship, action, composition, and reference requirement. Do not invent facts
that contradict supplied data."""

LENIENT_REFINE_POLICY = """Edit the supplied current prompt according to only the
latest user instruction. Return the complete updated prompt. Preserve every
unmentioned identity, subject, action, composition, relationship, and reference."""

FORMAT_REPAIR_POLICY = """Reformat the supplied rejected model output into the
required PROMPT/SUMMARY envelope. Preserve its usable prompt content and meaning.
Do not add new creative details. When an ANIMA language issue is listed, translate
only visual prose into English while retaining names, proper nouns, reference labels,
and quoted on-screen text."""


def image_target_policy(family: str, variant: str) -> str:
    policies = {
        "anima": (
            "Write ANIMA visual prose in English. Names, proper nouns, reference "
            "labels, and quoted on-screen text may retain their source language. "
            f"Target variant: {variant or 'base'}. Produce one detailed visual prompt, "
            "not an internal Plan or tag analysis."),
        "z_image": (
            "Write one detailed Z-Image Turbo natural-language prompt covering subject, "
            "environment, composition, lighting, and style. Do not output a negative prompt."),
        "qwen_image_edit": (
            "Write a direct Qwen Image Edit instruction. State the edit, object, and "
            "location precisely. Refer to connected images only as Figure 1, Figure 2, etc."),
        "generic_image": (
            "Write one complete natural-language image generation prompt. Keep the "
            "requested subject, action, composition, environment, and style explicit."),
    }
    if family not in policies:
        raise ValueError(f"不支持的 Prompt Studio target family: {family}")
    return policies[family]
