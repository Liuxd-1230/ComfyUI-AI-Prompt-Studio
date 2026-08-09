# P3 Semantic Consistency and Official Research

## Consistency Pipeline

`schemas/semantic.py` defines path-addressed semantic issues, risk assessments, and observable consistency results. `domain/semantic_consistency.py` implements the ordered P3 path:

1. normalize the typed plan;
2. run deterministic semantic invariants;
3. classify the requested/dependent/invalidation/conflict risk;
4. invoke a semantic critic only for high-risk changes;
5. run at most one repair pass for explicitly repairable issues;
6. normalize and deterministically validate again.

ANIMA checks stable IDs, single fact ownership, stable/variable trait overlap, legacy description ownership, and positive/negative contradictions. Its impact analyzer clears a stale legacy description when structured character facts change and marks lighting as invalid when an environment change leaves it unresolved.

H3 receives priority checks for 4–15 second duration, shot order/timing, stable speakers, voiceover lips, concrete reference use, retention coverage, and soundscape completion. Mechanical repair is deliberately limited to shot numbering, Shot 1 timestamp removal, and voiceover closed lips. It never guesses missing sound, duration, dialogue, identity, or reference semantics.

`domain/gateway_critic.py` is a real structured-output Gateway boundary, not a mock interface. It sends compact plan context and the reasoned ChangeSet as task data and returns typed issues. A caller must pass it only when `RiskAssessment.critic_required` is true.

## Official Research

`official-source-ledger.md` records the primary sources, access/revision policy, verified scope, and local status for ANIMA, Z-Image Turbo, Qwen Image Edit 2511, and MiniMax H3. Target-specific notes classify each finding as unchanged, new, contradicted, unsupported local assumption, architectural conflict, or explicit product override.

P3 does not silently rewrite Model Cores from research notes. Model Core migration is a later phase and must cite the ledger, update source versions/hashes, add contract cases, and preserve compatibility boundaries.
