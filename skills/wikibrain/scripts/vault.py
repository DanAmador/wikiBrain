"""The vault the wiki lives in: where it is, how a note's properties are read and written, how a note
is linked. A small YAML subset, the one the wiki writes; the standard library only.

A vault is any folder holding `wiki/` (an Obsidian vault, an llm-wiki clone). It may also hold a
`wayfinder/` tracker whose tickets articles cite as sources; the minimal ticket reading here is all
the wiki needs of it.
"""
import os
import re
import tempfile
from pathlib import Path

_default = Path.home() / "Documents" / "Second Brain"
VAULT = Path(os.environ.get("SB_VAULT") or (_default if _default.is_dir() else Path.cwd()))
WAYFINDER = VAULT / "wayfinder"

TICKET_STATUS = {"project.planned": "open", "project.inprogress": "claimed", "project.finished": "resolved",
                 "project.dropped": "out-of-scope", "planned": "open", "inprogress": "claimed",
                 "finished": "resolved", "dropped": "out-of-scope"}


def split_fm(text):
    """(properties, body, had_frontmatter)."""
    if not text.startswith("---\n"):
        return {}, text, False
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text, False
    props, key = {}, None
    for line in text[4:end].splitlines():
        item = re.match(r"^\s+-\s*(.*)$", line)
        kv = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if item and key is not None:
            props.setdefault(key, [])
            if isinstance(props[key], list):
                props[key].append(unquote(item.group(1)))
        elif kv:
            key, value = kv.group(1), kv.group(2).strip()
            if value in ("", "[]"):
                props[key] = []
            elif value.startswith("[") and value.endswith("]") and not value.startswith("[["):
                props[key] = [unquote(v) for v in value[1:-1].split(",") if v.strip()]
            else:
                props[key] = unquote(value)
    return props, text[end + 5:], True


def unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] == '"':
        return v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if len(v) >= 2 and v[0] == v[-1] == "'":
        return v[1:-1].replace("''", "'")
    return v


def scalar(v):
    v = str(v)
    if v == "" or re.search(r"[:#\[\]{}&*!|>'\"%@`,]|^[-?\s]|\s$", v):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return v


def dump_fm(props, order):
    keys = [k for k in order if k in props] + [k for k in props if k not in order]
    lines = ["---"]
    for k in keys:
        v = props[k]
        if isinstance(v, list):
            if not v:
                continue
            lines.append(f"{k}:")
            # a bare 001 or true in a list is a number or a boolean to YAML; Obsidian flags it
            lines += [f'  - "{x}"' if re.fullmatch(r"[-+.\d]+|true|false|null|~", str(x), re.I)
                      else f"  - {scalar(x)}" for x in v]
        elif v not in (None, ""):
            lines.append(f"{k}: {scalar(v)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def write_atomic(path, text):
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def rel(path):
    """The vault-relative path Obsidian speaks; the absolute path for a file outside the vault."""
    p = Path(path).resolve()
    try:
        return str(p.relative_to(VAULT.resolve()))
    except ValueError:
        return str(p)


def wikilink(path, alias):
    target = rel(path)
    target = target[:-3] if target.endswith(".md") else target
    return f"[[{target}|{alias}]]"


def opt(args, name, default=None):
    if name in args:
        idx = args.index(name)
        if idx + 1 < len(args):
            return args[idx + 1]
    return default


class Ticket:
    """A tracker ticket cited as a source: its number, status and type, read from its properties."""

    def __init__(self, path, note=None):
        """`note`: the already-parsed note (anything with props and body), to spare a second read."""
        self.path = Path(path)
        self.num = int(re.match(r"(\d+)", self.path.name).group(1))
        props, body = (note.props, note.body) if note else split_fm(self.path.read_text(encoding="utf-8"))[:2]
        self.title = str(props.get("title") or (re.search(r"^# (.+)$", body, re.M) or [None, self.path.stem])[1]).strip()
        raw = str(props.get("status") or "open").lower()
        self.status = TICKET_STATUS.get(raw, raw)
        self.type = str(props.get("type") or "task").lower()

    @property
    def id(self):
        return f"{self.num:03d}"

    def link(self, alias=None):
        return wikilink(self.path, alias or self.id)


class _Map:
    def __init__(self, folder):
        self.folder = folder

    def ticket(self, num):
        n = int(num)
        for p in sorted((self.folder / "issues").glob("*.md")):
            m = re.match(r"(\d+)[- ]", p.name)
            if m and int(m.group(1)) == n:
                return Ticket(p)
        raise SystemExit(f"wiki: no ticket {n:03d} in {rel(self.folder)}")


def load(name):
    """A tracker map by its folder under wayfinder/ (`monorepo/explosion-step`) or a path."""
    p = Path(name).expanduser()
    for folder in (p, WAYFINDER / name, WAYFINDER / name.replace("-", "/", 1)):
        if (folder / "map.md").exists():
            return _Map(folder)
    for f in WAYFINDER.glob("**/map.md"):
        if str(f.parent.relative_to(WAYFINDER)).replace("/", "-") == name or f.parent.name == name:
            return _Map(f.parent)
    raise SystemExit(f"wiki: no map '{name}' under {WAYFINDER}")
