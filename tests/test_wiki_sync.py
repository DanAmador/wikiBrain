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
        meshproxy = "wiki/monorepo/rendering/meshproxy.md"
        self.assertEqual((self.clone / meshproxy).read_bytes(), (self.vault / meshproxy).read_bytes())
        self.assertTrue((self.clone / "wiki/raw/monorepo/rendering/src.md").exists())
        self.assertFalse((self.clone / "wiki/monorepo/private").exists())
        self.assertFalse((self.clone / "wiki/sk4te").exists())
        self.assertIn("MeshProxy", (self.clone / "wiki/index.md").read_text())
        self.assertIn("dump | monorepo", (self.clone / "wiki/log.md").read_text())
        self.assertEqual(self.git("show", "main:README.md"), "# llm-wiki\n")
        body = (self.clone / ".git/sb-dump-pr.md").read_text()
        self.assertIn("### Articles (1)", body)
        self.assertIn("| 🆕 | **MeshProxy**: Parts are bones. | rendering | new |", body)
        self.assertIn("### Sources (raw notes) (1)", body)
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


if __name__ == "__main__":
    unittest.main()
