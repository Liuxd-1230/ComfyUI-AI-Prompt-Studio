# P3 Semantic Consistency and Official Research

## Consistency Pipeline

`schemas/semantic.py` defines path-addressed issues and risk assessments. The
production Prompt Composer and H3 Director REFINE paths now execute the ordered
P3 path after the P2 transaction has produced its isolated candidate:

1. normalize the typed plan;
2. run deterministic semantic invariants;
3. classify the requested/dependent/invalidation/conflict risk;
4. invoke a semantic critic only for high-risk changes;
5. reject non-repairable errors without reaching `PromptSession.commit()`;
6. for repairable errors, request exactly one new reasoned `ChangeSet`, then run
   Transaction/Diff Guard, semantic validation, Critic (when still high risk),
   renderer, and protocol validation again.

ANIMA deterministically checks stable/unique IDs, fact ownership,
stable/variable trait overlap, and positive/negative contradictions. Character
Bible identity plus explicitly locked traits are persisted as value-addressed
Session facts and resolved to current concrete paths for every transaction; list
insert/delete cannot shift a lock onto another fact. Pose, spatial,
object ownership, cross-binding, reference identity, and broader style conflicts
are high-risk Critic responsibilities when Python cannot prove them from typed
fields alone.

H3 receives priority checks for 4–15 second duration, shot order/timing, stable
speakers, visible speech-speaker binding, voiceover lips, concrete reference use,
retention coverage, and soundscape completion. Speaker IDs and reference bindings
use the same value-addressed fact locks. Action, held-object, location, clothing, causal,
camera/action, identity, and adjacent-shot state changes are classified high risk
and evaluated against the before/after candidate slice. Explicit adjacent
drop/release → hold gaps are also detected deterministically, while stated pickup,
dream, montage, flashback, time-jump, or transition intent is preserved.

`domain/gateway_critic.py` is the real structured-output Gateway boundary used by
both nodes. It receives only affected before/after values, adjacent shots, the
reasoned `ChangeSet`, and locked path values—never the full Plan or transcript.
Single color/material/clothing, minor lighting, and known compatible style presets
remain deterministic-only; unknown or conflicting style changes are escalated.
Missing Critic wiring on a high-risk pipeline is an explicit
error, not a silent skip. The Critic reports typed issues and cannot mutate Plan.

CREATE runs deterministic semantic validation before its first Session commit.
REFINE failures at proposal, transaction, Critic, repair, semantic validation, or
protocol validation preserve the stable Plan, prompt, and revision.

## Official Research

`official-source-ledger.md` records the primary sources, access/revision policy, verified scope, and local status for ANIMA, Z-Image Turbo, Qwen Image Edit 2511, and MiniMax H3. Target-specific notes classify each finding as unchanged, new, contradicted, unsupported local assumption, architectural conflict, or explicit product override.

P3 does not silently rewrite Model Cores from research notes. Model Core migration is a later phase and must cite the ledger, update source versions/hashes, add contract cases, and preserve compatibility boundaries.
