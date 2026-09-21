// AI Prompt Studio — 前端辅助（DOM 构建 / API 调用 / 提示）
import { invalidateCachedJson } from "./data_cache.js";

export const API_BASE = "/api/ai_prompt_studio";

// ---------- DOM ----------
export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") node.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(node.style, v);
    else if (k.startsWith("on")) node.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "text") node.textContent = v;
    // HTML 布尔属性按“是否存在”解释，disabled="false" 仍会禁用按钮。
    // 对 DOM 自带属性直接赋布尔值，才能正确表达 false；checked 同理。
    else if (typeof v === "boolean" && k in node) node[k] = v;
    else if (v != null) node.setAttribute(k, v);
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
    throw new Error("网络请求失败：" + e.message);
  }
  let data = {};
  try {
    data = await resp.json();
  } catch (e) {
    /* 空响应 */
  }
  if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
  const method = String(opts.method || "GET").toUpperCase();
  if (method !== "GET") {
    if (path.startsWith("/profiles")) invalidateCachedJson("/ai_prompt_studio/profiles");
    if (path.startsWith("/supplements")) invalidateCachedJson("/ai_prompt_studio/supplements");
    if (path.startsWith("/settings")) invalidateCachedJson("/ai_prompt_studio/status");
  }
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
