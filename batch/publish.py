"""docs/ 변경분을 git commit/push (remote 없으면 안내 후 스킵)."""

from __future__ import annotations

import subprocess
from pathlib import Path


PROPOSAL_ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def has_remote(repo: Path | None = None, name: str = "origin") -> bool:
    root = repo or PROPOSAL_ROOT
    r = _run(["git", "remote", "get-url", name], root)
    return r.returncode == 0 and bool((r.stdout or "").strip())


def publish_docs(
    *,
    repo: Path | None = None,
    push: bool = True,
    message: str | None = None,
) -> dict[str, str | bool]:
    """
    docs/ (및 배치가 갱신한 results) 를 스테이징·커밋하고, push=True면 origin에 push.

    Returns:
        ok, committed, pushed, detail
    """
    root = repo or PROPOSAL_ROOT
    msg = message or "docs: update finance bid survey (daily batch)"

    if not (root / ".git").exists():
        return {
            "ok": False,
            "committed": False,
            "pushed": False,
            "detail": f"git 저장소가 아닙니다: {root}",
        }

    # Pages 소스 + 배치가 함께 갱신하는 데이터
    paths = [
        "docs",
        "results.md",
        "webapp/data/results.json",
    ]
    add = _run(["git", "add", "--", *paths], root)
    if add.returncode != 0:
        return {
            "ok": False,
            "committed": False,
            "pushed": False,
            "detail": (add.stderr or add.stdout or "git add 실패").strip(),
        }

    status = _run(["git", "status", "--porcelain", "--", *paths], root)
    if not (status.stdout or "").strip():
        return {
            "ok": True,
            "committed": False,
            "pushed": False,
            "detail": "커밋할 변경 없음",
        }

    commit = _run(["git", "commit", "-m", msg], root)
    if commit.returncode != 0:
        return {
            "ok": False,
            "committed": False,
            "pushed": False,
            "detail": (commit.stderr or commit.stdout or "git commit 실패").strip(),
        }

    if not push:
        return {
            "ok": True,
            "committed": True,
            "pushed": False,
            "detail": "커밋 완료 (--push 미사용)",
        }

    if not has_remote(root):
        return {
            "ok": True,
            "committed": True,
            "pushed": False,
            "detail": (
                "origin remote가 없습니다. "
                "GitHub repo를 만든 뒤 `git remote add origin <url>` 후 다시 --push 하세요."
            ),
        }

    pushed = _run(["git", "push", "origin", "HEAD"], root)
    if pushed.returncode != 0:
        return {
            "ok": False,
            "committed": True,
            "pushed": False,
            "detail": (pushed.stderr or pushed.stdout or "git push 실패").strip(),
        }

    return {
        "ok": True,
        "committed": True,
        "pushed": True,
        "detail": "커밋 및 push 완료",
    }
