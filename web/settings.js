// AI Prompt Studio 设置工作台 —— ComfyUI 内嵌面板
// 界面固定中文；字段说明用 title 属性。
// 入口：ComfyUI 菜单（左上角 Logo 下拉）里的「AI Prompt Studio 设置工作台」，
// 也可从原生 Settings 的 AI Prompt Studio 分区打开。
import { app } from "../../scripts/app.js";
import { el, api, toast, maskDisplay } from "./profile_widgets.js";
import { cachedJson } from "./data_cache.js";

const WORKBENCH_COMMAND = "ai.promptstudio.openWorkbench";

const PROVIDERS = ["deepseek", "openai_compatible", "local"];
const PROTOCOLS = ["auto", "responses", "chat_completions"];
const REASONING = ["off", "low", "medium", "high"];
const WEB_SEARCH = ["off", "auto", "always"];
const UNLOAD = ["never", "after_request", "after_success"];

let panel = null;
let currentProfileId = "";
let defaultProfileId = "";
let profileRecords = [];
let activePanelTab = "profiles";
let panelReturnFocus = null;
let workbenchAutoOpened = false;

const STYLE_ID = "aps-settings-styles";

function ensureStylesheet() {
  if (document.getElementById(STYLE_ID)) return;
  const link = document.createElement("link");
  link.id = STYLE_ID;
  link.rel = "stylesheet";
  link.href = new URL("./styles.css", import.meta.url).href;
  document.head.appendChild(link);
}

function fieldLabel(label, tooltip) {
  return el("label", { title: tooltip || label }, [label]);
}

function inputRow(label, input, tooltip) {
  const row = el("div", { class: "aps-field" });
  row.appendChild(fieldLabel(label, tooltip));
  row.appendChild(input);
  return row;
}

function textInput(value, placeholder) {
  return el("input", { type: "text", value: value || "", placeholder: placeholder || "" });
}

function numberInput(value, placeholder, min, max, step) {
  return el("input", {
    type: "number", value: value != null ? String(value) : "",
    placeholder: placeholder || "", min, max, step: step || "any",
  });
}

// 与 schemas/profile.py::AIProfile.validate 保持同一套区间；改一边必须改另一边。
const NUMBER_RULES = [
  ["超时(秒)", 1, 600, 1],
  ["温度", 0, 2, "any"],
  ["Top P", 0, 1, "any"],
  ["频率惩罚", -2, 2, "any"],
  ["存在惩罚", -2, 2, "any"],
  ["最大输出 tokens", 1, 1000000, 1],
];

function numberProblems(controls) {
  const problems = [];
  for (const [label, lo, hi] of NUMBER_RULES) {
    const raw = controls[label].value.trim();
    if (raw === "") continue;
    const value = Number(raw);
    if (!Number.isFinite(value)) problems.push(`${label} 不是数字`);
    else if (value < lo || value > hi) problems.push(`${label} 必须在 ${lo}..${hi}`);
  }
  return problems;
}

function autocompleteInput(value, placeholder, values, idPrefix) {
  const id = `${idPrefix}-${Math.random().toString(36).slice(2)}`;
  const input = el("input", {
    type: "text", value: value || "", placeholder: placeholder || "", list: id,
  });
  const datalist = el("datalist", { id });
  for (const option of [...new Set((values || []).filter(Boolean))]) {
    datalist.appendChild(el("option", { value: option }));
  }
  return { input, datalist };
}

function selectInput(options, value) {
  const sel = el("select", {});
  for (const opt of options) {
    sel.appendChild(el("option", { value: opt, text: opt }));
  }
  sel.value = value || options[0];
  return sel;
}

function checkboxInput(checked, tooltip) {
  return el("input", { type: "checkbox", checked: !!checked, title: tooltip || "" });
}

function parseOptFloat(value) {
  const v = (value || "").trim();
  if (v === "") return null;
  const n = parseFloat(v);
  return isNaN(n) ? null : n;
}

// ---------------- 面板构建 ----------------

function openPanel() {
  ensureStylesheet();
  // 热重载/重复执行保护：复用已存在的 overlay（唯一 id），避免重复面板
  panel = panel || document.getElementById("aps-overlay");
  if (!panel) {
    panel = buildPanel();
    document.body.appendChild(panel);
  }
  panelReturnFocus = document.activeElement;
  panel.style.display = "flex";
  panel.setAttribute("aria-hidden", "false");
  showPanelTab(activePanelTab);
  panel.querySelector("[data-aps-tab].is-active")?.focus();
}

function closePanel() {
  if (panel) {
    panel.style.display = "none";
    panel.setAttribute("aria-hidden", "true");
  }
  panelReturnFocus?.focus?.();
}

// 原生设置面板只支持声明式的行，没有「某个分类对应一整页」的概念，
// 所以进入 AI Prompt Studio 分类时由这一行自己把工作台弹出来。
// 每次设置页会话只自动弹一次：这一行离开 DOM（关闭设置或切走分类）后才重新计。
function armWorkbenchAutoOpen(row) {
  if (workbenchAutoOpened) return;
  workbenchAutoOpened = true;
  const watcher = new MutationObserver(() => {
    if (!document.body.contains(row)) {
      workbenchAutoOpened = false;
      watcher.disconnect();
    }
  });
  watcher.observe(document.body, { childList: true });
  setTimeout(openPanel, 0);
}

function buildPanel() {
  const overlay = el("div", {
    class: "aps-overlay", role: "dialog", "aria-modal": "true",
    "aria-labelledby": "aps-settings-title", "aria-hidden": "true",
  });
  overlay.id = "aps-overlay";
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closePanel();
  });
  const body = el("div", { class: "aps-panel", tabindex: "-1" });
  overlay.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      // 原生 Settings 的 Escape 监听挂在 document 上：不截断的话，
      // 从设置页里打开工作台后按一次 Esc 会把整个设置页一起关掉。
      event.preventDefault();
      event.stopPropagation();
      closePanel();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [...overlay.querySelectorAll(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex="0"]')]
      .filter((item) => item.offsetParent !== null);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first.focus();
    }
  });

  // header
  const header = el("div", { class: "aps-header" }, [
    el("h2", { id: "aps-settings-title", text: "AI Prompt Studio 设置" }),
    el("button", { class: "aps-btn aps-btn-close", text: "✕", title: "关闭", onClick: closePanel }),
  ]);
  body.appendChild(header);

  // status line
  const statusLine = el("div", { class: "aps-status-line", id: "aps-status-line" });
  body.appendChild(statusLine);

  const tabs = el("div", { class: "aps-tabs", role: "tablist", "aria-label": "设置分区" });
  for (const [id, label] of [
    ["profiles", "模型档案"], ["capabilities", "能力与连接"],
    ["resources", "Markdown 资料与日志"],
  ]) {
    tabs.appendChild(el("button", {
      class: "aps-tab", text: label, role: "tab", "data-aps-tab": id,
      "aria-controls": `aps-pane-${id}`, onClick: () => showPanelTab(id),
    }));
  }
  body.appendChild(tabs);

  const profilesPane = el("section", { class: "aps-tab-pane", id: "aps-pane-profiles", role: "tabpanel" });
  profilesPane.appendChild(el("section", { class: "aps-guide" }, [
    el("h3", { text: "LM Studio 自动卸载怎么连接" }),
    el("p", { text: "把节点串在提示词生成和图像/视频生成之间：" }),
    el("code", { text: "LLM 提示词输出 → LLM 后卸载 LM Studio（提示词透传） → 图像/视频节点的 prompt" }),
    el("p", { text: "model 填 LM Studio 的模型 key（例如 openai/gpt-oss-20b）；本机服务的 url 通常留空即可。" }),
    el("p", { text: "不知道有哪些 key：填好 API URL 后点模型行的「拉取模型」，不必先保存档案就能列出上游目录。" }),
  ]));

  // two columns: profiles list + editor
  const cols = el("div", { class: "aps-cols" });
  const left = el("div", { class: "aps-col aps-col-list" }, [el("h3", { text: "档案" }), el("div", { id: "aps-profile-list" })]);
  const right = el("div", { class: "aps-col aps-col-editor" }, [el("div", { id: "aps-editor" }, [el("p", { class: "aps-muted", text: "选择档案开始配置" })])]);
  cols.appendChild(left);
  cols.appendChild(right);
  profilesPane.appendChild(cols);
  body.appendChild(profilesPane);

  const capabilityPane = el("section", { class: "aps-tab-pane", id: "aps-pane-capabilities", role: "tabpanel" }, [
    el("div", { class: "aps-section" }, [
    el("h3", { text: "能力状态" }),
    el("div", { id: "aps-capabilities" }),
  ])]);
  const resourcesPane = el("section", { class: "aps-tab-pane", id: "aps-pane-resources", role: "tabpanel" }, [
    el("div", { class: "aps-section" }, [
    el("h3", { text: "请求日志" }),
    el("div", { id: "aps-log" }),
  ]), el("div", { class: "aps-section" }, [
    el("h3", { text: "Markdown 补充资料" }),
    el("div", { id: "aps-supplements" }),
  ])]);
  body.append(capabilityPane, resourcesPane);
  overlay.appendChild(body);
  return overlay;
}

// ---------------- 数据刷新 ----------------

// 同一块区域只接受最后一次请求的结果：快速切换档案或标签时，
// 先发出去但后回来的响应不能把新状态盖掉。
let profilesSeq = 0;
let editorSeq = 0;
let capabilitiesSeq = 0;

async function refreshAll() {
  await showPanelTab(activePanelTab);
}

async function loadProfilesPane() {
  const seq = ++profilesSeq;
  try {
    const [status, list] = await Promise.all([
      cachedJson("/ai_prompt_studio/status", { ttlMs: 5000 }),
      cachedJson("/ai_prompt_studio/profiles"),
    ]);
    if (seq !== profilesSeq) return;
    renderStatus(status);
    renderProfiles(list);
    if (currentProfileId) renderEditor(currentProfileId);
  } catch (error) {
    if (seq !== profilesSeq) return;
    toast("错误: " + error.message, true);
  }
}

function showPanelTab(tabId) {
  activePanelTab = tabId;
  if (!panel) return;
  for (const button of panel.querySelectorAll("[data-aps-tab]")) {
    const selected = button.dataset.apsTab === tabId;
    button.classList.toggle("is-active", selected);
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  }
  for (const pane of panel.querySelectorAll(".aps-tab-pane")) {
    pane.hidden = pane.id !== `aps-pane-${tabId}`;
  }
  if (tabId === "profiles") return loadProfilesPane();
  if (tabId === "capabilities") return renderCapabilities();
  if (tabId === "resources") {
    renderLog();
    renderSupplements();
  }
  return undefined;
}

function renderStatus(info) {
  const line = document.querySelector("#aps-status-line");
  if (!line) return;
  line.textContent = `v${info.version || "?"}` +
    (info.comfyui_version ? ` · ComfyUI ${info.comfyui_version}` : "") +
    ` · ${info.profile_count} 个档案` +
    (info.anima_booster_detected ? " · ANIMA_BOOSTER 已检测" : "");
}

function renderProfiles({ profiles, default_profile_id }) {
  profileRecords = profiles || [];
  defaultProfileId = default_profile_id || "";
  const box = document.querySelector("#aps-profile-list");
  if (!box) return;
  box.innerHTML = "";
  if (!profiles.length) {
    box.appendChild(el("p", { class: "aps-muted", text: "档案" + ": —" }));
  }
  for (const p of profiles) {
    const row = el("div", {
      class: "aps-profile-row" + (p.profile_id === currentProfileId ? " aps-selected" : ""),
      onClick: () => {
        currentProfileId = p.profile_id;
        renderProfiles({ profiles, default_profile_id });
        renderEditor(p.profile_id);   // 档案取回后顺带刷新能力区，不再重复请求
      },
    });
    const title = el("div", { class: "aps-profile-title" }, [
      el("strong", { text: p.name || p.profile_id }),
      p.profile_id === default_profile_id ? el("span", { class: "aps-badge", text: "默认" }) : null,
    ]);
    const meta = el("div", { class: "aps-profile-meta", text: `${p.provider} · ${p.model || ""} · key ${maskDisplay(p.api_key_masked)}` });
    row.appendChild(title);
    row.appendChild(meta);
    box.appendChild(row);
  }
  box.appendChild(el("button", { class: "aps-btn aps-btn-primary", text: "+ 新建档案", onClick: () => {
    currentProfileId = "";
    renderEditor("");
    renderCapabilities();
  } }));
}

function renderEditor(profileId) {
  const box = document.querySelector("#aps-editor");
  if (!box) return;
  const seq = ++editorSeq;
  if (!profileId) {
    box.innerHTML = "";
    box.appendChild(buildEditorForm(null));
    return;
  }
  api("/profiles/" + encodeURIComponent(profileId))
    .then((p) => {
      if (seq !== editorSeq || currentProfileId !== profileId) return;
      box.innerHTML = "";
      box.appendChild(buildEditorForm(p));
      renderCapabilities(p);
    })
    .catch((e) => {
      if (seq === editorSeq) toast("错误: " + e.message, true);
    });
}

function buildEditorForm(p) {
  const wrap = el("div", {});
  const isNew = !p;
  p = p || {};

  const name = textInput(p.name, "档案名称");
  const provider = selectInput(PROVIDERS, p.provider);
  const baseUrl = textInput(p.base_url, "https://api.deepseek.com");
  const knownModels = [...(p.capabilities?.models || [])];
  if (p.model) knownModels.unshift(p.model);
  const modelChoice = autocompleteInput(p.model, "输入或从探测结果选择模型", knownModels, "aps-models");
  const model = modelChoice.input;
  const protocol = selectInput(PROTOCOLS, p.protocol);
  const reasoning = selectInput(REASONING, p.reasoning);
  const webSearch = selectInput(WEB_SEARCH, p.web_search);
  const unload = selectInput(UNLOAD, p.unload_policy);
  const visionUrl = textInput(p.vision_base_url, "");
  const knownVisionModels = [...(p.capabilities?.vision_models || []), ...knownModels];
  const visionChoice = autocompleteInput(p.vision_model, "输入或从探测结果选择视觉模型", knownVisionModels, "aps-vision-models");
  const visionModel = visionChoice.input;
  const visionProfileId = selectInput(
    ["", ...profileRecords.map((record) => record.profile_id).filter((id) => id && id !== p.profile_id)],
    p.vision_profile_id,
  );
  const visionLinkNote = el("small", { class: "aps-muted" });
  const syncVisionSource = () => {
    const linked = !!visionProfileId.value;
    visionUrl.disabled = linked;
    visionModel.disabled = linked;
    visionLinkNote.textContent = linked
      ? `Reference Analyzer 将使用关联档案 ${visionProfileId.value} 的主 API URL、主模型和密钥；上面两个视觉字段已停用。`
      : "未关联视觉档案：Reference Analyzer 使用本档案的视觉 URL、视觉模型和密钥。";
  };
  visionProfileId.addEventListener("change", syncVisionSource);
  syncVisionSource();
  const timeout = numberInput(p.timeout != null ? p.timeout : 120, "120", 1, 600, 1);
  // 高级采样参数：留空 = 不发送该字段，交给 provider 默认值
  const temperature = numberInput(p.temperature, "空=默认", 0, 2);
  const topP = numberInput(p.top_p, "空=默认", 0, 1);
  const freqPenalty = numberInput(p.frequency_penalty, "空=默认", -2, 2);
  const presPenalty = numberInput(p.presence_penalty, "空=默认", -2, 2);
  const maxTokens = numberInput(p.max_tokens, "空=默认", 1, 1000000, 1);
  const numericControls = {
    "超时(秒)": timeout, "温度": temperature, "Top P": topP,
    "频率惩罚": freqPenalty, "存在惩罚": presPenalty, "最大输出 tokens": maxTokens,
  };
  const searchUrl = textInput(p.search_url, "https://…/search");
  const supportsVision = checkboxInput(p.supports_vision, "未探测时按此声明判定主模型能否接收图片附件；能力探测跑完后会被实测结果覆盖");
  const supportsFiles = checkboxInput(p.supports_files, "未探测时按此声明判定端点是否支持文件内容部分（附件 type:file）；能力探测跑完后会被实测结果覆盖");
  const keySaved = !!p.has_api_key;
  const keyMask = maskDisplay(p.api_key_masked);
  const keyInput = el("input", {
    type: "password",
    placeholder: keySaved ? `已保存 ${keyMask}；留空则不修改，输入新值随“保存”一起写入` : "sk-...（留空表示不设置密钥）",
    title: "仅用于服务端请求；前端与工作流 JSON 中永不出现完整密钥",
  });

  wrap.appendChild(inputRow("名称", name, "档案名称"));
  wrap.appendChild(inputRow("提供商", provider, "deepseek=官方 API；openai_compatible=任意 OpenAI 兼容端点；local=本地服务"));
  wrap.appendChild(inputRow("API URL", baseUrl, "服务实际 API 根地址；OpenAI 兼容服务通常包含 /v1，例如 http://127.0.0.1:1234/v1"));
  const modelRow = inputRow("模型", model, "可从模型目录选择；仍允许填写代理端点的自定义模型名");
  modelRow.appendChild(modelChoice.datalist);
  const catalogNote = el("small", { class: "aps-muted" });
  const catalogBtn = el("button", {
    class: "aps-btn aps-btn-mini", text: "拉取模型",
    title: "按当前表单里的 API URL 与密钥读取上游模型目录，不需要先保存档案；同时填充“视觉模型”候选",
    onClick: () => fetchModelCatalog(),
  });
  modelRow.appendChild(catalogBtn);
  modelRow.appendChild(catalogNote);
  wrap.appendChild(modelRow);

  // 保存前就能问上游有哪些模型：模型名必填，而目录只有探测过才填充，
  // 先保存再探测的次序会让人卡在一个还不知道该填什么的必填项上。
  const fillModels = (choice, values) => {
    choice.datalist.innerHTML = "";
    for (const value of [...new Set([...(values || []), choice.input.value].filter(Boolean))]) {
      choice.datalist.appendChild(el("option", { value }));
    }
  };
  async function fetchModelCatalog() {
    const base = baseUrl.value.trim();
    if (!base) { catalogNote.textContent = "先填 API URL"; return; }
    catalogBtn.disabled = true;
    catalogBtn.textContent = "读取中…";
    try {
      const r = await api("/models", { method: "POST", body: JSON.stringify({
        base_url: base,
        vision_base_url: visionUrl.value.trim(),
        api_key: keyInput.value.trim(),
        profile_id: p.profile_id || "",
      }) });
      // 读取失败时保留上一次拿到的候选，只报这次的错
      if (r.ok) {
        fillModels(modelChoice, r.models);
        fillModels(visionChoice, r.vision_models);
      }
      const count = (r.models || []).length;
      const corrected = r.base_url && r.base_url !== base ? `，实际端点 ${r.base_url}` : "";
      catalogNote.textContent = count
        ? `已取回 ${count} 个模型${corrected}；直接在下拉框选择即可`
        : `未取到模型目录：${r.error || "端点返回空目录"}${corrected}`;
      if (count === 1 && !model.value.trim()) model.value = r.models[0];
      toast(count ? `已取回 ${count} 个模型` : "未取到模型目录", !count);
    } catch (e) {
      catalogNote.textContent = "读取失败：" + e.message;
      toast("读取失败: " + e.message, true);
    } finally {
      catalogBtn.disabled = false;
      catalogBtn.textContent = "拉取模型";
    }
  }
  wrap.appendChild(inputRow("协议", protocol, "auto=按能力自动选择；responses=Responses API；chat_completions=Chat Completions"));
  wrap.appendChild(inputRow("推理", reasoning, "推理强度（映射到各协议实际参数）"));
  wrap.appendChild(inputRow("联网", webSearch, "联网策略：off/auto/always"));
  wrap.appendChild(inputRow("卸载策略", unload, "本地模型卸载策略"));
  wrap.appendChild(inputRow("视觉 URL", visionUrl, "独立视觉端点根地址（可选）；留空复用主 API URL"));
  const visionModelRow = inputRow("视觉模型", visionModel, "视觉模型名；目录元数据明确声明 image 时才自动确认视觉能力，也可在高级设置手动覆盖");
  visionModelRow.appendChild(visionChoice.datalist);
  wrap.appendChild(visionModelRow);
  wrap.appendChild(inputRow("视觉档案", visionProfileId, "视觉/文本 Profile 解耦：从已有档案选择；留空使用本档案的 vision_* 配置与密钥"));
  wrap.appendChild(visionLinkNote);
  wrap.appendChild(inputRow("超时(秒)", timeout, "请求超时（秒，1-600；留空按 120）"));

  // 高级采样区（不进普通节点 UI）
  const adv = el("details", { class: "aps-advanced" });
  const sum = el("summary", { text: "高级采样参数（留空 = provider 默认值）" });
  adv.appendChild(sum);
  adv.appendChild(inputRow("温度", temperature, "采样温度（0-2；留空不发送）"));
  adv.appendChild(inputRow("Top P", topP, "核采样 top_p（0-1；留空不发送）"));
  adv.appendChild(inputRow("频率惩罚", freqPenalty, "频率惩罚（-2~2；留空不发送）"));
  adv.appendChild(inputRow("存在惩罚", presPenalty, "存在惩罚（-2~2；留空不发送）"));
  adv.appendChild(inputRow("最大输出 tokens", maxTokens, "最大输出 token（留空不发送）"));
  adv.appendChild(inputRow("外部搜索地址", searchUrl, "外部搜索后端地址（POST {query} → {results:[{title,url,snippet}]}；无原生联网搜索时用于降级注入联网结果）"));
  adv.appendChild(inputRow("支持图片输入", supportsVision,
    "探测前是手动声明；能力探测会用实测结果覆盖此勾选"));
  adv.appendChild(inputRow("支持文件输入", supportsFiles,
    "探测前是手动声明；能力探测会用实测结果覆盖此勾选"));
  wrap.appendChild(adv);

  // 密钥区：只有“保存”一个写入入口，避免与档案保存互相覆盖
  const keyRow = el("div", { class: "aps-field" });
  keyRow.appendChild(fieldLabel("API Key", "仅用于服务端请求；前端与工作流 JSON 中永不出现完整密钥"));
  keyRow.appendChild(keyInput);
  keyRow.appendChild(el("small", {
    id: "aps-key-status",
    class: keySaved ? "aps-key-status aps-key-saved" : "aps-key-status aps-key-missing",
    text: keySaved ? `✓ 密钥已保存（${keyMask}）` : "未保存密钥",
  }));
  keyRow.appendChild(el("div", { class: "aps-btn-row" }, [
    el("button", { class: "aps-btn", text: "清除密钥", disabled: isNew || !keySaved, onClick: async () => {
      try {
        await api("/profiles/" + encodeURIComponent(p.profile_id) + "/api_key", { method: "DELETE" });
        toast("密钥已清除");
        if (p.profile_id) renderEditor(p.profile_id);
      } catch (e) { toast("错误: " + e.message, true); }
    } }),
  ]));
  keyRow.appendChild(el("small", {
    class: "aps-muted",
    text: "留空表示不修改已保存的密钥；填写后点“保存”会随档案一起写入。",
  }));
  wrap.appendChild(keyRow);

  // 表单快照：能力探测会按已保存的配置覆盖式刷新编辑器，未保存的修改需要先提醒
  const trackedControls = [
    name, provider, baseUrl, model, protocol, reasoning, webSearch, unload,
    visionUrl, visionModel, visionProfileId, timeout, temperature, topP,
    freqPenalty, presPenalty, maxTokens, searchUrl, supportsVision, supportsFiles, keyInput,
  ];
  const formSnapshot = () => trackedControls
    .map((c) => (c.type === "checkbox" ? String(c.checked) : c.value)).join("\u0000");
  let initialSnapshot = formSnapshot();
  const formDirty = () => formSnapshot() !== initialSnapshot;

  // 保存/删除/测试/探测
  const saveBtn = el("button", { class: "aps-btn aps-btn-primary", text: "保存", onClick: async () => {
    const problems = numberProblems(numericControls);
    if (problems.length) return toast("请先修正：" + problems.join("；"), true);
    if (!model.value.trim()) {
      return toast("模型不能为空：点「拉取模型」从上游目录选择，或直接填写模型名", true);
    }
    const payload = {
      name: name.value, provider: provider.value, base_url: baseUrl.value,
      model: model.value, protocol: protocol.value, reasoning: reasoning.value,
      web_search: webSearch.value, unload_policy: unload.value,
      vision_base_url: visionUrl.value, vision_model: visionModel.value,
      vision_profile_id: visionProfileId.value.trim(),
      timeout: parseFloat(timeout.value) || 120,
      temperature: parseOptFloat(temperature.value),
      top_p: parseOptFloat(topP.value),
      frequency_penalty: parseOptFloat(freqPenalty.value),
      presence_penalty: parseOptFloat(presPenalty.value),
      max_tokens: parseOptFloat(maxTokens.value),
      search_url: searchUrl.value.trim(),
      supports_vision: supportsVision.checked,
      supports_files: supportsFiles.checked,
    };
    const typedKey = keyInput.value.trim();
    try {
      let profileId = p.profile_id;
      if (isNew) {
        const created = await api("/profiles", { method: "POST", body: JSON.stringify(payload) });
        profileId = created.profile_id;
        currentProfileId = profileId;
      } else {
        await api("/profiles/" + encodeURIComponent(profileId), { method: "PUT", body: JSON.stringify(payload) });
      }
      // 密钥必须等档案写入完成后才能定位 profile_id；新建档案时先建后写密钥，
      // 表单里填过的密钥就不会再被随后的重渲染静默丢弃。
      if (typedKey) {
        await api("/profiles/" + encodeURIComponent(profileId) + "/api_key", {
          method: "POST", body: JSON.stringify({ api_key: typedKey }),
        });
        keyInput.value = "";
      }
      initialSnapshot = formSnapshot();
      toast(typedKey ? "已保存（含密钥）" : "已保存");
      refreshAll();
    } catch (e) { toast("错误: " + e.message, true); }
  } });

  const delBtn = el("button", { class: "aps-btn aps-btn-danger", text: "删除", onClick: async () => {
    if (!confirm("确定删除该档案？")) return;
    try {
      await api("/profiles/" + encodeURIComponent(p.profile_id), { method: "DELETE" });
      currentProfileId = "";
      toast("已删除");
      refreshAll();
    } catch (e) { toast("错误: " + e.message, true); }
  } });

  const isDefault = !isNew && p.profile_id === defaultProfileId;
  const defaultBtn = el("button", {
    class: "aps-btn", text: isDefault ? "当前默认档案" : "设为默认", disabled: isDefault,
    title: "Model Profile 节点留空时会使用这个档案",
    onClick: async () => {
      try {
        await api("/profiles/" + encodeURIComponent(p.profile_id) + "/default", { method: "POST", body: "{}" });
        toast("已设为默认");
        refreshAll();
      } catch (e) { toast("错误: " + e.message, true); }
    },
  });

  const testBtn = el("button", { class: "aps-btn", text: "测试", onClick: async () => {
    try {
      const r = await api("/profiles/" + encodeURIComponent(p.profile_id) + "/test", { method: "POST", body: "{}" });
      toast(r.ok ? "连接正常" : "连接失败: " + (r.error || ""), !r.ok);
    } catch (e) { toast("错误: " + e.message, true); }
  } });

  const probeBtn = el("button", { class: "aps-btn", text: "能力探测", onClick: async () => {
    if (formDirty() && !confirm("档案有未保存的修改。能力探测按已保存的配置运行，完成后会用实测结果刷新本表单（含 API URL 与图片/文件支持勾选），未保存的修改将丢失。仍要继续吗？")) return;
    if (!confirm("能力探测会向当前模型发送最小文本、JSON、工具、图片和文件测试请求，并消耗少量 token。继续吗？")) return;
    probeBtn.disabled = true;
    probeBtn.textContent = "正在逐项实测…";
    try {
      const r = await api("/profiles/" + encodeURIComponent(p.profile_id) + "/probe", { method: "POST", body: "{}" });
      toast(r.ok ? "探测完成" : r.error || "连接失败", !r.ok);
      await refreshAll();
    } catch (e) { toast("错误: " + e.message, true); }
    finally {
      probeBtn.disabled = false;
      probeBtn.textContent = "能力探测";
    }
  } });

  const actions = el("div", { class: "aps-btn-row" });
  actions.appendChild(saveBtn);
  if (!isNew) {
    actions.appendChild(testBtn);
    actions.appendChild(probeBtn);
    actions.appendChild(defaultBtn);
    actions.appendChild(delBtn);
  }
  wrap.appendChild(actions);
  return wrap;
}

function renderCapabilities(preloaded) {
  const box = document.querySelector("#aps-capabilities");
  if (!box) return;
  const seq = ++capabilitiesSeq;
  box.innerHTML = "";
  if (!currentProfileId) {
    box.appendChild(el("p", { class: "aps-muted", text: "选择档案开始配置" }));
    return;
  }
  if (preloaded && preloaded.profile_id === currentProfileId) {
    renderCapabilityBox(box, preloaded);
    return;
  }
  api("/profiles/" + encodeURIComponent(currentProfileId))
    .then((p) => {
      if (seq !== capabilitiesSeq || currentProfileId !== p.profile_id) return;
      renderCapabilityBox(box, p);
    })
    .catch((e) => {
      if (seq !== capabilitiesSeq) return;
      box.innerHTML = "";
      box.appendChild(el("p", { class: "aps-error", text: "能力状态加载失败：" + e.message }));
    });
}

function renderCapabilityBox(box, p) {
  box.innerHTML = "";
  const caps = p.capabilities || {};
  const labels = {
    model_listing: "模型目录", chat_completions: "Chat Completions",
    responses: "Responses", structured_output_chat: "Chat JSON Schema",
    structured_output_responses: "Responses JSON Schema",
    json_output_chat: "Chat JSON Object", function_tools_chat: "Chat 函数工具",
    function_tools_responses: "Responses 函数工具", native_web_search: "原生联网搜索",
    vision_chat: "Chat 图片输入", vision_responses: "Responses 图片输入",
    files_chat: "Chat 文件输入", files_responses: "Responses 文件输入",
    vision_service: "Reference Analyzer 视觉模型",
  };
  const grid = el("div", { class: "aps-cap-grid" });
  for (const [key, label] of Object.entries(labels)) {
    if (typeof caps[key] !== "boolean") continue;
    const input = el("input", { type: "checkbox", checked: caps[key], disabled: true });
    const detail = caps.checks?.[key]?.detail || "尚无探测详情";
    grid.appendChild(el("label", {
      class: "aps-cap-check " + (caps[key] ? "ok" : "no"), title: detail,
    }, [input, el("span", { text: label })]));
  }
  box.appendChild(grid);
  if (caps.probed_at) box.appendChild(el("p", {
    class: "aps-muted", text: `最近实测：${caps.probed_at} · ${caps.capability_basis || ""}`,
  }));
  const checkRows = Object.entries(caps.checks || {});
  if (checkRows.length) {
    const details = el("details", { class: "aps-advanced" });
    details.appendChild(el("summary", { text: "查看各端点 HTTP 状态与失败原因" }));
    const table = el("table", { class: "aps-table" });
    table.appendChild(el("tr", {}, [el("th", { text: "能力" }), el("th", { text: "HTTP" }), el("th", { text: "结果" }), el("th", { text: "说明" })]));
    for (const [key, item] of checkRows) table.appendChild(el("tr", {}, [
      el("td", { text: labels[key] || key }), el("td", { text: String(item.http_status || "—") }),
      el("td", { text: item.ok ? "✓" : "✗" }), el("td", { text: item.detail || "" }),
    ]));
    details.appendChild(table);
    box.appendChild(details);
  }
  if (!Object.keys(caps).length) {
    box.appendChild(el("span", { class: "aps-muted", text: "尚未实测。保存 API Key 后点击“能力探测”。" }));
  }
}

function renderLog() {
  const box = document.querySelector("#aps-log");
  if (!box) return;
  api("/log")
    .then(({ log }) => {
      box.innerHTML = "";
      if (!log.length) {
        box.appendChild(el("p", { class: "aps-muted", text: "—" }));
        return;
      }
      const table = el("table", { class: "aps-table" });
      table.appendChild(el("tr", {}, [
        el("th", { text: "时间" }), el("th", { text: "档案" }),
        el("th", { text: "类型" }), el("th", { text: "结果" }), el("th", { text: "详情" }),
      ]));
      for (const e of log) {
        table.appendChild(el("tr", {}, [
          el("td", { text: e.ts }), el("td", { text: e.profile_id || "" }),
          el("td", { text: e.kind || "" }), el("td", { text: String(e.ok) }),
          el("td", { text: e.detail || "" }),
        ]));
      }
      box.appendChild(table);
    })
    .catch((e) => {
      box.innerHTML = "";
      box.appendChild(el("p", { class: "aps-error", text: "日志加载失败：" + e.message }));
    });
}

// ---------------- Markdown 补充资料管理 ----------------

function renderSupplements() {
  const box = document.querySelector("#aps-supplements");
  if (!box) return;
  box.innerHTML = "";
  box.appendChild(el("p", { class: "aps-muted", text: "正在加载 Markdown 补充资料…" }));
  api("/supplements")
    .then(({ supplements }) => {
      box.innerHTML = "";
      box.appendChild(el("div", { class: "aps-btn-row" }, [
        el("button", { class: "aps-btn aps-btn-mini", text: "新建 Markdown 资料", onClick: () => openSupplementEditor(box) }),
      ]));
      if (!supplements.length) {
        box.appendChild(el("p", { class: "aps-muted", text: "暂无资料。可在这里添加模型提示词参考、风格词表或节点说明。" }));
        return;
      }
      const table = el("table", { class: "aps-table" });
      table.appendChild(el("tr", {}, [
        el("th", { text: "资料 ID" }), el("th", { text: "标题" }),
        el("th", { text: "适用范围" }), el("th", { text: "状态" }),
        el("th", { text: "大小" }), el("th", { text: "摘要 / 更新时间" }),
        el("th", { text: "操作" }),
      ]));
      for (const s of supplements) {
        const ops = el("td", {});
        ops.appendChild(el("button", { class: "aps-btn aps-btn-mini", text: "查看/编辑", onClick: async () => {
          try {
            const detail = await api("/supplements/" + encodeURIComponent(s.supplement_id));
            openSupplementEditor(box, detail);
          } catch (e) { toast("错误: " + e.message, true); }
        } }));
        ops.appendChild(el("button", { class: "aps-btn aps-btn-mini", text: s.enabled ? "停用" : "启用", onClick: async () => {
          try {
            await api("/supplements/" + encodeURIComponent(s.supplement_id) + "/enabled", {
              method: "POST", body: JSON.stringify({ enabled: !s.enabled }),
            });
            renderSupplements();
          } catch (e) { toast("错误: " + e.message, true); }
        } }));
        ops.appendChild(el("button", { class: "aps-btn aps-btn-mini aps-btn-danger", text: "删除", onClick: async () => {
          if (!confirm("删除 Markdown 资料 " + s.supplement_id + "？")) return;
          try {
            await api("/supplements/" + encodeURIComponent(s.supplement_id), { method: "DELETE" });
            toast("已保存");
            renderSupplements();
          } catch (e) { toast("错误: " + e.message, true); }
        } }));
        table.appendChild(el("tr", {}, [
          el("td", { text: s.supplement_id }), el("td", { text: s.title }),
          el("td", { text: s.scope === "target" ? (s.target_families || []).join(",") || "所有目标" : s.scope }),
          el("td", { text: s.enabled ? "✓ 已启用" : "✗ 已停用" }),
          el("td", { text: `${Math.ceil((s.size || 0) / 1024)} KiB` }),
          el("td", { text: `${(s.hash || s.content_hash || "").slice(0, 12)}… · ${s.updated_at || "—"} ` }),
          ops,
        ]));
      }
      box.appendChild(table);
      box.appendChild(el("p", { class: "aps-muted", text: "Markdown 只作为低优先级参考资料；不能覆盖 Model Core、输出格式、校验器或用户本轮指令。请在支持节点的“高级设置 · Prompt Supplements”中选择；工作流只保存稳定 ID。" }));
    })
    .catch((e) => {
      box.innerHTML = "";
      box.appendChild(el("p", { class: "aps-error", text: "Markdown 资料加载失败：" + e.message }));
      box.appendChild(el("button", { class: "aps-btn aps-btn-mini", text: "重试", onClick: renderSupplements }));
    });
}

// 与 schemas/prompt_supplement.py::PromptSupplement.validate 保持同一套规则；
// 后端仍是权威，这里只是把必然 400 的输入在提交前说清楚。
const SUPPLEMENT_SCOPES = ["global", "node", "target"];

function supplementProblems(payload) {
  const problems = [];
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(payload.supplement_id)) {
    problems.push("资料 ID 需以字母或数字开头，仅含字母/数字/下划线/连字符，最长 64 字符");
  }
  if (!payload.title) problems.push("标题不能为空");
  if (payload.title.length > 160) problems.push("标题最长 160 字符");
  if (!/^[^/\\]+\.md$/i.test(payload.filename)) problems.push("文件名必须是不带目录的 .md 文件");
  if (!SUPPLEMENT_SCOPES.includes(payload.scope)) {
    problems.push(`适用范围只能是 ${SUPPLEMENT_SCOPES.join(" / ")}`);
  }
  if (payload.scope === "node" && !payload.node_ids.length) {
    problems.push("适用范围为 node 时至少填一个节点 ID");
  }
  return problems;
}

function openSupplementEditor(box, record = {}) {
  const old = box.querySelector(".aps-supplement-editor");
  if (old) old.remove();
  const editor = el("div", { class: "aps-supplement-editor" });
  const fields = {};
  const add = (name, label, value, tooltip, multiline = false) => {
    const input = multiline
      ? el("textarea", { rows: 12 })
      : textInput(value || "", label);
    input.value = value || "";
    input.disabled = name === "supplement_id" && !!record.supplement_id;
    fields[name] = input;
    editor.appendChild(inputRow(label, input, tooltip));
  };
  editor.appendChild(el("h4", { text: record.supplement_id ? "编辑 Markdown 补充资料" : "新建 Markdown 补充资料" }));
  add("supplement_id", "资料 ID", record.supplement_id || "",
    "字母开头，仅字母/数字/下划线/连字符，最长 64 字符；已保存的资料不能改 ID");
  add("title", "标题", record.title || "", "必填，最长 160 字符");
  add("filename", "文件名", record.filename || "reference.md", "不带目录的 .md 文件名");
  add("scope", "适用范围", record.scope || "target", "只能填 global、node 或 target（小写）");
  add("target_families", "目标系列", (record.target_families || []).join(","),
    "逗号分隔；scope=target 时不能有空项");
  add("node_ids", "节点 ID", (record.node_ids || []).join(","),
    "逗号分隔；scope=node 时至少填一个。可填 ComfyUI 节点实例 ID（只匹配画布上那一个节点），"
    + "或整类节点的作用域名：prompt.studio、h3.studio、llm.generate、reference.analyzer、storyboard.create");
  add("description", "说明", record.description || "", "资料用途备注");
  add("content", "正文", record.content || "", "Markdown 正文，最大 256 KiB", true);
  const fileInput = el("input", { type: "file", accept: ".md,text/markdown" });
  fileInput.addEventListener("change", async () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".md")) {
      toast("只支持 .md 文件", true);
      fileInput.value = "";
      return;
    }
    fields.filename.value = file.name;
    fields.content.value = await file.text();
  });
  editor.appendChild(inputRow("导入本地 Markdown 文件", fileInput,
    "文件只会读取为文本并发送到本地补充资料注册表，不会上传到第三方"));
  const actions = el("div", { class: "aps-btn-row" });
  actions.appendChild(el("button", { class: "aps-btn aps-btn-mini", text: "关闭", onClick: () => editor.remove() }));
  actions.appendChild(el("button", { class: "aps-btn aps-btn-mini", text: "保存", onClick: async () => {
    const payload = {
      supplement_id: fields.supplement_id.value.trim(), title: fields.title.value.trim(),
      filename: fields.filename.value.trim(), scope: fields.scope.value.trim(),
      target_families: fields.target_families.value.split(",").map((v) => v.trim()).filter(Boolean),
      node_ids: fields.node_ids.value.split(",").map((v) => v.trim()).filter(Boolean),
      description: fields.description.value.trim(), content: fields.content.value,
    };
    const problems = supplementProblems(payload);
    if (problems.length) return toast("请先修正：" + problems.join("；"), true);
    try {
      const path = record.supplement_id ? "/supplements/" + encodeURIComponent(record.supplement_id) : "/supplements";
      await api(path, { method: record.supplement_id ? "PUT" : "POST", body: JSON.stringify(payload) });
      toast("已保存");
      renderSupplements();
    } catch (e) { toast("错误: " + e.message, true); }
  } }));
  editor.appendChild(actions);
  box.prepend(editor);
}

// ---------------- 入口：ComfyUI 菜单命令 + 原生 Settings 行 ----------------
// 菜单项必须与 commands 同名：前端按 extension.commands 过滤 menuCommands，
// 只在菜单里登记 id 而不注册命令会被直接丢弃。
const PREFIX = "[AI Prompt Studio]";

app.registerExtension({
  name: "AI Prompt Studio Settings",
  commands: [{
    id: WORKBENCH_COMMAND,
    label: "AI Prompt Studio 设置工作台",
    tooltip: "打开模型档案、能力探测与 Markdown 资料",
    icon: "pi pi-cog",
    function: () => openPanel(),
  }],
  menuCommands: [{ path: [], commands: [WORKBENCH_COMMAND] }],
  settings: [
    {
      id: "AI Prompt Studio.General.openWorkbench",
      name: "设置工作台",
      category: ["AI Prompt Studio", "常规", "设置工作台"],
      tooltip: "进入本分类即自动打开；也可用左上角 ComfyUI 菜单里的同名命令。",
      type() {
        const button = el("button", {
          class: "aps-native-settings-button",
          text: "打开 AI Prompt Studio 设置工作台",
          onClick: openPanel,
        });
        armWorkbenchAutoOpen(button);
        return button;
      },
    },
  ],
  nodeCreated(node) {
    const kind = node.comfyClass || node.type;
    if (kind === "APS_UnloadModel") {
      node.title = "LLM 后卸载 LM Studio（提示词透传）";
      const labels = {
        prompt: "提示词（接 LLM 输出）",
        model: "LM Studio 模型 key",
        url: "服务地址（本机可留空）",
        result: "卸载结果 JSON",
        status: "卸载状态",
      };
      for (const input of node.inputs || []) input.label = labels[input.name] || input.label;
      for (const output of node.outputs || []) output.label = labels[output.name] || output.label;
      for (const widget of node.widgets || []) widget.label = labels[widget.name] || widget.label;
      return;
    }
    if (kind !== "APS_ModelProfile") return;

    node.title = "AI 模型档案（可选择）";
    const profileWidget = (node.widgets || []).find((widget) => widget.name === "profile");
    const modelWidget = (node.widgets || []).find((widget) => widget.name === "model_override");
    if (!profileWidget || !modelWidget) return;

    const updateModels = (profiles) => {
      const selectedId = String(profileWidget.value || "").match(/\[([^\[\]]+)\]\s*$/)?.[1] || profileWidget.value;
      const selected = profiles.find((profile) => profile.profile_id === selectedId);
      const values = ["", selected?.model, ...(selected?.capabilities?.models || [])].filter(Boolean);
      if (modelWidget.value && !values.includes(modelWidget.value)) values.push(modelWidget.value);
      modelWidget.options.values = [...new Set(values)];
      node.setDirtyCanvas?.(true, true);
    };
    cachedJson("/ai_prompt_studio/profiles").then(({ profiles }) => {
      const profileValues = ["", ...profiles.map((profile) =>
        profile.name && profile.name !== profile.profile_id
          ? `${profile.name} [${profile.profile_id}]`
          : profile.profile_id)];
      if (profileWidget.value && !profileValues.includes(profileWidget.value)) profileValues.push(profileWidget.value);
      profileWidget.options.values = profileValues;
      updateModels(profiles);
      const originalCallback = profileWidget.callback;
      profileWidget.callback = function (value, ...args) {
        const result = originalCallback?.call(this, value, ...args);
        updateModels(profiles);
        return result;
      };
      node.setDirtyCanvas?.(true, true);
    }).catch((error) => console.warn(PREFIX + " profile dropdown refresh failed", error));
  },
  async setup() {
    ensureStylesheet();
    console.info(PREFIX + " frontend extension loaded");
    console.info(PREFIX + " native Settings entry registered");
  },
});
