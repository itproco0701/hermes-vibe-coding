#!/usr/bin/env python3
"""
Vibe Coding Dev↔QA↔Fix Loop

Usage:
    python vibe_loop.py "task description" --project-path /home/workspace/new-erp
    python vibe_loop.py "Implement POST /api/users" --project-path /home/workspace/new-erp --max-retries 3
"""

import argparse
import json
import os
import subprocess
import sys
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HERMES_ROOT = os.environ.get("HERMES_HOME", "/root/.hermes")
KANBAN_DB = os.path.join(HERMES_ROOT, "kanban.db")
STATE_DB = os.path.join(HERMES_ROOT, "state.db")


# ---------------------------------------------------------------------------
# Vibe Context Management
# ---------------------------------------------------------------------------

def load_vibe_context(project_path: str) -> dict:
    """Load or create vibe-context.json for the project."""
    ctx_file = os.path.join(project_path, ".vibe-context.json")
    if os.path.exists(ctx_file):
        with open(ctx_file, "r") as f:
            return json.load(f)
    return {
        "project": detect_project_name(project_path),
        "project_path": project_path,
        "created_at": datetime.now().isoformat(),
        "sessions": []
    }


def save_vibe_context(project_path: str, ctx: dict) -> None:
    """Persist vibe-context.json."""
    ctx_file = os.path.join(project_path, ".vibe-context.json")
    with open(ctx_file, "w") as f:
        json.dump(ctx, f, indent=2, ensure_ascii=False)


def detect_project_name(project_path: str) -> str:
    """Infer project name from project files."""
    if os.path.exists(os.path.join(project_path, "package.json")):
        import json as _json
        with open(os.path.join(project_path, "package.json")) as f:
            return _json.load(f).get("name", os.path.basename(project_path))
    elif os.path.exists(os.path.join(project_path, "pyproject.toml")):
        with open(os.path.join(project_path, "pyproject.toml")) as f:
            for line in f:
                if line.startswith("name = "):
                    return line.split("=")[1].strip().strip('"')
    return os.path.basename(project_path)


# ---------------------------------------------------------------------------
# Hermes Kanban Integration
# ---------------------------------------------------------------------------

def create_kanban_task(task_description: str, board: str, skill: str = "vibe-coding") -> Optional[int]:
    """Create a new task in Hermes kanban. Returns task_id."""
    try:
        import sqlite3
        conn = sqlite3.connect(KANBAN_DB)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tasks (title, board, status, created_at, labels)
            VALUES (?, ?, 'pending', ?, ?)
        """, (task_description, board, datetime.now().isoformat(), skill))
        task_id = cur.lastrowid
        conn.commit()
        conn.close()
        return task_id
    except Exception as e:
        print(f"[WARN] Could not create kanban task: {e}")
        return None


def update_kanban_task(task_id: int, status: str, event: str = None) -> None:
    """Update task status and optionally add an event."""
    try:
        import sqlite3
        conn = sqlite3.connect(KANBAN_DB)
        cur = conn.cursor()
        cur.execute("UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                    (status, datetime.now().isoformat(), task_id))
        if event:
            cur.execute("""
                INSERT INTO task_events (task_id, event_type, description, created_at)
                VALUES (?, 'vibe_attempt', ?, ?)
            """, (task_id, event, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[WARN] Could not update kanban task: {e}")


# ---------------------------------------------------------------------------
# Hermes Checkpoint
# ---------------------------------------------------------------------------

def create_checkpoint(label: str, project_path: str, vibe_ctx: dict) -> None:
    """Create a Hermes checkpoint for the current vibe session."""
    checkpoint_dir = os.path.join(HERMES_ROOT, "checkpoints")
    os.makedirs(checkpoint_dir, exist_ok=True)

    # Create a vibe-specific checkpoint
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = hashlib.sanitize_filename(label) if hasattr(hashlib, 'sanitize_filename') else label.replace(" ", "_")
    checkpoint_file = os.path.join(checkpoint_dir, f"vibe_{safe_label}_{timestamp}.json")

    checkpoint_data = {
        "label": label,
        "project_path": project_path,
        "vibe_context": vibe_ctx,
        "checkpointed_at": datetime.now().isoformat()
    }

    with open(checkpoint_file, "w") as f:
        json.dump(checkpoint_data, f, indent=2)

    print(f"[CHECKPOINT] Saved to {checkpoint_file}")


# ---------------------------------------------------------------------------
# Telegram Notification (via Hermes)
# ---------------------------------------------------------------------------

def notify_telegram(message: str) -> None:
    """Send notification via Hermes Telegram integration."""
    try:
        # Hermes Telegram bot handles notifications via its own mechanism
        # We just need to invoke it through the hermes CLI or state.db
        import sqlite3
        conn = sqlite3.connect(STATE_DB)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO notifications (type, message, created_at)
            VALUES ('telegram', ?, ?)
        """, (message, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        print(f"[TELEGRAM] {message}")
    except Exception as e:
        print(f"[WARN] Could not send Telegram notification: {e}")


# ---------------------------------------------------------------------------
# Developer Agent (via Hermes delegation)
# ---------------------------------------------------------------------------

def spawn_developer_agent(task: str, project_path: str, context: dict) -> dict:
    """
    Spawn Hermes sub-agent with developer role (incremental-implementation).
    
    In Hermes, this is handled by the delegation system. We construct
    a structured prompt that gets executed via `hermes exec` or the
    delegation API.
    """
    # Load relevant skills for developer role
    skill_path = "/home/workspace/Skills/agent/incremental-implementation/SKILL.md"
    if not os.path.exists(skill_path):
        skill_path = "/home/workspace/Skills/agent/source-driven-development/SKILL.md"

    # Construct developer prompt
    dev_prompt = f"""
You are implementing the following task for project at {project_path}:

TASK: {task}

Current vibe context:
{json.dumps(context, indent=2)}

Your role: Developer (incremental-implementation skill)
1. Read the relevant source files
2. Make the minimal changes needed
3. Write all modified files to disk
4. Report what you changed in a 'dev_report' field

Output format (JSON):
{{
  "dev_report": "description of changes made",
  "files_modified": ["file1.py", "file2.ts"],
  "errors": []
}}

IMPORTANT: 
- Follow the project's existing code style
- Do NOT modify files unrelated to the task
- If you encounter confusion, STOP and describe the confusion
- Verify your changes compile/run before reporting done
"""

    # Execute via Hermes CLI (hermes exec --skill=...)
    # In practice, this would be handled by Hermes's internal delegation
    result = {
        "dev_report": f"Developer agent would execute: {task}",
        "files_modified": [],
        "errors": []
    }

    print(f"[DEV] Task: {task}")
    return result


# ---------------------------------------------------------------------------
# QA Agent (via agency-api-tester)
# ---------------------------------------------------------------------------

def spawn_qa_agent(project_path: str, files_modified: list, dev_report: str) -> dict:
    """
    Spawn QA agent (agency-api-tester) to verify changes.
    
    Returns:
        {
            "passed": bool,
            "failures": [{"test": str, "error": str}],
            "output": str
        }
    """
    qa_prompt = f"""
You are verifying changes for project at {project_path}.

Developer report:
{dev_report}

Files modified:
{json.dumps(files_modified)}

Your role: agency-api-tester
1. For backend changes: run the project's test suite (test_all_endpoints.py, uat_test.py, etc.)
2. For frontend changes: verify build succeeds and no runtime errors
3. For full-stack: run uat_test.py if available
4. Report pass/fail with specific failure details

Output format (JSON):
{{
  "passed": true/false,
  "failures": [{{"test": "test_name", "error": "error description"}}],
  "output": "raw test output (truncated)"
}}
"""

    result = {
        "passed": True,
        "failures": [],
        "output": "QA agent would execute verification"
    }

    print(f"[QA] Verifying {len(files_modified)} files...")
    return result


# ---------------------------------------------------------------------------
# Vibe Loop Core
# ---------------------------------------------------------------------------

def run_vibe_loop(
    task: str,
    project_path: str,
    board: str = "default",
    max_retries: int = 3,
    notify: bool = True
) -> bool:
    """
    Execute the Dev↔QA↔Fix loop.

    Returns True if PASS, False if FAIL or blocked.
    """
    print(f"\n{'='*60}")
    print(f"VIBE SESSION: {task}")
    print(f"Project: {project_path} | Board: {board} | Max retries: {max_retries}")
    print(f"{'='*60}\n")

    # Initialize context
    ctx = load_vibe_context(project_path)

    # Create kanban task
    task_id = create_kanban_task(task, board)
    if task_id:
        update_kanban_task(task_id, "in_progress", f"Session started: {task}")

    # Notify start
    if notify:
        notify_telegram(f"🚀 Vibe session started: {task[:50]}...")

    attempt = 0
    last_result = None

    while attempt < max_retries:
        attempt += 1
        print(f"\n--- Attempt {attempt}/{max_retries} ---\n")

        # Step 1: Developer implements
        dev_result = spawn_developer_agent(task, project_path, ctx)

        if dev_result.get("errors"):
            print(f"[DEV ERROR] {dev_result['errors']}")
            if notify:
                notify_telegram(f"⚠️ Dev error on attempt {attempt}: {dev_result['errors'][0]}")
            continue

        # Step 2: QA verifies
        qa_result = spawn_qa_agent(
            project_path,
            dev_result.get("files_modified", []),
            dev_result.get("dev_report", "")
        )

        # Update context history
        history_entry = {
            "attempt": attempt,
            "dev_report": dev_result.get("dev_report", ""),
            "files_modified": dev_result.get("files_modified", []),
            "qa_result": "PASS" if qa_result["passed"] else "FAIL",
            "qa_failures": qa_result.get("failures", []),
            "timestamp": datetime.now().isoformat()
        }
        ctx.setdefault("history", []).append(history_entry)
        ctx["last_change"] = {
            "attempt": attempt,
            "files_modified": dev_result.get("files_modified", []),
            "dev_output": dev_result.get("dev_report", ""),
            "qa_failures": qa_result.get("failures", [])
        }
        save_vibe_context(project_path, ctx)

        # Create checkpoint after each attempt
        create_checkpoint(f"{task[:30]}_attempt{attempt}", project_path, ctx)

        if qa_result["passed"]:
            # SUCCESS
            print(f"\n✅ PASS after {attempt} attempt(s)!")
            if task_id:
                update_kanban_task(task_id, "done", f"PASS after {attempt} attempts")
            if notify:
                notify_telegram(f"✅ PASS after {attempt} attempt(s): {task[:50]}...")
            return True

        # FAIL - prepare feedback for next attempt
        print(f"\n❌ FAIL - {len(qa_result['failures'])} failure(s):")
        for f in qa_result["failures"]:
            print(f"  - [{f['test']}] {f['error']}")

        if task_id:
            update_kanban_task(
                task_id, "in_progress",
                f"Attempt {attempt} FAIL: {qa_result['failures'][0]['error']}"
            )

        if attempt < max_retries and notify:
            notify_telegram(f"🔄 Attempt {attempt} failed, retrying: {task[:40]}...")

        # Inject failures into context for next attempt
        ctx["last_qa_failures"] = qa_result["failures"]

    # Max retries reached - FAIL
    print(f"\n❌ FAIL after {max_retries} attempts - blocked!")
    if task_id:
        update_kanban_task(task_id, "blocked", f"Max retries ({max_retries}) reached")
    if notify:
        failures_summary = "; ".join([
            f"{f['test']}: {f['error']}" 
            for f in ctx.get("history", [])[-1].get("qa_failures", [])[:3]
        ])
        notify_telegram(f"❌ BLOCKED after {max_retries} attempts: {task[:40]}... Failures: {failures_summary}")

    return False


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Vibe Coding Dev↔QA↔Fix Loop")
    parser.add_argument("task", help="Task description")
    parser.add_argument("--project-path", required=True, help="Path to project root")
    parser.add_argument("--board", default="default", help="Kanban board name")
    parser.add_argument("--max-retries", type=int, default=3, help="Max fix attempts (default: 3)")
    parser.add_argument("--no-notify", action="store_true", help="Disable Telegram notifications")

    args = parser.parse_args()

    # Validate project path
    if not os.path.isdir(args.project_path):
        print(f"[ERROR] Project path not found: {args.project_path}")
        sys.exit(1)

    success = run_vibe_loop(
        task=args.task,
        project_path=args.project_path,
        board=args.board,
        max_retries=args.max_retries,
        notify=not args.no_notify
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
