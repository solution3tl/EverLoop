"""
可拆卸插件管理器 - 所有 harness_framework 组件以插件形式注册
系统可以在不重启、不修改核心代码的情况下随时挂载或卸载任意插件
"""
from typing import Dict, List, Optional, Set, Type, Any
from dataclasses import dataclass, field


@dataclass
class PluginSpec:
    name: str
    plugin_class: Optional[Type] = None
    enabled_by_default: bool = True
    depends_on: List[str] = field(default_factory=list)
    description: str = ""
    instance: Any = None  # 已实例化的对象


# 全局注册表
PLUGIN_REGISTRY: Dict[str, PluginSpec] = {}
ACTIVE_PLUGINS: Set[str] = set()


def register_plugin(
    name: str,
    plugin_class: Type = None,
    enabled_by_default: bool = True,
    depends_on: List[str] = None,
    description: str = "",
    instance: Any = None,
):
    """注册插件"""
    spec = PluginSpec(
        name=name,
        plugin_class=plugin_class,
        enabled_by_default=enabled_by_default,
        depends_on=depends_on or [],
        description=description,
        instance=instance,
    )
    PLUGIN_REGISTRY[name] = spec
    if enabled_by_default:
        ACTIVE_PLUGINS.add(name)


def enable_plugin(name: str) -> Dict:
    """启用插件"""
    if name not in PLUGIN_REGISTRY:
        return {"success": False, "message": f"插件 {name} 不存在"}

    spec = PLUGIN_REGISTRY[name]

    # 检查依赖
    for dep in spec.depends_on:
        if dep not in ACTIVE_PLUGINS:
            return {"success": False, "message": f"依赖插件 {dep} 未启用，请先启用"}

    ACTIVE_PLUGINS.add(name)
    return {"success": True, "message": f"插件 {name} 已启用"}


def disable_plugin(name: str) -> Dict:
    """
    禁用插件（检查无其他插件依赖此插件）
    被 deterministic_linter 在自动降级时调用
    """
    if name not in PLUGIN_REGISTRY:
        return {"success": False, "message": f"插件 {name} 不存在"}

    # 检查是否有其他活跃插件依赖此插件
    for pname, spec in PLUGIN_REGISTRY.items():
        if pname in ACTIVE_PLUGINS and name in spec.depends_on:
            return {
                "success": False,
                "message": f"插件 {pname} 依赖 {name}，无法禁用",
            }

    ACTIVE_PLUGINS.discard(name)
    return {"success": True, "message": f"插件 {name} 已禁用"}


def get_active_plugin(name: str) -> Any:
    """
    获取已激活的插件实例。
    未激活或不存在则返回 None（调用方需做 None 判断，确保插件缺失时系统降级而非崩溃）
    """
    if name not in ACTIVE_PLUGINS:
        return None
    spec = PLUGIN_REGISTRY.get(name)
    if spec is None:
        return None
    if spec.instance is not None:
        return spec.instance
    if spec.plugin_class is not None:
        spec.instance = spec.plugin_class()
        return spec.instance
    return None


def list_plugins() -> List[Dict]:
    """列出所有插件及其状态"""
    result = []
    for name, spec in PLUGIN_REGISTRY.items():
        result.append({
            "name": name,
            "enabled": name in ACTIVE_PLUGINS,
            "description": spec.description,
            "depends_on": spec.depends_on,
        })
    return result


def _register_default_plugins():
    """注册所有默认插件"""
    from harness_framework.context_optimizer import ContextOptimizer
    from harness_framework.deterministic_linter import DeterministicLinter
    from harness_framework.sandwich_reasoning import SandwichReasoning
    from harness_framework.isolation_guard import IsolationGuard

    register_plugin(
        "context_optimizer",
        plugin_class=ContextOptimizer,
        enabled_by_default=True,
        description="上下文压缩优化器，防止长文档导致模型注意力衰退",
    )
    register_plugin(
        "deterministic_linter",
        plugin_class=DeterministicLinter,
        enabled_by_default=True,
        description="架构约束执行器，对 Agent 输出做格式和安全性校验",
    )
    register_plugin(
        "sandwich_reasoning",
        plugin_class=SandwichReasoning,
        enabled_by_default=False,  # 默认关闭，按需开启
        description="三明治推理算力分配器（规划→执行→验证），适合复杂代码生成任务",
        depends_on=["deterministic_linter"],
    )
    register_plugin(
        "isolation_guard",
        plugin_class=IsolationGuard,
        enabled_by_default=True,
        description="上下文隔离墙，防止子 Agent 认知污染父 Agent",
    )


# 启动时注册
try:
    _register_default_plugins()
except Exception:
    pass  # 首次 import 时依赖模块可能还未就绪，延迟注册
