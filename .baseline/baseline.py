"""repo-baseline v2: copy the core into a repo and check that it still matches.

Python 3.9+ standard library only. Run with `python3 -I`. In a consumer repo every command
runs from the pinned copy `.baseline/baseline.py`.
"""
import argparse
import ast
import copy
from datetime import datetime, timedelta, timezone
import difflib
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote

VERSION = "2.3.0"
START, END = b"<!-- baseline:start -->\n", b"<!-- baseline:end -->\n"
ENV_IGNORE = (".env", ".env.*", "!.env.example", "*.pem", "*.key", "*.p12")  # the v1 core gitignore had the same
ENV_SAMPLES = (".env", ".env.local", "a.pem", "a.key", "a.p12")
# The hashes of this version. check trusts these, not only baseline.json, so editing a managed
# file together with baseline.json still fails. test_baseline.py keeps them equal to core/.
# Each value is the sha256 of the source file, keyed by what the repo may change (GLOSSARY.md):
# sha256 nothing, block_sha256 all but the managed block, prefix_sha256 the lines below the source's
# lines at the top, seed_sha256 everything (written only when missing, never checked or upgraded).
MANAGED = {
    ".gitattributes": {"prefix_sha256": "d60f352d0db1404c70afb4bb8b2ca3fd1c610572aa40720e8a0b7baa7885418c"},
    "AGENTS.md": {"block_sha256": "1492f3d676395887479dd805ead043f844f85a235fe152fa9995de8fbc617cb7"},
    "CLAUDE.md": {"sha256": "336cc4fbf19beaada7ccf9986414fa91851a8d7a07dfb3ccbe800a69eed0ab49"},
    "REVIEW.md": {"block_sha256": "f5e1101fdcf937fa32494640097281009ef1e2fdd27f4ab0c93f0f12fb0c355f"},
    ".github/pull_request_template.md": {"sha256": "093b514f391e73dfc4de4d4f84db8297d635ba176484b183d2606032a2d3beaa"},
    ".claude/hooks/allow_enqueue.py": {"sha256": "55b4aeb5b60231948c9f6fe5190878ce9955114d4a8d87e55be33d9f27f3b5e7"},
    ".claude/hooks/check.py": {"sha256": "6b27ea25423c46e4cd0acd2510b7b4b1d0ee6ae6f38f8f4307a37ce6b1b3b758"},
    "docs/agents/issue-tracker.md": {"seed_sha256": "6fdb3e9b00b7b0b115ecac3b1c00e3790f637f190abf598815368722c0a94692"},
    "docs/agents/triage-labels.md": {"seed_sha256": "ae512af838c78b8750471c42cd2b20fa32319553e61d84c9a23d171b40ce14aa"},
    "docs/agents/domain.md": {"seed_sha256": "593a7042218689f1d24df89df14eaf0a20e19e0d0a7d479a01947ac78f0784b9"},
    "docs/agents/LICENSE": {"sha256": "0e7ac423bf2c6e223b7c5b156f8cf72da49d748e56a1641402c31f22ad07dbb5"},
    ".claude/skills/arena/LICENSE": {"sha256": "bc957ca6bee02792566a1a028d105e02e247c6e77cf057061674273da77b200e"},
    ".claude/skills/arena/SKILL.md": {"sha256": "2e418753dfc64239e4d6412e7b739196d268e22ef1a4ecfbb8c0498bd3c82636"},
    ".claude/skills/blast-radius/LICENSE": {"sha256": "bc957ca6bee02792566a1a028d105e02e247c6e77cf057061674273da77b200e"},
    ".claude/skills/blast-radius/SKILL.md": {"sha256": "4248d03e22365207d2e5f90c9542720f80a88a6b42fd542ef88dde3cf9f9223f"},
    ".claude/skills/code-review/LICENSE": {"sha256": "0e7ac423bf2c6e223b7c5b156f8cf72da49d748e56a1641402c31f22ad07dbb5"},
    ".claude/skills/code-review/SKILL.md": {"sha256": "9c921a8d88138a41401d8897ca1bb852088ab1b7b605cdd04edc13e3e8aab6dd"},
    ".claude/skills/code-review/agents/openai.yaml": {"sha256": "8229ca854e11dc8e6aef2131ee03f31fb1561cf905fab9ccc325180cf3331352"},
    ".claude/skills/codebase-design/DEEPENING.md": {"sha256": "f3dd099ce99289bd213914d8ee3e2429b78309c3957ca4583f7659551b1d53c1"},
    ".claude/skills/codebase-design/DESIGN-IT-TWICE.md": {"sha256": "c222ab5a82e0405672eb9062d62496139a08828e45d07fc5f18e4952c10fac1a"},
    ".claude/skills/codebase-design/LICENSE": {"sha256": "0e7ac423bf2c6e223b7c5b156f8cf72da49d748e56a1641402c31f22ad07dbb5"},
    ".claude/skills/codebase-design/SKILL.md": {"sha256": "2c20617f87ec8af6a434859f381b2f061a69b530444e74eb39e78bb016a6d1e2"},
    ".claude/skills/codebase-design/agents/openai.yaml": {"sha256": "edebc9e4fcfe102114012575eaa9600b9b5fd08c311664f389c36e7bc717740f"},
    ".claude/skills/create-verification-skill/LICENSE": {"sha256": "bc957ca6bee02792566a1a028d105e02e247c6e77cf057061674273da77b200e"},
    ".claude/skills/create-verification-skill/SKILL.md": {"sha256": "d353973547bf8ad8977eca645f4cd4feaed0d32f4b43d1448f906b0a76c4d694"},
    ".claude/skills/create-verification-skill/references/feature-map-example/README.md": {"sha256": "cb7bd782cf89968a4ba3d58a5151db837430db92d19a6f52a906973b77b516ba"},
    ".claude/skills/create-verification-skill/references/feature-map-example/create-note.md": {"sha256": "644a44c74f35d38c2feb7cd05a0121fdebbb623e8dc376c185b565a581d1ccf7"},
    ".claude/skills/create-verification-skill/references/feature-map-example/search.md": {"sha256": "6e87b9e7f2791a7776ba1bb83f371cd285c306c67f19d245cc4dd6ca3015c823"},
    ".claude/skills/diagnosing-bugs/LICENSE": {"sha256": "0e7ac423bf2c6e223b7c5b156f8cf72da49d748e56a1641402c31f22ad07dbb5"},
    ".claude/skills/diagnosing-bugs/SKILL.md": {"sha256": "849198df88cdb65fd0d97236604c1fca7ff2f22d2f705f9724a800d0266b118d"},
    ".claude/skills/diagnosing-bugs/agents/openai.yaml": {"sha256": "3e430dbe4334a87597488c060cb3dc3786bb00c9182877d6f5ec41f62490e90b"},
    ".claude/skills/diagnosing-bugs/scripts/hitl-loop.template.sh": {"sha256": "35103539fc36873eea36074769ad454f9379d6fc8b2dc0e26ce987fd3bfe5503"},
    ".claude/skills/domain-modeling/ADR-FORMAT.md": {"sha256": "944c92aa790e8fbdc9199640b170979abb8a34ba8d0fe18c2a01a63bce140ca0"},
    ".claude/skills/domain-modeling/GLOSSARY-FORMAT.md": {"sha256": "21dcc40cdec8e151a829b98ab1517c1867bc444e3665134a98c6983411996801"},
    ".claude/skills/domain-modeling/LICENSE": {"sha256": "0e7ac423bf2c6e223b7c5b156f8cf72da49d748e56a1641402c31f22ad07dbb5"},
    ".claude/skills/domain-modeling/SKILL.md": {"sha256": "7b925d7b1e341a2eeae33ad68a8a8c0ab889a38ddd22a7598e4c240e5a7556a3"},
    ".claude/skills/domain-modeling/agents/openai.yaml": {"sha256": "f6bf2aa996c6e6f53fdd0708e18a0d16a56aed8322cca59fedbe3c0d2c75f06b"},
    ".claude/skills/grill-with-docs/LICENSE": {"sha256": "0e7ac423bf2c6e223b7c5b156f8cf72da49d748e56a1641402c31f22ad07dbb5"},
    ".claude/skills/grill-with-docs/SKILL.md": {"sha256": "7de372c13488f1ee96cc11cd8907b56b6809cc93eef776eeddd37de6b6cbe3fe"},
    ".claude/skills/grill-with-docs/agents/openai.yaml": {"sha256": "94cd0ab161fb468a836349f5ed482ba58ce8e709a05c57ce533d739dbd35cca9"},
    ".claude/skills/grilling/LICENSE": {"sha256": "0e7ac423bf2c6e223b7c5b156f8cf72da49d748e56a1641402c31f22ad07dbb5"},
    ".claude/skills/grilling/SKILL.md": {"sha256": "a146842ed93ca43d833550fa9adf02e58cb63c83fea9d4b4522995b82242d4e2"},
    ".claude/skills/grilling/agents/openai.yaml": {"sha256": "1411d7df7d99b7e621a1ff8283c8133cc2464be63d064e52d8ce169c6800ee9b"},
    ".claude/skills/in-your-own-words/LICENSE": {"sha256": "bc957ca6bee02792566a1a028d105e02e247c6e77cf057061674273da77b200e"},
    ".claude/skills/in-your-own-words/SKILL.md": {"sha256": "fa8ba74e27d7be371dc270ec78bbf816411477d0dfab185356c861ac8dd413ad"},
    ".claude/skills/interrogate/LICENSE": {"sha256": "bc957ca6bee02792566a1a028d105e02e247c6e77cf057061674273da77b200e"},
    ".claude/skills/interrogate/SKILL.md": {"sha256": "3f3c2e9b8cf6b180dba9f32a4aff85e5691b09805232468e37a0ba45437a9984"},
    ".claude/skills/maintain-verification-skill/LICENSE": {"sha256": "bc957ca6bee02792566a1a028d105e02e247c6e77cf057061674273da77b200e"},
    ".claude/skills/maintain-verification-skill/SKILL.md": {"sha256": "515c0eaa054b3f6be1b1fb06f2c2f173c80fddb58bbcac57576f89c479bc68e8"},
    ".claude/skills/pr/CREDITS.md": {"sha256": "a7a087127665d7298a72280ef6e19c41ad8404523712a788c8dc3ab414bc2497"},
    ".claude/skills/pr/LICENSE": {"sha256": "0e7ac423bf2c6e223b7c5b156f8cf72da49d748e56a1641402c31f22ad07dbb5"},
    ".claude/skills/pr/SKILL.md": {"sha256": "ab63f1cf78647389edcd386c9427c5dfca27ed2836930c24773ffee834c19bcd"},
    ".claude/skills/pr/agents/openai.yaml": {"sha256": "2295b586624db4ef546f3fd4695492f039d941a46d8a1593a702ce3ca511b8ad"},
    ".claude/skills/prototype/LICENSE": {"sha256": "0e7ac423bf2c6e223b7c5b156f8cf72da49d748e56a1641402c31f22ad07dbb5"},
    ".claude/skills/prototype/LOGIC.md": {"sha256": "f61c7d249e786a79ef289018901c348271e1798dd0b0bc5607b5c6f4d4a01ab9"},
    ".claude/skills/prototype/SKILL.md": {"sha256": "714de632d116bb73f65cdb5a882db15b9369a6713b9a47c0fad827848f0bfbe3"},
    ".claude/skills/prototype/UI.md": {"sha256": "723211e878acbc7b6ff09755263f3295cde724ba902ff0064da41eed51d45ad3"},
    ".claude/skills/prototype/agents/openai.yaml": {"sha256": "5af65e43ab41a350436697b81e27b7f848d36782043b73c322bb2c9fa9cc55dc"},
    ".claude/skills/research/LICENSE": {"sha256": "0e7ac423bf2c6e223b7c5b156f8cf72da49d748e56a1641402c31f22ad07dbb5"},
    ".claude/skills/research/SKILL.md": {"sha256": "1f629e18ab899412683bc6a1c4efb4339999e27c2fdac328f26ee10a8c031d33"},
    ".claude/skills/research/agents/openai.yaml": {"sha256": "9b4c470d63221c1f68f22df70b83e2f12401b317babe0d1b7b5f24a974474d0d"},
    ".claude/skills/tdd/LICENSE": {"sha256": "0e7ac423bf2c6e223b7c5b156f8cf72da49d748e56a1641402c31f22ad07dbb5"},
    ".claude/skills/tdd/SKILL.md": {"sha256": "5505d25bbaa8fc14a79e4d20163936958992a2995b7f1dd1d6197edc9ed722e0"},
    ".claude/skills/tdd/agents/openai.yaml": {"sha256": "ea6f01cf1b8c06a4b0f5b649d74b1b8ce8685e72af1b38d70d877693e092af0b"},
    ".claude/skills/tdd/mocking.md": {"sha256": "3ceb807fdf4a47d6a93d4d9a891e5ba6d362a6247bd08adc451feebfc17361ef"},
    ".claude/skills/tdd/tests.md": {"sha256": "859f9e592c188fda4fc7277dd180e4ce9c7a2e13f6efe1f6f29eccc9d28c106a"},
    ".claude/skills/to-spec/LICENSE": {"sha256": "0e7ac423bf2c6e223b7c5b156f8cf72da49d748e56a1641402c31f22ad07dbb5"},
    ".claude/skills/to-spec/SKILL.md": {"sha256": "43ad9cf318e5e7d3d1fa360253a37021796dc87a0c2e595ad262661a10f85088"},
    ".claude/skills/to-spec/agents/openai.yaml": {"sha256": "1c5b4d1e3d8e52287ef19cc2742fdbbfae1914ac75d33af3e4c8174f08cc55bb"},
    ".claude/skills/to-tickets/LICENSE": {"sha256": "0e7ac423bf2c6e223b7c5b156f8cf72da49d748e56a1641402c31f22ad07dbb5"},
    ".claude/skills/to-tickets/SKILL.md": {"sha256": "56ec23c5b2782785d4e65bff9e315b6d3aeb4ef977c174a219e99489fada1995"},
    ".claude/skills/to-tickets/agents/openai.yaml": {"sha256": "21bc6215fffcd7614e9f772bb1760e87cc5fc7dcc707e7d282bc9414267a6090"},
    ".claude/skills/unslop/LICENSE": {"sha256": "bc957ca6bee02792566a1a028d105e02e247c6e77cf057061674273da77b200e"},
    ".claude/skills/unslop/SKILL.md": {"sha256": "ccab208e315ce05e2fab8eeee2f7879f1289b5c6844840b2d307adf31c79144f"},
    ".claude/skills/wayfinder/LICENSE": {"sha256": "0e7ac423bf2c6e223b7c5b156f8cf72da49d748e56a1641402c31f22ad07dbb5"},
    ".claude/skills/wayfinder/SKILL.md": {"sha256": "0c9fa96791aebf3b7d654cf35c6aadde97d81f57c17b07d13b27c14d9c46561f"},
    ".claude/skills/wayfinder/agents/openai.yaml": {"sha256": "88bc81a11a6d52ac67aeaa76b8b619e387020d47c5133a4dd4927fd15c4ad073"},
}
SKILLS = ".claude/skills/"  # skill copies: managed files whose source is skills/ (skills-bump)
COMMANDS = ("setup", "check", "test", "build")
DEFAULT_COMMANDS = {
    "setup": "N/A: 아직 정하지 않았다",
    "check": ["python3", "-I", ".baseline/baseline.py", "check"],
    "test": "N/A: 아직 정하지 않았다",
    "build": "N/A: 아직 정하지 않았다",
}
# Shell syntax only through `sh -c`, so every command runs the same on macOS, Linux and WSL2.
OTHER_SHELLS = {"bash", "zsh", "fish", "ksh", "dash", "csh", "tcsh"}
# What an easy-PR reviewer reads before the diff. prompts/review.md lives in repo-baseline only.
REVIEW_READ = ("AGENTS.md", "REVIEW.md", "prompts/review.md")
# Each file must stay under the limit an official doc gives for that kind of file (checked
# 2026-11-25, issue #175). No doc gives a limit for the reviewer's total, so it is printed only,
# and none gives a byte limit for AGENTS.md alone (Codex's 32 KiB counts all AGENTS.md together).
BUDGET = {
    # https://code.claude.com/docs/en/memory "target under 200 lines per CLAUDE.md file"
    "AGENTS.md": (200, "줄"),
    # https://code.claude.com/docs/en/code-review-customize "keep REVIEW.md and the files it
    # includes under 150,000 bytes combined". An include is an `@<file>` line naming a root file
    # or `.claude/skills/<folder>/SKILL.md` ("counts toward the limits of eight files and 150,000 bytes").
    "REVIEW.md": (150000, "바이트"),
    # https://code.claude.com/docs/en/skills "Keep SKILL.md under 500 lines"
    "prompts/review.md": (500, "줄"),
}
MAX_READ = 1 << 20

# review-preflight
BASELINE_REPO, TAG = "minjunkim-labs/repo-baseline", "v{}"
BOT = "dependabot[bot]"
INSTRUCTIONS = {"AGENTS.MD", "CLAUDE.MD", "REVIEW.MD"}
DOC_SUFFIXES = (".md", ".mdx", ".rst", ".txt", ".adoc")
AGENT_DIRS = {".claude", ".agents", ".codex", ".cursor"}
# shortcut: common manifest and lockfile names only; add a name when a repo's Dependabot touches another.
MANIFESTS = {
    "package.json", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lock",
    "pyproject.toml", "poetry.lock", "uv.lock", "Pipfile", "Pipfile.lock", "setup.py", "setup.cfg",
    "Gemfile", "Gemfile.lock", "go.mod", "go.sum", "Cargo.toml", "Cargo.lock", "composer.json", "composer.lock",
    "pom.xml", "build.gradle", "build.gradle.kts", "gradle.lockfile", "libs.versions.toml",
    "gradle-wrapper.properties", "Package.swift", "Package.resolved", "Podfile", "Podfile.lock",
    "pubspec.yaml", "pubspec.lock", "mix.exs", "mix.lock", "packages.lock.json", "Directory.Packages.props",
}
# enqueue
GRADES = ("문서", "쉬움", "어려움")
# POLICY §3: the reviewer's model tier and effort per grade. Never model names (ADR 0002).
REVIEW_TIERS = {"문서": None, "쉬움": {"model": "보통", "effort": "보통"}, "어려움": {"model": "무거움", "effort": "높음"}}
STANDING = "- 상시 지시:"
STANDING_COMMAND = "`python3 -I .baseline/baseline.py enqueue <PR> <리뷰한 head>`"
SHA_RE = re.compile(r"[0-9a-f]{40}")
PASSED = {"success", "neutral", "skipped"}
PR_QUERY = ("query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){pullRequest("
            "number:$number){id body createdAt userContentEdits(last:100){nodes{editedAt editor{__typename}}} "
            "reviewThreads(first:100){totalCount nodes{id isResolved comments(first:100){nodes{databaseId}}}}}}}")
REPORT_FIELDS = ("리뷰어", "리뷰한 head:", "리뷰한 모델:", "등급:", "고친 것:", "남은 지적:", "외부 리뷰 판정:")
RESOLVE = "mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}"
ENQUEUE = ("mutation($id:ID!,$sha:GitObjectID!){enqueuePullRequest(input:{pullRequestId:$id,expectedHeadOid:$sha})"
           "{mergeQueueEntry{position}}}")
HASH_RE = re.compile(r"\b[0-9a-f]{32,}\b|sha(?:1|256|384|512)-[A-Za-z0-9+/]+=*")
VERSION_RE = re.compile(r"\d+(?:\.\d+)+")


def linked(root, rel):
    """Is any part of root/rel a symlink?"""
    path = root
    for part in Path(rel).parts:
        path = path / part
        if path.is_symlink():
            return True
    return False


def read_file(root, rel):
    """check and budget read a PR tree in CI: regular files only, at most MAX_READ bytes.
    No symlink anywhere on the way: git ignores a symlinked .gitattributes, a linked .github moves the
    PR template, and a link to /dev/zero never ends."""
    path = root / rel
    if linked(root, rel) or not path.is_file():
        raise OSError("없거나 일반 파일이 아니다(symlink는 안 된다)")
    with path.open("rb") as f:
        data = f.read(MAX_READ + 1)
    if len(data) > MAX_READ:
        raise OSError(f"{MAX_READ}바이트를 넘는다")
    return data


def dump_json(obj):
    """Same bytes on every OS: sorted keys, LF, one final newline."""
    return (json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def block(data):
    """The bytes between the managed-block markers, or None unless there is exactly one block."""
    lines = data.splitlines(keepends=True)
    if lines.count(START) != 1 or lines.count(END) != 1:
        return None
    start, end = lines.index(START), lines.index(END)
    return b"".join(lines[start + 1:end]) if start < end else None


KINDS = ("sha256", "block_sha256", "prefix_sha256", "seed_sha256")


def digest(data, kind):
    """The hash a source file is recorded with. Only a managed block hashes part of the file."""
    if kind != "block_sha256":
        return sha256(data)
    inner = block(data)
    return None if inner is None else sha256(inner)


def after_prefix(data, want):
    """The bytes after the leading lines whose sha256 is want, or None when data does not start with them."""
    h, at = hashlib.sha256(), 0
    for line in (data or b"").splitlines(keepends=True):
        h.update(line)
        at += len(line)
        if h.hexdigest() == want:
            return data[at:]
    return None


def kind_of(rel, managed=None):
    """The MANAGED kind of a path, or None when it is not managed."""
    spec = (MANAGED if managed is None else managed).get(rel)
    return next(iter(spec)) if isinstance(spec, dict) and len(spec) == 1 else None


def source(rel):
    """Where repo-baseline keeps a managed file: skill copies in skills/, the rest in core/."""
    here = Path(__file__).resolve().parent
    return here / "skills" / rel[len(SKILLS):] if rel.startswith(SKILLS) else here / "core" / rel


def source_root():
    """repo-baseline clone root when core/ is next to this script (or its .baseline/ copy)."""
    here = Path(__file__).resolve().parent
    root = here.parent if here.name == ".baseline" else here
    return root if (root / "core").is_dir() else None


def repo_rel(rel):
    """Path of a managed file inside minjunkim-labs/repo-baseline."""
    return "skills/" + rel[len(SKILLS):] if rel.startswith(SKILLS) else "core/" + rel


def managed_rel_ok(rel):
    """Refuse path escape in managed keys (.github / .gitattributes stay allowed)."""
    return (isinstance(rel, str) and rel.isprintable() and "\\" not in rel and not rel.startswith("/")
            and not any(part in ("", ".", "..") for part in rel.split("/")))


def repo_root():
    # No resolve(): a symlinked .baseline/baseline.py must not move the root (check then refuses it).
    here = Path(os.path.abspath(__file__)).parent
    return here.parent if here.name == ".baseline" else Path.cwd()


def command_problem(name, value):
    # Control characters can make a printed command look like another one (hooks, CI and the cloud run it).
    parts = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    if not all(not isinstance(a, str) or a.isprintable() for a in parts):
        return f"{name}: 출력할 수 없는 문자가 있다"
    if isinstance(value, str):
        return None if value.startswith("N/A: ") and len(value) > 5 else f"{name}: 문자열이면 'N/A: <이유>'여야 한다"
    if not isinstance(value, list) or not value or not all(isinstance(a, str) and a for a in value):
        return f"{name}: 빈 문자열이 없는 argv 배열이어야 한다"
    if Path(value[0]).name in OTHER_SHELLS:
        return f"{name}: 셸은 [\"sh\", \"-c\", ...]로만 쓴다"
    return None


def command_line(name, value):
    return f"- {name}: `{value if isinstance(value, str) else shlex.join(value)}`"


def load_commands(root):
    """(commands, problems). Problems are messages; commands is None when the file is unusable."""
    try:
        commands = json.loads(read_file(root, ".baseline/commands.json"))
    except (OSError, ValueError) as error:
        return None, [f"commands.json을 읽지 못했다: {error}"]
    if not isinstance(commands, dict):
        return None, ["commands.json은 객체여야 한다"]
    problems = []
    for name in COMMANDS:
        problem = f"commands.json에 {name}이 없다" if name not in commands else command_problem(name, commands[name])
        if problem:
            problems.append(problem)
    return commands, problems


def core_files(commands):
    """Every file init writes, keyed by repo path. core/ must sit next to this script."""
    core = Path(__file__).resolve().parent / "core"
    files = {p.relative_to(core).as_posix(): p.read_bytes() for p in sorted(core.rglob("*")) if p.is_file()}
    files.update({rel: source(rel).read_bytes() for rel in MANAGED if rel.startswith(SKILLS)})
    files[".baseline/baseline.py"] = Path(__file__).read_bytes()
    # core/ holds a placeholder pin, so a change to this script never has to touch core/.claude/settings.json.
    files[".claude/settings.json"] = re.sub(rb'("--sha256",\s*")[0-9a-f]{64}"', b'\\g<1>' + sha256(files[".baseline/baseline.py"]).encode()
                                            + b'"', files[".claude/settings.json"])
    files[".baseline/commands.json"] = dump_json(commands)
    files[".baseline/baseline.json"] = dump_json({"version": VERSION, "profiles": [], "managed": MANAGED})
    return files


def symlinks(target, rels):
    """Symlinks on the way to any of rels. Writing through one (even a broken one) lands outside the repo."""
    links = set()
    for rel in rels:
        path = target
        for part in (".", *Path(rel).parts):
            path = path / part
            if path.is_symlink():
                links.add(path.as_posix())
    return sorted(links)


def need_core(command, target):
    if not target.is_dir():
        sys.exit(f"{command}: 폴더가 아니다: {target}")
    if not (Path(__file__).resolve().parent / "core").is_dir():
        sys.exit(f"{command}: core/가 없다. repo-baseline 클론의 baseline.py로 돌린다")


def cmd_init(args):
    target = Path(args.path)
    need_core("init", target)
    files = core_files(DEFAULT_COMMANDS)
    links = symlinks(target, (*files, ".gitignore"))
    if links:
        sys.exit("init: symlink는 따라가지 않는다: " + ", ".join(links))
    kept = {rel for rel in files if kind_of(rel) == "seed_sha256" and (target / rel).exists()}
    existing = sorted(rel for rel in files if (target / rel).exists() and rel not in kept)
    if existing:
        sys.exit("init: 이미 있다(기존 저장소는 migrate로 옮긴다): " + ", ".join(existing))
    # Read it before any write.
    try:
        ignore = with_env_ignore(target)
    except (OSError, ValueError) as error:
        sys.exit(f"init: .gitignore를 읽지 못했다(아무것도 쓰지 않았다): {error}")
    for rel, data in files.items():
        if rel in kept:
            print(f"init: {rel}: 시작 파일이 이미 있어 둔다")
            continue
        (target / rel).parent.mkdir(parents=True, exist_ok=True)
        (target / rel).write_bytes(data)
        print(f"init: {rel}")
    if ignore is not None:
        (target / ".gitignore").write_bytes(ignore)
        print("init: .gitignore (비밀값 줄 추가)")
    return 0


def with_env_ignore(target):
    """target's .gitignore with the secret lines it lacks added, or None when it has them all.
    It is the project's file, so nothing else changes. OSError or ValueError when it cannot be read as UTF-8."""
    ignore = target / ".gitignore"
    old = ignore.read_bytes().decode("utf-8") if ignore.exists() else ""  # bytes: read_text turns CRLF into LF
    added = [line for line in ENV_IGNORE if line not in old.splitlines() and line != "!.env.example"]
    # The last matching rule wins, so the exception goes after .env.*, also when only the exception is missing.
    added += ["!.env.example"] if added or "!.env.example" not in old.splitlines() else []
    if not added:
        return None
    nl = "\r\n" if "\r\n" in old else "\n"  # keep the file's own line endings
    lead = ("" if old.endswith("\n") else nl) + nl if old else ""
    text = lead + "# 비밀값은 커밋하지 않는다(repo-baseline POLICY §7)" + nl + "".join(line + nl for line in added)
    return (old + text).encode("utf-8")


def ignore_problems(root):
    """Secret file names the repository's own .gitignore does not ignore (POLICY §7).

    Checked in an empty repo holding only that file, so this machine's global ignore and
    .git/info/exclude cannot make it pass here and fail in CI."""
    path = root / ".gitignore"
    try:
        data = read_file(root, ".gitignore") if path.exists() or path.is_symlink() else b""
    except OSError as error:
        return [f".gitignore: {error}"]
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / ".gitignore").write_bytes(data)
        # No GIT_* from the caller: a git hook sets GIT_DIR, and git would then use that repo and its info/exclude.
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        result = subprocess.run(["git", "init", "-q", "--template=", tmp], capture_output=True, env=env)  # no info/exclude
        if not result.returncode:
            result = subprocess.run(["git", "-c", f"core.excludesFile={os.devnull}", "check-ignore", "--no-index",
                                     "--stdin"], cwd=tmp, capture_output=True, env=env,
                                    input="\n".join(ENV_SAMPLES + (".env.example",)).encode())
    if result.returncode not in (0, 1):
        return [f".gitignore를 확인하지 못했다: {result.stderr.decode('utf-8', 'replace').strip()}"]
    ignored = result.stdout.decode("utf-8", "replace").splitlines()
    problems = []
    missing = [name for name in ENV_SAMPLES if name not in ignored]
    if missing:
        problems.append(f".gitignore: 비밀값 파일을 ignore하지 않는다({', '.join(missing)}). "
                        f"이 줄을 더한다: {' '.join(ENV_IGNORE)}")
    if ".env.example" in ignored:
        problems.append(".gitignore: `.env.example`까지 ignore한다. `!.env.example`을 `.env.*` 뒤에 둔다")
    return problems


# migrate
OLD_MANIFEST = ".github/repo-baseline.json"  # v1 hash-copy
OTHER_INSTRUCTIONS = ("GEMINI.md", ".cursorrules", ".cursor/rules", ".windsurfrules", ".github/copilot-instructions.md")
SHELL_SYNTAX = re.compile(r"[|&;<>()$*?~{}\[\]\\'\"#]")
COMMAND_CELL = re.compile(r"- (setup|check|test|build): (.*)")
MOVED_CLAUDE = "## CLAUDE.md에서 옮긴 것\n\n".encode("utf-8")


def draft_command(cell):
    """(commands.json value, prose left out) for an old command cell such as "`make test`  (CI도)".
    The value is None when the cell has no backticks and no N/A: it may be a command or prose."""
    cell = cell.strip()
    code = re.fullmatch(r"`([^`]*)`(.*)", cell)
    cmd, prose = (code.group(1).strip(), code.group(2).strip()) if code else (cell, "")
    if cmd.startswith("N/A") or not cmd:
        return "N/A: " + (cmd[3:].lstrip(":").strip() or "이유를 쓴다"), prose
    if code is None:
        return None, cell
    argv = cmd.split()
    if SHELL_SYNTAX.search(cmd) or "=" in argv[0] or Path(argv[0]).name in OTHER_SHELLS:
        return ["sh", "-c", cmd], prose
    return argv, prose


def insert_before_block(data, extra):
    lines = data.splitlines(keepends=True)
    at = lines.index(START) if START in lines else len(lines)
    head = b"".join(lines[:at]).rstrip(b"\n")
    return (head + b"\n\n" if head else b"") + extra.rstrip(b"\n") + b"\n\n" + b"".join(lines[at:])


def with_block(data, core_data):
    """data with this version's managed block (replaced, or appended when there is none), or None."""
    lines = data.splitlines(keepends=True)
    if START not in lines and END not in lines:
        head = data.rstrip(b"\n")
        return (head + b"\n\n" if head else b"") + START + block(core_data) + END
    return None if block(data) is None else replace_block(data, block(core_data))


def overlapping_headings(data, core_data):
    """Headings of the core block that the project already has outside its block (v1 copied them by hand)."""
    lines = data.splitlines(keepends=True)
    if block(data) is not None:
        lines = lines[:lines.index(START)] + lines[lines.index(END) + 1:]
    ours = {line for line in block(core_data).splitlines(keepends=True) if line.startswith(b"#")}
    return sorted(line.decode("utf-8", "replace").strip() for line in set(lines) & ours)


def migrate_agents(data, core_data, extra, blocks, notes):
    """(new AGENTS.md or None, drafted commands or None). Each None comes with a reason in blocks.
    extra is the text moved from CLAUDE.md; migrate_plan has made sure it holds no command cell."""
    try:
        lines = (insert_before_block(data, extra) if extra else data).decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        blocks.append("AGENTS.md: UTF-8이 아니다")
        return None, None
    drafts, last = {}, None
    marks = START.decode(), END.decode()
    inside = range(lines.index(marks[0]), lines.index(marks[1])) if all(m in lines for m in marks) else range(0)
    for i, line in enumerate(lines):
        match = COMMAND_CELL.fullmatch(line.rstrip("\n"))
        if not match:
            continue
        name, cell = match.groups()
        if not cell.strip().isprintable():
            blocks.append(f"AGENTS.md 명령 칸 {name}에 출력할 수 없는 문자가 있다. 지운 뒤 다시 migrate한다")
            return None, None
        if name in drafts:
            blocks.append(f"AGENTS.md: 명령 칸 {name}이 여러 줄이다. 한 줄만 남긴다")
            return None, None
        drafts[name], prose = draft_command(cell)
        if drafts[name] is None:
            blocks.append(f"AGENTS.md 명령 칸 {name}: 명령을 backtick으로 감싸거나 `N/A: <이유>`로 쓴다: {cell!r}")
            return None, None
        # The prose stays, one line below, where check does not read it.
        lines[i] = command_line(name, drafts[name]) + "\n" + (f"  - {prose}\n" if prose else "")
        last = last if i in inside else i  # a cell inside the old block goes with it; the check below says so
        if "`" in prose:
            notes.append(f"AGENTS.md 명령 칸 {name}의 산문에 명령이 더 있다: {prose!r}. 초안에 넣을지 정한다")
        elif prose:
            notes.append(f"AGENTS.md 명령 칸 {name}에 산문이 섞였다: {prose!r}. 명령에서 빼 아래 줄로 옮긴다")
        if drafts[name][:2] == ["sh", "-c"]:
            notes.append(f"AGENTS.md 명령 칸 {name}에 셸 문법이 있어 sh -c로 감쌌다")
    missing = [name for name in COMMANDS if name not in drafts]
    drafts.update({name: DEFAULT_COMMANDS[name] for name in missing})
    added = "".join(command_line(name, drafts[name]) + "\n" for name in missing)
    if missing:
        notes.append("AGENTS.md에 명령 칸이 없다: " + ", ".join(missing) + ". 기본값을 쓴다")
    if last is not None:
        lines[last] += added
    new = "".join(lines).encode("utf-8")
    if last is None and missing:
        new = insert_before_block(new, ("## 명령\n\n`python3 -I .baseline/baseline.py run test`처럼 부른다. "
                                        "이 칸은 `.baseline/commands.json`과 같아야 한다.\n\n" + added).encode("utf-8"))
    new = with_block(new, core_data)
    if new is None:
        blocks.append("AGENTS.md: 관리 블록 표시가 하나씩 있어야 한다")
        return None, drafts
    # The line is core's default (POLICY: the owner deletes it to opt out); enqueue reads it from base.
    standing = [line for line in new.decode("utf-8").splitlines() if line.startswith(STANDING)]
    if not standing:
        core = core_data.decode("utf-8")
        new = insert_before_block(new, core[core.index("## 병합\n"):core.index(START.decode())].encode("utf-8"))
        notes.append("AGENTS.md: 상시 지시 줄이 없어 코어의 「병합」 절을 블록 앞에 더한다. 끄려면 그 줄을 지운다")
    elif not any(STANDING_COMMAND in line for line in standing):
        notes.append(f"AGENTS.md: 상시 지시 줄에 {STANDING_COMMAND}이 없어 enqueue가 모든 PR을 거절한다. "
                     "켜려면 그 명령을 줄에 넣는다")
    # check's own rule, so --apply never writes what check then refuses.
    got = new.decode("utf-8").splitlines()
    for name in COMMANDS:
        if [line for line in got if line.startswith(f"- {name}: ")] != [command_line(name, drafts[name])]:
            blocks.append(f"AGENTS.md: 명령 칸 {name}이 관리 블록 안에 있다. 블록 밖으로 옮긴 뒤 다시 migrate한다")
            return None, drafts
    return new, drafts


def recorded_hashes(target):
    """{path: sha256} that the v1 hash-copy manifest recorded. A file still at its hash is a pristine v1 copy."""
    try:
        files = json.loads(read_file(target, OLD_MANIFEST)).get("files", {})
        return {rel: entry["sha256"] for rel, entry in files.items() if isinstance(entry.get("sha256"), str)}
    except (OSError, ValueError, AttributeError, TypeError):
        return {}


def migrate_plan(target):
    """(blocks, notes, writes, drafts). Any block stops --apply; writes maps repo path -> new bytes."""
    blocks, notes, writes = [], [], {}
    if (target / ".baseline").exists() or (target / ".baseline").is_symlink():
        return [".baseline/: 이미 v2다. upgrade로 판을 올린다"], notes, writes, None
    files = core_files(DEFAULT_COMMANDS)
    links = symlinks(target, (*files, ".gitignore"))
    if links:
        hint = ". CLAUDE.md는 지우면 migrate가 `@AGENTS.md` 파일로 만든다" if any(
            Path(link).name == "CLAUDE.md" for link in links) else ""
        return ["symlink는 따라가지 않는다: " + ", ".join(links) + hint], notes, writes, None
    in_the_way = sorted({parent.as_posix() for rel in files for parent in Path(rel).parents
                         if parent != Path(".") and (target / parent).exists() and not (target / parent).is_dir()})
    if in_the_way:
        return [f"{rel}: 폴더여야 하는데 파일이다" for rel in in_the_way], notes, writes, None

    read = {}

    def have(rel):
        try:
            read[rel] = read_file(target, rel)
            return read[rel]
        except OSError as error:
            blocks.append(f"{rel}: {error}")
            return None

    clashing = set()
    for name in sorted({rel[len(SKILLS):].split("/")[0] for rel in MANAGED if rel.startswith(SKILLS)}):
        if not (target / SKILLS / name).exists():
            continue
        found = {p.relative_to(target).as_posix() for p in (target / SKILLS / name).rglob("*")
                 if p.is_symlink() or not p.is_dir()}
        want = {rel for rel in MANAGED if rel.startswith(f"{SKILLS}{name}/")}
        if found != want or any(have(rel) != files[rel] for rel in want):
            clashing.add(name)
            blocks.append(f"{SKILLS}{name}/: 같은 이름 스킬이 있다. 이름을 바꾸거나 지운 뒤 다시 migrate한다")

    extra, moved_cells = b"", []
    claude =have("CLAUDE.md") if (target / "CLAUDE.md").exists() else files["CLAUDE.md"]
    if not (target / "CLAUDE.md").exists():
        writes["CLAUDE.md"] = claude
    elif claude is not None and claude != files["CLAUDE.md"]:
        body = b"".join(line for line in claude.splitlines(keepends=True) if line.strip() != b"@AGENTS.md")
        try:
            body.decode("utf-8")
        except UnicodeDecodeError:
            blocks.append("CLAUDE.md: UTF-8이 아니다")
        if {START, END} & set(body.splitlines(keepends=True)):
            # Moved into AGENTS.md, the markers would make with_block replace that text with the core block.
            blocks.append("CLAUDE.md: 관리 블록 표시가 있다. 표시를 지우거나 내용을 옮긴 뒤 다시 migrate한다")
        extra = MOVED_CLAUDE + body.strip() + b"\n" if body.strip() else b""
        # Checked on the moved text itself (strip() can turn an indented line into a cell).
        # A moved cell would clash with or replace an AGENTS.md cell; a human picks the one to keep.
        moved_cells = [f"CLAUDE.md: 명령 칸 {match.group(1)}이 있다. AGENTS.md의 명령 칸으로 옮긴 뒤 다시 migrate한다"
                       for match in map(COMMAND_CELL.fullmatch, extra.decode("utf-8", "replace").splitlines()) if match]
        blocks += moved_cells
        notes.append("CLAUDE.md: 내용을 AGENTS.md로 옮기고 `@AGENTS.md` 한 줄로 바꾼다")
        writes["CLAUDE.md"] = files["CLAUDE.md"]

    agents = have("AGENTS.md") if (target / "AGENTS.md").exists() else files["AGENTS.md"]
    drafts = None
    if agents is not None and not moved_cells:  # else every moved cell would also report as an AGENTS.md clash
        new, drafts = migrate_agents(agents, files["AGENTS.md"], extra, blocks, notes)
        if new is not None and (new != agents or not (target / "AGENTS.md").exists()):
            writes["AGENTS.md"] = new
    files[".baseline/commands.json"] = dump_json(drafts or DEFAULT_COMMANDS)

    try:
        ignore = with_env_ignore(target)
    except (OSError, ValueError) as error:
        blocks.append(f".gitignore를 읽지 못했다: {error}")
    else:
        if ignore is not None:
            writes[".gitignore"] = ignore
            notes.append(".gitignore: 비밀값 줄이 빠져 있어 더한다")

    recorded = recorded_hashes(target)
    for rel, data in files.items():
        if rel in ("AGENTS.md", "CLAUDE.md") or rel.startswith(SKILLS):
            if rel.startswith(SKILLS) and not (target / rel).exists() and rel.split("/")[2] not in clashing:
                writes[rel] = data
            continue
        if not (target / rel).exists():
            writes[rel] = data
            continue
        old = have(rel)
        if old is None or old == data:
            continue
        if kind_of(rel) == "seed_sha256":
            notes.append(f"{rel}: 코어 판과 다르다. 시작 파일이라 저장소 판을 둔다")
        elif kind_of(rel) == "prefix_sha256":
            if after_prefix(old, MANAGED[rel]["prefix_sha256"]) is None:
                writes[rel] = data + old
                notes.append(f"{rel}: 맨 앞에 코어 줄을 넣는다. `git add --renormalize .`로 줄 끝을 다시 맞춰 커밋한다")
        elif kind_of(rel) == "block_sha256":
            new = with_block(old, data)
            if new is None:
                blocks.append(f"{rel}: 관리 블록 표시가 하나씩 있어야 한다")
            else:
                writes[rel] = new
        elif rel in MANAGED and recorded.get(rel) == sha256(old):
            writes[rel] = data
            notes.append(f"{rel}: 옛 hash-copy 사본 그대로라 이 판으로 바꾼다")
        elif rel in MANAGED:
            blocks.append(f"{rel}: 프로젝트 내용이 있다. 덮어쓰면 잃으니 손으로 옮기거나 지운 뒤 다시 migrate한다")
        else:
            notes.append(f"{rel}: 이미 있어 둔다. core/{rel}과 손으로 합친다"
                         + ("(훅의 --sha256은 .baseline/baseline.py의 해시와 같아야 한다)" if rel == ".claude/settings.json" else ""))
    blocks += [f"{rel}: 쓸 내용이 {MAX_READ}바이트를 넘는다. check가 읽지 못하니 줄인 뒤 다시 migrate한다"
               for rel, data in writes.items() if len(data) > MAX_READ]
    for rel in ("AGENTS.md", "REVIEW.md"):
        if rel in writes and rel in read:
            notes += [f"{rel}: 관리 블록과 겹치는 절 {heading!r}이 블록 밖에 있다. 확인 뒤 지운다"
                      for heading in overlapping_headings(read[rel], files[rel])]

    workflows = sorted(p.relative_to(target).as_posix() for p in (target / ".github/workflows").glob("*.y*ml"))
    notes.append("CI: " + (", ".join(workflows) + "에서 `python3 -I .baseline/baseline.py check`를 돌리게 고친다"
                           if workflows else "workflow가 없다. check를 돌리는 workflow를 더한다")
                 + "(migrate는 workflow를 바꾸지 않는다)")
    if (target / OLD_MANIFEST).exists():
        notes.append(f"{OLD_MANIFEST}: 옛 hash-copy manifest다. v2 check가 대신하니 그 check를 부르는 CI 단계와 함께 지운다")
    notes += [f"{rel}: 도구별 지침 파일이다. 내용을 AGENTS.md로 옮기고 지운다"
              for rel in OTHER_INSTRUCTIONS if (target / rel).exists()]
    return blocks, notes, writes, drafts


def replace_file(path, data):
    """Write through a new file in the same folder, then rename it over path. A link at path (hard or
    symbolic, even one made after the plan) is replaced, not written through, and a failed write leaves no half file."""
    tmp = path.with_name(f".{path.name}.migrate-{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        if path.is_file() and not path.is_symlink():
            os.chmod(tmp, path.stat().st_mode & 0o7777)
        os.replace(tmp, path)
    except BaseException:
        if tmp.exists():
            tmp.unlink()
        raise


def cmd_migrate(args):
    target = Path(args.path)
    need_core("migrate", target)
    blocks, notes, writes, drafts = migrate_plan(target)
    print("충돌:")
    for line in [f"- 막힘 {b}" for b in blocks] + [f"- 확인 {n}" for n in notes]:
        print(line)
    print("계획:")
    for rel in sorted(rel for rel in writes if not rel.startswith(SKILLS)):
        print(f"- {'고친다' if (target / rel).exists() else '새로 쓴다'} {rel}")
    skills = sorted({rel.split("/")[2] for rel in writes if rel.startswith(SKILLS)})
    if skills:
        print(f"- 새로 쓴다 {SKILLS}: " + ", ".join(skills))
    if drafts is not None:
        print("commands.json 초안(사람이 확인한다. check는 Stop 훅에서, setup·check·test는 CI와 클라우드에서 돈다):")
        for name in COMMANDS:
            print(command_line(name, drafts[name]))
    if blocks:
        print("migrate: 막힘을 풀기 전에는 --apply도 아무것도 쓰지 않는다", file=sys.stderr)
        return 1
    if not args.apply:
        print("migrate: 계획을 받아들이려면 --apply를 붙여 다시 돌린다")
        return 0
    # CLAUDE.md last: its text is in the new AGENTS.md only once that write has landed.
    for rel in sorted(writes, key=lambda rel: rel == "CLAUDE.md"):
        (target / rel).parent.mkdir(parents=True, exist_ok=True)
        replace_file(target / rel, writes[rel])
    print(f"migrate: 파일 {len(writes)}개를 썼다. commands.json 초안을 확인하고 check를 돌린다")
    return 0


def cmd_check(args):
    root = repo_root()
    problems = []
    if Path(os.path.abspath(__file__)).parent.name == ".baseline":
        try:
            read_file(root, ".baseline/baseline.py")
        except OSError as error:
            problems.append(f".baseline/baseline.py: {error}")
    try:
        recorded = json.loads(read_file(root, ".baseline/baseline.json"))
    except (OSError, ValueError) as error:
        problems.append(f"baseline.json을 읽지 못했다: {error}")
    else:
        if not isinstance(recorded, dict):
            problems.append("baseline.json은 객체여야 한다")
        elif recorded.get("version") != VERSION:
            problems.append(f"baseline.json의 판 {recorded.get('version')!r}이 baseline.py의 판 {VERSION!r}과 다르다")
        if isinstance(recorded, dict) and recorded.get("managed") != MANAGED:
            problems.append("baseline.json의 관리 해시가 baseline.py 안의 해시와 다르다")
        if isinstance(recorded, dict) and isinstance(recorded.get("profiles"), list) and "ops" in recorded["profiles"]:
            problems += ops_problems(root)
    for rel, expected in MANAGED.items():
        (kind, want), = expected.items()
        if kind == "seed_sha256":
            if (root / rel).exists() or (root / rel).is_symlink():
                try:  # the content is the repo's; a link would make the skills read a file outside it
                    read_file(root, rel)
                except OSError as error:
                    problems.append(f"{rel}: {error}")
            continue
        try:
            data = read_file(root, rel)
        except OSError as error:
            problems.append(f"{rel}: {error}")
            continue
        got = digest(data, kind)
        if kind == "prefix_sha256":
            if after_prefix(data, want) is None:
                problems.append(f"{rel}: 맨 앞 줄이 이 판과 다르다")
        elif got is None:
            problems.append(f"{rel}: 관리 블록 표시가 하나씩 있어야 한다")
        elif got != want:
            problems.append(f"{rel}: {'관리 블록이' if kind == 'block_sha256' else '파일이'} 이 판과 다르다")
    problems += ignore_problems(root)
    # A file added to a skill copy changes the skill too. Other folders in .claude/skills/ are the project's.
    for name in sorted({rel[len(SKILLS):].split("/")[0] for rel in MANAGED if rel.startswith(SKILLS)}):
        if linked(root, SKILLS + name):  # os.walk opens a linked top folder; read_file above already reported it
            continue
        for folder, dirs, names in os.walk(root / SKILLS / name):
            for entry in names + [d for d in dirs if Path(folder, d).is_symlink()]:
                rel = Path(folder, entry).relative_to(root).as_posix()
                if rel not in MANAGED:
                    problems.append(f"{rel}: 이 판의 스킬 사본에 없는 파일이다")
    commands, command_problems = load_commands(root)
    problems += command_problems
    if commands is not None:
        try:
            lines = read_file(root, "AGENTS.md").decode("utf-8").splitlines()
        except (OSError, ValueError):
            lines = []
        for name in COMMANDS:
            if name not in commands:
                continue
            found = [line for line in lines if line.startswith(f"- {name}: ")]
            if found != [command_line(name, commands[name])]:
                problems.append(f"AGENTS.md 명령 칸 {name}이 commands.json과 다르다. 이 한 줄이어야 한다: "
                                + command_line(name, commands[name]))
    for problem in problems:
        print(f"check: {problem}", file=sys.stderr)
    if problems:
        return 1
    print("check: 통과")
    return 0


def mise_prefix(root):
    """argv prefix for the pinned toolchain: [] without settings in .mise.toml, else `mise exec --`."""
    data, refused = repo_bytes(root, ".mise.toml")
    try:
        text = "" if data is None else data.decode("utf-8")
    except UnicodeDecodeError:
        refused = True
    if refused:
        sys.exit("run: .mise.toml을 읽지 못했다")
    if not any(section != "settings" for section, _ in mise_keys(text)):
        return []
    if not shutil.which("mise"):
        sys.exit("run: .mise.toml이 툴체인 판을 정하는데 mise가 없다. doctor가 설치 명령을 출력한다")
    # mise install and mise exec trust their own config (https://mise.jdx.dev/cli/trust.html, 2026-11-24).
    return ["mise", "exec", "--"]


def mise_keys(text):
    """(section, key) of every key line in .mise.toml; "" is the top level."""
    keys, section = [], ""
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line.startswith("[") and line.endswith("]"):
            section = line.strip("[]").strip()
        elif "=" in line:
            keys.append((section, line.split("=", 1)[0].strip()))
    return keys


def mise_failed(root, code):
    """Name `mise trust` after a failed mise step: paranoid mode and older mise still refuse the file."""
    if code:
        print("run: mise가 .mise.toml을 신뢰하지 않는다는 오류면 고치는 명령: mise trust "
              + shlex.quote(root.joinpath(".mise.toml").as_posix()), file=sys.stderr)
    return code


def cmd_run(args):
    root = repo_root()
    commands, problems = load_commands(root)
    if commands is None:
        sys.exit(f"run: {problems[0]}")
    if args.name not in commands:
        sys.exit(f"run: commands.json에 {args.name}이 없다")
    value = commands[args.name]
    problem = command_problem(args.name, value)
    if problem:
        sys.exit(f"run: {problem}")
    if isinstance(value, str) and args.name != "setup":  # N/A needs no toolchain
        print(f"run: {args.name}은 {value}")
        return 0
    prefix = mise_prefix(root)
    if prefix and args.name == "setup":
        try:
            code = subprocess.run(["mise", "install"], cwd=root).returncode
        except OSError as error:
            sys.exit(f"run: mise install을 시작하지 못했다: {error}")
        if code:
            return mise_failed(root, code)
    if isinstance(value, str):
        print(f"run: {args.name}은 {value}")
        return 0
    try:
        return subprocess.run(prefix + value, cwd=root).returncode
    except OSError as error:
        sys.exit(f"run: {args.name}을 시작하지 못했다: {error}")


def cmd_budget(args):
    root = repo_root()
    read = {}
    for rel in REVIEW_READ:
        if rel.startswith("prompts/") and not (root / rel).exists() and not (root / rel).is_symlink():
            continue
        try:
            read[rel] = read_file(root, rel)
        except OSError as error:
            sys.exit(f"budget: {rel}: {error}")
    over = False
    for rel, data in read.items():
        limit, unit = BUDGET[rel]
        if rel == "REVIEW.md":
            # Each name once, and stop at the limit: repeated lines must not make CI read without end.
            for name in dict.fromkeys(re.findall(rb"^@([^/\s]+|\.claude/skills/[^/\s]+/SKILL\.md)[ \t\r]*$",
                                                 data, re.M)):
                if len(data) >= limit:
                    break
                if (root / name.decode()).is_file():
                    try:
                        data += read_file(root, name.decode())
                    except OSError as error:
                        sys.exit(f"budget: {name.decode()}: {error}")
        size = len(data) if unit == "바이트" else data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
        print(f"budget: {rel} {size}{unit}(상한 {limit}{unit} 미만)" + (f", {len(data)}바이트" if unit == "줄" else ""))
        over |= size >= limit
    print(f"budget: 리뷰어 읽기 {sum(map(len, read.values()))}바이트(출력만): {', '.join(read)}")
    if over:
        print("budget: 상한을 넘었다", file=sys.stderr)
        return 1
    return 0


def gh_api(path, raw=False):
    """GitHub REST through `gh api`. Never GraphQL: the cloud sessions' proxy blocks it.
    raw returns file bytes, or None when the file is not there."""
    accept = "application/vnd.github.raw+json" if raw else "application/vnd.github+json"
    result = subprocess.run(["gh", "api", "-H", f"Accept: {accept}", path], capture_output=True)
    code, stdout, stderr = result.returncode, result.stdout, result.stderr
    if code and b"IP allow list" in stderr:  # e.g. cursor/plugins refuses the Actions token (#175)
        refused = stderr.strip()
        code, stdout, stderr = anonymous_api(path, accept)
        if code:  # keep why the token failed: a private repo answers 404 without one
            stderr += b"; " + refused
    if code:
        if raw and b"(HTTP 404)" in stderr:
            return None
        raise OSError(f"gh api {path}: {stderr.decode('utf-8', 'replace').strip()}")
    if len(stdout) > MAX_READ * 32:
        raise OSError(f"gh api {path}: 응답이 너무 크다")
    if raw:
        if len(stdout) > MAX_READ:
            raise OSError(f"{path}: {MAX_READ}바이트를 넘는다")
        return stdout
    return json.loads(stdout)


def anonymous_api(path, accept):
    """(code, body, error) of the same REST call without a token. An org's IP allow list refuses tokens
    from other IPs; its public repos stay readable without one (60 calls an hour, so only as a retry)."""
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen
    request = Request(f"https://api.github.com/{path}", headers={"Accept": accept, "User-Agent": "repo-baseline"})
    try:
        with urlopen(request, timeout=30) as response:
            return 0, response.read(MAX_READ * 32 + 1), b""
    except HTTPError as error:
        return 1, b"", f"토큰 없이: {error.reason} (HTTP {error.code})".encode()
    except OSError as error:  # URLError: network failure or timeout
        return 1, b"", f"토큰 없이: {error}".encode()


def pages(path, key=None):
    """Every item of a paginated REST list (key: the list inside an object response)."""
    items, page = [], 1
    while True:
        data = gh_api(f"{path}{'&' if '?' in path else '?'}per_page=100&page={page}")
        chunk = data.get(key) if key else data
        if not isinstance(chunk, list):
            raise ValueError(f"{path}: 목록이 아니다")
        items += chunk
        if len(chunk) < 100:
            return items
        page += 1


def contents(repo, rel, ref):
    return gh_api(f"repos/{repo}/contents/{quote(rel)}?ref={quote(ref)}", raw=True)


def env_file_names(paths):
    """(hits, examples): any folder or file name starting with .env is a hit, except .env.example files."""
    hits, examples = set(), set()
    for path in paths:
        *folders, name = path.split("/")
        if any(f.startswith(".env") for f in folders) or (name.startswith(".env") and name != ".env.example"):
            hits.add(path)
        elif name == ".env.example":
            examples.add(path)
    return sorted(hits), sorted(examples)


def is_manifest(name):
    return name in MANIFESTS or fnmatch.fnmatchcase(name, "requirements*.txt") or name.endswith(".csproj")


def is_mise_config(path):
    """Files mise reads as config (https://mise.jdx.dev/configuration.html, 2026-11-24)."""
    *folders, name = path.split("/")
    return (fnmatch.fnmatchcase(name, "*mise*.toml") or name in {".tool-versions", "mise.lock"}
            or any(folder in {".mise", "mise"} for folder in folders))


def is_sensitive(path, patterns):
    parts = path.split("/")
    # .gitattributes can hide a file's diff from review (`-diff`, `binary`), wherever its lines are.
    return (parts[-1] in {".mcp.json", "CODEOWNERS", ".gitattributes"} or is_manifest(parts[-1]) or is_mise_config(path)
            or any(part in AGENT_DIRS or part in {".github", ".baseline"} for part in parts)
            or any(fnmatch.fnmatchcase(path, p) or path.startswith(p.rstrip("*").rstrip("/") + "/")
                   for p in patterns))


def is_doc(path):
    name = path.rsplit("/", 1)[-1]
    return (name.endswith(DOC_SUFFIXES) and name.upper() not in INSTRUCTIONS and name != "SKILL.md"
            and path not in MANAGED and not path.startswith("prompts/") and "skills" not in path.split("/"))


def outside(data):
    """The bytes around the managed block, which the project writes."""
    if data is None or block(data) is None:
        return data
    lines = data.splitlines(keepends=True)
    return b"".join(lines[:lines.index(START) + 1] + lines[lines.index(END):])


def section(data, title):
    """Non-empty lines of a `## title` section outside the managed block."""
    found, inside = [], False
    for line in (outside(data) or b"").decode("utf-8", "replace").splitlines():
        if line.startswith("## "):
            inside = line == f"## {title}"
        elif inside and line.strip():
            found.append(line.strip())
    return found


def sensitive_patterns(review):
    """The `path` globs in REVIEW.md 「민감한 파일」, in list items or prose: a missed path lowers the grade."""
    return [p for line in section(review, "민감한 파일") for p in re.findall(r"`([^`]+)`", line)]


def embedded_assign(source, name):
    """Literal value of a top-level assignment in a baseline.py, or None. The tag's code is never run."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign) and [getattr(t, "id", None) for t in node.targets] == [name]:
            try:
                return ast.literal_eval(node.value)
            except ValueError:
                return None
    return None


def embedded_managed(source):
    """MANAGED of a baseline.py, read with ast. The tag's code is never run."""
    value = embedded_assign(source, "MANAGED")
    if isinstance(value, dict) and all(isinstance(v, dict) and len(v) == 1 and
                                       next(iter(v)) in KINDS for v in value.values()):
        return value
    return None


def replace_block(data, inner):
    """data with the managed-block body replaced. data must already have one marker pair."""
    lines = data.splitlines(keepends=True)
    start, end = lines.index(START), lines.index(END)
    return b"".join(lines[:start + 1]) + inner + b"".join(lines[end:])


def tag_commit(tag):
    """Commit SHA of a tag that main already holds."""
    target = gh_api(f"repos/{BASELINE_REPO}/git/ref/tags/{tag}")["object"]
    if target["type"] == "tag":
        target = gh_api(f"repos/{BASELINE_REPO}/git/tags/{target['sha']}")["object"]
    if target["type"] != "commit":
        raise OSError(f"태그 {tag}가 커밋을 가리키지 않는다")
    if gh_api(f"repos/{BASELINE_REPO}/compare/{target['sha']}...main")["status"] not in ("ahead", "identical"):
        raise OSError(f"태그 {tag}가 {BASELINE_REPO} main에 없는 커밋이다")
    return target["sha"]


def pristine_block_file(rel, version, want):
    """Bytes of a managed block file as recorded for `version`, for the stop-and-diff path."""
    home = source_root()
    if home is not None:
        try:
            data = read_file(home, repo_rel(rel))
        except OSError:
            data = None
        if data is not None and digest(data, "block_sha256") == want:
            return data
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        raise OSError(f"{rel}: 판 {version!r}의 원본 관리 블록을 찾지 못했다")
    data = contents(BASELINE_REPO, repo_rel(rel), tag_commit(TAG.format(version)))
    if data is None or digest(data, "block_sha256") != want:
        raise OSError(f"{rel}: 원본 관리 블록을 읽지 못했다")
    return data

def upgrade(root, tag_name):
    """Replace managed blocks, managed files and skill copies with the tag's bytes; refresh baseline.json."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", tag_name or "")
    if not match:
        raise ValueError(f"태그는 vX.Y.Z 형태여야 한다: {tag_name!r}")
    version = ".".join(match.groups())
    tag = TAG.format(version)
    recorded = json.loads(read_file(root, ".baseline/baseline.json"))
    if not isinstance(recorded, dict) or not isinstance(recorded.get("managed"), dict):
        raise ValueError("baseline.json이 객체가 아니거나 managed가 없다")
    current = re.match(r"(\d+)\.(\d+)\.(\d+)", str(recorded.get("version")))
    if current and (tuple(map(int, match.groups())) < tuple(map(int, current.groups()))
                    or recorded.get("version") == version):
        raise ValueError("판을 올리지 않는다")
    sha = tag_commit(tag)
    source = contents(BASELINE_REPO, "baseline.py", sha)
    managed = embedded_managed(source) if source is not None else None
    if source is None or managed is None:
        raise OSError(f"{BASELINE_REPO}의 태그 {tag}에서 baseline.py의 관리 해시를 읽지 못했다")
    if embedded_assign(source, "VERSION") != version:
        raise OSError(f"태그 {tag}의 VERSION이 {version!r}이 아니다")
    bad = sorted({rel for rel in list(managed) + list(recorded["managed"]) if not managed_rel_ok(rel)})
    if bad:
        raise OSError("쓸 수 없는 관리 경로: " + ", ".join(bad))
    # Stop before any write when a managed block was edited in the consumer.
    for rel, spec in sorted(recorded["managed"].items()):
        if "block_sha256" not in spec:
            continue
        want = spec["block_sha256"]
        try:
            local = read_file(root, rel)
        except OSError as error:
            raise OSError(f"{rel}: {error}") from error
        local_hash = digest(local, "block_sha256")
        new_spec = managed.get(rel) or {}
        # local_hash is None when markers are gone — do not treat None == None as "already applied".
        if local_hash is not None and (local_hash == want or new_spec.get("block_sha256") == local_hash):
            continue  # recorded, or a partial upgrade that already wrote the tag block
        if "sha256" in new_spec and digest(local, "sha256") == new_spec["sha256"]:
            continue  # partial upgrade already wrote the whole-file tag bytes
        try:
            expected = pristine_block_file(rel, str(recorded.get("version")), want)
        except OSError as error:
            print(f"upgrade: {rel}: 관리 블록이 고쳐져 있다", file=sys.stderr)
            print(f"upgrade: {error}", file=sys.stderr)
            return 1
        before = (block(expected) or b"").decode("utf-8", "replace").splitlines(True)
        after = (block(local) or b"").decode("utf-8", "replace").splitlines(True)
        diff = "".join(difflib.unified_diff(before, after, fromfile=f"a/{rel}", tofile=f"b/{rel}"))
        print(f"upgrade: {rel}: 관리 블록이 고쳐져 있다", file=sys.stderr)
        if diff:
            print(diff, end="" if diff.endswith("\n") else "\n", file=sys.stderr)
        return 1
    files = {}
    for rel in managed:
        if kind_of(rel, managed) == "seed_sha256":
            continue  # the repo owns it after init or migrate
        data = contents(BASELINE_REPO, repo_rel(rel), sha)
        if data is None:
            raise OSError(f"{repo_rel(rel)}: 태그 {tag}에 없다")
        (kind, want), = managed[rel].items()
        if digest(data, kind) != want:
            raise OSError(f"{repo_rel(rel)}: 태그 {tag}의 기록과 다르다")
        files[rel] = data
    writes = {".baseline/baseline.py": source}
    for rel, data in files.items():
        (kind, _), = managed[rel].items()
        if kind == "sha256":
            writes[rel] = data
            continue
        if not (root / rel).exists() and not linked(root, rel):
            writes[rel] = data
            continue
        local = read_file(root, rel)
        if kind == "prefix_sha256":
            old_spec = recorded["managed"].get(rel)
            old_want = next(iter(old_spec.values()), None) if isinstance(old_spec, dict) else None
            # Both versions can match (a partial upgrade, core lines that grow or shrink): the longer
            # core lines win, so the shorter rest is the repo's.
            rests = [r for r in (after_prefix(local, old_want), after_prefix(local, managed[rel]["prefix_sha256"]))
                     if r is not None]
            rest = min(rests, key=len) if rests else None
            if rest is None:
                raise OSError(f"{rel}: 맨 앞 줄이 판 {recorded.get('version')}의 코어 줄과 다르다. check를 통과하게 고친 뒤 다시 upgrade한다")
            writes[rel] = data + rest
            continue
        if block(local) is None:
            raise OSError(f"{rel}: 관리 블록 표시가 하나씩 있어야 한다")
        writes[rel] = replace_block(local, block(data))
    settings = ".claude/settings.json"
    touch_settings = (root / settings).exists() or linked(root, settings)
    skill_names = sorted({rel[len(SKILLS):].split("/")[0]
                          for rel in list(managed) + list(recorded["managed"]) if rel.startswith(SKILLS)})
    targets = (list(writes) + [".baseline/baseline.json"] + ([settings] if touch_settings else [])
               + [SKILLS + name for name in skill_names])
    links = [rel for rel in targets if linked(root, rel)]
    if links:
        raise OSError("symlink는 따라가지 않는다: " + ", ".join(links))
    if touch_settings:
        writes[settings] = re.sub(rb'("--sha256",\s*")[0-9a-f]{64}"',
                                  b'\\g<1>' + sha256(source).encode() + b'"', read_file(root, settings))
    big = sorted(rel for rel, data in writes.items() if len(data) > MAX_READ)
    if big:  # check could not read them
        raise OSError(f"쓸 내용이 {MAX_READ}바이트를 넘는다: " + ", ".join(big))
    record = dump_json(dict(recorded, version=version, managed=managed))
    for rel, data in writes.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f"upgrade: {rel}")
    for name in skill_names:
        folder = root / SKILLS / name
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*"), reverse=True):
            rel = path.relative_to(root).as_posix()
            if path.is_symlink() or (path.is_file() and rel not in managed):
                path.unlink()
            elif path.is_dir() and not any(path.iterdir()):
                path.rmdir()
    # After every other write, so a failure does not record a version the tree does not match.
    path = root / ".baseline/baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(record)
    print("upgrade: .baseline/baseline.json")
    return 0

def cmd_upgrade(args):
    root = repo_root()
    try:
        return upgrade(root, args.tag)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"upgrade: {error}", file=sys.stderr)
        return 2


def upgrade_problem(paths, old, new):
    """None when every changed path holds the bytes recorded by the baseline tag that the PR's
    baseline.json names. old/new read a path at base/head."""
    try:
        before, after = json.loads(old(".baseline/baseline.json") or b""), json.loads(new(".baseline/baseline.json") or b"")
    except ValueError:
        return "baseline.json을 읽지 못했다"
    if not isinstance(before, dict) or not isinstance(after, dict) or not isinstance(after.get("version"), str):
        return "baseline.json이 객체가 아니거나 판이 없다"
    version = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", after["version"])
    current = re.match(r"(\d+)\.(\d+)\.(\d+)", str(before.get("version")))
    if not version:
        return f"판 {after['version']!r}이 X.Y.Z가 아니다"
    if current and (tuple(map(int, version.groups())) < tuple(map(int, current.groups()))
                    or before.get("version") == after["version"]):
        return "판을 올리지 않는다"
    tag = TAG.format(after["version"])
    try:  # a tag only (a branch can have the same name), and one that main already holds
        target = gh_api(f"repos/{BASELINE_REPO}/git/ref/tags/{tag}")["object"]
        if target["type"] == "tag":
            target = gh_api(f"repos/{BASELINE_REPO}/git/tags/{target['sha']}")["object"]
        if target["type"] != "commit":
            return f"태그 {tag}가 커밋을 가리키지 않는다"
        if gh_api(f"repos/{BASELINE_REPO}/compare/{target['sha']}...main")["status"] not in ("ahead", "identical"):
            return f"태그 {tag}가 {BASELINE_REPO} main에 없는 커밋이다"
    except (OSError, KeyError, TypeError) as error:
        return f"태그 {tag}를 읽지 못했다: {error}"
    source = contents(BASELINE_REPO, "baseline.py", target["sha"])
    managed = embedded_managed(source) if source is not None else None
    if managed is None:
        return f"{BASELINE_REPO}의 태그 {tag}에서 baseline.py의 관리 해시를 읽지 못했다"
    want = {".baseline/baseline.py": source,
            ".baseline/baseline.json": dump_json(dict(before, version=after["version"], managed=managed))}
    old_managed = before.get("managed") if isinstance(before.get("managed"), dict) else {}
    skill_names = {rel[len(SKILLS):].split("/")[0]
                   for rel in list(managed) + list(old_managed) if isinstance(rel, str) and rel.startswith(SKILLS)}
    for path in sorted(paths):
        data = new(path)
        if path in want:
            same = data == want[path]
        elif path == ".claude/settings.json" and data is not None and old(path) is not None:
            pin = sha256(source).encode()
            same = data == re.sub(rb'("--sha256",\s*")[0-9a-f]{64}"', b'\\g<1>' + pin + b'"', old(path))
        elif path in managed and data is not None and kind_of(path, managed) != "seed_sha256":
            (kind, hash_), = managed[path].items()
            if kind == "prefix_sha256":
                old_spec = old_managed.get(path)
                old_want = next(iter(old_spec.values()), None) if isinstance(old_spec, dict) else None
                rest = after_prefix(data, hash_)
                same = rest is not None and (rest == b"" if old(path) is None else rest == after_prefix(old(path), old_want))
            elif digest(data, kind) != hash_:
                same = False
            elif kind == "sha256":
                same = True
            elif old(path) is None:
                tagged = contents(BASELINE_REPO, repo_rel(path), target["sha"])
                same = tagged is not None and data == tagged
            else:
                same = outside(data) == outside(old(path))
        elif data is None and path.startswith(SKILLS):
            name = path[len(SKILLS):].split("/")[0]
            same = name in skill_names and path not in managed
        else:
            same = False
        if not same:
            return f"{path}: 태그 {tag}의 기록과 다르다"
    return None

def bump_problem(patch):
    """None when each changed line only swaps a version or a hash and no major version changes."""
    if not patch:
        return "diff가 없다(바이너리이거나 너무 크다)"
    removed, added = [], []

    def pair():
        if len(removed) != len(added):
            return "더하거나 지운 줄이 있다(새 의존성 등)"
        for old, new in zip(removed, added):
            old, new = HASH_RE.sub("#", old), HASH_RE.sub("#", new)
            before, after = VERSION_RE.findall(old), VERSION_RE.findall(new)
            if VERSION_RE.sub("V", old) != VERSION_RE.sub("V", new) or len(before) != len(after):
                return f"버전·해시 밖의 변경: {new.strip()}"
            if any(a.split(".")[0] != b.split(".")[0] for a, b in zip(before, after)):
                return f"major 업데이트: {new.strip()}"
        removed.clear()
        added.clear()
        return None

    for line in patch.splitlines() + [""]:
        if line.startswith("-") and not added:
            removed.append(line[1:])
            continue
        if line.startswith("+"):
            added.append(line[1:])
            continue
        problem = pair()
        if problem:
            return problem
        if line.startswith("-"):
            removed.append(line[1:])
    return None


def dependabot_problem(repo, pr, fork, files):
    """None when the PR author login and every push to the head branch are dependabot[bot] (git author
    names are free text, so they do not count) and the PR only bumps minor or patch versions."""
    if pr["user"]["login"] != BOT:
        return f"작성자가 {BOT}이 아니다"
    if fork:
        return "fork PR이다"
    # One page only: this endpoint pages by cursor and ignores `page`, so pages() would loop forever.
    pushes = gh_api(f"repos/{repo}/activity?ref={quote(pr['head']['ref'], safe='')}&per_page=100")
    if not isinstance(pushes, list) or len(pushes) >= 100:
        return "head 브랜치의 push 기록을 다 읽지 못했다(100개 이상)"
    if not any(p.get("after") == pr["head"]["sha"] for p in pushes) or any(
            (p.get("actor") or {}).get("login") != BOT for p in pushes):
        return f"head 브랜치에 {BOT}이 아닌 push가 있거나 head를 push한 기록이 없다"
    for f in files:
        name = f["filename"].rsplit("/", 1)[-1]
        if not is_manifest(name) or f.get("status") != "modified":
            return f"{f['filename']}: manifest·lockfile 수정이 아니다"
        problem = bump_problem(f.get("patch"))
        if problem:
            return f"{f['filename']}: {problem}"
    return None


def pr_target(pr, remote):
    match = re.fullmatch(r"https://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)/?", pr)
    if match:
        return match.group(1), match.group(2)
    if not pr.isdigit():
        raise ValueError("PR은 번호나 https://github.com/<owner>/<repo>/pull/<번호>다")
    url = subprocess.run(["git", "remote", "get-url", remote], capture_output=True, text=True).stdout.strip()
    match = re.search(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$", url)
    if not match:
        raise ValueError(f"remote {remote}가 GitHub 저장소가 아니다: {url!r}")
    return match.group(1), pr


def preflight(repo, number, remote):
    """The report, or None when the head or base moved during the run."""
    pr = gh_api(f"repos/{repo}/pulls/{number}")
    head, base = pr["head"]["sha"], pr["base"]["sha"]
    fork = (pr["head"].get("repo") or {}).get("full_name") != pr["base"]["repo"]["full_name"]
    files = pages(f"repos/{repo}/pulls/{number}/files")
    commits = pages(f"repos/{repo}/pulls/{number}/commits")
    if len(files) >= 3000 or len(commits) >= 250:
        raise OSError("REST가 보여 주는 한도(파일 3000개, 커밋 250개)에 닿아 다 볼 수 없다")
    paths = {p for f in files for p in (f["filename"], f.get("previous_filename")) if p}
    names = set(paths)
    for commit in commits:  # a .env added and renamed inside the PR shows only in its commit
        changed = pages(f"repos/{repo}/commits/{commit['sha']}", "files")
        if len(changed) >= 3000:
            raise OSError(f"커밋 {commit['sha']}의 파일이 REST 한도(3000개)에 닿아 다 볼 수 없다")
        names |= {p for f in changed for p in (f["filename"], f.get("previous_filename")) if p}
    hits, examples = env_file_names(names)
    # The contents API follows symlinks, so the bytes alone cannot show a link or a submodule.
    # Both sides count: a PR that turns a link into a file changes what the link used to reach.
    linked = set()
    for sha in (base, head):
        tree = gh_api(f"repos/{repo}/git/trees/{sha}?recursive=1")
        if tree.get("truncated"):
            raise OSError("트리가 커서 REST가 다 보여 주지 않는다")
        linked |= {e["path"] for e in tree["tree"] if e["mode"] in ("120000", "160000")}
    links = sorted({q for p in paths for q in ("/".join(p.split("/")[:i + 1]) for i in range(p.count("/") + 1))
                    if q in linked})
    report = {"pr": int(number), "fork": fork, "head": head, "base": base, "branch": pr["head"]["ref"],
              "author": pr["user"]["login"], "base_branch": pr["base"]["ref"],
              "env_file_hits": hits, "unreviewed_examples": examples, "grade": None, "review_tier": None, "reasons": [],
              "fetch_argv": None, "diff_argv": None}
    if not hits:
        # Grade inputs come from base: the PR cannot list itself out of the sensitive paths.
        cache = {}

        def read(ref):
            def get(rel):
                if (rel, ref) not in cache:
                    cache[rel, ref] = contents(repo, rel, ref)
                return cache[rel, ref]
            return get
        old, new = read(base), read(head)
        patterns = sensitive_patterns(old("REVIEW.md"))
        reasons = [f"민감한 파일: {p}" for p in sorted(paths) if is_sensitive(p, patterns)]
        reasons += [f"symlink·submodule: {p}" for p in links]
        reasons += [f"출력할 수 없는 문자가 있는 경로: {json.dumps(p)}" for p in sorted(paths) if not p.isprintable()]
        for rel, spec in MANAGED.items():
            (kind, want), = spec.items()
            if rel not in paths or kind == "seed_sha256":  # a seed file is the repo's own
                continue
            if kind == "prefix_sha256":
                hard = any(after_prefix(data, want) is None for data in (old(rel), new(rel)))
            else:
                hard = kind == "sha256" or old(rel) is None or new(rel) is None or block(old(rel)) != block(new(rel))
            if hard:
                reasons.append(f"관리 {'블록' if kind == 'block_sha256' else '파일'}: {rel}")
        # Seed files instruct the skills too, so a new standing line there is as hard as in AGENTS.md.
        for rel in ["AGENTS.md"] + [rel for rel in MANAGED if kind_of(rel) == "seed_sha256"]:
            if rel not in paths:
                continue
            before = set((old(rel) or b"").decode("utf-8", "replace").splitlines())
            if any(("enqueue" in line or "상시 지시" in line) and line not in before
                   for line in (new(rel) or b"").decode("utf-8", "replace").splitlines()):
                reasons.append(f"상시 지시 줄을 만들거나 바꿨다: {rel}")
        if "REVIEW.md" in paths and set(patterns) - set(sensitive_patterns(new("REVIEW.md"))):
            reasons.append("「민감한 파일」 경로를 지웠다: REVIEW.md")
        exceptions = []
        if reasons and ".baseline/baseline.json" in paths:
            exceptions.append(("upgrade", upgrade_problem(paths, old, new)))
        if reasons and pr["user"]["login"] == BOT:
            exceptions.append(("Dependabot", dependabot_problem(repo, pr, fork, files)))
        passed = [name for name, problem in exceptions if problem is None and not links]
        if passed:
            report["grade"], reasons = "쉬움", [f"{passed[0]} 예외"]
        else:
            report["grade"] = "어려움" if reasons else "문서" if all(map(is_doc, paths)) else "쉬움"
            reasons += [f"{name} 예외 아님: {problem}" for name, problem in exceptions]
        report["reasons"] = reasons
        report["review_tier"] = REVIEW_TIERS[report["grade"]]
        report["fetch_argv"] = ["git", "fetch", "--no-tags", remote, base,
                                f"+refs/pull/{number}/head:refs/review-preflight/{remote}/pr/{number}"]
        report["diff_argv"] = ["git", "diff", f"{base}...{head}", "--", ".", ":!.env*", ":!**/.env*"]
    now = gh_api(f"repos/{repo}/pulls/{number}")
    if now["head"]["sha"] != head or now["base"]["sha"] != base:
        return None
    return report


def cmd_review_preflight(args):
    try:
        report = preflight(*pr_target(args.pr, args.remote), args.remote)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(f"review-preflight: 실행 실패: {error}", file=sys.stderr)
        return 2
    if report is None:
        print("review-preflight: head나 base가 실행 중에 바뀌었다. 다시 실행한다.", file=sys.stderr)
        return 2
    code = 1 if report["env_file_hits"] else 0
    if args.json:
        print(json.dumps(report))  # ASCII only, so a non-UTF-8 stdout cannot fail after the checks
        return code
    print(f"PR: {report['pr']}  fork: {'예' if report['fork'] else '아니요'}  branch: {report['branch']}")
    print(f"head: {report['head']}")
    print(f"base: {report['base']}")
    show = lambda paths: ", ".join(p if p.isprintable() else json.dumps(p) for p in paths)  # noqa: E731
    print("미검토(.env.example): " + (show(report["unreviewed_examples"]) or "없음"))
    if code:
        print("리뷰 미완(비밀값 파일): " + show(report["env_file_hits"]))
        return code
    print(f"등급: {report['grade']}")
    tier = report["review_tier"]
    print("리뷰 층: " + (f"{tier['model']}·{tier['effort']}" if tier else "없음"))
    for reason in report["reasons"]:
        print(f"이유: {show([reason])}")
    print("fetch: " + shlex.join(report["fetch_argv"]))
    print("diff: " + shlex.join(report["diff_argv"]) + "  (저장소 루트에서)")
    return 0


def gh_graphql(query, **fields):
    """GitHub GraphQL. Only the merge queue and review threads need it (no REST endpoint); cloud proxies block it."""
    argv = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in fields.items():
        argv += ["-F" if isinstance(value, int) else "-f", f"{key}={value}"]
    result = subprocess.run(argv, capture_output=True)
    data = json.loads(result.stdout or b"{}") if not result.returncode else {}
    if result.returncode or data.get("errors") or "data" not in data:
        raise OSError(f"gh api graphql: {data.get('errors') or result.stderr.decode('utf-8', 'replace').strip()}")
    return data["data"]


def review_fields(body):
    """The `## Review` fields enqueue reads, each from exactly one `name: value` line.

    None: no line, or one line left blank as the PR template has it. "": two lines, so neither is read."""
    lines = section(body.encode("utf-8"), "Review")
    fields = {}
    for name in ("리뷰한 head", "등급", "남은 지적"):
        at = [i for i, line in enumerate(lines) if line.startswith(f"{name}:")]
        if len(at) != 1:
            fields[name] = None if not at else ""
            continue
        value = lines[at[0]][len(name) + 1:].strip().strip("`")
        if at[0] + 1 < len(lines) and lines[at[0] + 1].startswith(("- ", "* ")):  # `*강조*` is not a list
            fields[name] = value + " (목록이 이어진다)"  # 「남은 지적: 없음」 followed by a list is not 없음
        else:
            fields[name] = value or None
    return fields


def required_checks(repo, branch):
    """(context, app id or None) pairs that branch protection and rulesets require on the base branch."""
    need = set()
    protection = (gh_api(f"repos/{repo}/branches/{quote(branch, safe='')}").get("protection") or {})
    checks = protection.get("required_status_checks") or {}
    need |= {(c["context"], c.get("app_id")) for c in checks.get("checks") or []}
    need |= {(c, None) for c in checks.get("contexts") or [] if all(c != n for n, _ in need)}
    for rule in pages(f"repos/{repo}/rules/branches/{quote(branch, safe='')}"):
        if rule.get("type") == "required_status_checks":
            need |= {(c["context"], c.get("integration_id")) for c in rule["parameters"]["required_status_checks"]}
    return need


def ci_problems(repo, sha, need):
    if not need:
        return ["필수 CI가 정해져 있지 않다"]
    runs = pages(f"repos/{repo}/commits/{sha}/check-runs?filter=latest", "check_runs")
    statuses = {s["context"]: s["state"] for s in pages(f"repos/{repo}/commits/{sha}/status", "statuses")}
    problems = []
    for context, app in sorted(need, key=lambda n: (n[0], str(n[1]))):
        mine = [r for r in runs if r["name"] == context and (app in (None, -1) or (r.get("app") or {}).get("id") == app)]
        status = statuses.get(context) if app in (None, -1) else None
        if not mine and status is None:
            problems.append(f"필수 CI {context}: 결과가 없다")
            continue
        if mine:
            run = max(mine, key=lambda r: r["id"])
            if run["status"] != "completed" or run["conclusion"] not in PASSED:
                problems.append(f"필수 CI {context}: {run['conclusion'] or run['status']}")
        if status not in (None, "success"):  # a check run and a status of one name: both must pass
            problems.append(f"필수 CI {context}: {status}")
    return problems


def account_problems(repo, report, commits):
    """The author and every commit author must be able to push (Dependabot PRs: dependabot[bot] only)."""
    allowed = {}

    def can_push(login):
        if login not in allowed:
            allowed[login] = (login == BOT if report["author"] == BOT else
                              gh_api(f"repos/{repo}/collaborators/{quote(login, safe='')}/permission")
                              .get("permission") in ("admin", "write"))
        return allowed[login]
    problems = [] if can_push(report["author"]) else [f"작성자 {report['author']}에게 쓰기 권한이 없다"]
    for commit in commits:
        login = (commit.get("author") or {}).get("login")
        if not login:
            problems.append(f"커밋 {commit['sha'][:7]}의 작성자를 GitHub 계정으로 알 수 없다")
        elif not can_push(login):
            problems.append(f"커밋 {commit['sha'][:7]}의 작성자 {login}에게 쓰기 권한이 없다")
    return problems


def is_bot(user):
    """GitHub App accounts: type Bot, or a login ending in [bot] (people cannot use [ ] in a login)."""
    return (user or {}).get("type") == "Bot" or ((user or {}).get("login") or "").endswith("[bot]")


def changes_requested(reviews):
    """People whose last review state is CHANGES_REQUESTED. Comments do not change a state; bots are left out."""
    last = {}
    for review in sorted(reviews, key=lambda r: r.get("submitted_at") or ""):
        user = review.get("user") or {}
        if not is_bot(user) and review.get("submitted_at") and review.get("state") != "COMMENTED":
            last[user.get("login") or "ghost"] = review["state"]
    return sorted(login for login, state in last.items() if state == "CHANGES_REQUESTED")


def external_reviews(repo, number, reported, reviews, settled=frozenset()):
    """Reviews and comments written after the review report, or edited by a person after it: nobody judged them.

    An edit to a bot's comment does not count: CodeRabbit rewrites its summary comment after every body edit,
    so the report could never come last (#215). Its line findings arrive as new reviews and comments, but the
    summary's pre-merge checks are re-scored in place, and REST does not say who edited a comment.
    A bot's reply in a thread already resolved (settled: ids of the replies, never a thread's first comment) does
    not count either, nor a bot review holding only such replies: CodeRabbit answers the reviewer's judgment after
    the report, each answer its own review (#216). A thread's first comment always counts, so resolving a new
    thread does not hide its finding. shortcut: a new finding a bot posts as a reply inside a resolved thread goes
    unseen; reopen such threads if that happens."""
    line_comments = pages(f"repos/{repo}/pulls/{number}/comments")
    by_review = {}
    for c in line_comments:
        by_review.setdefault(c.get("pull_request_review_id"), []).append(c.get("id") in settled)
    items = [(r.get("submitted_at"), r) for r in reviews
             if not (is_bot(r.get("user")) and not (r.get("body") or "").strip()  # a review body is a finding
                     and by_review.get(r.get("id")) and all(by_review[r.get("id")]))]
    for path, found in (("pulls", line_comments), ("issues", pages(f"repos/{repo}/issues/{number}/comments"))):
        for c in found:
            if is_bot(c.get("user")) and path == "pulls" and c.get("id") in settled:
                continue
            # shortcut: a finding added only by editing a bot's old comment (by the bot, or by a person with
            # write access) goes unseen, e.g. a pre-merge check turning red; count those edits if that happens.
            items.append((c["created_at"] if is_bot(c.get("user")) else max(c["created_at"], c.get("updated_at") or ""), c))
    return sorted({(item.get("user") or {}).get("login") or "ghost" for at, item in items if at and at > reported})


def enqueue_problems(repo, number, sha, remote):
    """(PR node id, reasons not to queue). The checks POLICY §5 lists, all recomputed now."""
    report = preflight(repo, number, remote)
    if report is None:
        return None, ["head나 base가 실행 중에 바뀌었다"]
    if report["env_file_hits"]:
        return None, ["비밀값 파일 이름: " + ", ".join(json.dumps(p) for p in report["env_file_hits"])]
    owner, name = repo.split("/")
    pr = gh_graphql(PR_QUERY, owner=owner, name=name, number=int(number))["repository"]["pullRequest"]
    problems = [] if report["head"] == sha else [f"head가 {sha}가 아니라 {report['head']}다"]
    if report["fork"]:
        problems.append("fork PR이다")
    agents = (contents(repo, "AGENTS.md", report["base"]) or b"").decode("utf-8", "replace").splitlines()
    if not any(line.startswith(STANDING) and STANDING_COMMAND in line for line in agents):
        problems.append("base의 AGENTS.md에 상시 지시 줄이 없다")
    problems += account_problems(repo, report, pages(f"repos/{repo}/pulls/{number}/commits"))
    fields = review_fields(pr["body"] or "")
    if fields["등급"] is not None and fields["등급"] not in GRADES:
        problems.append(f"「등급」이 {'·'.join(GRADES)} 중 하나가 아니다")
    grade = max(report["grade"], fields["등급"] if fields["등급"] in GRADES else "문서", key=GRADES.index)
    if grade == "어려움":
        problems.append("어려움 등급이다(소유자가 GitHub 화면에서 넣는다)")
    if grade == "쉬움" and fields["등급"] is None:
        problems.append("리뷰 보고에 「등급」이 없다")
    if grade == "쉬움" and fields["리뷰한 head"] != sha:
        problems.append(f"리뷰 보고의 「리뷰한 head」가 {sha}가 아니다")
    if (grade == "쉬움" or fields["남은 지적"] is not None) and fields["남은 지적"] != "없음":
        problems.append("리뷰 보고의 「남은 지적」이 「없음」 한 줄이 아니다")
    threads = pr["reviewThreads"]
    open_threads = sum(1 for t in threads["nodes"] if not t["isResolved"]) + threads["totalCount"] - len(threads["nodes"])
    if open_threads:  # GitHub refuses with "All comments must be resolved"; say which thing is missing
        problems.append(f"해결하지 않은 리뷰 스레드 {open_threads}개")
    problems += ci_problems(repo, report["head"], required_checks(repo, report["base_branch"]))
    reviews = pages(f"repos/{repo}/pulls/{number}/reviews")
    blocked = changes_requested(reviews)
    if blocked:
        problems.append("변경 요청: " + ", ".join(blocked))
    if grade == "쉬움":  # docs PRs have no reviewer to judge bot comments: CI only (POLICY §3)
        # The report's time is the last body edit by a person: bots (CodeRabbit) also rewrite the body.
        edits = [e["editedAt"] for e in pr["userContentEdits"]["nodes"]
                 if (e.get("editor") or {}).get("__typename") == "User"]
        settled = {c["databaseId"] for t in threads["nodes"] if t["isResolved"] for c in t["comments"]["nodes"][1:]}
        late = external_reviews(repo, number, max(edits, default=pr["createdAt"]), reviews, settled)
        if late:
            problems.append("리뷰 보고 뒤의 판정하지 않은 외부 리뷰: " + ", ".join(late))
    return pr["id"], problems


def cmd_enqueue(args):
    if os.environ.get("CLAUDE_CODE_REMOTE") == "true":
        print("enqueue: 클라우드 세션에서는 넣지 않는다. 프록시가 GraphQL(큐 넣기)을 막는다. 로컬 세션에서 부른다.",
              file=sys.stderr)
        return 2
    if not SHA_RE.fullmatch(args.sha):
        print("enqueue: SHA는 40자 소문자 hex다", file=sys.stderr)
        return 2
    try:
        repo, number = pr_target(args.pr, args.remote)
        node, problems = enqueue_problems(repo, number, args.sha, args.remote)
        if problems:
            for problem in problems:
                print(f"enqueue: 넣지 않는다: {problem if problem.isprintable() else json.dumps(problem)}")
            return 1
        gh_graphql(ENQUEUE, id=node, sha=args.sha)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(f"enqueue: 실행 실패: {error}", file=sys.stderr)
        return 2
    print(f"enqueue: {repo}#{number}을 {args.sha}로 머지 큐에 넣었다")
    return 0


def report_problems(text, head):
    """Why a `## Review` section text is not one enqueue can read, checked with enqueue's own parser."""
    if any(line.startswith("## ") for line in text.splitlines()):
        return ["Review 칸 안에 `## ` 제목 줄이 있다"]
    lines = section(("## Review\n" + text).encode("utf-8"), "Review")
    fields = review_fields("## Review\n" + text)
    problems = [] if fields["리뷰한 head"] == head else [f"「리뷰한 head」가 지금 PR head {head}가 아니다"]
    if fields["등급"] not in GRADES:
        problems.append(f"「등급」이 {'·'.join(GRADES)} 중 하나 한 줄이 아니다")
    starts = [i for i, line in enumerate(lines) if line.startswith("남은 지적:")]
    at = starts[0] if len(starts) == 1 else len(lines)  # none or two lines: items stay empty and it is refused
    items = []
    for line in lines[at + 1:]:
        if not line.startswith(("- ", "* ")):
            break
        items.append(line[2:].strip())
    left = (fields["남은 지적"] or "").removesuffix(" (목록이 이어진다)")
    if not (left == "없음" and not items or left == "" and items and "없음" not in items
            or left and not left.startswith("없음") and not items):
        problems.append("「남은 지적」은 「남은 지적: 없음」 한 줄이거나 빈 값 뒤의 `- [Spec|Standards] …` 목록이다")
    return problems


def replace_review(body, text):
    """The body with its one `## Review` section (heading up to the next `## ` heading) replaced by text."""
    lines = body.split("\n")
    at = [i for i, line in enumerate(lines) if line.rstrip() == "## Review"]
    if len(at) != 1:
        raise ValueError(f"본문에 `## Review` 제목이 {len(at)}개다(1개여야 한다)")
    end = next((i for i in range(at[0] + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    old = [p.strip("\n") for p in "\n".join(lines[at[0] + 1:end]).split("\n\n") if p.strip()]
    # Paragraphs after the last one with a field stay: the tool's attribution line, a bot's markers (CodeRabbit).
    last = max((i for i, p in enumerate(old) if any(line.startswith(REPORT_FIELDS + ("- ", "* "))  # `*강조*` is not a list
                                                     for line in p.split("\n"))), default=-1)
    keep = old[last + 1:]
    tail = [""] + lines[end:] if end < len(lines) else []
    out = lines[:at[0]] + ["## Review", ""] + text.strip("\n").split("\n") + [x for k in keep for x in ("", k)] + tail
    return "\n".join(out) + ("" if tail else "\n")


def cmd_review_report(args):
    """Write the `## Review` section last: thread replies and resolutions first, so the report is the latest record."""
    try:
        with open(args.file, encoding="utf-8") as f:
            text = f.read()
        text = re.sub(r"\A\s*## Review[ \t]*\n", "", text)
        judged = []
        for item in args.thread:
            cid, _, reply = item.partition("=")
            if not cid.isdigit() or not reply.strip():
                raise ValueError(f"--thread는 <댓글 id>=<판정>이다: {item!r}")
            judged.append((int(cid), reply.strip()))
        repo, number = pr_target(args.pr, args.remote)
        head = gh_api(f"repos/{repo}/pulls/{number}")["head"]["sha"]
        problems = report_problems(text, head)
        if problems:
            for problem in problems:
                print(f"review-report: 쓰지 않는다: {problem}")
            return 1
        cloud = os.environ.get("CLAUDE_CODE_REMOTE") == "true"
        threads = {}
        if judged:  # REST first, so a wrong id stops it before any write, in the cloud too
            comments = {c["id"]: c for c in pages(f"repos/{repo}/pulls/{number}/comments")}
            missing = [str(cid) for cid, _ in judged if cid not in comments]
            if missing:
                print(f"review-report: 쓰지 않는다: 리뷰 스레드에 없는 댓글 id: {', '.join(missing)}")
                return 1
            # The replies endpoint takes the thread's first comment, not a reply in it.
            judged = [(comments[cid].get("in_reply_to_id") or cid, reply) for cid, reply in judged]
            roots = [cid for cid, _ in judged]
            if len(set(roots)) != len(roots):
                print("review-report: 쓰지 않는다: 같은 스레드를 --thread로 두 번 줬다")
                return 1
            # A cloud run answers without resolving; the local run that carries the report over resolves only.
            # Only a writer's reply counts: in a public repo anyone can post the same words first.
            wanted = set(judged)
            posted = set()
            for c in comments.values():
                key = (c.get("in_reply_to_id"), (c.get("body") or "").strip())
                login = (c.get("user") or {}).get("login")
                if key in wanted and login and not is_bot(c.get("user")) and gh_api(
                        f"repos/{repo}/collaborators/{quote(login, safe='')}/permission").get("permission") in (
                        "admin", "write"):
                    posted.add(key)
        if judged and not cloud:
            owner, name = repo.split("/")
            nodes = gh_graphql(PR_QUERY, owner=owner, name=name, number=int(number))["repository"]["pullRequest"][
                "reviewThreads"]["nodes"]
            threads = {c["databaseId"]: t for t in nodes for c in t["comments"]["nodes"]}
            missing = [str(cid) for cid, _ in judged if cid not in threads]
            if missing:
                print(f"review-report: 쓰지 않는다: 리뷰 스레드에 없는 댓글 id: {', '.join(missing)}")
                return 1
        answered = []
        try:
            for cid, reply in judged:
                if not cloud and threads[cid]["isResolved"]:  # a rerun after a partial failure answers once
                    print(f"review-report: 댓글 {cid}의 스레드는 이미 해결됐다. 건너뛴다")
                    continue
                if (cid, reply) in posted:
                    print(f"review-report: 댓글 {cid}의 스레드에는 같은 판정이 이미 있다. 답은 다시 달지 않는다")
                else:
                    github_write("POST", f"repos/{repo}/pulls/{number}/comments/{cid}/replies", {"body": reply})
                    answered.append(str(cid))
                if cloud:
                    print(f"review-report: 댓글 {cid}에 답했다. 스레드 해결은 로컬 세션이 한다(클라우드는 GraphQL이 막힌다)")
                else:
                    gh_graphql(RESOLVE, id=threads[cid]["id"])
                    print(f"review-report: 댓글 {cid}에 답하고 스레드를 해결했다")
        except (OSError, subprocess.SubprocessError) as error:
            raise OSError(f"{error} (이미 답한 댓글: {', '.join(answered) or '없음'}. 본문은 쓰지 않았다)") from error
        pr = gh_api(f"repos/{repo}/pulls/{number}")  # read again: bots rewrite the body while threads are answered
        if pr["head"]["sha"] != head:
            print(f"review-report: 쓰지 않는다: 실행 중에 head가 {pr['head']['sha']}로 바뀌었다")
            return 1
        new_body = replace_review(pr["body"] or "", text)
        if review_fields(new_body) != review_fields("## Review\n" + text):  # kept paragraphs must not add fields
            print("review-report: 쓰지 않는다: 본문의 남은 문단이 Review 칸 값을 바꾼다")
            return 1
        # shortcut: PR PATCH has no conditional write, so an edit between the read above and this write is lost.
        github_write("PATCH", f"repos/{repo}/pulls/{number}", {"body": new_body})
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"review-report: 실행 실패: {error}", file=sys.stderr)
        return 2
    print(f"review-report: {repo}#{number}의 Review 칸을 썼다(head {head})")
    return 0


def blob_sha(data):
    """The git blob id, so files can be compared with a REST tree without downloading them."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def tag_version(name):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", name or "")
    return tuple(map(int, match.groups())) if match else None


def lock_problems(lock):
    if not isinstance(lock, dict) or not isinstance(lock.get("sources"), dict) or not isinstance(lock.get("skills"), dict):
        return ["skills.lock.json에 sources·skills 객체가 없다"]
    problems = []
    for name, src in lock["sources"].items():
        if not (isinstance(src, dict) and re.fullmatch(r"[\w.-]+/[\w.-]+", str(src.get("repo")))
                and src.get("update") in ("tag", "commit") and isinstance(src.get("days"), int) and src["days"] >= 7
                and all(isinstance(src.get(k), str) for k in ("license", "plugin"))
                and (src["update"] == "tag" or isinstance(src.get("branch"), str))):
            problems.append(f"출처 {name}: repo, update(tag·commit), days(7 이상), license, plugin"
                            "(commit이면 branch)가 있어야 한다")
    for name, skill in lock["skills"].items():
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name) or not isinstance(skill, dict) \
                or skill.get("source") not in lock["sources"] or not isinstance(skill.get("path"), str) \
                or ".." in skill["path"].split("/") or not isinstance(skill.get("requires"), list):
            problems.append(f"{name}: 이름(소문자·숫자·-), source, path, requires가 맞지 않다")
            continue
        for need in skill["requires"]:  # one source moves as one pin, so its skills change together
            if (lock["skills"].get(need) or {}).get("source") != skill["source"]:
                problems.append(f"{name}: 의존 스킬 {need}가 lock에 없거나 출처가 다르다")
    return problems


def newest_pin(src, cutoff):
    """(tag or None, commit) of the newest version older than the cutoff that is newer than the pin, or None."""
    repo = src["repo"]

    def ahead(sha):  # never back, never sideways: a new tag can name an old commit
        return not src.get("commit") or gh_api(f"repos/{repo}/compare/{src['commit']}...{sha}")["status"] == "ahead"
    if src["update"] == "commit":
        found = gh_api(f"repos/{repo}/commits?sha={quote(src['branch'], safe='')}"
                       f"&until={cutoff:%Y-%m-%dT%H:%M:%SZ}&per_page=1")
        if not found:
            return None
        return (None, found[0]["sha"]) if ahead(found[0]["sha"]) else None
    current = tag_version(src.get("tag"))
    for tag in sorted({t["name"] for t in pages(f"repos/{repo}/tags") if tag_version(t["name"])},
                      key=tag_version, reverse=True):
        if current and tag_version(tag) <= current:
            return None
        target = gh_api(f"repos/{repo}/git/ref/tags/{quote(tag, safe='')}")["object"]
        if target["type"] != "tag":  # a lightweight tag has no date of its own: an old commit can get a new tag
            continue
        annotated = gh_api(f"repos/{repo}/git/tags/{target['sha']}")
        date, target = annotated["tagger"]["date"], annotated["object"]
        if target["type"] != "commit":
            raise ValueError(f"{repo} {tag}: 커밋을 가리키지 않는다")
        if datetime.fromisoformat(date.replace("Z", "+00:00")) <= cutoff and ahead(target["sha"]):
            return tag, target["sha"]
    return None


def snapshot(src, names, skills, commit):
    """{"<skill>/<rel>": (path in the source, tree entry)} at the commit, with the source LICENSE in each skill."""
    repo = src["repo"]
    tree = gh_api(f"repos/{repo}/git/trees/{commit}?recursive=1")
    if tree.get("truncated"):
        raise OSError(f"{repo}@{commit[:7]}: 트리가 커서 REST가 다 보여 주지 않는다")
    entries = {e["path"]: e for e in tree["tree"]}
    out = {}
    for name in names:
        prefix = skills[name]["path"].rstrip("/") + "/"
        found = {p[len(prefix):]: p for p, e in entries.items() if p.startswith(prefix) and e.get("type") != "tree"}
        if "SKILL.md" not in found or "LICENSE" in found:
            raise OSError(f"{repo}@{commit[:7]} {prefix}: SKILL.md가 없거나 LICENSE가 이미 있다")
        found["LICENSE"] = src["license"]
        for rel, path in found.items():
            entry = entries.get(path) or {}
            if (not rel.isprintable() or "\\" in rel or any(part in ("", ".", "..") or part.lower().startswith(".git") for part in rel.split("/"))
                    or entry.get("type") != "blob" or entry.get("mode") not in ("100644", "100755")
                    or not isinstance(entry.get("size"), int) or entry["size"] > MAX_READ):
                raise OSError(f"{repo}@{commit[:7]} {json.dumps(path)}: 없거나 일반 파일이 아니다(symlink·submodule, "
                              f"{MAX_READ}바이트 넘음, 쓸 수 없는 이름)")
            out[f"{name}/{rel}"] = (path, entry)
    return out


def local_shas(root, names):
    found = {}
    for name in names:
        for path in sorted((root / "skills" / name).rglob("*")):
            if path.is_file():
                found[path.relative_to(root / "skills").as_posix()] = blob_sha(path.read_bytes())
    return found


def write_managed(path, managed):
    """Replace the MANAGED literal of a baseline.py, one entry per line."""
    text = path.read_bytes().decode("utf-8")
    node = next(n for n in ast.parse(text).body
                if isinstance(n, ast.Assign) and [getattr(t, "id", None) for t in n.targets] == ["MANAGED"])
    lines = text.splitlines(keepends=True)
    lines[node.lineno - 1:node.end_lineno] = ["MANAGED = {\n"] + [
        f"    {json.dumps(rel)}: {{{json.dumps(kind)}: {json.dumps(want)}}},\n"
        for rel, spec in managed.items() for kind, want in spec.items()] + ["}\n"]
    path.write_bytes("".join(lines).encode("utf-8"))


def skills_bump(root, check, now):
    """Move each skill source of skills/skills.lock.json to its newest version older than `days`."""
    try:
        lock = json.loads(read_file(root, "skills/skills.lock.json"))
        problems = lock_problems(lock)
        if problems:
            raise ValueError("; ".join(problems))
        updates = []
        for name, src in lock["sources"].items():
            # No newer version: still check the copies against the pin (a skill added to the lock).
            pin = newest_pin(src, now - timedelta(days=src["days"])) or (
                (src.get("tag"), src["commit"]) if src.get("commit") else None)
            names = sorted(n for n, s in lock["skills"].items() if s["source"] == name)
            files = snapshot(src, names, lock["skills"], pin[1]) if pin else None
            if files and {rel: e["sha"] for rel, (_, e) in files.items()} != local_shas(root, names):
                updates.append((name, src, pin, names, files))
        if not updates:
            print("skills-bump: 새 판이 없다")
            return 0
        for name, src, (tag, commit), names, _ in updates:
            print(f"skills-bump: {name}: {src.get('tag') or (src.get('commit') or '없음')[:7]} → {tag or commit[:7]} "
                  f"({src['repo']}, 스킬: {', '.join(names)})")
        if check:
            return 1
        folders = [base + n for base in ("skills/", SKILLS) for update in updates for n in update[3]]
        targets = folders + ["skills/skills.lock.json", "baseline.py", ".baseline/baseline.py", ".baseline/baseline.json",
                             ".claude/settings.json"]
        links = [rel for rel in targets if linked(root, rel)]
        if links:  # rmtree(ignore_errors) would leave the link and write through it
            raise OSError(f"symlink가 있는 경로에 쓰지 않는다: {', '.join(links)}")
        # rmtree drops local edits without a trace, so a dirty folder (untracked and ignored files too) stops the bump.
        status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--ignored", "--", *folders],
                                cwd=root, capture_output=True)
        if status.returncode:
            raise OSError("git status 실패: " + status.stderr.decode(errors="replace").strip())
        if status.stdout.strip():
            raise OSError("커밋하지 않은 변경이 있어 쓰지 않는다: " + "; ".join(status.stdout.decode(errors="replace").splitlines()))
        # status does not show edits to assume-unchanged (lowercase tag) or skip-worktree (S) files.
        flags = subprocess.run(["git", "ls-files", "-v", "--", *folders], cwd=root, capture_output=True)
        hidden = [line for line in flags.stdout.decode(errors="replace").splitlines() if not line.startswith("H ")]
        if flags.returncode or hidden:
            raise OSError("git이 변경을 숨기는 파일이 있어 쓰지 않는다: " + "; ".join(hidden or [flags.stderr.decode(errors="replace").strip()]))
        writes = {}  # download and verify everything before the first write
        for name, src, (tag, commit), names, files in updates:
            for rel, (path, entry) in files.items():
                data = contents(src["repo"], path, commit)
                if data is None or blob_sha(data) != entry["sha"]:
                    raise OSError(f"{src['repo']}@{commit[:7]} {path}: 받은 바이트가 트리와 다르다")
                writes[rel] = data
            version = json.loads(contents(src["repo"], src["plugin"], commit) or b"null")
            version = version.get("version") if isinstance(version, dict) else None
            if not isinstance(version, str):
                raise ValueError(f"{src['repo']}@{commit[:7]} {src['plugin']}: version이 없다")
            src.update({"commit": commit, "version": version}, **({"tag": tag} if tag else {}))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration) as error:
        print(f"skills-bump: 실행 실패: {error}", file=sys.stderr)
        return 2
    changed = [n for update in updates for n in update[3]]
    for base in ("skills", SKILLS):
        for name in changed:
            shutil.rmtree(root / base / name, ignore_errors=True)
        for rel, data in writes.items():
            (root / base / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / base / rel).write_bytes(data)
    (root / "skills/skills.lock.json").write_bytes(dump_json(lock))
    managed = {rel: spec for rel, spec in embedded_managed((root / "baseline.py").read_bytes()).items()
               if not rel.startswith(SKILLS)}
    for name in sorted(lock["skills"]):
        for path in sorted((root / "skills" / name).rglob("*")):
            if path.is_file():
                managed[SKILLS + path.relative_to(root / "skills").as_posix()] = {"sha256": sha256(path.read_bytes())}
    write_managed(root / "baseline.py", managed)
    after = sha256((root / "baseline.py").read_bytes())
    settings = root / ".claude/settings.json"  # the enqueue hook pins baseline.py; core/ keeps its placeholder
    if settings.is_file():
        settings.write_bytes(re.sub(rb'("--sha256",\s*")[0-9a-f]{64}"', b'\\g<1>' + after.encode() + b'"', settings.read_bytes()))
    shutil.copyfile(root / "baseline.py", root / ".baseline/baseline.py")
    recorded = json.loads((root / ".baseline/baseline.json").read_bytes())
    (root / ".baseline/baseline.json").write_bytes(dump_json(dict(recorded, managed=managed)))
    print("skills-bump: skills/, .claude/skills/, skills.lock.json, baseline.py의 MANAGED, .baseline/을 바꿨다. "
          "PR을 연다(소유자가 diff를 읽고 병합한다)")
    return 0


def cmd_skills_bump(args):
    root = Path(__file__).resolve().parent
    if not (root / "skills/skills.lock.json").is_file():
        sys.exit("skills-bump: skills/skills.lock.json이 없다. repo-baseline 클론의 baseline.py로 돌린다")
    return skills_bump(root, args.check, datetime.now(timezone.utc))


DOCTOR_TOOLS = ("python", "git", "gh", "claude", "mise")
DOCTOR_PROJECT_SETTINGS = (".claude/settings.json", ".claude/settings.local.json")


def doctor_version(value):
    return value if isinstance(value, str) and VERSION_RE.fullmatch(value) else None


def skill_entry_name(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value) else None


def doctor_release(expected):
    if expected and expected.count(".") == 1:
        return "VERSION", f"기준 {expected}에 맞는 전체 릴리스 판으로 VERSION을 바꾼다. "
    return expected, ""


def powershell_literal(value):
    # PowerShell interprets typographic single quotes as quote characters too.
    escaped = re.sub("['‘’‚‛]", lambda match: match.group() * 2, str(value))
    return f"'{escaped}'"


def doctor_install_mise_separately(expected, os_name):
    release, guide = doctor_release(expected)
    repo, python, script = repo_root(), sys.executable, os.path.abspath(__file__)
    if os_name == "win32":
        # https://mise.jdx.dev/installing-mise.html#windows (2026-11-24)
        args = ", ".join(powershell_literal(arg) for arg in (release, repo, python, script))
        return (f"{guide}PowerShell의 별도 프로세스에서 설치하고 다시 검사한다\n"
                f"Start-Job -ArgumentList {args} -ScriptBlock {{\n"
                "  param($release, $repo, $python, $baseline)\n"
                "  $ErrorActionPreference = 'Stop'\n"
                '  $miseDir = Join-Path $env:TEMP "repo-baseline-mise-$([guid]::NewGuid())"\n'
                "  $null = New-Item -ItemType Directory -Path $miseDir\n"
                "  $env:MISE_VERSION = $release\n"
                "  $env:MISE_INSTALL_PATH = Join-Path $miseDir 'mise.exe'\n"
                "  $env:MISE_INSTALL_MODIFY_PATH = '0'\n"
                "  irm https://mise.run/powershell | iex\n"
                "  if (!(Test-Path -LiteralPath $env:MISE_INSTALL_PATH -PathType Leaf)) { throw 'mise install failed' }\n"
                '  $env:Path = "$miseDir;$env:Path"\n'
                "  Set-Location -LiteralPath $repo\n"
                "  $ErrorActionPreference = 'Continue'\n"
                "  & $python -I $baseline doctor 2>&1 | ForEach-Object { $_.ToString() }\n"
                "} | Receive-Job -Wait -AutoRemoveJob")
    # https://mise.jdx.dev/installing-mise.html#install-script-mise-run (2026-11-24)
    rerun = f'{shlex.quote(python)} -I {shlex.quote(script)} doctor'
    return (f'{guide}mise_dir=$(mktemp -d) && curl -fsSL https://mise.run | '
            f'MISE_VERSION=v{release} MISE_INSTALL_PATH="$mise_dir/mise" sh\n'
            f'doctor: 같은 셸에서 다시 검사한다: (cd {shlex.quote(str(repo))} && PATH="$mise_dir:$PATH" {rerun})')


def doctor_install(name, expected, os_name, present=False):
    if name == "claude":
        if present:
            return "claude update"
        # https://code.claude.com/docs/en/setup#install-a-specific-version (2026-11-24)
        release, guide = doctor_release(expected)
        if os_name == "win32":
            if release:
                return f"{guide}PowerShell에서 & ([scriptblock]::Create((irm https://claude.ai/install.ps1))) {release}"
            return "PowerShell에서 irm https://claude.ai/install.ps1 | iex"
        args = f" -s {release}" if release else ""
        return f"{guide}curl -fsSL https://claude.ai/install.sh | bash{args}"
    if name == "mise":
        if not present:
            if expected:
                return doctor_install_mise_separately(expected, os_name)
            if os_name == "win32":
                return "PowerShell에서 irm https://mise.run/powershell | iex"
            return "brew install mise" if os_name == "darwin" else "curl -fsSL https://mise.run | sh"
        # https://mise.jdx.dev/cli/self-update.html (2026-11-24)
        release, guide = doctor_release(expected)
        args = f" {release}" if release else ""
        return (f"{guide}직접 설치: mise self-update --no-plugins{args}. "
                "패키지 관리자로 설치했다면 같은 관리자로 기준 판을 설치한다")
    if expected and name in DOCTOR_TOOLS:
        return f"mise install {name}@{expected}"
    if expected:
        return f"AGENTS.md 길잡이의 설치법으로 {name} {expected}을 설치한다"
    if name == "python":
        return "mise install python"
    package = "gh" if name == "gh" else "git" if name == "git" else name
    return f"brew install {package}" if os_name == "darwin" else f"sudo apt install {package}"


def version_matches(got, expected):
    return got == expected or got.startswith(expected + ".")


def org_mentioned(text, org):
    """A prose autoMode entry names the org when `github.com/<org>` has a boundary on both sides.

    `github.com/acme-other` does not name `acme`, and neither does `notgithub.com/acme` or a path on another host.
    Official entries are sentences, not only exact URLs (code.claude.com auto-mode-config, 2026-11-23).
    """
    needle = f"github.com/{org}"
    start = 0
    while True:
        index = text.find(needle, start)
        if index < 0:
            return False
        if index > 0:
            prev = text[index - 1]
            scheme = index >= 3 and text[index - 3:index] == "://"
            path_slash = prev == "/" and not scheme
            if prev.isalnum() or prev in "-." or path_slash:
                start = index + 1
                continue
        after = index + len(needle)
        if after >= len(text) or not (text[after].isalnum() or text[after] == "-"):
            return True
        start = after


def org_allowed(org, environment):
    needle = f"github.com/{org}"
    for item in environment:
        if not isinstance(item, str):
            continue
        if item in (org, needle) or item.startswith(needle + "/") or org_mentioned(item, org):
            return True
    return False


def doctor_problems(facts):
    """Failures and the command that fixes each one. facts is the simulated or gathered machine."""
    if not isinstance(facts, dict):
        return ["doctor: 사실이 객체가 아니다"]
    problems = []
    versions = facts.get("versions") if isinstance(facts.get("versions"), dict) else {}
    want = facts.get("want") if isinstance(facts.get("want"), dict) else {}
    os_name = facts.get("os") if isinstance(facts.get("os"), str) else ""
    if facts.get("settings_unreadable"):
        problems.append("doctor: ~/.claude/settings.json을 읽지 못했다\ndoctor: 고치기: JSON 객체로 고친다")
    project_errors = facts.get("project_settings_unreadable")
    if isinstance(project_errors, list):
        for rel in DOCTOR_PROJECT_SETTINGS:
            if rel in project_errors:
                problems.append(f"doctor: {rel}을 읽지 못했다\n"
                                "doctor: 고치기: 읽을 수 있는 일반 파일의 JSON 객체로 고친다")
    names = list(DOCTOR_TOOLS)
    for name in sorted(want):
        if skill_entry_name(name) and name not in names:
            names.append(name)
    for name in names:
        got = versions.get(name)
        raw_expected = want.get(name)
        expected = doctor_version(raw_expected)
        if isinstance(raw_expected, str) and expected is None:
            problems.append(f"doctor: {name} 기준 판을 읽을 수 없다")
        if not isinstance(got, str) or not got:
            problems.append(f"doctor: {name}이 없다\ndoctor: 고치는 명령: {doctor_install(name, expected, os_name)}")
        elif expected and not version_matches(got, expected):
            problem = f"doctor: {name} 판이 다르다. 지금 {got}, 기준 {expected}"
            if name == "mise" and (not doctor_version(got) or version_at_least(got, expected)):
                # A repository pin cannot authorize replacing a newer mise binary.
                command = doctor_install_mise_separately(expected, os_name)
            else:
                command = doctor_install(name, expected, os_name, present=True)
            problems.append(f"{problem}\ndoctor: 고치는 명령: {command}")
    if facts.get("wsl"):
        if facts.get("wsl_version") != 2:
            problems.append("doctor: WSL1이다\n"
                            "doctor: 고치는 명령: wsl.exe --set-version <배포판> 2\n"
                            "doctor: PowerShell에서 wsl.exe --list --verbose 로 배포판 이름을 본다")
        repo = facts.get("repo") if isinstance(facts.get("repo"), str) else ""
        if repo.startswith("/mnt/"):
            problems.append("doctor: 저장소가 /mnt/ 아래다\ndoctor: 고치는 명령: 저장소를 ~ 아래에 클론한다")
        git_path = facts.get("git_path") if isinstance(facts.get("git_path"), str) else ""
        git_version = facts.get("git_version") if isinstance(facts.get("git_version"), str) else ""
        if (git_path.endswith(".exe") or "/mnt/" in git_path.replace("\\", "/")
                or ".windows." in git_version.lower()):
            problems.append("doctor: Windows git이다\ndoctor: 고치는 명령: sudo apt install git")
    repo_skills = set(facts.get("skills_repo") or [])
    for item in facts.get("skills_user") or []:
        if isinstance(item, str):
            item = {"entry": item, "names": [item]}
        if not isinstance(item, dict):
            continue
        names = {skill_entry_name(name) for name in item.get("names") or []}
        names.discard(None)
        repo_names = {skill_entry_name(name) for name in repo_skills}
        repo_names.discard(None)
        entry = skill_entry_name(item.get("entry"))
        hit = sorted(names & repo_names)
        if not hit:
            continue
        guide = "doctor: 다른 저장소에서도 쓰려면 플러그인으로 설치한다. 플러그인 스킬은 플러그인:스킬로 이름이 나뉜다"
        if not entry:
            problems.append(f"doctor: 개인 스킬 {hit[0]}이 저장소 사본과 같은 이름이다. 개인 스킬이 프로젝트 스킬보다 먼저 돈다\n"
                            "doctor: 고치는 명령을 만들지 못했다\n" + guide)
            continue
        problems.append(
            f"doctor: 개인 스킬 {hit[0]}이 저장소 사본과 같은 이름이다. 개인 스킬이 프로젝트 스킬보다 먼저 돈다\n"
            f"doctor: 고치는 명령: rm -rf ~/.claude/skills/{shlex.quote(entry)}\n" + guide)
    org = facts.get("org") if isinstance(facts.get("org"), str) else None
    environment = facts.get("environment") if isinstance(facts.get("environment"), list) else []
    if org and not facts.get("settings_unreadable") and not org_allowed(org, environment):
        snippet = json.dumps({"autoMode": {"environment": [f"github.com/{org}"]}}, ensure_ascii=False, separators=(", ", ": "))
        problems.append(f"doctor: autoMode.environment에 조직 {org}이 없다. 사용자 설정에만 넣는다. 자동으로 쓰지 않는다\n"
                        f"doctor: 고치는 명령: {snippet}")
    if facts.get("mise_unreadable"):
        problems.append("doctor: .mise.toml을 읽지 못했다")
    else:
        mise_toml = facts.get("mise_toml") if isinstance(facts.get("mise_toml"), str) else None
        if mise_toml and not facts.get("mise_trusted"):
            # mise shortens paths under home to ~/...; a quoted ~ is not expanded by the shell.
            trust_path = os.path.expanduser(mise_toml)
            problems.append(f"doctor: mise 설정이 신뢰되지 않았다: {mise_toml}\ndoctor: 고치는 명령: mise trust {shlex.quote(trust_path)}")
        if facts.get("mise_failed"):
            problems.append(f"doctor: mise config ls가 실패했다: {facts['mise_failed']}\n"
                            f"doctor: 저장소에서 mise config ls를 돌려 오류를 본다")
    if facts.get("sandbox") and (os_name == "linux" or facts.get("wsl_version") == 2):
        if not facts.get("have_bubblewrap"):
            problems.append("doctor: 샌드박스에 bubblewrap이 없다\ndoctor: 고치는 명령: sudo apt install bubblewrap")
        if not facts.get("have_socat"):
            problems.append("doctor: 샌드박스에 socat이 없다\ndoctor: 고치는 명령: sudo apt install socat")
    return problems


def version_binary(name):
    """A single tool name to ask `--version`, or None. Paths are not names."""
    if not skill_entry_name(name):
        return None
    return "python3" if name == "python" else name


def tool_version(argv):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    line = ((result.stdout or result.stderr).strip().splitlines() or [""])[0]
    match = re.search(r"(\d+\.\d+(?:\.\d+)?)", line)
    return match.group(1) if match else None


def skill_entries(folder):
    if not folder.is_dir():
        return []
    entries = []
    for path in sorted(folder.iterdir(), key=lambda item: item.name):
        if path.name.startswith(".") or not (path.is_symlink() or path.is_dir()):
            continue
        names = {path.name}
        if path.is_symlink():
            try:
                names.add(path.resolve().name)
            except (OSError, RuntimeError):
                pass
        entries.append({"entry": path.name, "names": sorted(names)})
    return entries


def repo_skill_names(root):
    """Managed skill-copy folder names in this repo. A project skill is not a copy."""
    managed = {rel[len(SKILLS):].split("/", 1)[0] for rel in MANAGED if rel.startswith(SKILLS)}
    return sorted(item["entry"] for item in skill_entries(root / ".claude/skills") if item["entry"] in managed)


def github_org(url):
    match = re.search(r"github\.com[:/]([^/]+)/", url or "")
    return match.group(1) if match else None


def parse_mise_pins(text):
    """Top-level min_version and [tools] plain version strings."""
    min_version, tools, section = None, {}, ""
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        if "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if (len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'"):
            parsed = value[1:-1]
        elif value.startswith("["):
            parsed = re.findall(r"""["']([^"']+)["']""", value)
        else:
            parsed = None
        if key == "min_version" and isinstance(parsed, str):
            min_version = parsed
        elif section == "tools" and parsed and key != "min_version":
            tools[key] = parsed if isinstance(parsed, list) else [parsed]
    return min_version, tools


def version_at_least(installed, minimum):
    def parts(text):
        return tuple(int(part) for part in text.split("."))
    try:
        got, need = parts(installed), parts(minimum)
    except (TypeError, ValueError):
        return False
    width = max(len(got), len(need))
    return got + (0,) * (width - len(got)) >= need + (0,) * (width - len(need))


def pins_from(doctor_versions, mise_text, installed_mise):
    """Version pins doctor compares. .mise.toml [tools] wins. min_version is a floor for mise."""
    want = {name: value for name, value in (doctor_versions or {}).items()
            if skill_entry_name(name) and isinstance(value, str) and value}
    min_version, tools = parse_mise_pins(mise_text)
    for name, requested in tools.items():
        concrete = next((item for item in requested if doctor_version(item)), None)
        if skill_entry_name(name) and concrete:
            want[name] = concrete
    if doctor_version(min_version):
        pinned_mise = want.get("mise")
        version = pinned_mise if pinned_mise is not None else installed_mise
        if (pinned_mise is None or doctor_version(pinned_mise)) and (
                not version or not version_at_least(version, min_version)):
            want["mise"] = min_version
    return want


UNTRUSTED = re.compile(r"Config files in (.+?) are not trusted")


def untrusted_config(output):
    """The config file mise names as untrusted in its own error, or None."""
    found = UNTRUSTED.search(output or "")
    return found.group(1) if found else None


def repo_bytes(root, rel):
    """(bytes or None, refused). A missing file is (None, False).

    Same rule as read_file: no symlink on the way, at most MAX_READ bytes.
    """
    root = Path(root)
    try:
        if linked(root, rel):
            return None, True
        (root / rel).stat()
    except FileNotFoundError:
        return None, False
    except OSError:
        return None, True
    try:
        return read_file(root, rel), False
    except OSError:
        return None, True


def read_json_object(path):
    """(dict or None, unreadable). A missing file is (None, False). At most MAX_READ bytes."""
    try:
        if path.is_symlink() and not path.is_file():
            return None, True
        if not path.is_file():
            return None, False
        with path.open("rb") as handle:
            raw = handle.read(MAX_READ + 1)
    except OSError:
        return None, True
    if len(raw) > MAX_READ:
        return None, True
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:
        return None, True
    return (data, False) if isinstance(data, dict) else (None, True)


def sandbox_enabled(data):
    sandbox = data.get("sandbox") if isinstance(data, dict) else None
    return isinstance(sandbox, dict) and sandbox.get("enabled") is True


def tool_text(argv):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (result.stdout or "") + "\n" + (result.stderr or "")


def kernel_text():
    chunks = []
    for rel in ("/proc/sys/kernel/osrelease", "/proc/version"):
        path = Path(rel)
        if not path.is_file():
            continue
        try:
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(chunks).lower()


def gather_doctor(root=None):
    root = Path(root) if root is not None else repo_root()
    git_text = tool_text(["git", "--version"])
    versions = {
        "python": tool_version(["python3", "--version"]) or tool_version([sys.executable, "--version"]),
        "git": tool_version(["git", "--version"]),
        "gh": tool_version(["gh", "--version"]),
        "claude": tool_version(["claude", "--version"]),
        "mise": tool_version(["mise", "--version"]),
    }
    commands, _ = load_commands(root)
    pinned = commands.get("doctor_versions") if isinstance(commands, dict) else None
    if not isinstance(pinned, dict):
        pinned = {}
    mise_data, mise_unreadable = repo_bytes(root, ".mise.toml")
    mise_body = ""
    if mise_data is not None:
        try:
            mise_body = mise_data.decode("utf-8")
        except ValueError:
            mise_unreadable = True
            mise_data = None
    want = pins_from(pinned, "" if mise_unreadable else mise_body, versions.get("mise"))
    for name in want:
        if name in versions:
            continue
        binary = version_binary(name)
        if binary:
            versions[name] = tool_version([binary, "--version"])
    release = kernel_text()
    wsl = "microsoft" in release or "wsl" in release
    if not wsl:
        wsl_version = None
    elif "wsl2" in release or "microsoft-standard" in release:
        wsl_version = 2
    else:
        wsl_version = 1
    user_data, settings_unreadable = read_json_object(Path.home() / ".claude/settings.json")
    environment = []
    if isinstance(user_data, dict):
        auto = user_data.get("autoMode")
        if isinstance(auto, dict) and isinstance(auto.get("environment"), list):
            environment = auto["environment"]
    sandbox = sandbox_enabled(user_data)
    project_settings_unreadable = []
    for rel in DOCTOR_PROJECT_SETTINGS:
        data, refused = repo_bytes(root, rel)
        if refused:
            project_settings_unreadable.append(rel)
            continue
        if data is None:
            continue
        try:
            parsed = json.loads(data.decode("utf-8"))
        except ValueError:
            project_settings_unreadable.append(rel)
            continue
        if not isinstance(parsed, dict):
            project_settings_unreadable.append(rel)
            continue
        sandbox = sandbox or sandbox_enabled(parsed)
    remote = ""
    try:
        result = subprocess.run(["git", "remote", "get-url", "origin"], cwd=root, capture_output=True, text=True, timeout=15)
        remote = result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        remote = ""
    untrusted = mise_failed = None
    if shutil.which("mise"):
        # mise itself decides which config needs trust; it reads mise.local.toml and the rest too.
        try:
            shown = subprocess.run(["mise", "config", "ls"], cwd=root, stdin=subprocess.DEVNULL,  # no trust prompt
                                   capture_output=True, text=True, timeout=15)
            untrusted = untrusted_config((shown.stdout or "") + "\n" + (shown.stderr or ""))
            if untrusted is None and shown.returncode:  # a broken config is not a passing one
                lines = [line for line in (shown.stderr or "").splitlines() if line.strip()]
                mise_failed = lines[0] if lines else f"종료 코드 {shown.returncode}"
        except subprocess.TimeoutExpired:
            mise_failed = "15초 안에 끝나지 않았다"
        except OSError as error:
            mise_failed = str(error)
    return {
        "versions": versions, "want": want, "os": "linux" if sys.platform.startswith("linux") else sys.platform,
        "wsl": wsl, "wsl_version": wsl_version, "repo": root.as_posix(), "git_path": shutil.which("git") or "",
        "git_version": git_text, "skills_repo": repo_skill_names(root),
        "skills_user": skill_entries(Path.home() / ".claude/skills"),
        "org": github_org(remote), "environment": environment, "settings_unreadable": settings_unreadable,
        "project_settings_unreadable": project_settings_unreadable,
        "mise_toml": untrusted, "mise_trusted": untrusted is None, "mise_unreadable": mise_unreadable,
        "mise_failed": mise_failed,
        "sandbox": sandbox, "have_bubblewrap": shutil.which("bwrap") is not None or shutil.which("bubblewrap") is not None,
        "have_socat": shutil.which("socat") is not None,
    }


def cmd_doctor(args):
    if sys.stdin.isatty():
        raw = ""
    else:
        raw = sys.stdin.read(MAX_READ + 1)
        if len(raw) > MAX_READ:
            print("doctor: 사실을 읽지 못했다: 너무 크다", file=sys.stderr)
            return 2
    try:
        facts = json.loads(raw) if raw.strip() else gather_doctor()
    except ValueError as error:
        print(f"doctor: 사실을 읽지 못했다: {error}", file=sys.stderr)
        return 2
    problems = doctor_problems(facts)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print("doctor: 통과")
    return 0


# github plan|apply: repository settings and status labels (owner only)
GITHUB_PROFILE = ".github/repository-settings.json"
# Common values. A project file holds only its own values (identity, required checks, allowed actions,
# exceptions) and wins: objects merge by key, lists are replaced whole.
GITHUB_SETTINGS = json.loads(r"""
{"schema_version": 1, "repository": "REPLACE-OWNER/NAME", "repository_id": 0, "default_branch": "main",
 "expected": {
  "repository": {"default_branch": "main", "visibility": "public", "allow_merge_commit": false,
   "allow_rebase_merge": false, "allow_squash_merge": true, "allow_auto_merge": false,
   "delete_branch_on_merge": true, "allow_update_branch": true, "squash_merge_commit_title": "PR_TITLE",
   "squash_merge_commit_message": "PR_BODY",
   "security_and_analysis": {"dependabot_security_updates": {"status": "enabled"},
    "secret_scanning": {"status": "enabled"}, "secret_scanning_push_protection": {"status": "enabled"}}},
  "protection": {
   "required_status_checks": {"strict": false,
    "checks": [{"context": "REPLACE: ci, after the ci job succeeded on a real PR", "app_id": 15368}]},
   "required_pull_request_reviews": {"required_approving_review_count": 0, "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false, "require_last_push_approval": false},
   "enforce_admins": {"enabled": true}, "required_linear_history": {"enabled": true},
   "required_conversation_resolution": {"enabled": true}, "allow_force_pushes": {"enabled": false},
   "allow_deletions": {"enabled": false}, "lock_branch": {"enabled": false}},
  "rulesets": [{"name": "merge-queue", "target": "branch", "enforcement": "active", "bypass_actors": [],
   "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
   "rules": [{"type": "merge_queue", "parameters": {"merge_method": "SQUASH", "grouping_strategy": "ALLGREEN",
    "max_entries_to_build": 5, "max_entries_to_merge": 5, "min_entries_to_merge": 1,
    "min_entries_to_merge_wait_minutes": 0, "check_response_timeout_minutes": 60}}]}],
  "actions": {"enabled": true, "allowed_actions": "selected", "sha_pinning_required": true},
  "allowed_actions": {"github_owned_allowed": true, "verified_allowed": false,
   "patterns_allowed": ["REPLACE: each non-GitHub action the workflows use, as owner/repo@*, or leave the list empty"]},
  "workflow_token": {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": false},
  "fork_policy": {"approval_policy": "all_external_contributors"},
  "immutable_releases": {"enabled": true}, "private_vulnerability_reporting": {"enabled": true},
  "dependabot_alerts": {"enabled": true}, "codeql": {"state": "configured"}}}
""")
# The five status labels Matt's skills use (docs/agents/triage-labels.md). Created or fixed, never deleted.
LABELS = (
    {"name": "needs-triage", "color": "ededed", "description": "아직 분류하지 않았다"},
    {"name": "needs-info", "color": "d4c5f9", "description": "답이나 자료를 기다린다"},
    {"name": "ready-for-agent", "color": "0e8a16", "description": "범위와 완료 기준이 정해져 에이전트가 시작할 수 있다"},
    {"name": "ready-for-human", "color": "fbca04", "description": "사람이 해야 한다"},
    {"name": "wontfix", "color": "ffffff", "description": "하지 않는다"},
    # The wayfinder skill files maps and tickets with these; `gh issue create --label` fails on a missing one.
    {"name": "wayfinder:map", "color": "5319e7", "description": "wayfinder 지도(결정과 남은 안개)"},
    {"name": "wayfinder:research", "color": "c5def5", "description": "wayfinder 티켓: 조사"},
    {"name": "wayfinder:prototype", "color": "c5def5", "description": "wayfinder 티켓: 버리는 시제품"},
    {"name": "wayfinder:grilling", "color": "c5def5", "description": "wayfinder 티켓: 질문으로 결정"},
    {"name": "wayfinder:task", "color": "c5def5", "description": "wayfinder 티켓: 작은 일"},
)
# Write order matters: security updates need alerts on; selected actions need allowed_actions=selected.
SETTINGS_ORDER = ("dependabot_alerts", "repository", "protection", "rulesets", "actions", "allowed_actions",
                  "workflow_token", "fork_policy", "immutable_releases", "private_vulnerability_reporting", "codeql")
SETTINGS_MANUAL = ("codeql_workflow",)
MERGE_FIELDS = ("allow_merge_commit", "allow_rebase_merge", "allow_squash_merge", "allow_auto_merge",
                "delete_branch_on_merge", "allow_update_branch", "squash_merge_commit_title", "squash_merge_commit_message")
REVIEW_FIELDS = ("required_approving_review_count", "dismiss_stale_reviews",
                 "require_code_owner_reviews", "require_last_push_approval")
PROTECTION_FLAGS = ("required_linear_history", "allow_force_pushes", "allow_deletions",
                    "required_conversation_resolution", "lock_branch")
# A protection PUT resets these, and the baseline does not record them, so they must be off.
UNMANAGED_PROTECTION = ("required_signatures", "block_creations", "allow_fork_syncing")
CODEQL_WAIT = 120  # seconds; default setup turns on in the background
# Required controls cannot disappear when someone edits the baseline.
REQUIRED_FIELDS = {
    "repository": "default_branch visibility allow_merge_commit allow_rebase_merge allow_squash_merge allow_auto_merge delete_branch_on_merge allow_update_branch squash_merge_commit_title squash_merge_commit_message security_and_analysis.dependabot_security_updates.status security_and_analysis.secret_scanning.status security_and_analysis.secret_scanning_push_protection.status",
    "protection": "required_status_checks.strict required_status_checks.checks required_pull_request_reviews.required_approving_review_count required_pull_request_reviews.dismiss_stale_reviews required_pull_request_reviews.require_code_owner_reviews required_pull_request_reviews.require_last_push_approval enforce_admins.enabled required_linear_history.enabled required_conversation_resolution.enabled allow_force_pushes.enabled allow_deletions.enabled lock_branch.enabled",
    "rulesets": "",
    "actions": "enabled allowed_actions sha_pinning_required",
    "allowed_actions": "github_owned_allowed verified_allowed patterns_allowed",
    "workflow_token": "default_workflow_permissions can_approve_pull_request_reviews",
    "fork_policy": "approval_policy",
    "immutable_releases": "enabled",
    "private_vulnerability_reporting": "enabled",
    "dependabot_alerts": "enabled",
    "codeql": "state",
    "codeql_workflow": "path state",
}
ENDPOINTS = {
    "dependabot_alerts": "vulnerability-alerts", "protection": "branches/{branch}/protection", "rulesets": "rulesets",
    "actions": "actions/permissions", "allowed_actions": "actions/permissions/selected-actions",
    "workflow_token": "actions/permissions/workflow", "fork_policy": "actions/permissions/fork-pr-contributor-approval",
    "immutable_releases": "immutable-releases", "private_vulnerability_reporting": "private-vulnerability-reporting",
    "codeql": "code-scanning/default-setup", "codeql_workflow": "actions/workflows/{workflow}",
}
# A ruleset as the baseline records it: the rule itself, not ids or timestamps.
RULESET_FIELDS = ("name", "target", "enforcement", "conditions", "rules", "bypass_actors")
ADVANCED_CODEQL = {"codeql_workflow"}  # only advanced setup has a workflow file
STRING_FIELDS = {"default_branch", "visibility", "squash_merge_commit_title", "squash_merge_commit_message",
                 "status", "allowed_actions", "default_workflow_permissions", "approval_policy", "state", "path"}
# Only feature availability can narrow coverage; repository identity and merge policy stay required.
EXCEPTION_PATHS = (set(REQUIRED_FIELDS) - {"repository"} - ADVANCED_CODEQL) | {
    "repository." + field for field in REQUIRED_FIELDS["repository"].split()
    if field.startswith("security_and_analysis.")} | {"actions.sha_pinning_required"}


WORKFLOW_PATH = re.compile(r"\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml")


def endpoint(name, branch, workflow="codeql.yml"):
    return ENDPOINTS[name].format(branch=branch, workflow=workflow)


def workflow_file(profile):
    """The advanced CodeQL workflow file the profile names; GitHub reads a workflow by its file name."""
    return Path(profile["expected"].get("codeql_workflow", {}).get("path", "codeql.yml")).name


def skipped(profile, name):
    """GitHub has a selected-actions list only under the "selected" policy, so another policy ignores it."""
    return name == "allowed_actions" and profile["expected"].get("actions", {}).get("allowed_actions", "selected") != "selected"


def placeholders(value, path=""):
    if isinstance(value, dict):
        return [found for key, item in value.items() for found in placeholders(item, f"{path}.{key}" if path else key)]
    if isinstance(value, list):
        return [found for item in value for found in placeholders(item, path)]
    return [path] if isinstance(value, str) and value.startswith("REPLACE") else []


def overlay(base, project):
    """Objects merge key by key and the project value wins; lists and other values are replaced whole."""
    if not isinstance(base, dict) or not isinstance(project, dict):
        return copy.deepcopy(project)
    result = copy.deepcopy(base)
    for key, value in project.items():
        result[key] = overlay(base[key], value) if key in base else copy.deepcopy(value)
    return result


def merged(project, template=None):
    """The project's settings on top of the common values. A full copy merges to itself. A common value
    under a declared exception is dropped first. Unfilled values ("REPLACE...") stop the run here."""
    if not isinstance(project, dict):
        raise ValueError("설정은 객체여야 한다")
    template = copy.deepcopy(GITHUB_SETTINGS if template is None else template)
    exceptions = project.get("exceptions", {})
    expected = template.get("expected", {})
    for path in exceptions if isinstance(exceptions, dict) else ():
        parts = path.split(".")
        chain = [expected]
        for part in parts[:-1]:
            chain.append(chain[-1].get(part) if isinstance(chain[-1], dict) else None)
        if isinstance(chain[-1], dict):
            chain[-1].pop(parts[-1], None)
        # An object left empty goes too: GitHub omits an unavailable feature rather than answering {}.
        for depth in range(len(parts) - 1, 0, -1):
            parent, child = chain[depth - 1], chain[depth]
            if isinstance(child, dict) and not child and isinstance(parent, dict):
                parent.pop(parts[depth - 1], None)
    profile = overlay(template, project)
    unfilled = placeholders(profile)
    if unfilled:
        raise ValueError("공통값의 빈칸을 먼저 채운다: " + ", ".join(unfilled))
    return profile


def differences(expected, actual, path=""):
    """Compare required fields; omitted required fields are drift, not false."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [path or "<root>"]
        result = []
        for key, value in expected.items():
            name = f"{path}.{key}" if path else key
            result.extend([name] if key not in actual else differences(value, actual[key], name))
        return result
    if type(expected) is not type(actual):
        return [path]
    if isinstance(expected, list):
        # API ordering is irrelevant; duplicates and extra entries still differ.
        expected = sorted(json.dumps(item, sort_keys=True) for item in expected)
        actual = sorted(json.dumps(item, sort_keys=True) for item in actual)
    return [] if expected == actual else [path]


def validate_exceptions(profile):
    exceptions = profile.get("exceptions", {})
    if not isinstance(exceptions, dict):
        raise ValueError("exceptions는 객체여야 한다")
    for path, entry in exceptions.items():
        if path not in EXCEPTION_PATHS or not isinstance(entry, dict):
            raise ValueError(f"예외로 둘 수 없다: {path}")
        if (set(entry) != {"status", "reason", "evidence"} or entry["status"] not in ("unsupported", "not_applicable")
                or any(not isinstance(entry[key], str) or not entry[key].strip() for key in ("reason", "evidence"))):
            raise ValueError(f"예외에는 status, reason, evidence가 있어야 한다: {path}")
        if any(path.startswith(other + ".") for other in exceptions):
            raise ValueError(f"예외가 겹친다: {path}")
        value = profile.get("expected", {})
        for part in path.split("."):
            if not isinstance(value, dict) or part not in value:
                break
            value = value[part]
        else:
            raise ValueError(f"예외는 expected에서 빼야 한다: {path}")
    return exceptions


def validate_profile(profile):
    if not isinstance(profile, dict):
        raise ValueError("설정은 객체여야 한다")
    expected = profile.get("expected")
    if not isinstance(expected, dict):
        raise ValueError("설정에 필수 항목이 모두 있어야 한다")
    if "codeql_main_source" in expected:
        # Every codeql-action bump rewrote the pinned blob sha and left the audit drifting.
        raise ValueError("codeql_main_source는 더 보지 않는다. 설정에서 지운다")
    exceptions = validate_exceptions(profile)
    codeql = expected.get("codeql")
    default_setup = isinstance(codeql, dict) and codeql.get("state") == "configured"
    required = set(REQUIRED_FIELDS) - (ADVANCED_CODEQL if default_setup or "codeql" in exceptions else set())
    required -= {name for name in exceptions if "." not in name}
    if set(expected) != required:
        raise ValueError("설정에 필수 항목이 모두 있어야 한다(빠졌거나 남는 것: "
                         + ", ".join(sorted(set(expected) ^ required)) + ")")
    for control, fields in REQUIRED_FIELDS.items():
        if control not in required:
            continue
        value = expected[control]
        if control == "rulesets":
            if not isinstance(value, list) or any(
                    not isinstance(item, dict) or set(item) != set(RULESET_FIELDS)
                    or not isinstance(item["name"], str) or not item["name"] for item in value):
                raise ValueError("rulesets는 " + ", ".join(RULESET_FIELDS) + "가 모두 있는 ruleset 목록이어야 한다")
            if len({item["name"] for item in value}) != len(value):
                raise ValueError("ruleset 이름이 겹친다")
            continue
        if not isinstance(value, dict):
            raise ValueError(f"항목이 객체가 아니다: {control}")
        for field in fields.split():
            if f"{control}.{field}" in exceptions:
                continue
            current = value
            for part in field.split("."):
                if not isinstance(current, dict) or part not in current:
                    raise ValueError(f"필수 설정이 없다: {control}.{field}")
                current = current[part]
            leaf = field.split(".")[-1]
            kind = (str if leaf in STRING_FIELDS else int if leaf == "required_approving_review_count"
                    else list if leaf in {"checks", "patterns_allowed"} else bool)
            if type(current) is not kind:
                raise ValueError(f"설정의 형이 다르다: {control}.{field}")
            if kind is str and not current:
                raise ValueError(f"설정이 비었다: {control}.{field}")
        checks = value["required_status_checks"]["checks"] if control == "protection" else None
        if checks is not None and (not checks or any(
                not isinstance(check, dict) or not isinstance(check.get("context"), str)
                or not check["context"] or type(check.get("app_id")) is not int for check in checks)):
            raise ValueError("필수 체크에는 이름(context)과 App ID가 있어야 한다")
    workflow = expected.get("codeql_workflow")
    if isinstance(workflow, dict) and not WORKFLOW_PATH.fullmatch(str(workflow.get("path"))):
        raise ValueError("codeql_workflow.path는 .github/workflows/<이름>.yml이어야 한다")
    if type(profile.get("repository_id")) is not int or profile["repository_id"] <= 0:
        raise ValueError("repository_id가 맞지 않는다")


def validate_target(profile):
    """Schema version, repository name and branch, checked before any request path is built."""
    if type(profile.get("schema_version")) is not int or profile["schema_version"] != 1:
        raise ValueError("schema_version은 1이어야 한다")
    repo, branch = profile.get("repository"), profile.get("default_branch")
    if (not isinstance(repo, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]+", repo)
            or repo.split("/")[-1] in {".", ".."}):
        raise ValueError("repository가 owner/name 꼴이 아니다")
    if (not isinstance(branch, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", branch)
            or ".." in branch or branch.endswith(".")):
        raise ValueError("default_branch가 맞지 않는다")


def plain(text):
    """Server and project text goes to a terminal; control characters must not reach it."""
    return "".join(c if c.isprintable() else "?" for c in str(text))


def github_read(path):
    """GET through `gh api` (REST). A 404 raises CalledProcessError with "HTTP 404" in stderr."""
    result = subprocess.run(["gh", "api", "--method", "GET", path], capture_output=True, text=True,
                            check=True, timeout=60)
    if len(result.stdout) > MAX_READ * 32:  # the same cap as gh_api
        raise OSError(f"gh api {path}: 응답이 너무 크다")
    return json.loads(result.stdout) if result.stdout.strip() else None


def github_write(method, path, body):
    command = ["gh", "api", "--method", method, path, "--silent"] + (["--input", "-"] if body is not None else [])
    subprocess.run(command, input=None if body is None else json.dumps(body), text=True,
                   capture_output=True, check=True, timeout=60)


def read_rulesets(read, prefix):
    """(id, ruleset) for each repository ruleset; the summary list omits the rules, so read each one."""
    summaries, page = [], 1
    while True:
        chunk = read(f"{prefix}/rulesets?includes_parents=false&per_page=100&page={page}") or []
        # The id goes into a request path, so only an integer from the server is used.
        if not isinstance(chunk, list) or any(not isinstance(item, dict) or type(item.get("id")) is not int
                                              for item in chunk):
            raise ValueError("rulesets: id가 정수인 목록이 아니다")
        summaries += chunk
        if len(chunk) < 100:
            break
        page += 1
    return [(item["id"], {key: detail.get(key) for key in RULESET_FIELDS})
            for item in summaries for detail in [read(f"{prefix}/rulesets/{item['id']}")]]


def known_parameters(expected, actual):
    """Drop rule parameters the baseline does not list; GitHub may add new ones.
    Extra rulesets, extra rules and differing listed parameters still differ."""
    listed = {ruleset["name"]: {rule["type"]: set(rule.get("parameters") or {}) for rule in ruleset["rules"]
                                if isinstance(rule, dict) and "type" in rule}
              for ruleset in expected if isinstance(ruleset.get("rules"), list)}
    result = []
    for ruleset in actual:
        if not isinstance(ruleset.get("rules"), list):
            result.append(ruleset)  # a missing or odd rules value must still differ
            continue
        keys = listed.get(ruleset.get("name"), {})
        rules = [{**rule, "parameters": {k: v for k, v in rule["parameters"].items() if k in keys[rule["type"]]}}
                 if isinstance(rule, dict) and rule.get("type") in keys and isinstance(rule.get("parameters"), dict)
                 else rule for rule in ruleset["rules"]]
        result.append({**ruleset, "rules": rules})
    return result


def read_labels(read, prefix):
    labels, page = [], 1
    while True:
        chunk = read(f"{prefix}/labels?per_page=100&page={page}") or []
        if not isinstance(chunk, list):
            raise ValueError("labels: 목록이 아니다")
        labels += chunk
        if len(chunk) < 100:
            return labels
        page += 1


def label_changes(read, prefix):
    """Create each missing status label and fix a differing one; other labels are left alone."""
    # GitHub label names are unique without case, so `Wontfix` is the same label.
    found = {label["name"].lower(): label for label in read_labels(read, prefix)}
    changes = []
    for want in LABELS:
        have = found.get(want["name"].lower())
        if have is None:
            changes.append(([(f"labels.{want['name']}", "<not set>", want)], [("POST", f"{prefix}/labels", want)]))
            continue
        current = {key: have.get(key) for key in ("name", "color", "description")}
        current["color"] = str(current["color"]).lower()
        if current != want:
            body = {"new_name": want["name"], "color": want["color"], "description": want["description"]}
            changes.append(([(f"labels.{want['name']}", current, want)],
                            [("PATCH", f"{prefix}/labels/{quote(have['name'], safe='')}", body)]))
    return changes


def audit(profile, read):
    """Differing settings paths and labels, read only. The same reads as settings_plan."""
    validate_profile(profile)
    validate_target(profile)
    repo, branch = profile["repository"], profile["default_branch"]
    prefix = f"repos/{repo}"
    metadata = read(prefix)
    if not isinstance(metadata, dict) or metadata.get("id") != profile["repository_id"] or metadata.get("full_name") != repo:
        raise ValueError("저장소가 repository·repository_id와 다르다")
    result, workflow = [], workflow_file(profile)
    for name, expected in profile["expected"].items():
        if skipped(profile, name):
            continue
        if name == "repository":
            actual = metadata
        elif name == "rulesets":
            actual = known_parameters(expected, [ruleset for _, ruleset in read_rulesets(read, prefix)])
        else:
            # A 404 is "not set", as in settings_plan: it differs (1), it does not fail the run (2).
            actual, found = get(read, f"{prefix}/{endpoint(name, branch, workflow)}")
            if name == "dependabot_alerts":
                actual = {"enabled": found}  # 204 with no body when on, 404 when off
        result.extend(differences(expected, actual, name))
    return result + [path for shown, _ in label_changes(read, prefix) for path, _, _ in shown]


def github_load(root):
    """The project's file on top of the common values, refused before any request if unfilled or inconsistent."""
    try:
        data = read_file(root, GITHUB_PROFILE)
    except OSError as error:
        raise OSError(f"{GITHUB_PROFILE}: {error}") from None
    profile = merged(json.loads(data))
    validate_profile(profile)
    validate_target(profile)
    if profile["expected"]["repository"]["default_branch"] != profile["default_branch"]:
        raise ValueError("default_branch와 expected.repository.default_branch가 같아야 한다")
    return profile


def get(read, path):
    """GET a setting; (None, False) when GitHub answers 404 (not set up yet). Other errors stop the run."""
    try:
        return read(path), True
    except subprocess.CalledProcessError as error:
        if "HTTP 404" not in (error.stderr or ""):
            raise
        return None, False


def leaves(value, path):
    if isinstance(value, dict) and value:
        return [leaf for key, item in value.items() for leaf in leaves(item, f"{path}.{key}")]
    return [path]


def value_at(data, path):
    if data is None:
        return "<not set>"
    for part in path.split(".")[1:]:
        if not isinstance(data, dict) or part not in data:
            return "<missing>"
        data = data[part]
    return data


def audited(name, path):
    """Whether a drifted path is one of the audited fields apply writes."""
    fields = [f"{name}.{field}" for field in REQUIRED_FIELDS[name].split()] or [name]
    return any(path == field or field.startswith(path + ".") or path.startswith(field + ".") for field in fields)


def unmanaged_protection(actual):
    """Protection settings the baseline does not record; a PUT would reset any that are set."""
    kept = [key for key in UNMANAGED_PROTECTION if (actual.get(key) or {}).get("enabled")]
    kept += ["restrictions"] if actual.get("restrictions") else []
    reviews = actual.get("required_pull_request_reviews") or {}
    bypass = reviews.get("bypass_pull_request_allowances") or {}
    if any(bypass.get(kind) for kind in ("users", "teams", "apps")):
        kept.append("required_pull_request_reviews.bypass_pull_request_allowances")
    if reviews.get("dismissal_restrictions"):
        kept.append("required_pull_request_reviews.dismissal_restrictions")
    return kept


def writes_for(name, expected, prefix, branch):
    """GitHub write requests that turn the expected GET shape into server state."""
    def toggle(on):
        return "PUT" if on else "DELETE"
    if name == "repository":
        body = {field: expected[field] for field in MERGE_FIELDS if field in expected}
        security = expected.get("security_and_analysis", {})
        # A nested exception leaves {} without "status"; send only the features the baseline sets.
        secret = {key: security[key] for key in ("secret_scanning", "secret_scanning_push_protection")
                  if "status" in security.get(key, {})}
        if secret:
            body["security_and_analysis"] = secret
        result = [("PATCH", prefix, body)]
        if "status" in security.get("dependabot_security_updates", {}):
            on = security["dependabot_security_updates"]["status"] == "enabled"
            result.append((toggle(on), f"{prefix}/automated-security-fixes", None))
        return result
    if name == "protection":
        body = {
            "required_status_checks": {key: expected["required_status_checks"][key] for key in ("strict", "checks")},
            "enforce_admins": expected["enforce_admins"]["enabled"],
            "required_pull_request_reviews": {key: expected["required_pull_request_reviews"][key] for key in REVIEW_FIELDS},
            "restrictions": None,
            **{flag: expected[flag]["enabled"] for flag in PROTECTION_FLAGS},
        }
        return [("PUT", f"{prefix}/{endpoint(name, branch)}", body)]
    if name in ("dependabot_alerts", "immutable_releases", "private_vulnerability_reporting"):
        return [(toggle(expected["enabled"]), f"{prefix}/{endpoint(name, branch)}", None)]
    if name == "codeql":
        return [("PATCH", f"{prefix}/{endpoint(name, branch)}", {"state": expected["state"]})]
    fields = REQUIRED_FIELDS[name].split()
    return [("PUT", f"{prefix}/{endpoint(name, branch)}", {key: expected[key] for key in fields if key in expected})]


def ruleset_writes(expected, found, prefix, manual):
    """Create or replace each baseline ruleset by name; others are reported, never deleted."""
    by_name = {}
    for ruleset_id, ruleset in found:
        by_name.setdefault(ruleset["name"], []).append((ruleset_id, ruleset))
    shown, requests = [], []
    for ruleset in expected:
        same = by_name.get(ruleset["name"], [])
        if len(same) > 1:
            manual.append(f"rulesets.{ruleset['name']}: 이 이름의 ruleset이 여럿이다")
        elif not same:
            shown.append((f"rulesets.{ruleset['name']}", "<not set>", ruleset))
            requests.append(("POST", f"{prefix}/rulesets", ruleset))
        elif differences(ruleset, same[0][1]):
            shown.append((f"rulesets.{ruleset['name']}", same[0][1], ruleset))
            requests.append(("PUT", f"{prefix}/rulesets/{same[0][0]}", ruleset))
    names = {ruleset["name"] for ruleset in expected}
    manual.extend(f"rulesets.{name}은 기준에 없다. 지우지 않는다" for name in by_name if name not in names)
    return shown, requests


def settings_plan(profile, read):
    """(changes, manual). changes: per control or label, the differing (path, current, baseline) values and
    the requests that fix them. manual: differences apply leaves to a person."""
    repo, branch = profile["repository"], profile["default_branch"]
    prefix = f"repos/{repo}"
    metadata = read(prefix)
    if not isinstance(metadata, dict) or metadata.get("id") != profile["repository_id"] or metadata.get("full_name") != repo:
        raise ValueError("저장소가 repository·repository_id와 다르다")
    if metadata.get("default_branch") != branch:
        raise ValueError("저장소의 기본 브랜치가 default_branch와 다르다")
    changes, manual, current = [], [], {}
    expected, workflow = profile["expected"], workflow_file(profile)
    for name in SETTINGS_ORDER + SETTINGS_MANUAL:
        if name not in expected or skipped(profile, name):
            continue
        if name == "repository":
            actual = metadata
        elif name == "rulesets":
            found = read_rulesets(read, prefix)
            ids = [ruleset_id for ruleset_id, _ in found]
            actual = known_parameters(expected[name], [ruleset for _, ruleset in found])
            found = list(zip(ids, actual))
        elif name == "allowed_actions" and "actions" in current and current["actions"].get("allowed_actions") != "selected":
            actual = None  # GitHub lists selected actions only under a "selected" policy; the actions write comes first
        else:
            actual, found = get(read, f"{prefix}/{endpoint(name, branch, workflow)}")
            if name == "dependabot_alerts":
                actual = {"enabled": found}  # 204 with no body when on, 404 when off
            if name == "private_vulnerability_reporting" and not found:
                # Off answers {"enabled": false}; 404 means a private repository, which has no merge queue either.
                raise ValueError("private-vulnerability-reporting가 404다. 비공개 저장소는 기준 밖이다(POLICY §5)")
        current[name] = actual if isinstance(actual, dict) else {}
        # A control that is not set yet differs in every field; list them so unaudited ones still show.
        drift = leaves(expected[name], name) if actual is None else differences(expected[name], actual, name)
        if not drift:
            continue
        if name == "rulesets":
            shown, requests = ruleset_writes(expected[name], found, prefix, manual)
            if requests:
                changes.append((shown, requests))
            continue
        if name in SETTINGS_MANUAL:
            manual.extend(f"{path}가 다르다. apply는 바꾸지 않는다" for path in drift)
            continue
        if name == "repository" and "repository.visibility" in drift:
            manual.append("repository.visibility가 다르다. apply는 바꾸지 않는다")
            drift.remove("repository.visibility")
            if not drift:
                continue
        unaudited = [path for path in drift if not audited(name, path)]
        if unaudited:
            manual.extend(f"{path}가 다르다. apply는 필수 필드만 쓴다" for path in unaudited)
            drift = [path for path in drift if path not in unaudited]
            if not drift:
                continue
        if name == "protection" and actual is not None:
            kept = unmanaged_protection(actual)
            if kept:
                manual.extend(f"protection.{key}가 켜져 있다. protection을 쓰면 지워진다" for key in kept)
                continue
        if name == "codeql" and expected[name]["state"] == "not-configured" and "codeql_workflow" in expected:
            live = get(read, f"{prefix}/{endpoint('codeql_workflow', branch, workflow)}")[0]
            # The workflow must really run, whatever state the baseline records for it.
            ready = (live or {}).get("state") == "active" and not differences(
                expected["codeql_workflow"], live, "codeql_workflow")
            if not ready:
                manual.append("codeql.state: 고급 설정 workflow가 돌 때까지 기본 설정을 켜 둔다")
                continue
        shown = [(path, value_at(actual, path), value_at(expected[name], path)) for path in drift]
        changes.append((shown, writes_for(name, expected[name], prefix, branch)))
    return changes + label_changes(read, prefix), manual


def wait_for_codeql(profile, read, sleep, step=5):
    path = f"repos/{profile['repository']}/{endpoint('codeql', profile['default_branch'])}"
    for _ in range(CODEQL_WAIT // step):
        current, _ = get(read, path)  # may answer 404 while setup is still being created
        if (current or {}).get("state") == profile["expected"]["codeql"]["state"]:
            return
        sleep(step)


def github(root, apply, read=github_read, write=github_write, sleep=time.sleep):
    """plan: read only, 0 when nothing differs. apply: plan, write, then audit again. 2 on any error."""
    done, attempt, drift = [], None, []
    try:
        profile = github_load(root)
        print(f"github: 공통값은 baseline.py {VERSION}, 프로젝트 값은 {GITHUB_PROFILE}(프로젝트 값이 이긴다)")
        changes, manual = settings_plan(profile, read)
        for shown, requests in changes:
            for path, before, after in shown:
                print(f"github: 차이: {plain(path)}: {json.dumps(before, sort_keys=True, ensure_ascii=False)} -> "
                      f"{json.dumps(after, sort_keys=True, ensure_ascii=False)}")
            for method, path, body in requests:
                print(f"github: {'적용' if apply else '계획'}: {method} {path}"
                      + ("" if body is None else " " + json.dumps(body, sort_keys=True, ensure_ascii=False)))
                if apply:
                    attempt = f"{method} {path}"
                    write(method, path, body)
                    done.append(attempt)
                    attempt = None
        for line in manual:
            print(f"github: 사람이 할 일: {plain(line)}")
        if skipped(profile, "allowed_actions"):
            print("github: 건너뜀: actions.allowed_actions가 selected가 아니라 allowed_actions 목록은 쓰지도 보지도 않는다")
        for path, entry in sorted(profile.get("exceptions", {}).items()):
            print(plain(f"github: 예외({entry['status']}): {path}: {entry['reason']} ({entry['evidence']})")
                  + ". 쓰지도 보지도 않는다")
        if apply:
            if any(path.endswith("code-scanning/default-setup") for path in done):
                wait_for_codeql(profile, read, sleep)
            drift = audit(profile, read)
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        stderr = getattr(error, "stderr", None)
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        detail = stderr.strip().splitlines()[-1] if stderr and stderr.strip() else f"{type(error).__name__}: {error}"
        print(f"github: 실패: {detail}", file=sys.stderr)
        if done:
            print("github: 이미 썼다: " + ", ".join(done) + ". 다시 하기 전에 github plan을 돌린다", file=sys.stderr)
        if attempt:
            print(f"github: 결과를 모른다: {attempt}. github plan으로 적용됐는지 본다", file=sys.stderr)
        return 2
    limited = "(선언한 예외는 확인하지 않았다)" if profile.get("exceptions") else ""
    if not apply:
        if changes:
            print("github: 계획만 했다. 아무것도 쓰지 않았다. 읽고 나서 github apply로 적용한다")
        elif manual:
            print("github: 쓸 것은 없고 사람이 할 일이 남았다")
        else:
            print(f"github: 차이 없음: {profile['repository']}{limited}")
        return 1 if changes or manual else 0
    if drift:
        print("github: 적용 뒤에도 다르다: " + ", ".join(drift))
    else:
        print(f"github: 통과: {profile['repository']} 설정과 라벨이 기준과 같다{limited}")
    return 1 if drift or manual else 0


def cmd_github(args):
    return github(repo_root(), args.action == "apply", read=github_read, write=github_write)


# ops profile: docs/agents/ops.md when baseline.json lists "ops" (ops/README.md)
OPS_PATH = "docs/agents/ops.md"
# Tools of the ops/README.md table, in order. A rule line names at most one of them.
OPS_TOOLS = ("GitHub secret scanning, push protection, Dependabot, CodeQL", "GitGuardian", "Sentry", "PostHog",
             "UptimeRobot", "Cloudflare", "Grafana Cloud", "Infisical")
# Each secret name belongs to the tool whose name contains this word.
OPS_NAMES = {"SENTRY_DSN": "Sentry", "SENTRY_AUTH_TOKEN": "Sentry", "POSTHOG_KEY": "PostHog", "POSTHOG_HOST": "PostHog"}
OPS_EXCLUSION = re.compile(r"- 뺀 도구: (.+?) — (\S.*)")
# The bytes of ops/ops.md (test_github.py keeps them equal).
OPS_MD = """# ops

- repo-baseline ops 프로필의 도구를 모두 쓴다. 이 파일은 손으로 고치지 않는다. 빼는 도구는 이 파일 끝에 `- 뺀 도구: 도구 — 이유` 한 줄로 적고 그 도구의 줄을 지운다. 다른 도구를 더하려면 먼저 소유자에게 묻는다.
- 코드·의존성 보안(GitHub secret scanning, push protection, Dependabot, CodeQL)은 켜져 있다. CodeQL은 기본 설정을 먼저 쓰고, 기본 설정으로 분석이 안 될 때만 고급 설정 workflow를 쓴다. 그 이유는 저장소 문서에 적는다. 저장소에서 끄지 않는다.
- GitGuardian은 조직에 설치한 GitHub App으로 돈다. 저장소에서 끄지 않는다.
- 에러 추적은 Sentry다.
- 제품 분석은 PostHog다.
- SDK는 처음 배포하는 PR에서 붙인다. 이미 배포한 앱이면 이 파일을 더한 뒤 따로 여는 PR에서 붙인다.
- 배포한 URL은 UptimeRobot에 소유자가 등록한다.
- 도메인은 Cloudflare에 소유자가 연결한다. DNS와 Cloudflare 설정 변경도 소유자가 한다.
- 서버를 직접 운영하게 되면 Grafana Cloud를 켠다. 켜기 전에 소유자에게 알린다.
- 비밀값이 세 곳을 넘으면 Infisical을 켠다. 켜기 전에 소유자에게 알린다.
- Sentry 비밀값 이름은 `SENTRY_DSN`, `SENTRY_AUTH_TOKEN`이다. `.env.example`에 빈 칸으로 둔다. `SENTRY_AUTH_TOKEN`은 GitHub secrets에만 둔다.
- PostHog 비밀값 이름은 `POSTHOG_KEY`, `POSTHOG_HOST`다. `.env.example`에 빈 칸으로 둔다.
- 개인 정보는 분석 이벤트에 넣지 않는다. 세션 녹화를 켜면 입력 필드와 개인 정보를 보여 주는 화면 요소를 가린다.
- SDK를 처음 붙이거나 보내는 데이터를 넓히는 PR은 되돌리기 어려움이다(POLICY §4 다른 사람 데이터의 노출).
- 감시 대상 변경은 소유자가 한다.
"""


def ops_mentions(tool, line):
    return tool in line or any(owner in tool and name in line for name, owner in OPS_NAMES.items())


def ops_text(exclude):
    """docs/agents/ops.md for these exclusions ({tool: reason}, in any order)."""
    unknown = [tool for tool in exclude if tool not in OPS_TOOLS]
    if unknown:
        raise ValueError(f"ops 표에 없는 도구를 뺐다: {', '.join(unknown)}")
    lines = [line for line in OPS_MD.splitlines()
             if not (line.startswith("- ") and any(ops_mentions(tool, line) for tool in exclude))]
    return "\n".join(lines + [f"- 뺀 도구: {tool} — {exclude[tool]}" for tool in OPS_TOOLS if tool in exclude]) + "\n"


def ops_problems(root):
    """The ops file equals OPS_MD minus excluded tools' lines plus one `뺀 도구:` line each. Once .env.example
    names an ops secret (the first-deploy SDK PR), every kept tool's names are there and empty."""
    try:
        text = read_file(root, OPS_PATH).decode("utf-8")
    except (OSError, ValueError) as error:
        return [f"{OPS_PATH}: {error}"]
    excluded, problems = {}, []
    for line in text.splitlines():
        if line.startswith("- 뺀 도구:"):
            match = OPS_EXCLUSION.fullmatch(line)
            if match:
                excluded[match.group(1)] = match.group(2)
            else:
                problems.append(f"{OPS_PATH}: 형식이 `- 뺀 도구: <도구> — <이유>`가 아니다: {line}")
    try:
        expected = ops_text(excluded)
    except ValueError as error:
        return problems + [f"{OPS_PATH}: {error}"]
    if text != expected:
        have, want = text.splitlines(), expected.splitlines()
        problems += [f"{OPS_PATH}에 없다: {line}" for line in want if line not in have]
        problems += [f"{OPS_PATH}에 있으면 안 된다: {line}" for line in have if line not in want]
        if not problems:
            problems.append(f"{OPS_PATH}: 줄 순서나 빈 줄이 ops/ops.md와 다르다")
    try:
        os.lstat(root / ".env.example")
    except FileNotFoundError:
        return problems
    except OSError:
        pass  # Path.exists() is False when stat is denied (a sandbox on .env.*); read_file below reports it
    try:
        lines = read_file(root, ".env.example").decode("utf-8").splitlines()
    except (OSError, ValueError) as error:
        return problems + [f".env.example: {error}"]
    # A framework prefix such as NEXT_PUBLIC_ is allowed in front of the name.
    found = {name: [line for line in lines if re.match(rf"\s*(?:export\s+)?(?:[A-Z0-9]+_)*{name}\s*=", line)]
             for name in OPS_NAMES}
    if not any(found.values()):
        return problems
    for name, owner in OPS_NAMES.items():
        if any(owner in tool for tool in excluded):
            continue
        if not found[name]:
            problems.append(f".env.example에 {name} 칸이 없다")
        elif any(line.split("=", 1)[1].strip().strip("'\"") for line in found[name]):
            problems.append(f".env.example의 {name}에 값이 있다. 빈 칸으로 둔다")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(prog="baseline.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="빈 저장소에 코어를 복사한다").add_argument("path")
    migrate_parser = sub.add_parser("migrate", help="기존 저장소의 충돌과 옮길 계획을 출력한다(--apply면 쓴다)")
    migrate_parser.add_argument("path")
    migrate_parser.add_argument("--apply", action="store_true", help="막힘이 없으면 계획대로 쓴다")
    sub.add_parser("check", help="관리 파일·블록과 명령 칸이 이 판과 같은지 본다")
    sub.add_parser("run", help="commands.json의 명령을 돌린다").add_argument("name", choices=COMMANDS)
    sub.add_parser("budget", help="AGENTS.md와 리뷰어가 읽는 글의 크기를 잰다")
    sub.add_parser("upgrade", help="관리 블록·파일·스킬 사본을 그 태그 판으로 바꾼다").add_argument("tag")
    preflight_parser = sub.add_parser("review-preflight", help="REST로 PR의 등급과 리뷰 전 확인을 출력한다")
    preflight_parser.add_argument("pr", help="PR URL 또는 번호")
    preflight_parser.add_argument("--remote", default="origin", help="base 저장소의 remote(번호만 줄 때)")
    preflight_parser.add_argument("--json", action="store_true", help="JSON 한 개로 출력한다")
    enqueue_parser = sub.add_parser("enqueue", help="문서·쉬움 PR을 다시 확인하고 머지 큐에 넣는다(로컬 전용)")
    enqueue_parser.add_argument("pr", help="PR URL 또는 번호")
    enqueue_parser.add_argument("sha", help="리뷰한 head(40자 SHA)")
    enqueue_parser.add_argument("--remote", default="origin", help="base 저장소의 remote(번호만 줄 때)")
    report_parser = sub.add_parser("review-report", help="스레드 판정에 답하고 해결한 뒤 PR 본문의 Review 칸만 바꾼다")
    report_parser.add_argument("pr", help="PR URL 또는 번호")
    report_parser.add_argument("--file", required=True, help="Review 칸의 줄(「리뷰한 head:」「등급:」「남은 지적:」 등)")
    report_parser.add_argument("--thread", action="append", default=[], metavar="ID=판정",
                               help="판정한 리뷰 스레드 댓글 id와 답글(여러 번)")
    report_parser.add_argument("--remote", default="origin", help="base 저장소의 remote(번호만 줄 때)")
    bump_parser = sub.add_parser("skills-bump", help="스킬 출처마다 7일 지난 새 판으로 사본을 바꾼다(repo-baseline 전용)")
    bump_parser.add_argument("--check", action="store_true", help="바꾸지 않고 새 판이 있는지만 본다(있으면 1)")
    sub.add_parser("doctor", help="로컬 기기와 기준이 다른 곳을 보고 고치는 명령을 출력한다")
    sub.add_parser("github", help="저장소 설정과 상태 라벨을 기준과 비교한다(plan) 또는 적용한다(apply, 소유자만)"
                   ).add_argument("action", choices=("plan", "apply"))
    args = parser.parse_args(argv)
    return {"init": cmd_init, "migrate": cmd_migrate, "check": cmd_check, "run": cmd_run, "budget": cmd_budget, "upgrade": cmd_upgrade,
            "review-preflight": cmd_review_preflight, "enqueue": cmd_enqueue, "review-report": cmd_review_report,
            "skills-bump": cmd_skills_bump, "doctor": cmd_doctor, "github": cmd_github}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
