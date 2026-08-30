#!/usr/bin/env python3
"""Validate a Claude Code SKILL.md against the documented frontmatter contract.

Usage:
    validate_skill.py <path-to-SKILL.md | skill-dir> [...]   # validate
    validate_skill.py --portable <path>                      # also enforce the
                                                             # agentskills.io spec
                                                             # subset (claude.ai
                                                             # upload / Skills API)
    validate_skill.py --all <skills-root>                    # walk a skills tree

Exit code 0 = no errors (warnings allowed), 1 = at least one error.

Reference: https://code.claude.com/docs/en/skills#frontmatter-reference
           https://agentskills.io/specification
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Contract tables (keep in sync with references/frontmatter.md)
# ---------------------------------------------------------------------------

CLAUDE_CODE_FIELDS = {
    "name",
    "description",
    "when_to_use",
    "argument-hint",
    "arguments",
    "disable-model-invocation",
    "user-invocable",
    "allowed-tools",
    "disallowed-tools",
    "model",
    "effort",
    "context",
    "agent",
    "background",
    "hooks",
    "paths",
    "shell",
    "metadata",
    "license",
    "compatibility",
}

# Portable subset accepted by claude.ai uploads, the Skills API and package_skill.py
PORTABLE_FIELDS = {
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
}

BOOL_FIELDS = {"disable-model-invocation", "user-invocable", "background"}
TRUTHY = {"true", "yes", "on", "1"}
FALSY = {"false", "no", "off", "0"}

EFFORT_VALUES = {"low", "medium", "high", "xhigh", "max"}
SHELL_VALUES = {"bash", "powershell"}

DESC_LISTING_CAP = 1536  # description + when_to_use, per docs
COMPATIBILITY_CAP = 500
BODY_LINE_SOFT_CAP = 500

# Common typos / fields that belong to agents, not skills
KNOWN_MISTAKES = {
    "tools": "agents use `tools:`; skills use `allowed-tools:`",
    "allowed_tools": "use `allowed-tools` (hyphen, not underscore)",
    "disallowed_tools": "use `disallowed-tools` (hyphen, not underscore)",
    "when-to-use": "the field is `when_to_use` (underscore, not hyphen)",
    "argument_hint": "use `argument-hint` (hyphen, not underscore)",
    "user_invocable": "use `user-invocable` (hyphen, not underscore)",
    "disable_model_invocation": "use `disable-model-invocation` (hyphens)",
    "version": "not a Claude Code field; put it under `metadata:` if you need it",
    "author": "not a Claude Code field; put it under `metadata:` if you need it",
    "tags": "not a Claude Code field; put it under `metadata:` if you need it",
    "skills": "`skills:` is a subagent field, not a skill field",
    "color": "not a Claude Code skill field",
}

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FIRST_PERSON_RE = re.compile(r"\b(I |I'll|I can|my |we |we'll|our )", re.IGNORECASE)
MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)#][^)]*)\)")
INLINE_BASH_RE = re.compile(r"(?:^|\s)!`([^`]+)`")
FENCED_BASH_RE = re.compile(r"^```!\s*$", re.MULTILINE)
NAMED_ARG_RE = re.compile(r"\$([a-zA-Z_][a-zA-Z0-9_]*)")


class Report:
    def __init__(self, path: Path):
        self.path = path
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.notes: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def note(self, msg: str) -> None:
        self.notes.append(msg)

    def render(self) -> str:
        icon = "FAIL" if self.errors else ("WARN" if self.warnings else "OK")
        out = [f"[{icon}] {self.path}"]
        out += [f"  ERROR   {m}" for m in self.errors]
        out += [f"  WARN    {m}" for m in self.warnings]
        out += [f"  note    {m}" for m in self.notes]
        return "\n".join(out)


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------

def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Return (frontmatter_yaml, body). frontmatter is None when absent."""
    if not text.startswith("---"):
        return None, text
    lines = text.split("\n")
    if lines[0].strip() != "---":
        return None, text
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1:])
    return None, text


def parse_yaml(raw: str) -> tuple[dict | None, str | None]:
    try:
        import yaml  # type: ignore
    except ImportError:
        return _parse_yaml_fallback(raw), None
    try:
        data = yaml.safe_load(raw)
    except Exception as exc:  # noqa: BLE001 - surface any YAML error verbatim
        return None, str(exc).replace("\n", " ")
    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return None, "frontmatter is not a YAML mapping"
    return data, None


def _parse_yaml_fallback(raw: str) -> dict:
    """Line-based top-level parse for environments without PyYAML."""
    data: dict = {}
    key = None
    for line in raw.split("\n"):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[:1] not in (" ", "\t") and ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            data[key] = value.strip() or {}
        elif key is not None and isinstance(data.get(key), dict):
            data[key] = data[key] or {}
    return data


def as_bool(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value) if value in (0, 1) else None
    if isinstance(value, str):
        low = value.strip().lower()
        if low in TRUTHY:
            return True
        if low in FALSY:
            return False
    return None


def as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [p for p in re.split(r"[,\s]+", str(value)) if p]


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def validate(path: Path, portable: bool) -> Report:
    rep = Report(path)
    text = path.read_text(encoding="utf-8")

    if path.name != "SKILL.md" and path.suffix == ".md" and path.parent.name != "commands":
        rep.warn("entrypoint should be named SKILL.md (a skill is a directory)")

    fm_raw, body = split_frontmatter(text)
    if fm_raw is None:
        rep.error("no YAML frontmatter: the file must start with a `---` line")
        return rep

    fm, err = parse_yaml(fm_raw)
    if err or fm is None:
        rep.error(
            f"frontmatter YAML is malformed ({err}). Claude Code loads the body with "
            "EMPTY metadata in this case: /name still works but the description is gone"
        )
        return rep

    _check_fields(rep, fm, portable)
    _check_name(rep, fm, path, portable)
    _check_description(rep, fm, portable)
    if portable:
        _check_portable_extras(rep, fm)
    _check_invocation(rep, fm)
    _check_fork(rep, fm)
    _check_values(rep, fm)
    _check_body(rep, fm, body, path)
    return rep


def _check_fields(rep: Report, fm: dict, portable: bool) -> None:
    allowed = PORTABLE_FIELDS if portable else CLAUDE_CODE_FIELDS
    for key in fm:
        if key in allowed:
            continue
        if key in KNOWN_MISTAKES:
            rep.error(f"unknown field `{key}`: {KNOWN_MISTAKES[key]}")
        elif portable and key in CLAUDE_CODE_FIELDS:
            rep.error(
                f"`{key}` is Claude Code-only; portable distribution (claude.ai upload, "
                f"Skills API, package_skill.py) hard-fails on it. Allowed: "
                f"{', '.join(sorted(PORTABLE_FIELDS))}"
            )
        else:
            rep.error(f"unknown frontmatter field `{key}` (typo? it will be ignored)")


def _check_name(rep: Report, fm: dict, path: Path, portable: bool) -> None:
    name = fm.get("name")
    if name is None:
        if portable:
            rep.error("`name` is required by the Agent Skills spec")
        else:
            rep.note("no `name`: listings fall back to the directory name")
        return
    name = str(name)
    if not NAME_RE.match(name):
        rep.error(
            f"`name: {name}` must be lowercase a-z0-9 and single hyphens, with no "
            "leading, trailing or doubled hyphen (agentskills.io spec)"
        )
    if not 1 <= len(name) <= 64:
        rep.error(f"`name` is {len(name)} chars; the spec allows 1-64")
    dirname = path.parent.name
    if dirname not in ("skills", "commands") and name != dirname:
        msg = (f"`name: {name}` differs from the directory `{dirname}/`. The spec requires "
               f"name == parent directory; in Claude Code the command is /{dirname} and "
               "`name` is only the display label")
        rep.error(msg) if portable else rep.warn(msg)


def _check_description(rep: Report, fm: dict, portable: bool) -> None:
    desc = fm.get("description")
    if not desc:
        if portable:
            rep.error("`description` is required by the Agent Skills spec (1-1024 chars)")
        else:
            rep.warn("no `description`: Claude falls back to the first paragraph and "
                     "auto-invocation gets unreliable")
        return
    desc = str(desc)
    if len(desc) > 1024:
        msg = (f"`description` is {len(desc)} chars; the Agent Skills spec caps it at 1024 "
               "(Claude Code itself only truncates the listing entry at 1536)")
        rep.error(msg) if portable else rep.warn(msg)
    when = str(fm.get("when_to_use") or "")
    total = len(desc) + len(when)
    if total > DESC_LISTING_CAP:
        rep.error(
            f"description + when_to_use is {total} chars; the skill listing truncates "
            f"at {DESC_LISTING_CAP}. Put the key use case first"
        )
    elif total > 900:
        rep.warn(f"description + when_to_use is {total} chars — long entries eat the "
                 "shared listing budget and get trimmed first")
    if FIRST_PERSON_RE.search(desc):
        rep.warn("description uses first person; it is injected into the system prompt "
                 "— write it in third person")
    low = desc.lower()
    trigger_words = ("use when", "use for", " when ", "whenever", "trigger",
                     "когда", "если", "используй")
    if not any(w in low for w in trigger_words):
        rep.warn("description has no triggering condition; start with "
                 "\"Use when ...\" so the model can match it")
    if low.startswith("this skill"):
        rep.warn("drop the \"This skill ...\" preamble; lead with the trigger")


def _check_portable_extras(rep: Report, fm: dict) -> None:
    """Rules that only apply to the agentskills.io distribution path."""
    meta = fm.get("metadata")
    if isinstance(meta, dict):
        bad = [k for k, v in meta.items() if not isinstance(v, str)]
        if bad:
            rep.warn(f"spec says `metadata` maps string keys to string VALUES; "
                     f"non-string values: {', '.join(map(str, bad))}")
    tools = fm.get("allowed-tools")
    if isinstance(tools, str) and "," in tools:
        rep.error("the spec defines `allowed-tools` as a space-separated string; "
                  "commas are a Claude Code extension")
    elif isinstance(tools, list):
        rep.warn("the spec defines `allowed-tools` as a space-separated string; "
                 "a YAML list is a Claude Code extension")


def _check_invocation(rep: Report, fm: dict) -> None:
    for field in BOOL_FIELDS:
        if field in fm and as_bool(fm[field]) is None:
            rep.error(f"`{field}: {fm[field]}` is not a boolean "
                      "(true/false/yes/no/on/off/1/0)")
    dmi = as_bool(fm.get("disable-model-invocation")) or False
    ui = as_bool(fm.get("user-invocable"))
    if dmi and ui is False:
        rep.error("`disable-model-invocation: true` + `user-invocable: false` makes the "
                  "skill unreachable by anyone")
    if "paths" in fm and dmi:
        rep.warn("`paths` only gates automatic activation, which "
                 "`disable-model-invocation: true` already disables")


def _check_fork(rep: Report, fm: dict) -> None:
    ctx = str(fm.get("context") or "").strip().lower()
    if "context" in fm and ctx != "fork":
        rep.error(f"`context: {fm['context']}` — the only documented value is `fork`")
    forked = ctx == "fork"
    if "agent" in fm and not forked:
        rep.error("`agent` only applies with `context: fork`")
    if "background" in fm and not forked:
        rep.error("`background` only applies with `context: fork`")
    if forked and as_bool(fm.get("background")) is not False:
        rep.note("forked skills run in the background by default and get the narrower "
                 "background-subagent tool set; set `background: false` if a step needs "
                 "the full tool set or the result in this turn")


def _check_values(rep: Report, fm: dict) -> None:
    effort = fm.get("effort")
    if effort is not None and str(effort).lower() not in EFFORT_VALUES:
        rep.error(f"`effort: {effort}` — allowed: {', '.join(sorted(EFFORT_VALUES))}")
    shell = fm.get("shell")
    if shell is not None and str(shell).lower() not in SHELL_VALUES:
        rep.error(f"`shell: {shell}` — allowed: {', '.join(sorted(SHELL_VALUES))}")
    meta = fm.get("metadata")
    if meta is not None and not isinstance(meta, dict):
        rep.error("`metadata` must be a YAML map; a non-map value is dropped")
    if isinstance(meta, dict):
        clash = set(meta) & CLAUDE_CODE_FIELDS
        if clash:
            rep.warn(f"`metadata` reuses frontmatter field names: {', '.join(sorted(clash))}")
    compat = fm.get("compatibility")
    if compat is not None:
        if not isinstance(compat, str):
            rep.error("`compatibility` must be a string")
        elif len(compat) > COMPATIBILITY_CAP:
            rep.error(f"`compatibility` is {len(compat)} chars; cap is {COMPATIBILITY_CAP}")
    hooks = fm.get("hooks")
    if hooks is not None and not isinstance(hooks, dict):
        rep.error("`hooks` must be a map of event name -> matcher list")


def _check_body(rep: Report, fm: dict, body: str, path: Path) -> None:
    lines = body.count("\n") + 1
    if lines > BODY_LINE_SOFT_CAP:
        rep.warn(f"body is {lines} lines; keep SKILL.md under {BODY_LINE_SOFT_CAP} and "
                 "move reference material to files loaded on demand")
    est_tokens = int(len(body) / 3.5)  # rough, mixed latin/cyrillic
    if est_tokens > 5000:
        rep.warn(f"body is ~{est_tokens} tokens; the spec recommends under 5000 for the "
                 "level-2 payload, and it stays in context for the whole session")
    if not body.strip():
        rep.error("empty body: the skill has nothing to instruct")

    # Injected shell commands must be pre-approved or the whole invocation aborts.
    injected = INLINE_BASH_RE.findall(body)
    has_fenced = bool(FENCED_BASH_RE.search(body))
    if injected or has_fenced:
        grants = " ".join(as_list(fm.get("allowed-tools")))
        if "Bash" not in grants and str(fm.get("shell", "")).lower() != "powershell":
            rep.warn("body injects shell output with !`cmd`, but no Bash grant in "
                     "`allowed-tools`: a permission prompt aborts the whole invocation")
        for cmd in injected:
            if "||" not in cmd and cmd.split()[0] in {"grep", "rg", "diff", "test", "["}:
                rep.note(f"!`{cmd}` — non-zero exit aborts the invocation; "
                         "append `|| true` unless it is a carve-out command")

    # Declared named arguments should actually be used.
    declared = as_list(fm.get("arguments"))
    if declared:
        used = set(NAMED_ARG_RE.findall(body))
        missing = [a for a in declared if a not in used]
        if missing:
            rep.warn(f"declared arguments never used in the body: {', '.join(missing)}")
    if "argument-hint" in fm and "$" not in body:
        rep.warn("`argument-hint` promises arguments but the body has no "
                 "$ARGUMENTS/$0/$name placeholder")

    # Referenced supporting files must exist.
    for target in MD_LINK_RE.findall(body):
        target = target.split()[0].strip("<>")
        if re.match(r"^[a-z]+://|^/|^\$\{|^mailto:", target):
            continue
        if not (path.parent / target).exists():
            rep.error(f"referenced file does not exist: {target}")

    if str(fm.get("context", "")).lower() == "fork":
        imperative = re.search(r"^\s*(?:\d+\.|[-*])?\s*(?:[A-ZА-Я][a-zа-я]+)\b",
                               body.strip(), re.MULTILINE)
        if not imperative:
            rep.warn("`context: fork` needs an actionable task in the body — a forked "
                     "subagent given only guidelines returns nothing useful")


# ---------------------------------------------------------------------------

def collect(targets: list[str], walk_all: bool) -> list[Path]:
    found: list[Path] = []
    for target in targets:
        p = Path(target).expanduser()
        if p.is_dir():
            if walk_all:
                found += sorted(p.glob("**/SKILL.md"))
            elif (p / "SKILL.md").exists():
                found.append(p / "SKILL.md")
            else:
                found += sorted(p.glob("*/SKILL.md"))
        elif p.exists():
            found.append(p)
        else:
            print(f"[FAIL] {p}\n  ERROR   file not found", file=sys.stderr)
            found.append(Path(os.devnull))
    return [f for f in found if f != Path(os.devnull)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("targets", nargs="+", help="SKILL.md files, skill dirs, or a skills root")
    ap.add_argument("--portable", action="store_true",
                    help="also enforce the agentskills.io six-field subset")
    ap.add_argument("--all", action="store_true", help="walk the tree for every SKILL.md")
    args = ap.parse_args()

    paths = collect(args.targets, args.all)
    if not paths:
        print("no SKILL.md found", file=sys.stderr)
        return 1

    failed = 0
    for path in paths:
        rep = validate(path, args.portable)
        failed += bool(rep.errors)
        print(rep.render())
    print(f"\n{len(paths)} skill(s) checked, {failed} with errors")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
