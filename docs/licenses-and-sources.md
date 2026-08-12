# 参考来源与许可证边界 licenses-and-sources.md

## 本项目许可证

- 本项目使用 **MIT License**（见根目录 LICENSE）。

## 参考项目与使用边界

| 参考项目 | 仓库 | 关系 | 使用边界 |
|---|---|---|---|
| PromptForge | https://github.com/Liuxd-1230/PromptForge | 能力对标（覆盖并改进） | 优先**独立重构**，不复制代码；不继承其旧接口与重复逻辑。用户即该仓库作者，但本仓库仍保持独立实现。 |
| ComfyUI-Prompt-Assistant | https://github.com/yawiii/ComfyUI-Prompt-Assistant | **GPL** 项目 | 只参考架构与行为，**不复制任何代码进入 MIT 项目**。 |
| TE_MAN | https://github.com/tl2012tl/TE_MAN | 受限代码（编译 .pyd） | 只参考其能力清单，**不得复制受限代码或二进制实现**。 |
| DaSiWa（可访问实现） | https://github.com/darksidewalker/ComfyUI-DaSiWa-Nodes | **GPL-3.0** | 只对照官方规范研究结构（导演/构建器拆分、自动对齐行、硬上限校验），**不复制源码/工作流 JSON**。 |
| MiniMax-H3 官方仓库 | https://github.com/MiniMax-AI/MiniMax-H3 | 官方真源 | `skills/h3-prompt-writing/references/base-en.txt` 与 `ref-en.txt` 与本地官方 PDF 手册互为印证；格式以本地 PDF 为准。 |
| ANIMA_BOOSTER | https://github.com/BlackSnowSkill/ANIMA_BOOSTER | 松耦合兼容 | 只做节点存在性软检测，**不复制内部实现**（JIT/TeaCache/采样逻辑）；官方提示词指导以 Civitai 官方模型卡为准。 |
| ComfyUI 核心 | https://github.com/comfyanonymous/ComfyUI | 运行平台 | 只通过公开扩展接口交互（NODE_CLASS_MAPPINGS / WEB_DIRECTORY / PromptServer.instance.routes / app.registerExtension），**不修改核心源码**。 |

## 官方 API/文档来源

- DeepSeek API 文档：https://api-docs.deepseek.com （models、responses、chat-completions、error-codes、pricing）
- ANIMA 官方模型卡：https://civitai.com/models/2458426 （CircleStone Labs）
- Ollama API：https://docs.ollama.com/api
- llama.cpp server README：https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- LM Studio REST API：https://lmstudio.ai/docs/developer/rest
- ComfyUI 文档：https://docs.comfy.org

## 版权文档副本（不提交）

- `docs/sources/minimax_h3_FL2V手册.html`、`docs/sources/minimax_h3_r2v手册.html` 是 MiniMax 官方手册的本地副本，仅用于格式真源参照；**已加入 .gitignore，不进入版本库**。格式规则已提炼进 Model Core、renderer/validator，不将手册全文塞入请求。
