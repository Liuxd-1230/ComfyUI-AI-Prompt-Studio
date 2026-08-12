// Compact Advanced selector for Prompt Supplement workflow IDs.
// Markdown content and policy stay server-side; workflows serialize IDs only.
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const TARGETS = new Set([
  "APS_LLMGenerate",
  "APS_ReferenceAnalyzer",
  "APS_StoryboardBuilder",
  "APS_PromptStudio",
  "APS_H3PromptStudio",
]);
const IMAGE_FAMILIES = {
  anima_base: "anima",
  anima_aesthetic: "anima",
  anima_turbo: "anima",
  z_image_turbo: "z_image",
  qwen_image_edit_2511: "qwen_image_edit",
  generic_image: "generic_image",
};
const NODE_CONTEXT = {
  APS_LLMGenerate: { family: "generic_llm", nodeId: "llm.generate", auto: false },
  APS_ReferenceAnalyzer: {
    family: "reference_analyzer", nodeId: "reference.analyzer", auto: true,
  },
  APS_StoryboardBuilder: {
    family: "storyboard", nodeId: "storyboard.create", auto: true,
  },
  APS_H3PromptStudio: { family: "minimax_h3", nodeId: null, auto: true },
};
const byName = (node, name) => (node.widgets || []).find((item) => item.name === name);

function nodeContext(node) {
  const type = node.comfyClass || node.type;
  if (type === "APS_PromptStudio") {
    return {
      family: IMAGE_FAMILIES[String(byName(node, "target")?.value || "")] || "generic_image",
      nodeId: String(node.id ?? ""),
      auto: true,
    };
  }
  const fixed = NODE_CONTEXT[type] || { family: "", nodeId: "", auto: true };
  return { ...fixed, nodeId: fixed.nodeId ?? String(node.id ?? "") };
}

function hideSerializedWidget(widget) {
  widget.hidden = true;
  widget.draw = () => {};
  widget.computeSize = () => [0, -4];
  widget.serializeValue = async () => widget.value;
}

function selectedIds(widget) {
  const raw = String(widget.value || "").trim();
  if (!raw || raw.toLowerCase() === "auto") return new Set();
  return new Set(raw.split(",").map((item) => item.trim()).filter(Boolean));
}

function isApplicable(record, context) {
  if (record.scope === "global") return true;
  if (record.scope === "node") return (record.node_ids || []).includes(context.nodeId);
  return !(record.target_families || []).length
    || record.target_families.includes(context.family);
}

function markChanged(node, widget, value) {
  widget.value = value;
  widget.callback?.(value, node, widget);
  node.graph?.change?.();
  app.graph?.change?.();
  node.setDirtyCanvas?.(true, true);
}

function statusText(widget, records) {
  const raw = String(widget.value || "").trim();
  if (!raw) return "未使用";
  if (raw.toLowerCase() === "auto") return "自动选择适用资料";
  const known = new Map(records.map((item) => [item.supplement_id, item]));
  const ids = [...selectedIds(widget)];
  const missing = ids.filter((id) => !known.has(id));
  return missing.length
    ? `已选 ${ids.length} 项 · ${missing.length} 项缺失`
    : `已选 ${ids.length} 项`;
}

function buildPicker(node, widget) {
  const root = document.createElement("details");
  root.className = "aps-supplement-picker";
  root.innerHTML = `
    <summary>高级设置 · Prompt Supplements <span>未使用</span></summary>
    <div class="aps-supplement-picker-body">
      <p>Markdown 只作为低优先级参考；工作流仅保存资料 ID。</p>
      <div class="aps-supplement-picker-options">正在加载…</div>
      <button type="button" data-action="retry" hidden>重新加载</button>
    </div>`;
  const summaryStatus = root.querySelector("summary span");
  const options = root.querySelector(".aps-supplement-picker-options");
  const retry = root.querySelector('[data-action="retry"]');
  let records = [];
  let expanded = false;

  const render = () => {
    const context = nodeContext(node);
    const chosen = selectedIds(widget);
    const raw = String(widget.value || "").trim().toLowerCase();
    options.replaceChildren();

    if (context.auto) {
      const label = document.createElement("label");
      label.className = "aps-supplement-option is-auto";
      label.innerHTML = `<input type="radio" name="aps-supplement-${node.id}" value="auto">
        <span><strong>自动</strong><small>加载所有适用于当前节点/目标的已启用资料</small></span>`;
      const input = label.querySelector("input");
      input.checked = raw === "auto";
      input.onchange = () => { markChanged(node, widget, "auto"); render(); };
      options.append(label);
    }

    const none = document.createElement("label");
    none.className = "aps-supplement-option";
    none.innerHTML = `<input type="radio" name="aps-supplement-${node.id}" value="">
      <span><strong>不使用</strong><small>不向本节点加载 Markdown 资料</small></span>`;
    const noneInput = none.querySelector("input");
    noneInput.checked = !raw;
    noneInput.onchange = () => { markChanged(node, widget, ""); render(); };
    options.append(none);

    for (const record of records) {
      const applicable = isApplicable(record, context);
      const enabled = Boolean(record.enabled);
      const label = document.createElement("label");
      label.className = "aps-supplement-option" + (!enabled || !applicable ? " is-disabled" : "");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = chosen.has(record.supplement_id);
      checkbox.disabled = !enabled || !applicable;
      const copy = document.createElement("span");
      const reason = !enabled ? "已停用" : !applicable ? "不适用于当前节点/目标" : record.description || record.scope;
      copy.innerHTML = `<strong></strong><small></small>`;
      copy.querySelector("strong").textContent = record.title || record.supplement_id;
      copy.querySelector("small").textContent = `${record.supplement_id} · ${reason}`;
      checkbox.onchange = () => {
        const next = selectedIds(widget);
        if (checkbox.checked) next.add(record.supplement_id);
        else next.delete(record.supplement_id);
        markChanged(node, widget, [...next].join(","));
        render();
      };
      label.append(checkbox, copy);
      options.append(label);
    }

    for (const id of [...chosen].filter((item) => !records.some((record) => record.supplement_id === item))) {
      const missing = document.createElement("div");
      missing.className = "aps-supplement-option is-missing";
      missing.textContent = `${id} · 资料已删除或注册表中不存在`;
      options.append(missing);
    }
    summaryStatus.textContent = statusText(widget, records);
  };

  const load = async () => {
    options.textContent = "正在加载…";
    options.classList.remove("is-error");
    retry.hidden = true;
    try {
      const response = await api.fetchApi("/ai_prompt_studio/supplements");
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      records = Array.isArray(payload.supplements) ? payload.supplements : [];
      render();
    } catch (error) {
      options.textContent = `加载失败：${error?.message || error}`;
      options.classList.add("is-error");
      retry.hidden = false;
    }
  };
  retry.onclick = load;
  root.addEventListener("toggle", () => {
    if (root.open !== expanded) {
      const delta = root.open ? 180 : -180;
      expanded = root.open;
      node.setSize?.([node.size?.[0] || 320, Math.max(80, (node.size?.[1] || 80) + delta)]);
    }
    node.setDirtyCanvas?.(true, true);
  });
  return { root, load, render };
}

function attachPicker(node) {
  const widget = byName(node, "prompt_supplements");
  if (!widget) return;
  hideSerializedWidget(widget);
  const picker = buildPicker(node, widget);
  const domWidget = node.addDOMWidget(
    "prompt_supplement_picker", "PROMPT_SUPPLEMENTS", picker.root,
    { serialize: false, hideOnZoom: false });
  domWidget.computeSize = () => [Math.max(node.size?.[0] || 320, 320), picker.root.open ? 214 : 34];

  const target = byName(node, "target");
  if (target) {
    const previous = target.callback;
    target.callback = function refreshSupplementScope() {
      previous?.apply(this, arguments);
      picker.render();
    };
  }
  const previousConfigure = node.onConfigure;
  node.onConfigure = function configureSupplementPicker() {
    previousConfigure?.apply(this, arguments);
    setTimeout(picker.render, 0);
  };
  picker.load();
}

app.registerExtension({
  name: "AI Prompt Studio Supplement Picker",
  nodeCreated(node) {
    if (TARGETS.has(node.comfyClass || node.type)
        && !byName(node, "prompt_supplement_picker")) attachPicker(node);
  },
});
