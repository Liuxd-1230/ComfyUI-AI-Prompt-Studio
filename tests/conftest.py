"""pytest 公共夹具：以 ComfyUI 方式加载扩展，测试统一通过 aps.* 命名空间访问。

注意：项目内部使用相对导入（ComfyUI 加载器要求），所以测试不能把子包当顶层包导入
（否则会触发「relative import beyond top-level package」且产生重复模块实例）。
统一走 aps.schemas / aps.server / aps.services / aps.nodes。
"""
import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXT_NAME = "aps_extension_test"

# 先加载扩展根模块（ComfyUI 加载器语义：spec_from_file_location）
if EXT_NAME not in sys.modules:
    sys.path.insert(0, str(PROJECT_ROOT))
    spec = importlib.util.spec_from_file_location(EXT_NAME, str(PROJECT_ROOT / "__init__.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[EXT_NAME] = mod
    spec.loader.exec_module(mod)

import aps_extension_test as aps  # noqa: E402

# 让测试模块可以写 `import aps.schemas` / `from aps.server.config_store import ...`
sys.modules["aps"] = aps

# 关键：把 aps_extension_test.* 的全部子模块同步注册为 aps.*。
# 否则 `import aps.schemas` 会按 sys.path 重新加载出一棵重复模块树，
# 导致 config_store 单例、Schema 类身份不一致（测试互相矛盾）。
for _name, _mod in list(sys.modules.items()):
    if _name.startswith(EXT_NAME + "."):
        sys.modules["aps" + _name[len(EXT_NAME):]] = _mod


@pytest.fixture(scope="session")
def ext():
    return aps


@pytest.fixture()
def store(tmp_path):
    from aps.server.config_store import reset_store_for_tests

    return reset_store_for_tests(tmp_path / "cfg")


@pytest.fixture()
def storyboard():
    """一个两场景、三镜头的分镜夹具。"""
    from aps.schemas.storyboard import Beat, Scene, Shot, Storyboard

    s1 = Scene(scene_id="s1", index=1, title="进门", synopsis="少女走进咖啡店",
               location="咖啡店", characters=["c1"])
    s1.shots.append(Shot(shot_id="s1sh1", index=1, summary="全景",
                         action="少女推门而入", characters=["c1"], beats=[Beat(beat_id="b1", text="开门声")]))
    s1.shots.append(Shot(shot_id="s1sh2", index=2, summary="中景",
                         action="少女走向柜台", characters=["c1"]))
    s2 = Scene(scene_id="s2", index=2, title="落座", synopsis="点单后落座",
               location="咖啡店", characters=["c1", "c2"])
    s2.shots.append(Shot(shot_id="s2sh1", index=1, summary="特写",
                         action="咖啡杯被放上桌面", characters=["c1", "c2"]))
    return Storyboard(story_id="story_1", title="咖啡店", split_mode="shot",
                      characters=["c1", "c2"], scenes=[s1, s2])
