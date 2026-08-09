"""Schema 基础：dataclass + 版本字段 + 迁移注册表 + JSON 往返 + 输入容错。

所有节点间传递的数据类型都必须继承 :class:`Schema`（dataclass 基类），
禁止在节点之间传递含义不明的任意字典（见 ADR-0001）。
"""

import dataclasses
import typing
from types import UnionType
from typing import Any, Callable, ClassVar, Dict, get_args, get_origin

SCHEMA_VERSION = "1.0"


class SchemaError(ValueError):
    """带可读信息的数据结构错误，面向节点用户而非开发者。"""


def _is_dataclass_type(t: Any) -> bool:
    return isinstance(t, type) and dataclasses.is_dataclass(t)


def to_json(obj: Any) -> Any:
    """把 dataclass / list / dict / 基本类型递归转为可 JSON 序列化的值。"""
    if obj is None:
        return None
    if dataclasses.is_dataclass(obj):
        return {f.name: to_json(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, (list, tuple)):
        return [to_json(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): to_json(v) for k, v in obj.items()}
    if isinstance(obj, (str, int, float, bool)):
        return obj
    # 兜底：datetime 等 → 字符串，保证可序列化
    return str(obj)


def _coerce(value: Any, ftype: Any, path: str = "$") -> Any:
    """按字段类型对输入值做容错转换：未知键忽略、缺失取默认、类型尽量收敛。

    转换失败时保留原值而不是抛异常，由上层 validate() 负责暴露问题，
    避免因单字段脏数据导致整个节点崩溃。
    """
    if value is None:
        return None
    origin = get_origin(ftype)
    args = get_args(ftype)

    if origin is typing.Union or origin is UnionType:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _coerce(value, non_none[0], path)
        return value
    if origin in (list, typing.List):
        if isinstance(value, (list, tuple)):
            item_type = args[0] if args else Any
            return [_coerce(v, item_type, path) for v in value]
        return value
    if origin in (dict, typing.Dict):
        if isinstance(value, dict):
            val_type = args[1] if len(args) > 1 else Any
            return {str(k): _coerce(v, val_type, path) for k, v in value.items()}
        return value
    if _is_dataclass_type(ftype):
        if isinstance(value, dict):
            try:
                return ftype.from_json(value)
            except (SchemaError, TypeError, ValueError):
                return value
        return value
    if ftype is str:
        return value if isinstance(value, str) else str(value)
    if ftype is bool:
        return value if isinstance(value, bool) else bool(value)
    if ftype is int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if ftype is float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    return value


@dataclasses.dataclass
class Schema:
    """所有 Schema 的基类。子类须为 dataclass 并继承本类。"""

    schema_version: str = SCHEMA_VERSION

    # 迁移注册表：{"1.0": {"1.1": fn(data)->data, ...}, ...}
    MIGRATIONS: ClassVar[Dict[str, Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]]] = {}
    CURRENT_SCHEMA_VERSION: ClassVar[str] = SCHEMA_VERSION

    def to_json(self) -> Dict[str, Any]:
        """序列化为可 JSON 化的 dict（含 schema_version）。"""
        return to_json(self)

    def to_json_string(self) -> str:
        import json

        return json.dumps(self.to_json(), ensure_ascii=False, indent=2)

    @classmethod
    def _migrate(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        version = str(data.get("schema_version", SCHEMA_VERSION))
        chain = cls.MIGRATIONS.get(version, {})
        for target in sorted(chain.keys()):
            fn = chain[target]
            try:
                data = fn(data)
            except Exception as exc:  # noqa: BLE001 - 迁移错误统一为 SchemaError
                raise SchemaError(
                    f"{cls.__name__}: 数据迁移 {version}->{target} 失败：{exc}"
                ) from exc
            version = target
        data["schema_version"] = cls.CURRENT_SCHEMA_VERSION
        return data

    @classmethod
    def from_json(cls, data: Any) -> "Schema":
        """容错反序列化：接受 None/dict/JSON 字符串/同类型实例。未知键忽略，缺失字段取默认。"""
        if isinstance(data, cls):
            return data
        if data is None:
            data = {}
        if isinstance(data, str):
            try:
                import json as _json
                parsed = _json.loads(data)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                data = parsed
        if not isinstance(data, dict):
            raise SchemaError(f"{cls.__name__}: 输入必须是对象，实际是 {type(data).__name__}")
        data = cls._migrate(dict(data))
        fields = {f.name: f for f in dataclasses.fields(cls)}
        kwargs: Dict[str, Any] = {}
        for name, f in fields.items():
            if name == "schema_version":
                continue
            if name in data:
                kwargs[name] = _coerce(data[name], f.type, f"{cls.__name__}.{name}")
            else:
                if f.default is not dataclasses.MISSING:
                    kwargs[name] = f.default
                elif f.default_factory is not dataclasses.MISSING:
                    kwargs[name] = f.default_factory()
                else:
                    kwargs[name] = None
        try:
            return cls(**kwargs)
        except TypeError as exc:
            raise SchemaError(f"{cls.__name__}: 无法构造：{exc}") from exc

    def validate(self) -> list[str]:
        """返回可读的问题列表；默认无问题。子类按需覆写。"""
        return []

    def issues_text(self) -> str:
        issues = self.validate()
        if not issues:
            return ""
        return "\n".join(f"- {i}" for i in issues)
