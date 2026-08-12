// AI Prompt Studio 设置工作台 —— ComfyUI 内嵌面板
// 语言：中文默认，可切换 EN；字段 tooltip 用 title 属性。
// 入口（0.2.1c）：ComfyUI 原生 Settings 页面；设置项触发大型工作台 overlay。
import { app } from "../../scripts/app.js";
import { el, api, toast, t, setLang, lang, maskDisplay } from "./profile_widgets.js";

const PROVIDERS = ["deepseek", "openai_compatible", "local"];
const PROTOCOLS = ["auto", "responses", "chat_completions"];
const REASONING = ["off", "low", "medium", "high"];
const WEB_SEARCH = ["off", "auto", "always"];
const UNLOAD = ["never", "after_request", "after_success"];
const BACKENDS = ["ollama", "llamacpp", "lmstudio", "custom"];
const ACTIONS = ["status", "list_models", "load", "unload", "reload", "unload_all"];

let panel = null;
let currentProfileId = "";
let profileRecords = [];

const STYLE_ID = "aps-settings-styles";

function ensureStylesheet() {
  if (document.getElementById(STYLE_ID)) return;
  const link = document.createElement("link");
  link.id = STYLE_ID;
  link.rel = "stylesheet";
  link.href = new URL("./styles.css", import.meta.url).href;
  document.head.appendChild(link);
}

function fieldLabel(key, tooltip) {
  return el("label", { title: tooltip || t(key) }, [t(key)]);
}

function inputRow(labelKey, input, tooltip) {
  const row = el("div", { class: "aps-field" });
  row.appendChild(fieldLabel(labelKey, tooltip));
  row.appendChild(input);
  return row;
}

function textInput(value, placeholder) {
  return el("input", { type: "text", value: value || "", placeholder: placeholder || "" });
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
  panel.style.display = "flex";
  refreshAll();
}

function closePanel() {
  if (panel) panel.style.display = "none";
}

function buildPanel() {
  const overlay = el("div", { class: "aps-overlay" });
  overlay.id = "aps-overlay";
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closePanel();
  });
  const body = el("div", { class: "aps-panel" });

  // header
  const header = el("div", { class: "aps-header" }, [
    el("h2", { text: t("title") }),
    el("button", { class: "aps-btn", id: "aps-lang-btn", text: t("lang"), onClick: () => {
      setLang(lang() === "zh" ? "en" : "zh");
      document.querySelector("#aps-lang-btn").textContent = t("lang");
      refreshAll();
    } }),
    el("button", { class: "aps-btn aps-btn-close", text: "✕", title: t("close"), onClick: closePanel }),
  ]);
  body.appendChild(header);

  // status line
  const statusLine = el("div", { class: "aps-status-line", id: "aps-status-line" });
  body.appendChild(statusLine);

  body.appendChild(el("section", { class: "aps-guide" }, [
    el("h3", { text: "LM Studio 自动卸载怎么连接" }),
    el("p", { text: "把节点串在提示词生成和图像/视频生成之间：" }),
    el("code", { text: "LLM 提示词输出 → LLM 后卸载 LM Studio（提示词透传） → 图像/视频节点的 prompt" }),
    el("p", { text: "model 填 LM Studio 的模型 key（例如 openai/gpt-oss-20b）；本机服务的 url 通常留空即可。" }),
  ]));

  // two columns: profiles list + editor
  const cols = el("div", { class: "aps-cols" });
  const left = el("div", { class: "aps-col aps-col-list" }, [el("h3", { text: t("profiles") }), el("div", { id: "aps-profile-list" })]);
  const right = el("div", { class: "aps-col aps-col-editor" }, [el("div", { id: "aps-editor" }, [el("p", { class: "aps-muted", text: t("select_profile") })])]);
  cols.appendChild(left);
  cols.appendChild(right);
  body.appendChild(cols);

  // bottom sections
  const bottom = el("div", { class: "aps-bottom" });
  bottom.appendChild(el("div", { class: "aps-section" }, [
    el("h3", { text: t("capabilities") }),
    el("div", { id: "aps-capabilities" }),
  ]));
  bottom.appendChild(el("div", { class: "aps-section" }, [
    el("h3", { text: t("runtime") }),
    el("div", { id: "aps-runtime" }),
  ]));
  bottom.appendChild(el("div", { class: "aps-section" }, [
    el("h3", { text: t("log") }),
    el("div", { id: "aps-log" }),
  ]));
  bottom.appendChild(el("div", { class: "aps-section" }, [
    el("h3", { text: t("supplements") }),
    el("div", { id: "aps-supplements" }),
  ]));
  body.appendChild(bottom);
  overlay.appendChild(body);
  return overlay;
}

// ---------------- 数据刷新 ----------------

async function refreshAll() {
  try {
    const [status, list] = await Promise.all([
      api("/status"),
      api("/profiles"),
    ]);
    renderStatus(status);
    renderProfiles(list);
  } catch (e) {
    toast(t("error") + ": " + e.message, true);
  }
  renderRuntime();
  renderLog();
  renderSupplements();
  if (currentProfileId) renderEditor(currentProfileId);
}

function renderStatus(info) {
  const line = document.querySelector("#aps-status-line");
  if (!line) return;
  line.textContent = `v${info.version || "?"}` +
    (info.comfyui_version ? ` · ComfyUI ${info.comfyui_version}` : "") +
    ` · ${info.profile_count} profiles` +
    (info.anima_booster_detected ? " · ANIMA_BOOSTER 已检测" : "");
}

function renderProfiles({ profiles, default_profile_id }) {
  profileRecords = profiles || [];
  const box = document.querySelector("#aps-profile-list");
  if (!box) return;
  box.innerHTML = "";
  if (!profiles.length) {
    box.appendChild(el("p", { class: "aps-muted", text: t("profiles") + ": —" }));
  }
  for (const p of profiles) {
    const row = el("div", {
      class: "aps-profile-row" + (p.profile_id === currentProfileId ? " aps-selected" : ""),
      onClick: () => {
        currentProfileId = p.profile_id;
        renderProfiles({ profiles, default_profile_id });
        renderEditor(p.profile_id);
        renderCapabilities();
      },
    });
    const title = el("div", { class: "aps-profile-title" }, [
      el("strong", { text: p.name || p.profile_id }),
      p.profile_id === default_profile_id ? el("span", { class: "aps-badge", text: t("default") }) : null,
    ]);
    const meta = el("div", { class: "aps-profile-meta", text: `${p.provider} · ${p.model || ""} · key ${maskDisplay(p.api_key_masked)}` });
    row.appendChild(title);
    row.appendChild(meta);
    box.appendChild(row);
  }
  box.appendChild(el("button", { class: "aps-btn aps-btn-primary", text: "+ " + t("new_profile"), onClick: () => {
    currentProfileId = "";
    renderEditor("");
  } }));
}

function renderEditor(profileId) {
  const box = document.querySelector("#aps-editor");
  if (!box) return;
  if (!profileId) {
    box.innerHTML = "";
    box.appendChild(buildEditorForm(null));
    return;
  }
  api("/profiles/" + encodeURIComponent(profileId))
    .then((p) => {
      box.innerHTML = "";
      box.appendChild(buildEditorForm(p));
      renderCapabilities();
    })
    .catch((e) => toast(t("error") + ": " + e.message, true));
}

function buildEditorForm(p) {
  const wrap = el("div", {});
  const isNew = !p;
  p = p || {};

  const name = textInput(p.name, "profile name");
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
  const timeout = textInput(p.timeout != null ? String(p.timeout) : "120", "120");
  // 高级采样参数（D19）：留空 = 不发送该字段，交给 provider 默认值
  const temperature = textInput(p.temperature != null ? String(p.temperature) : "", "空=默认");
  const topP = textInput(p.top_p != null ? String(p.top_p) : "", "空=默认");
  const freqPenalty = textInput(p.frequency_penalty != null ? String(p.frequency_penalty) : "", "空=默认");
  const presPenalty = textInput(p.presence_penalty != null ? String(p.presence_penalty) : "", "空=默认");
  const maxTokens = textInput(p.max_tokens != null ? String(p.max_tokens) : "", "空=默认");
  const searchUrl = textInput(p.search_url, "https://…/search");
  const supportsVision = checkboxInput(p.supports_vision, "主模型支持图片附件（覆盖能力探测的保守判定）");
  const supportsFiles = checkboxInput(p.supports_files, "端点支持文件内容部分（附件 type:file）");
  const keySaved = !!p.has_api_key;
  const keyMask = maskDisplay(p.api_key_masked);
  const keyInput = el("input", {
    type: "password",
    placeholder: keySaved ? `已保存 ${keyMask}；输入新值可替换` : t("api_key_placeholder"),
    title: t("api_tooltip"),
  });

  wrap.appendChild(inputRow("name", name, "档案名称"));
  wrap.appendChild(inputRow("provider", provider, "deepseek=官方 API；openai_compatible=任意 OpenAI 兼容端点；local=本地服务"));
  wrap.appendChild(inputRow("base_url", baseUrl, "服务实际 API 根地址；OpenAI 兼容服务通常包含 /v1，例如 http://127.0.0.1:1234/v1"));
  const modelRow = inputRow("model", model, "探测成功后可从模型目录选择；仍允许填写代理端点的自定义模型名");
  modelRow.appendChild(modelChoice.datalist);
  wrap.appendChild(modelRow);
  wrap.appendChild(inputRow("protocol", protocol, "auto=按能力自动选择；responses=Responses API；chat_completions=Chat Completions"));
  wrap.appendChild(inputRow("reasoning", reasoning, "推理强度（映射到各协议实际参数）"));
  wrap.appendChild(inputRow("web_search", webSearch, "联网策略：off/auto/always"));
  wrap.appendChild(inputRow("unload_policy", unload, "本地模型卸载策略"));
  wrap.appendChild(inputRow("vision_base_url", visionUrl, "独立视觉端点根地址（可选）；留空复用主 API URL"));
  const visionModelRow = inputRow("vision_model", visionModel, "视觉模型名；目录元数据明确声明 image 时才自动确认视觉能力，也可在高级设置手动覆盖");
  visionModelRow.appendChild(visionChoice.datalist);
  wrap.appendChild(visionModelRow);
  wrap.appendChild(inputRow("vision_profile_id", visionProfileId, "视觉/文本 Profile 解耦：从已有档案选择；留空使用本档案的 vision_* 配置与密钥"));
  wrap.appendChild(visionLinkNote);
  wrap.appendChild(inputRow("timeout", timeout, "请求超时（秒）"));

  // 高级采样区（不进普通节点 UI）
  const adv = el("details", { class: "aps-advanced" });
  const sum = el("summary", { text: "高级采样参数（留空 = provider 默认值）" });
  adv.appendChild(sum);
  adv.appendChild(inputRow("temperature", temperature, "采样温度（0-2；留空不发送）"));
  adv.appendChild(inputRow("top_p", topP, "核采样 top_p（0-1；留空不发送）"));
  adv.appendChild(inputRow("frequency_penalty", freqPenalty, "频率惩罚（-2~2；留空不发送）"));
  adv.appendChild(inputRow("presence_penalty", presPenalty, "存在惩罚（-2~2；留空不发送）"));
  adv.appendChild(inputRow("max_tokens", maxTokens, "最大输出 token（留空不发送）"));
  adv.appendChild(inputRow("search_url", searchUrl, "外部搜索后端地址（POST {query} → {results:[{title,url,snippet}]}；无原生联网搜索时用于降级注入联网结果）"));
  adv.appendChild(inputRow("supports_vision", supportsVision, ""));
  adv.appendChild(inputRow("supports_files", supportsFiles, ""));
  wrap.appendChild(adv);

  // 密钥区
  const keyRow = el("div", { class: "aps-field" });
  keyRow.appendChild(fieldLabel("api_key", t("api_tooltip")));
  keyRow.appendChild(keyInput);
  keyRow.appendChild(el("small", {
    id: "aps-key-status",
    class: keySaved ? "aps-key-status aps-key-saved" : "aps-key-status aps-key-missing",
    text: keySaved ? `✓ 密钥已保存（${keyMask}）` : "未保存密钥",
  }));
  const keyBtns = el("div", { class: "aps-btn-row" }, [
    el("button", { class: "aps-btn aps-btn-primary", text: t("set_key"), disabled: isNew, onClick: async () => {
      const val = keyInput.value.trim();
      if (!val) return toast(t("error") + ": api_key empty", true);
      try {
        const r = await api("/profiles/" + encodeURIComponent(p.profile_id) + "/api_key", {
          method: "POST", body: JSON.stringify({ api_key: val }),
        });
        keyInput.value = "";
        toast(t("key_ok") + " (" + r.masked + ")");
        if (p.profile_id) renderEditor(p.profile_id);
        refreshAll();
      } catch (e) { toast(t("error") + ": " + e.message, true); }
    } }),
    el("button", { class: "aps-btn", text: t("clear_key"), disabled: isNew || !keySaved, onClick: async () => {
      try {
        await api("/profiles/" + encodeURIComponent(p.profile_id) + "/api_key", { method: "DELETE" });
        toast(t("key_ok"));
        if (p.profile_id) renderEditor(p.profile_id);
      } catch (e) { toast(t("error") + ": " + e.message, true); }
    } }),
  ]);
  keyRow.appendChild(keyBtns);
  if (isNew) keyRow.appendChild(el("small", { class: "aps-muted", text: "请先保存档案，系统生成 profile_id 后再保存 API Key。" }));
  wrap.appendChild(keyRow);

  // 保存/删除/测试/探测
  const saveBtn = el("button", { class: "aps-btn aps-btn-primary", text: t("save"), onClick: async () => {
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
    try {
      if (isNew) {
        const created = await api("/profiles", { method: "POST", body: JSON.stringify(payload) });
        currentProfileId = created.profile_id;
      } else {
        await api("/profiles/" + encodeURIComponent(p.profile_id), { method: "PUT", body: JSON.stringify(payload) });
      }
      toast(t("save_ok"));
      refreshAll();
    } catch (e) { toast(t("error") + ": " + e.message, true); }
  } });

  const delBtn = el("button", { class: "aps-btn aps-btn-danger", text: t("delete"), onClick: async () => {
    if (!confirm(t("delete_confirm"))) return;
    try {
      await api("/profiles/" + encodeURIComponent(p.profile_id), { method: "DELETE" });
      currentProfileId = "";
      toast(t("save_ok"));
      refreshAll();
    } catch (e) { toast(t("error") + ": " + e.message, true); }
  } });

  const testBtn = el("button", { class: "aps-btn", text: t("test"), onClick: async () => {
    try {
      const r = await api("/profiles/" + encodeURIComponent(p.profile_id) + "/test", { method: "POST", body: "{}" });
      toast(r.ok ? t("test_ok") : t("test_fail") + ": " + (r.error || ""), !r.ok);
    } catch (e) { toast(t("error") + ": " + e.message, true); }
  } });

  const probeBtn = el("button", { class: "aps-btn", text: t("probe"), onClick: async () => {
    if (!confirm("能力探测会向当前模型发送最小文本、JSON、工具、图片和文件测试请求，并消耗少量 token。继续吗？")) return;
    probeBtn.disabled = true;
    probeBtn.textContent = "正在逐项实测…";
    try {
      const r = await api("/profiles/" + encodeURIComponent(p.profile_id) + "/probe", { method: "POST", body: "{}" });
      toast(r.ok ? t("probe_ok") : r.error || t("test_fail"), !r.ok);
      await refreshAll();
    } catch (e) { toast(t("error") + ": " + e.message, true); }
    finally {
      probeBtn.disabled = false;
      probeBtn.textContent = t("probe");
    }
  } });

  const actions = el("div", { class: "aps-btn-row" });
  actions.appendChild(saveBtn);
  if (!isNew) {
    actions.appendChild(testBtn);
    actions.appendChild(probeBtn);
    actions.appendChild(delBtn);
  }
  wrap.appendChild(actions);
  return wrap;
}

function renderCapabilities() {
  const box = document.querySelector("#aps-capabilities");
  if (!box) return;
  box.innerHTML = "";
  if (!currentProfileId) {
    box.appendChild(el("p", { class: "aps-muted", text: t("select_profile") }));
    return;
  }
  api("/profiles/" + encodeURIComponent(currentProfileId))
    .then((p) => {
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
        box.appendChild(el("span", { class: "aps-muted", text: "尚未实测。保存 API Key 后点击“重新探测”。" }));
      }
    })
    .catch((e) => {
      box.innerHTML = "";
      box.appendChild(el("p", { class: "aps-error", text: "能力状态加载失败：" + e.message }));
    });
}

function renderRuntime() {
  const box = document.querySelector("#aps-runtime");
  if (!box) return;
  box.innerHTML = "";
  const backend = selectInput(BACKENDS, "ollama");
  const url = textInput("", "");
  const model = textInput("", "");
  const out = el("pre", { class: "aps-pre" });

  const act = (action) => async () => {
    try {
      const r = await api("/runtime", {
        method: "POST",
        body: JSON.stringify({ backend: backend.value, action, url: url.value, model: model.value }),
      });
      out.textContent = JSON.stringify(r, null, 2);
    } catch (e) { out.textContent = e.message; }
  };

  box.appendChild(inputRow("backend", backend, "Ollama / llama.cpp server / LM Studio / 自定义"));
  box.appendChild(inputRow("base_url", url, "服务地址；留空使用默认端口"));
  box.appendChild(inputRow("model", model, "模型名（加载/卸载需要）"));
  const row = el("div", { class: "aps-btn-row" });
  const runtimeActions = [
    ["runtime_status", "status"],
    ["runtime_list", "list_models"],
    ["runtime_load", "load"],
    ["runtime_unload", "unload"],
    ["runtime_unload_all", "unload_all"],
  ];
  for (const [label, action] of runtimeActions) {
    row.appendChild(el("button", { class: "aps-btn", text: t(label), onClick: act(action) }));
  }
  box.appendChild(row);
  box.appendChild(out);
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
        el("th", { text: "time" }), el("th", { text: "profile" }),
        el("th", { text: "kind" }), el("th", { text: "ok" }), el("th", { text: "detail" }),
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
        el("th", { text: "id" }), el("th", { text: "标题" }),
        el("th", { text: "适用范围" }), el("th", { text: "状态" }),
        el("th", { text: "大小" }), el("th", { text: "hash / 更新时间" }),
        el("th", { text: "操作" }),
      ]));
      for (const s of supplements) {
        const ops = el("td", {});
        ops.appendChild(el("button", { class: "aps-btn aps-btn-mini", text: "查看/编辑", onClick: async () => {
          try {
            const detail = await api("/supplements/" + encodeURIComponent(s.supplement_id));
            openSupplementEditor(box, detail);
          } catch (e) { toast(t("error") + ": " + e.message, true); }
        } }));
        ops.appendChild(el("button", { class: "aps-btn aps-btn-mini", text: s.enabled ? "停用" : "启用", onClick: async () => {
          try {
            await api("/supplements/" + encodeURIComponent(s.supplement_id) + "/enabled", {
              method: "POST", body: JSON.stringify({ enabled: !s.enabled }),
            });
            renderSupplements();
          } catch (e) { toast(t("error") + ": " + e.message, true); }
        } }));
        ops.appendChild(el("button", { class: "aps-btn aps-btn-mini aps-btn-danger", text: "删除", onClick: async () => {
          if (!confirm("删除 Markdown 资料 " + s.supplement_id + "？")) return;
          try {
            await api("/supplements/" + encodeURIComponent(s.supplement_id), { method: "DELETE" });
            toast(t("save_ok"));
            renderSupplements();
          } catch (e) { toast(t("error") + ": " + e.message, true); }
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

function openSupplementEditor(box, record = {}) {
  const old = box.querySelector(".aps-supplement-editor");
  if (old) old.remove();
  const editor = el("div", { class: "aps-supplement-editor" });
  const fields = {};
  const add = (name, value, multiline = false) => {
    const input = multiline
      ? el("textarea", { rows: 12 })
      : textInput(value || "", name);
    input.value = value || "";
    input.disabled = name === "supplement_id" && !!record.supplement_id;
    fields[name] = input;
    editor.appendChild(inputRow(name, input, name));
  };
  editor.appendChild(el("h4", { text: record.supplement_id ? "编辑 Markdown 补充资料" : "新建 Markdown 补充资料" }));
  add("supplement_id", record.supplement_id || "");
  add("title", record.title || "");
  add("filename", record.filename || "reference.md");
  add("scope", record.scope || "target");
  add("target_families", (record.target_families || []).join(","));
  add("node_ids", (record.node_ids || []).join(","));
  add("description", record.description || "");
  add("content", record.content || "", true);
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
    try {
      const path = record.supplement_id ? "/supplements/" + encodeURIComponent(record.supplement_id) : "/supplements";
      await api(path, { method: record.supplement_id ? "PUT" : "POST", body: JSON.stringify(payload) });
      toast(t("save_ok"));
      renderSupplements();
    } catch (e) { toast(t("error") + ": " + e.message, true); }
  } }));
  editor.appendChild(actions);
  box.prepend(editor);
}

// ---------------- 原生 Settings 入口（0.2.1c） ----------------
// ComfyUI Settings API 没有 button/action 类型；用一次性 combo 作为工作台入口。
// 选择 "Open Settings Workbench" 后打开现有大型 overlay，再恢复为 idle。
const PREFIX = "[AI Prompt Studio]";
const OPEN_WORKBENCH_SETTING_ID = "AI Prompt Studio.General.openWorkbench";

function resetWorkbenchSetting() {
  const setting = app.extensionManager && app.extensionManager.setting;
  if (!setting || typeof setting.set !== "function") return;
  Promise.resolve(setting.set(OPEN_WORKBENCH_SETTING_ID, "idle")).catch((err) => {
    console.warn(PREFIX + " failed to reset workbench setting", err);
  });
}

app.registerExtension({
  name: "AI Prompt Studio Settings",
  settings: [
    {
      id: "AI Prompt Studio.General.language",
      name: "界面语言",
      category: ["AI Prompt Studio", "常规", "界面语言"],
      type: "combo",
      defaultValue: "zh",
      options: [
        { text: "中文", value: "zh" },
        { text: "English", value: "en" },
      ],
      onChange(value) {
        setLang(value === "en" ? "en" : "zh");
        const btn = document.querySelector("#aps-lang-btn");
        if (btn) btn.textContent = t("lang");
      },
    },
    {
      id: OPEN_WORKBENCH_SETTING_ID,
      name: "打开 AI Prompt Studio 设置工作台",
      category: ["AI Prompt Studio", "常规", "设置工作台"],
      tooltip: "选择“打开完整设置工作台”进入模型档案、本地运行时和 Markdown 补充资料配置。",
      type: "combo",
      defaultValue: "idle",
      options: [
        { text: "请选择", value: "idle" },
        { text: "打开完整设置工作台", value: "open" },
      ],
      onChange(value, oldValue) {
        if (value !== "open" || oldValue === "open") return;
        openPanel();
        resetWorkbenchSetting();
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
    api("/profiles").then(({ profiles }) => {
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
