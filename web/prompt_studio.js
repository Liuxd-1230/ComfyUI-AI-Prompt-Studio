// Persistent Prompt Studio UI. Domain state stays in the backend PromptSession;
// this module only renders it and writes the serialized result back to workflow widgets.
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const TARGETS = new Set(["APS_PromptStudio", "APS_H3PromptStudio"]);
const STUDIO_HEIGHT = 438;
const MIN_NODE_WIDTH = 420;
const H3_MODE_HELP = {
  T2VA: "纯文字生成视频｜不接参考图。适合从零描述完整画面、动作、镜头和声音。",
  I2VA: "首帧生成视频｜接 1 张图，作为 0 秒的真实首帧；提示词描述它之后如何运动。",
  FL2VA: "首尾帧生成视频｜接 2 张图，Picture 1 是首帧、Picture 2 是末帧；描述连续过渡。",
  L2VA: "尾帧生成视频｜接 1 张图，作为视频最终帧；提示词设计前序动作并收敛到该图。",
  Ref2VA: "多模态参考生成｜可组合图片、视频、音频来约束人物、风格、动作和声音；不是首尾帧模式。",
};
const byName = (node, name) => (node.widgets || []).find((widget) => widget.name === name);
const newMessageNonce = () => globalThis.crypto?.randomUUID?.()
  || `msg-${Date.now()}-${Math.random().toString(16).slice(2)}`;

function hideSerializedWidget(widget) {
  if (!widget) return;
  widget.hidden = true;
  widget.draw = () => {};
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

function markWorkflowDirty(node) {
  node.graph?.change?.();
  app.graph?.change?.();
  app.extensionManager?.workflow?.activeWorkflow?.changeTracker?.checkState?.();
  app.workflowManager?.activeWorkflow?.changeTracker?.checkState?.();
  node.setDirtyCanvas?.(true, true);
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
    <div class="aps-studio-help" hidden>
      <div><strong>生成模式：</strong><span class="aps-studio-mode-help"></span></div>
      <div><strong>执行方式：</strong>直接维护成品提示词；格式异常时仅自动修复一次，失败保留上一版。</div>
      <div class="aps-studio-legacy-note">旧工作流里的 R2V 等同 Ref2VA；新建工作流统一使用 Ref2VA。</div>
    </div>
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

function renderInlineHelp(node, root) {
  const help = root.querySelector(".aps-studio-help");
  if ((node.comfyClass || node.type) !== "APS_H3PromptStudio") {
    help.hidden = true;
    return;
  }
  help.hidden = false;
  const mode = String(byName(node, "mode")?.value || "T2VA");
  root.querySelector(".aps-studio-mode-help").textContent =
    H3_MODE_HELP[mode] || H3_MODE_HELP.Ref2VA;
}

function watchHelpWidget(node, root, name) {
  const widget = byName(node, name);
  if (!widget) return;
  const previousCallback = widget.callback;
  widget.callback = function updateStudioHelp(value) {
    previousCallback?.apply(this, arguments);
    renderInlineHelp(node, root);
  };
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

async function recoverNewerJournal(node, root) {
  const session = parseSession(node);
  const sessionId = String(session.id || "");
  const nodeInstanceId = String(session.node_instance_id || "");
  if (!sessionId || !nodeInstanceId) return;
  const path = `/ai_prompt_studio/recovery/${encodeURIComponent(sessionId)}`
    + `/${encodeURIComponent(nodeInstanceId)}`;
  try {
    const response = await api.fetchApi(path);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const candidate = await response.json();
    const diskRevision = Number(candidate.result_revision || 0);
    const workflowRevision = Number(session.revision || 0);
    if (!candidate.found || diskRevision <= workflowRevision) return;
    const shouldRecover = globalThis.confirm(
      `Prompt Studio 检测到后端成功版本 v${diskRevision}，工作流仍是 v${workflowRevision}。\n`
      + `Recover v${diskRevision}?（恢复后请保存工作流）`);
    if (!shouldRecover) {
      await api.fetchApi(path, { method: "DELETE" });
      root.querySelector(".aps-studio-summary").textContent =
        `已保留工作流 v${workflowRevision}，并忽略恢复候选 v${diskRevision}。`;
      return;
    }
    const snapshot = candidate.session_snapshot;
    if (!snapshot || snapshot.id !== sessionId
        || Number(snapshot.revision || 0) !== diskRevision) {
      throw new Error("恢复快照身份或 revision 不一致");
    }
    setWidget(node, "prompt_session", JSON.stringify(snapshot, null, 2));
    setWidget(node, "session_action", "continue");
    renderSession(node, root, snapshot);
    root.querySelector(".aps-studio-summary").textContent =
      `已恢复后端成功版本 v${diskRevision}；请保存工作流。`;
    markWorkflowDirty(node);
  } catch (error) {
    const summary = root.querySelector(".aps-studio-summary");
    summary.textContent = `恢复检查失败：${error?.message || error}`;
    summary.classList.add("is-error");
  }
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
  renderInlineHelp(node, root);
  watchHelpWidget(node, root, "mode");

  const previousExecuted = node.onExecuted;
  node.onExecuted = function onExecuted(message) {
    previousExecuted?.apply(this, arguments);
    if (message?.prompt_session?.[0] !== undefined) {
      setWidget(node, "prompt_session", message.prompt_session[0]);
      setWidget(node, "session_action", "continue");
      setWidget(node, "text", "");
      root.querySelector(".aps-studio-input").value = "";
      markWorkflowDirty(node);
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
      renderInlineHelp(node, root);
      recoverNewerJournal(node, root);
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
