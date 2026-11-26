"""Stop hook: run `baseline.py run check` when the working tree changed since the last pass.

Claude Code runs it without a shell: python3 -I .claude/hooks/check.py, the event JSON on stdin.
Exit 2 sends the failure on stderr back to Claude. Exit 1 is a non-blocking error.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

BIG = 16 << 20  # larger files count by size and mtime, so a turn never waits on reading them


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True).stdout


def fingerprint(root):
    """HEAD, status and the bytes of every changed or untracked file. The Stop input does not say
    whether this turn changed files."""
    h = hashlib.sha256()
    try:
        h.update(git(root, "rev-parse", "HEAD"))
        names = git(root, "diff", "--name-only", "-z", "HEAD")
    except subprocess.CalledProcessError:  # no commit yet
        names = git(root, "ls-files", "-z")
    h.update(git(root, "status", "--porcelain", "-z", "--untracked-files=all"))
    names += git(root, "ls-files", "-z", "-o", "--exclude-standard")
    top = os.path.realpath(root)
    for name in sorted(set(names.split(b"\0")) - {b""}):
        path = os.path.join(os.fsencode(root), name)
        h.update(name + b"\0")
        if os.path.islink(path):  # never follow: a link to /dev/zero would not end
            h.update(os.readlink(path))
        elif os.path.commonpath([top, os.path.realpath(os.fsdecode(path))]) != top:
            continue  # a linked parent folder leads out of the repo
        elif os.path.isfile(path):
            st = os.stat(path)
            if st.st_size > BIG:
                h.update(f"{st.st_size} {st.st_mtime_ns}".encode())
                continue
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
    return h.hexdigest()


def main():
    try:
        event = json.load(sys.stdin)
        cwd = event["cwd"]
    except (ValueError, KeyError, TypeError) as error:
        print(f"check.py: 입력 JSON을 읽지 못했다: {error!r}", file=sys.stderr)
        return 1
    if event.get("stop_hook_active"):
        return 0  # Claude is already continuing because of this hook; do not block again
    project = os.environ.get("CLAUDE_PROJECT_DIR")
    if not project:
        return 0
    try:
        # CLAUDE_PROJECT_DIR points at the first checkout even inside a worktree, so start from cwd,
        # but only run the project's own code: the root must be one of the project's worktrees.
        # A hand-made `.git` file pointing at the project's git dir is not in that list.
        root = git(cwd, "rev-parse", "--show-toplevel").decode().rstrip("\n")
        stamp = Path(git(cwd, "rev-parse", "--absolute-git-dir").decode().rstrip("\n")) / "baseline-check"
    except (OSError, subprocess.CalledProcessError):
        return 0  # not a git repo
    try:
        try:
            trees = git(project, "worktree", "list", "--porcelain", "-z").split(b"\0")
        except subprocess.CalledProcessError:
            # -z needs git 2.36 (Ubuntu 22.04 ships 2.34). Lines cannot hold a path with a newline,
            # which could forge a `worktree` line, so this path only runs on that older git.
            trees = git(project, "worktree", "list", "--porcelain").splitlines()
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"check.py: 프로젝트의 worktree 목록을 읽지 못했다: {error}", file=sys.stderr)
        return 1
    if os.path.realpath(root) not in {os.path.realpath(os.fsdecode(t[9:])) for t in trees
                                      if t.startswith(b"worktree ")}:
        return 0
    script = Path(root) / ".baseline/baseline.py"
    if not script.is_file():
        return 0
    try:
        now = fingerprint(root)
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"check.py: 작업 트리를 읽지 못했다: {error}", file=sys.stderr)
        return 1
    if not stamp.is_symlink() and stamp.is_file() and stamp.read_text() == now:
        return 0
    result = subprocess.run([sys.executable, "-I", str(script), "run", "check"], cwd=root,
                            capture_output=True, text=True)
    if result.returncode != 0:
        # Stop treats exit 2 with empty stdout and "No such file" on stderr as non-blocking.
        print("check.py: check가 실패했다")
        print(result.stdout + result.stderr, end="", file=sys.stderr)
        return 2
    if fingerprint(root) != now:
        return 0  # the tree changed while check ran; check it again next turn
    temp = stamp.with_name(stamp.name + ".tmp")
    temp.unlink(missing_ok=True)
    temp.write_text(now)
    os.replace(temp, stamp)  # replaces a link at stamp instead of writing through it
    return 0


if __name__ == "__main__":
    sys.exit(main())
