# Phase 2: Skill Generation and Memory Management

To ensure persistent memory and avoid repeating the same configuration process for the same robot brand in the future, you must act as a maintainer of your own knowledge base.

## 0. Before You Start — Read First (MANDATORY)

**Before writing any new script or issuing any motion command**, check if a robot-specific SKILL already exists:

1. Search the skills directory for a SKILL matching this robot/project.
2. If found, **read it entirely** before proceeding. Pay special attention to:
   - Known hardware offsets and quirks
   - Verified coordinate system directions
   - Working script examples
   - The Troubleshooting / Lessons Learned section
3. If the SKILL is outdated or incomplete, update it as you work.

Skipping this step is the single most common cause of repeating solved problems.

## 1. When to Generate the Skill

- **Immediately after reading the project's README** (before running the complex demo), invoke your **native SKILL creation tool** to generate a new SKILL specifically dedicated to this robot brand (e.g., `brandX_robot_manual`).

## 2. Content of the Generated Skill

When generating this new SKILL, ensure it contains:

1. **Hardware Parameters:** Valid sensor ranges, joint limits, coordinate system directions (verified, not assumed), known hardware offsets.
2. **Source Links:** The URL of the official documentation or GitHub repository.
3. **Local Paths:** Absolute paths to the cloned repository, model weights, calibration files, and the tool library.
4. **Conda Environments:** Which environment to use for which task (control vs. vision).
5. **Boot & Config Process:** Step-by-step instructions to activate the environment, start drivers, and run the basic demo.
6. **Tool Library Reference:** List of available utility modules and their key functions.
7. **Verified Poses:** Named poses (home, observe, pre-grasp) with confirmed coordinates.

## 3. Continuous Updating (Lessons Learned)

- **Treat this new SKILL as your long-term memory.**
- Every time a terminal command fails and you find a workaround, **immediately** update the SKILL's Troubleshooting section.
- Do not wait until the end of the session — context is lost if the session ends unexpectedly.
- The update should include: exact error message, root cause, and the fix.
