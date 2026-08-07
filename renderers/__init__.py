"""渲染器分发：按目标家族选择 renderer。"""

from .anima import AnimaRenderResult, render_anima
from .generic import render_generic

__all__ = ["render_anima", "render_generic", "AnimaRenderResult"]
