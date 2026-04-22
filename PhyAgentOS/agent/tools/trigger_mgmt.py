"""触发器管理工具 — 智能体通过工具调用管理触发器的统一接口。

提供单一 ``trigger`` 工具，通过 ``action`` 参数区分操作：
- list:列出当前环境中所有可见触发器
- status:   查看单个触发器的详细状态
- create:   创建新触发器（环境侧校验）
- modify:   修改触发器的描述或实现
- rename:   重命名触发器
- delete:   删除触发器
- set_state: 设置触发器状态（active/muted/inactive）
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PhyAgentOS.agent.tools.base import Tool

if TYPE_CHECKING:
    from PhyAgentOS.triggers.registry import TriggerRegistry


class TriggerManagementTool(Tool):
    """触发器管理的统一工具调用接口。

    智能体通过此工具对触发器进行增删改查和状态管理。
    所有写操作都经过环境侧安全校验。
    """

    def __init__(self, registry: "TriggerRegistry | None" = None) -> None:
        self._registry = registry
        self._session_key: str = "cli:direct"

    def set_context(self, channel: str, chat_id: str) -> None:
        """设置当前会话上下文（由AgentLoop 在每轮调用前设置）。"""
        self._session_key = f"{channel}:{chat_id}"

    @property
    def name(self) -> str:
        return "trigger"

    @property
    def description(self) -> str:
        return (
            "管理触发器环境中的触发器。支持操作: "
            "list（列出）、status（状态）、create（创建）、"
            "modify（修改）、rename（重命名）、delete（删除）、"
            "set_state（设置状态）。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "status", "create", "modify",
                             "rename", "delete", "set_state"],
                    "description": "要执行的操作类型",
                },
                "name": {
                    "type": "string",
                    "description": "触发器名称（create/status/modify/rename/delete/set_state 时需要）",
                },
                "new_name": {
                    "type": "string",
                    "description": "新名称（仅 rename 时需要）",
                },
                "state": {
                    "type": "string",
                    "enum": ["active", "muted", "inactive"],
                    "description": "目标状态（仅 set_state 时需要）",
                },
                "description": {
                    "type": "string",
                    "description": "触发器描述（create/modify 时可用）",
                },
                "watched_observations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "监听的观测键列表（create/modify 时可用）",
                },
                "allowed_actions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "允许触发的动作类型列表（create/modify 时可用）",
                },
                "code": {
                    "type": "string",
                    "description": "触发器的on_tick 实现代码（create/modify 时可用，Python async 函数体）",
                },
                "filter_state": {
                    "type": "string",
                    "enum": ["active", "muted", "inactive"],
                    "description": "按状态过滤（仅 list 时可用）",
                },
                "detail": {
                    "type": "boolean",
                    "description": "是否返回详细信息（仅 list 时可用）",
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str, **kwargs: Any) -> str:
        """执行触发器管理操作。"""
        if not self._registry:
            return "Error: 触发器注册表未配置。"

        instance = self._registry.get_instance(self._session_key)

        if action == "list":
            return self._action_list(instance, kwargs)
        elif action == "status":
            return self._action_status(instance, kwargs)
        elif action == "create":
            return self._action_create(instance, kwargs)
        elif action == "modify":
            return self._action_modify(instance, kwargs)
        elif action == "rename":
            return self._action_rename(instance, kwargs)
        elif action == "delete":
            return self._action_delete(instance, kwargs)
        elif action == "set_state":
            return self._action_set_state(instance, kwargs)
        else:
            return f"Error: 未知操作 '{action}'。支持: list, status, create, modify, rename, delete, set_state"

    # ------------------------------------------------------------------
    # 各操作的具体实现
    # ------------------------------------------------------------------

    def _action_list(self, instance, kwargs: dict) -> str:
        if not instance:
            envs = self._registry.list_available() if self._registry else []
            return f"当前会话无活跃环境。可用环境: {', '.join(envs) or '(无)'}"

        from PhyAgentOS.triggers.trigger import TriggerState
        filter_state = None
        if fs := kwargs.get("filter_state"):
            filter_state = TriggerState(fs)

        triggers = instance.list_triggers(
            agent_visible_only=True,
            state_filter=filter_state,
)
        if not triggers:
            return "没有匹配的触发器。"

        detail = kwargs.get("detail", False)
        lines = [f"环境 '{instance.name}' 中的触发器 ({len(triggers)} 个):"]
        icons = {"active": "🟢", "muted": "🔇", "inactive": "⭕"}
        for t in triggers:
            icon = icons.get(t["state"], "❓")
            line = f"{icon} {t['name']} [{t['state']}]"
            if detail:
                line += f" — {t.get('description') or '(无描述)'}"
                line += f" | 监听: {t['watched_observations'] or '全部'}"
                line += f" | 动作: {t['allowed_actions'] or '全部'}"
            lines.append(line)
        return "\n".join(lines)

    def _action_status(self, instance, kwargs: dict) -> str:
        name = kwargs.get("name")
        if not name:
            return "Error: status 操作需要 name 参数。"
        if not instance:
            return "当前会话无活跃环境。"
        trigger = instance.get_trigger(name)
        if not trigger:
            return f"触发器 '{name}' 不存在。"
        if not trigger.is_agent_visible:
            return f"触发器 '{name}' 不可访问。"
        return(
            f"触发器: {trigger.name} (id={trigger.trigger_id})\n"
            f"状态: {trigger.state.value}\n"
            f"描述: {trigger.description or '(无)'}\n"
            f"监听: {trigger.watched_observations or '(全部)'}\n"
            f"动作: {trigger.allowed_actions or '(全部)'}\n"
            f"可见: {trigger.is_agent_visible}\n"
            f"可改: {trigger.is_agent_modifiable}\n"
            f"可启: {trigger.is_agent_startable}"
        )

    def _action_create(self, instance, kwargs: dict) -> str:
        name = kwargs.get("name")
        if not name:
            return "Error: create 操作需要 name 参数。"
        if not instance:
            return "当前会话无活跃环境，无法创建触发器。"

        from PhyAgentOS.triggers.trigger import FunctionTrigger, TriggerContext

        # 如果提供了代码，编译为函数
        code = kwargs.get("code")
        if code:
            try:
                # 将代码编译为 async 函数
                func_code = f"async def _trigger_fn(ctx):\n"
                for line in code.split("\n"):
                    func_code += f"    {line}\n"
                local_ns: dict[str, Any] = {}
                exec(func_code, {"__builtins__": __builtins__}, local_ns)  # noqa: S102
                fn = local_ns["_trigger_fn"]
            except Exception as e:
                return f"Error: 代码编译失败: {e}"
        else:
            # 创建一个空的占位触发器
            async def fn(ctx: TriggerContext) -> None:
                pass

        trigger = FunctionTrigger(
            fn=fn,
            name=name,
            description=kwargs.get("description", ""),
            watched_observations=kwargs.get("watched_observations", []),
            allowed_actions=kwargs.get("allowed_actions", []),
        )

        try:
            tid = instance.add_trigger(trigger)
            return f"触发器 '{name}' 创建成功 (id={tid})。"
        except (ValueError, PermissionError) as e:
            return f"Error: 创建失败: {e}"

    def _action_modify(self, instance, kwargs: dict) -> str:
        name = kwargs.get("name")
        if not name:
            return "Error: modify 操作需要 name 参数。"
        if not instance:
            return "当前会话无活跃环境。"
        trigger = instance.get_trigger(name)
        if not trigger:
            return f"触发器 '{name}' 不存在。"
        if not trigger.is_agent_modifiable:
            return f"Error: 触发器 '{name}' 不可修改（权限限制）。"

        modified = []
        if "description" in kwargs:
            trigger.description = kwargs["description"]
            modified.append("描述")
        if "watched_observations" in kwargs:
            trigger.watched_observations = kwargs["watched_observations"]
            modified.append("监听列表")
        if "allowed_actions" in kwargs:
            trigger.allowed_actions = kwargs["allowed_actions"]
            modified.append("动作列表")

        if not modified:
            return "未提供要修改的字段。"
        return f"触发器 '{name}' 已修改: {', '.join(modified)}"

    def _action_rename(self, instance, kwargs: dict) -> str:
        name = kwargs.get("name")
        new_name = kwargs.get("new_name")
        if not name or not new_name:
            return "Error: rename 操作需要 name 和 new_name 参数。"
        if not instance:
            return "当前会话无活跃环境。"
        trigger = instance.get_trigger(name)
        if trigger and not trigger.is_agent_modifiable:
            return f"Error: 触发器 '{name}' 不可修改（权限限制）。"
        try:
            if instance.rename_trigger(name, new_name):
                return f"触发器 '{name}' 已重命名为 '{new_name}'。"
            return f"触发器 '{name}' 不存在。"
        except ValueError as e:
            return f"Error: 重命名失败: {e}"

    def _action_delete(self, instance, kwargs: dict) -> str:
        name = kwargs.get("name")
        if not name:
            return "Error: delete 操作需要 name 参数。"
        if not instance:
            return "当前会话无活跃环境。"
        trigger = instance.get_trigger(name)
        if not trigger:
            return f"触发器 '{name}' 不存在。"
        if not trigger.is_agent_modifiable:
            return f"Error: 触发器 '{name}' 不可删除（权限限制）。"
        instance.remove_trigger(name)
        return f"触发器 '{name}' 已删除。"

    def _action_set_state(self, instance, kwargs: dict) -> str:
        name = kwargs.get("name")
        state_str = kwargs.get("state")
        if not name or not state_str:
            return "Error: set_state 操作需要 name 和 state 参数。"
        if not instance:
            return "当前会话无活跃环境。"

        from PhyAgentOS.triggers.trigger import TriggerState
        state_map = {
            "active": TriggerState.ACTIVE,
            "muted": TriggerState.MUTED,
            "inactive": TriggerState.INACTIVE,
        }
        if state_str not in state_map:
            return f"Error: 无效状态 '{state_str}'。可选: active, muted, inactive"

        trigger = instance.get_trigger(name)
        if trigger and not trigger.is_agent_startable:
            return f"Error: 触发器 '{name}' 不可启动/停止（权限限制）。"

        if instance.set_trigger_state(name, state_map[state_str]):
            return f"触发器 '{name}' 状态已设为 {state_str}。"
        return f"触发器 '{name}' 不存在。"
