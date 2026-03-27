# OpenEmbodiedAgent (OEA) 用户开发手册

> **版本**: 0.0.5 | **状态**: 草案 (Draft)

## 1. 简介

欢迎使用 OpenEmbodiedAgent (OEA) 用户开发手册。本文档旨在指导开发者如何基于 OEA 框架进行二次开发，包括但不限于：
*   开发新的硬件驱动 (Driver)
*   编写自定义技能 (Skill)
*   集成外部感知模块 (Perception)
*   使用 Fleet 模式进行多机器人协同开发

## 2. 架构概览

OEA 采用“认知-物理解耦”的架构，通过 Markdown 文件（Workspace API）作为软硬件通信的唯一桥梁。

*   **Track A (软件大脑)**: 负责推理、规划、记忆和多智能体协同。
*   **Track B (硬件小脑)**: 负责解析 `ACTION.md`，驱动物理或仿真硬件，并更新 `ENVIRONMENT.md`。

## 3. 开发新硬件驱动 (Driver)

### 3.1 BaseDriver 接口
所有硬件驱动必须继承 `hal.base_driver.BaseDriver` 并实现以下核心方法：
*   `get_profile_path()`: 返回该硬件的 `EMBODIED.md` 配置文件路径。
*   `load_scene(scene)`: 初始化场景。
*   `execute_action(action_type, params)`: 执行具体动作。
*   `get_scene()`: 获取当前环境状态。

### 3.2 注册驱动
在 `hal/drivers/__init__.py` 的 `DRIVER_REGISTRY` 中注册新驱动。

### 3.3 外部插件机制
对于不希望直接修改 OEA 核心代码的外部硬件，可以使用插件机制。
参考 `scripts/deploy_rekep_real_plugin.py` 了解如何动态加载外部驱动。

## 4. 编写自定义技能 (Skill)

技能 (Skill) 是 OEA 中可复用的认知方法论，存储在 `SKILL.md` 中。

### 4.1 技能结构
一个标准的 `SKILL.md` 应包含：
*   **技能描述**: 技能的目的和适用场景。
*   **前置条件**: 执行该技能所需的环境或硬件状态。
*   **执行步骤**: 详细的操作流程，通常表现为状态机或 DAG。
*   **异常处理**: 遇到常见错误时的恢复策略。

### 4.2 技能的跨本体迁移
编写技能时，应尽量使用高层语义约束（如“对齐”、“保持距离”），避免硬编码具体的关节角度，以实现跨硬件本体的零代码迁移。

## 5. 集成感知模块 (Perception)

OEA 提供了 `PerceptionService` 用于处理多模态传感器数据。

### 5.1 几何与语义融合
*   **GeometryPipeline**: 处理点云和里程计数据。
*   **SegmentationPipeline**: 处理图像语义分割。
*   **FusionPipeline**: 将几何与语义信息融合为 Scene-Graph。

### 5.2 更新 ENVIRONMENT.md
感知模块的最终输出应通过 `EnvironmentWriter` 写入 `ENVIRONMENT.md`，供 Planner Agent 读取。

## 6. Fleet 模式与多机器人协同

### 6.1 工作区拓扑
在 Fleet 模式下，工作区结构如下：
*   `workspaces/shared/`: 全局环境状态 (`ENVIRONMENT.md`) 和任务编排 (`TASK.md`)。
*   `workspaces/<robot_id>/`: 各机器人的本地动作指令 (`ACTION.md`) 和本体声明 (`EMBODIED.md`)。

### 6.2 Fleet Watchdog
使用 `tests/test_fleet_watchdog.py` 中的机制，可以同时管理多个机器人的看门狗进程。

## 7. 调试与测试

*   **日志**: 查看看门狗和 Agent 的控制台输出。
*   **状态检查**: 实时查看 `ACTION.md` 和 `ENVIRONMENT.md` 的内容。
*   **单元测试**: 运行 `pytest tests/` 执行框架的自动化测试。

---
*本文档仍在持续完善中，欢迎提交 PR 补充内容。*
