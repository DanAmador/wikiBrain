"""wikibrain: an LLM wiki's tools, `reference/wiki.md` made executable. Run as `wikibrain.py <command>`
(a leading `wiki` is accepted, so the sb skill's `sbmap wiki <command>` delegates here unchanged).

  read
    wikibrain.py index [--project P] [--write]
                                            every project, topic and article, one line each; --project
                                            narrows to P and general; --write restamps index.md
    wikibrain.py find <terms…> [--raw] [--project P] [--limit N]
                                            notes matching any term, scored: title/aliases 3, summary 2, body 1
    wikibrain.py show <note> [--full]      digest: properties, Overview, headings, Outdated/Disputed callouts
    wikibrain.py link <note>               the wikilink to paste into prose
    wikibrain.py backlog [--project P] [--limit N]
                                            raw notes no article cites and the log has not marked no-material
  write
    wikibrain.py init                      creates whatever of the layout is missing; never overwrites
    wikibrain.py raw <project>/<topic> --title "…" --source "…" [--author "…"] [--published YYYY-MM-DD|Unknown]
                          [--repo-root <clone> [--rev <branch|sha>] [--paths a,b] [--symbols a,b]]
                          --from <file|->   keeps a source as a raw note; --repo-root stamps the repo,
                                            commit and ref it was read at (HEAD, or --rev)
    wikibrain.py new <project>/<topic>/<slug> --title "…" --type concept|entity|synthesis --summary "…"
                          --sources <refs> [--related <refs>] [--aliases "a, b"] [--tags "a, b"] [--about "…"]
    wikibrain.py set <note> key=value … [key+=<refs>] [key-=<refs>]
    wikibrain.py log <learn|ask|tend> --subject "…" [--disposition "…"] [--raw <refs>] [--updated <refs>]
    wikibrain.py check [--fix]             lint; exits non-zero on any format or link problem
    wikibrain.py verify [--repo-root <clone>] [--project P] [--base origin/main] [--json]
                                            each article's claims checked against the repo's git:
                                            current, drifted, broken, orphaned or unanchored
    wikibrain.py migrate <project> [topic…] [--write]
                                            topics from before projects (wiki/<topic>/) move under
                                            <project>, links in wiki/ and wayfinder/ follow; a dry run
                                            unless --write
  sync (a shared git clone of chosen projects; its links relative, the vault's wikilinks)
    wikibrain.py dump <clone> [--projects a,b] [--exclude p/topic] [--base main]
                                            the vault's changes onto a new wiki-dump/<date> branch
    wikibrain.py import <clone>            merged changes from the base branch into the vault

<project> is a repo's folder name under wayfinder/ (`monorepo`), or `general` for knowledge that
holds outside any one repo. <note> is a vault path, `<project>/<topic>/<slug>` or a wikilink. <refs> are comma-separated vault paths,
wikilinks, or `<map>#<NNN>` for a ticket; each is written in the store's form (`sb.links`): a full-path
wikilink, or in a relative store (a sync clone) the repo-root path.
"""
import copy
import functools
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from urllib.parse import unquote

import vault as sb

WIKI_KEYS = ["wiki", "type", "project", "status", "title", "source", "author", "published", "created", "summary",
             "updated", "reviewed", "verified", "archived", "sources", "related", "supersedes", "superseded_by",
             "disputes", "aliases", "tags", "repo", "commit", "ref", "paths", "symbols"]
PROVENANCE = ("repo", "commit", "ref", "paths", "symbols")
TEXT_LISTS = ("aliases", "tags", "paths", "symbols")
SHA = re.compile(r"[0-9a-f]{40}")
REPO = re.compile(r"[\w.-]+/[\w.-]+")
KINDS = {"article", "synthesis", "raw", "topic", "index", "log"}
TYPES = {"article": {"concept", "entity"}, "synthesis": {"synthesis"}, "raw": {"source"},
         "topic": {"topic"}}
STATUSES = ("current", "outdated", "disputed")
REF_KEYS = ("sources", "related", "supersedes", "superseded_by", "disputes")
EDGE_KEYS = REF_KEYS + ("tickets", "paths")
RECIPROCAL = {"disputes": "disputes", "supersedes": "superseded_by", "superseded_by": "supersedes"}
DATE_KEYS = ("updated", "reviewed", "archived", "created", "published")
ROOT_FILES = ("index.md", "log.md", "README.md")
GENERAL = "general"
INDEX_START, INDEX_END = "%% sb:index:start %%", "%% sb:index:end %%"
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
DATED = re.compile(r"\d+-")
DISPUTED = re.compile(r"^> \[!question\] Disputed", re.M)
OUTDATED = re.compile(r"^> \[!warning\] Outdated\b(.*)$", re.M)
LINK = re.compile(r"(!?)\[\[([^\]|#]*)(#[^\]|]*)?(?:\|([^\]]*))?\]\]")
MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)")
MD_FULL = re.compile(r"(!?)\[([^\]]*)\]\(([^)\s]+)\)")
SCHEME = re.compile(r"[a-z][a-z0-9+.-]*:", re.I)
CACHE = Path(os.environ.get("WIKIBRAIN_CACHE") or Path.home() / ".cache" / "wikibrain")


def wiki_dir():
    return sb.VAULT / "wiki"


def today():
    return date.today().isoformat()


def die(msg):
    sys.exit(f"wikibrain: {msg}")


# ---- the graph cache ------------------------------------------------------
# One JSON file per wiki root in CACHE: for each note read, its properties, body and edges, stamped
# with the file's mtime and size. A read stats the file and parses it only when the stamp moved.
# ponytail: a same-size edit inside the filesystem's timestamp tick goes unseen; delete the file to rebuild.

_graph, _dirty = None, False


def edges(props, body, rel):
    """[[kind, target]] a note points at: its list properties, then its body links, wikilinks and
    relative links alike, each target a vault-relative path without `.md` (a `paths` entry as written)."""
    out = []
    for k in EDGE_KEYS:
        v = props.get(k) or []
        out += [(k, str(e) if k == "paths" else entry_key(e)) for e in (v if isinstance(v, list) else [v])]
    out += [("link", entry_key(m.group(2))) for m in LINK.finditer(body) if m.group(2).strip()]
    for t in MD_LINK.findall(body):  # ponytail: links inside code fences count too
        t = unquote(re.split(r"[#?]", t)[0])
        if t and not SCHEME.match(t):
            out.append(("link", entry_key(os.path.normpath(os.path.join(os.path.dirname(rel), t)))))
    return [list(e) for e in dict.fromkeys(out)]


def cache_file():
    return CACHE / (hashlib.sha1(str(sb.VAULT.resolve()).encode()).hexdigest()[:16] + ".json")


def graph_entry(path):
    global _graph, _dirty
    if _graph is None:
        try:
            d = json.loads(cache_file().read_text(encoding="utf-8"))
            _graph = d["notes"] if d["v"] == 1 and isinstance(d["notes"], dict) else {}
        except (OSError, ValueError, KeyError, TypeError):
            _graph = {}
    st = path.stat()
    stamp, e = [st.st_mtime_ns, st.st_size], _graph.get(str(path))
    if isinstance(e, dict) and e.get("stamp") == stamp and {"props", "body", "fm", "edges"} <= e.keys():
        return e
    props, body, fm = sb.split_fm(path.read_text(encoding="utf-8"))
    _graph[str(path)] = e = {"stamp": stamp, "props": props, "body": body, "fm": fm,
                             "edges": edges(props, body, sb.rel(path))}
    _dirty = True
    return e


def save_graph():
    if _dirty:
        try:
            CACHE.mkdir(parents=True, exist_ok=True)
            live = {k: v for k, v in _graph.items() if os.path.exists(k)}
            sb.write_atomic(cache_file(), json.dumps({"v": 1, "notes": live}))
        except OSError:
            pass  # ponytail: the cache is best-effort; an unwritable one costs a re-read next time


# ---- notes ----------------------------------------------------------------

class Note:
    def __init__(self, path):
        self.path = Path(path)
        e = graph_entry(self.path)
        self.props, self.body, self.has_fm, self.edges = copy.deepcopy(e["props"]), e["body"], e["fm"], e["edges"]
        self.kind = str(self.props.get("wiki", ""))

    @property
    def title(self):
        return sb.title(self.props, self.body, self.path.stem)

    @property
    def rel(self):
        return sb.rel(self.path)

    def refs(self, key):
        v = self.props.get(key) or []
        return v if isinstance(v, list) else [v]

    def link(self, here=None):
        """The store's link to this note, for a property; `here`: the file a body link is written into."""
        return sb.wikilink(self.path, self.title, here)

    def save(self, props=None, body=None):
        if props is not None:
            self.props = props
        if body is not None:
            self.body = body
        sb.write_atomic(self.path, sb.dump_fm(self.props, WIKI_KEYS) + self.body.lstrip("\n"))


def target_of(target):
    """The file a link target names (with or without `.md`), or None."""
    target = target.strip().strip("/")
    if not target:
        return None
    p = sb.VAULT / target
    if p.is_file():
        return p
    q = p.with_name(p.name + ".md")
    return q if q.is_file() else None


def ticket(path):
    return sb.Ticket(path, Note(path))


def link_path(ref):
    """The file a `[[target|alias]]` names, or None."""
    m = LINK.fullmatch(str(ref).strip())
    return target_of(m.group(2)) if m else None


def note_path(arg):
    """A note under wiki/: a vault path, `<topic>/<slug>`, or a wikilink."""
    arg = str(arg).strip()
    p = link_path(arg) if arg.startswith("[[") else None
    if p is None:
        arg = arg.removeprefix(str(sb.VAULT) + "/")
        p = target_of(arg) or target_of("wiki/" + arg)
    if p is None:
        die(f"'{arg}' names no note")
    return p


def resolve_ref(ref, here=None):
    """One <ref> -> (path, the store's link to it; a body link from `here`). Exits on a ref that names no note."""
    ref = ref.strip()
    m = re.fullmatch(r"(.+)#(\d+)", ref)
    if m and not ref.startswith("[["):
        t = sb.load(m.group(1)).ticket(m.group(2))
        return t.path, t.link("#" + t.id, here)
    if ref.startswith("[["):
        p = link_path(ref)
    else:
        ref = ref.removeprefix(str(sb.VAULT) + "/")
        p = target_of(ref) or target_of("wiki/" + ref)
    if p is None:
        die(f"'{ref}' names no note")
    if "/wayfinder/" in "/" + sb.rel(p) and re.match(r"\d+[- ]", p.name) and p.parent.name == "issues":
        t = ticket(p)
        return p, t.link("#" + t.id, here)
    return p, Note(p).link(here)


def split_refs(s):
    return [r.strip() for r in re.findall(r"\[\[.*?\]\]|[^,]+", s or "") if r.strip()]


def wiki_notes():
    """Every note under wiki/ but raw/, index, log and README."""
    w = wiki_dir()
    if not w.is_dir():
        return []
    return [Note(p) for p in sorted(w.rglob("*.md"))
            if p.relative_to(w).parts[0] != "raw" and p.relative_to(w).as_posix() not in ROOT_FILES]


def articles():
    return [n for n in wiki_notes() if n.kind in ("article", "synthesis")]


def is_folder_note(p):
    return p.stem == p.parent.name and p.parent.parent != wiki_dir() / "raw"


def slug_taken(slug):
    """Article and source slugs are unique across the wiki; a topic's folder note is named after it."""
    w = wiki_dir()
    return w.is_dir() and any(p.stem == slug for p in w.rglob("*.md")
                              if p.relative_to(w).as_posix() not in ROOT_FILES and not is_folder_note(p))


def slugify(title):
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    m = re.match(r"((?:\d+-)+)(.+)", s)  # a leading date or number moves to the end
    if m:
        s = m.group(2) + "-" + m.group(1).strip("-")
    return s[:60].rstrip("-")


# ---- raw classes ----------------------------------------------------------

def raw_class(path):
    """'raw', 'clipping', 'research', 'ticket', or None for a note that is not a source."""
    parts = Path(sb.rel(path)).parts
    if parts[:2] == ("wiki", "raw"):
        return "raw"
    if parts[:1] == ("Clippings",):
        return "clipping"
    if parts[:1] == ("wayfinder",) and "research" in parts[:-1]:
        return "research"
    if parts[:1] == ("wayfinder",) and len(parts) > 1 and parts[-2] == "issues" and re.match(r"\d+[- ]", parts[-1]):
        return "ticket"
    return None


def source_problem(kind, path):
    """Why `path` may not be a `sources` entry of a note of `kind`, or None."""
    cls = raw_class(path)
    if cls is None:
        if kind == "synthesis" and Note(path).kind == "article":
            return None
        return f"{sb.rel(path)[:-3]} is not a raw note" + (" or an article" if kind == "synthesis" else "")
    if cls == "ticket" and ticket(path).status != "resolved":
        return f"{sb.rel(path)[:-3]} is a ticket that is not resolved"
    return None


def ref_links(refs_arg, kind=None, key="sources"):
    out = []
    for ref in split_refs(refs_arg):
        p, link = resolve_ref(ref)
        if key == "sources" and kind:
            why = source_problem(kind, p)
            if why:
                die(why)
        if link not in out:
            out.append(link)
    return out


# ---- the index ------------------------------------------------------------

def check_name(what, name):
    if name == "raw" or not SLUG.fullmatch(name or ""):
        die(f"{what} '{name}' must be kebab-case and not 'raw'")


def is_old_topic(d):
    """A topic folder straight under wiki/, from before projects."""
    return d.parent == wiki_dir() and (d / f"{d.name}.md").exists()


def old_raw(d):
    """A source folder straight under wiki/raw/, from before projects."""
    return d.parent == wiki_dir() / "raw" and any(d.glob("*.md"))


def projects(only=None):
    """Project folders, general first; with `only`, that project and general."""
    w = wiki_dir()
    found = [d.name for d in w.iterdir() if d.is_dir() and d.name != "raw" and not is_old_topic(d)] if w.is_dir() else []
    if only:
        found = [p for p in found if p in (only, GENERAL)]
    return sorted(found, key=lambda p: (p != GENERAL, p))


def topics(project):
    d = wiki_dir() / project
    return sorted(t.name for t in d.iterdir() if t.is_dir()) if d.is_dir() else []


def base_tags(kind_tag, project, topic):
    """The tags every wiki note carries. Semantra makes each one a `tag:<name>` node the note is
    `tagged` to, so notes meet through shared tags; no tag notes are written."""
    return [kind_tag, f"project/{project}", f"topic/{topic}"]


def retag(props, project, topic):
    """The note's tags with its project and topic tags made current, the owner's own kept."""
    tags = [t for t in props.get("tags") or [] if not t.startswith(("project/", "topic/"))]
    return tags + [t for t in base_tags(f"wiki/{props.get('type')}", project, topic) if t not in tags]


def project_of(path):
    """The project a note belongs to: its wiki folder, or its map's repo; None for a clipping."""
    parts = Path(sb.rel(path)).parts
    if parts[:2] == ("wiki", "raw"):
        return parts[2] if len(parts) > 3 else None
    if parts[:1] in (("wiki",), ("wayfinder",)) and len(parts) > 2:
        return parts[1]
    return None


def in_scope(path, project):
    return project is None or project_of(path) in (project, GENERAL, None)


def esc(s):
    return str(s).replace("|", "\\|")


def topic_rows(project, topic):
    notes = [n for n in articles() if n.path.parent == wiki_dir() / project / topic]
    return sorted(notes, key=lambda n: (n.kind == "synthesis", n.title.lower()))


def folder_note(project, topic):
    p = wiki_dir() / project / topic / f"{topic}.md"
    return Note(p) if p.exists() else None


def index_block():
    lines = [INDEX_START, ""]
    for project in projects():
        lines += [f"## {project}", ""]
        for t in topics(project):
            fn = folder_note(project, t)
            lines += [f"### {t}", ""]
            if fn and fn.props.get("summary"):
                lines += [str(fn.props["summary"]), ""]
            lines += table(topic_rows(project, t))
    lines += ["*Generated by wikibrain from the articles' properties; edit the articles, not this block.*",
              INDEX_END]
    return "\n".join(lines)


def table(rows):
    if not rows:
        return []
    lines = ["| Article | Type | Summary | Updated |", "|---|---|---|---|"]
    for n in rows:
        when = n.props.get("archived") if n.kind == "synthesis" else n.props.get("updated")
        lines.append(f"| {esc(n.link(wiki_dir() / 'index.md'))} | {n.props.get('type', '')} | "
                     f"{esc(n.props.get('summary', ''))} | {when or ''} |")
    return lines + [""]


def stamped_index():
    """index.md's text with a fresh block, or None when there is no index.md."""
    p = wiki_dir() / "index.md"
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8")
    block = index_block()
    if INDEX_START in text and INDEX_END in text:
        return text[:text.index(INDEX_START)] + block + text[text.index(INDEX_END) + len(INDEX_END):]
    return text.rstrip("\n") + "\n\n" + block + "\n"


def write_index():
    text = stamped_index()
    if text is not None:
        sb.write_atomic(wiki_dir() / "index.md", text)


def cmd_index(args):
    if not wiki_dir().is_dir():
        print("no wiki/ yet: `wikibrain init`")
        return
    if "--write" in args:
        write_index()
        print(f"wrote the index into {wiki_dir() / 'index.md'}")
        return
    shown = projects(sb.opt(args, "--project"))
    for project in shown:
        print(f"# {project}")
        for t in topics(project):
            fn = folder_note(project, t)
            print(f"## {t}" + (f": {fn.props.get('summary')}" if fn and fn.props.get("summary") else ""))
            for n in topic_rows(project, t):
                status = n.props.get("status") or n.kind
                print(f"  {n.rel[:-3]} · {n.props.get('type', '')} · {status} · {n.props.get('summary', '')}")
    if not shown:
        print("(the wiki is empty)")
    if any(is_old_topic(d) for d in wiki_dir().iterdir() if d.is_dir()):
        print("⚠️ topics from before projects sit straight under wiki/: `wikibrain migrate <project>`")


# ---- init -----------------------------------------------------------------

INDEX_MD = f"""---
wiki: index
---
# Wiki index

Every topic and article in the vault's wiki, from their properties. Agents read it with
`wikibrain index`.

{INDEX_START}
{INDEX_END}

![[wiki/wiki.base#Needs attention]]
"""

LOG_MD = """---
wiki: log
---
# Wiki log

Append-only, newest last, written by `wikibrain log`.
"""

README_MD = """# The wiki

Compiled knowledge: articles under `<project>/<topic>/`, their sources under `raw/<project>/<topic>/`.
A project is a repo's folder name under `wayfinder/`, or `general`. Start at `index.md`.
The format and the commands: the wikibrain skill's `reference/wiki.md`.
"""

WIKI_BASE = """filters:
  and:
    - file.inFolder("wiki")
    - 'wiki == "article" || wiki == "synthesis"'
properties:
  file.name:
    displayName: Article
views:
  - type: table
    name: To review
    filters:
      and:
        - wiki == "article"
        - '!reviewed || reviewed < updated'
    order:
      - file.name
      - project
      - summary
      - updated
      - reviewed
    sort:
      - property: updated
        direction: DESC
  - type: table
    name: By project
    filters:
      and:
        - wiki == "article"
    groupBy:
      property: project
      direction: ASC
    order:
      - file.name
      - file.folder
      - type
      - status
      - summary
  - type: table
    name: Needs attention
    filters:
      and:
        - wiki == "article"
        - status != "current"
    order:
      - file.name
      - status
      - summary
      - updated
  - type: table
    name: Recently updated
    filters:
      and:
        - wiki == "article"
    order:
      - file.name
      - updated
      - summary
    sort:
      - property: updated
        direction: DESC
  - type: table
    name: Synthesis
    filters:
      and:
        - wiki == "synthesis"
    order:
      - file.name
      - archived
      - summary
    sort:
      - property: archived
        direction: DESC
"""


def cmd_init(args):
    w = wiki_dir()
    (w / "raw").mkdir(parents=True, exist_ok=True)
    made = []
    for name, text in (("index.md", INDEX_MD), ("log.md", LOG_MD), ("README.md", README_MD),
                       ("wiki.base", WIKI_BASE)):
        if not (w / name).exists():
            sb.write_atomic(w / name, text)
            made.append(name)
    write_index()
    print("created " + (", ".join(made) if made else "nothing: the layout is complete"))


# ---- new ------------------------------------------------------------------

def make_topic(project, topic, about):
    if folder_note(project, topic):
        return
    if not about:
        die(f"'{project}/{topic}' is a new topic: --about \"<what it covers>\" writes its folder note")
    (wiki_dir() / project / topic).mkdir(parents=True, exist_ok=True)
    heading = topic.replace("-", " ").capitalize()
    n = Note.__new__(Note)
    n.path, n.body = wiki_dir() / project / topic / f"{topic}.md", f"# {heading}\n\n{about.strip()}\n"
    n.save({"wiki": "topic", "type": "topic", "project": project, "summary": about.strip(),
            "tags": base_tags("wiki/topic", project, topic)})


def sources_project(refs_arg):
    """The one repo every wayfinder source comes from, else general."""
    found = {project_of(p) for p, _ in map(resolve_ref, split_refs(refs_arg))
             if Path(sb.rel(p)).parts[:1] == ("wayfinder",)}
    return found.pop() if len(found) == 1 else GENERAL


def cmd_new(args):
    parts = args[0].split("/") if args else []
    if len(parts) != 3:
        hint = f"{sources_project(sb.opt(args, '--sources', ''))}/{args[0]}" if len(parts) == 2 else "<project>/<topic>/<slug>"
        die(f"wiki new takes <project>/<topic>/<slug>: {hint}")
    project, topic, slug = parts
    check_name("project", project)
    check_name("topic", topic)
    title = sb.opt(args, "--title") or die("--title is required")
    type_ = sb.opt(args, "--type") or die("--type is required")
    summary = sb.opt(args, "--summary") or die("--summary is required")
    if type_ not in ("concept", "entity", "synthesis"):
        die("--type must be concept, entity or synthesis")
    if not SLUG.fullmatch(slug) or len(slug) > 60:
        die(f"slug '{slug}' must be kebab-case, at most 60 characters")
    if DATED.match(slug):
        die(f"slug '{slug}' starts with digits and a dash, which Semantra reads as a ticket number")
    if slug_taken(slug):
        die(f"slug '{slug}' is taken")
    kind = "synthesis" if type_ == "synthesis" else "article"
    sources = ref_links(sb.opt(args, "--sources", ""), kind)
    if not sources:
        die("--sources is required")
    related = ref_links(sb.opt(args, "--related", ""), key="related")
    make_topic(project, topic, sb.opt(args, "--about"))
    props = {"wiki": kind, "type": type_, "project": project}
    if kind == "article":
        props.update(status="current", summary=summary, updated=today())
    else:
        props.update(summary="[Archived] " + summary.removeprefix("[Archived] "), archived=today())
    props.update(sources=sources, related=related,
                 aliases=[a.strip() for a in (sb.opt(args, "--aliases") or "").split(",") if a.strip()],
                 tags=base_tags(f"wiki/{type_}", project, topic)
                 + [t.strip() for t in (sb.opt(args, "--tags") or "").split(",") if t.strip()])
    n = Note.__new__(Note)
    n.path = wiki_dir() / project / topic / f"{slug}.md"
    n.save(props, f"# {title}\n\n## Overview\n\n{summary.removeprefix('[Archived] ')}\n")
    write_index()
    print(n.rel)


# ---- read -----------------------------------------------------------------

def cmd_link(args):
    print(Note(note_path(args[0])).link())


def sections(body):
    """[(heading line or None, text)] in order."""
    out, head, lines = [], None, []
    for line in body.splitlines():
        if re.match(r"#{1,6} ", line):
            out.append((head, "\n".join(lines).strip()))
            head, lines = line, []
        else:
            lines.append(line)
    out.append((head, "\n".join(lines).strip()))
    return out


def callouts(body):
    return re.findall(r"^> \[!(?:warning|question)\].*(?:\n>.*)*", body, re.M)


def cmd_show(args):
    n = Note(note_path(args[0]))
    print(f"# {n.title}  ({n.rel})")
    for k in WIKI_KEYS:
        if k in n.props and k != "tags" and n.props[k] not in ("", []):
            v = n.props[k]
            print(f"{k}: " + (", ".join(v) if isinstance(v, list) else str(v)))
    if "--full" in args:
        print("\n" + n.body.strip())
        return
    overview = ""
    for head, text in sections(n.body):
        if head is None or head.startswith("# "):
            continue
        print("\n" + head)
        if head == "## Overview" and text:
            overview = text
            print(text)
    for c in callouts(n.body):
        if c not in overview:
            print("\n" + c)


def raw_notes():
    """Every note an article may cite: wiki/raw, Clippings, research notes, resolved tickets."""
    out = []
    for folder in (wiki_dir() / "raw", sb.VAULT / "Clippings", sb.WAYFINDER):
        if folder.is_dir():
            out += [p for p in sorted(folder.rglob("*.md")) if "backups" not in p.parts
                    and raw_class(p) and (raw_class(p) != "ticket" or ticket(p).status == "resolved")]
    return out


def describe(path):
    """(type, status, summary) for one line of output."""
    if raw_class(path) == "ticket":
        t = ticket(path)
        return t.type + " ticket", t.status, t.title
    n = Note(path)
    if raw_class(path):
        return "source", "-", n.title
    return n.props.get("type", ""), n.props.get("status") or n.kind, n.props.get("summary", "")


def cmd_find(args):
    limit = int(sb.opt(args, "--limit", 10))
    project = sb.opt(args, "--project")
    terms = [a.lower() for i, a in enumerate(args)
             if not a.startswith("--") and (i == 0 or args[i - 1] not in ("--limit", "--project"))]
    if not terms:
        die("find needs at least one term")
    paths = [n.path for n in wiki_notes()] + (raw_notes() if "--raw" in args else [])
    paths = [p for p in paths if in_scope(p, project)]
    scored = []
    for p in paths:
        n = Note(p)
        names = (n.title + " " + " ".join(n.refs("aliases"))).lower()
        summary, body = str(n.props.get("summary", "")).lower(), n.body.lower()
        score = sum(3 * (t in names) + 2 * (t in summary) + (t in body) for t in terms)
        if score:
            scored.append((score, p))
    scored.sort(key=lambda x: (-x[0], sb.rel(x[1])))
    for score, p in scored[:limit]:
        type_, status, summary = describe(p)
        print(f"{sb.rel(p)[:-3]} · {type_} · {status} · {score} · {summary}")
    if not scored:
        print("no matches")
    elif len(scored) > limit:
        print(f"({len(scored) - limit} more; --limit)")


# ---- raw ------------------------------------------------------------------

def cmd_raw(args):
    parts = args[0].split("/") if args and not args[0].startswith("--") else []
    if len(parts) != 2:
        die("wiki raw takes <project>/<topic>: the repo's folder under wayfinder/, or general")
    project, topic = parts
    check_name("project", project)
    check_name("topic", topic)
    title = sb.opt(args, "--title") or die("--title is required")
    source = sb.opt(args, "--source") or die("--source is required")
    src = sb.opt(args, "--from") or die("--from <file|-> is required")
    if re.match(r"https?://", source):
        for p in raw_notes():
            if raw_class(p) in ("raw", "clipping") and Note(p).props.get("source") == source:
                print(sb.rel(p))
                die(f"{source} is already kept as {sb.rel(p)}")
    text = sys.stdin.read() if src == "-" else Path(src).expanduser().read_text(encoding="utf-8")
    base = slugify(title) or "source"
    slug, i = base, 1
    while slug_taken(slug):
        i += 1
        slug = f"{base}-{i}"
    props = {"wiki": "raw", "type": "source", "project": project, "title": title, "source": source,
             "author": sb.opt(args, "--author", ""), "published": sb.opt(args, "--published", "Unknown"),
             "created": today(), "tags": base_tags("wiki/source", project, topic)}
    root = sb.opt(args, "--repo-root")
    if root:
        props.update(provenance(Path(root).expanduser(), split_text(sb.opt(args, "--paths", "")),
                                split_text(sb.opt(args, "--symbols", "")), sb.opt(args, "--rev", "HEAD")))
    elif sb.opt(args, "--paths") or sb.opt(args, "--symbols") or sb.opt(args, "--rev"):
        die("--paths, --symbols and --rev need --repo-root <clone>")
    path = wiki_dir() / "raw" / project / topic / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    sb.write_atomic(path, sb.dump_fm(props, WIKI_KEYS) + text)
    print(sb.rel(path))


def split_text(value):
    return [v.strip() for v in str(value or "").split(",") if v.strip()]


def text_list(n, key):
    """A text-list property, also when it is still written as one comma-separated string."""
    v = n.props.get(key)
    return split_text(v) if isinstance(v, str) else [str(x) for x in v or []]


def repo_name(origin):
    m = re.search(r"[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$", origin)
    return m.group(1) if m else origin


def provenance(root, paths, symbols, rev="HEAD"):
    """Where a source was read: the repo (from origin), the commit and branch (checked out, or
    `rev` read without checking it out), and the paths and symbols its claims rest on, each path
    checked to exist at that commit."""
    def git(*a):
        r = subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True)
        if r.returncode:
            die(f"git {' '.join(a)} in {root}: {r.stderr.strip() or 'failed'}")
        return r.stdout.strip()
    origin = git("remote", "get-url", "origin")
    commit = git("rev-parse", "--verify", f"{rev}^{{commit}}")
    ref = (git("rev-parse", "--abbrev-ref", "HEAD") if rev == "HEAD" else
           "" if re.fullmatch(r"[0-9a-f]{7,40}", rev) else re.sub(r"^(refs/)?(remotes/)?origin/", "", rev))
    for path in paths:
        if subprocess.run(["git", "-C", str(root), "cat-file", "-e", f"{commit}:{path.rstrip('/')}"],
                          capture_output=True).returncode:
            die(f"'{path}' does not exist at {commit[:10]} in {root}")
    return {"repo": repo_name(origin), "commit": commit,
            "ref": ref, "paths": paths, "symbols": symbols}


def provenance_problems(n, kind):
    """A raw note read from a repo names the repo and the full commit; paths and symbols are lists.
    An article records only `verified`, a full commit."""
    props, out = n.props, []
    if kind == "raw" and any(props.get(k) for k in PROVENANCE):
        if not REPO.fullmatch(str(props.get("repo", ""))):
            out.append("provenance without a repo (owner/name)")
        if not SHA.fullmatch(str(props.get("commit", ""))):
            out.append("provenance without a full 40-character commit")
        out += [f"{k} is text, not a list: `wikibrain check --fix`" for k in ("paths", "symbols")
                if isinstance(props.get(k), str)]
    elif kind != "raw":
        out += [f"{k} belongs on the raw notes it was read from" for k in PROVENANCE if props.get(k)]
    if props.get("verified") and (kind != "article" or not SHA.fullmatch(str(props["verified"]))):
        out.append("verified is a full 40-character commit, on articles only")
    return out


# ---- verify ---------------------------------------------------------------

TOKEN = re.compile(r"`([^`\s]+)`")
IDENT = re.compile(r"(?:[A-Z][A-Za-z0-9]+|[a-z]+[A-Z][A-Za-z0-9]*|[A-Z][A-Z0-9_]{3,})(?:\.[A-Za-z]+)*")
VERDICTS = ("broken", "orphaned", "drifted", "unanchored", "current")


def cmd_verify(args):
    """Are an article's claims about a repo still true? Anchor at `verified` or the newest source
    commit; compare against the base branch when the anchor is on it, else against the source's
    branch; a deleted path or a vanished symbol is broken, a changed path drifted. An article
    with no recorded source commit is anchored at its `updated` date on the base, with paths and
    identifiers guessed from its backticked code, and says so."""
    root = Path(sb.opt(args, "--repo-root", ".")).expanduser()
    base = sb.opt(args, "--base", "origin/main")

    @functools.lru_cache(maxsize=None)
    def git(*a):
        r = subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None

    origin = git("remote", "get-url", "origin") or die(f"{root} is not a git clone with an origin")
    repo = repo_name(origin)
    project = sb.opt(args, "--project") or repo.split("/")[-1]
    git("rev-parse", "--verify", base) is not None or die(f"no {base} in {root}: git fetch first")
    tree = set((git("ls-tree", "-r", "--name-only", base) or "").splitlines())
    dirs = {"/".join(t.split("/")[:i]) for t in tree for i in range(1, t.count("/") + 1)}

    def exists(ref, path):
        return git("cat-file", "-e", f"{ref}:{path.rstrip('/')}") is not None

    def guess(n):
        toks = set(TOKEN.findall(n.body))
        paths = set()
        for t in (x.rstrip("/") for x in toks):
            if t in tree or t in dirs:
                paths.add(t)
            elif "." in t.split("/")[-1] and not t.startswith("@"):
                hits = [x for x in tree if x.endswith("/" + t)]
                paths.update(hits if 0 < len(hits) <= 3 else [])
        names = {t for t in toks if IDENT.fullmatch(t) and t not in paths and not any(p.endswith(t) for p in paths)}
        return sorted(paths), sorted(names)

    rows = []
    for n in articles():
        if n.kind != "article" or project_of(n.path) != project:
            continue
        srcs = [Note(p) for p in (target_of(entry_key(e)) for e in n.refs("sources")) if p and Note(p).kind == "raw"]
        mine = [x for x in srcs if x.props.get("repo") == repo and SHA.fullmatch(str(x.props.get("commit", "")))]
        row = {"note": n.rel, "anchor": None, "ref": None, "target": None, "guessed": False,
               "paths": [], "symbols": [], "changed": [], "gone": [], "commits_since": 0}
        if mine:
            newest = max(mine, key=lambda x: int(git("log", "-1", "--format=%ct", x.props["commit"]) or 0))
            row.update(anchor=newest.props["commit"], ref=newest.props.get("ref"),
                       paths=sorted({p for x in mine for p in text_list(x, "paths")}),
                       symbols=sorted({y for x in mine for y in text_list(x, "symbols")}))
        else:
            row["guessed"] = True
            row["paths"], row["symbols"] = guess(n)
            row["anchor"] = git("rev-list", "-1", f"--before={n.props.get('updated', '')} 23:59", base)
        if SHA.fullmatch(str(n.props.get("verified", ""))):
            row["anchor"] = n.props["verified"]
        if not row["anchor"] or not (row["paths"] or row["symbols"]) or git("cat-file", "-e", row["anchor"] + "^{commit}") is None:
            rows.append({**row, "verdict": "unanchored"})
            continue
        if git("merge-base", "--is-ancestor", row["anchor"], base) is not None:
            row["target"] = base
        elif row["ref"] and (target := next((t for t in (f"origin/{row['ref']}", row["ref"])
                                             if git("rev-parse", "--verify", t) is not None), None)):
            row["target"] = target
        else:
            rows.append({**row, "verdict": "orphaned"})
            continue
        t, a = row["target"], row["anchor"]
        if row["paths"]:
            row["changed"] = (git("diff", "--name-status", a, t, "--", *row["paths"]) or "").splitlines()
            row["commits_since"] = int(git("rev-list", "--count", f"{a}..{t}", "--", *row["paths"]) or 0)
        row["gone"] = [p for p in row["paths"] if not exists(t, p)]
        row["gone"] += [y for y in row["symbols"]
                        if git("grep", "-q", "-w", "-F", y.split(".")[0], t, "--", ".", ":!*.md") is None]
        verdict = ("broken" if row["gone"] or any(c[:1] in "DR" for c in row["changed"])
                   else "drifted" if row["changed"] else "current")
        rows.append({**row, "verdict": verdict})
    rows.sort(key=lambda r: (VERDICTS.index(r["verdict"]), r["note"]))
    if "--json" in args:
        print(json.dumps(rows, indent=1))
        return
    for r in rows:
        at = f"{r['anchor'][:10]}{'@' + r['ref'] if r['ref'] else ''}" if r["anchor"] else "no anchor"
        detail = ([f"gone: {', '.join(r['gone'][:4])}"] if r["gone"] else []) + \
                 ([f"{len(r['changed'])} files changed in {r['commits_since']} commits"] if r["changed"] else [])
        print(f"{r['verdict']:<10} {r['note']}  ({at} → {r['target'] or '-'}{', guessed' if r['guessed'] else ''})"
              + (f"  {'; '.join(detail)}" if detail else ""))
    counts = {v: sum(r["verdict"] == v for r in rows) for v in VERDICTS}
    print(f"{len(rows)} articles in {project} against {repo} {base}: "
          + ", ".join(f"{c} {v}" for v, c in counts.items() if c))


# ---- set ------------------------------------------------------------------

def entry_key(entry):
    """What a list entry points at, comparable across alias and `.md` spellings."""
    m = LINK.fullmatch(str(entry).strip())
    t = m.group(2).strip() if m else str(entry).strip()
    return t[:-3] if t.endswith(".md") else t


def status_after_supersession(n):
    if n.refs("superseded_by"):
        return "outdated"
    return "disputed" if DISPUTED.search(n.body) else "current"


def cmd_set(args):
    n = Note(note_path(args[0]))
    props = dict(n.props)
    others = {}  # path -> Note, the far ends of reciprocal links

    def far(path):
        if path not in others:
            others[path] = Note(path)
        return others[path]

    for kv in args[1:]:
        m = re.fullmatch(r"([A-Za-z_]\w*)([+-]?)=(.*)", kv, re.S)
        if not m:
            die(f"'{kv}' is not key=value, key+=refs or key-=refs")
        key, op, value = m.groups()
        if key in REF_KEYS:
            new = [resolve_ref(r) for r in split_refs(value)]
            if key == "sources":
                for p, _ in new:
                    why = op != "-" and source_problem(n.kind, p)
                    if why:
                        die(why)
            old = list(n.refs(key)) if key not in props else list(props.get(key) or [])
            have = {entry_key(e) for e in old}
            if op == "+":
                result = old + [link for _, link in new if entry_key(link) not in have]
            elif op == "-":
                drop = {entry_key(link) for _, link in new}
                result = [e for e in old if entry_key(e) not in drop]
            else:
                result = [link for _, link in new]
            props[key] = result
            if key in RECIPROCAL:
                back, me = RECIPROCAL[key], n.link()
                before, after = {entry_key(e) for e in old}, {entry_key(e) for e in result}
                for k in (before ^ after):
                    p = target_of(k)
                    if p is None:
                        continue
                    o = far(p)
                    lst = [e for e in o.refs(back) if entry_key(e) != entry_key(me)]
                    if k in after:
                        lst.append(me)
                    o.props = {**o.props, back: lst}
        elif key in TEXT_LISTS:
            items = [a.strip() for a in value.split(",") if a.strip()]
            old = list(props.get(key) or [])
            props[key] = (old + [i for i in items if i not in old] if op == "+"
                          else [o for o in old if o not in items] if op == "-" else items)
        elif op:
            die(f"'{key}' is not a list: use {key}=value")
        else:
            if key == "status" and value not in STATUSES:
                die(f"status must be one of {', '.join(STATUSES)}")
            if value == "today" and key in DATE_KEYS:
                value = today()
            props[key] = value
    n.props = props
    supersession = any(re.match(r"supersede", a) for a in args[1:])
    for note in [n] + list(others.values()):
        if supersession and note.kind == "article":
            note.props = {**note.props, "status": status_after_supersession(note)}
        note.save()
    write_index()
    print(f"{n.rel}: " + " ".join(args[1:]) + (f" (and {', '.join(o.rel for o in others.values())})"
                                                if others else ""))


# ---- log ------------------------------------------------------------------

def try_note(arg):
    try:
        return Note(note_path(arg))
    except SystemExit:
        return None


def cmd_log(args):
    kind = args[0] if args else ""
    if kind not in ("learn", "ask", "tend"):
        die("usage: wiki log <learn|ask|tend> --subject \"…\"")
    subject = sb.opt(args, "--subject") or die("--subject is required")
    p = wiki_dir() / "log.md"
    if not p.exists():
        die("no wiki/log.md: `wikibrain init`")
    m = re.fullmatch(r"(Archived: )?(.+)", subject)
    if not subject.startswith("no material: "):
        n = try_note(m.group(2))
        if n is not None:
            subject = (m.group(1) or "") + n.link(p)
    lines = [f"## [{today()}] {kind} | {subject}"]
    if sb.opt(args, "--disposition"):
        lines.append(f"- Disposition: {sb.opt(args, '--disposition')}")
    for flag, name in (("--raw", "Raw"), ("--updated", "Updated")):
        if sb.opt(args, flag):
            lines.append(f"- {name}: " + ", ".join(resolve_ref(r, p)[1] for r in split_refs(sb.opt(args, flag))))
    sb.write_atomic(p, p.read_text(encoding="utf-8").rstrip("\n") + "\n\n" + "\n".join(lines) + "\n")
    print(lines[0])


# ---- backlog --------------------------------------------------------------

def cited():
    """Every note some article or synthesis page names in `sources`."""
    return {dst for n in articles() for kind, dst in n.edges if kind == "sources"}


def no_material():
    p = wiki_dir() / "log.md"
    if not p.exists():
        return set()
    found = re.findall(r"^## \[[^\]]*\] learn \| no material: (.+?)\s*$", Note(p).body, re.M)
    return {entry_key(f) for f in found}


def backlog(project=None):
    done = cited() | no_material()
    out = []
    for p in raw_notes():
        key = sb.rel(p)[:-3]
        if key in done or not in_scope(p, project) or (raw_class(p) == "ticket" and ticket(p).type != "research"):
            continue
        created = str(Note(p).props.get("created") or date.fromtimestamp(p.stat().st_mtime).isoformat())
        out.append((created[:10], key, p))
    return sorted(out)


def cmd_backlog(args):
    limit = int(sb.opt(args, "--limit", 10))
    items = backlog(sb.opt(args, "--project"))
    for created, key, p in items[:limit]:
        print(f"{key} · {created} · {describe(p)[2]}")
    print(f"{len(items)} on the backlog" + (f", {limit} shown" if len(items) > limit else ""))


# ---- grounding ------------------------------------------------------------
# Candidate literals, ported from the karpathy-llm-wiki skill's scripts/check_evidence.py:
#
#   MIT License
#
#   Copyright (c) 2026 Yuhan Lei
#
#   Permission is hereby granted, free of charge, to any person obtaining a copy
#   of this software and associated documentation files (the "Software"), to deal
#   in the Software without restriction, including without limitation the rights
#   to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#   copies of the Software, and to permit persons to whom the Software is
#   furnished to do so, subject to the following conditions:
#
#   The above copyright notice and this permission notice shall be included in all
#   copies or substantial portions of the Software.
#
#   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#   AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#   OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
#   SOFTWARE.
#
# Closed candidate set: quotes of 15+ characters (double-quoted spans and plain blockquotes), ISO
# dates, and numbers that are grouped (10,000), dotted (2.1.80), suffixed (42K, 99.9%) or 4+ digits.
# Changed here: callouts are prose, not quotes, and their own date is not evidence; wikilinks read
# as their alias.

NUMBER_TOKEN = re.compile(r"(?:\d{1,3}(?:,\d{3})+(?:\.\d+)*(?:\s*[KMB%](?![A-Za-z]))?"
                          r"|\d+(?:\.\d+)*(?:\s*[KMB%](?![A-Za-z]))?)(?![A-Za-z])")
ISO_DATE = re.compile(r"\d{4}-\d{2}(?:-\d{2})?")
QUOTED = re.compile(r'"([^"\n]*)"')
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def plain(text):
    """Whitespace collapsed, curly quotes straight: both sides of every comparison."""
    text = text.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    return re.sub(r"\s+", " ", text).strip()


def unfenced(text):
    out, fence = [], None
    for line in text.splitlines():
        m = FENCE.match(line)
        if fence:
            if m and m.group(1)[0] == fence:
                fence = None
            continue
        if m:
            fence = m.group(1)[0]
            continue
        out.append(line)
    return out


def denoise(line):
    line = re.sub(r"`[^`\n]*`", " ", line)
    line = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)
    return LINK.sub(lambda m: m.group(4) or m.group(2), line)


def keep_number(token):
    token = token.strip()
    return bool(re.search(r"[KMB%]$", token)) or "," in token or "." in token or len(token) >= 4


def literals(line):
    found = [("date", m.group(0)) for m in ISO_DATE.finditer(line)]
    masked = ISO_DATE.sub(lambda m: " " * len(m.group(0)), line)
    return found + [("number", m.group(0)) for m in NUMBER_TOKEN.finditer(masked) if keep_number(m.group(0))]


def candidates(body):
    out, quote, para, callout = [], [], [], False

    def flush(buf, as_quote):
        if not buf:
            return
        joined = plain(" ".join(buf))
        if as_quote and len(joined) >= 15:
            out.append(("quote", joined))
        elif not as_quote:
            out.extend(("quote", m.group(1)) for m in QUOTED.finditer(joined) if len(m.group(1).strip()) >= 15)
        buf.clear()

    for line in unfenced(plain_quotes(body)):
        s = line.strip()
        if s.startswith(">"):
            flush(para, False)
            content = denoise(s.lstrip(">").strip())
            if content.startswith("[!"):
                callout = True
                continue
            out.extend(literals(content))
            (para if callout else quote).append(content)
            continue
        flush(quote, True)
        if callout:
            flush(para, False)
            callout = False
        if not s:
            flush(para, False)
            continue
        line = denoise(line)
        out.extend(literals(line))
        para.append(line)
    flush(quote, True)
    flush(para, False)
    seen, unique = set(), []
    for kind, value in out:
        value = value.strip().strip(".,;:()[]")
        if value and (kind, value) not in seen:
            seen.add((kind, value))
            unique.append((kind, value))
    return unique


def plain_quotes(text):
    return text.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")


def holds(haystack, kind, value):
    if kind == "quote":
        return value in haystack
    right = r"(?!-\d{2})" if kind == "date" and len(value) == 7 else ""
    return re.search(r"(?<![\d.,])" + re.escape(value) + right + r"(?![A-Za-z0-9]|[.,]\d|%)", haystack) is not None


def suspects(n):
    sources = [target_of(entry_key(e)) for e in n.refs("sources")]
    texts = [plain("\n".join(unfenced(sb.split_fm(p.read_text(encoding="utf-8"))[1]))) for p in sources if p]
    if not texts:
        return []
    return [v for kind, v in candidates(n.body) if not any(holds(t, kind, plain(v)) for t in texts)]


# ---- check ----------------------------------------------------------------

REQUIRED = {"article": ("summary", "updated", "status", "sources"), "synthesis": ("summary", "archived", "sources"),
            "topic": ("summary",), "raw": ("title", "source")}
SKIP_DIRS = {".obsidian", ".trash", "backups"}


def by_name(name):
    """Every vault file with this name, outside Obsidian's own folders."""
    return [p for p in sb.VAULT.rglob(name) if not SKIP_DIRS & set(p.relative_to(sb.VAULT).parts)]


CODE_SPAN = re.compile(r"```.*?```|`[^`\n]*`", re.S)


def outside_code(text, fn, keep_code=False):
    """fn applied to the text between code spans; the spans kept, or blanked for searching."""
    out, last = [], 0
    for m in CODE_SPAN.finditer(text):
        out += [fn(text[last:m.start()]), m.group(0) if keep_code else " " * len(m.group(0))]
        last = m.end()
    return "".join(out + [fn(text[last:])])


def heading_alias(q, embed, anchor):
    """The alias a link to `q` must carry, its `# ` heading, so a property can drop it and get it back;
    None where any will do: an embed, a link to a section, a ticket (`#NNN`), a file that is no note."""
    if embed or anchor or q.suffix != ".md" or raw_class(q) == "ticket":
        return None
    return Note(q).title


def cmd_check(args):
    fix = "--fix" in args
    relative = sb.links() == "relative"
    w = wiki_dir()
    if not w.is_dir():
        die("no wiki/ yet: `wikibrain init`")
    problems, fixed = [], []

    def lab(p):
        return p.relative_to(w).as_posix()

    old = [d for d in sorted(w.iterdir()) if d.is_dir() and is_old_topic(d)]
    old += [d for d in sorted((w / "raw").iterdir()) if d.is_dir() and old_raw(d)] if (w / "raw").is_dir() else []
    for d in old:
        problems.append(f"{lab(d)}: old layout, a topic outside any project: `wikibrain migrate <project>`")
    every = [p for p in sorted(w.rglob("*.md")) if lab(p) not in ROOT_FILES
             and not any(p.is_relative_to(d) for d in old)]
    # slugs and places: wiki/<project>/<topic>/<slug>.md, wiki/raw/<project>/<topic>/<slug>.md
    stems = {}
    for p in every:
        if not is_folder_note(p):
            stems.setdefault(p.stem, []).append(lab(p))
        parts = p.relative_to(w).parts
        depth = 4 if parts[0] == "raw" else 3
        if DATED.match(p.stem):
            problems.append(f"{lab(p)}: slug starts with digits and a dash")
        if len(parts) < depth:
            problems.append(f"{lab(p)}: outside a topic folder; the place is wiki/"
                            + ("raw/" if parts[0] == "raw" else "") + "<project>/<topic>/")
        elif len(parts) > depth:
            problems.append(f"{lab(p)}: deeper than wiki/" + ("raw/" if parts[0] == "raw" else "") + "<project>/<topic>/")
    for stem, where in stems.items():
        if len(where) > 1:
            problems.append(f"slug '{stem}' is taken twice: {', '.join(where)}")
    for project in projects():
        for t in topics(project):
            if not (w / project / t / f"{t}.md").exists():
                problems.append(f"{project}/{t}: no folder note ({project}/{t}/{t}.md)")

    for p in every:
        n = Note(p)
        kind = "raw" if p.relative_to(w).parts[0] == "raw" else n.kind
        if kind not in TYPES:
            problems.append(f"{lab(p)}: unknown wiki '{n.kind}'")
            continue
        if kind == "raw":
            if n.kind != "raw":
                problems.append(f"{lab(p)}: a source without wiki: raw")
        elif n.props.get("type") not in TYPES[kind]:
            problems.append(f"{lab(p)}: unknown type '{n.props.get('type', '')}' for {kind}")
        for key in REQUIRED[kind]:
            if not n.props.get(key):
                problems.append(f"{lab(p)}: missing {key}")
        texts = [k for k in ("paths", "symbols") if isinstance(n.props.get(k), str)]
        if fix and texts:
            n.props = {**n.props, **{k: split_text(n.props[k]) for k in texts}}
            n.save()
            fixed.append(f"{lab(p)}: {', '.join(texts)} made lists")
        problems += [f"{lab(p)}: {why}" for why in provenance_problems(n, kind)]
        if kind == "raw":
            continue
        if kind == "article":
            status = n.props.get("status")
            if status and status not in STATUSES:
                problems.append(f"{lab(p)}: unknown status '{status}'")
            elif status and status != status_after_supersession(n):
                problems.append(f"{lab(p)}: status is {status}; the rule makes it {status_after_supersession(n)}")
        for m in OUTDATED.finditer(n.body):
            if not re.match(r"\s*\(\d{4}-\d{2}-\d{2}\)", m.group(1)):
                problems.append(f"{lab(p)}: Outdated callout without its date")
        me = sb.rel(p)[:-3]
        for key, back in RECIPROCAL.items():
            for e in n.refs(key):
                q = target_of(entry_key(e))
                if q and me not in {entry_key(x) for x in Note(q).refs(back)}:
                    problems.append(f"{lab(q) if q.is_relative_to(w) else sb.rel(q)}: missing {back} back to {me}")
        for e in n.refs("sources"):
            q = target_of(entry_key(e))
            why = q and source_problem(kind, q)
            if why:
                problems.append(f"{lab(p)}: {why}")

        # links: in properties and prose
        changed = False

        def aliased(link, alias, want, rebuilt):
            nonlocal changed
            if want is None or alias == want:
                return link
            if fix:
                changed = True
                fixed.append(f"{lab(p)}: alias set to the heading: {rebuilt}")
                return rebuilt
            problems.append(f"{lab(p)}: alias is not the target's heading: {link} (heading: {want})")
            return link

        def repair(m, key=None):
            nonlocal changed
            target = m.group(2).strip()
            if not target or "/" not in target:
                if target:
                    problems.append(f"{lab(p)}: wikilink by bare file name: {m.group(0)}")
                return m.group(0)
            q = target_of(target)
            if q:
                want = heading_alias(q, m.group(1), m.group(3))
                return aliased(m.group(0), m.group(4), want, f"[[{target}|{want}]]")
            name = Path(target).name
            hits = by_name(name if "." in name else name + ".md")
            if len(hits) == 1:
                new = sb.rel(hits[0])
                new = new[:-3] if new.endswith(".md") else new
                if fix:
                    changed = True
                    fixed.append(f"{lab(p)}: link moved to {new}")
                    return f"{m.group(1)}[[{new}{m.group(3) or ''}" + (f"|{m.group(4)}" if m.group(4) is not None else "") + "]]"
                problems.append(f"{lab(p)}: link moved: {m.group(0)} -> {new}")
                return m.group(0)
            if key == "related":
                if fix:
                    changed = True
                    fixed.append(f"{lab(p)}: dropped dead related {target}")
                    return None
                problems.append(f"{lab(p)}: related link to a note that no longer exists: {target}")
                return m.group(0)
            problems.append(f"{lab(p)}: broken link: {m.group(0)}")
            return m.group(0)

        def repair_md(m):
            """A relative link, as a sync clone writes them: it resolves and carries the heading."""
            href = m.group(3)
            path, _, anchor = href.partition("#")
            if SCHEME.match(href) or not path or path.startswith("/"):
                return m.group(0)
            q = target_of(os.path.normpath(os.path.join(os.path.dirname(sb.rel(p)), unquote(path))))
            if q is None:
                problems.append(f"{lab(p)}: broken link: {m.group(0)}")
                return m.group(0)
            want = heading_alias(q, m.group(1), anchor)
            return aliased(m.group(0), m.group(2), want, f"[{want}]({href})")

        def links_in(seg):
            seg = LINK.sub(lambda m: repair(m), seg)
            return MD_FULL.sub(repair_md, seg) if relative else seg

        props = dict(n.props)
        here = p.relative_to(w).parts[0]
        if props.get("project") != here:
            if fix:
                props["project"] = here
                changed = True
                fixed.append(f"{lab(p)}: project set to {here}")
            else:
                problems.append(f"{lab(p)}: project is {props.get('project') or 'missing'}; its folder says {here}")
        for key, v in n.props.items():
            if isinstance(v, list):
                kept = []
                for e in v:
                    m = LINK.fullmatch(str(e).strip())
                    if not m and key in REF_KEYS and not target_of(entry_key(e)):
                        problems.append(f"{lab(p)}: broken link: {e}")
                    r = repair(m, key) if m else e
                    if r is not None:
                        kept.append(r)
                props[key] = kept
        old, rel = list(props.get("tags") or []), p.relative_to(w).parts
        tags = retag(props, here, rel[1]) if len(rel) > 2 else old
        if set(tags) != set(old):
            if fix:
                props["tags"] = tags
                changed = True
                fixed.append(f"{lab(p)}: tags set to {', '.join(tags)}")
            else:
                problems.append(f"{lab(p)}: tags are {', '.join(old) or 'missing'}; the rule makes them {', '.join(tags)}")
        prose = outside_code(n.body, lambda seg: seg)
        body = outside_code(n.body, links_in, keep_code=True)
        for m in [] if relative else re.finditer(r"\[[^\]]*\]\((?!https?://|mailto:)([^)\s]+?\.md)\)", prose):
            problems.append(f"{lab(p)}: markdown link to a vault note: {m.group(0)} (a full-path wikilink belongs here)")
        bare = re.sub(r"\[\[[^\]]*\]\]|\[[^\]]*\]\([^)]*\)|https?://\S+", " ", prose)
        for m in re.finditer(r"(?:^|[^\w/&#\[])#(\d{2,4})\b", bare):
            problems.append(f"{lab(p)}: bare #{m.group(1)} (`sbmap link` prints the ticket's link)")
        if changed:
            n.save(props, body)

    index = w / "index.md"
    if index.exists() and stamped_index() != index.read_text(encoding="utf-8"):
        if fix:
            write_index()
            fixed.append("index.md: restamped")
        else:
            problems.append("index.md: the index block is out of date")

    for f in fixed:
        print("fixed " + f)
    for pr in problems:
        print(pr)
    sus = [(n, suspects(n)) for n in articles() if n.kind == "article"]
    sus = [(n, v) for n, v in sus if v]
    if sus:
        print("grounding suspects (judge each against its sources; never counted):")
        for n, values in sus:
            print(f"  {lab(n.path)}: " + " · ".join(values))
    print(f"{len(backlog())} on the backlog")
    print(f"{len(problems)} problem(s) in wiki/")
    sys.exit(1 if problems else 0)


# ---- migrate --------------------------------------------------------------

def relink(text, moves):
    """Every wikilink into a moved folder, repointed."""
    def sub(m):
        target = m.group(2).strip()
        for old, new in moves:
            if target == old or target.startswith(old + "/"):
                target = new + target[len(old):]
                return f"{m.group(1)}[[{target}{m.group(3) or ''}" + (f"|{m.group(4)}" if m.group(4) is not None else "") + "]]"
        return m.group(0)
    return LINK.sub(sub, text)


def cmd_migrate(args):
    write = "--write" in args
    names = [a for a in args if not a.startswith("--")]
    if not names:
        die("usage: wiki migrate <project> [topic…] [--write]")
    project, chosen = names[0], names[1:]
    check_name("project", project)
    w = wiki_dir()
    topics_ = [d for d in sorted(w.iterdir()) if d.is_dir() and is_old_topic(d)] if w.is_dir() else []
    raws = [d for d in sorted((w / "raw").iterdir()) if d.is_dir() and old_raw(d)] if (w / "raw").is_dir() else []
    if chosen:
        missing = set(chosen) - {d.name for d in topics_ + raws}
        if missing:
            die(f"no topic from before projects named {', '.join(sorted(missing))}")
        topics_ = [d for d in topics_ if d.name in chosen]
        raws = [d for d in raws if d.name in chosen]
    moves = [(d, w / project / d.name) for d in topics_] + [(d, w / "raw" / project / d.name) for d in raws]
    if not moves:
        print("nothing to migrate: every topic is under a project")
        return
    for old, new in moves:
        if new.exists():
            die(f"{sb.rel(new)} exists already; move {sb.rel(old)} by hand")
    pairs = [(sb.rel(old), sb.rel(new)) for old, new in moves]
    edited, yours = [], []
    for p in sorted(sb.VAULT.rglob("*.md")):
        parts = p.relative_to(sb.VAULT).parts
        if SKIP_DIRS & set(parts) or p.parent.parent == w / "raw" or parts[:2] == ("wiki", "raw"):
            continue
        text = p.read_text(encoding="utf-8")
        if relink(text, pairs) != text:
            (edited if parts[0] in ("wiki", "wayfinder") else yours).append(p)
    for old, new in pairs:
        print(f"{old} -> {new}")
    print(f"links repointed in {len(edited)} note(s) under wiki/ and wayfinder/")
    for p in yours:
        print(f"⚠️ not rewritten, the owner's note: {sb.rel(p)} links into a moved topic")
    if not write:
        print("dry run: nothing written (add --write)")
        return
    for p in edited:
        sb.write_atomic(p, relink(p.read_text(encoding="utf-8"), pairs))
    for old, new in moves:
        new.parent.mkdir(parents=True, exist_ok=True)
        old.rename(new)
        if new.parent != w / "raw" / project:  # sources are never edited
            for q in new.glob("*.md"):
                n = Note(q)
                n.save({**n.props, "project": project, "tags": retag(n.props, project, new.name)})
    write_index()
    print("written")


def cmd_sync(name):
    def run(args):
        import wikisync as sbsync  # dump/import live beside this file; a loader that fetches only wikibrain.py and vault.py never needs it
        sbsync.COMMANDS[name](args)
    return run


COMMANDS = {"index": cmd_index, "find": cmd_find, "show": cmd_show, "link": cmd_link,
            "backlog": cmd_backlog, "init": cmd_init, "raw": cmd_raw, "new": cmd_new, "set": cmd_set,
            "log": cmd_log, "check": cmd_check, "verify": cmd_verify,
            "migrate": cmd_migrate, "dump": cmd_sync("dump"), "import": cmd_sync("import")}


def main(args):
    if args and args[0] == "wiki":
        args = args[1:]
    if not args or args[0] not in COMMANDS:
        sys.exit(__doc__)
    try:
        COMMANDS[args[0]](args[1:])
    finally:
        save_graph()


if __name__ == "__main__":
    main(sys.argv[1:])
