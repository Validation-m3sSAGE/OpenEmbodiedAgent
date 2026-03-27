# OpenEmbodiedAgent (OEA) 使用手册

> **版本**: 0.0.5 | **状态**: 草案 (Draft)

## 1. 简介

欢迎使用 OpenEmbodiedAgent (OEA) 使用手册。本文档旨在指导普通用户如何快速上手并使用 OEA 框架，包括：
*   环境配置与安装
*   启动单机仿真或物理机器人
*   使用自然语言与机器人交互
*   配置多机器人协同 (Fleet 模式)

## 2. 环境配置与安装

### 2.1 系统要求
*   Python 3.11 或更高版本
*   Git
*   (可选) PyBullet 用于仿真环境
*   (可选) ROS2 用于特定硬件驱动 (如 Go2)

### 2.2 安装步骤
1.  克隆 OEA 仓库：
    ```bash
    git clone https://github.com/your-repo/OpenEmbodiedAgent.git
    cd OpenEmbodiedAgent
    ```
2.  安装依赖：
    ```bash
    pip install -e .
    ```
3.  (可选) 安装仿真依赖：
    ```bash
    pip install watchdog pybullet
    ```

## 3. 快速启动 (单机模式)

### 3.1 初始化工作区
首次使用前，需要初始化 OEA 工作区：
```bash
OEA onboard
```
这将在 `~/.OEA/workspace/` 目录下生成核心的 Markdown 协议文件（如 `EMBODIED.md`, `ENVIRONMENT.md`）。

### 3.2 启动硬件看门狗 (Track B)
打开一个新终端，启动硬件看门狗。默认使用仿真驱动：
```bash
python hal/hal_watchdog.py
```
如果需要使用其他硬件，可以通过 `--driver` 参数指定，例如：
```bash
python hal/hal_watchdog.py --driver go2_edu
```

### 3.3 启动软件大脑 (Track A)
打开另一个新终端，启动 OEA Agent：
```bash
OEA agent
```

## 4. 与机器人交互

在 `OEA agent` 的命令行界面中，你可以使用自然语言向机器人下达指令。

### 4.1 基础指令示例
*   "看看桌子上有什么。" (Agent 会读取 `ENVIRONMENT.md` 并回复)
*   "把红色的苹果推到地上。" (Agent 会生成动作写入 `ACTION.md`，看门狗执行后更新环境)
*   "移动到厨房的桌子旁。" (使用语义导航工具)

### 4.2 复杂任务示例
*   "清理客厅：把地上的玩具捡起来放到收纳箱里，然后去厨房待命。" (Agent 会将任务拆解为多个子任务并依次执行)

## 5. 多机器人协同 (Fleet 模式)

OEA 支持同时管理多个异构机器人。

### 5.1 配置 Fleet 工作区
Fleet 模式使用 `~/.OEA/workspaces/` 目录，包含一个 `shared` 目录和多个机器人专属目录。

### 5.2 启动 Fleet Watchdog
使用 Fleet Watchdog 脚本同时启动多个机器人的驱动：
```bash
# 示例：启动一个仿真机械臂和一个 Go2 机器狗
python scripts/start_fleet.py --robots sim_arm:simulation go2_dog:go2_edu
```
*(注：`start_fleet.py` 脚本需根据实际项目结构提供)*

### 5.3 协同任务指令
在 Agent 界面中，你可以下达涉及多个机器人的指令：
*   "让 Go2 走到门口，然后让机械臂把包裹递给它。"

## 6. 常见问题与故障排除

*   **Q: Agent 提示找不到 EMBODIED.md？**
    *   A: 确保已运行 `OEA onboard`，并且看门狗已成功启动并加载了对应的 profile。
*   **Q: 机器人没有执行动作？**
    *   A: 检查看门狗终端的日志，确认是否收到了 `ACTION.md` 的更新，以及动作是否被 Critic 校验拒绝（查看 `LESSONS.md`）。
*   **Q: 如何添加新的 API Key？**
    *   A: 修改 `~/.OEA/config.json` 文件，在 `providers` 部分添加相应的配置。

---
*本文档仍在持续完善中，如有疑问请查阅开发者指南或提交 Issue。*
