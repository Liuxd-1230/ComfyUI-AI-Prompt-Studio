// AI Prompt Studio 原创图片引用输入：在 APS_ReferencePrompt 的 prompt 文本框键入 @。
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const MENU_CLASS = "aps-reference-mention-menu";

function connectedReferences(node) {
  return (node.inputs || [])
    .map((input, slot) => ({ input, slot }))
    .filter(({ input }) => /^image_[1-3]$/.test(input.name) && input.link != null)
    .map(({ input, slot }) => {
      const link = app.graph.links[input.link];
      const origin = link ? app.graph.getNodeById(link.origin_id) : null;
      const number = Number(input.name.slice(-1));
      return { slot, number, origin, token: `@图${number}` };
    });
}

function previewUrl(origin) {
  const image = app.nodeOutputs?.[origin?.id]?.images?.[0];
  if (!image) return "";
  const query = new URLSearchParams({
    filename: image.filename,
    type: image.type || "output",
    subfolder: image.subfolder || "",
  });
  return api.apiURL(`/view?${query}`);
}

function removeMenu() {
  document.querySelectorAll(`.${MENU_CLASS}`).forEach((element) => element.remove());
}

function showMenu(node, widget, textarea) {
  removeMenu();
  const refs = connectedReferences(node);
  const menu = document.createElement("div");
  menu.className = MENU_CLASS;
  Object.assign(menu.style, {
    position: "fixed", zIndex: "10020", width: "260px", maxHeight: "260px",
    overflow: "auto", padding: "6px", border: "1px solid #46505d",
    borderRadius: "8px", background: "#171a1f", boxShadow: "0 10px 30px #0008",
  });
  const rect = textarea.getBoundingClientRect();
  menu.style.left = `${Math.min(rect.left, window.innerWidth - 280)}px`;
  menu.style.top = `${Math.min(rect.bottom + 4, window.innerHeight - 280)}px`;

  if (!refs.length) {
    const empty = document.createElement("div");
    empty.textContent = "先连接 image_1～image_3，再输入 @";
    Object.assign(empty.style, { padding: "10px", color: "#aeb7c4", fontSize: "12px" });
    menu.appendChild(empty);
  }
  for (const ref of refs) {
    const item = document.createElement("button");
    item.type = "button";
    Object.assign(item.style, {
      display: "flex", width: "100%", gap: "10px", alignItems: "center",
      border: "0", borderRadius: "6px", padding: "6px", color: "#eef2f7",
      background: "transparent", cursor: "pointer", textAlign: "left",
    });
    const url = previewUrl(ref.origin);
    if (url) {
      const image = document.createElement("img");
      image.src = url;
      Object.assign(image.style, { width: "46px", height: "46px", objectFit: "cover", borderRadius: "5px" });
      item.appendChild(image);
    }
    const label = document.createElement("span");
    label.textContent = `${ref.token} · ${ref.origin?.title || ref.origin?.type || "已连接图片"}`;
    item.appendChild(label);
    item.onmouseenter = () => { item.style.background = "#2a3039"; };
    item.onmouseleave = () => { item.style.background = "transparent"; };
    item.onkeydown = (event) => {
      const buttons = [...menu.querySelectorAll("button")];
      const index = buttons.indexOf(item);
      if (event.key === "ArrowDown") {
        event.preventDefault();
        buttons[(index + 1) % buttons.length]?.focus();
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        buttons[(index - 1 + buttons.length) % buttons.length]?.focus();
      } else if (event.key === "Escape") {
        removeMenu();
        textarea.focus();
      }
    };
    item.onclick = () => {
      const end = textarea.selectionStart;
      const start = Math.max(0, end - 1);
      const value = textarea.value;
      textarea.value = value.slice(0, start) + ref.token + value.slice(end);
      widget.value = textarea.value;
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      textarea.focus();
      textarea.setSelectionRange(start + ref.token.length, start + ref.token.length);
      app.graph.setDirtyCanvas(true, true);
      removeMenu();
    };
    menu.appendChild(item);
  }
  document.body.appendChild(menu);
}

app.registerExtension({
  name: "AI Prompt Studio.ReferenceMentions",
  async nodeCreated(node) {
    if ((node.comfyClass || node.type) !== "APS_ReferencePrompt") return;
    const widget = node.widgets?.find((candidate) => candidate.name === "prompt");
    const textarea = widget?.inputEl;
    if (!textarea) return;
    textarea.placeholder = "输入编辑指令；键入 @ 选择已连接图片";
    textarea.addEventListener("input", (event) => {
      const cursor = event.currentTarget.selectionStart;
      if (event.currentTarget.value[cursor - 1] === "@") showMenu(node, widget, event.currentTarget);
    });
    textarea.addEventListener("keydown", (event) => {
      if (event.key === "Escape") removeMenu();
      if (event.key === "ArrowDown") {
        const first = document.querySelector(`.${MENU_CLASS} button`);
        if (first) {
          event.preventDefault();
          first.focus();
        }
      }
    });
  },
});
