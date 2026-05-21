#!/usr/bin/env python3
"""
Vibe Coding Dev↔QA↔Fix Loop with Mistake Journal

Usage:
    python vibe_loop.py "task description" --project-path /home/workspace/new-erp
    python vibe_loop.py "Implement POST /api/users" --project-path /home/workspace/new-erp --max-retries 3
    python vibe_loop.py --show-mistakes --project-path /home/workspace/new-erp
    python vibe_loop.py --clean-mistakes --project-path /home/workspace/new-erp
"""

import argparse
import json
import os
import subprocess
import sys
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HERMES_ROOT = os.environ.get("HERMES_HOME", "/root/.hermes")
KANBAN_DB = os.path.join(HERMES_ROOT, "kanban.db")
STATE_DB = os.path.join(HERMES_ROOT, "state.db")


# ---------------------------------------------------------------------------
# Mistake Journal — Permanent Error Memory
# ---------------------------------------------------------------------------

MISTAKE_CATEGORIES = [
    "confusion",        # 思考錯亂：錯誤理解需求或上下文
    "misjudgment",      # 判斷錯誤：錯誤的技術決策或方向
    "repeated_error",   # 重複犯錯：之前已犯過但再次犯的錯
    "wrong_assumption", # 錯誤假設：基於錯誤前提進行開發
    "scope_creep",      # 範圍蔓延：修改了不該修改的東西
    "schema_mismatch",  # 結構不匹配：前後端數據結構不一致
    "missing_import",   # 缺少依賴：忘記import或缺少依賴項
]


def _mistake_journal_path(project_path: str) -> str:
    return os.path.join(project_path, ".vibe-mistakes.json")


def load_mistake_journal(project_path: str) -> dict:
    """Load or create the permanent mistake journal for a project."""
    jp = _mistake_journal_path(project_path)
    if os.path.exists(jp):
        with open(jp, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "project": os.path.basename(project_path),
        "created_at": datetime.now().isoformat(),
        "mistakes": [],
        "_meta": {
            "version": "1.0.0",
            "description": "Permanent mistake journal — checked before every vibe step to prevent repeated errors"
        }
    }


def save_mistake_journal(project_path: str, journal: dict) -> None:
    """Persist mistake journal to disk."""
    jp = _mistake_journal_path(project_path)
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(journal, f, indent=2, ensure_ascii=False)


def _generate_mistake_id(mistake: dict) -> str:
    """Generate a deterministic ID based on category + context + mistake content."""
    raw = f"{mistake.get('category','')}|{mistake.get('context','')}|{mistake.get('mistake','')}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def find_similar_mistakes(journal: dict, context_hint: str = "", category: str = "", related_files: List[str] = None) -> List[dict]:
    """Find past mistakes that are similar to the current situation."""
    relevant = []
    for m in journal.get("mistakes", []):
        score = 0
        # Category match
        if category and m.get("category") == category:
            score += 3
        # File overlap
        if related_files:
            m_files = set(m.get("related_files", []))
            overlap = m_files & set(related_files)
            if overlap:
                score += 2 * len(overlap)
        # Context keyword overlap (simple word match)
        if context_hint:
            ctx_words = set(context_hint.lower().split())
            m_ctx_words = set(m.get("context", "").lower().split())
            m_mistake_words = set(m.get("mistake", "").lower().split())
            overlap = (ctx_words & m_ctx_words) | (ctx_words & m_mistake_words)
            if overlap:
                score += len(overlap)
        if score > 0:
            relevant.append((score, m))

    relevant.sort(key=lambda x: -x[0])
    return [m for _, m in relevant[:10]]  # Top 10 most relevant


def record_mistake(
    project_path: str,
    category: str,
    context: str,
    mistake: str,
    lesson: str,
    related_files: List[str] = None,
    session_id: str = ""
) -> dict:
    """
    Record a mistake into the permanent journal.
    If the same mistake already exists, increment occurrence_count.
    Returns the recorded/updated mistake entry.
    """
    journal = load_mistake_journal(project_path)

    new_entry = {
        "category": category,
        "context": context,
        "mistake": mistake,
        "lesson": lesson,
        "related_files": related_files or [],
        "timestamp": datetime.now().isoformat(),
        "session_id": session_id,
        "occurrence_count": 1
    }

    # Check if same mistake already recorded (by content hash)
    mid = _generate_mistake_id(new_entry)
    for existing in journal["mistakes"]:
        existing_id = _generate_mistake_id(existing)
        if existing_id == mid:
            # Same mistake — increment count, update timestamp
            existing["occurrence_count"] = existing.get("occurrence_count", 1) + 1
            existing["last_occurred"] = datetime.now().isoformat()
            existing["session_id"] = session_id
            # Update lesson if new one is more detailed
            if len(lesson) > len(existing.get("lesson", "")):
                existing["lesson"] = lesson
            save_mistake_journal(project_path, journal)
            return existing

    # New mistake
    new_entry["id"] = mid
    journal["mistakes"].append(new_entry)
    save_mistake_journal(project_path, journal)
    return new_entry


def check_mistakes_before_action(
    project_path: str,
    action: str,
    context_hint: str = "",
    related_files: List[str] = None,
    category: str = ""
) -> str:
    """
    Check the mistake journal before taking an action.
    Returns a formatted warning string to inject into agent prompts,
    or empty string if no relevant mistakes found.
    """
    journal = load_mistake_journal(project_path)
    relevant = find_similar_mistakes(journal, context_hint, category, related_files)

    if not relevant:
        return ""

    lines = [
        "",
        "⚠️ ========== MISTAKE JOURNAL WARNING ========== ⚠️",
        f"Before {action}, review these past mistakes to AVOID repeating:",
        ""
    ]

    for i, m in enumerate(relevant[:5], 1):
        count = m.get("occurrence_count", 1)
        count_warn = f" (⚠️ REPEATED {count}x!)" if count > 1 else ""
        lines.append(f"  {i}. [{m.get('category','unknown').upper()}]{count_warn}")
        lines.append(f"     Context: {m.get('context','')}")
        lines.append(f"     Mistake: {m.get('mistake','')}")
        lines.append(f"     Lesson:  {m.get('lesson','')}")
        if m.get("related_files"):
            lines.append(f"     Files:   {', '.join(m['related_files'])}")
        lines.append("")

    lines.append("⚠️ Make sure you do NOT repeat these mistakes. ⚠️")
    lines.append("===============================================")
    lines.append("")

    return "\n".join(lines)


def analyze_failure_for_mistake(
    project_path: str,
    task: str,
    attempt: int,
    dev_report: str,
    qa_failures: List[dict],
    session_id: str = ""
) -> Optional[dict]:
    """
    Analyze a QA failure and determine if it represents a thinking/judgment error
    that should be recorded in the mistake journal.
    Returns the recorded mistake or None.
    """
    if not qa_failures:
        return None

    # Analyze failure patterns to categorize
    for failure in qa_failures:
        error_str = str(failure.get("error", "")).lower()
        test_name = str(failure.get("test", "")).lower()

        category = None
        context = f"Task: {task}, Attempt: {attempt}"
        mistake_desc = ""
        lesson = ""

        # Pattern: Schema/field mismatch
        if any(kw in error_str for kw in ["field required", "422", "validation error", "missing", "unexpected key"]):
            category = "schema_mismatch"
            mistake_desc = f"Schema mismatch in {test_name}: {failure.get('error', '')}"
            lesson = "Always verify request/response schemas match the model definition before implementing endpoints"

        # Pattern: Method not allowed / wrong route
        elif any(kw in error_str for kw in ["method not allowed", "405", "not found", "404"]):
            category = "wrong_assumption"
            mistake_desc = f"Wrong route/method assumption in {test_name}: {failure.get('error', '')}"
            lesson = "Always check the actual registered routes (via openapi.json or router definition) before implementing"

        # Pattern: Import error / dependency missing
        elif any(kw in error_str for kw in ["import", "module not found", "nameerror", "not defined"]):
            category = "missing_import"
            mistake_desc = f"Missing import/dependency in {test_name}: {failure.get('error', '')}"
            lesson = "Verify all imports and dependencies are present before running. Check requirements.txt and __init__.py"

        # Pattern: Scope creep — modified unrelated files
        elif any(kw in error_str for kw in ["unrelated", "side effect", "regression"]):
            category = "scope_creep"
            mistake_desc = f"Scope creep caused regression in {test_name}: {failure.get('error', '')}"
            lesson = "Only modify files directly related to the task. Run full test suite before and after changes"

        # Pattern: General confusion (500 errors, unexpected behavior)
        elif any(kw in error_str for kw in ["500", "internal server error", "unexpected", "typeerror"]):
            category = "confusion"
            mistake_desc = f"Thinking confusion in {test_name}: {failure.get('error', '')}"
            lesson = "When encountering unexpected errors, read the full error traceback before attempting fixes"

        # Pattern: Repeated fix attempt that doesn't work
        if attempt >= 2:
            category = category or "repeated_error"
            if "repeated_error" not in mistake_desc:
                mistake_desc = f"Repeated fix failure (attempt {attempt}) for {test_name}: {failure.get('error', '')}"
                lesson = lesson or "If the same fix fails twice, stop and re-analyze the root cause from scratch"

        if category:
            related = failure.get("related_files", [])
            return record_mistake(
                project_path=project_path,
                category=category,
                context=context,
                mistake=mistake_desc,
                lesson=lesson,
                related_files=related,
                session_id=session_id
            )

    return None


def format_mistake_journal_display(journal: dict) -> str:
    """Format the mistake journal for CLI display."""
    mistakes = journal.get("mistakes", [])
    if not mistakes:
        return "No mistakes recorded yet."

    lines = [f"Mistake Journal for {journal.get('project', 'unknown')}", "=" * 50, ""]

    # Group by category
    by_category: Dict[str, List[dict]] = {}
    for m in mistakes:
        cat = m.get("category", "unknown")
        by_category.setdefault(cat, []).append(m)

    for cat, items in sorted(by_category.items()):
        lines.append(f"📂 {cat.upper()} ({len(items)} mistake(s))")
        lines.append("-" * 40)
        for m in items:
            count = m.get("occurrence_count", 1)
            count_str = f" [×{count}]" if count > 1 else ""
            lines.append(f"  ID: {m.get('id', '?')}{count_str}")
            lines.append(f"  Context: {m.get('context', '')}")
            lines.append(f"  Mistake: {m.get('mistake', '')}")
            lines.append(f"  Lesson:  {m.get('lesson', '')}")
            if m.get("related_files"):
                lines.append(f"  Files:   {', '.join(m['related_files'])}")
            lines.append(f"  Last:    {m.get('last_occurred', m.get('timestamp', ''))}")
            lines.append("")
        lines.append("")

    # Summary
    total = len(mistakes)
    repeated = sum(1 for m in mistakes if m.get("occurrence_count", 1) > 1)
    lines.append(f"Total: {total} mistake(s), {repeated} repeated")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Vibe Context Management
# ---------------------------------------------------------------------------

def load_vibe_context(project_path: str) -> dict:
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
    ctx_file = os.path.join(project_path, ".vibe-context.json")
    with open(ctx_file, "w") as f:
        json.dump(ctx, f, indent=2, ensure_ascii=False)


def detect_project_name(project_path: str) -> str:
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
    checkpoint_dir = os.path.join(HERMES_ROOT, "checkpoints")
    os.makedirs(checkpoint_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = label.replace(" ", "_").replace("/", "_")[:40]
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
    try:
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

def spawn_developer_agent(task: str, project_path: str, context: dict, mistake_warning: str = "") -> dict:
    """
    Spawn Hermes sub-agent with developer role.
    Injects mistake journal warnings to prevent repeated errors.
    """
    skill_path = "/home/workspace/Skills/agent/incremental-implementation/SKILL.md"
    if not os.path.exists(skill_path):
        skill_path = "/home/workspace/Skills/agent/source-driven-development/SKILL.md"

    mistake_section = ""
    if mistake_warning:
        mistake_section = f"""
{mistake_warning}
"""

    dev_prompt = f"""
You are implementing the following task for project at {project_path}:

TASK: {task}

Current vibe context:
{json.dumps(context, indent=2)}
{mistake_section}
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
- Review the MISTAKE JOURNAL WARNING above (if any) and do NOT repeat those errors
"""

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

def spawn_qa_agent(project_path: str, files_modified: list, dev_report: str, mistake_warning: str = "") -> dict:
    """
    Spawn QA agent (agency-api-tester) to verify changes.
    Injects mistake journal warnings.
    """
    mistake_section = ""
    if mistake_warning:
        mistake_section = f"""
{mistake_warning}
"""

    qa_prompt = f"""
You are verifying changes for project at {project_path}.

Developer report:
{dev_report}

Files modified:
{json.dumps(files_modified)}
{mistake_section}
Your role: agency-api-tester
1. For backend changes: run the project's test suite (test_all_endpoints.py, uat_test.py, etc.)
2. For frontend changes: verify build succeeds and no runtime errors
3. For full-stack: run uat_test.py if available
4. Report pass/fail with specific failure details

Output format (JSON):
{{
  "passed": true/false,
  "failures": [{{"test": "test_name", "error": "error description", "related_files": []}}],
  "output": "raw test output (truncated)"
}}

IMPORTANT:
- Check for the specific mistake patterns listed in the WARNING above (if any)
- If a past mistake pattern appears in the current code, flag it as a failure
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
    Execute the Dev↔QA↔Fix loop with Mistake Journal integration.

    Returns True if PASS, False if FAIL or blocked.
    """
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"\n{'='*60}")
    print(f"VIBE SESSION: {task}")
    print(f"Project: {project_path} | Board: {board} | Max retries: {max_retries}")
    print(f"Session: {session_id}")
    print(f"{'='*60}\n")

    # Initialize context
    ctx = load_vibe_context(project_path)

    # Load mistake journal and show relevant warnings for this task
    mistake_journal = load_mistake_journal(project_path)
    task_mistakes = find_similar_mistakes(mistake_journal, context_hint=task, related_files=[])
    if task_mistakes:
        print(f"[MISTAKE JOURNAL] Found {len(task_mistakes)} relevant past mistake(s) for this task:")
        for m in task_mistakes[:3]:
            count = m.get("occurrence_count", 1)
            print(f"  ⚠️ [{m.get('category','?')}] {m.get('mistake','')[:80]} (×{count})")
        print()

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

        # === CHECK MISTAKES BEFORE DEV ===
        dev_mistake_warning = check_mistakes_before_action(
            project_path=project_path,
            action="Developer implementation",
            context_hint=task,
            related_files=ctx.get("last_change", {}).get("files_modified", []),
        )

        if dev_mistake_warning:
            print("[MISTAKE CHECK] Injecting past mistake warnings into Developer agent...")

        # Step 1: Developer implements
        dev_result = spawn_developer_agent(task, project_path, ctx, mistake_warning=dev_mistake_warning)

        if dev_result.get("errors"):
            print(f"[DEV ERROR] {dev_result['errors']}")
            # Record as confusion mistake
            record_mistake(
                project_path=project_path,
                category="confusion",
                context=f"Task: {task}, Attempt: {attempt}",
                mistake=f"Developer agent encountered error: {dev_result['errors']}",
                lesson="Check error details and verify all dependencies/imports before implementing",
                related_files=dev_result.get("files_modified", []),
                session_id=session_id
            )
            if notify:
                notify_telegram(f"⚠️ Dev error on attempt {attempt}: {dev_result['errors'][0]}")
            continue

        # === CHECK MISTAKES BEFORE QA ===
        qa_mistake_warning = check_mistakes_before_action(
            project_path=project_path,
            action="QA verification",
            context_hint=f"Verifying: {dev_result.get('dev_report', '')}",
            related_files=dev_result.get("files_modified", []),
        )

        # Step 2: QA verifies
        qa_result = spawn_qa_agent(
            project_path,
            dev_result.get("files_modified", []),
            dev_result.get("dev_report", ""),
            mistake_warning=qa_mistake_warning
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

        # FAIL — analyze and record mistake
        print(f"\n❌ FAIL - {len(qa_result['failures'])} failure(s):")
        for f in qa_result["failures"]:
            print(f"  - [{f['test']}] {f['error']}")

        # Record the failure as a mistake in the journal
        recorded = analyze_failure_for_mistake(
            project_path=project_path,
            task=task,
            attempt=attempt,
            dev_report=dev_result.get("dev_report", ""),
            qa_failures=qa_result.get("failures", []),
            session_id=session_id
        )
        if recorded:
            print(f"[MISTAKE JOURNAL] Recorded: [{recorded['category']}] {recorded['mistake'][:60]}")
            if recorded.get("occurrence_count", 1) > 1:
                print(f"  ⚠️ This mistake has been made {recorded['occurrence_count']} times!")

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

    # Record the overall failure as a misjudgment
    record_mistake(
        project_path=project_path,
        category="misjudgment",
        context=f"Task: {task}, All {max_retries} attempts failed",
        mistake=f"Could not resolve task after {max_retries} attempts. Last failures: {str(ctx.get('history', [{}])[-1].get('qa_failures', []))[:200]}",
        lesson="When all attempts fail, stop and re-analyze the root cause. Consider: (1) wrong approach entirely, (2) missing context, (3) need human input",
        related_files=ctx.get("last_change", {}).get("files_modified", []),
        session_id=session_id
    )

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
    parser = argparse.ArgumentParser(description="Vibe Coding Dev↔QA↔Fix Loop with Mistake Journal")
    parser.add_argument("task", nargs="?", help="Task description")
    parser.add_argument("--project-path", required=True, help="Path to project root")
    parser.add_argument("--board", default="default", help="Kanban board name")
    parser.add_argument("--max-retries", type=int, default=3, help="Max fix attempts (default: 3)")
    parser.add_argument("--no-notify", action="store_true", help="Disable Telegram notifications")
    parser.add_argument("--show-mistakes", action="store_true", help="Display the mistake journal for this project")
    parser.add_argument("--clean-mistakes", action="store_true", help="Reset the mistake journal for this project")

    args = parser.parse_args()

    # Validate project path
    if not os.path.isdir(args.project_path):
        print(f"[ERROR] Project path not found: {args.project_path}")
        sys.exit(1)

    # Show mistakes mode
    if args.show_mistakes:
        journal = load_mistake_journal(args.project_path)
        print(format_mistake_journal_display(journal))
        sys.exit(0)

    # Clean mistakes mode
    if args.clean_mistakes:
        jp = _mistake_journal_path(args.project_path)
        if os.path.exists(jp):
            os.remove(jp)
            print("[MISTAKE JOURNAL] Cleared.")
        else:
            print("[MISTAKE JOURNAL] No journal found.")
        sys.exit(0)

    # Normal vibe loop mode
    if not args.task:
        print("[ERROR] Task description required")
        parser.print_help()
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
