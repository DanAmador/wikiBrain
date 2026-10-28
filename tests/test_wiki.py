import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import TODAY, VaultCase


class InitAndNew(VaultCase):
    def test_init_creates_the_layout_and_never_overwrites(self):
        self.sb("wiki", "init")
        for f in ("wiki/index.md", "wiki/log.md", "wiki/wiki.base", "wiki/README.md"):
            self.assertTrue(self.exists(f), f)
        self.assertTrue((self.vault / "wiki/raw").is_dir())
        self.assertIn("%% sb:index:start %%", self.read("wiki/index.md"))
        self.assertIn("![[wiki/wiki.base#Needs attention]]", self.read("wiki/index.md"))
        self.write("wiki/log.md", "mine\n")
        self.sb("wiki", "init")
        self.assertEqual(self.read("wiki/log.md"), "mine\n")

    def test_new_article_scaffolds_properties_heading_and_overview(self):
        self.sb("wiki", "init")
        self.write("wiki/raw/general/obsidian/link-cache.md", "---\nwiki: raw\ntype: source\ntitle: Link cache\n"
                   "source: https://example.com/a\n---\nBody.\n")
        self.sb("wiki", "new", "general/obsidian/frontmatter-links", "--title", "Frontmatter links",
                "--type", "concept", "--summary", "Property links lose their name.",
                "--sources", "wiki/raw/general/obsidian/link-cache", "--aliases", "frontmatterLinks, fm links",
                "--about", "How Obsidian stores and indexes notes.")
        text = self.read("wiki/general/obsidian/frontmatter-links.md")
        self.assertTrue(text.startswith("---\nwiki: article\ntype: concept\nproject: general\nstatus: current\n"), text)
        self.assertIn(f"updated: {TODAY}", text)
        self.assertIn('  - "[[wiki/raw/general/obsidian/link-cache|Link cache]]"', text)
        self.assertIn("  - frontmatterLinks\n  - fm links\n", text)
        self.assertIn("  - wiki/concept", text)
        self.assertIn("# Frontmatter links\n\n## Overview\n\nProperty links lose their name.", text)
        folder = self.read("wiki/general/obsidian/obsidian.md")
        self.assertIn("wiki: topic", folder)
        self.assertIn("type: topic", folder)
        self.assertIn("How Obsidian stores and indexes notes.", folder.split("---", 2)[2])

    def test_new_refuses_a_taken_slug_a_new_topic_without_about_and_a_dated_slug(self):
        self.sb("wiki", "init")
        self.write("wiki/raw/p/t/s.md", "---\nwiki: raw\ntype: source\ntitle: S\nsource: x\n---\nB\n")
        base = ["--type", "concept", "--summary", "S.", "--sources", "wiki/raw/p/t/s"]
        self.sb("wiki", "new", "p/topic/thing", "--title", "Thing", *base, ok=False)  # no --about
        self.sb("wiki", "new", "p/topic/thing", "--title", "Thing", *base, "--about", "A topic.")
        self.sb("wiki", "new", "p/topic/thing", "--title", "Thing", *base, ok=False)
        self.sb("wiki", "new", "p/topic/2026-plan", "--title", "Plan", *base, ok=False)
        self.sb("wiki", "new", "p/raw/thing2", "--title", "T", *base, "--about", "x", ok=False)

    def test_new_refuses_sources_that_name_no_note_or_the_wrong_class(self):
        self.sb("wiki", "init")
        self.sb("wiki", "new", "p/t/a", "--title", "A", "--type", "concept", "--summary", "S.",
                "--sources", "wiki/raw/p/t/missing", "--about", "x", ok=False)
        self.write("Notes/mine.md", "# Mine\n")
        self.sb("wiki", "new", "p/t/a", "--title", "A", "--type", "concept", "--summary", "S.",
                "--sources", "Notes/mine", "--about", "x", ok=False)

    def test_new_synthesis_is_archived_and_cites_articles(self):
        self.sb("wiki", "init")
        self.write("wiki/raw/p/t/s.md", "---\nwiki: raw\ntype: source\ntitle: S\nsource: x\n---\nB\n")
        self.sb("wiki", "new", "p/t/a", "--title", "A", "--type", "concept", "--summary", "S.",
                "--sources", "wiki/raw/p/t/s", "--about", "x")
        self.sb("wiki", "new", "p/t/how-a-works", "--title", "How A works", "--type", "synthesis",
                "--summary", "A works.", "--sources", "p/t/a")
        text = self.read("wiki/p/t/how-a-works.md")
        self.assertIn("wiki: synthesis", text)
        self.assertIn(f"archived: {TODAY}", text)
        self.assertIn('summary: "[Archived] A works."', text)
        self.assertNotIn("status:", text)
        self.assertNotIn("updated:", text)
        self.assertIn("## Overview\n\nA works.", text)

    def test_ticket_sources_are_full_path_links_and_must_be_resolved(self):
        self.sb("wiki", "init")
        self.map("semantra/plugin")
        self.ticket("semantra/plugin", 7, "Does it read links")
        self.ticket("semantra/plugin", 8, "Still open", status="Project.Planned")
        self.sb("wiki", "new", "p/t/a", "--title", "A", "--type", "concept", "--summary", "S.",
                "--sources", "semantra/plugin#007", "--about", "x")
        self.assertIn('"[[wayfinder/semantra/plugin/issues/007-does-it-read-links|#007]]"',
                      self.read("wiki/p/t/a.md"))
        self.sb("wiki", "new", "p/t/b", "--title", "B", "--type", "concept", "--summary", "S.",
                "--sources", "semantra/plugin#8", ok=False)


class Seeded(VaultCase):
    """A wiki with one topic, one source and one article."""

    def setUp(self):
        super().setUp()
        self.sb("wiki", "init")
        self.write("wiki/raw/general/obsidian/link-cache.md", "---\nwiki: raw\ntype: source\ntitle: Link cache\n"
                   "source: https://example.com/a\ncreated: 2026-01-02\n---\n"
                   "The cache holds 42K links, measured on 2026-03-01.\n")
        self.sb("wiki", "new", "general/obsidian/frontmatter-links", "--title", "Obsidian property links",
                "--type", "concept", "--summary", "Property links lose their property name.",
                "--sources", "wiki/raw/general/obsidian/link-cache", "--aliases", "frontmatterLinks",
                "--about", "How Obsidian stores notes.")
        self.article = "wiki/general/obsidian/frontmatter-links.md"

    def append(self, rel, text):
        self.write(rel, self.read(rel) + text)


class Read(Seeded):
    def test_index_prints_one_line_per_article_and_write_stamps_a_table(self):
        out = self.sb("wiki", "index").stdout
        self.assertIn("# general\n## obsidian: How Obsidian stores notes.", out)
        self.assertIn("wiki/general/obsidian/frontmatter-links · concept · current · Property links lose", out)
        idx = self.read("wiki/index.md")
        self.assertIn("| [[wiki/general/obsidian/frontmatter-links\\|Obsidian property links]] | concept |", idx)
        self.assertIn(f"| {TODAY} |", idx)

    def test_index_without_a_wiki_says_so(self):
        import shutil
        shutil.rmtree(self.vault / "wiki")
        self.assertIn("wikibrain init", self.sb("wiki", "index").stdout)

    def test_link_prints_the_full_path_wikilink(self):
        for arg in ("general/obsidian/frontmatter-links", self.article, "[[wiki/general/obsidian/frontmatter-links]]"):
            self.assertEqual(self.sb("wiki", "link", arg).stdout.strip(),
                             "[[wiki/general/obsidian/frontmatter-links|Obsidian property links]]")

    def test_show_prints_the_outline_and_callouts_not_the_body(self):
        self.append(self.article, "\nA long paragraph only --full prints.\n\n## Links lose their name\n\n"
                    "> [!question] Disputed\n> Two sources disagree.\n\nMore.\n")
        out = self.sb("wiki", "show", "general/obsidian/frontmatter-links").stdout
        self.assertIn("# Obsidian property links", out)
        self.assertIn("status: current", out)
        self.assertIn("Property links lose their property name.", out)
        self.assertIn("## Links lose their name", out)
        self.assertIn("> Two sources disagree.", out)
        self.assertNotIn("More.", out)
        self.assertIn("More.", self.sb("wiki", "show", "general/obsidian/frontmatter-links", "--full").stdout)

    def test_show_prints_a_callout_in_the_overview_once(self):
        self.append(self.article, "\n> [!warning] Outdated (2026-10-01)\n> Was X.\n")
        self.assertEqual(self.sb("wiki", "show", self.article).stdout.count("> Was X."), 1)

    def test_find_scores_title_over_summary_over_body(self):
        self.sb("wiki", "new", "general/obsidian/metadata-cache", "--title", "Metadata cache", "--type", "entity",
                "--summary", "Where Obsidian keeps parsed links.", "--sources", "wiki/raw/general/obsidian/link-cache")
        self.append("wiki/general/obsidian/metadata-cache.md", "\nIt mentions frontmatterLinks once.\n")
        out = self.sb("wiki", "find", "FRONTMATTERLINKS").stdout.splitlines()
        self.assertTrue(out[0].startswith("wiki/general/obsidian/frontmatter-links"), out)
        self.assertTrue(out[1].startswith("wiki/general/obsidian/metadata-cache"), out)
        self.assertNotIn("link-cache", "\n".join(out))
        self.assertIn("wiki/raw/general/obsidian/link-cache", self.sb("wiki", "find", "42K", "--raw").stdout)
        self.assertEqual(self.sb("wiki", "find", "nothingmatches").stdout.strip(), "no matches")

    def test_find_raw_reaches_clippings_research_and_resolved_tickets(self):
        self.write("Clippings/Some page.md", "---\nsource: https://x.org\n---\nzebra here\n")
        self.map("m/one")
        self.write("wayfinder/m/one/research/notes.md", "# Notes\n\nzebra again\n")
        self.ticket("m/one", 1, "Zebra ticket")
        self.ticket("m/one", 2, "Zebra open", status="Project.Planned")
        out = self.sb("wiki", "find", "zebra", "--raw").stdout
        self.assertIn("Clippings/Some page", out)
        self.assertIn("wayfinder/m/one/research/notes", out)
        self.assertIn("wayfinder/m/one/issues/001-zebra-ticket", out)
        self.assertNotIn("002-zebra-open", out)


class Graph(Seeded):
    """The cached graph index behind index, find, show and backlog."""

    READS = (("index",), ("find", "links", "--raw"), ("show", "general/obsidian/frontmatter-links", "--full"),
             ("backlog",))

    def setUp(self):
        super().setUp()
        self.write("Clippings/Page.md", "---\ncreated: 2026-02-01\n---\nlinks everywhere\n")
        self.map("m/one")
        self.ticket("m/one", 1, "Links research")

    def notes(self):
        return [p for p in self.vault.rglob("*.md")]

    def test_a_second_read_touches_no_note_file_and_prints_the_same(self):
        first = [self.sb("wiki", *a).stdout for a in self.READS]
        self.assertEqual(len(list(self.cache.glob("*.json"))), 1)
        notes = self.notes()
        try:
            for p in notes:
                p.chmod(0)
            if os.access(notes[0], os.R_OK):
                self.skipTest("file modes do not bind this user")
            second = [self.sb("wiki", *a).stdout for a in self.READS]
        finally:
            for p in notes:
                p.chmod(0o644)
        self.assertEqual(first, second)

    def test_an_edited_note_is_read_again(self):
        self.sb("wiki", "index")
        p = self.vault / self.article
        p.write_text(p.read_text(encoding="utf-8").replace("lose their property name", "keep their name"),
                     encoding="utf-8")
        st = p.stat()
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 10**10))
        self.assertIn("Property links keep their name.", self.sb("wiki", "index").stdout)
        self.assertIn("keep their name", self.sb("wiki", "find", "keep").stdout)

    def test_a_corrupt_cache_rebuilds(self):
        want = self.sb("wiki", "index").stdout
        for f in self.cache.glob("*.json"):
            f.write_text('{"v": 1, "notes": {"x"', encoding="utf-8")
        self.assertEqual(self.sb("wiki", "index").stdout, want)
        self.assertEqual(json.loads(next(self.cache.glob("*.json")).read_text())["v"], 1)

    def test_wikilinks_and_relative_links_name_the_same_targets(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "wikibrain" / "scripts"))
        import wikibrain
        props = {"sources": ["[[wiki/raw/p/t/x|X]]"], "tickets": ["[[wayfinder/m/one/issues/001-a|#001]]"],
                 "related": ["wiki/p/t/b.md"], "paths": ["src/a.md"]}
        vault = wikibrain.edges(props, "See [[wiki/p/u/c|C]] and [[wiki/p/u/c#Part|C]].", "wiki/p/t/a.md")
        clone = wikibrain.edges(props, "See [C](../u/c.md) and [C](../u/c.md#part), [site](https://x.org/c.md).",
                                "wiki/p/t/a.md")
        self.assertEqual(vault, clone)
        self.assertIn(["link", "wiki/p/u/c"], vault)
        self.assertIn(["sources", "wiki/raw/p/t/x"], vault)
        self.assertIn(["related", "wiki/p/t/b"], vault)
        self.assertIn(["tickets", "wayfinder/m/one/issues/001-a"], vault)
        self.assertIn(["paths", "src/a.md"], vault)
        self.assertEqual(len(vault), 5)


class Raw(Seeded):
    def test_raw_keeps_the_text_exactly_with_clipper_properties(self):
        r = self.sb("wiki", "raw", "general/obsidian", "--title", "2026 Bases syntax", "--source",
                    "https://example.com/bases", "--author", "Obsidian", "--from", "-",
                    stdin="Bases filter with  two spaces.\n")
        path = r.stdout.strip()
        self.assertEqual(path, "wiki/raw/general/obsidian/bases-syntax-2026.md")
        text = self.read(path)
        for line in ("wiki: raw", "type: source", "title: 2026 Bases syntax", '"https://example.com/bases"',
                     "author: Obsidian", "published: Unknown", f"created: {TODAY}", "  - wiki/source"):
            self.assertIn(line, text)
        self.assertTrue(text.endswith("---\nBases filter with  two spaces.\n"), text)

    def test_raw_suffixes_a_taken_slug_and_refuses_a_known_url(self):
        src = self.write("scratch.txt", "Text.\n")
        a = self.sb("wiki", "raw", "general/obsidian", "--title", "Link cache", "--source", "pasted by the owner",
                    "--from", str(src)).stdout.strip()
        self.assertEqual(a, "wiki/raw/general/obsidian/link-cache-2.md")
        r = self.sb("wiki", "raw", "general/other", "--title", "Again", "--source", "https://example.com/a",
                    "--from", str(src), ok=False)
        self.assertIn("wiki/raw/general/obsidian/link-cache", r.stdout + r.stderr)



class Provenance(Seeded):
    """A raw note read from a repo records the repo, commit, ref and paths; check holds the shape."""

    def repo(self):
        root = Path(self._tmp.name) / "monorepo"
        (root / "libs" / "viewport").mkdir(parents=True)
        (root / "libs" / "viewport" / "Render.ts").write_text("export const frameloop = 'demand'\n")
        for a in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.invalid"],
                  ["config", "user.name", "t"], ["remote", "add", "origin", "git@github.com:org/monorepo.git"],
                  ["add", "-A"], ["commit", "-q", "-m", "x"]):
            subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True)
        sha = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        return root, sha

    def test_raw_with_repo_root_stamps_repo_commit_ref_and_paths(self):
        root, sha = self.repo()
        src = self.write("scratch.txt", "Renders on demand.\n")
        rel = self.sb("wiki", "raw", "monorepo/rendering", "--title", "Render loop", "--source", "AGENTS.md",
                      "--repo-root", str(root), "--paths", "libs/viewport/Render.ts,libs/viewport/",
                      "--symbols", "frameloop", "--from", str(src)).stdout.strip()
        text = self.read(rel)
        for line in ("repo: org/monorepo", f"commit: {sha}", "ref: main",
                     "paths:\n  - libs/viewport/Render.ts\n  - libs/viewport/", "symbols:\n  - frameloop"):
            self.assertIn(line, text)
        self.assertNotIn("problem", self.sb("wiki", "check").stdout.replace("0 problem", ""))

    def test_raw_refuses_a_path_missing_at_the_commit_and_paths_without_a_repo(self):
        root, _ = self.repo()
        src = self.write("scratch.txt", "x\n")
        r = self.sb("wiki", "raw", "monorepo/rendering", "--title", "T", "--source", "s", "--repo-root", str(root),
                    "--paths", "libs/nowhere.ts", "--from", str(src), ok=False)
        self.assertIn("does not exist", r.stdout + r.stderr)
        self.sb("wiki", "raw", "monorepo/rendering", "--title", "T", "--source", "s", "--paths", "a",
                "--from", str(src), ok=False)

    PR = "https://github.com/org/monorepo/pull/7"

    def pr(self, **over):
        sha = "b" * 40
        return {"title": "Render on demand", "body": "Switches the frameloop.\r\nSee @alice.\n",
                "mergeCommit": {"oid": sha}, "headRefName": "feat/demand", "headRefOid": "c" * 40,
                "baseRefName": "main", "createdAt": "2026-03-01T10:00:00Z", "mergedAt": "2026-03-04T09:30:00Z",
                "files": [{"path": "libs/viewport/Render.ts", "changeType": "MODIFIED"},
                          {"path": "libs/viewport/Old.ts", "changeType": "DELETED"},
                          {"path": "apps/web/main.ts", "changeType": "MODIFIED"}], **over}

    def test_raw_pr_merged_keeps_description_and_discussion_without_people_or_bots(self):
        human, bot = {"login": "bob", "type": "User"}, {"login": "coderabbitai[bot]", "type": "Bot"}
        self.fake_gh(self.pr(), comments=[{"user": human, "body": "Why demand?"}, {"user": bot, "body": "Walkthrough"}],
                     reviews=[{"user": human, "body": ""}, {"user": human, "body": "Looks good."}],
                     inline=[{"user": human, "path": "libs/viewport/Render.ts", "body": "Name it."},
                             {"user": bot, "path": "a.ts", "body": "Nit."}])
        rel = self.sb("wiki", "raw", "monorepo/rendering", "--pr", self.PR + "/files").stdout.strip()
        text = self.read(rel)
        for line in ("title: Render on demand", f'source: "{self.PR}"', f'pr: "{self.PR}"', "repo: org/monorepo",
                     f"commit: {'b' * 40}", "ref: main", "published: 2026-03-04",
                     "paths:\n  - libs/viewport/Render.ts\n  - apps/web/main.ts\n"):
            self.assertIn(line, text)
        self.assertTrue(text.endswith("---\nSwitches the frameloop.\nSee @alice.\n\nWhy demand?\n\nLooks good."
                                      "\n\nlibs/viewport/Render.ts: Name it.\n"), text)
        for gone in ("bob", "Walkthrough", "Nit.", "coderabbit"):
            self.assertNotIn(gone, text)
        self.assertNotRegex(text, r"author: \S")
        self.assertIn("0 problem", self.sb("wiki", "check").stdout)

    def test_raw_pr_open_records_the_head_and_narrows_paths_to_a_folder(self):
        self.fake_gh(self.pr(mergeCommit=None, mergedAt=None))
        rel = self.sb("wiki", "raw", "monorepo/rendering", "--pr", self.PR, "--paths", "libs/viewport/",
                      "--title", "Mine").stdout.strip()
        text = self.read(rel)
        for line in (f"commit: {'c' * 40}", "ref: feat/demand", "published: 2026-03-01", "title: Mine",
                     "paths:\n  - libs/viewport/Render.ts\n"):
            self.assertIn(line, text)
        self.assertNotIn("main.ts", text)
        r = self.sb("wiki", "raw", "monorepo/rendering", "--pr", "https://github.com/org/monorepo/pull/8",
                    "--paths", "nowhere/", ok=False)
        self.assertIn("matches no file", r.stdout + r.stderr)

    def test_raw_pr_with_repo_root_checks_the_commit_and_paths_in_the_clone(self):
        root, sha = self.repo()
        self.fake_gh(self.pr(mergeCommit={"oid": sha}, files=[{"path": "libs/viewport/Render.ts"}]))
        rel = self.sb("wiki", "raw", "monorepo/rendering", "--pr", self.PR, "--repo-root", str(root)).stdout.strip()
        self.assertIn(f"commit: {sha}\nref: main", self.read(rel))
        other = "https://github.com/org/monorepo/pull/8"
        self.fake_gh(self.pr(mergeCommit={"oid": "d" * 40}, files=[{"path": "libs/viewport/Render.ts"}]))
        r = self.sb("wiki", "raw", "monorepo/rendering", "--pr", other, "--repo-root", str(root), "--title", "Again",
                    ok=False)
        self.assertIn("rev-parse", r.stdout + r.stderr)
        self.fake_gh(self.pr(mergeCommit={"oid": sha}, files=[{"path": "libs/nowhere.ts"}]))
        r = self.sb("wiki", "raw", "monorepo/rendering", "--pr", other, "--repo-root", str(root), "--title", "Again",
                    ok=False)
        self.assertIn("does not exist", r.stdout + r.stderr)

    def test_raw_pr_refuses_a_duplicate_and_a_missing_or_failing_gh(self):
        r = self.sb("wiki", "raw", "monorepo/rendering", "--pr", self.PR, ok=False)
        self.assertIn("gh is not installed", r.stdout + r.stderr)
        self.fake_gh(self.pr(), fail="gh: HTTP 404")
        self.assertIn("HTTP 404", self.sb("wiki", "raw", "monorepo/rendering", "--pr", self.PR, ok=False).stderr)
        self.sb("wiki", "raw", "monorepo/rendering", "--pr", "not a url", ok=False)
        self.fake_gh(self.pr())
        first = self.sb("wiki", "raw", "monorepo/rendering", "--pr", self.PR).stdout.strip()
        n = len(list((self.vault / "wiki/raw").rglob("*.md")))
        for extra in ([], ["--title", "Other", "--source", "elsewhere"]):
            r = self.sb("wiki", "raw", "monorepo/other", "--pr", self.PR, *extra, ok=False)
            self.assertIn(first, r.stdout)
        src = self.write("scratch.txt", "x\n")
        r = self.sb("wiki", "raw", "monorepo/other", "--title", "Same url", "--source", self.PR, "--from", str(src),
                    ok=False)
        self.assertIn(first, r.stdout)
        self.assertEqual(len(list((self.vault / "wiki/raw").rglob("*.md"))), n)

    def test_check_holds_the_pr_url_shape(self):
        raw = "wiki/raw/general/obsidian/link-cache.md"
        self.write(raw, self.read(raw).replace("created: 2026-01-02\n", "created: 2026-01-02\nrepo: org/monorepo\n"
                                               f"commit: {'a' * 40}\npr: https://example.com/x\n"))
        self.assertIn("pr is not an https://github.com", self.sb("wiki", "check", ok=False).stdout)

    def test_check_flags_bad_provenance_and_fix_makes_text_paths_lists(self):
        raw = "wiki/raw/general/obsidian/link-cache.md"
        self.write(raw, self.read(raw).replace("created: 2026-01-02\n", "created: 2026-01-02\nrepo: org/monorepo\n"
                                               f"commit: {'a' * 40}\nref: main\npaths: x/a.ts, x/b.ts\n"))
        out = self.sb("wiki", "check", ok=False).stdout
        self.assertIn("paths is text, not a list", out)
        self.sb("wiki", "check", "--fix", ok=None)
        self.assertIn("paths:\n  - x/a.ts\n  - x/b.ts", self.read(raw))
        self.sb("wiki", "check")
        self.sb("wiki", "set", raw, "commit=abc123")
        self.assertIn("full 40-character commit", self.sb("wiki", "check", ok=False).stdout)

    def test_verified_is_a_full_commit_on_articles_and_provenance_stays_on_raw_notes(self):
        self.sb("wiki", "set", self.article, "verified=" + "b" * 40)
        self.sb("wiki", "check")
        self.sb("wiki", "set", self.article, "commit=" + "b" * 40)
        self.assertIn("belongs on the raw notes", self.sb("wiki", "check", ok=False).stdout)


class Verify(Seeded):
    """wiki verify anchors each article at its sources' commit and checks paths and symbols in git."""

    def git(self, cwd, *a):
        return subprocess.run(["git", "-C", str(cwd), *a], check=True, capture_output=True, text=True).stdout.strip()

    def setUp(self):
        super().setUp()
        tmp = Path(self._tmp.name)
        self.remote, self.clone = tmp / "remote.git", tmp / "monorepo"
        self.git(tmp, "init", "-q", "--bare", "-b", "main", str(self.remote))
        self.git(tmp, "clone", "-q", str(self.remote), str(self.clone))
        for a in (["config", "user.email", "t@example.invalid"], ["config", "user.name", "t"],
                  ["remote", "set-url", "origin", "git@github.com:org/monorepo.git"],
                  ["remote", "set-url", "--push", "origin", str(self.remote)],
                  ["config", "remote.origin.fetchurl", str(self.remote)]):
            self.git(self.clone, *a)
        self.commit("libs/viewport/Render.ts", "export const frameloop = 'demand'\n", "base")

    def commit(self, path, text, msg, branch="main"):
        f = self.clone / path
        if text is None:
            f.unlink()
        else:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text)
        self.git(self.clone, "add", "-A")
        self.git(self.clone, "commit", "-q", "-m", msg)
        self.git(self.clone, "push", "-q", str(self.remote), f"HEAD:{branch}")
        self.git(self.clone, "fetch", "-q", "--prune", str(self.remote), "+refs/heads/*:refs/remotes/origin/*")
        return self.git(self.clone, "rev-parse", "HEAD")

    def add_article(self, slug, sha=None, ref="main", body="", symbols=""):
        src = self.write("scratch.txt", "Claims.\n")
        raw = self.sb("wiki", "raw", "monorepo/rendering", "--title", f"src {slug}", "--source", "s",
                      "--from", str(src)).stdout.strip()[:-3]
        if sha:
            self.sb("wiki", "set", raw, "repo=org/monorepo", f"commit={sha}", f"ref={ref}",
                    "paths=libs/viewport/Render.ts", *([f"symbols={symbols}"] if symbols else []))
        self.sb("wiki", "new", f"monorepo/rendering/{slug}", "--title", slug, "--type", "concept", "--summary", "S.",
                "--sources", raw, "--about", "Rendering.")
        if body:
            self.append(f"wiki/monorepo/rendering/{slug}.md", body)

    def verdicts(self):
        rows = json.loads(self.sb("wiki", "verify", "--repo-root", str(self.clone), "--json").stdout)
        return {Path(r["note"]).stem: r["verdict"] for r in rows}

    def test_anchored_article_is_current_then_drifted_then_broken(self):
        self.add_article("render-loop", self.git(self.clone, "rev-parse", "HEAD"), symbols="frameloop")
        self.assertEqual(self.verdicts()["render-loop"], "current")
        self.commit("libs/viewport/Render.ts", "export const frameloop = 'always'\n", "change")
        self.assertEqual(self.verdicts()["render-loop"], "drifted")
        self.commit("libs/viewport/Render.ts", "export const loop = 1\n", "rename symbol")
        self.assertEqual(self.verdicts()["render-loop"], "broken")

    def test_branch_only_claim_is_checked_against_its_branch_then_orphaned(self):
        self.git(self.clone, "switch", "-q", "-c", "feature")
        sha = self.commit("libs/viewport/Clip.ts", "export const clipPrelude = 1\n", "feature", branch="feature")
        self.add_article("clip-prelude", sha, ref="feature", symbols="clipPrelude")
        self.assertEqual(self.verdicts()["clip-prelude"], "current")
        self.git(self.clone, "push", "-q", str(self.remote), ":feature")
        self.git(self.clone, "fetch", "-q", "--prune", str(self.remote), "+refs/heads/*:refs/remotes/origin/*")
        self.assertEqual(self.verdicts()["clip-prelude"], "current")
        self.git(self.clone, "switch", "-q", "main")
        self.git(self.clone, "branch", "-q", "-D", "feature")
        self.assertEqual(self.verdicts()["clip-prelude"], "orphaned")

    def test_raw_rev_stamps_a_branch_without_checking_it_out_and_verify_finds_a_local_branch(self):
        self.git(self.clone, "switch", "-q", "-c", "local-only")
        (self.clone / "libs/viewport/Frame.ts").write_text("export const LEGACY = 1\n")
        self.git(self.clone, "add", "-A")
        self.git(self.clone, "commit", "-q", "-m", "local")
        tip = self.git(self.clone, "rev-parse", "HEAD")
        self.git(self.clone, "switch", "-q", "main")
        src = self.write("scratch.txt", "Frame.\n")
        raw = self.sb("wiki", "raw", "monorepo/rendering", "--title", "Frame re-read", "--source", "s",
                      "--repo-root", str(self.clone), "--rev", "local-only", "--paths", "libs/viewport/Frame.ts",
                      "--symbols", "LEGACY", "--from", str(src)).stdout.strip()
        self.assertIn(f"commit: {tip}\nref: local-only", self.read(raw))
        self.sb("wiki", "new", "monorepo/rendering/frame", "--title", "Frame", "--type", "concept", "--summary", "S.",
                "--sources", raw[:-3], "--about", "Rendering.")
        self.assertEqual(self.verdicts()["frame"], "current")

    def test_paths_still_written_as_text_are_read_as_a_list(self):
        self.add_article("text-paths", self.git(self.clone, "rev-parse", "HEAD"))
        raw = "wiki/raw/monorepo/rendering/src-text-paths.md"
        self.write(raw, self.read(raw).replace("paths:\n  - libs/viewport/Render.ts\n",
                                               "paths: libs/viewport/Render.ts, libs/viewport\n"))
        self.assertEqual(self.verdicts()["text-paths"], "current")

    def test_unstamped_article_is_guessed_from_its_code_and_verified_overrides_the_anchor(self):
        self.add_article("guessed", body="\nThe loop lives in `Render.ts` and reads `frameloop`.\n")
        self.add_article("nothing", body="\nPlain prose only.\n")
        out = json.loads(self.sb("wiki", "verify", "--repo-root", str(self.clone), "--json").stdout)
        rows = {Path(r["note"]).stem: r for r in out}
        self.assertEqual((rows["guessed"]["verdict"], rows["guessed"]["guessed"]), ("current", True))
        self.assertEqual(rows["guessed"]["paths"], ["libs/viewport/Render.ts"])
        self.assertEqual(rows["nothing"]["verdict"], "unanchored")
        old = self.git(self.clone, "rev-parse", "HEAD")
        self.add_article("re-read", old, symbols="frameloop")
        new = self.commit("libs/viewport/Render.ts", "export const frameloop = 'x'\n", "edit")
        self.assertEqual(self.verdicts()["re-read"], "drifted")
        self.sb("wiki", "set", "wiki/monorepo/rendering/re-read.md", f"verified={new}")
        self.assertEqual(self.verdicts()["re-read"], "current")

class Set(Seeded):
    def setUp(self):
        super().setUp()
        self.sb("wiki", "new", "general/obsidian/metadata-cache", "--title", "Metadata cache", "--type", "entity",
                "--summary", "Where Obsidian keeps parsed links.", "--sources", "wiki/raw/general/obsidian/link-cache")
        self.other = "wiki/general/obsidian/metadata-cache.md"

    def test_set_replaces_scalars_and_stamps_today(self):
        self.sb("wiki", "set", "general/obsidian/frontmatter-links", "summary=New summary.", "reviewed=today")
        text = self.read(self.article)
        self.assertIn("summary: New summary.", text)
        self.assertIn(f"reviewed: {TODAY}", text)
        self.assertIn("| New summary. |", self.read("wiki/index.md"))

    def test_set_adds_and_drops_list_refs(self):
        self.sb("wiki", "set", "general/obsidian/frontmatter-links", "related+=general/obsidian/metadata-cache")
        self.assertIn('related:\n  - "[[wiki/general/obsidian/metadata-cache|Metadata cache]]"', self.read(self.article))
        self.sb("wiki", "set", "general/obsidian/frontmatter-links", "related-=general/obsidian/metadata-cache")
        self.assertNotIn("related:", self.read(self.article))
        self.sb("wiki", "set", "general/obsidian/frontmatter-links", "related+=general/obsidian/nope", ok=False)

    def test_disputes_are_written_on_both_ends(self):
        self.sb("wiki", "set", "general/obsidian/frontmatter-links", "disputes+=general/obsidian/metadata-cache")
        self.assertIn("[[wiki/general/obsidian/frontmatter-links|Obsidian property links]]", self.read(self.other))
        self.sb("wiki", "set", "general/obsidian/frontmatter-links", "disputes-=general/obsidian/metadata-cache")
        self.assertNotIn("disputes:", self.read(self.other))

    def test_superseded_by_marks_outdated_on_one_end_and_supersedes_on_the_other(self):
        self.sb("wiki", "set", "general/obsidian/frontmatter-links", "superseded_by+=general/obsidian/metadata-cache")
        self.assertIn("status: outdated", self.read(self.article))
        self.assertIn("supersedes:\n  - \"[[wiki/general/obsidian/frontmatter-links|", self.read(self.other))
        self.sb("wiki", "set", "general/obsidian/metadata-cache", "supersedes-=general/obsidian/frontmatter-links")
        self.assertIn("status: current", self.read(self.article))
        self.assertNotIn("superseded_by", self.read(self.article))

    def test_set_refuses_an_unknown_status(self):
        self.sb("wiki", "set", "general/obsidian/frontmatter-links", "status=wrong", ok=False)


class Log(Seeded):
    def test_log_appends_a_dated_entry_with_links(self):
        self.sb("wiki", "log", "learn", "--subject", "general/obsidian/frontmatter-links", "--disposition", "New",
                "--raw", "wiki/raw/general/obsidian/link-cache")
        self.sb("wiki", "log", "ask", "--subject", "Archived: general/obsidian/frontmatter-links")
        self.sb("wiki", "log", "learn", "--subject", "no material: Clippings/A page.md")
        log = self.read("wiki/log.md")
        self.assertIn(f"## [{TODAY}] learn | [[wiki/general/obsidian/frontmatter-links|Obsidian property links]]\n"
                      "- Disposition: New\n- Raw: [[wiki/raw/general/obsidian/link-cache|Link cache]]\n", log)
        self.assertIn(f"## [{TODAY}] ask | Archived: [[wiki/general/obsidian/frontmatter-links|", log)
        self.assertTrue(log.endswith(f"## [{TODAY}] learn | no material: Clippings/A page.md\n"), log)
        self.sb("wiki", "log", "forget", "--subject", "x", ok=False)


class Backlog(Seeded):
    def test_backlog_lists_uncited_unlogged_sources_oldest_first(self):
        self.write("wiki/raw/general/obsidian/newer.md", "---\nwiki: raw\ntitle: Newer\ncreated: 2026-05-01\n---\nx\n")
        self.write("Clippings/Older.md", "---\ncreated: 2026-02-01\n---\nx\n")
        self.write("Clippings/Dismissed.md", "---\ncreated: 2026-01-01\n---\nx\n")
        self.map("m/one")
        self.ticket("m/one", 1, "Research done")
        self.ticket("m/one", 2, "Task done", type_="task")
        self.sb("wiki", "log", "learn", "--subject", "no material: Clippings/Dismissed.md")
        out = self.sb("wiki", "backlog").stdout
        lines = [l.split(" ")[0] for l in out.splitlines() if l.startswith(("wiki/", "Clippings/", "wayfinder/"))]
        # a note without `created` sorts by its file time: today, so last
        self.assertEqual(lines, ["Clippings/Older", "wiki/raw/general/obsidian/newer",
                                 "wayfinder/m/one/issues/001-research-done"])
        self.assertIn("3 on the backlog", out)
        limited = self.sb("wiki", "backlog", "--limit", "1").stdout
        self.assertIn("Clippings/Older", limited)
        self.assertNotIn("newer", limited)
        self.assertIn("3 on the backlog", limited)


class Check(Seeded):
    def problems(self, *expected):
        r = self.sb("wiki", "check", ok=False)
        for e in expected:
            self.assertIn(e, r.stdout)
        return r.stdout

    def test_a_clean_wiki_passes(self):
        out = self.sb("wiki", "check").stdout
        self.assertIn("0 problem(s)", out)

    def test_fix_restamps_a_stale_index(self):
        idx = self.read("wiki/index.md").replace("| concept |", "| entity |")
        self.write("wiki/index.md", idx)
        self.problems("index.md: the index block is out of date")
        self.sb("wiki", "check", "--fix")
        self.assertIn("| concept |", self.read("wiki/index.md"))

    def test_fix_repoints_moved_links_and_drops_dead_related(self):
        self.sb("wiki", "new", "general/obsidian/metadata-cache", "--title", "Metadata cache", "--type", "entity",
                "--summary", "S.", "--sources", "wiki/raw/general/obsidian/link-cache")
        self.sb("wiki", "set", "general/obsidian/frontmatter-links", "related+=general/obsidian/metadata-cache")
        self.append(self.article, "\nSee [[wiki/general/obsidian/metadata-cache|the cache]].\n")
        self.write("wiki/general/obsidian/gone.md", "---\nwiki: article\n---\n# Gone\n")
        self.sb("wiki", "set", "general/obsidian/frontmatter-links", "related+=general/obsidian/gone")
        (self.vault / "wiki/general/obsidian/gone.md").unlink()
        (self.vault / "wiki/general/cache").mkdir()
        self.write("wiki/general/cache/cache.md", "---\nwiki: topic\ntype: topic\nsummary: Caches.\n---\n# Cache\n\nCaches.\n")
        (self.vault / "wiki/general/obsidian/metadata-cache.md").rename(self.vault / "wiki/general/cache/metadata-cache.md")
        self.problems("moved", "general/obsidian/gone")
        self.sb("wiki", "check", "--fix")
        text = self.read(self.article)
        self.assertIn("[[wiki/general/cache/metadata-cache|Metadata cache]]", text)
        self.assertIn("[[wiki/general/cache/metadata-cache|the cache]]", text)
        self.assertNotIn("gone", text)

    def test_tags_carry_project_and_topic_and_fix_makes_them_current(self):
        self.sb("wiki", "new", "general/obsidian/metadata-cache", "--title", "Metadata cache", "--type", "entity",
                "--summary", "S.", "--sources", "wiki/raw/general/obsidian/link-cache", "--tags", "graph, obsidian/api")
        self.assertIn("  - wiki/entity\n  - project/general\n  - topic/obsidian\n  - graph\n  - obsidian/api\n",
                      self.read("wiki/general/obsidian/metadata-cache.md"))
        self.write(self.article, self.read(self.article).replace("  - topic/obsidian\n", "  - topic/old\n"))
        self.problems("tags are wiki/concept, project/general, topic/old")
        self.sb("wiki", "check", "--fix")
        text = self.read(self.article)
        self.assertIn("  - topic/obsidian\n", text)
        self.assertNotIn("topic/old", text)

    def test_format_problems(self):
        self.write("wiki/general/obsidian/bad.md", "---\nwiki: article\ntype: concept\nstatus: wrong\n---\n# Bad\n")
        self.write("wiki/general/obsidian/deep/note.md", "---\nwiki: article\n---\n# Deep\n")
        self.write("wiki/general/orphan/2026-plan.md", "---\nwiki: article\n---\n# Plan\n")
        self.write("wiki/raw/general/x/frontmatter-links.md", "---\nwiki: raw\ntitle: T\nsource: s\n---\nB\n")
        self.problems("bad.md: unknown status 'wrong'", "bad.md: missing summary", "bad.md: missing sources",
                      "deep/note.md: deeper than wiki/<project>/<topic>/", "orphan: no folder note",
                      "2026-plan.md: slug starts with digits and a dash",
                      "slug 'frontmatter-links' is taken twice")

    def test_status_must_match_the_callouts_and_supersession(self):
        self.append(self.article, "\n> [!question] Disputed\n> A and B.\n\n> [!warning] Outdated\n> Was X.\n")
        self.problems("status is current; the rule makes it disputed", "Outdated callout without its date")

    def test_reciprocal_ends_must_both_exist(self):
        self.sb("wiki", "new", "general/obsidian/metadata-cache", "--title", "Metadata cache", "--type", "entity",
                "--summary", "S.", "--sources", "wiki/raw/general/obsidian/link-cache")
        text = self.read(self.article).replace("tags:", 'disputes:\n  - "[[wiki/general/obsidian/metadata-cache|M]]"\ntags:')
        self.write(self.article, text)
        self.problems("metadata-cache.md: missing disputes back to wiki/general/obsidian/frontmatter-links")

    def test_link_problems(self):
        self.map("m/one")
        self.ticket("m/one", 3, "Open one", status="Project.Planned")
        self.write("Notes/mine.md", "# Mine\n")
        text = self.read(self.article).replace(
            "sources:\n", 'sources:\n  - "[[Notes/mine|Mine]]"\n  - "[[wayfinder/m/one/issues/003-open-one|#003]]"\n')
        self.write(self.article, text + "\nSee [mine](../../Notes/mine.md), [[mine]], #123 and [[wiki/nowhere|x]].\n")
        self.problems("Notes/mine is not a raw note", "003-open-one is a ticket that is not resolved",
                      "markdown link to a vault note", "wikilink by bare file name: [[mine]]",
                      "bare #123", "broken link: [[wiki/nowhere|x]]")

    def test_links_inside_code_are_text(self):
        self.append(self.article, "\nSee [[wiki/general/obsidian/obsidian|Obsidian]]. Write `[[mine]]` or `#123`, never bare.\n\n```\n[[other]] #456\n```\n")
        self.sb("wiki", "check")

    def test_an_alias_must_be_the_targets_heading_and_fix_writes_it(self):
        text = self.read(self.article).replace("|Link cache]]", "|The cache]]")
        self.write(self.article, text + "\nSee [[wiki/general/obsidian/obsidian|the topic]], "
                   "[[wiki/general/obsidian/obsidian#Part|a part]] and [[wiki/general/obsidian/obsidian]].\n")
        out = self.problems(
            "alias is not the target's heading: [[wiki/raw/general/obsidian/link-cache|The cache]] (heading: Link cache)",
            "alias is not the target's heading: [[wiki/general/obsidian/obsidian|the topic]] (heading: Obsidian)",
            "alias is not the target's heading: [[wiki/general/obsidian/obsidian]] (heading: Obsidian)")
        self.assertNotIn("a part", out)
        self.sb("wiki", "check", "--fix")
        text = self.read(self.article)
        self.assertIn('"[[wiki/raw/general/obsidian/link-cache|Link cache]]"', text)
        self.assertIn("See [[wiki/general/obsidian/obsidian|Obsidian]], [[wiki/general/obsidian/obsidian#Part|a part]] "
                      "and [[wiki/general/obsidian/obsidian|Obsidian]].", text)
        self.sb("wiki", "check")

    def test_grounding_suspects_are_printed_and_never_counted(self):
        self.append(self.article, "\nThe cache holds 42K links; 99.9% stay. \u201cA quote that no source holds at all\u201d.\n")
        out = self.sb("wiki", "check").stdout
        suspects = out[out.index("grounding suspect"):]
        self.assertIn("99.9%", suspects)
        self.assertIn("A quote that no source holds at all", suspects)
        self.assertNotIn("42K", suspects)
        self.assertIn("on the backlog", out)


class RelativeStore(VaultCase):
    """A sync clone (`sb.projects` set, or `sb.links relative`) writes the links GitHub renders."""

    def setUp(self):
        super().setUp()
        subprocess.run(["git", "init", "-q", str(self.vault)], check=True)
        self.config("sb.projects", "general")
        self.sb("wiki", "init")
        self.write("wiki/raw/general/obsidian/link-cache.md", "---\nwiki: raw\ntype: source\ntitle: Link cache\n"
                   "source: https://example.com/a\n---\nThe cache.\n")
        self.sb("wiki", "new", "general/obsidian/frontmatter-links", "--title", "Obsidian property links",
                "--type", "concept", "--summary", "S.", "--sources", "wiki/raw/general/obsidian/link-cache",
                "--about", "How Obsidian stores notes.")
        self.sb("wiki", "new", "general/obsidian/metadata-cache", "--title", "Metadata cache", "--type", "entity",
                "--summary", "S.", "--sources", "wiki/raw/general/obsidian/link-cache",
                "--related", "general/obsidian/frontmatter-links")
        self.article = "wiki/general/obsidian/frontmatter-links.md"

    def config(self, key, value):
        subprocess.run(["git", "-C", str(self.vault), "config", key, value], check=True)

    def test_every_write_uses_relative_links(self):
        self.assertIn("sources:\n  - wiki/raw/general/obsidian/link-cache.md\n"
                      "related:\n  - wiki/general/obsidian/frontmatter-links.md\n",
                      self.read("wiki/general/obsidian/metadata-cache.md"))
        self.sb("wiki", "set", "general/obsidian/frontmatter-links", "related+=general/obsidian/metadata-cache")
        self.assertIn("related:\n  - wiki/general/obsidian/metadata-cache.md\n", self.read(self.article))
        self.sb("wiki", "log", "learn", "--subject", "general/obsidian/metadata-cache",
                "--raw", "wiki/raw/general/obsidian/link-cache")
        log = self.read("wiki/log.md")
        self.assertIn("learn | [Metadata cache](general/obsidian/metadata-cache.md)\n", log)
        self.assertIn("- Raw: [Link cache](raw/general/obsidian/link-cache.md)\n", log)
        self.assertIn("| [Metadata cache](general/obsidian/metadata-cache.md) | entity |", self.read("wiki/index.md"))
        self.assertEqual(self.sb("wiki", "link", "general/obsidian/metadata-cache").stdout.strip(),
                         "wiki/general/obsidian/metadata-cache.md")
        self.assertIn("0 problem(s)", self.sb("wiki", "check").stdout)

    def test_check_reads_relative_links_and_fix_writes_the_heading(self):
        text = self.read(self.article).replace("sources:\n", "sources:\n  - wiki/raw/general/obsidian/nowhere.md\n")
        self.write(self.article, text + "\nSee [the cache](metadata-cache.md), [gone](gone.md), "
                   "[site](https://x.org/a.md) and `[x](nowhere.md)`.\n")
        out = self.sb("wiki", "check", ok=False).stdout
        for e in ("alias is not the target's heading: [the cache](metadata-cache.md) (heading: Metadata cache)",
                  "broken link: [gone](gone.md)", "broken link: wiki/raw/general/obsidian/nowhere.md"):
            self.assertIn(e, out)
        self.assertNotIn("markdown link to a vault note", out)
        self.assertNotIn("x.org", out)
        self.assertNotIn("[x](nowhere.md)", out)
        self.sb("wiki", "check", "--fix", ok=False)
        self.assertIn("See [Metadata cache](metadata-cache.md),", self.read(self.article))

    def test_sb_links_overrides_the_default(self):
        self.config("sb.links", "wikilink")
        self.sb("wiki", "new", "general/obsidian/third", "--title", "Third", "--type", "concept",
                "--summary", "S.", "--sources", "wiki/raw/general/obsidian/link-cache")
        self.assertIn('  - "[[wiki/raw/general/obsidian/link-cache|Link cache]]"\n',
                      self.read("wiki/general/obsidian/third.md"))


class Projects(Seeded):
    """Every note lives under its project: the repo's folder name under wayfinder/, or general."""

    def setUp(self):
        super().setUp()
        self.map("monorepo/overrides")
        self.ticket("monorepo/overrides", 5, "The override data model", answer="Overrides key by part id.")
        self.sb("wiki", "new", "monorepo/part-hierarchy/part-ids", "--title", "Part ids", "--type", "entity",
                "--summary", "How parts are identified.", "--sources", "monorepo/overrides#005",
                "--about", "The product's part tree.")

    def test_new_writes_the_project_on_the_article_and_its_folder_note(self):
        self.assertIn("project: monorepo", self.read("wiki/monorepo/part-hierarchy/part-ids.md"))
        self.assertIn("project: monorepo", self.read("wiki/monorepo/part-hierarchy/part-hierarchy.md"))
        self.assertIn("project: general", self.read(self.article))

    def test_new_without_a_project_names_the_one_its_sources_come_from(self):
        r = self.sb("wiki", "new", "part-hierarchy/more", "--title", "More", "--type", "concept",
                    "--summary", "S.", "--sources", "monorepo/overrides#005", ok=False)
        self.assertIn("monorepo/part-hierarchy/more", r.stderr)

    def test_raw_needs_a_project_and_records_it(self):
        self.sb("wiki", "raw", "obsidian", "--title", "T", "--source", "x", "--from", "-", stdin="B\n", ok=False)
        path = self.sb("wiki", "raw", "monorepo/part-hierarchy", "--title", "T", "--source", "x",
                       "--from", "-", stdin="B\n").stdout.strip()
        self.assertEqual(path, "wiki/raw/monorepo/part-hierarchy/t.md")
        self.assertIn("project: monorepo", self.read(path))

    def test_index_groups_by_project_and_narrows_to_one_plus_general(self):
        self.map("semantra/plugin")
        self.ticket("semantra/plugin", 7, "Links")
        self.sb("wiki", "new", "semantra/graph/edges", "--title", "Edges", "--type", "concept",
                "--summary", "S.", "--sources", "semantra/plugin#007", "--about", "The graph.")
        idx = self.read("wiki/index.md")
        self.assertLess(idx.index("## general"), idx.index("## monorepo"))
        self.assertIn("## monorepo\n\n### part-hierarchy\n", idx)
        out = self.sb("wiki", "index", "--project", "monorepo").stdout
        self.assertIn("# monorepo\n## part-hierarchy: The product's part tree.", out)
        self.assertIn("# general", out)
        self.assertNotIn("semantra", out)

    def test_find_and_backlog_narrow_to_a_project_plus_general(self):
        self.map("semantra/plugin")
        self.ticket("semantra/plugin", 7, "Part ids elsewhere")
        out = self.sb("wiki", "find", "part", "--raw", "--project", "monorepo").stdout
        self.assertIn("wiki/monorepo/part-hierarchy/part-ids", out)
        self.assertNotIn("semantra", out)
        self.assertIn("semantra", self.sb("wiki", "find", "part", "--raw").stdout)
        self.write("wiki/raw/general/obsidian/loose.md", "---\nwiki: raw\ntitle: L\ncreated: 2026-01-01\n---\nx\n")
        back = self.sb("wiki", "backlog", "--project", "monorepo").stdout
        self.assertIn("loose", back)
        self.assertNotIn("semantra", back)

    def test_check_keeps_the_project_property_in_step_with_the_folder(self):
        path = "wiki/monorepo/part-hierarchy/part-ids.md"
        self.write(path, self.read(path).replace("project: monorepo", "project: semantra"))
        r = self.sb("wiki", "check", ok=False)
        self.assertIn("part-ids.md: project is semantra; its folder says monorepo", r.stdout)
        self.sb("wiki", "check", "--fix")
        self.assertIn("project: monorepo", self.read(path))

    def test_check_flags_the_old_layout(self):
        self.write("wiki/oldtopic/oldtopic.md", "---\nwiki: topic\ntype: topic\nsummary: S.\n---\n# Old\n\nS.\n")
        self.assertIn("old layout", self.sb("wiki", "check", ok=False).stdout)


class Migrate(VaultCase):
    """A wiki written before projects: topics straight under wiki/."""

    def setUp(self):
        super().setUp()
        self.sb("wiki", "init")
        self.map("monorepo/overrides")
        self.ticket("monorepo/overrides", 5, "The override data model")
        self.write("wiki/part-hierarchy/part-hierarchy.md",
                   "---\nwiki: topic\ntype: topic\nsummary: Parts.\ntags:\n  - wiki/topic\n---\n# Part hierarchy\n\nParts.\n")
        self.write("wiki/part-hierarchy/part-ids.md", """---
wiki: article
type: entity
status: current
summary: Ids.
updated: 2026-10-26
sources:
  - "[[wayfinder/monorepo/overrides/issues/005-the-override-data-model|#005]]"
  - "[[wiki/raw/part-hierarchy/dump|Dump]]"
tags:
  - wiki/entity
---
# Part ids

## Overview

Ids. See [[wiki/part-hierarchy/part-hierarchy|Part hierarchy]].
""")
        self.write("wiki/raw/part-hierarchy/dump.md", "---\nwiki: raw\ntype: source\ntitle: Dump\nsource: x\n---\nIds.\n")
        self.sb("wiki", "log", "learn", "--subject", "wiki/part-hierarchy/part-ids")
        self.write("wayfinder/monorepo/overrides/report.md", "Findings: [[wiki/part-hierarchy/part-ids|Part ids]]\n")
        self.write("Notes/mine.md", "My link: [[wiki/part-hierarchy/part-ids|Part ids]]\n")

    def test_dry_run_lists_the_moves_and_writes_nothing(self):
        out = self.sb("wiki", "migrate", "monorepo").stdout
        self.assertIn("wiki/part-hierarchy -> wiki/monorepo/part-hierarchy", out)
        self.assertIn("wiki/raw/part-hierarchy -> wiki/raw/monorepo/part-hierarchy", out)
        self.assertIn("dry run", out)
        self.assertTrue(self.exists("wiki/part-hierarchy/part-ids.md"))

    def test_write_moves_relinks_and_leaves_a_clean_wiki(self):
        out = self.sb("wiki", "migrate", "monorepo", "--write").stdout
        art = self.read("wiki/monorepo/part-hierarchy/part-ids.md")
        self.assertIn("project: monorepo", art)
        self.assertIn("[[wiki/raw/monorepo/part-hierarchy/dump|Dump]]", art)
        self.assertIn("[[wiki/monorepo/part-hierarchy/part-hierarchy|Part hierarchy]]", art)
        self.assertIn("project: monorepo", self.read("wiki/monorepo/part-hierarchy/part-hierarchy.md"))
        self.assertNotIn("project", self.read("wiki/raw/monorepo/part-hierarchy/dump.md"))  # raw is never edited
        self.assertIn("[[wiki/monorepo/part-hierarchy/part-ids|", self.read("wiki/log.md"))
        self.assertIn("[[wiki/monorepo/part-hierarchy/part-ids|", self.read("wayfinder/monorepo/overrides/report.md"))
        self.assertIn("[[wiki/part-hierarchy/part-ids|", self.read("Notes/mine.md"))  # the owner's note
        self.assertIn("Notes/mine.md", out)
        self.assertFalse(self.exists("wiki/part-hierarchy"))
        self.sb("wiki", "check")

    def test_only_the_named_topics_move(self):
        self.write("wiki/obsidian/obsidian.md", "---\nwiki: topic\ntype: topic\nsummary: O.\n---\n# Obsidian\n\nO.\n")
        self.sb("wiki", "migrate", "monorepo", "part-hierarchy", "--write")
        self.assertTrue(self.exists("wiki/obsidian/obsidian.md"))
        self.sb("wiki", "migrate", "general", "--write")
        self.assertTrue(self.exists("wiki/general/obsidian/obsidian.md"))


if __name__ == "__main__":
    unittest.main()
