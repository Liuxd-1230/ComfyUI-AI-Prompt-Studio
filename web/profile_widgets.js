// AI Prompt Studio — 前端辅助（DOM 构建 / API 调用 / i18n / 提示）
export const API_BASE = "/api/ai_prompt_studio";

// ---------- i18n ----------
const I18N = {
  zh: {
    title: "AI Prompt Studio 设置",
    lang: "EN",
    close: "关闭",
    profiles: "档案",
    new_profile: "新建档案",
    edit: "编辑",
    delete: "删除",
    set_default: "设为默认",
    default: "默认",
    test: "测试",
    probe: "能力探测",
    save: "保存",
    cancel: "取消",
    api_key: "API Key",
    api_key_placeholder: "sk-...（已保存的显示为脱敏值）",
    set_key: "保存密钥",
    clear_key: "清除密钥",
    capabilities: "能力状态",
    runtime: "本地运行时",
    runtime_status: "状态",
    runtime_list: "模型列表",
    runtime_load: "加载",
    runtime_unload: "卸载",
    runtime_unload_all: "全部卸载",
    log: "请求日志",
    skills: "Prompt Skill",
    status: "状态",
    name: "名称",
    provider: "提供商",
    base_url: "API URL",
    model: "模型",
    protocol: "协议",
    reasoning: "推理",
    web_search: "联网",
    unload_policy: "卸载策略",
    vision_base_url: "视觉 URL",
    vision_model: "视觉模型",
    timeout: "超时(秒)",
    save_ok: "已保存",
    key_ok: "密钥已保存",
    test_ok: "连接正常",
    test_fail: "连接失败",
    probe_ok: "探测完成",
    delete_confirm: "确定删除该档案？",
    error: "错误",
    select_profile: "选择档案开始配置",
    api_tooltip: "仅用于服务端请求；前端与工作流 JSON 中永不出现完整密钥",
    detect: "重新探测",
  },
  en: {
    title: "AI Prompt Studio Settings",
    lang: "中文",
    close: "Close",
    profiles: "Profiles",
    new_profile: "New Profile",
    edit: "Edit",
    delete: "Delete",
    set_default: "Set Default",
    default: "Default",
    test: "Test",
    probe: "Probe",
    save: "Save",
    cancel: "Cancel",
    api_key: "API Key",
    api_key_placeholder: "sk-... (masked when saved)",
    set_key: "Save Key",
    clear_key: "Clear Key",
    capabilities: "Capabilities",
    runtime: "Local Runtime",
    runtime_status: "Status",
    runtime_list: "List Models",
    runtime_load: "Load",
    runtime_unload: "Unload",
    runtime_unload_all: "Unload All",
    log: "Request Log",
    skills: "Prompt Skill",
    status: "Status",
    name: "Name",
    provider: "Provider",
    base_url: "API URL",
    model: "Model",
    protocol: "Protocol",
    reasoning: "Reasoning",
    web_search: "Web Search",
    unload_policy: "Unload Policy",
    vision_base_url: "Vision URL",
    vision_model: "Vision Model",
    timeout: "Timeout(s)",
    save_ok: "Saved",
    key_ok: "Key saved",
    test_ok: "Connection OK",
    test_fail: "Connection failed",
    probe_ok: "Probe done",
    delete_confirm: "Delete this profile?",
    error: "Error",
    select_profile: "Select a profile to configure",
    api_tooltip: "Used server-side only; never appears in frontend or workflow JSON",
    detect: "Re-probe",
  },
};

let currentLang = localStorage.getItem("aps_lang") || "zh";
export function lang() {
  return currentLang;
}
export function t(key) {
  return (I18N[currentLang] && I18N[currentLang][key]) || I18N.zh[key] || key;
}
export function setLang(l) {
  currentLang = l;
  localStorage.setItem("aps_lang", l);
}

// ---------- DOM ----------
export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") node.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(node.style, v);
    else if (k.startsWith("on")) node.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "text") node.textContent = v;
    else node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    if (c == null) continue;
    node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return node;
}

// ---------- API ----------
export async function api(path, options = {}) {
  const opts = { headers: { "Content-Type": "application/json" }, ...options };
  let resp;
  try {
    resp = await fetch(API_BASE + path, opts);
  } catch (e) {
    throw new Error(t("network_error") || "网络错误: " + e.message);
  }
  let data = {};
  try {
    data = await resp.json();
  } catch (e) {
    /* 空响应 */
  }
  if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
  return data;
}

// ---------- toast ----------
export function toast(message, isError = false, duration = 3200) {
  let box = document.querySelector("#aps-toast-box");
  if (!box) {
    box = el("div", { id: "aps-toast-box", class: "aps-toast-box" });
    document.body.appendChild(box);
  }
  const node = el("div", { class: "aps-toast" + (isError ? " aps-toast-error" : "") }, [message]);
  box.appendChild(node);
  setTimeout(() => node.remove(), duration);
}

export function maskDisplay(masked) {
  return masked || "—";
}
