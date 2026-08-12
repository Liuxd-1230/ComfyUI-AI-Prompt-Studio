// Persistent Prompt Studio UI. Domain state stays in the backend PromptSession;
// this module only renders it and writes the serialized result back to workflow widgets.
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const TARGETS = new Set(["APS_PromptStudio", "APS_H3PromptStudio"]);
const STUDIO_HEIGHT = 390;
const MIN_NODE_WIDTH = 420;
const byName = (node, name) => (node.widgets || []).find((widget) => widget.name === name);
const newMessageNonce = () => globalThis.crypto?.randomUUID?.()
  || `msg-${Date.now()}-${Math.random().toString(16).slice(2)}`;

function hideSerializedWidget(widget) {
  if (!widget) return;
  widget.computeSize = () => [0, -4];
  widget.serializeValue = async () => widget.value;
}

function setWidget(node, name, value) {
  const widget = byName(node, name);
  if (!widget) return;
  widget.value = value;
  widget.callback?.(value, node, widget);
  node.setDirtyCanvas?.(true, true);
  app.graph?.setDirtyCanvas?.(true, true);
}

function parseSession(node) {
  try {
    return JSON.parse(String(byName(node, "prompt_session")?.value || ""));
  } catch (_) {
    return {};
  }
}

function studioElement(node) {
  const root = document.createElement("section");
  root.className = "aps-prompt-studio";
  root.innerHTML = `
    <header><strong>Prompt Studio</strong><span class="aps-studio-revision">v0</span></header>
    <div class="aps-studio-chat" aria-label="会话记录"></div>
    <div class="aps-studio-summary"></div>
    <label>本轮需求 / 修改意见
      <textarea class="aps-studio-input" placeholder="例如：只把第二个镜头改成固定机位，其他内容不变"></textarea>
    </label>
    <label>Current Prompt
      <textarea class="aps-studio-preview" readonly placeholder="成功生成后，这里显示真正传给下游的 Prompt"></textarea>
    </label>
    <div class="aps-studio-actions">
      <button type="button" data-action="previous">恢复上一版为新版本</button>
      <button type="button" data-action="new">新会话</button>
    </div>`;
  const chatInput = root.querySelector(".aps-studio-input");
  chatInput.value = String(byName(node, "text")?.value || "");
  chatInput.oninput = () => {
    setWidget(node, "text", chatInput.value);
    setWidget(node, "message_nonce", newMessageNonce());
  };
  root.querySelector('[data-action="previous"]').onclick = () => {
    const session = parseSession(node);
    if ((session.revisions || []).length < 2) {
      root.querySelector(".aps-studio-summary").textContent =
        "当前会话尚无可恢复的成功版本；请先完成至少两次成功提交。";
      return;
    }
    setWidget(node, "session_action", "previous");
    root.querySelector(".aps-studio-summary").textContent =
      "已选择恢复上一版；执行后会创建新 revision，历史不会删除。";
  };
  root.querySelector('[data-action="new"]').onclick = () => {
    setWidget(node, "session_action", "new");
    chatInput.value = "";
    setWidget(node, "text", "");
    setWidget(node, "message_nonce", "");
    root.querySelector(".aps-studio-summary").textContent =
      "已选择新会话；旧会话会保留到新结果成功提交。填写需求后 Queue。";
  };
  return root;
}

function renderSession(node, root, session = parseSession(node), message = null) {
  const chat = root.querySelector(".aps-studio-chat");
  chat.replaceChildren();
  (session.conversation || []).forEach((entry) => {
    const row = document.createElement("div");
    row.className = `aps-studio-message ${entry.role === "user" ? "is-user" : "is-ai"}`;
    const who = entry.role === "user" ? "你" : "AI";
    row.textContent = `${who}：${entry.content || ""}`;
    chat.append(row);
  });
  root.querySelector(".aps-studio-preview").value =
    message?.current_prompt?.[0] ?? session.current_prompt ?? "";
  root.querySelector(".aps-studio-revision").textContent =
    `v${message?.revision?.[0] ?? session.revision ?? 0}`;
  const summary = root.querySelector(".aps-studio-summary");
  summary.classList.remove("is-error");
  const change = message?.change_summary?.[0] || "";
  const validation = message?.validation?.[0] || "";
  summary.textContent = [change, validation].filter(Boolean).join("\n");
}

function attachStudio(node) {
  ["operation", "text", "prompt_session", "session_action", "continue_previous",
    "message_nonce"].forEach(
    (name) => hideSerializedWidget(byName(node, name)));
  const root = studioElement(node);
  const studioWidget = node.addDOMWidget(
    "prompt_studio_workbench", "PROMPT_STUDIO", root, {
      serialize: false,
      hideOnZoom: false,
      getMinHeight: () => STUDIO_HEIGHT,
      getMaxHeight: () => STUDIO_HEIGHT,
      getHeight: () => STUDIO_HEIGHT,
  });
  studioWidget.computeSize = () => [MIN_NODE_WIDTH, STUDIO_HEIGHT];
  renderSession(node, root);

  const previousExecuted = node.onExecuted;
  node.onExecuted = function onExecuted(message) {
    previousExecuted?.apply(this, arguments);
    if (message?.prompt_session?.[0] !== undefined) {
      setWidget(node, "prompt_session", message.prompt_session[0]);
      setWidget(node, "session_action", "continue");
      setWidget(node, "text", "");
      root.querySelector(".aps-studio-input").value = "";
    }
    renderSession(node, root, parseSession(node), message);
  };
  const previousConfigure = node.onConfigure;
  node.onConfigure = function onConfigure() {
    previousConfigure?.apply(this, arguments);
    setTimeout(() => {
      root.querySelector(".aps-studio-input").value =
        String(byName(node, "text")?.value || "");
      renderSession(node, root);
    }, 0);
  };
  const onExecutionError = ({ detail }) => {
    const failedNode = detail?.node_id ?? detail?.nodeId;
    if (String(failedNode) !== String(node.id)) return;
    const error = detail?.exception_message || detail?.exception_type || "执行失败";
    root.querySelector(".aps-studio-summary").textContent = `本轮失败，上一版保持不变：${error}`;
    root.querySelector(".aps-studio-summary").classList.add("is-error");
  };
  api.addEventListener("execution_error", onExecutionError);
  const previousRemoved = node.onRemoved;
  node.onRemoved = function onRemoved() {
    api.removeEventListener("execution_error", onExecutionError);
    previousRemoved?.apply(this, arguments);
  };
  const [computedWidth = MIN_NODE_WIDTH, computedHeight = 0] =
    node.computeSize?.() || [];
  node.setSize?.([
    Math.max(node.size?.[0] || 0, computedWidth, MIN_NODE_WIDTH),
    Math.max(computedHeight, STUDIO_HEIGHT + 120),
  ]);
}

app.registerExtension({
  name: "AI Prompt Studio Persistent Sessions",
  nodeCreated(node) {
    if (TARGETS.has(node.comfyClass || node.type) && !byName(node, "prompt_studio_workbench")) {
      attachStudio(node);
    }
  },
});
