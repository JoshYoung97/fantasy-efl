"""Publish data/app.html to the gh-pages branch, as index.html.

    python scripts/export_app_data.py && python scripts/build_app.py && python scripts/publish_page.py

GitHub Pages serves gh-pages directly (Settings -> Pages -> Deploy from a
branch), so this is the entire publish step -- no build service involved.

Deliberately a separate branch from main, not a commit onto it: the page is
rebuilt twice daily (see run_refresh.cmd) and main's history would otherwise
fill with nothing but regenerated-file diffs -- exactly why data/app.html is
gitignored on main in the first place.

Runs in an isolated git worktree so it never touches whatever branch is
currently checked out -- run_refresh.cmd runs this unattended, and it must
leave the working checkout exactly as it found it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "data" / "app.html"
BRANCH = "gh-pages"
REMOTE = "origin"


def run(*args, cwd=None, check=True):
    return subprocess.run(
        ["git", *args], cwd=cwd or ROOT, check=check, capture_output=True, text=True,
    )


def _cleanup(worktree: Path) -> None:
    """Drop the temporary worktree, tolerating a locked filesystem.

    The push has already happened by the time this runs, so a failure here
    means the page IS live and only the scratch checkout survived. Raising
    would report the opposite: every run from 29 Aug logged "FAILED at
    publish - built page not live" while having published perfectly, because
    OneDrive holds a lock on the repo and `git worktree remove` exits 255.

    Prunes the leftover administrative entry too, or `.git/worktrees` fills
    with husks and each run picks a new name (gh-pages1, gh-pages2, ...).
    """
    if run("worktree", "remove", "--force", str(worktree), check=False).returncode == 0:
        return
    run("worktree", "prune", check=False)
    print(
        f"note: could not remove the temporary worktree at {worktree} "
        "(a file lock, usually OneDrive). The page published successfully; "
        "this is cleanup only.",
        file=sys.stderr,
    )


def main() -> int:
    if not PAGE.exists():
        print(
            "no page -- run: python scripts/export_app_data.py && python scripts/build_app.py",
            file=sys.stderr,
        )
        return 1

    content = PAGE.read_bytes()
    run("fetch", REMOTE)

    # ignore_cleanup_errors: if the worktree could not be removed above, the
    # directory is still locked here and tearing it down would raise for the
    # same reason -- after the page is already published.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        worktree = Path(tmp) / BRANCH

        exists_remotely = run(
            "show-ref", "--verify", "--quiet", f"refs/remotes/{REMOTE}/{BRANCH}", check=False
        ).returncode == 0

        if exists_remotely:
            run("worktree", "add", "--detach", str(worktree), f"{REMOTE}/{BRANCH}")
        else:
            # First publish: an orphan branch with no shared history with main,
            # so its own history is just "the page, over time".
            run("worktree", "add", "--detach", str(worktree), "HEAD")
            run("checkout", "--orphan", BRANCH, cwd=worktree)
            run("rm", "-rf", "--cached", ".", cwd=worktree, check=False)
            for entry in worktree.iterdir():
                if entry.name == ".git":
                    continue
                shutil.rmtree(entry) if entry.is_dir() else entry.unlink()

        (worktree / "index.html").write_bytes(content)
        run("add", "index.html", cwd=worktree)

        status = run("status", "--porcelain", cwd=worktree)
        if not status.stdout.strip():
            print("page unchanged -- nothing to publish")
            _cleanup(worktree)
            return 0

        run(
            "-c", "user.name=fantasy-efl-publish",
            "-c", "user.email=noreply@users.noreply.github.com",
            "commit", "-m", "Publish projections page",
            cwd=worktree,
        )
        run("push", REMOTE, f"HEAD:{BRANCH}", cwd=worktree)
        _cleanup(worktree)

    print(f"published {PAGE} to {BRANCH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
