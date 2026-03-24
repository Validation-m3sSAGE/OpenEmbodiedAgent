---
name: robot-management-guideline
description: robot-management-guideline
---

# Robot Control & Environment Configuration Skill

## 1. Introduction

This SKILL equips you with the capability to configure environments for physical robots from scratch, run demonstration code, and program trajectory controls.

## 2. Core Workflows

When tasked with configuring a new robot or controlling an existing one, follow these workflows **in order**. Each phase has a dedicated reference file — **read it before proceeding**.

| Phase | Content | Reference |
|-------|---------|-----------|
| 0 | **Hardware Audit** — Confirm physical parameters before writing any code | `references/00_hardware_audit.md` |
| 1 | **Environment Setup** — Docs, virtual envs, demo execution | `references/01_environment_setup.md` |
| 2 | **Skill Generation & Memory** — Create/update the robot's SKILL immediately | `references/02_skill_generation_and_memory.md` |
| 3 | **Tool Library Design** — Build reusable utilities before task scripts | `references/03_tool_library_design.md` |
| 4 | **Trajectory & Execution** — Motion control, verification, recovery | `references/04_trajectory_and_execution.md` |
| 5 | **Safety Guidelines** — When to act autonomously vs. ask for confirmation | `references/05_safety_guidelines.md` |
| 6 | **Workspace Management** — Script organization, cleanup, security | `references/06_workspace_and_security.md` |

## 3. General Rules

- **Hardware first, code second.** Never write motion or perception code before completing Phase 0.
- **Read the SKILL before acting.** If a robot-specific SKILL exists, read it entirely before writing any new script.
- **Use the tool library.** If a utility function (move, capture, detect) already exists in the project's `scripts/` directory, call it — do not rewrite it.
- **One variable at a time.** When debugging, change exactly one parameter per experiment.
- **Log failures immediately.** Update `LESSONS.md` after every failed attempt, not at the end of the session.
- **Check references.** Do not guess the workflow — the answer is usually in `references/`.
