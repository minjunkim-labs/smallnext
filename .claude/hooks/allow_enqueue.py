"""PreToolUse hook: allow `python3 -I .baseline/baseline.py enqueue <PR number> <40-hex SHA>` and nothing else.

Auto mode drops an allow rule for that command (an interpreter with a flag), and a rule cannot see which
code it runs. This hook answers "allow" only when the copy has the sha256 given in `--sha256`, which lives
in `.claude/settings.json`, a path Claude Code does not let an agent change without a prompt or the auto
mode classifier. Git refs are not trusted: an agent can move them. Otherwise the hook prints nothing and
the call goes through the normal permission flow. Deny rules still win.
"""
import hashlib
import json
import os
import re
import sys

COMMAND = re.compile(r"python3 -I \.baseline/baseline\.py enqueue [1-9][0-9]{0,9} [0-9a-f]{40}")


def allowed(event, want):
    if event.get("tool_name") != "Bash" or not COMMAND.fullmatch(event["tool_input"]["command"]):
        return False
    folder = os.path.join(event["cwd"], ".baseline")
    copy = os.path.join(folder, "baseline.py")
    if os.path.islink(folder) or os.path.islink(copy):
        return False
    with open(copy, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest() == want


def main(argv):
    try:
        if len(argv) != 2 or argv[0] != "--sha256" or not re.fullmatch(r"[0-9a-f]{64}", argv[1]):
            return 0
        ok = allowed(json.load(sys.stdin), argv[1])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        ok = False
    if ok:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                                 "permissionDecisionReason": "baseline enqueue (pinned copy)"}}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
