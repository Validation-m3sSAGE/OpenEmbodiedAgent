"""Triggers package — external hooks management for PhyAgentOS.

This package implements a real-time monitoring, asynchronous injection,
safety-constrained, customizable external Hooks management system.

Key concepts
------------
- **TriggerEnvironment**: An external environment that provides observation
  spaces (what can be monitored) and action spaces (what effects can be
  fired).  Each environment runs independently of the agent lifecycle.

- **Trigger**: A monitoring unit that watches specific observation points
  and fires specific actions when conditions are met.  Triggers are
  the agent's customizable hooks into external environments.

- **TriggerRegistry**: Manages registered environments, active sessions,
  and trigger lifecycle.

- **TriggerBuffer**: Per-session message buffer that queues trigger
  messages before they are flushed into the agent's conversation context.

Architecture layers
-------------------
Triggers.Messaging (agent-facing, same level as Tools)
Manages the session message buffer, priorities, watermarks,
    dropped/muted semantics, and the agent-wakeup trigger.

Triggers.Runtime (execution-facing, same level as Exec/MCP)
    Manages environment lifecycle, observation monitoring, action
    execution, trigger lifecycle, and remote gRPC bridging.

Replaces
--------
Formerly known as 'Missions' in earlier protocol drafts.  Renamed to
better reflect the external-hooks-management nature of the system:
- Mission → TriggerEnvironment
- Worker→ Trigger
- Missions package → triggers package
"""

from PhyAgentOS.triggers.base import TriggerEnvironment
from PhyAgentOS.triggers.trigger import BaseTrigger, TriggerContext, TriggerState
from PhyAgentOS.triggers.buffer import TriggerBuffer, TriggerBufferManager, BufferFullError
from PhyAgentOS.triggers.registry import TriggerRegistry, EnvironmentSession

__all__ = [
    "TriggerEnvironment",
    "BaseTrigger",
    "TriggerContext",
    "TriggerState",
    "TriggerBuffer",
    "TriggerBufferManager",
    "BufferFullError",
    "TriggerRegistry",
    "EnvironmentSession",
]
