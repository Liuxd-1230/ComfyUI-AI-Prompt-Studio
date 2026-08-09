# AI Prompt Studio — Persistent Semantic Prompt Architecture Refactor

> **用途**：交给 Coding Agent 直接执行的实施提示词与架构契约。
> **项目**：`Liuxd-1230/ComfyUI-AI-Prompt-Studio`
> **目标**：把 APS 从“LLM 改写 Prompt 的节点组”升级为“以 Semantic Plan 为真源、支持安全多轮编辑、模型专属编译、版本控制、Skill Package、风格预设与生成反馈闭环”的 Prompt 创作系统。
> **重要**：本文不是建议清单。除非当前代码或 ComfyUI API 明确证明某项不可行，否则本文中的架构边界、失败语义、兼容要求和测试要求均视为实施约束。

---

# 0. 你的角色

你是本项目的自主重构 Agent。

你的任务不是“给现有 PromptComposer 加一个聊天框”，也不是在当前实现上继续堆条件分支，而是：

1. 审计当前仓库；
2. 找出已经存在但与本文目标架构冲突的半成品实现；
3. 保持现有功能与旧 workflow 尽可能兼容；
4. 建立新的 Domain / Semantic / Session / Compilation 分层；
5. 先把数据与事务语义做正确，再做 UI；
6. 用测试证明局部修改、依赖传播、失败回滚、并发、持久化和兼容逻辑；
7. 最终新增真正的 Image Prompt Studio 与 H3 Prompt Studio。

你必须主动判断现有实现是否符合架构，而不是因为已有代码存在就默认保留。

---

# 1. 当前仓库已知现状：先审计，不要盲目假设

开始编码前，必须实际读取当前仓库相关文件，并以当前 HEAD 为准。

至少检查：

```text
nodes/prompt_composer.py
nodes/minimax_h3_director.py

schemas/prompt_plan.py
schemas/prompt_session.py
schemas/h3.py
schemas/character.py
schemas/storyboard.py

services/prompt_session.py
services/skills.py
services/gateway.py

renderers/anima.py
renderers/special_image.py

validators/anima.py
validators/minimax_h3.py

skills/
web/
server/
docs/
tests/
```

当前仓库已经存在一部分 Persistent Session 实现，但它不是本架构最终形态。

## 1.1 `APS_PromptComposer` 已被塞入 Session 逻辑

当前 `nodes/prompt_composer.py` 已出现类似：

```text
continue_previous
prompt_session
session_action
persistent_lifecycle
PromptSession
request_plan_patch
```

这属于早期试验实现。

目标架构不是继续把 PromptComposer 变成 stateful giant node。

最终原则：

```text
PromptComposer = One-shot Composer
Prompt Studio  = Stateful Editor
```

因此当前已经混入 PromptComposer 的持久会话代码必须重新评估：

- 哪些底层能力可以提取复用；
- 哪些 Session/UI 逻辑应移入新的 Studio；
- 哪些参数只作为 legacy workflow compatibility 暂时保留；
- 不允许因为已有实现存在就继续强化“PromptComposer 即 Studio”的方向。

## 1.2 当前 `PromptSession.revert_previous()` 是破坏性回退

当前实现会：

```text
pop current revision
→ pointer 回到 previous
```

目标架构禁止这种历史破坏。

正确语义：

```text
v1
v2
v3
v4

用户 Restore v2

→ 创建 v5 = restore(v2)
```

v3/v4 仍然存在于历史中。

## 1.3 当前 Patch Schema 不够

当前 `services/prompt_session.py` 主要是：

```text
base_revision
scope
changes
summary
rebuild_plan_json
```

而目标 ChangeSet 至少需要能够表达：

```text
requested_changes
dependent_changes
invalidated_facts
constraint_conflicts
base_revision
```

当前简单 Patch 只能描述“改什么”，不能可靠表达：

- 为什么连带修改；
- 什么事实被新要求废弃；
- 什么约束与用户意图发生冲突；
- 哪些修改是用户直接要求；
- 哪些修改只是为了保持全局一致。

不要在旧 Patch Schema 上简单加几个字段后就宣布完成。

## 1.4 当前 ANIMA Plan 位置与事实所有权有问题

当前 `AnimaPromptPlan` 位于：

```text
renderers/anima.py
```

而它本质上是 Semantic Domain Schema，不应该属于 renderer 内部私有实现。

当前 Plan 同时包含：

```text
natural_body
characters[].description
characters[].required_traits
characters[].variable_traits
style
environment
composition
lighting
...
```

这里存在重复表达同一事实的风险。

例如：

```text
character clothing = red dress
natural_body = "a woman in a red dress..."
```

如果只 Patch clothing，会出现：

```text
structured = blue dress
natural_body = red dress
```

因此 ANIMA 必须优先完成 Plan Normal Form。

## 1.5 当前 H3 Plan 已较成熟，但含不应回灌 LLM 的字段

当前 H3 Plan 已有较丰富的：

```text
shots
speakers
subjects
assets
retention
soundscape
music
...
```

这是正确方向，应尽量保留。

但类似：

```text
raw
warnings
validation
created_at
plan_id
```

不能直接通过 `to_json()` 全量回灌到 Refine LLM Context。

尤其 `raw` 可能重复完整 LLM JSON，造成上下文浪费。

必须实现专门的：

```python
to_llm_context()
```

而不是复用序列化存储格式。

## 1.6 当前 YAML Skill 是 Legacy

当前：

```text
services/skills.py
skills/*.yaml
```

是过去把 MiniMax H3 官方 Skill 转成内部 YAML 后形成的 APS 私有格式。

它不是未来 Skill Package 标准。

本次重构：

```text
Legacy YAML Skill
```

必须兼容旧 workflow，但不得继续作为未来可安装 Skill 生态的基础格式无限扩展。

---

# 2. 本次重构的产品目标

APS 最终同时支持两种工作模式。

## 2.1 One-shot / Automation

```text
text / storyboard / character / reference
        ↓
PromptComposer / H3 Director
        ↓
Semantic Plan
        ↓
Renderer
        ↓
Final Prompt
```

适合：

- 一次性生成；
- batch；
- 自动 workflow；
- 外部节点动态输入；
- expand/rewrite/translate/audit/repair；
- 不需要人工会话。

## 2.2 Interactive Studio

```text
User
 ↓
Conversation
 ↓
Persistent Session
 ↓
Current Semantic Plan
 ↓
Safe Change Transaction
 ↓
Renderer
 ↓
Prompt
 ↓
Image / Video Generation
 ↓
User observes result
 ↓
Feedback
 ↓
Next refinement
```

适合：

- 看结果；
- 局部反馈；
- 多轮调整；
- 版本恢复；
- 风格/Skill 切换；
- 后续接视觉反馈。

---

# 3. 用户可见节点结构

最终不要创建：

```text
Beginner Compiler
Advanced Compiler
Plan Compiler
H3 Compiler
...
```

内部代码架构不等于每一层都必须成为 ComfyUI Node。

推荐用户节点分层：

```text
DATA / CONTEXT
────────────────────────
Model Profile
Reference Analyzer
Character Bible
Storyboard Builder
Storyboard Select
Reference Prompt
...

GENERAL AI
────────────────────────
APS_LLMGenerate

ONE-SHOT PROMPT TOOLS
────────────────────────
APS_PromptComposer
APS_MiniMaxH3Director

INTERACTIVE PROMPT TOOLS
────────────────────────
APS_ImagePromptStudio
APS_H3PromptStudio

RUNTIME
────────────────────────
Runtime Control
Unload Model
...
```

---

# 4. 现有 PromptComposer / H3 Director 的定位

## 4.1 PromptComposer

定位：

```text
One-shot Composer / Facade
```

保留现有 operation 概念用于兼容和自动化：

```text
generate
expand
rewrite
translate
audit
repair
convert
```

但是内部逐渐重构为：

```text
one-shot policy
↓
Semantic Plan
↓
PlanAdapter / Renderer
↓
Validation
↓
Final Prompt
```

不能继续让 operation、family、session、renderer、validator 全部在一个巨大函数里增长。

## 4.2 H3 Director

同理：

```text
One-shot H3 Composer
```

继续适合：

```text
generate
rewrite
convert_storyboard
audit
repair
```

但底层必须与 H3 Prompt Studio 共用：

```text
H3PromptPlan
H3Adapter
H3 Renderer
H3 Validator
```

不要维护两套 H3 Prompt 生成逻辑。

---

# 5. Studio 不使用 operation 下拉框

新的：

```text
APS_ImagePromptStudio
APS_H3PromptStudio
```

主交互不显示：

```text
Generate
Expand
Rewrite
Translate
Audit
Repair
Convert
```

内部生命周期主要只有：

```text
CREATE
REFINE
```

规则：

```text
没有 Current Plan + 有新消息
→ CREATE

有 Current Plan + 有新消息
→ REFINE

有 Current Plan + 没有新消息
→ NO-OP / RE-RENDER
→ 不调用 LLM
```

不要新增：

```text
Continue previous plan
```

这种 Toggle。

Studio 的定义本身就是持续 Session。

重新开始使用：

```text
New Session
```

按钮。

---

# 6. 绝对不要让 Studio 把 PromptComposer 当黑盒

错误：

```text
Studio
↓
偷偷设置 operation=rewrite
↓
PromptComposer.compose()
```

正确：

```text
                    ┌─ PromptComposer
Shared Domain Layer ┤
                    └─ PromptStudio
```

共享：

```text
Semantic Plan
PlanAdapter
Renderer
Validator
Model Core
Context Builder
```

Composer 与 Studio 是两个上层入口。

---

# 7. Semantic Plan 是唯一核心真源

以下内容不是事实真源：

```text
chat history
rendered prompt
LLM raw output
natural-language duplicate description
validation report
UI preview
```

真正的当前作品状态是：

```text
Current Semantic Plan
```

但是禁止做一个万能：

```text
CanonicalPromptPlan
```

覆盖所有模型。

不同领域应该拥有不同 Plan 类型。

例如：

```text
AnimaPlan
VisualGenerationPlan
QwenEditPlan
H3PromptPlan
```

如果 Z-Image 与某些 image-generation target 确实语义足够一致，可以共享 Visual Plan。

如果不一致，不要为了“统一”强行抽象。

---

# 8. 数据分四层

必须在代码结构和命名上体现：

## 8.1 Source State

```text
CharacterBible
CharacterBook
Storyboard
ReferenceManifest
```

表示外部输入事实。

## 8.2 Semantic State

```text
AnimaPlan
VisualGenerationPlan
QwenEditPlan
H3PromptPlan
```

表示作品当前语义。

## 8.3 Execution State

```text
PromptStudioSession
Revision
ChangeSet
Transaction
GenerationObservation
```

表示编辑过程。

## 8.4 Compiled Result

```text
RenderedPrompt
GenerationProfile
ValidationReport
```

表示从 Plan 派生的结果。

现有 `PromptPlan` 如果同时承担多个层次，需要逐步拆责。

不要一次删除旧类型破坏 workflow；可以建立兼容 adapter。

---

# 9. Plan Normal Form — P0

这是整个重构最重要的基础之一。

原则：

> 同一个语义事实只能有一个 authoritative owner。

例如：

```text
Character.clothing = "blue dress"
```

是 authoritative。

那么：

```text
natural_body = "a woman wearing a blue dress..."
```

只能是 derived 或 non-authoritative。

不能两个都独立可编辑。

---

# 10. Plan 字段分类

每种 Semantic Plan 必须明确字段类型。

## 10.1 Authoritative Fields

用于：

- Patch；
- Diff；
- Lock；
- Impact Analysis；
- Revision；
- Validation。

例如：

```text
identity
hair
clothing
action
position
environment
objects
camera
lighting
references
shot state
style spec
negative constraints
```

## 10.2 Derived Fields

例如：

```text
natural rendered description
final prompt
tag ordering
H3 formatted text
some summaries
```

原则：

```text
authoritative field changes
→ mark derived dirty
→ renderer rebuild
```

Derived field 不得成为第二份事实真源。

## 10.3 Free Creative Fields

无法合理完全结构化的创意 prose 可以保留。

但：

> 任何需要稳定局部修改、锁定、回退、Diff、冲突判断的语义不能只藏在 prose blob 中。

如果一个 500-token 字符串同时包含：

```text
hair
clothing
camera
lighting
environment
pose
```

那么路径级 Diff Guard 几乎失效。

需要把高价值状态提升为结构化字段。

---

# 11. ANIMA Plan 重构

将当前 renderer 内部的：

```text
AnimaPromptPlan
AnimaCharacter
```

迁移/提升到正式 schema，例如：

```text
schemas/anima.py
```

允许保留兼容 import。

重新设计事实所有权。

目标示意，不要求字段名完全照抄：

```text
AnimaPlan
├─ subjects / characters
│  ├─ identity
│  ├─ stable_traits
│  ├─ variable_traits
│  ├─ clothing
│  ├─ action
│  ├─ pose
│  └─ position
├─ environment
├─ composition
├─ camera/view
├─ lighting
├─ style
├─ references
├─ positive_constraints
├─ negative_constraints
└─ optional creative_notes
```

重点不是字段数量，而是避免：

```text
natural_body
character.description
structured traits
```

同时成为独立真源。

Renderer 负责从 Plan 生成 ANIMA natural / tags / hybrid。

---

# 12. H3 Plan

现有 H3PromptPlan 方向正确。

不要为了统一 Image Plan 而削弱它。

继续保持：

```text
shots
speakers
subjects
assets
retention
soundscape
music
...
```

但逐步补充真正需要表达的语义，例如必要时：

```text
transition
time_jump
continuity_requirement
intentional_discontinuity
shot end state
shot start state
```

只有在确实有验证或编辑需求时再增加。

不要无意义地把所有自然语言拆成几百个字段。

---

# 13. PlanAdapter

建立正式的 target/domain adapter abstraction。

概念接口：

```python
class PlanAdapter:
    plan_type: str

    def create(...): ...
    def propose_changes(...): ...
    def validate_changes(...): ...
    def analyze_impact(...): ...
    def apply_changes(...): ...
    def normalize(...): ...
    def diff(...): ...
    def semantic_validate(...): ...
    def render(...): ...
    def protocol_validate(...): ...
    def repair(...): ...
    def to_llm_context(...): ...
```

可以根据实际代码拆分服务，不要求一定一个巨大 class。

重要的是职责存在且边界明确。

示例：

```text
AnimaAdapter
ZImageAdapter
QwenEditAdapter
H3Adapter
```

不要继续让：

```text
if family == ...
```

成为整个系统扩展方式。

---

# 14. REFINE 不能默认重新生成完整 Plan

普通多轮修改：

错误：

```text
Current Plan
+
latest feedback
↓
Generate entirely new Plan
```

正确：

```text
Current Plan
+
latest feedback
↓
ChangeSet
```

只有用户明确要求：

```text
“整个重新设计”
“推翻这版”
“全部重做”
```

或者 Impact Analysis 判定必须结构性重建时，才能进入受控 Broad Rewrite / Migration。

即便 Broad Rewrite，也必须事务化，并经过 Diff/Validation。

---

# 15. ChangeSet

重新设计 ChangeSet Schema。

最低语义：

```json
{
  "base_revision": 7,
  "intent_scope": "local",
  "requested_changes": [],
  "dependent_changes": [],
  "invalidated_facts": [],
  "constraint_conflicts": [],
  "summary": ""
}
```

推荐每个 change 包含：

```json
{
  "path": "characters/0/clothing/color",
  "action": "replace",
  "value": "blue",
  "reason": "User explicitly requested blue clothing"
}
```

`dependent_changes` 必须带 reason：

```json
{
  "path": "shots/1/start_time",
  "action": "replace",
  "value": 8.0,
  "reason": "Shot 1 duration increased; preserve non-overlapping timeline"
}
```

`invalidated_facts` 表达“旧事实不能再存在”：

```json
{
  "path": "environment/details/sea_breeze",
  "reason": "Environment changed from beach to space station"
}
```

不要把所有变化混成一个无来源的 `changes` 数组。

---

# 16. Minimum Consistent Change

正式原则：

> Apply the user's latest request using the smallest globally consistent change set.

不是：

```text
最少改几个字段
```

而是：

```text
Requested Delta
↓
Dependency / Impact Closure
↓
Smallest globally consistent change set
```

REFINE Policy 至少表达：

```text
First identify explicitly requested changes.

Then identify only directly dependent changes required to preserve
logical, temporal, referential, narrative, spatial, character-state,
style, positive/negative, and model-protocol consistency.

Identify existing facts that become invalid under the new request.

Preserve every unrelated existing decision.

Do not optimize for the minimum number of changed fields.

Do not modify unrelated fields merely because they could be improved.

Distinguish requested changes from dependent changes and invalidated facts.
```

---

# 17. Impact Analysis

不要只实现 Dependency Resolver。

正式使用：

```text
Impact Analysis
```

它回答：

1. 用户明确要求改什么？
2. 哪些字段必须连带变化？
3. 哪些旧事实因新要求失效？
4. 哪些约束发生冲突？
5. 哪些 derived 内容需要重渲染？
6. 哪些硬约束不能被用户/Skill 隐式覆盖？

示例：

```text
old:
environment = beach
details = sea breeze, wet sand, ocean reflection

user:
"整个场景改成太空站"
```

结果不应只是：

```text
environment = space station
```

还必须识别：

```text
invalidated:
sea breeze
wet sand
ocean reflection
```

---

# 18. 依赖分两类

## 18.1 Deterministic Dependencies

Python 能证明的全部用代码。

例如：

```text
timestamp
duration
shot ordering
shot numbering
speaker ids
asset/reference numbering
reference existence
schema types
label mapping
simple duration limits
negative duplicate cleanup
derived dirty marking
revision ids
```

原则：

> 能证明的事情不要问 LLM。

## 18.2 Semantic Dependencies

只有真正需要语义理解时调用模型。

例如：

```text
action causality
character state
object possession
spatial continuity
narrative prerequisites
scene coherence
semantic style conflicts
identity/reference continuity
```

---

# 19. 完整事务流水线

最终 REFINE 应接近：

```text
Latest User Message
        ↓
Intent Grounding
        ↓
Change Proposal
        ↓
ChangeSet Schema Validation
        ↓
Impact Analysis
        ↓
Minimum Consistent ChangeSet
        ↓
Apply to CLONE of Current Plan
        ↓
Diff Guard
        ↓
Plan Normalizer
        ↓
Deterministic Consistency Checks
        ↓
Semantic Critic (risk-triggered only)
        ↓
Renderer
        ↓
Protocol Validator
        ↓
Targeted Repair (bounded)
        ↓
Revalidate
        ↓
Atomic Commit
```

任何阶段失败：

```text
stable Current Plan remains unchanged
stable Prompt remains unchanged
revision remains unchanged
```

禁止边改边覆盖。

---

# 20. ChangeSet Schema Validator

检查：

```text
base_revision
path format
action
value type
array index
path existence
allowed roots
locked fields
immutable metadata
plan type
change category
```

禁止任意路径执行。

不要接受：

```text
__class__
..
arbitrary object attributes
```

严格白名单/结构化路径。

---

# 21. Diff Guard

Diff Guard 只回答：

> 模型是否修改了它没有被授权修改的字段？

流程：

```text
Old Plan
vs
Candidate Plan
↓
structural diff
↓
Changed Paths
```

允许集合：

```text
requested paths
+
approved dependent paths
+
approved invalidation paths
+
deterministic normalization paths
```

超出：

```text
FAIL
```

示例：

用户：

```text
“裙子改蓝色”
```

模型偷偷改：

```text
hair
camera
lighting
```

必须拦截。

---

# 22. Diff Guard 不能替代 Plan Normal Form

如果：

```text
natural_body
```

是一个包含所有视觉语义的大字符串，

LLM 只改这一个 path，也能在字符串内部偷改十件事。

因此：

```text
Path Diff Guard
```

对 semantic blob 能力有限。

解决方法不是无限复杂 NLP diff，而是：

```text
重要可编辑事实结构化
+
prose 尽量作为 derived/creative note
```

---

# 23. Semantic Consistency Validator

它与 Diff Guard、Protocol Validator 是不同东西。

## Diff Guard

```text
“有没有越权改东西？”
```

## Semantic Validator

```text
“改完以后语义自洽吗？”
```

## Protocol Validator

```text
“最终是否符合目标模型格式/协议？”
```

三者必须分开。

---

# 24. H3 Semantic Checks

至少考虑：

```text
character state continuity
location/spatial continuity
causal/action prerequisite
action contradictions
held/object state
clothing continuity
speaker continuity
speaker ↔ visible character
voiceover ↔ lips_closed
camera/action feasibility
identity/reference continuity
previous shot ending state ↔ next shot starting state
```

示例：

```text
Shot 1: drops umbrella
Shot 2: holds umbrella
```

如果无中间解释，应产生 semantic issue。

---

# 25. Image Semantic Checks

至少考虑：

```text
identity trait conflicts
CharacterBible locked trait violations
character cross-binding
pose/view contradictions
spatial contradictions
reference identity conflicts
positive/negative contradictions
style/semantic conflicts
object ownership
duplicate incompatible states
```

示例：

```text
positive: black hat
negative: hat
```

必须识别。

---

# 26. Semantic Validator 不是现实主义警察

创作允许：

```text
dream
flashback
montage
smash cut
time jump
surreal transition
intentional discontinuity
```

不要把：

```text
人物突然出现在月球
```

自动判错。

判断标准应是：

> 是否违反当前 Plan / User 声明的 continuity contract。

必要时增加：

```text
intentional_discontinuity
transition_type
time_jump
continuity_requirement
```

但不要过度 schema 化。

---

# 27. Semantic Critic 只在高风险时调用

不要每次改颜色都再调用一个 LLM Critic。

建立风险分类。

## LOW RISK

```text
single color
simple material
minor lighting trait
single clothing attribute
simple style preset change with deterministic compatibility
```

只运行 deterministic checks。

## HIGH RISK

```text
shot insertion/deletion
timeline restructuring
location change
character state change
action change
story rewrite
identity/reference change
major composition restructure
broad negative constraint changes
```

才调用 Semantic Critic。

Critic 输入只包含：

```text
affected plan slice
adjacent/dependency states
proposed changes
relevant hard constraints
```

不要整段聊天和全部历史。

Critic 输出：

```json
{
  "valid": false,
  "issues": [
    {
      "type": "causal_gap",
      "location": "shots/1 -> shots/2",
      "reason": "..."
    }
  ]
}
```

Critic 不允许直接修改 Plan。

Repair 是独立步骤。

---

# 28. Repair

Repair 必须：

- 只接收具体 issues；
- 只修改被允许的相关 paths；
- 再经过 Diff Guard；
- 再经过 Semantic/Protocol Validation；
- 次数有限；
- Repair 失败不 commit。

不要无限 repair loop。

MVP 最多一次 targeted repair 即可。

---

# 29. CREATE 与 REFINE 的 fallback 语义不同

CREATE 可以有限 graceful fallback。

例如一次性生成中：

```text
structured JSON failed
→ maybe deterministic fallback
```

但 Persistent REFINE 禁止 destructive fallback。

例如：

```text
current H3 plan = 8 shots

LLM patch parse failed
```

绝对不能：

```text
fallback → rebuild as single shot
```

正确：

```text
abort transaction
current revision unchanged
```

---

# 30. PromptStudioSession

建议重新定义，不要完全沿用当前版本。

概念字段：

```text
PromptStudioSession
├─ session_id
├─ node_instance_id
├─ schema_version
├─ domain
├─ target_signature
├─ plan_type
├─ current_plan
├─ revision
├─ recent_revisions
├─ last_processed_message_id
├─ context_fingerprints
│  ├─ model_core_hash
│  ├─ character_bible_hash
│  ├─ storyboard_hash
│  └─ reference_manifest_hash
├─ active_skill_refs
├─ style_state
├─ chat_ui_history
├─ validation_state
└─ optional generation observations
```

注意：

```text
current_prompt
```

可以作为 cached derived value，但不能成为事实真源。

---

# 31. Revision

Revision 必须不可变。

推荐：

```text
PromptRevision
├─ revision_id
├─ parent_revision
├─ base_revision
├─ plan_snapshot
├─ rendered_prompt_snapshot
├─ renderer_signature
├─ user_instruction
├─ requested_paths
├─ dependent_paths
├─ invalidated_paths
├─ change_summary
├─ validation_summary
├─ model_core_hash
├─ skill_hashes
└─ timestamp
```

不要让 rollback `pop()` 历史。

---

# 32. Restore 语义

用户：

```text
restore v2
```

当前：

```text
v4
```

结果：

```text
v5 = restore(v2)
parent_revision = v2
```

保留 v3/v4。

---

# 33. Semantic Restore 与 Exact Replay

Renderer 会升级。

所以：

```text
Plan v3 + Renderer A → Prompt A
Plan v3 + Renderer B → Prompt B
```

至少保存：

```text
renderer_signature
rendered_prompt_snapshot
```

UI/逻辑区分：

```text
Semantic Restore
= old semantic plan + current renderer

Exact Replay
= old rendered prompt snapshot
```

MVP 可以先暴露一个 Restore 行为，但底层数据必须为两者留出能力。

---

# 34. 无新消息不得再次调用 LLM

这是 P0。

用户可能只是：

```text
修改 downstream sampler seed
↓
Queue
```

Studio 不能把同一句 feedback 再处理一次。

Session 需要：

```text
message_id / message_nonce
last_processed_message_id
```

只有：

```text
message_id != last_processed_message_id
```

才能 CREATE/REFINE。

不要用当前时间戳强制 node 每次 changed。

---

# 35. ComfyUI Cache / Change Detection

Session-driving state 必须是显式输入/序列化 widget/property。

不要依赖：

```python
self.last_plan
global dict
```

ComfyUI 可能：

- cache node；
- 重建 object；
- 多 Queue；
- 重启；
- clone workflow。

必须让真正影响执行的：

```text
message nonce
session serialized state
target signature
relevant source fingerprints
```

进入合理的 change detection 路径。

---

# 36. Session Persistence

主要可移植状态：

```text
workflow-owned serialized session snapshot
```

前端执行成功后：

```text
write new session state into serializable hidden widget/property
mark workflow dirty
```

保存 workflow 后，重开应恢复。

不要让 Session 只存在 server memory。

---

# 37. Backend Recovery Journal

纯 frontend writeback 存在失败窗口：

```text
backend successfully generates v5
↓
downstream uses v5
↓
browser disconnects before frontend writes v5 to workflow
↓
workflow still stores v4
```

因此建议轻量 hybrid：

```text
Workflow Snapshot
+
Backend Recovery Journal
```

Journal 不是第二份长期真源。

用途：

```text
last successful transaction
revision lineage
crash/writeback recovery
```

重新打开时如果：

```text
workflow revision = v4
journal latest = v5
same session id
```

应提示：

```text
Recover v5?
```

而不是静默覆盖。

如果第一阶段不实现 journal，也必须设计接口，不要把架构锁死在纯 frontend state。

---

# 38. 并发 / Stale Queue

仅有 `base_revision` 不够。

例：

```text
Queue A reads v5
Queue B reads v5

A → v6A
B → v6B
```

两边本地验证都可能成功。

需要：

```text
transaction_id
base_revision
commit-time compare-and-swap
```

前端/Session commit 时：

```text
if current_revision != result.base_revision:
    reject stale result
```

迟到的结果不能覆盖新 revision。

可以以后保留为 branch candidate，但 MVP 直接 stale reject 即可。

---

# 39. Node Copy / Duplicate

Studio serialized state 被 Ctrl+C/Ctrl+V 后可能出现：

```text
same session_id
different node
```

如果 backend journal 按 session_id 管理会冲突。

因此区分：

```text
session_id
node_instance_id
```

检测复制后应：

```text
fork session identity
```

保留 plan snapshot，但产生新的 session id。

---

# 40. Session Schema Migration

所有 persistent schema 必须：

```text
schema_version
```

加载：

```text
deserialize
↓
detect version
↓
migrate step-by-step
↓
validate
↓
load
```

禁止：

```text
old JSON
→ 直接 dataclass(**json)
→ 碰运气
```

---

# 41. Forward Compatibility

明确 unknown field 策略。

推荐：

- Storage envelope 对未知 metadata 尽量保留；
- Domain Plan 遇到未知 future-required schema 应明确拒绝或通过 extension map 保存；
- 不要静默丢掉未知 authoritative semantic field；
- 版本高于当前实现且无法安全理解时，拒绝编辑但尽可能允许只读/导出。

---

# 42. Context Fingerprints

Session 保存：

```text
model_core_hash
character_bible_hash
storyboard_hash
reference_manifest_hash
active_skill_hashes
```

每轮比较。

不要把外部数据变化当普通 chat refine。

---

# 43. 外部变化处理

## Compatible Change

例如：

```text
CharacterBible 某个非结构性 trait 更新
```

→ Rebase。

## Structural Change

例如：

```text
Storyboard 大量 Shot 被替换
```

→ Migration。

## Incompatible Change

例如：

```text
Image Generation Plan
→ Qwen Image Edit Plan
```

→ explicit migration/fork/new session。

不要“魔法 Convert”。

---

# 44. Target Compatibility

PlanAdapter 声明：

```text
plan_type
compatible_targets
migration_targets
```

例如：

```text
ANIMA base → ANIMA turbo
```

可能：

```text
same plan, different renderer/profile
```

而：

```text
ANIMA generation → Qwen image edit
```

通常需要新的 Edit Plan。

---

# 45. `convert` 的语义债

审计当前 `convert`。

如果它只是：

```text
deterministic normalize / re-render
```

不要继续把它描述成真正 Model A → Model B Semantic Conversion。

需要：

- 要么重新命名内部语义；
- 要么只把真正经过 plan migration 的流程称为 convert；
- 旧 UI label 为兼容可以保留，但文档和代码注释必须真实。

---

# 46. Generic `audit` 的语义债

审计 generic audit。

如果没有实际 validator，只是形式上的 operation，不要把它和：

```text
ANIMA validator
H3 validator
```

描述成同等能力。

目标：

```text
audit capability must be explicit per adapter/target
```

---

# 47. H3 operation 传递问题

审计 H3 Director 现有：

```text
generate
rewrite
```

是否真的通过不同 policy/operation context 进入 LLM。

如果 operation 只存在于 UI/Plan metadata，实际 prompt 构建没有传入，则修复。

但不要让 Studio 重用 H3 legacy operation。

Studio 仍然使用：

```text
CREATE / REFINE
```

---

# 48. Context Builder

每个 LLM call 不发送完整 Session。

原则：

> Store Richly, Reason Compactly.

发送：

```text
APS Runtime Policy
+
Target Model Core
+
CREATE/REFINE policy
+
compact Current Semantic Plan
+
relevant hard constraints
+
activated external skills
+
style state
+
latest user message
```

不发送：

```text
entire chat transcript
all revisions
old plans
old rendered prompts
raw LLM output
created_at
plan_id
full old validation logs
redundant warnings
```

---

# 49. `to_llm_context()`

每种 Plan 必须提供专用 compact serialization。

尤其 H3：

排除：

```text
raw
warnings
validation
created_at
plan_id
```

除非 Repair 特定需要 issues。

不要直接：

```python
json.dumps(plan.to_json())
```

作为每轮上下文。

---

# 50. Context Slicing

MVP：

```text
compact full current plan
+
latest message
```

够用。

先不要上：

```text
vector DB
RAG
embedding
```

未来长 H3 Plan 再做：

```text
Plan Index
+
Affected Slice
+
Adjacent States
+
Direct Dependencies
```

不要第一版过度设计。

---

# 51. Prompt Budget

除了 Context，最终 Prompt 自身也可能 30 轮后膨胀。

Adapter 提供：

```text
semantic budget
render budget
```

Normalizer 允许：

```text
deduplicate
remove obsolete derived details
compact equivalent descriptions
```

但不能删除：

```text
hard user constraints
locked CharacterBible traits
required model protocol
```

---

# 52. Chat UI History 与 LLM Context 解耦

UI 可以保存有限聊天历史用于用户阅读，例如：

```text
20–50 messages
```

但 LLM 不必回放这些历史。

模型真正需要的是：

```text
Current Plan + latest instruction
```

这也是 Persistent Semantic Plan 的意义。

---

# 53. Studio Assistant Reply

每轮成功后，Chat 中 Assistant 回复主要是：

```text
简短变更摘要
```

例如：

```text
已把裙子改成蓝色；人物身份、镜头和环境保持不变。
```

不要每轮把完整 Prompt 塞入聊天。

完整 Prompt 位于只读 Preview。

---

# 54. Prompt Preview

默认只读。

```text
Semantic Plan
↓
Renderer
↓
Prompt Preview
```

不要让用户直接改 Preview 后 Plan 不同步。

如果未来支持 Manual Edit：

```text
edited prompt
↓
Import / Parse
↓
candidate semantic changes
↓
new revision
```

否则会产生第二事实真源。

---

# 55. 不设置默认 Manual Approval Gate

正常用户流程：

```text
Generate
↓
Observe actual image/video
↓
Feedback
↓
Refine
```

不是：

```text
Plan changed
↓
Approve
↓
Generate
```

不要默认每轮多一个审批按钮阻塞体验。

---

# 56. Generation Provenance

用户反馈通常针对“某一次实际生成”，不是抽象 Prompt。

同一个 Plan/Prompt：

```text
seed A → good
seed B → face bad
```

“脸不好看”未必意味着 Plan 有问题。

为未来设计：

```text
GenerationObservation
```

至少：

```text
observation_id
revision_id
prompt_hash
target_signature
generation/run id
optional seed/settings fingerprint
batch index
user feedback
```

MVP 如果无法完整接 downstream execution，也至少预留 schema/interface。

---

# 57. Current Observation / Reference Scope

用户会说：

```text
“上一张”
“第二张”
“刚才那个脸”
“前一个视频”
```

Session/UI 需要知道当前 feedback 的候选观察集合。

例如：

```text
current_generation_group
recent_generation_observations
```

无法唯一解析时进入 Ambiguity Gate。

---

# 58. Intent Grounding / Ambiguity Gate

不是每条 Chat 都必须产生 revision。

如果用户说：

```text
“把她衣服换一下”
```

但场景里有三个人且无法确定“她”，不要猜。

如果：

```text
“第二张”
```

但存在多个 batch，也不要猜。

流程：

```text
Can target be uniquely resolved?
├─ yes → ChangeSet
└─ no  → ask clarification / no mutation
```

Ambiguous turn：

```text
revision unchanged
```

---

# 59. Model Core 与 Skill 必须彻底分开

不要继续把所有模型专属规则都叫 Skill。

正式区分：

```text
Model Core
External Skill
Style Preset
Session
```

---

# 60. Model Core

Model Core 是 APS 内部 target adapter/driver 规范。

例如：

```text
ANIMA Core
MiniMax H3 Core
Qwen Image Edit Core
Z-Image Core
```

负责：

```text
model-specific semantic rules
target protocol
create policy
refine constraints
renderer
validator
reference handling
plan compatibility
```

它不是用户随便安装后可以替换的第三方 Skill。

---

# 61. Runtime Policy 与 Model Core 的边界

最上层：

```text
APS Hard Runtime Policy
```

负责：

```text
transaction safety
schema enforcement
diff authorization
revision semantics
state consistency
prompt injection boundary
security
```

用户 Skill 不能覆盖。

Model Core 负责：

```text
target model truth
```

也不能被普通 External Skill 随意关闭。

---

# 62. External Skill Package

真正的用户 Skill 使用包格式。

P0 安装单位：

```text
ZIP
```

推荐目录：

```text
photo-abstract-editorial.zip
└── photo-abstract-editorial/
    ├── SKILL.md
    ├── aps.json              # optional
    ├── references/
    ├── assets/
    └── scripts/
```

---

# 63. `SKILL.md`

保留 Skill 作者原始内容。

不要把第三方 Skill 再转换成 APS YAML 作为主要存储格式。

如果可以，兼容通行的 `SKILL.md` 目录式 Skill。

---

# 64. `aps.json`

可选 APS metadata，不替代 SKILL.md。

示例：

```json
{
  "schema_version": 1,
  "id": "photo-abstract-editorial",
  "domains": ["image"],
  "role": "creative_direction",
  "compatible_plan_types": ["anima", "visual_generation"],
  "affects": ["style", "composition", "lighting", "camera"]
}
```

没有 `aps.json`：

```text
APS analyzes SKILL.md
→ creates local compatibility metadata
```

不要修改第三方原始 SKILL.md。

---

# 65. ZIP Installer

设置页：

```text
Install Skill
[ Select ZIP ]
```

支持 drag/drop 可后做。

GitHub 以后只是来源：

```text
GitHub repo/release
↓
download zip
↓
same ZIP importer
```

不要维护两套 package install pipeline。

---

# 66. ZIP 安全

P0 必须防：

```text
path traversal
../../
absolute paths
symlink escape
zip bombs
unreasonable file count
unreasonable expanded size
duplicate/conflicting root
hidden executable surprise
```

安装前解压到临时目录，验证后原子移动。

不要直接 extractall 到最终 Skill 目录。

---

# 67. Third-party Scripts

第一版：

```text
scripts/ may be stored
but NEVER automatically executed
```

最好默认：

```text
scripts disabled
```

任何脚本执行能力以后单独设计：

```text
permissions
sandbox
explicit enable
```

不要在本次重构顺手打开任意代码执行。

---

# 68. Skill Registry

未来建议：

```text
skill_packages/
```

每个 Skill 一个目录。

例如用户目录：

```text
ComfyUI/user/ai_prompt_studio/skills/
```

具体路径按项目现有 config conventions 决定。

Registry 至少记录：

```text
id
name
version
source
format
hash
enabled
domains
role
capabilities
compatible plan types
path
```

---

# 69. Legacy YAML Skill

当前 YAML：

```text
skills/*.yaml
custom skills/*.yaml
```

继续：

```text
read-compatible
```

不要一开始删除。

标记：

```text
legacy_aps_yaml
```

如果旧 workflow 引用，继续可用。

但：

- 新 UI 不鼓励创建新的 YAML Skill；
- 新 ZIP Skill 不转成 YAML；
- Model Core 不再依赖“一个 YAML system_prompt 就代表模型能力”的假设。

---

# 70. 旧同名覆盖行为

当前 custom YAML 同名会覆盖 builtin。

新架构：

- 保留 legacy compatibility；
- 新 Skill Package 默认禁止 silent override；
- 同 ID 冲突时显示来源与冲突；
- 用户必须显式 Replace / Install as new id；
- 不允许第三方包悄悄替换 Model Core。

---

# 71. Skill Capability

Skill 不能因为成功解析就默认可用于所有 Studio。

至少识别：

```text
domain
role
compatible_plan_types
affects
requires_scripts
requires_assets
```

如果内部 Native/Legacy Skill 需要 capabilities，可表示：

```text
one_shot
studio_create
studio_refine
repair
```

但不要把 Model Core 和 External Skill 再混回一个类型。

---

# 72. Skill 与 Model Core 冲突优先级

正式优先级：

```text
APS Hard Runtime Policy
        >
Target Model Core / Protocol
        >
Locked Source Constraints
        >
Latest Explicit User Intent
        >
Activated External Skills
        >
Style Preset / Soft Preferences
        >
Model Defaults
```

说明：

- 用户明确要求一般高于 External Skill 的软创作建议；
- 用户不能通过自然语言绕过硬协议/安全事务；
- Skill 不能改变 locked identity；
- Skill 不能关闭 validator/diff guard；
- Skill 中针对其他模型的格式命令不能污染当前 target。

---

# 73. Prompt Injection Boundary

以下全部作为 DATA，而不是系统指令：

```text
Storyboard
Story text
Character Bible
Reference descriptions
Current Plan
Previous generated prompt
External Skill content where appropriate
Visible text
Dialogue
Validator issues
```

构建上下文时清晰分区：

```text
SYSTEM
APS Runtime Policy
Model Core
Session Policy

SKILL GUIDANCE
...

STRUCTURED TASK DATA
...

USER
latest request
```

如果 External Skill 含：

```text
ignore previous instructions
output only ...
```

不能覆盖 Runtime/Model Core。

---

# 74. Skill Extension / Full Fork

如果保留 APS 自定义专业指导能力，建议提供两种方式。

## Extension

推荐普通用户：

```text
Base Skill
+
User Extension
```

只保存用户自己的 delta。

官方 Skill 更新后仍能继承新版本。

## Full Fork

高级：

```text
copy entire skill
→ independent custom skill
```

用于真正需要完全控制的人。

如果 ZIP Skill 已经天然是用户自定义包，可以用“Duplicate / Fork package”实现。

---

# 75. Skill Test Bench

设置/开发界面建议加入测试入口。

至少可输入：

```text
Current Plan optional
Latest instruction
CREATE / REFINE
Target
Active Skill
```

显示：

```text
LLM raw response (debug only)
ChangeSet
requested paths
dependent paths
invalidated paths
Diff
semantic issues
protocol issues
rendered prompt
token usage
```

可运行固定 regression fixtures。

这是开发 Skill 的工具，不要求第一批普通 UI 全开放，但服务层应支持。

---

# 76. Style Preset

Style 不属于 Skill。

Studio Advanced 增加：

```text
Art Style
[ Auto / No preset ▼ ]

Custom Style
[ ... ]
```

Image 初始预设可包括：

```text
Auto / No preset
Photorealistic
Cinematic
Anime
Manga
Digital Illustration
Concept Art
Oil Painting
Watercolor
3D Render
Pixel Art
Retro Film
Cyberpunk
```

不要预设几十上百项。

---

# 77. StyleSpec

Style 是 Semantic Plan 的正式部分。

示例：

```text
StyleSpec
├─ preset_id
├─ custom_style
├─ resolved_traits
└─ source
```

不要只是 renderer 最后拼接几个词。

---

# 78. Preset 与 Custom Style 冲突

规则：

```text
compatible
→ merge

conflict
→ explicit Custom Style wins
→ incompatible preset traits invalidated
→ optional warning
```

例如：

```text
preset = Photorealistic
custom = flat anime cel shading
```

不能输出：

```text
photorealistic + anime cel shading
```

如果语义冲突，Custom 赢。

---

# 79. Auto Style

默认：

```text
Auto / No preset
```

含义：

```text
do not inject a hard style preset
```

不是：

```text
call another LLM to guess style
```

保留用户和 Model Core 当前语义。

---

# 80. H3 Style

H3 可以共享 StylePreset infrastructure，但 UI 语义显示为：

```text
Visual / Film Style
```

示例：

```text
Cinematic
Documentary
Commercial
Anime
Handheld Realism
Music Video
Vintage Film
Surreal
```

具体如何映射到：

```text
camera
lighting
visual treatment
editing rhythm
```

由 H3 Adapter / Core 决定。

---

# 81. Style 不得改 Identity

例如选：

```text
Oil Painting
```

不能自动修改：

```text
black hair
blue eyes
red coat
```

Style 是 treatment，不是 identity source。

---

# 82. Skill 与 Style 的区别

不要制造：

```text
anima_cinematic_skill
anima_watercolor_skill
...
```

StylePreset：

```text
quick aesthetic direction
```

External Skill：

```text
professional methodology / creative workflow / domain knowledge
```

例如 `photo-abstract-editorial` 更可能是 External Creative Skill，而不是一个简单 StylePreset。

---

# 83. Session Pinning

Session 保存：

```text
model_core id/hash/version
active skill id/hash/version
style state
```

中途 Skill 变更：

```text
detect fingerprint mismatch
```

但：

```text
do not silently rewrite current plan
```

兼容变化：

```text
continue from current semantic plan using new guidance
```

结构不兼容：

```text
migration / new session
```

---

# 84. Observability

每个事务保留轻量事件。

例如：

```text
RevisionEvent
├─ transaction_id
├─ base_revision
├─ result_revision
├─ user_message_id
├─ requested_paths
├─ dependent_paths
├─ invalidated_paths
├─ diff_guard_result
├─ semantic_validation_result
├─ protocol_validation_result
├─ repair_count
├─ model_core_hash
├─ skill_hashes
├─ duration/token usage optional
└─ status
```

目的：

能够判断问题到底来自：

```text
Intent grounding
Refiner
Impact Analysis
Diff Guard
Semantic Critic
Renderer
Protocol Validator
Persistence
Concurrency
```

不要最终只剩：

```text
AI result wrong
```

---

# 85. Debug 数据不要污染正常 Session

例如：

```text
LLM raw
full validator trace
full context dump
```

默认不持久化进 workflow。

可通过：

```text
debug mode
backend log
temporary test bench
```

查看。

---

# 86. Workflow JSON Size

默认限制：

```text
current_plan                1
recent revisions            5–10
chat UI history             20–50
raw LLM output              0
full validation history     0
old prompt snapshots        bounded with revisions
generation observations     bounded
```

不要无限增长。

---

# 87. Source Fingerprints

CharacterBible / Storyboard / ReferenceManifest 最多做轻量修改：

```text
schema_version
content_hash/fingerprint
to_context_view()
```

不要把：

```text
session
revision
chat
```

塞进这些 Source Node。

---

# 88. APS_LLMGenerate

保持 general-purpose primitive。

不要让它知道：

```text
ANIMA Plan
H3 Plan
Prompt Studio Session
Skill package semantics
```

Studio 内部可以复用 Gateway，不要把 LLMGenerate 变成系统大脑。

---

# 89. Renderer

Renderer 的职责：

```text
Semantic Plan
→ deterministic target prompt
```

不要：

```text
store session
mutate plan secretly
call random LLM
manage chat
```

如果需要 normalization，显式放到 adapter/normalizer。

---

# 90. Protocol Validator

只回答：

```text
Does the rendered result satisfy target protocol?
```

例如 H3：

```text
section order
shot numbering
timestamps
duration
dialogue markers
speaker labels
reference labels
soundscape/music
mode limits
```

不要让 Protocol Validator 承担 narrative critic。

---

# 91. Model Core / Renderer Signature

Revision 保存：

```text
renderer_signature
model_core_hash
```

方便重现和 migration。

Signature 可以基于：

```text
plugin version
renderer version
model core version/hash
```

---

# 92. Migration API

建议统一：

```text
migrate_plan(old_plan, from_schema, to_schema)
rebase_plan(current_plan, source_changes)
migrate_target(current_plan, target_adapter)
```

不要求第一版实现所有 target migration。

但接口与失败语义要存在。

---

# 93. Failure Semantics

明确各错误是否阻止 commit。

| Failure | Commit? | Stable Plan |
|---|---:|---|
| LLM network error | No | unchanged |
| LLM malformed ChangeSet | No | unchanged |
| stale base_revision | No | unchanged |
| invalid path | No | unchanged |
| Diff Guard fail | No | unchanged |
| deterministic semantic fail | No unless repaired | unchanged |
| Semantic Critic fail | No unless repaired | unchanged |
| protocol validation fail | No unless repaired | unchanged |
| repair fail | No | unchanged |
| frontend writeback fail after backend success | recovery needed | workflow snapshot may lag |
| ambiguous user intent | No | unchanged |
| no new message | No new revision | unchanged |

---

# 94. Atomic Commit

Commit 只能发生在：

```text
candidate plan valid
+
semantic checks pass
+
renderer succeeds
+
protocol validation passes
+
base revision still current
```

然后一次更新：

```text
current_plan
revision
cached prompt
validation summary
history
last_processed_message_id
```

不要提前改变 Session。

---

# 95. Broad Rewrite

必须显式受控。

不要保留类似：

```text
scope=broad
rebuild_plan_json
```

然后允许模型自由重建且只检查 root。

如果需要 broad：

1. 用户意图必须明确或 policy 明确判定；
2. 仍然基于 old plan；
3. 输出完整 candidate 或 structured migration；
4. Diff 仍然可见；
5. hard constraints 仍然锁定；
6. semantic/protocol validation；
7. 事务 commit。

---

# 96. Locked Constraints

区分：

```text
hard locks
soft preferences
```

例如：

```text
CharacterBible locked identity
reference-bound identity
model protocol
```

是 hard。

StylePreset 是 soft。

用户 latest intent 可以覆盖旧 soft creative decision，但不能静默覆盖 hard lock。

如果用户明确要求修改 hard lock：

```text
return explicit conflict
```

是否允许用户手动 unlock 由 Source Node 决定，不由 Refiner 偷改。

---

# 97. Positive / Negative 同一影响图

例如：

```text
negative = hat
```

用户：

```text
add black wide-brim hat
```

Impact Analysis 应识别：

```text
requested:
headwear = black wide-brim hat

invalidated:
negative constraint "hat"
```

避免 Prompt 自打架。

---

# 98. Reference / Character / Style 关系

检查：

```text
character ↔ reference
character ↔ CharacterBible
style ↔ identity
style ↔ composition
reference ↔ target protocol
```

External Skill 只能影响被允许的 creative fields。

---

# 99. One-shot Legacy Compatibility

旧 workflow 必须尽可能继续运行。

策略：

- 保持 Node class names；
- 保持旧 INPUT widgets 顺序时特别谨慎，因为 ComfyUI workflow 可能按 `widget_values` 顺序序列化；
- 新 optional widget 应追加而不是插入破坏序列；
- 已 deprecated 参数继续迁移；
- 不随意改 RETURN_TYPES；
- 如果必须改，提供 compatibility shim。

在当前 PromptComposer 中已经有关于旧 widget 顺序的兼容注释，重构时必须尊重这种风险。

---

# 100. 不要让 Legacy 决定新架构

兼容是边界层。

不要因为：

```text
PromptComposer 旧 workflow 有 session_action
```

就让新的 Studio 继续沿用错误概念。

允许：

```text
legacy shim
→ calls new service
```

但核心架构遵循本文。

---

# 101. 前端 UI — 最终形态

Image Studio 概念：

```text
APS Image Prompt Studio
──────────────────────────────

Target
[ ANIMA Base ▼ ]

Chat
──────────────────────────────
User: ...
APS: 已修改...

[ message input                ]
[ Send ]

Current Prompt
──────────────────────────────
(read-only preview)

Revision
v7   [History]

Advanced ▼
──────────────────────────────
Art Style
[ Auto / No preset ▼ ]

Custom Style
[                         ]

Active Skills
[ Photo Abstract Editorial ]
[ Manage Skills ]

Validation
✓

[ New Session ]
```

---

# 102. H3 Studio

类似：

```text
Target / H3 Mode
Chat
Current Prompt
Revision
Visual / Film Style
Active Skills
Validation
New Session
```

不要复制两个完全独立的 Session engine。

共享 Session/transaction infrastructure。

Domain Plan 和 Adapter 不同。

---

# 103. UI 只展示必要状态

普通用户不需要看到：

```text
base_revision
transaction_id
model_core_hash
ChangeSet JSON
```

这些可进：

```text
Advanced Debug
```

普通 UI 关注：

```text
current prompt
change summary
revision
warnings
style
skills
new session
```

---

# 104. Skill Manager UI

推荐：

```text
Skills
────────────────────────

Installed
Photo Abstract Editorial
Fashion Photography
...

[ Install ZIP ]

Legacy
ANIMA Expand YAML
...
```

每个包：

```text
name
version
source
enabled
compatibility
permissions
hash
```

操作：

```text
Enable
Disable
Inspect
Remove
Duplicate/Fork
```

---

# 105. Skill Install Preview

安装前显示：

```text
Package
Format
SKILL.md found?
references count
assets count
scripts count
compatible domains
compatible targets
warnings
permissions
```

用户确认安装。

如果安装流程已有前端确认机制则复用。

---

# 106. Style Preset 数据文件

预设不要硬编码散落在 JS/Python。

建议：

```text
style_presets/
```

或一个清晰 registry。

每个 preset 具有稳定 ID：

```text
cinematic
photorealistic
anime
...
```

label 可国际化。

Adapter 负责 target-specific interpretation。

---

# 107. 测试策略

不要只写 unit tests 针对 helper。

必须有：

```text
domain tests
transaction tests
compatibility tests
persistence tests
security tests
regression tests
```

---

# 108. P0 Regression Matrix

以下在 Studio 架构宣称完成前必须覆盖。

## 108.1 Single Attribute Edit

Old：

```text
red dress
black hair
wide shot
night street
```

User：

```text
“裙子改蓝色”
```

Expected：

```text
dress → blue
hair unchanged
camera unchanged
environment unchanged
```

## 108.2 Derived Description Synchronization

Old：

```text
clothing = red
derived prose = red dress
```

User：

```text
blue
```

Expected：

```text
authoritative = blue
rendered prose = blue
no red residue
```

## 108.3 Environment Invalidation

Old：

```text
beach
sea breeze
wet sand
ocean reflections
```

User：

```text
“改成太空站”
```

Expected：

```text
beach-dependent facts invalidated
unrelated character identity preserved
```

## 108.4 Positive / Negative Conflict

Old：

```text
negative: hat
```

User：

```text
“戴黑色帽子”
```

Expected：

```text
positive adds hat
negative incompatible constraint removed/updated
```

## 108.5 H3 Timing Dependency

User extends Shot 1.

Expected：

```text
dependent timestamps adjusted deterministically
no overlap
unrelated shot content preserved
```

## 108.6 Delete Middle Shot

Delete transition shot.

Expected：

```text
numbering fixed
timeline fixed
semantic continuity checked
```

If causal gap remains：

```text
transaction requires targeted dependency change or reports issue
```

## 108.7 Object State

```text
Shot 1 drops umbrella
Shot 2 still holds umbrella
```

Expected semantic issue unless explicit pickup exists.

## 108.8 Intentional Surreal Transition

```text
Tokyo street
→ intentional smash cut to Moon
```

Expected：

```text
not automatically rejected as impossible
```

## 108.9 Unauthorized Changes

User changes dress.

Mock LLM changes hair/camera too.

Expected：

```text
Diff Guard reject
```

## 108.10 Malformed Patch

Expected：

```text
no commit
old plan intact
```

## 108.11 Validator Failure

Expected：

```text
no stable-state mutation unless targeted repair succeeds
```

## 108.12 Repair Failure

Expected：

```text
old revision remains active
```

## 108.13 No New Message

Queue workflow again with same message nonce.

Expected：

```text
zero LLM refine calls
same revision
```

## 108.14 Stale Concurrent Result

A/B from same base.

Expected：

```text
only first successful CAS commit wins
late result stale
```

## 108.15 Restore

v1→v2→v3→v4, restore v2.

Expected：

```text
create v5 based on v2
v3/v4 history remains
```

## 108.16 Workflow Reload

Save/reopen.

Expected current plan/revision restored.

## 108.17 Node Copy

Copy Studio node.

Expected：

```text
new node_instance/session identity
plan may be cloned
backend journal identity does not collide
```

## 108.18 Skill Changed

Skill hash changes.

Expected mismatch detection.

No silent full Plan rewrite.

## 108.19 CharacterBible Changed

Expected rebase/conflict logic.

## 108.20 Storyboard Major Change

Expected migration path, not normal tiny patch.

## 108.21 Target Compatible Switch

ANIMA variant switch.

Expected semantic plan reuse where valid.

## 108.22 Target Incompatible Switch

Generation → Edit plan.

Expected explicit migration/new session.

## 108.23 Long Conversation

50 turns.

Expected：

```text
LLM context does not linearly include all chat history
```

## 108.24 Workflow Size

Many revisions.

Expected bounded history.

## 108.25 Prompt Injection in Storyboard

Expected Runtime Policy unaffected.

## 108.26 Prompt Injection in Skill

Expected Model Core/Runtime cannot be overridden.

## 108.27 ZIP Path Traversal

Malicious archive entry：

```text
../../evil.py
```

Expected install reject.

## 108.28 Skill Scripts

Package includes scripts.

Expected：

```text
not executed
```

## 108.29 Style Conflict

Preset：

```text
Photorealistic
```

Custom：

```text
flat anime cel shading
```

Expected：

```text
custom wins conflicting style traits
```

## 108.30 Style Identity Lock

Oil Painting preset.

Expected character identity unchanged.

---

# 109. 开发顺序

不要平行乱改所有层。

## PHASE 0 — Repository Audit & Architecture Baseline

必须先完成：

1. 阅读当前架构；
2. 列出当前半成品 Session 代码；
3. 标记：reuse / refactor / deprecate / remove after migration；
4. 识别旧 workflow compatibility requirements；
5. 建立 architecture note / ADR。

禁止此阶段重做 UI。

验收：

```text
clear module boundaries
no hidden assumptions
tests still pass
```

## PHASE 1 — Semantic Domain Foundation

实现：

```text
formal ANIMA semantic schema
Plan Normal Form
PlanAdapter abstraction
to_llm_context
plan schema versioning
migration hooks
```

H3 保持现有丰富 schema，补 compact context。

验收：

```text
Semantic Plan can serialize/deserialize
important semantic facts have single owner
renderer accepts formal plan
old renderer entrypoints still work
```

## PHASE 2 — Transaction & Safe Mutation

实现：

```text
new ChangeSet
Impact Analysis interfaces
apply-to-clone
authorized paths
Diff Guard
invalidated facts
constraint conflicts
atomic commit
```

先用 deterministic/mocked LLM 测试。

## PHASE 3 — Semantic Consistency

实现：

```text
deterministic invariants
risk classifier
semantic issue schema
risk-triggered critic
bounded targeted repair
```

H3 优先验证。

## PHASE 4 — Session & Revision

实现：

```text
PromptStudioSession vNext
immutable revision
restore-as-new-revision
message nonce
source fingerprints
model/skill fingerprints
bounded history
```

把当前 destructive revert 修掉。

## PHASE 5 — Persistence & Concurrency

实现：

```text
serialized workflow session
frontend writeback
cache semantics
transaction_id
commit-time CAS
node instance identity
session copy/fork
schema migration
```

Backend recovery journal 可实现 minimal version 或提供 clean interface + tests，但不能把未来可能性堵死。

## PHASE 6 — H3 Prompt Studio

先做：

```text
APS_H3PromptStudio
```

原因：H3 当前 Semantic Plan 最成熟，最适合验证整套 Session/Transaction 架构。

要求：

```text
CREATE
REFINE
no operation dropdown
read-only prompt preview
revision
New Session
semantic continuity checks
same H3 renderer/validator as one-shot
```

## PHASE 7 — Image Prompt Studio

优先：

```text
ANIMA
```

因为现有 AnimaPromptPlan 已经提供基础，但需要 Normal Form。

再：

```text
Z-Image
Qwen Image Edit
```

如果语义不同，建立不同 PlanAdapter。

不要强行共用同一个 Plan。

## PHASE 8 — Model Core Separation

把当前 Legacy YAML 中真正属于：

```text
model target truth
renderer selection
validator selection
```

的概念迁移到 Model Core。

不要立即删除 YAML compatibility。

## PHASE 9 — Skill Package

实现：

```text
ZIP importer
SKILL.md loader
optional aps.json
registry
compatibility metadata
enable/disable
security checks
scripts disabled
legacy YAML compatibility
```

GitHub direct install 不属于 P0。

## PHASE 10 — Style Presets

实现：

```text
StyleSpec
preset registry
Auto
Custom Style
conflict resolution
Adapter rendering
```

Advanced UI 添加下拉。

## PHASE 11 — UI Polish

最后再做：

```text
chat layout
revision history
diff viewer
validation indicators
skill selector
style selector
recovery prompt
debug panel
generation observation hooks
```

禁止在基础架构未通过测试前投入大量 UI 重构。

---

# 110. 每 Phase 的工作方式

每一 Phase：

1. 先列明目标文件；
2. 说明现有代码与目标的差异；
3. 最小范围修改；
4. 添加/更新测试；
5. 运行测试；
6. 修复回归；
7. 更新文档/CHANGELOG；
8. 再进入下一 Phase。

不要：

```text
一次修改几十个文件
然后最后才运行测试
```

---

# 111. 兼容原则

优先保持：

```text
existing node class names
existing workflow loadability
old target names
old renderer outputs
legacy YAML skill references
old optional widget serialization
```

如果无法完全兼容：

- 明确 migration；
- 给出 warning；
- 不静默改变语义。

---

# 112. 不允许的架构捷径

以下视为错误实现。

1. 把所有新功能继续塞进 `APS_PromptComposer`。
2. 把 Chat History 当真源。
3. 每次 REFINE 重新生成整个 Plan。
4. 只依赖 Prompt 文字 diff 判断修改范围。
5. 把 Semantic Validator、Diff Guard、Protocol Validator 合并成一个“AI 检查”。
6. 每轮都调用第二个 Semantic Critic。
7. 用 `self.session` / global dictionary 作为唯一 Session。
8. rollback 删除 revision。
9. 无新消息仍调用 LLM。
10. 允许迟到 Queue 覆盖新 revision。
11. 把外部 Skill 当另一个最高优先级 system prompt。
12. 第三方 ZIP scripts 自动执行。
13. StylePreset 变成几十个重复 Skill。
14. 把 Model Core、External Skill、Style、Session 再合成一个类型。
15. 直接让用户编辑 Prompt Preview 而不同步 Plan。
16. 把 renderer 内部 prose 当 Semantic Plan 唯一状态。
17. 为了统一而把 H3 强行塞进 Image Plan。
18. 遇到 broad change 就允许任意 `rebuild_plan_json` 绕过 Diff/Validator。

---

# 113. 推荐目录方向

不要求机械照抄，但职责应类似：

```text
schemas/
  studio_session.py
  changeset.py
  revision.py
  anima.py
  h3.py
  style.py
  generation_observation.py

domain/
  adapters/
    base.py
    anima.py
    h3.py
    z_image.py
    qwen_edit.py

services/
  studio/
    engine.py
    context_builder.py
    transaction.py
    impact_analysis.py
    diff_guard.py
    semantic_validation.py
    persistence.py
    migrations.py
    recovery.py

model_core/
  anima/
  minimax_h3/
  z_image/
  qwen_edit/

skill_packages/
  loader.py
  registry.py
  installer.py
  compatibility.py

style_presets/
  registry.py
  presets.*

renderers/
validators/
nodes/
web/
```

如果当前包结构有更合适的组织，可以调整。

不要为了目录美观做无价值移动。

---

# 114. Model Core Prompt Composition

每轮语义 LLM 调用应按层构建。

概念：

```text
SYSTEM:
  APS Runtime Policy
  Target Model Core
  CREATE or REFINE Policy

SKILL GUIDANCE:
  activated compatible external skills

STYLE:
  current StyleSpec

STRUCTURED CONTEXT:
  compact semantic plan
  source locks
  relevant references

USER:
  latest user instruction
```

不要：

```text
concat random system prompts
```

需要明确优先级和数据边界。

---

# 115. External Skill Adapter

External Skill 不一定天然知道 APS Plan。

因此可建立：

```text
ExternalSkillProfile
```

例如：

```json
{
  "domain": "image",
  "role": "creative_direction",
  "affects": ["style", "composition", "lighting", "camera"],
  "target_specific_syntax": false,
  "requires_scripts": false,
  "compatible_plan_types": ["anima", "visual_generation"]
}
```

有 `aps.json` 优先。

无 metadata 时：

- 基于 SKILL.md 做保守分析；
- 不确认的 compatibility 标记 unknown；
- 不要自信地赋予高权限。

---

# 116. Skill Target-Specific Syntax

如果 Skill 内容要求：

```text
--ar 3:2 --stylize 500
```

但当前 target 是 ANIMA：

不能直接注入最终 Prompt。

External Skill guidance 应经过 target Adapter / Core 解释。

如果无法安全适配：

```text
mark incompatible
```

---

# 117. User Intent vs Skill

用户最新明确要求：

```text
“不要 editorial 构图，改成普通证件照”
```

即便 active Skill 是 editorial：

用户 explicit intent 在 soft creative 层优先。

但如果用户要求违反 target hard protocol：

Model Core/Validator 优先。

---

# 118. Art Style 与 External Skill 同时启用

例如：

```text
Skill: photo-abstract-editorial
Preset: Cinematic
Custom: cold fluorescent light
```

不能简单 concat。

通过 Style/Skill influence map 进入 Plan。

Impact Analysis / conflict resolver 处理冲突。

如果 Skill 给的是方法论，不应转成一堆永远残留的 Prompt 字符串。

---

# 119. Generation Feedback 与 Plan 修改

未来用户反馈：

```text
“这张脸太近”
```

系统应先判断：

```text
是随机生成问题？
是 camera/composition Plan 问题？
是 identity problem？
```

MVP 可以仍让 LLM 解释，但数据架构必须把 feedback 绑定到：

```text
revision / generation observation
```

不要丢失 provenance。

---

# 120. 事务可观测状态

建议 transaction status：

```text
created
intent_resolved
patch_proposed
impact_resolved
candidate_built
diff_checked
semantic_checked
rendered
protocol_checked
committed
failed
stale
```

调试日志足够，不需要全部展示给普通用户。

---

# 121. Token / Cost 约束

Context Builder 可以记录估算：

```text
model core tokens
skill tokens
plan tokens
latest request tokens
```

如果 Skill 太长：

优先：

- progressive disclosure；
- 只载入 relevant references；
- compact external skill context。

不要每次把 ZIP 包所有 references 全塞进 LLM。

---

# 122. Skill Progressive Disclosure

对于 Skill Package：

默认加载：

```text
SKILL.md core instructions
```

references 仅在：

- Skill 明确要求；
- 当前任务匹配；
- Context Builder 判断相关；

时加载必要文件。

assets 不自动转成文本上下文。

scripts 不执行。

---

# 123. H3 `raw` 调试处理

`H3PromptPlan.raw` 如果保留：

```text
debug only
```

不要：

- 持久化进每个 Revision；
- 回灌 LLM；
- 用作 Semantic Plan source。

长期可考虑从 Domain Plan 移到 debug result。

---

# 124. ANIMA Natural Body 处理

如果继续保留 `natural_body`：

必须明确其状态：

```text
derived render source
or
creative note
```

不能既被当作完整 Prompt 事实，又同时让 structured fields 独立修改。

一种可行策略：

```text
structured semantic plan
+
creative_notes
↓
renderer synthesizes natural body
```

若 natural body 必须由 LLM 生成，可：

```text
rebuild derived text when authoritative dependencies change
```

但不要把旧 derived text 当不可变状态。

---

# 125. Character Description 处理

类似：

```text
AnimaCharacter.description
```

如果它重复：

```text
required_traits
variable_traits
action
position
```

必须：

- 变成 derived；
- 或拆出 truly free-form `creative_description_notes`。

不要重复事实。

---

# 126. Validator 分层文件

推荐逻辑层次：

```text
validators/
  protocol/
  semantic/
```

不要求强制目录重构，但 API 上要区分：

```text
validate_protocol(plan/render)
validate_semantics(plan)
```

---

# 127. Normalizer 权限

Normalizer 可以修改：

```text
derived ids
ordering
dedupe
timestamps
canonical casing
reference labels
obsolete derived state
```

但是任何 normalizer-generated changes 应加入：

```text
authorized normalization paths
```

让 Diff Guard 能解释，而不是隐藏修改。

---

# 128. Migration 不等于 Repair

Migration：

```text
schema/target/source structure change
```

Repair：

```text
candidate failed validation
```

两者不要混用。

---

# 129. Rebase 不等于 User Refine

Rebase：

```text
upstream source changed
```

User Refine：

```text
latest conversational intent changed
```

RevisionEvent 中标记 source：

```text
user
rebase
migration
restore
repair
```

---

# 130. Session New

`New Session`：

- 创建新 session id；
- current plan 清空；
- revision 从 0 开始；
- 不删除旧 session 数据立即不可恢复，如果实现 history/session archive 可保留；
- 不依赖 `continue_previous=false`。

---

# 131. Studio 与 One-shot 共享 Target Core

One-shot 与 Studio 对同一 target 必须使用同一：

```text
renderer
protocol validator
target-specific rules
```

避免：

```text
PromptComposer output differs because it has separate hard-coded model knowledge
Studio output differs because it has another prompt
```

上层 intent policy 可以不同。

---

# 132. Tests First Where Risky

以下建议先写 failing tests 再改代码：

```text
immutable restore
message nonce no-call
stale CAS
Diff Guard unauthorized field
derived description sync
H3 delete-shot continuity
ZIP path traversal
Skill script non-execution
```

---

# 133. 自测要求

修改 Python 后：

```text
python -m compileall
or targeted py_compile
```

并运行项目测试。

修改 JS：

```text
node --check
```

如果仓库已有 lint/test 命令，优先遵循项目。

不得留下明显无法加载的 Node。

---

# 134. 文档更新

至少更新：

```text
README
node-reference-zh
architecture/decisions docs
skill install docs
migration notes
```

明确：

```text
PromptComposer = one-shot
PromptStudio = persistent
Model Core ≠ External Skill
Plan = truth
Prompt = derived
```

---

# 135. 不要把所有 Phase 强塞进一次大 Commit

如果运行环境允许 git：建议按逻辑 Phase 保持小而清晰的改动。

但不要擅自 push。

除非任务执行环境明确要求提交，否则只完成代码与测试即可。

---

# 136. 最终验收标准

本重构真正完成的标准不是：

```text
UI 里有聊天框
```

而是以下全部成立：

1. Studio 有真正 persistent Semantic Plan；
2. Current Prompt 只是 derived result；
3. 局部修改默认走 ChangeSet；
4. Impact Analysis 能表达依赖与 invalidation；
5. Diff Guard 能拦截无关修改；
6. Semantic Validator 能发现行为/状态问题；
7. Protocol Validator 保持 target correctness；
8. 失败永不污染 stable revision；
9. Restore 不破坏历史；
10. 无新消息不调用 LLM；
11. Stale Queue 不覆盖新 revision；
12. Workflow reload 能恢复；
13. ANIMA 不再依赖双真源 prose；
14. H3 compact context 不回放 raw；
15. Model Core 与 Skill 分离；
16. ZIP Skill 安全安装；
17. External scripts 不自动执行；
18. Style preset + custom style 正确进入 Plan；
19. One-shot nodes 继续可用；
20. H3 Studio 与 Image Studio 共用 Session Engine 但不共用错误的 Universal Plan。

---

# 137. 最后的架构图

```text
                         USER
                          │
                          ▼
                ┌──────────────────┐
                │ Prompt Studio UI │
                └────────┬─────────┘
                         │
                latest instruction
                         │
                         ▼
                ┌──────────────────┐
                │ Session Engine   │
                │ revision/state   │
                └────────┬─────────┘
                         │
                  Current Plan
                         │
                         ▼
                ┌──────────────────┐
                │ Intent Grounding │
                └────────┬─────────┘
                         │
                         ▼
                ┌──────────────────┐
                │ Change Planner   │
                └────────┬─────────┘
                         │
                    ChangeSet
                         │
                         ▼
                ┌──────────────────┐
                │ Impact Analysis  │
                └────────┬─────────┘
                         │
           requested / dependent /
           invalidated / conflicts
                         │
                         ▼
                ┌──────────────────┐
                │ Apply to Clone   │
                └────────┬─────────┘
                         │
             ┌───────────┴───────────┐
             ▼                       ▼
       ┌────────────┐          ┌──────────────┐
       │ Diff Guard │          │ Semantic     │
       │            │          │ Validation   │
       └─────┬──────┘          └──────┬───────┘
             └───────────┬────────────┘
                         ▼
                ┌──────────────────┐
                │ Plan Normalizer  │
                └────────┬─────────┘
                         │
                         ▼
                ┌──────────────────┐
                │ Target Renderer  │
                └────────┬─────────┘
                         │
                         ▼
                ┌──────────────────┐
                │ Protocol Check   │
                └────────┬─────────┘
                         │
                         ▼
                ┌──────────────────┐
                │ Atomic Commit    │
                └────────┬─────────┘
                         │
                         ▼
                    Final Prompt
                         │
                         ▼
                 IMAGE / VIDEO MODEL
                         │
                         ▼
               Generation Observation
                         │
                         └──────→ next feedback
```

One-shot 入口：

```text
PromptComposer / H3 Director
            │
            ▼
       Model Core /
       Plan Adapter
            │
            ▼
      Semantic Plan
            │
            ▼
   Same Renderer/Validator
            │
            ▼
        Final Prompt
```

External guidance：

```text
APS Runtime Policy
        >
Target Model Core
        >
Locked Source Constraints
        >
Latest User Intent
        >
External Skills
        >
Style Presets
        >
Defaults
```

---

# 138. 执行原则总结

始终坚持：

```text
Plan is truth.
Prompt is compiled output.

One semantic fact has one authoritative owner.

Refine uses a ChangeSet, not a full rewrite.

Apply the minimum globally consistent change.

Analyze impact before mutation.

Dependencies and invalidated facts are both first-class.

Diff Guard, Semantic Validator and Protocol Validator are different.

Every mutation is transactional.

Invalid/stale/failed candidates never replace stable state.

Store richly, reason compactly.

Deterministic facts belong in code, not in LLM guesses.

Model Core ≠ External Skill ≠ Style ≠ Session.

One-shot Composer ≠ Stateful Studio.

Code architecture layers do not all need to become ComfyUI nodes.

Compatibility belongs at the boundary, not at the architectural core.
```

---

# 139. 开始执行

现在开始：

1. 先读取当前仓库与测试；
2. 输出一个简短的 current-state audit；
3. 明确哪些现有 Session/Skill 代码与本文冲突；
4. 从 Phase 0 开始实施；
5. 不要先做视觉 UI；
6. 每一阶段完成后运行测试；
7. 如果当前实现已经提前实现了某项功能，必须验证其语义是否满足本文，而不是仅根据名称认为完成；
8. 遇到本文没有明确规定的实现细节，选择最小、可测试、可迁移、与现有 ComfyUI 兼容的方案；
9. 不擅自改变上述核心架构边界。

最终目标不是“多了两个节点”，而是让 APS 成为：

> **一个以 Semantic Plan 为核心、支持事务式多轮编辑、依赖与逻辑一致性维护、模型专属编译、版本控制、安全 Skill Package、艺术风格预设以及真实生成反馈闭环的 Prompt 创作系统。**
