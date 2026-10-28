---
name: wikibrain
description: "An LLM wiki's tools (Karpathy's LLM-wiki pattern, in a typed Obsidian-friendly format): read and author notes, index, check format, links and grounding, verify claims against git, and sync chosen projects with a shared git repo by pull request. Used by the sb skill and by team wikis; not a workflow on its own."
---

# wikibrain

The tools of a markdown wiki where sources are kept as raw notes, articles are compiled from them and
cite them, and every field is a frontmatter property and every reference a full-path wikilink. The
format, and how to write a finding, is [reference/wiki.md](reference/wiki.md): read it before the
first write.

## Run

```bash
SB_VAULT=<folder holding wiki/> python3 <this skill>/scripts/wikibrain.py <command> [args]
```

No command lists them all. `SB_VAULT` is the vault root (an Obsidian vault or a wiki repo clone).

| | commands |
|---|---|
| read | `index`, `find`, `show`, `link`, `backlog`, `verify` |
| write | `init`, `raw`, `new`, `set`, `log`, `check [--fix]`, `migrate` |
| sync | `dump <clone>`, `import <clone>`: chosen projects ↔ a shared git clone, byte for byte, by PR |

## Rules

- Standard library only: `python3`, plus `git` for `raw --repo-root`, `verify`, `dump` and `import`.
- Raw notes are never edited after they are kept; articles are compiled from them.
- `dump` never pushes and never commits to the base branch; `import` never overwrites a note changed
  on both sides.
