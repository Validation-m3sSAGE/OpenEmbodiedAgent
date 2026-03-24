# Phase 5: Workspace Management and Script Organization

As an autonomous agent, you must maintain a clean, organized, and secure workspace. Do not leave temporary scripts scattered in the root directory.

## 1. Workspace Directory Management
- **Create a `WORKSPACE.md`:** Maintain a `WORKSPACE.md` file at `memory/WORKSPACE.md`. This file acts as a directory index.
- **Document Projects:** Every time you start working on a new robot or project, add an entry to `WORKSPACE.md` describing the project, its directory path, and its purpose.
- **Clean Up Proactively:** Do not wait until the end of a session. After each major phase (environment setup, first successful motion, etc.), move generated files into the appropriate project subdirectory.

## 2. Script Organization and Reusability
- **Project directory structure:**
  ```
  projects/<robot_task>/
    scripts/    ← successful, reusable scripts
    archive/    ← failed or experimental scripts (keep for reference)
    images/     ← captured images and depth data
  ```
- **Differentiate Scripts:** Clearly separate successful, reusable scripts from failed or experimental ones. Prefix failed scripts with `FAILED_` or move them to `archive/`.
- **Utilize the `scripts/` Directory of the SKILL:** When a script becomes stable and reusable, copy it into the robot's SKILL `scripts/` directory and document it in SKILL.md.
- **Handle Failed Scripts:** Do NOT delete failed scripts immediately — they contain valuable negative knowledge. Store them in `archive/` with a comment at the top explaining why they failed.

## 3. LESSONS.md — Mandatory Failure Logging
- The workspace contains a `LESSONS.md` file. **You MUST update it after every failed attempt**, not just at the end of the session.
- Each entry should include: date, what was tried, why it failed, and what to do instead.
- The Planner reads this file before proposing actions to avoid repeating mistakes.

## 4. Periodic Cleanup Reminders
- **After environment setup:** Create the project directory and WORKSPACE.md entry.
- **After first successful motion:** Move all probe/test scripts to `archive/`.
- **After a failed approach:** Log to LESSONS.md immediately.
- **At session end:** Ensure workspace root contains only system files (AGENTS.md, memory/, projects/, skills/, etc.), no loose scripts or images.

## 5. Security and Privacy (CRITICAL)
- **Prevent Data Leaks:** Before saving any script to a SKILL directory or uploading it anywhere, you MUST review the code for sensitive information.
- **Scrub Sensitive Data:** Ensure the script does NOT contain:
  - Host IP addresses (use `localhost`, `127.0.0.1`, or placeholders like `<ROBOT_IP>`).
  - Passwords, API keys, or authentication tokens.
  - Personal user data or specific local absolute paths that reveal user information (use relative paths or environment variables where possible).
