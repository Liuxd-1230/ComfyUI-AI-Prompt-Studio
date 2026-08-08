// MiniMax H3 导演工作台：在节点内编辑镜头草稿，再写回 text 输入。
import { app } from "../../scripts/app.js";

const byName = (node, name) => (node.widgets || []).find((w) => w.name === name);

function input(label, value = "", type = "text") {
  const wrap = document.createElement("label");
  wrap.className = "aps-director-field";
  const title = document.createElement("span");
  title.textContent = label;
  const el = document.createElement(type === "textarea" ? "textarea" : "input");
  if (type !== "textarea") el.type = type;
  el.value = value;
  wrap.append(title, el);
  return { wrap, el };
}

function shotCard(index, start = "", visual = "", camera = "", dialogue = "", audio = "", refs = "") {
  const card = document.createElement("div");
  card.className = "aps-director-shot";
  const head = document.createElement("div");
  head.className = "aps-director-shot-head";
  const heading = document.createElement("strong");
  heading.textContent = `Shot ${index}`;
  const remove = document.createElement("button");
  remove.textContent = "删除";
  remove.onclick = () => card.remove();
  head.append(heading, remove);
  const time = input(index === 1 ? "开始时间（Shot 1 固定无时间戳）" : "开始时间（秒）", start, "number");
  time.el.disabled = index === 1;
  time.el.step = "0.001";
  const fields = {
    visual: input("画面与动作", visual, "textarea"),
    camera: input("运镜（类型 / 幅度 / 速度 / 目标）", camera),
    dialogue: input("对白（语言、说话人 S1/S2、原文；画外音注明闭唇）", dialogue, "textarea"),
    audio: input("本镜头同步声音", audio),
    refs: input("本镜头生效引用（如 <Subject 1>, <Picture 1>）", refs),
  };
  card.dataset.index = String(index);
  card._directorFields = { time, ...fields };
  card.append(head, time.wrap, fields.visual.wrap, fields.camera.wrap,
              fields.dialogue.wrap, fields.audio.wrap, fields.refs.wrap);
  return card;
}

function parseDraft(text) {
  const source = String(text || "").trim();
  const empty = { style: "", subjects: "", soundscape: "", music: "", shots: [] };
  if (!source) return empty;
  if (!source.startsWith("[导演工作台｜")) {
    // 不理解的已有提示词绝不能丢弃：作为第一个镜头的画面原文带入。
    return { ...empty, shots: [{ visual: source }] };
  }
  const value = (name) => source.match(new RegExp(`^${name}：(.*)$`, "m"))?.[1]?.trim() || "";
  const parsed = {
    style: value("整体风格"), subjects: value("主体与参考"),
    soundscape: value("全局声景"), music: value("画外音乐"), shots: [],
  };
  const blocks = source.split(/\n(?=\[Shot \d+｜)/).slice(1);
  blocks.forEach((block, index) => {
    const field = (name) => block.match(new RegExp(`^${name}：(.*)$`, "m"))?.[1]?.trim() || "";
    const startText = block.match(/^\[Shot \d+｜([^\]]+)\]/)?.[1] || "";
    parsed.shots.push({
      start: index === 0 ? "" : (startText.match(/^([\d.]+)秒$/)?.[1] || ""),
      visual: field("画面与动作"), camera: field("运镜"), dialogue: field("对白"),
      audio: field("同步声音"), refs: field("生效引用"),
    });
  });
  return parsed;
}

function openWorkbench(node) {
  document.querySelector(".aps-director-overlay")?.remove();
  const overlay = document.createElement("div");
  overlay.className = "aps-director-overlay";
  const panel = document.createElement("div");
  panel.className = "aps-director-panel";
  const mode = byName(node, "mode")?.value || "T2VA";
  const duration = Number(byName(node, "duration")?.value || 10);
  const draft = parseDraft(byName(node, "text")?.value);
  panel.innerHTML = `<h2>MiniMax H3 导演工作台</h2>
    <p class="aps-muted">当前 ${mode} · ${duration.toFixed(2)} 秒。镜头必须在 4–15 秒范围内，Shot 1 无时间戳，后续时间严格递增。</p>`;
  const global = {
    style: input("整体视觉风格", draft.style),
    subjects: input("主体定义与参考来源", draft.subjects, "textarea"),
    soundscape: input("全局声景（全片静音才写 N/A）", draft.soundscape, "textarea"),
    music: input("画外音乐（乐器 / 速度 / 力度；没有则 N/A）", draft.music, "textarea"),
  };
  panel.append(global.style.wrap, global.subjects.wrap, global.soundscape.wrap, global.music.wrap);
  const shots = document.createElement("div");
  shots.className = "aps-director-shots";
  (draft.shots.length ? draft.shots : [{}]).forEach((shot, index) => {
    shots.append(shotCard(index + 1, shot.start, shot.visual, shot.camera,
                          shot.dialogue, shot.audio, shot.refs));
  });
  panel.append(shots);
  const actions = document.createElement("div");
  actions.className = "aps-director-actions";
  const add = document.createElement("button");
  add.textContent = "添加镜头";
  add.onclick = () => shots.append(shotCard(shots.children.length + 1));
  const cancel = document.createElement("button");
  cancel.textContent = "取消";
  cancel.onclick = () => overlay.remove();
  const apply = document.createElement("button");
  apply.textContent = "写回节点";
  apply.onclick = () => {
    const cards = [...shots.querySelectorAll(".aps-director-shot")];
    const meaningful = [global.style.el.value, global.subjects.el.value,
      global.soundscape.el.value, global.music.el.value,
      ...cards.flatMap((card) => Object.values(card._directorFields)
        .map((field) => field.el.value))].some((value) => String(value || "").trim());
    if (!meaningful) {
      window.alert("工作台还是空的，未覆盖节点中已有的提示词。");
      return;
    }
    const lines = [
      `[导演工作台｜${mode}｜${duration.toFixed(2)}秒]`,
      `整体风格：${global.style.el.value.trim()}`,
      `主体与参考：${global.subjects.el.value.trim()}`,
      `全局声景：${global.soundscape.el.value.trim()}`,
      `画外音乐：${global.music.el.value.trim()}`,
    ];
    cards.forEach((card, i) => {
      const f = card._directorFields;
      const start = i === 0 ? "无时间戳" : `${f.time.el.value || "未填写"}秒`;
      lines.push(`\n[Shot ${i + 1}｜${start}]`, `画面与动作：${f.visual.el.value.trim()}`,
        `运镜：${f.camera.el.value.trim()}`, `对白：${f.dialogue.el.value.trim()}`,
        `同步声音：${f.audio.el.value.trim()}`, `生效引用：${f.refs.el.value.trim()}`);
    });
    const text = byName(node, "text");
    if (text) text.value = lines.join("\n");
    node.setDirtyCanvas?.(true, true);
    overlay.remove();
  };
  actions.append(add, cancel, apply);
  panel.append(actions);
  overlay.append(panel);
  overlay.onclick = (event) => { if (event.target === overlay) overlay.remove(); };
  document.body.append(overlay);
}

app.registerExtension({
  name: "AI Prompt Studio H3 Director Workbench",
  nodeCreated(node) {
    if ((node.comfyClass || node.type) !== "APS_MiniMaxH3Director" || byName(node, "导演工作台")) return;
    node.addWidget("button", "导演工作台", null, () => openWorkbench(node), {
      serialize: false,
    });
  },
});
