"""wikibrain dump / import: keep chosen wiki projects in step with a shared git clone.

The vault stays whole and primary. Only `wiki/<p>/` and `wiki/raw/<p>/` of the listed projects
cross. The vault links with full-path wikilinks, the clone with links GitHub renders: a body link
relative to its note, a list property the repo-root path. Dump converts on the way out and drops
the vault-only properties (`sb.vaultOnly`, default `tickets`); import converts back and keeps the
vault copy's vault-only properties. Aliases are the targets' headings (`wiki check` holds them
there), so a round trip gives back every note; a note with no link to convert crosses byte for
byte. The clone remembers its projects, excluded topics, base branch, vault-only properties and
extra leak patterns in its git config (`sb.projects`, `sb.exclude`, `sb.base`, `sb.vaultOnly`,
`sb.leak`), and the base commit last imported as `refs/sb/last-sync`.

  dump <clone> [--projects a,b] [--exclude p/topic,…] [--base main]
      copies the vault's changes onto a new branch `wiki-dump/<date>` cut from the base, refreshes
      the clone's index and log and commits there; never touches the base, never pushes
  import <clone>
      fast-forwards the base, copies what changed on it since the last import into the vault,
      lists every note changed on both sides instead of overwriting it, then reindexes the vault
"""
import os
import posixpath
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from urllib.parse import unquote

import vault as sb
from wikibrain import LINK, MD_FULL, REF_KEYS, SCHEME, outside_code

MARK = "refs/sb/last-sync"
LEAKS = [r"/Users/", r"/home/[a-z]", r"obsidian://", r"\[\[wayfinder/"]
WIKI = Path(__file__).with_name("wikibrain.py")


def die(msg):
    sys.exit(f"wikibrain: {msg}")


def git(clone, *args, ok=True):
    r = subprocess.run(["git", "-C", str(clone), *args], capture_output=True, text=True)
    if ok and r.returncode:
        die(f"git {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
    return r


def git_bytes(clone, rev, path):
    r = subprocess.run(["git", "-C", str(clone), "show", f"{rev}:{path}"], capture_output=True)
    return r.stdout if r.returncode == 0 else None


def setting(clone, key, given, default=""):
    """The flag's value, remembered in the clone's git config; else the remembered one."""
    if given is not None:
        git(clone, "config", f"sb.{key}", given)
        return given
    r = git(clone, "config", "--get", f"sb.{key}", ok=False)
    return r.stdout.strip() if r.returncode == 0 else default


def split(value):
    return [v.strip().strip("/") for v in value.split(",") if v.strip()]


class Scope:
    def __init__(self, clone, args):
        self.clone = Path(clone).expanduser().resolve()
        if not (self.clone / ".git").exists():
            die(f"{self.clone} is not a git clone")
        self.projects = split(setting(self.clone, "projects", sb.opt(args, "--projects")))
        if not self.projects:
            die("no projects: pass --projects monorepo (remembered afterwards)")
        self.exclude = split(setting(self.clone, "exclude", sb.opt(args, "--exclude")))
        self.base = setting(self.clone, "base", sb.opt(args, "--base"), "main")
        self.vault_only = set(split(setting(self.clone, "vaultOnly", None, "tickets")))
        extra = git(self.clone, "config", "--get-all", "sb.leak", ok=False).stdout.split("\n")
        self.leaks = [re.compile(p) for p in LEAKS + [e for e in extra if e.strip()]]
        self.roots = [f"wiki/{p}" for p in self.projects] + [f"wiki/raw/{p}" for p in self.projects]

    def covers(self, rel):
        parts = rel.split("/")
        if parts[:2] == ["wiki", "raw"]:
            project, rest = parts[2:3], parts[3:]
        else:
            project, rest = parts[1:2], parts[2:]
        if not project or project[0] not in self.projects or not rest:
            return False
        topic = f"{project[0]}/{rest[0]}" if len(rest) > 1 else None
        return topic not in self.exclude and not any(p.startswith(".") for p in parts)

    def files(self, root):
        out = {}
        for r in self.roots:
            base = Path(root) / r
            if base.is_dir():
                for p in base.rglob("*"):
                    rel = p.relative_to(root).as_posix()
                    if p.is_file() and self.covers(rel):
                        out[rel] = p
        return out

    def leaked(self, texts):
        hits = []
        for rel, text in texts.items():
            for i, line in enumerate(text.splitlines(), 1):
                if any(rx.search(line) for rx in self.leaks):
                    hits.append(f"{rel}:{i}: {line.strip()[:100]}")
        return hits


# ---- the two link forms ----------------------------------------------------
# A note is text (bytes decoded with surrogateescape, so any byte survives). Frontmatter is edited
# line by line, never re-serialised, so a property that needs no conversion keeps its spelling.

def text(raw):
    return raw.decode("utf-8", "surrogateescape")


def data(text):
    return text.encode("utf-8", "surrogateescape")


def blocks(text):
    """([key, lines] per property, the text after the frontmatter); (None, text) without one."""
    if text.startswith("---\n---\n"):
        return [], text[4:]
    end = text.find("\n---\n", 4) if text.startswith("---\n") else -1
    if end < 0:
        return None, text
    out = []
    for line in text[4:end].split("\n"):
        m = re.match(r"([A-Za-z_][\w-]*):", line)
        if m or not out:
            out.append([m and m.group(1), [line]])
        else:
            out[-1][1].append(line)
    return out, text[end + 1:]


def joined(fm, rest):
    return rest if fm is None else "---\n" + "".join(line + "\n" for _, lines in fm for line in lines) + rest


def strip(text, only):
    """The note without its vault-only properties."""
    fm, rest = blocks(text)
    return joined(fm and [b for b in fm if b[0] not in only], rest)


def restore(text, mine, only):
    """`text` with the vault copy's vault-only properties, each back before the property it preceded."""
    kept, _ = blocks(mine) if mine is not None else (None, "")
    keep = [(i, b) for i, b in enumerate(kept or []) if b[0] in only]
    if not keep:
        return text
    fm, rest = blocks(text)
    fm, rest = ([], "---\n" + rest) if fm is None else ([b for b in fm if b[0] not in only], rest)
    for i, b in keep:
        after = [k for k, _ in kept[i + 1:] if k not in only]
        fm.insert(next((j for k in after for j, x in enumerate(fm) if x[0] == k), len(fm)), b)
    return joined(fm, rest)


def ref_props(fm, convert):
    """Each value of a link-list property (`sources`, `related`, …) through `convert`."""
    for key, lines in fm or []:
        if key in REF_KEYS:
            for i, line in enumerate(lines):
                m = re.match(r"(\s+-\s*|[\w-]+:\s*)(\S.*)$", line)
                new = m and convert(sb.unquote(m.group(2)))
                if new is not None:
                    lines[i] = m.group(1) + sb.scalar(new)


def heading(note, stem):
    """The title of a note's text (`sb.title`), or `stem` when there is no note."""
    if note is None:
        return stem
    props, body, _ = sb.split_fm(note)
    return sb.title(props, body, stem)


def source_text(rel):
    """A raw note's body is its source's own text, links to the source's repo included: never converted."""
    return rel.startswith("wiki/raw/")


def to_repo(note, rel):
    """The clone's form: body links relative to `rel`, link properties repo-root paths."""
    def prop(v):
        m = LINK.fullmatch(v.strip())
        if m and not m.group(1) and not m.group(3) and m.group(2).strip():
            return m.group(2).strip() + ".md"
        return None

    def link(m):
        embed, target, anchor, alias = m.group(1), m.group(2).strip(), m.group(3), m.group(4)
        if "/" not in target or target.endswith("\\") or (sb.VAULT / target).is_file():
            return m.group(0)  # a bare name, a pipe escaped in a table, a file that is no note: left as written
        path, p = target + ".md", sb.VAULT / (target + ".md")
        if alias is None and not embed:
            alias = heading(text(p.read_bytes()) if p.is_file() else None, Path(target).name)
        return embed + sb.md_link(path, alias or "", rel, (anchor or "")[1:])

    fm, rest = blocks(note)
    ref_props(fm, prop)
    return joined(fm, rest if source_text(rel) else outside_code(rest, lambda seg: LINK.sub(link, seg), keep_code=True))


def to_vault(text, rel, title):
    """The vault's form; `title(path)` is the heading a property's wikilink takes as its alias."""
    def prop(v):
        if v.startswith("[") or SCHEME.match(v) or not v.endswith(".md"):
            return None
        return f"[[{v[:-3]}|{title(v)}]]"

    def link(m):
        embed, label, href = m.groups()
        path, _, anchor = href.partition("#")
        path = unquote(path)
        if SCHEME.match(href) or path.startswith("/") or not path.endswith(".md"):
            return m.group(0)
        target = posixpath.normpath(posixpath.join(posixpath.dirname(rel), path))
        if target.startswith("../"):
            return m.group(0)
        return f"{embed}[[{target[:-3]}" + (f"#{unquote(anchor)}" if anchor else "") + (f"|{label}" if label else "") + "]]"

    fm, rest = blocks(text)
    ref_props(fm, prop)
    return joined(fm, rest if source_text(rel) else outside_code(rest, lambda seg: MD_FULL.sub(link, seg), keep_code=True))


def last_sync(s):
    r = git(s.clone, "rev-parse", "--verify", "--quiet", MARK, ok=False)
    return r.stdout.strip() or None


def base_rev(s):
    r = git(s.clone, "rev-parse", "--verify", "--quiet", s.base, ok=False)
    return r.stdout.strip() or None


def clean(s):
    if git(s.clone, "status", "--porcelain", "--untracked-files=no").stdout.strip() or \
            git(s.clone, "status", "--porcelain", "--", "wiki").stdout.strip():
        die(f"{s.clone} has uncommitted changes: commit or discard them first")


def run_wiki(vault, *args):
    env = {**os.environ, "SB_VAULT": str(vault)}
    return subprocess.run([sys.executable, str(WIKI), *args], capture_output=True, text=True, env=env)


def cmd_dump(args):
    if not args:
        die("dump <clone> [--projects a,b] [--exclude p/topic,…] [--base main]")
    s = Scope(args[0], args[1:])
    clean(s)
    last, base = last_sync(s), base_rev(s)
    if last and base and base != last:
        die(f"{s.base} moved since the last import: run `wikibrain import {s.clone}` first")
    vault_files = s.files(sb.VAULT)
    gated = {rel: text(p.read_bytes()) for rel, p in vault_files.items()}
    gated = {rel: strip(t, s.vault_only) if rel.endswith(".md") else t for rel, t in gated.items()}
    out = {rel: data(to_repo(t, rel)) if rel.endswith(".md") else vault_files[rel].read_bytes()
           for rel, t in gated.items()}
    hits = s.leaked(gated) or s.leaked({rel: text(b) for rel, b in out.items()})  # an alias can bring a heading
    if hits:
        die("leak gate: these lines must not leave the vault\n  " + "\n  ".join(hits))
    start = base or git(s.clone, "rev-parse", "--verify", "--quiet", "HEAD", ok=False).stdout.strip()
    branch = f"wiki-dump/{date.today().isoformat()}"
    n = 2
    while git(s.clone, "rev-parse", "--verify", "--quiet", branch, ok=False).returncode == 0:
        branch, n = f"wiki-dump/{date.today().isoformat()}-{n}", n + 1
    git(s.clone, "switch", "-c", branch, *([start] if start else []))
    clone_files = s.files(s.clone)
    changed = [rel for rel in vault_files if rel not in clone_files or clone_files[rel].read_bytes() != out[rel]]
    removed = [rel for rel in clone_files if rel not in vault_files] if last else []
    for rel in changed:
        dst = s.clone / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(out[rel])
    for rel in removed:
        (s.clone / rel).unlink()
    if not changed and not removed:
        git(s.clone, "switch", "-")
        git(s.clone, "branch", "-D", branch)
        print("nothing to dump: the clone already holds the vault's notes")
        return
    run_wiki(s.clone, "wiki", "init")
    run_wiki(s.clone, "wiki", "index", "--write")
    log = s.clone / "wiki" / "log.md"
    with log.open("a", encoding="utf-8") as f:
        f.write(f"\n## [{date.today().isoformat()}] dump | {', '.join(s.projects)}\n"
                f"- {len(changed)} changed, {len(removed)} removed\n")
    title = f"wiki dump: {', '.join(s.projects)} ({len(changed)} changed, {len(removed)} removed)"
    body = pr_body(s, start, changed, removed, out)
    git(s.clone, "add", "-A", "wiki")
    git(s.clone, "commit", "-q", "-m", title)
    body_file = s.clone / ".git" / "sb-dump-pr.md"
    body_file.write_text(body, encoding="utf-8")
    print(f"dumped {len(changed)} changed and {len(removed)} removed notes onto {branch} in {s.clone}")
    print(f"next: git -C '{s.clone}' push -u origin {branch}")
    print(f"      gh pr create -R \"$(git -C '{s.clone}' remote get-url origin)\" --base {s.base} --head {branch} "
          f"--title '{title}' --body-file '{body_file}'")


def describe(raw):
    """(kind, title, summary or source, props, body) of a note's bytes."""
    props, body, _ = sb.split_fm(raw.decode("utf-8", errors="replace"))
    m = re.search(r"^# (.+)$", body, re.M)
    title = str(props.get("title") or "") if props.get("wiki") == "raw" else ""
    title = title or (m.group(1).strip() if m else str(props.get("title") or ""))
    return str(props.get("wiki", "")), title, str(props.get("summary") or props.get("source") or ""), props, body


def pr_body(s, start, changed, removed, out):
    """The pull request's description: what a reviewer reads before the files; `out`: the notes as dumped."""
    rows = {"article": [], "raw": [], "other": []}
    for rel in sorted(changed):
        kind, title, line, props, body = describe(out[rel])
        old = git_bytes(s.clone, start, rel) if start else None
        group = "article" if kind in ("article", "synthesis") else "raw" if kind == "raw" else "other"
        topic = rel.split("/")[-2]
        if old is None:
            rows[group].append(f"| 🆕 | **{title}**: {line} | {topic} | new |")
            continue
        _, _, _, oprops, obody = describe(old)
        what = [k for k in sorted(set(props) | set(oprops)) if str(props.get(k)) != str(oprops.get(k))]
        if body.strip() != obody.strip():
            what.insert(0, "text")
        rows[group].append(f"| 💬 | **{title}** | {topic} | {', '.join(what) or 'whitespace'} |")
    out = [f"Wiki dump of **{', '.join(s.projects)}** from the maintainer's notes: {len(changed)} changed, "
           f"{len(removed)} removed. Copied by `wikibrain dump` with the links converted to relative links and "
           f"the vault-only properties ({', '.join(sorted(s.vault_only)) or 'none'}) dropped; nothing else was rewritten.", ""]
    head = "| | note | topic | what changed |\n| --- | --- | --- | --- |"
    for group, name in (("article", "Articles"), ("raw", "Sources (raw notes)"), ("other", "Topics and other notes")):
        if not rows[group]:
            continue
        table = "\n".join([head, *rows[group]])
        out.append(f"### {name} ({len(rows[group])})\n")
        out.append(table if len(rows[group]) <= 12 else f"<details><summary>{len(rows[group])} notes</summary>\n\n{table}\n\n</details>")
        out.append("")
    if removed:
        out.append(f"### Removed ({len(removed)})\n")
        out += [f"- `{rel}`" for rel in sorted(removed)] + [""]
    out += ["### Reviewing", "",
            "- New or rewritten articles: read the Overview; every number and quote must be in a raw note it cites.",
            "- Raw notes are sources: their text is never edited, only their properties (provenance: `repo`, `commit`, `ref`, `paths`); check those point at real code.",
            "- CI runs `wiki check` (format and links)."]
    return "\n".join(out) + "\n"


def cmd_import(args):
    if not args:
        die("import <clone>")
    s = Scope(args[0], args[1:])
    clean(s)
    if not base_rev(s):
        die(f"{s.clone} has no {s.base} yet: nothing to import")
    git(s.clone, "switch", s.base)
    if git(s.clone, "rev-parse", "--abbrev-ref", "@{u}", ok=False).returncode == 0:
        git(s.clone, "pull", "--ff-only", "-q")
    head, last = base_rev(s), last_sync(s)
    if last == head:
        print("nothing to import: the vault already has every merged change")
        return
    if last:
        out = git(s.clone, "diff", "--name-status", "--no-renames", last, head, "--", *s.roots).stdout
        rows = [line.split("\t", 1) for line in out.splitlines() if line.strip()]
    else:
        out = git(s.clone, "ls-tree", "-r", "--name-only", head, "--", *s.roots).stdout
        rows = [["A", line] for line in out.splitlines() if line.strip()]
    titles = {}

    def title(path):
        """A note's heading as merged on the base, else as in the vault."""
        if path not in titles:
            raw = git_bytes(s.clone, head, path)
            raw = raw if raw is not None else (sb.VAULT / path).read_bytes() if (sb.VAULT / path).is_file() else None
            titles[path] = heading(None if raw is None else text(raw), Path(path).stem)
        return titles[path]

    written, deleted, conflicts = [], [], []
    for status, rel in rows:
        if not s.covers(rel):
            continue
        vault = sb.VAULT / rel
        mine = vault.read_bytes() if vault.exists() else None
        before = git_bytes(s.clone, last, rel) if last else None
        theirs = None if status == "D" else git_bytes(s.clone, head, rel)
        md = rel.endswith(".md")

        def repo(raw):
            """Compared in the clone's form, vault-only properties never compared; an old wikilink-form
            clone note compares alike."""
            return data(to_repo(strip(text(raw), s.vault_only), rel)) if md and raw is not None else raw

        if repo(mine) == repo(theirs):
            continue
        if mine is None or repo(mine) == repo(before):
            if theirs is None:
                vault.unlink(missing_ok=True)
                deleted.append(rel)
            else:
                vault.parent.mkdir(parents=True, exist_ok=True)
                vault.write_bytes(data(restore(to_vault(text(theirs), rel, title), mine and text(mine), s.vault_only))
                                  if md else theirs)
                written.append(rel)
        else:
            conflicts.append(rel)
    for rel in written:
        print(f"  imported {rel}")
    for rel in deleted:
        print(f"  deleted {rel}")
    if conflicts:
        print("changed on both sides since the last sync, left as they are in the vault:")
        for rel in conflicts:
            print(f"  ⚠️ {rel}  (theirs: git -C '{s.clone}' show {s.base}:{rel})")
        print("settle each one in the vault, then run import again")
    else:
        git(s.clone, "update-ref", MARK, head)
    if written or deleted:
        run_wiki(sb.VAULT, "wiki", "index", "--write")
        tail = run_wiki(sb.VAULT, "wiki", "check").stdout.strip().splitlines()
        if tail:
            print(tail[-1])
    print(f"{len(written)} imported, {len(deleted)} deleted, {len(conflicts)} conflicts")
    if conflicts:
        sys.exit(1)


COMMANDS = {"dump": cmd_dump, "import": cmd_import}
