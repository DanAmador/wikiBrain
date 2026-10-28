# wikiBrain

The tools of an LLM wiki: [Karpathy's LLM-wiki pattern](https://github.com/astro-han/karpathy-llm-wiki)
(sources kept, articles compiled from them, cited, compounding) in a typed, Obsidian-friendly format:
every field a property, every reference a full-path wikilink. One skill, `skills/wikibrain/`, that the
[sb](https://github.com/DanAmador/SB) workflow and team wikis build on.

- **Format:** [skills/wikibrain/reference/wiki.md](skills/wikibrain/reference/wiki.md)
- **Commands:** `python3 skills/wikibrain/scripts/wikibrain.py` lists them: read, write, check,
  verify against git, and `dump`/`import` to sync chosen projects with a shared git repo by PR.

## Use it

- **As a skill:** `npx skills add DanAmador/wikiBrain -g -s wikibrain`.
- **Pinned from another repo:** reference a commit, as sb does in its `skills-lock.json`, or fetch the
  scripts at a commit (see [agent-stuff](https://github.com/assemblio-development/agent-stuff)'s
  team-wiki). Want to change it for your team? Fork it and pin your fork.

## Tests

```bash
python3 -m unittest discover tests
```

Standard library only. MIT.
