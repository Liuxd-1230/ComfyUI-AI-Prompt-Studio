// AI Prompt Studio 设置工作台 —— ComfyUI 内嵌面板
// 语言：中文默认，可切换 EN；字段 tooltip 用 title 属性。
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
  const model = textInput(p.model, "deepseek-v4-flash");
  const protocol = selectInput(PROTOCOLS, p.protocol);
  const reasoning = selectInput(REASONING, p.reasoning);
  const webSearch = selectInput(WEB_SEARCH, p.web_search);
  const unload = selectInput(UNLOAD, p.unload_policy);
  const visionUrl = textInput(p.vision_base_url, "");
  const visionModel = textInput(p.vision_model, "");
  const timeout = textInput(p.timeout != null ? String(p.timeout) : "120", "120");
  // 高级采样参数（D19）：留空 = 不发送该字段，交给 provider 默认值
  const temperature = textInput(p.temperature != null ? String(p.temperature) : "", "空=默认");
  const topP = textInput(p.top_p != null ? String(p.top_p) : "", "空=默认");
  const freqPenalty = textInput(p.frequency_penalty != null ? String(p.frequency_penalty) : "", "空=默认");
  const presPenalty = textInput(p.presence_penalty != null ? String(p.presence_penalty) : "", "空=默认");
  const maxTokens = textInput(p.max_tokens != null ? String(p.max_tokens) : "", "空=默认");
  const supportsVision = checkboxInput(p.supports_vision, "主模型支持图片附件（覆盖能力探测的保守判定）");
  const supportsFiles = checkboxInput(p.supports_files, "端点支持文件内容部分（附件 type:file）");
  const keyInput = el("input", { type: "password", placeholder: t("api_key_placeholder"), title: t("api_tooltip") });

  wrap.appendChild(inputRow("name", name, "档案名称"));
  wrap.appendChild(inputRow("provider", provider, "deepseek=官方 API；openai_compatible=任意 OpenAI 兼容端点；local=本地服务"));
  wrap.appendChild(inputRow("base_url", baseUrl, "API 根地址（不含 /v1）"));
  wrap.appendChild(inputRow("model", model, "默认模型名，如 deepseek-v4-flash"));
  wrap.appendChild(inputRow("protocol", protocol, "auto=按能力自动选择；responses=Responses API；chat_completions=Chat Completions"));
  wrap.appendChild(inputRow("reasoning", reasoning, "推理强度（映射到各协议实际参数）"));
  wrap.appendChild(inputRow("web_search", webSearch, "联网策略：off/auto/always"));
  wrap.appendChild(inputRow("unload_policy", unload, "本地模型卸载策略"));
  wrap.appendChild(inputRow("vision_base_url", visionUrl, "视觉端点根地址（OpenAI 兼容，可选）"));
  wrap.appendChild(inputRow("vision_model", visionModel, "视觉模型名（可选，如 qwen-vl-max）"));
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
  adv.appendChild(inputRow("supports_vision", supportsVision, ""));
  adv.appendChild(inputRow("supports_files", supportsFiles, ""));
  wrap.appendChild(adv);

  // 密钥区
  const keyRow = el("div", { class: "aps-field" });
  keyRow.appendChild(fieldLabel("api_key", t("api_tooltip")));
  keyRow.appendChild(keyInput);
  const keyBtns = el("div", { class: "aps-btn-row" }, [
    el("button", { class: "aps-btn aps-btn-primary", text: t("set_key"), onClick: async () => {
      const val = keyInput.value.trim();
      if (!val) return toast(t("error") + ": api_key empty", true);
      try {
        const r = await api("/profiles/" + encodeURIComponent(p.profile_id || name.value) + "/api_key", {
          method: "POST", body: JSON.stringify({ api_key: val }),
        });
        keyInput.value = "";
        toast(t("key_ok") + " (" + r.masked + ")");
        if (p.profile_id) renderEditor(p.profile_id);
        refreshAll();
      } catch (e) { toast(t("error") + ": " + e.message, true); }
    } }),
    el("button", { class: "aps-btn", text: t("clear_key"), onClick: async () => {
      try {
        await api("/profiles/" + encodeURIComponent(p.profile_id) + "/api_key", { method: "DELETE" });
        toast(t("key_ok"));
        if (p.profile_id) renderEditor(p.profile_id);
      } catch (e) { toast(t("error") + ": " + e.message, true); }
    } }),
  ]);
  keyRow.appendChild(keyBtns);
  wrap.appendChild(keyRow);

  // 保存/删除/测试/探测
  const saveBtn = el("button", { class: "aps-btn aps-btn-primary", text: t("save"), onClick: async () => {
    const payload = {
      name: name.value, provider: provider.value, base_url: baseUrl.value,
      model: model.value, protocol: protocol.value, reasoning: reasoning.value,
      web_search: webSearch.value, unload_policy: unload.value,
      vision_base_url: visionUrl.value, vision_model: visionModel.value,
      timeout: parseFloat(timeout.value) || 120,
      temperature: parseOptFloat(temperature.value),
      top_p: parseOptFloat(topP.value),
      frequency_penalty: parseOptFloat(freqPenalty.value),
      presence_penalty: parseOptFloat(presPenalty.value),
      max_tokens: parseOptFloat(maxTokens.value),
      supports_vision: supportsVision.checked,
      supports_files: supportsFiles.checked,
    };
    try {
      if (isNew) {
        await api("/profiles", { method: "POST", body: JSON.stringify(payload) });
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
    try {
      const r = await api("/profiles/" + encodeURIComponent(p.profile_id) + "/probe", { method: "POST", body: "{}" });
      toast(r.ok ? t("probe_ok") : r.error || t("test_fail"), !r.ok);
      renderCapabilities();
    } catch (e) { toast(t("error") + ": " + e.message, true); }
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
      const keys = ["responses", "chat_completions", "function_tools", "native_web_search", "structured_output", "vision", "files", "capability_basis", "model_listing"];
      for (const k of keys) {
        const v = caps[k];
        if (v === undefined) continue;
        const badge = el("span", { class: "aps-cap " + (v === true ? "ok" : v === false ? "no" : "unk"), text: k + "=" + String(v) });
        box.appendChild(badge);
      }
      if (!Object.keys(caps).length) {
        box.appendChild(el("span", { class: "aps-muted", text: t("probe") + "?" }));
      }
    })
    .catch(() => {});
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
  for (const a of ["runtime_status", "runtime_list", "runtime_load", "runtime_unload", "runtime_unload_all"]) {
    row.appendChild(el("button", { class: "aps-btn", text: t(a), onClick: act(a.replace("runtime_", "")) }));
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
    .catch(() => {});
}

// ---------------- 菜单入口 ----------------

function addMenuButton() {
  const menu = document.querySelector(".comfy-menu");
  if (!menu) return;
  const btn = el("button", {
    class: "comfy-menu-btn",
    text: "AI Prompt Studio",
    title: "AI Prompt Studio 设置工作台",
    style: { width: "100%", margin: "4px 0" },
    onClick: openPanel,
  });
  menu.insertBefore(btn, menu.firstChild);
}

app.registerExtension({
  name: "AI Prompt Studio Settings",
  async setup() {
    addMenuButton();
  },
});
