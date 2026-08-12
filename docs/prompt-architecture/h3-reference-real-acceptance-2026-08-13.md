# H3 Reference Real Acceptance — 2026-08-13

## Scope

The acceptance ran the production ComfyUI node graph on port 8189 without any
MiniMax H3 checkpoint, sampler, or video output node. Text generation used the
`基元` Responses profile; image observation used its linked LM vision profile.

## Executed paths

1. `APS_ModelProfile → APS_H3PromptStudio`, T2VA, strict, five seconds, no
   reference inputs. The returned prompt contained one `[Shot 1]`, a slow push,
   synchronized cloth/city ambience, and all three base fields. Validation: 0
   errors, 0 warnings.
2. `LoadImage (640.jpg) → APS_ReferenceAnalyzer → APS_CharacterBible →
   APS_H3PromptStudio`, I2VA, strict, five seconds. The vision result identified
   dark wavy side-braided hair, white floral hair ornament, green eyes, a white
   lace high-neck blouse, light skirt, and red rose accessories. The final prompt
   began with the exact `<Picture 1>` first-frame alignment, preserved these
   observable identity facts, used one slow orbit, and described synchronized
   petal/fabric sound. Validation: 0 errors, 0 warnings.

## Defects found and closed

- Base image modes were incorrectly validated against Ref2VA-only Shot reference
  and retention requirements even when the mandatory alignment line consumed the
  picture.
- Character Book display names were incorrectly treated as drawable traits, so a
  valid romanization or omission failed identity validation.
- A near-copy Chinese display name could drift in word order. It is now optional,
  but exact when present; explicitly locked visual traits remain hard anchors.

The deterministic regression lives in `tests/test_h3_prompt_studio.py`. Live
provider evidence complements rather than replaces the repository release gate.
