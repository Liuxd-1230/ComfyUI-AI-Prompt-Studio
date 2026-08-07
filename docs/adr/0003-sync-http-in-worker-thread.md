# Gateway 用同步 requests + SSE 解析，节点在 ComfyUI 工作线程内执行

LLM 调用使用 `requests` 同步阻塞式 HTTP，在 ComfyUI 的节点工作线程内执行，SSE 流式边收边解析；取消通过共享 `stop_event` 轮询。

ComfyUI 的节点执行本身是同步的（graph 在独立线程中运行），事件循环线程只做前端服务。aiohttp 异步方案要跨线程桥接 `asyncio.run_coroutine_threadsafe`，出错面大。同步方案简单、可注入 HTTP 客户端做单元测试，代价是节点执行期间该工作线程被占（ComfyUI 已有并行度限制，行为一致）。

## Consequences

- 长生成期间其它依赖同线程的节点会等待；可用 ComfyUI 原生中断（stop_event）退出，避免卡死。
