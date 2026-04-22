from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


# Tools that mutate files and should be snapshotted before execution.
MUTATING_TOOLS: frozenset[str] = frozenset({
    "write_file",
    "append_file",
    "replace_in_file",
    "edit_file",
    "patch_file",
    "insert_at_line",
    "delete_range",
    "yaml_edit",
    "json_edit",
    "delete_file",
    "rename_or_move",
})


class RollbackStore:
    """Stores pre-mutation file snapshots for per-task rollback."""

    def __init__(self, storage_dir: Path) -> None:
        self._dir = storage_dir / "rollbacks"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _task_dir(self, task_id: str) -> Path:
        return self._dir / task_id

    def snapshot(self, task_id: str, file_path: Path) -> None:
        """Snapshot file content before mutation. Idempotent for the same task+path pair."""
        task_dir = self._task_dir(task_id)
        task_dir.mkdir(parents=True, exist_ok=True)

        # Use MD5 of resolved path as filename to avoid OS path separator issues.
        resolved = str(file_path.resolve())
        path_key = hashlib.md5(resolved.encode()).hexdigest()
        snapshot_file = task_dir / f"{path_key}.json"

        if snapshot_file.exists():
            return  # Already snapshotted for this task — preserve the original state.

        existed = file_path.exists()
        content: str | None = None
        if existed:
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                content = None

        snapshot_file.write_text(
            json.dumps({
                "original_path": resolved,
                "existed": existed,
                "content": content,
            }),
            encoding="utf-8",
        )

    def restore(self, task_id: str) -> list[str]:
        """Restore all snapshotted files for a task. Returns list of affected paths."""
        task_dir = self._task_dir(task_id)
        if not task_dir.exists():
            return []

        restored: list[str] = []
        for snapshot_file in task_dir.glob("*.json"):
            try:
                data = json.loads(snapshot_file.read_text(encoding="utf-8"))
                original_path = Path(data["original_path"])
                existed: bool = bool(data["existed"])
                content: str | None = data.get("content")

                if not existed:
                    # File was created by the task — remove it.
                    if original_path.exists():
                        original_path.unlink(missing_ok=True)
                elif content is not None:
                    # Restore original content.
                    original_path.parent.mkdir(parents=True, exist_ok=True)
                    original_path.write_text(content, encoding="utf-8")

                restored.append(str(original_path))
            except (OSError, KeyError, json.JSONDecodeError):
                pass

        return restored

    def discard(self, task_id: str) -> None:
        """Remove snapshots once a task completes successfully."""
        task_dir = self._task_dir(task_id)
        if task_dir.exists():
            shutil.rmtree(task_dir, ignore_errors=True)

    def has_snapshots(self, task_id: str) -> bool:
        task_dir = self._task_dir(task_id)
        return task_dir.exists() and any(task_dir.glob("*.json"))
