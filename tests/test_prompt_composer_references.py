"""专用图像模型的引用编号必须与实际清单一致。"""

from aps.nodes.prompt_composer import _validate_special
from aps.schemas.references import AssetRef, ReferenceManifest


def test_qwen_rejects_figure_number_not_in_manifest():
    manifest = ReferenceManifest(assets=[
        AssetRef(asset_id="img1", asset_type="image", note="Figure 1")])
    report = _validate_special("把 Figure 3 的衣服换给 Figure 1", "qwen_image_edit", manifest)
    assert any(issue.code == "missing_figure" for issue in report.issues)


def test_qwen_accepts_connected_figure_number():
    manifest = ReferenceManifest(assets=[
        AssetRef(asset_id="img1", asset_type="image", note="Figure 1")])
    report = _validate_special("修改 Figure 1", "qwen_image_edit", manifest)
    assert report.valid
