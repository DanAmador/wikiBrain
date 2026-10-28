# The wiki

The maps hold **work**; the wiki holds **knowledge**, the part of what a map learned that stays true
after the map closes. Sources are never edited; the LLM compiles them into articles, and the
articles compound. Built on Karpathy's LLM-wiki pattern (the `karpathy-llm-wiki` skill, MIT), in the
vault's own shape: every field a property, every reference a full-path wikilink. That shape is what
lets Obsidian's graph, Bases, and Semantra read the wiki as typed data.

## Layout

```
<vault>/wiki/
  index.md                         the agent's entry point: generated, one row per article,
                                   by project, then topic
  log.md                           append-only: every learn, every archived ask, every tend
  wiki.base                        the owner's board (views below), embedded in index.md
  README.md                        three lines pointing here, for harnesses without this skill
  raw/<project>/<topic>/<slug>.md  sources an agent fetched or the owner pasted
  <project>/<topic>/<topic>.md     the topic's folder note: what the topic covers
  <project>/<topic>/<slug>.md      articles and synthesis pages
```

**Raw** is every note an article may cite as evidence. It is read and never edited by the wiki:

| raw class | where | on the backlog |
|---|---|---|
| fetched or pasted source | `wiki/raw/<project>/<topic>/` (written by `wikibrain raw`) | yes |
| clipping | `Clippings/` (the owner's web clipper) | yes |
| research note | `wayfinder/**/research/` | yes |
| ticket, `status: resolved` | `wayfinder/**/issues/` | `type: research` only; others when `learn` names them |

The agent writes only under `wiki/` (and the tracker). `Clippings/` is the owner's.

**Projects** keep each repo's knowledge apart, the way `wayfinder/<repo>/` keeps its maps. A
project is the repo's folder name under `wayfinder/` (`monorepo`, `semantra`, `sk4te`), so a map's
findings land in its repo's project. Knowledge that holds outside any one repo (how Obsidian
indexes links, a three.js technique, a library's API) goes in `general`, even when one repo's map
found it: the test is whether another repo could use it unchanged. An article that applies one
`general` article to a repo lives in the repo's project and links the general one through
`related`.

**Topics** are subject areas inside a project (`part-hierarchy`, `obsidian`, `unity-physics`), never
maps: one article serves every map of the project that touches its subject. One level each:
`wiki/<project>/<topic>/<slug>.md`. `raw` is reserved as a project and a topic name. A wiki from
before projects (topics straight under `wiki/`) moves with `wikibrain migrate <project>`.

**Slugs** are the title in kebab-case, ≤60 characters, unique across the whole wiki (so a link
fixed by file name is never ambiguous). They never start with digits and a dash: Semantra's vault
index reads a leading `NNN-` (and so a `2026-` date) as a ticket number. Dates live in properties;
`wiki raw` moves a leading number to the end of the slug (`2026 roadmap` → `roadmap-2026`), and
`wiki new` refuses one.

## An article

```markdown
---
wiki: article
type: concept
project: general
status: current
summary: "One line: what this article establishes."
updated: 2026-10-26
sources:
  - "[[wiki/raw/general/obsidian/frontmatter-link-cache|Frontmatter link cache]]"
  - "[[wayfinder/semantra/obsidian-plugin/issues/007-does-the-plugin-read-links-and-tags-from-obsi|#007]]"
related:
  - "[[wiki/general/obsidian/metadata-cache|Metadata cache]]"
aliases:
  - frontmatterLinks
tags:
  - wiki/concept
  - project/general
  - topic/obsidian
  - obsidian/metadata-cache
---
# Frontmatter links

## Overview

One paragraph: the article's thesis and the facts it rests on.

## <body sections>

Distilled and reorganised from the sources, not copied. Other articles and tickets are wikilinks
in prose: `[[wiki/<project>/<topic>/<slug>|Title]]`, a ticket's from `sbmap link`.
```

Properties, in this order; wikibrain omits an empty list:

| key | values |
|---|---|
| `wiki` | `article`, `synthesis`, `raw`, `topic`, `index`, `log`: what wikibrain and Bases filter on |
| `type` | `concept` (an idea, technique, pattern, the reason behind a decision), `entity` (a named tool, library, API, service, product), `synthesis`, `source` (raw), `topic`: Semantra's node kind |
| `project` | the project folder the note lives in, written by wikibrain so Bases and Semantra can filter on it; `wiki check` keeps it in step with the folder |
| `status` | `current`, `outdated`, `disputed`; articles only |
| `summary` | the note's line in the index, written once, here |
| `updated` | the last change to the knowledge, never a typo fix; articles only |
| `reviewed` | the date the owner accepted the article; set only on the owner's word. Empty or older than `updated` → it is in *To review* |
| `verified` | articles: the full commit an agent re-read the code at and found the article still true, with no new source |
| `archived` | the date a synthesis page was written, in place of `updated` |
| `sources` | wikilinks to raw notes (articles), or to articles and raw notes (synthesis) |
| `related` | wikilinks to related articles: a See Also as typed edges |
| `supersedes`, `superseded_by` | articles this one replaces, or that replace it; always both ends |
| `disputes` | articles that disagree with this one; always both ends |
| `aliases` | other names the concept goes by: what `wiki find` and Obsidian match |
| `tags` | `wiki/<type>`, `project/<project>`, `topic/<topic>`, then the concept tags (`wiki new --tags`, `wiki set tags+=`) |
| `repo`, `commit`, `ref` | raw notes read from a repo: `owner/name`, the full commit and the branch it was read at (`wiki raw --repo-root <clone>` or `--pr` fills them) |
| `pr` | raw notes read from a pull request: its `https://github.com/<owner>/<name>/pull/<n>` URL (`wiki raw --pr`); needs `repo` and `commit` beside it |
| `paths`, `symbols` | raw notes read from a repo: the files or folders, and the identifiers, its claims rest on (`--paths`, `--symbols`); checked to exist at that commit |

**Provenance makes claims checkable.** A claim about code is only as good as the commit it was read
at: a raw note from a repo records where (`repo`, `commit`, `ref`, `pr`, `paths`), so a later check can
diff those paths and grep those symbols on main, or on the branch when the code is not merged yet.
`wikibrain verify --repo-root <clone>` does exactly that for every article of the repo's project:
**current**, **drifted** (a path changed since), **broken** (a path deleted or a symbol gone),
**orphaned** (read on a branch gone from origin and the clone, never merged) or **unanchored** (no source commit;
it then guesses from the article's backticked code and says so). Re-read a drifted or broken
article, update it, and set `verified` to the commit you read.

**Every reference is a full-path wikilink**, its alias the target's `# ` heading. Semantra and
Obsidian then resolve it to exactly one note. A bare `#NNN` resolves to the first ticket of that
number in *any* map: always `sbmap link`. External sources are ordinary `https://` links.

**Two link forms, one graph.** The vault writes `[[wiki/<project>/<topic>/<slug>|Title]]` in the
body and `"[[wiki/raw/<project>/<topic>/<slug>|Title]]"` in list properties. A shared clone writes
what GitHub renders: body links relative to the note's own file, `[Title](../topic/slug.md)`, and
list properties (`sources`, `related`, `supersedes`, `superseded_by`, `disputes`) as plain repo-root
paths, `wiki/raw/<project>/<topic>/<slug>.md`. A store's form is its git config `sb.links`
(`wikilink` or `relative`); without it, a clone with `sb.projects` set is `relative` and anything
else `wikilink`, and every wikibrain write (`new`, `set`, `log`, the index block) uses it. Readers
take either form. The alias always being the heading is what lets a property drop it in the clone
and get it back on import; `wiki check` holds it there. Embeds, links to a section (`#heading`) and
ticket links (`#NNN`) are exempt.

**Tags are edges.** Semantra makes every tag a `tag:<name>` node and links each note to it with a
`tagged` edge, so articles meet through shared tags; a nested `a/b` will also hang under `tag:a`.
So tag what an article is about with a concept tag (`obsidian/metadata-cache`, `three/instancing`),
and never write tag notes: a note under `wiki/tags/` is an ordinary note, not a tag.
`wiki check --fix` keeps `project/` and `topic/` current after a move. Outside Obsidian, Semantra's
folder reader sees frontmatter tags only once its ticket 028 lands.

### Outdated and disputed claims

A claim a newer source replaces stays, marked beneath it, so history is never silently rewritten:

```markdown
> [!warning] Outdated (2026-10-26)
> What changed and what is true now, with the source as a wikilink.

> [!question] Disputed
> Each competing claim, each with its source as a wikilink.
```

`status` is `disputed` exactly while one or more Disputed callouts stand; `outdated` exactly when
`superseded_by` is set (the whole article is replaced); otherwise `current`. Outdated callouts on
single claims leave `status` alone. A dispute between two articles is a callout in each and
`disputes` on both.

### Synthesis pages

An answer worth keeping (`/sb ask --save`): `wiki: synthesis`, `type: synthesis`, `archived`, and
`sources` naming the articles (and any raw notes) it drew on. It has no `status` or `updated`. It is
a point-in-time snapshot: always a new page, never merged into, never cascade-updated. wikibrain
prefixes its summary with `[Archived]`.

### Raw notes and folder notes

`wikibrain raw` writes the properties Obsidian's web clipper writes, so a clipping and a fetched
source read alike: `wiki: raw`, `type: source`, `title`, `source` (URL, or an origin such as
"pasted by the owner"), `author`, `published` (`YYYY-MM-DD` or `Unknown`), `created`,
`tags: [wiki/source, project/<project>, topic/<topic>]`. The body is the source's own text, formatting noise removed, opinions and
wording kept.

A topic's folder note is `wiki: topic`, `type: topic`, `project`, `summary`, `tags: [wiki/topic, project/<project>, topic/<topic>]`, its `# `
heading, and the `--about` text as a paragraph of body: without a body, only the heading is
embedded.

## The grounding invariant

Every **load-bearing literal** in an article (a number, a date, a direct quote) exists verbatim in a
note its `sources` names. `learn` establishes it: locate each value in the source before writing it,
and write it exactly as found (`42K` stays `42K`). A derived value shows its components, each
findable. A value that cannot be located is dropped or stated without precision. `wikibrain check`
verifies it. Synthesis pages are exempt.

## Writing a finding

Every article, synthesis page, folder note and map report has two readers: the owner, reviewing on
a phone, and Semantra's embedding model, placing the note beside the notes it means the same as.
Both want one subject per note, the point first, in plain words.

What Semantra embeds (`embeddableText` in
`packages/web/src/features/obsidian-connector/vaultEmbedding.ts`, `parseNote` in
`packages/core/src/graph/vault/noteFields.ts`): the note's first `# ` heading, then its body with
the properties, fenced code and inline code removed, and with any `Key: value` lines directly under
the heading dropped as header fields. That text is cut at blank lines into passages of up to 200
words (short paragraphs are packed together), each passage is embedded, and the passages are
averaged, each counting the same, into **one vector for the whole note**. So:

- **One subject per note.** A tangent counts as much as the thesis, and a note about three things
  sits near none of them. A second subject is a second article, linked through `related`.
- **A heading that names the subject.** The heading is the only label embedded: name the concept
  in words a search would use ("Obsidian property links"), never a bare identifier or an acronym.
- **The point first.** `## Overview` sits directly under the heading and opens with the `summary`
  sentence (`wiki new` writes it there). Properties are never embedded, so a point made only in
  `summary`, or a synonym only in `aliases`, is invisible to Similar: write the other names into
  the Overview too.
- **Plain words for every name.** Inline code is stripped before embedding. Write "the frontmatter
  link list (`frontmatterLinks`)": the words carry the meaning, the code carries the exact name.
  The same goes for files, commands and settings.
- **Self-contained paragraphs.** Each names its subject in full, for a reader arriving from search
  in the middle of the note. "It", "this ticket", "the bug above" point at nothing there.
- **What is true, not how it was found.** The session's story, the dates of the work, ticket numbers
  and who did what stay on the ticket. The article states the knowledge, when it applies, and what
  to do about it: "When a plugin reads property links, take each link's property name from
  `FrontmatterLinkCache.key`; without it every property link reads as a plain link." An Outdated
  callout says what changed in one or two sentences; it is still embedded, so the current claim
  stays the larger part of the note.
- **How it is known**, in words, on every finding: measured, tested, read in the code, or reported by
  a source. An inference says it is one.
- **References live in properties.** `sources` and `related` carry the evidence and the neighbours.
  A link in prose is embedded path and all, so link only where the reader needs to jump, once per
  target.
- **No stub endings.** The last passage counts as much as the first: an empty section, a
  "Nothing.", or a one-line afterthought at the end pulls the note toward every other note ending
  the same way. Leave an empty section out.
- **Short enough to review.** One screen of Overview, findings under headings, about 600 words in
  all; past that the note is usually two subjects.
- **Headings that are claims.** A section holding a finding is headed by the finding as a sentence
  ("Property links lose their property name"), so the owner can review an article from its outline
  alone, and `wiki show` prints exactly that outline.

## The index and the log

`index.md` holds, between `%% sb:index:start %%` and `%% sb:index:end %%`, one `## <project>` section
per project (`general` first, then alphabetical) and in it one `### <topic>` section per topic,
alphabetical: the folder note's `summary`, then a table (Article as a wikilink, Type,
Summary, Updated, which is `archived` for synthesis), articles by title, synthesis pages last. It is
built from properties alone, so every `wikibrain` write regenerates it, the way writes resync a
map's Route. Never hand-edit the block. Below it, `![[wiki/wiki.base#Needs attention]]`.

`wiki.base` views: *To review* (`reviewed` empty or older than `updated`), *By project* (articles
grouped by `project`, each with its topic folder), *Needs attention* (`status` not `current`), *Recently updated* (by `updated`,
descending), *Synthesis*.

`log.md` is append-only, newest last. Its headings are the machine-readable inventory:

```markdown
## [2026-10-26] learn | [[wiki/general/obsidian/frontmatter-links|Frontmatter links]]
- Disposition: New; Disputed
- Raw: [[wiki/raw/general/obsidian/frontmatter-link-cache|Frontmatter link cache]]
- Updated: [[wiki/general/obsidian/metadata-cache|Metadata cache]]

## [2026-10-26] learn | no material: Clippings/Claude Artifact.md

## [2026-10-26] ask | Archived: [[wiki/general/obsidian/how-semantra-reads-properties|How Semantra reads properties]]

## [2026-10-26] tend | 6 problems, 4 fixed
```

The exact `learn | no material: <vault path>` heading is what keeps a source off the backlog.

## The wikibrain commands

`wikibrain <command>` (`python3 scripts/wikibrain.py <command>`; no command lists them). The sb skill's
`wikibrain <command>` delegates here. Properties go through it; the body
below them is the agent's prose, written with ordinary edit tools. Tickets cited as sources are
read with `sbmap show`, as everywhere.

- `<note>` is any note under `wiki/` (article, synthesis, raw, folder note): a vault path, a
  `<project>/<topic>/<slug>`, or a wikilink.
- `--project <repo>` narrows a read to that project plus `general`: what one repo's work can use.
- `<refs>` are comma-separated vault paths, wikilinks, or `<map>#<NNN>` for a ticket; wikibrain writes
  each in the store's form (a full-path wikilink, or a repo-root path in a relative store) and refuses
  one that names no note.
- Every command reads notes through a graph cache, one JSON file per wiki root in `~/.cache/wikibrain`
  (`WIKIBRAIN_CACHE` moves it): each note's properties, body and edges (`sources`, `related`,
  `supersedes`, `disputes`, `tickets`, `paths`, and body links, wikilink or relative alike), re-read
  only when its mtime or size changes. Delete the file to rebuild; a corrupt one rebuilds itself.

| command | does |
|---|---|
| **read** | |
| `wiki index [--project P] [--write]` | prints every project, topic and article, one line each. The first read of every verb, with `--project` set to the repo's. `--write` restamps the block into `index.md`, adding the markers if missing |
| `wiki find <terms…> [--raw] [--project P] [--limit N]` | case-insensitive; a note matches any term; scored 3 per hit on title or aliases, 2 on summary, 1 in the body. Prints the top N (default 10): path, type, status, summary, score. `--raw` searches raw notes too (every class above), so `ask` works with Obsidian closed |
| `wiki show <note> [--full]` | digest: properties, Overview, headings, every Outdated/Disputed callout. `--full` prints the body |
| `wiki link <note>` | the wikilink to paste into prose; in a relative store the repo-root path (a body link there is relative to the note it sits in) |
| `wiki backlog [--project P] [--limit N]` | raw notes on the backlog that no article's `sources` cites and the log has not marked no-material; oldest `created` first (file time when there is none); default 10, and the total |
| `wiki verify [--repo-root <clone>] [--project P] [--base origin/main] [--json]` | each article of the repo's project (default: the repo's name) checked against its git, worst first: **current**, **drifted** (a path changed since), **broken** (a path deleted or a symbol gone), **orphaned** (read on a branch gone from origin and the clone, never merged), **unanchored** (no source commit: anchored at `updated` with paths and identifiers guessed from backticked code, marked as guessed). Anchor: `verified`, else the newest source commit; target: the base when the anchor is on it, else `origin/<ref>`, else the local `<ref>`. Read-only git, cached |
| **write** | |
| `wiki init` | creates whatever of the layout is missing; never overwrites |
| `wiki raw <project>/<topic> --title "…" --source "…" [--author "…"] [--published YYYY-MM-DD\|Unknown] [--repo-root <clone> [--rev <branch\|sha>] [--paths a,b] [--symbols a,b]] --from <file\|->` | writes a raw note from a file or stdin; the slug comes from the title (`-2` when taken). A `source` URL (or `pr`) another raw note already has prints that note and exits non-zero. Never overwrites. `--repo-root` stamps provenance: `repo` from origin, `commit` and `ref` of HEAD or of `--rev` (read without checking it out; a sha records no ref), and `paths` (each checked to exist at that commit) and `symbols` |
| `wiki raw <project>/<topic> --pr <url> [--title "…"] [--source "…"] [--paths a,b] [--symbols a,b] [--repo-root <clone>]` | a GitHub pull request, read through `gh`, as a raw note in place of `--from`: the body is the description, then the discussion as plain text (comments, reviews with a body, inline review comments led by their file path). No author, no names and no bot comments (`[bot]` accounts) are kept. `title` defaults to the PR's title, `source` to its URL, `published` to the merge date (else the creation date). Merged: `commit` is the merge commit, `ref` the base branch; open or closed unmerged: the head commit and branch. `pr` records the URL; `repo` comes from it; `paths` are the changed files the PR did not delete, narrowed by `--paths` (files or folders; one matching nothing is an error). `--repo-root` is optional: given, the commit and each path are checked in the clone; absent, `gh` is trusted. A missing or failing `gh` is an error |
| `wiki new <project>/<topic>/<slug> --title "…" --type concept\|entity\|synthesis --summary "…" --sources <refs> [--related <refs>] [--aliases "a, b"] [--about "…"]` | scaffolds the note: properties, `# Title`, `## Overview` opening with the summary. A taken slug is an error. A new topic needs `--about`, which writes its folder note. Given only `<topic>/<slug>`, it refuses and names the project its sources come from |
| `wiki set <note> key=value … [key+=<refs>] [key-=<refs>]` | `=` replaces (a list key takes `<refs>`; `aliases`, `tags`, `paths`, `symbols` take comma-separated text), `+=`/`-=` add to or drop from a list; `updated=today` stamps the date. `disputes` and `supersedes`/`superseded_by` are written on both articles; setting `superseded_by` sets `status=outdated` |
| `wiki log <learn\|ask\|tend> --subject "…" [--disposition "New; Update"] [--raw <refs>] [--updated <refs>]` | appends one dated entry; a note path in the subject (`Archived: <path>`) becomes its wikilink, other text stays as written |
| `wiki check [--fix]` | the lint below. Exits non-zero on any format or link problem; grounding suspects and the backlog are printed, never counted |
| `wiki migrate <project> [topic…] [--write]` | moves topics from before projects (`wiki/<topic>/`, `wiki/raw/<topic>/`) under `<project>`, all of them or the named ones; sets `project` on what moved (sources excepted: they are never edited) and repoints every link in `wiki/` and `wayfinder/`. Lists the owner's notes elsewhere that link in, without touching them. A dry run unless `--write` |
| **sync** | |
| `wiki dump <clone> [--projects a,b] [--exclude p/topic,…] [--base main]` | copies the listed projects' notes (`wiki/<p>/`, `wiki/raw/<p>/`, minus excluded topics) into a git clone with their links converted to the clone's form and the vault-only properties dropped, on a new branch `wiki-dump/<date>` cut from the base, refreshes the clone's own `wiki/index.md` and `wiki/log.md`, commits there; never touches the base, never pushes. Refuses on a dirty clone, when the base moved since the last import, or when a note matches the leak gate (machine paths, `obsidian://`, ticket links, any `sb.leak` pattern) |
| `wiki import <clone>` | fast-forwards the clone's base, copies what changed on it since the last import into the vault (adds, edits, deletions) with links converted back to wikilinks and the vault copy's vault-only properties kept, lists a note changed on both sides instead of overwriting it (exit 1), then reindexes the vault. Both sides are compared in the clone's form without vault-only properties, so a clone note still in wikilink form compares alike. The last import is the ref `refs/sb/last-sync` in the clone |

### What `wiki check` enforces

- **Fixed with `--fix`:** the index block out of date; a wikilink whose target moved, when one note
  has that file name; a `related` link to a note that no longer exists (dropped); a `project`
  property that disagrees with the note's folder; a link whose alias (wikilink) or text (relative
  link) is not its target's `# ` heading, in properties and prose, on articles, synthesis pages and
  folder notes alike.
- **Format:** an unknown `wiki`, `type` or `status`; a property missing for its kind (an article
  without `summary`, `updated`, `status` or `sources`; a synthesis without `archived` or `sources`);
  `status` disagreeing with the rule under *Outdated and disputed claims*; an Outdated callout
  without its date; one end missing from `supersedes`/`superseded_by` or `disputes`; a topic folder
  without its folder note; a slug taken twice (folder notes aside), or starting with digits and a
  dash; a note anywhere but `wiki/<project>/<topic>/` or `wiki/raw/<project>/<topic>/`; a topic from
  before projects.
- **Provenance:** a raw note with any of `repo`, `commit`, `ref`, `pr`, `paths`, `symbols` needs `repo`
  (`owner/name`) and a full 40-character `commit`; a `pr` is a GitHub pull request URL; `paths` and `symbols` are lists (`--fix` turns
  comma-separated text into a list); provenance on a note that is not raw, or a `verified` that is
  not a full commit on an article, is an error.
- **Links:** a markdown link to a vault note (in a wikilink store), or a wikilink by bare file name,
  where a full-path wikilink belongs; a relative link or a repo-root path that names no file; a bare `#NNN`; a `sources` entry of the wrong class for its note; a source ticket
  that is not resolved; broken links, read from the files, so Obsidian need not be running. Links
  inside inline code and code blocks are text, never checked.
- **Grounding suspects:** each article's candidate literals (quotes of 15+ characters, ISO dates,
  numbers that are grouped, dotted, suffixed `K`/`M`/`B`/`%`, or 4+ digits) searched for in the
  bodies of its sources, case-sensitive, with whitespace collapsed and curly quotes made straight on
  both sides. A miss is a suspect, not a verdict: a derived value or a product name may be fine.
  Port the candidate set from the karpathy skill's `scripts/check_evidence.py`, keeping its MIT
  notice on the ported code.

## Sharing projects through a git clone

Some projects are shared with a team (the monorepo's knowledge with `assemblio-development/llm-wiki`).
The vault stays whole and primary; a clone of the shared repo sits outside it, and `wiki dump` /
`wiki import` move only the listed projects between them. The format and the properties are the
same on both sides; only the links change form (*Two link forms, one graph*): dump writes them
relative and import writes them back as wikilinks, and since every alias is its target's heading,
import(dump(note)) is the note again. A note with no link to convert crosses byte for byte, and a
raw note's body is its source's own text, so it crosses as written (its properties still convert).
Links inside inline code and code blocks are text and never converted. Vault-only properties, the
clone's git config `sb.vaultOnly` (comma-separated, default `tickets`), are dropped on dump; import
keeps the vault copy's values and never compares them. The clone remembers its projects, excluded
topics, base branch, vault-only properties and extra leak patterns in its git config
(`sb.projects`, `sb.exclude`, `sb.base`, `sb.vaultOnly`, `sb.leak`). Every change reaches the base by pull
request: dump makes the owner's branch, teammates make theirs, and import brings merged work back.
Repo-only files (the clone's README, AGENTS.md, CI, `wiki/index.md`, `wiki/log.md`) never enter
the vault, and the vault's index, log, `wiki.base` and `wayfinder/` never leave it. Sources that
are tickets do not travel: keep a ticket's finding as a raw note before citing it in a shared project.

Teammates work the shared repo without the vault and without installing sb: the `team-wiki` skill
(in the team's skills repo) runs ask, learn, verify, lint, and `export`/`import` (this file's dump
and import, for anyone's own wiki folder) through `sbmap.py`, `sbwiki.py` and `sbsync.py`, fetched
from GitHub at a pinned commit (`TOOLS_COMMIT`) into a per-user cache by a small loader. The shared
repo's CI runs `wiki check` through a copy of that loader pinned to the same commit; bump both pins
together when the tools change. `wiki dump` writes the pull request's description to
`.git/sb-dump-pr.md` in the clone (new and changed notes in tables, what changed, how to review),
and team-wiki's learn PRs use the same shape.

## How Semantra reads it

Semantra's Obsidian connector turns each note into a node (`type` → kind; every property flat on
the node), each folder into a `contains` parent, each tag into a node, each resolved link into an
edge. So the wiki needs no Semantra-specific markup:

- articles, sources and synthesis pages are distinct node kinds, grouped under `wiki`;
- `sources`, `related`, `supersedes`, `disputes` are edges; `status` and `updated` are queryable
  properties (*every disputed article*, *what changed this week*).

**Depends on Semantra:** today the plugin turns every property link into a plain `links_to`, so
`sources` and `disputes` look alike (`packages/obsidian-plugin/src/host/indexSnapshot.ts`, which
drops Obsidian's `FrontmatterLinkCache.key`). Once the property name becomes the relation, these
edges arrive typed with no change to the format. The same fix restores typed `blocked_by` edges on
tickets. The browser connector (`readVault`) also drops YAML list properties; the plugin does not.

Two embedding changes would help any vault, this one included:

- The embedded text keeps each link as written, path and all. Embedding a link's display text
  instead (the alias of `[[path|alias]]`, the text of `[text](path)`) would let prose link freely.
- Every note is embedded, `index.md` and `log.md` too. They mention every topic, so they sit near
  everything in Similar, and the log grows without end. A property that keeps a note out of meaning
  (on the index, the log and the README) would remove that noise.

Synthesis pages restate their articles, so they sit beside them in Similar. That is expected; the
`synthesis` kind filters them out.
