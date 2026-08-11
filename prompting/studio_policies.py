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
Do not add new creative details. When a target-language issue is listed, translate
only the required visual/audiovisual prose into English while retaining names, proper
nouns, reference labels, dialogue, lyrics, and quoted on-screen text."""


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
    from ..services.skills import get_skill

    skill = get_skill({
        "anima": "prompt_studio_anima",
        "z_image": "prompt_studio_z_image",
        "qwen_image_edit": "prompt_studio_qwen_image_edit",
        "generic_image": "prompt_studio_generic_image",
    }[family])
    supplement = (skill.system_prompt.strip()
                  if skill is not None and skill.system_prompt.strip() else "")
    return policies[family] + ("\n\n[Editable target strategy]\n" + supplement
                               if supplement else "")


def h3_target_policy(mode: str, duration: float) -> str:
    return (
        "Write one complete MiniMax H3 target prompt in the official rendered text "
        f"format. Mode: {mode}. Duration: {float(duration):.2f} seconds. Preserve "
        "dialogue, lyrics, and visible text verbatim in their source language; write "
        "all other visual and audiovisual description in English. Use only connected "
        "Picture/Video/Audio labels. Include synchronized shot audio, a non-empty "
        "overall soundscape unless explicit silence was requested, and a concrete "
        "non-diegetic music decision. Do not return an internal JSON Plan.")
