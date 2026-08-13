// Persistent Prompt Studio UI. Domain state stays in the backend PromptSession;
// this module only renders it and writes the serialized result back to workflow widgets.
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { cachedJson } from "./data_cache.js";

const TARGETS = new Set(["APS_PromptStudio", "APS_H3PromptStudio"]);
const UI_CONTRACT_VERSION = "single-lane-ui-v2";
const STUDIO_HEIGHT = 320;
const STUDIO_EXPANDED_HEIGHT = 410;
const MIN_NODE_WIDTH = 420;
const INPUT_DEBOUNCE_MS = 200;
const VISIBLE_HISTORY_ITEMS = 6;
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

function setWidget(node, name, value, redraw = true) {
  const widget = byName(node, name);
  if (!widget) return;
  if (widget.value === value) return;
  widget.value = value;
  widget.callback?.(value, node, widget);
  if (redraw) node.setDirtyCanvas?.(true, true);
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
    <header><strong>提示词工作台</strong><span><span class="aps-studio-state">就绪</span> <span class="aps-studio-revision">v0</span></span></header>
    <div class="aps-studio-contract" role="alert" hidden></div>
    <details class="aps-studio-help" hidden>
      <summary>H3 模式说明</summary>
      <div><strong>生成模式：</strong><span class="aps-studio-mode-help"></span></div>
      <div><strong>执行方式：</strong>直接维护成品提示词；格式异常时仅自动修复一次，失败保留上一版。</div>
      <div class="aps-studio-legacy-note">旧工作流里的 R2V 等同 Ref2VA；新建工作流统一使用 Ref2VA。</div>
    </details>
    <div class="aps-studio-summary" role="status" aria-live="polite"></div>
    <label>本轮需求 / 修改意见
      <textarea class="aps-studio-input" placeholder="例如：只把第二个镜头改成固定机位，其他内容不变"></textarea>
    </label>
    <details class="aps-studio-output" open>
      <summary><span>当前提示词</span><button type="button" data-action="copy">复制</button></summary>
      <textarea class="aps-studio-preview" readonly aria-label="当前提示词" placeholder="成功生成后，这里显示真正传给下游的 Prompt"></textarea>
    </details>
    <details class="aps-studio-history"><summary>会话记录 <span></span></summary><div class="aps-studio-chat"></div></details>
    <div class="aps-studio-actions">
      <button type="button" data-action="previous">恢复上一版为新版本</button>
      <button type="button" data-action="new">新会话</button>
    </div>`;
  const chatInput = root.querySelector(".aps-studio-input");
  chatInput.value = String(byName(node, "text")?.value || "");
  let inputTimer = null;
  let lastSyncedValue = chatInput.value;
  const flushInput = () => {
    if (inputTimer) clearTimeout(inputTimer);
    inputTimer = null;
    if (chatInput.value === lastSyncedValue) return;
    lastSyncedValue = chatInput.value;
    const textWidget = byName(node, "text");
    if (textWidget) textWidget.callback?.(chatInput.value, node, textWidget);
    setWidget(node, "message_nonce", newMessageNonce(), false);
    node.graph?.change?.();
    node.setDirtyCanvas?.(true, false);
  };
  chatInput.oninput = () => {
    const textWidget = byName(node, "text");
    if (textWidget) textWidget.value = chatInput.value;
    if (inputTimer) clearTimeout(inputTimer);
    inputTimer = setTimeout(flushInput, INPUT_DEBOUNCE_MS);
  };
  chatInput.onblur = flushInput;
  root._flushInput = flushInput;
  root._resetInput = (value = "") => {
    if (inputTimer) clearTimeout(inputTimer);
    inputTimer = null;
    chatInput.value = value;
    lastSyncedValue = value;
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
    root._flushInput?.();
    setWidget(node, "session_action", "new");
    root._resetInput?.("");
    setWidget(node, "text", "");
    setWidget(node, "message_nonce", "");
    root.querySelector(".aps-studio-summary").textContent =
      "已选择新会话；旧会话会保留到新结果成功提交。填写需求后 Queue。";
  };
  root.querySelector('[data-action="copy"]').onclick = async (event) => {
    event.preventDefault();
    const value = root.querySelector(".aps-studio-preview").value;
    if (!value) return;
    try {
      await globalThis.navigator?.clipboard?.writeText(value);
      root.querySelector(".aps-studio-summary").textContent = "已复制当前提示词。";
    } catch (_) {
      root.querySelector(".aps-studio-preview").select();
      root.querySelector(".aps-studio-summary").textContent = "已选中提示词，请按 Ctrl+C 复制。";
    }
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

function setStudioHeight(node, widget, expanded) {
  const height = expanded ? STUDIO_EXPANDED_HEIGHT : STUDIO_HEIGHT;
  widget._apsHeight = height;
  const computed = node.computeSize?.() || [MIN_NODE_WIDTH, 0];
  node.setSize?.([
    Math.max(computed[0] || MIN_NODE_WIDTH, MIN_NODE_WIDTH),
    Math.max(height + 112, computed[1] || 0),
  ]);
  node.setDirtyCanvas?.(true, true);
}

async function verifyUiContract(node, root) {
  const warning = root.querySelector(".aps-studio-contract");
  try {
    const status = await cachedJson("/ai_prompt_studio/status", { ttlMs: 5000 });
    if (status.ui_contract_version !== UI_CONTRACT_VERSION) {
      warning.hidden = false;
      warning.textContent = "AI Prompt Studio 前后端版本不一致。请重启 ComfyUI 后再执行此节点。";
      root.classList.add("is-contract-mismatch");
      root.querySelector(".aps-studio-state").textContent = "需重启";
      root.querySelectorAll(".aps-studio-input, .aps-studio-actions button").forEach((item) => {
        item.disabled = true;
      });
      return false;
    }
    warning.hidden = true;
    root.classList.remove("is-contract-mismatch");
    root.querySelector(".aps-studio-state").textContent = "就绪";
    root.querySelectorAll(".aps-studio-input, .aps-studio-actions button").forEach((item) => {
      item.disabled = false;
    });
    return true;
  } catch (error) {
    warning.hidden = false;
    warning.textContent = `无法确认前后端版本：${error?.message || error}`;
    root.querySelector(".aps-studio-state").textContent = "未连接";
    return false;
  }
}

function renderSession(node, root, session = parseSession(node), message = null) {
  const chat = root.querySelector(".aps-studio-chat");
  chat.replaceChildren();
  const conversation = session.conversation || [];
  const visible = conversation.slice(-VISIBLE_HISTORY_ITEMS);
  visible.forEach((entry) => {
    const row = document.createElement("div");
    row.className = `aps-studio-message ${entry.role === "user" ? "is-user" : "is-ai"}`;
    const who = entry.role === "user" ? "你" : "AI";
    row.textContent = `${who}：${entry.content || ""}`;
    chat.append(row);
  });
  const historyCount = root.querySelector(".aps-studio-history summary span");
  historyCount.textContent = conversation.length ? `（${conversation.length}）` : "";
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
  let studioWidget = null;
  studioWidget = node.addDOMWidget(
    "prompt_studio_workbench", "PROMPT_STUDIO", root, {
      serialize: false,
      hideOnZoom: false,
      getMinHeight: () => STUDIO_HEIGHT,
      getMaxHeight: () => studioWidget?._apsHeight || STUDIO_HEIGHT,
      getHeight: () => studioWidget?._apsHeight || STUDIO_HEIGHT,
  });
  studioWidget._apsHeight = STUDIO_HEIGHT;
  studioWidget.computeSize = () => [MIN_NODE_WIDTH, studioWidget._apsHeight];
  renderSession(node, root);
  renderInlineHelp(node, root);
  watchHelpWidget(node, root, "mode");
  root.querySelectorAll("details").forEach((details) => {
    details.addEventListener("toggle", () => {
      const expanded = [...root.querySelectorAll("details")].some((item) =>
        item.open && (item.classList.contains("aps-studio-history")
          || item.classList.contains("aps-studio-help")));
      setStudioHeight(node, studioWidget, expanded);
    });
  });
  verifyUiContract(node, root);

  const previousExecuted = node.onExecuted;
  node.onExecuted = function onExecuted(message) {
    root._flushInput?.();
    previousExecuted?.apply(this, arguments);
    if (message?.prompt_session?.[0] !== undefined) {
      setWidget(node, "prompt_session", message.prompt_session[0]);
      setWidget(node, "session_action", "continue");
      setWidget(node, "text", "");
      root._resetInput?.("");
      markWorkflowDirty(node);
    }
    renderSession(node, root, parseSession(node), message);
  };
  const previousConfigure = node.onConfigure;
  node.onConfigure = function onConfigure() {
    previousConfigure?.apply(this, arguments);
    setTimeout(() => {
      root._resetInput?.(String(byName(node, "text")?.value || ""));
      renderSession(node, root);
      renderInlineHelp(node, root);
      verifyUiContract(node, root);
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
    Math.max(computedHeight, STUDIO_HEIGHT + 112),
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
