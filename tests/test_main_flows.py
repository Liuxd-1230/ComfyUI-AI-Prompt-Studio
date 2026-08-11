"""High-value production flows across public nodes."""
from __future__ import annotations

import json

import numpy as np

import aps.nodes.llm_chat as llm_mod
import aps.nodes.prompt_studio as studio_mod
import aps.nodes.reference_analyzer as reference_mod
from aps.nodes.character_bible import APS_CharacterBible
from aps.schemas.attachments import Attachment, AttachmentList
from aps.schemas.character import CharacterBible
from aps.schemas.results import LLMResult


def _profile(store):
    store.create_profile({"profile_id": "flow", "name": "Flow"})
    store.set_api_key("flow", "sk-local")
    return store.get_profile("flow").node_payload()


def test_llm_generate_custom_system_and_text_attachment(monkeypatch, store) -> None:
    class Gateway:
        request = None

        def generate(self, profile, api_key, request):
            del profile, api_key
            type(self).request = request
            return LLMResult(text="模型回答")

    monkeypatch.setattr(llm_mod, "Gateway", Gateway)
    attachments = AttachmentList(attachments=[
        Attachment.from_text("附件数据内容", name="note.txt")])
    result = llm_mod.APS_LLMGenerate().generate(
        AI_PROFILE=_profile(store), system_prompt="You are a careful reviewer.",
        user_prompt="请总结", context="", session=None, history_mode="append",
        output_mode="text", json_schema="",
        attachments=json.dumps(attachments.to_json()))
    assert result[0] == "模型回答"
    assert "You are a careful reviewer." in Gateway.request.system
    assert Gateway.request.attachments[0].content == "附件数据内容"


def test_reference_to_bible_to_strict_anima_studio(monkeypatch, store) -> None:
    profile = _profile(store)
    class ReferenceGateway:
        def generate(self, profile, api_key, request):
            del profile, api_key, request
            return LLMResult(text=json.dumps({"name": "Rin", "traits": [{
                "name": "hair", "value": "long black hair",
                "category": "stable", "confidence": 0.9}]}))

    monkeypatch.setattr(reference_mod, "Gateway", ReferenceGateway)
    monkeypatch.setattr(reference_mod.vision_svc, "call_vision",
                        lambda *args, **kwargs: {"ok": True, "text": json.dumps({
                            "name": "Rin", "traits": [{
                                "name": "hair", "value": "long black hair",
                                "category": "stable", "confidence": 0.9}]}),
                            "raw": "raw"})
    analyzed = reference_mod.APS_ReferenceAnalyzer().analyze(
        AI_PROFILE=profile, analysis_mode="character_full",
        text_anchor="Rin, long black hair",
        images=[np.random.rand(8, 8, 3).astype(np.float32)],
        character_bible=None, custom_prompt="")
    bible_json = APS_CharacterBible().merge(
        merge_strategy="text_priority", character_candidate=analyzed[1])[0]
    bible = CharacterBible.from_json(bible_json)
    assert any(item.value == "long black hair" for item in bible.traits)

    class StudioGateway:
        def generate(self, profile, api_key, request):
            del profile, api_key, request
            return LLMResult(text=json.dumps({
                "content": {
                    "scene_description": "Rin waits beside a rain-streaked window.",
                    "characters": [{"character_id": bible.character_id,
                                    "name": "Rin",
                                    "required_traits": ["long black hair"],
                                    "action": "waiting"}],
                    "environment": ["quiet cafe"], "lighting": "warm light",
                }, "negative": "watermark"}))

    monkeypatch.setattr(studio_mod, "Gateway", StudioGateway)
    created = studio_mod.APS_PromptStudio().run(
        profile, "Rin waits in a cafe", "anima_base", "strict",
        character_bible=bible_json, message_nonce="flow-create")
    assert "Rin" in created["result"][0]
    assert "long black hair" in created["result"][0]
    assert "通过" in created["result"][3]
