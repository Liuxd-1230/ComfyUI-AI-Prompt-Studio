# 设置工作台采用内嵌面板 + 自有服务端路由

「AI Prompt Studio Settings」用菜单按钮打开的内嵌模态面板（vanilla JS 零构建）实现，数据走自有后端路由（`/api/ai_prompt_studio/...`），而不是只注册 ComfyUI 原生 extension settings 项。

原生 settings 机制（`app.registerExtension({settings:[...]})`）能持久化到服务端 `comfy.settings.json`，但做不了工作台级交互：密钥脱敏显示、API 测试按钮、能力探测重跑、runtime 状态、prompt 预览与验证报告。自有路由把这些收进一个界面，且密钥只存在我们自己的 `user/<pkg>/config.json`（原生 settings 会把值原样存进 `comfy.settings.json`，密钥不宜放那里）。

## Consequences

- 需要维护自己的设置路由与前端页面；后续可把「选默认档案」等简单项补注册到原生 settings 提升集成度。
