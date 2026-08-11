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
    if mode == "Ref2VA":
        format_contract = """Use exactly these six headings in this order:
subject_definitions:
summary:
retention_analysis:
detailed_description: [Shot 1] ...
overall_soundscape:
non_diegetic_music:
Do not rename, omit, translate, number, or wrap these headings."""
    else:
        alignment = {
            "T2VA": "T2VA starts directly with integrated_multimodal_description; add no alignment line.",
            "I2VA": ("The first line must be: For the target video, at 0.00 seconds into the "
                     "target video, <Picture 1> (from [Shot 1]) is fully referenced."),
            "FL2VA": ("The first line must start with: How the reference pictures align with "
                      "the target video — and align Picture 1 at 0.00 seconds and Picture 2 "
                      f"at {float(duration):.2f} seconds."),
            "L2VA": ("The first line must start with: How the reference pictures align with "
                     "the target video — and align <Picture 1> with the final shot at "
                     f"{float(duration):.2f} seconds."),
        }.get(mode, "")
        format_contract = f"""{alignment}
After any required alignment line, use exactly these three fields in this order:
integrated_multimodal_description: [Shot 1] complete shot description
overall_soundscape: concrete full-video ambience, or N/A only for explicit complete silence
non_diegetic_music: concrete instrumentation/tempo/dynamics, or N/A when absent
Do not rename, omit, translate, number, or wrap these field names. Every shot begins with
[Shot N]; Shot 1 has no timestamp and later shots use At MM:SS.mmm."""
    return (
        "Write one complete MiniMax H3 target prompt in the official rendered text "
        f"format. Mode: {mode}. Duration: {float(duration):.2f} seconds. Preserve "
        "dialogue, lyrics, and visible text verbatim in their source language; write "
        "all other visual and audiovisual description in English. Use only connected "
        "Picture/Video/Audio labels. Include synchronized shot audio, a non-empty "
        "overall soundscape unless explicit silence was requested, and a concrete "
        "non-diegetic music decision. Translate concrete source facts faithfully. "
        "Never generalize or substitute a concrete location, vehicle, object type, "
        "character count, action, or relationship with an adjacent alternative. "
        "Do not return an internal JSON Plan.\n\n" +
        format_contract)
