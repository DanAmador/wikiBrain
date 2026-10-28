import subprocess
import unittest
from pathlib import Path

from helpers import VaultCase

ARTICLE = """---
wiki: article
type: concept
project: monorepo
status: current
summary: "{s}"
updated: 2026-10-28
sources:
  - "[[wiki/raw/monorepo/rendering/src|Source]]"
tags:
  - wiki/concept
---
# {t}

## Overview

{s}
"""
RAW = """---
wiki: raw
type: source
project: monorepo
title: Source
source: "repo@abc:README.md"
---
# Source

The text.
"""


class SyncCase(VaultCase):
    def setUp(self):
        super().setUp()
        self.clone = Path(self._tmp.name) / "llm-wiki"
        self.clone.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "T")
        (self.clone / "README.md").write_text("# llm-wiki\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "init")
        self.sb("wiki", "init")
        self.write("wiki/monorepo/rendering/rendering.md", "---\nwiki: topic\ntype: topic\nproject: monorepo\n---\n# Rendering\n")
        self.write("wiki/monorepo/rendering/meshproxy.md", ARTICLE.format(t="MeshProxy", s="Parts are bones."))
        self.write("wiki/raw/monorepo/rendering/src.md", RAW)
        self.write("wiki/monorepo/private/mine.md", ARTICLE.format(t="Mine", s="Owner only."))
        self.write("wiki/sk4te/x/y.md", ARTICLE.format(t="Other", s="Another project."))

    def git(self, *args, cwd=None):
        r = subprocess.run(["git", "-C", str(cwd or self.clone), *args], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def dump(self, ok=True):
        return self.sb("wiki", "dump", str(self.clone), "--projects", "monorepo",
                       "--exclude", "monorepo/private", ok=ok)

    def merge_dump(self):
        branch = self.git("branch", "--show-current").strip()
        self.git("switch", "-q", "main")
        self.git("merge", "-q", "--ff-only", branch)

    def teammate_edit(self, rel, text):
        (self.clone / rel).write_text(text)
        self.git("commit", "-q", "-am", "teammate")


class DumpTest(SyncCase):
    def test_dump_copies_listed_projects_on_a_branch_and_leaves_the_rest(self):
        r = self.dump()
        self.assertIn("wiki-dump/", r.stdout)
        self.assertTrue(self.git("branch", "--show-current").startswith("wiki-dump/"))
        meshproxy, src = "wiki/monorepo/rendering/meshproxy.md", "wiki/raw/monorepo/rendering/src.md"
        self.assertEqual((self.clone / meshproxy).read_text(), self.read(meshproxy).replace(
            '"[[wiki/raw/monorepo/rendering/src|Source]]"', "wiki/raw/monorepo/rendering/src.md"))
        self.assertEqual((self.clone / src).read_bytes(), (self.vault / src).read_bytes())
        self.assertFalse((self.clone / "wiki/monorepo/private").exists())
        self.assertFalse((self.clone / "wiki/sk4te").exists())
        self.assertIn("MeshProxy", (self.clone / "wiki/index.md").read_text())
        self.assertIn("dump | monorepo", (self.clone / "wiki/log.md").read_text())
        self.assertEqual(self.git("show", "main:README.md"), "# llm-wiki\n")
        body = (self.clone / ".git/sb-dump-pr.md").read_text()
        self.assertIn("### Articles (1)", body)
        self.assertIn("| 🆕 | **MeshProxy**: Parts are bones. | rendering | new |", body)
        self.assertIn("### Sources (raw notes) (1)", body)
        self.assertIn("links converted to relative links and the vault-only properties (tickets) dropped", body)
        self.assertIn("gh pr create", r.stdout)

    def test_projects_are_remembered_and_a_second_dump_has_nothing_new(self):
        self.dump()
        self.merge_dump()
        self.sb("wiki", "import", str(self.clone))
        r = self.sb("wiki", "dump", str(self.clone))
        self.assertIn("nothing to dump", r.stdout)

    def test_leak_gate_refuses_a_machine_path(self):
        self.write("wiki/monorepo/rendering/meshproxy.md",
                   ARTICLE.format(t="MeshProxy", s="See /Users/someone/notes."))
        r = self.dump(ok=False)
        self.assertIn("leak gate", r.stdout + r.stderr)
        self.assertEqual(self.git("branch", "--show-current").strip(), "main")

    def test_dump_refuses_until_merged_changes_are_imported(self):
        self.dump()
        self.merge_dump()
        self.sb("wiki", "import", str(self.clone))
        self.teammate_edit("wiki/monorepo/rendering/meshproxy.md", ARTICLE.format(t="MeshProxy", s="Teammate."))
        r = self.sb("wiki", "dump", str(self.clone), ok=False)
        self.assertIn("run `wikibrain import", r.stdout + r.stderr)


class ImportTest(SyncCase):
    def setUp(self):
        super().setUp()
        self.dump()
        self.merge_dump()
        self.sb("wiki", "import", str(self.clone))

    def test_a_teammate_change_reaches_the_vault(self):
        self.teammate_edit("wiki/monorepo/rendering/meshproxy.md", ARTICLE.format(t="MeshProxy", s="Teammate."))
        r = self.sb("wiki", "import", str(self.clone))
        self.assertIn("1 imported", r.stdout)
        self.assertIn("Teammate.", self.read("wiki/monorepo/rendering/meshproxy.md"))
        self.assertIn("Owner only.", self.read("wiki/monorepo/private/mine.md"))

    def test_a_vault_edit_dumps_after_import(self):
        self.write("wiki/monorepo/rendering/meshproxy.md", ARTICLE.format(t="MeshProxy", s="Owner edit."))
        self.dump()
        self.assertIn("Owner edit.", (self.clone / "wiki/monorepo/rendering/meshproxy.md").read_text())
        body = (self.clone / ".git/sb-dump-pr.md").read_text()
        self.assertIn("| 💬 | **MeshProxy** | rendering | text, summary |", body)

    def test_a_note_changed_on_both_sides_is_reported_and_kept(self):
        self.write("wiki/monorepo/rendering/meshproxy.md", ARTICLE.format(t="MeshProxy", s="Owner edit."))
        self.teammate_edit("wiki/monorepo/rendering/meshproxy.md", ARTICLE.format(t="MeshProxy", s="Teammate."))
        r = self.sb("wiki", "import", str(self.clone), ok=False)
        self.assertIn("1 conflicts", r.stdout)
        self.assertIn("Owner edit.", self.read("wiki/monorepo/rendering/meshproxy.md"))
        r = self.sb("wiki", "dump", str(self.clone), ok=False)
        self.assertIn("run `wikibrain import", r.stdout + r.stderr)

    def test_a_teammate_deletion_reaches_the_vault(self):
        self.git("rm", "-q", "wiki/raw/monorepo/rendering/src.md")
        self.git("commit", "-q", "-m", "drop")
        self.sb("wiki", "import", str(self.clone))
        self.assertFalse(self.exists("wiki/raw/monorepo/rendering/src.md"))


TAGS = "tags:\n  - wiki/{k}\n  - project/monorepo\n  - topic/rendering\n---\n"
LINKED = {
    "wiki/monorepo/rendering/rendering.md": "---\nwiki: topic\ntype: topic\nproject: monorepo\n"
    "summary: How the viewer draws parts.\n" + TAGS.format(k="topic") + "# Rendering\n\n"
    "How the viewer draws parts: [[wiki/monorepo/rendering/meshproxy|MeshProxy]].\n",
    "wiki/monorepo/rendering/meshproxy.md": """---
wiki: article
type: concept
project: monorepo
status: current
summary: Parts are bones.
updated: 2026-10-28
sources:
  - "[[wiki/raw/monorepo/rendering/src|Source]]"
  - "[[wiki/raw/monorepo/rendering/notes|Field notes]]"
related:
  - "[[wiki/monorepo/rendering/raycast|Raycast picking]]"
tickets:
  - "[[wayfinder/monorepo/x/issues/001-a|#001]]"
""" + TAGS.format(k="concept") + """# MeshProxy

## Overview

Parts are bones, read from [[wiki/raw/monorepo/rendering/src|Source]], picked by
[[wiki/monorepo/rendering/raycast#How it works|Raycast picking]] in [[wiki/monorepo/rendering/rendering|Rendering]].
Docs: [three](https://threejs.org/docs/x.md). Code is text: `[[wiki/monorepo/rendering/raycast|R]]`.

```
[[wiki/raw/monorepo/rendering/src|Source]]
```
""",
    "wiki/monorepo/rendering/raycast.md": ARTICLE.format(t="Raycast picking", s="Rays pick parts.").replace(
        "  - wiki/concept\n", "  - wiki/concept\n  - project/monorepo\n  - topic/rendering\n")
    + "\n## How it works\n\nA ray from [[wiki/monorepo/rendering/meshproxy|MeshProxy]].\n",
    "wiki/raw/monorepo/rendering/notes.md": "---\nwiki: raw\ntype: source\nproject: monorepo\ntitle: Field notes\n"
    "source: pasted by the owner\nrelated:\n  - \"[[wiki/raw/monorepo/rendering/src|Source]]\"\n---\n"
    "As [[wiki/raw/monorepo/rendering/src|Source]] says, parts are bones. Its guide: [/AGENTS.md](../../AGENTS.md).\n",
}


class RoundTrip(SyncCase):
    """The vault writes wikilinks, the clone relative links; import(export(x)) gives back x."""

    def setUp(self):
        super().setUp()
        for rel, text in LINKED.items():
            self.write(rel, text)
        self.want = {rel: self.read(rel) for rel in [*LINKED, "wiki/raw/monorepo/rendering/src.md"]}
        self.dump()

    def clone_text(self, rel):
        return (self.clone / rel).read_text()

    def test_dump_converts_links_and_drops_vault_only_properties(self):
        art = self.clone_text("wiki/monorepo/rendering/meshproxy.md")
        self.assertIn("sources:\n  - wiki/raw/monorepo/rendering/src.md\n  - wiki/raw/monorepo/rendering/notes.md\n"
                      "related:\n  - wiki/monorepo/rendering/raycast.md\ntags:", art)
        self.assertNotIn("wayfinder", art)
        self.assertIn("read from [Source](../../raw/monorepo/rendering/src.md), picked by\n"
                      "[Raycast picking](raycast.md#How%20it%20works) in [Rendering](rendering.md).", art)
        self.assertIn("[three](https://threejs.org/docs/x.md)", art)
        self.assertIn("`[[wiki/monorepo/rendering/raycast|R]]`", art)
        self.assertIn("```\n[[wiki/raw/monorepo/rendering/src|Source]]\n```", art)
        self.assertIn("[MeshProxy](meshproxy.md)", self.clone_text("wiki/monorepo/rendering/rendering.md"))
        src, notes = "wiki/raw/monorepo/rendering/src.md", "wiki/raw/monorepo/rendering/notes.md"
        self.assertEqual((self.clone / src).read_bytes(), (self.vault / src).read_bytes())
        self.assertEqual(self.clone_text(notes), self.read(notes).replace(  # a source's text is never converted
            '  - "[[wiki/raw/monorepo/rendering/src|Source]]"', "  - wiki/raw/monorepo/rendering/src.md"))
        self.assertIn("| [MeshProxy](monorepo/rendering/meshproxy.md) |", self.clone_text("wiki/index.md"))
        self.assertIn("0 problem(s)", self.sb("wiki", "check", vault=self.clone).stdout)

    def test_import_of_the_export_gives_back_every_note(self):
        self.merge_dump()
        for rel in self.want:
            if rel != "wiki/monorepo/rendering/meshproxy.md":
                (self.vault / rel).unlink()
        r = self.sb("wiki", "import", str(self.clone))
        self.assertIn("4 imported, 0 deleted, 0 conflicts", r.stdout)
        for rel, text in self.want.items():
            self.assertEqual(self.read(rel), text, rel)

    def test_a_teammate_edit_comes_back_with_the_vault_only_properties(self):
        self.merge_dump()
        self.sb("wiki", "import", str(self.clone))
        rel = "wiki/monorepo/rendering/meshproxy.md"
        self.teammate_edit(rel, self.clone_text(rel).replace("Parts are bones, read", "Parts are joints, read"))
        self.assertIn("1 imported", self.sb("wiki", "import", str(self.clone)).stdout)
        self.assertEqual(self.read(rel), self.want[rel].replace("Parts are bones, read", "Parts are joints, read"))

    def test_conflicts_are_found_in_repo_form_and_never_over_vault_only_properties(self):
        self.merge_dump()
        self.sb("wiki", "import", str(self.clone))
        rel = "wiki/monorepo/rendering/meshproxy.md"
        self.write(rel, self.want[rel].replace("001-a|#001", "002-b|#002"))
        self.teammate_edit(rel, self.clone_text(rel).replace("Parts are bones, read", "Parts are joints, read"))
        self.assertIn("1 imported, 0 deleted, 0 conflicts", self.sb("wiki", "import", str(self.clone)).stdout)
        self.assertIn("002-b|#002", self.read(rel))
        self.write(rel, self.read(rel).replace("Parts are joints", "Parts are owner's"))
        self.teammate_edit(rel, self.clone_text(rel).replace("Parts are joints", "Parts are teammate's"))
        self.assertIn("1 conflicts", self.sb("wiki", "import", str(self.clone), ok=False).stdout)
        self.assertIn("Parts are owner's", self.read(rel))


if __name__ == "__main__":
    unittest.main()
