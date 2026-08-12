"""节点 6：Storyboard Select / Batch —— 从分镜选择场景/镜头，为批处理提供单项或列表。

不调用模型；纯确定性选择逻辑（Phase 1 即完整实现）。
"""

import json
import re

from ..schemas import types
from ..schemas.storyboard import SELECT_MODES, Scene, Shot, StoryItem, StoryItemList, Storyboard


def _shot_text(shot: Shot) -> str:
    parts = []
    if shot.summary:
        parts.append(f"概述：{shot.summary}")
    if shot.action:
        parts.append(f"动作：{shot.action}")
    parts.append(f"机位：{shot.camera or '未指定'}")
    parts.append(f"时长：{shot.duration:g}s")
    if shot.audio:
        parts.append(f"声音：{'、'.join(shot.audio)}")
    for b in shot.beats:
        if b.text:
            parts.append(f"{b.kind}：{b.text}")
        if b.audio:
            parts.append(f"节拍声音：{'、'.join(b.audio)}")
    return "\n".join(p for p in parts if p)


def _scene_item(scene: Scene) -> StoryItem:
    shot_texts = [_shot_text(shot) for shot in scene.shots]
    shot_text = "\n\n".join(text for text in shot_texts if text)
    text = "\n".join(p for p in [scene.synopsis or scene.title, shot_text] if p)
    characters = list(scene.characters)
    for shot in scene.shots:
        for character_id in shot.characters:
            if character_id not in characters:
                characters.append(character_id)
    return StoryItem(
        item_id=scene.scene_id, kind="scene", scene_id=scene.scene_id, index=scene.index,
        title=scene.title, text=text, characters=characters,
        scene_title=scene.title, location=scene.location,
    )


def _shot_item(scene: Scene, shot: Shot) -> StoryItem:
    return StoryItem(
        item_id=shot.shot_id, kind="shot", scene_id=scene.scene_id, shot_id=shot.shot_id,
        index=shot.index, title=f"{scene.title} / {shot.summary or f'Shot {shot.index}'}",
        text=_shot_text(shot), characters=list(shot.characters),
        scene_title=scene.title, location=scene.location, camera=shot.camera,
    )


def _parse_range(range_text: str) -> list[int]:
    """解析 1-3 / 1,2,5 为 1 基索引列表。"""
    indexes: list[int] = []
    for token in (range_text or "").replace(" ", "").split(","):
        if not token:
            continue
        if "-" in token:
            a, _, b = token.partition("-")
            try:
                indexes.extend(range(int(a), int(b) + 1))
            except ValueError:
                raise ValueError(f"非法范围: {token!r}（应为 1-3 或 1,2,5）")
        else:
            try:
                indexes.append(int(token))
            except ValueError:
                raise ValueError(f"非法范围: {token!r}")
    return indexes


def _selection_index(value: str, kind: str) -> int | None:
    """把 1 / scene_01 / 场景1 / shot-2 / 镜头2 解析为一基序号。"""
    text = (value or "").strip().lower()
    if not text:
        return None
    label = "场景" if kind == "scene" else "镜头"
    match = re.fullmatch(
        rf"(?:{kind}|{label})?[\s_-]*0*(\d+)", text, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _available(items, id_attr: str) -> str:
    return "、".join(f"{index}:{getattr(item, id_attr)}"
                     for index, item in enumerate(items, start=1)) or "（空）"


def select_items(storyboard: Storyboard, select_mode: str,
                 scene_id: str = "", shot_id: str = "", range_text: str = ""):
    """返回 (items, single)。single 为第一项或 None。"""
    items: list[StoryItem] = []

    def flat_shots() -> list[tuple[Scene, Shot]]:
        return [(sc, sh) for sc in storyboard.scenes for sh in sc.shots]

    if select_mode == "scene":
        requested = _selection_index(scene_id, "scene")
        for position, sc in enumerate(storyboard.scenes, start=1):
            if scene_id and (sc.scene_id == scene_id or requested == position):
                items.append(_scene_item(sc))
                break
            if not scene_id:
                items.append(_scene_item(sc))
        if scene_id and not items:
            raise ValueError(
                f"未找到场景 {scene_id!r}；可填写序号 1-{len(storyboard.scenes)}，"
                f"或实际 ID。当前场景：{_available(storyboard.scenes, 'scene_id')}")
    elif select_mode == "shot":
        shots = flat_shots()
        requested = _selection_index(shot_id, "shot")
        for position, (sc, sh) in enumerate(shots, start=1):
            if shot_id and (sh.shot_id == shot_id or requested == position):
                items.append(_shot_item(sc, sh))
                break
            if not shot_id:
                items.append(_shot_item(sc, sh))
        if shot_id and not items:
            available = "、".join(
                f"{index}:{shot.shot_id}" for index, (_, shot) in enumerate(shots, start=1)
            ) or "（空）"
            raise ValueError(
                f"未找到镜头 {shot_id!r}；可填写扁平序号 1-{len(shots)}，"
                f"或实际 ID。当前镜头：{available}")
    elif select_mode == "range":
        shots = flat_shots()
        for idx in _parse_range(range_text):
            if 1 <= idx <= len(shots):
                sc, sh = shots[idx - 1]
                items.append(_shot_item(sc, sh))
        if not items:
            raise ValueError(f"范围内没有镜头: {range_text!r}")
    elif select_mode == "all":
        items = [_shot_item(sc, sh) for sc, sh in flat_shots()]
    else:
        raise ValueError(f"非法选择模式: {select_mode!r}")

    if not items:
        raise ValueError("没有匹配的镜头/场景")
    return items, items[0]


class APS_StoryboardSelect:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "storyboard": (types.STORYBOARD,),
            "select_mode": (SELECT_MODES, {"default": "all",
                                           "tooltip": "scene=按场景；shot=按镜头；range=镜头序号区间（1-3 / 1,2,5）；all=全部镜头"}),
            "scene_id": ("STRING", {"default": "", "tooltip": "scene 模式：填 1、scene_01 或实际场景 ID；留空选择全部场景"}),
            "shot_id": ("STRING", {"default": "", "tooltip": "shot 模式：填扁平序号 1、shot_01 或实际镜头 ID；留空选择全部镜头"}),
            "range": ("STRING", {"default": "", "tooltip": "select_mode=range 时的扁平镜头序号区间，如 1-3 或 1,2,5"}),
        }}

    RETURN_TYPES = (types.STORY_ITEM, types.STORY_ITEM_LIST, "STRING", "STRING", "INT",
                    types.STORY_ITEM)
    RETURN_NAMES = ("STORY_ITEM", "STORY_ITEM_LIST", "scene_text", "character_ids",
                    "batch_count", "STORY_ITEMS")
    OUTPUT_IS_LIST = (False, False, False, False, False, True)
    FUNCTION = "select"
    CATEGORY = "AI Prompt Studio"
    DESCRIPTION = "从分镜选择场景/镜头，输出单项或批处理列表（不调用模型）。"

    def select(self, storyboard, select_mode, scene_id, shot_id, range):
        sb = Storyboard.from_json(storyboard)
        items, single = select_items(sb, select_mode, scene_id, shot_id, range)
        item_list = StoryItemList(mode=select_mode, selection=range or scene_id or shot_id,
                                  story_id=sb.story_id, items=items)
        scene_text = single.text if single else ""
        chars = []
        for it in items:
            for c in it.characters:
                if c not in chars:
                    chars.append(c)
        return (single.to_json() if single else StoryItem().to_json(),
                item_list.to_json(),
                scene_text,
                json.dumps(chars, ensure_ascii=False),
                item_list.batch_count,
                [item.to_json() for item in items])
