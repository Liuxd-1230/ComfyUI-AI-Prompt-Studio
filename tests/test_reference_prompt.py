import pytest


def test_qwen_reference_tokens_and_manifest(ext):
    node = ext.NODE_CLASS_MAPPINGS["APS_ReferencePrompt"]()
    prompt, manifest, summary, count = node.build(
        "让@图1中的人物穿上@图2的衣服", "qwen_image_edit_2511",
        image_1=object(), image_2=object())
    assert prompt == "让Figure 1中的人物穿上Figure 2的衣服"
    assert count == 2
    assert len(manifest["assets"]) == 2
    assert "图2 → Figure 2" in summary


def test_h3_reference_token(ext):
    node = ext.NODE_CLASS_MAPPINGS["APS_ReferencePrompt"]()
    prompt, _, _, count = node.build("从@图1开始运镜", "minimax_h3", image_1=object())
    assert prompt == "从<Picture 1>开始运镜"
    assert count == 1


def test_missing_connected_image_is_readable(ext):
    node = ext.NODE_CLASS_MAPPINGS["APS_ReferencePrompt"]()
    with pytest.raises(ValueError, match="image_2 未连接"):
        node.build("参考@图2", "qwen_image_edit_2511")


def test_sparse_slot_is_renumbered_by_used_connection_order(ext):
    node = ext.NODE_CLASS_MAPPINGS["APS_ReferencePrompt"]()
    prompt, manifest, _, count = node.build(
        "只参考@图2", "qwen_image_edit_2511", image_2=object())
    assert prompt == "只参考Figure 1"
    assert count == 1
    assert manifest["assets"][0]["h3_labels"] == ["Picture 1"]
