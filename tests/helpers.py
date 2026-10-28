"""A throwaway vault per test, and wikibrain run against it as an agent runs it: a subprocess."""
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

SBMAP = Path(__file__).resolve().parents[1] / "skills" / "wikibrain" / "scripts" / "wikibrain.py"
TODAY = date.today().isoformat()


class VaultCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name) / "Vault"
        self.vault.mkdir()
        self.cache = Path(self._tmp.name) / "cache"

    def tearDown(self):
        self._tmp.cleanup()

    def sb(self, *args, stdin=None, ok=True):
        """Run sbmap; ok=True asserts exit 0, ok=False asserts non-zero, ok=None asserts nothing."""
        # PATH without /usr/local/bin keeps the real Obsidian CLI out of the tests
        env = {**os.environ, "SB_VAULT": str(self.vault),
               "WIKIBRAIN_CACHE": str(self.cache), "PATH": "/usr/bin:/bin"}
        r = subprocess.run([sys.executable, str(SBMAP), *args], capture_output=True, text=True,
                           env=env, input=stdin, cwd=self.vault)
        if ok is True:
            self.assertEqual(r.returncode, 0, f"sbmap {' '.join(args)}\n{r.stdout}{r.stderr}")
        elif ok is False:
            self.assertNotEqual(r.returncode, 0, f"sbmap {' '.join(args)} should fail\n{r.stdout}")
        return r

    def write(self, rel, text):
        p = self.vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def read(self, rel):
        return (self.vault / rel).read_text(encoding="utf-8")

    def exists(self, rel):
        return (self.vault / rel).exists()

    # ---- fixtures in the vault's own shape ----

    def ticket(self, map_folder, num, title, status="Project.Finished", type_="research", answer="An answer."):
        return self.write(f"wayfinder/{map_folder}/issues/{num:03d}-{title.lower().replace(' ', '-')}.md", f"""---
wayfinder: ticket
number: {num}
status: {status}
type: {type_}
map: "[[wayfinder/{map_folder}/map|Map]]"
tags:
  - wayfinder/ticket
---
# {title}

## Question

What?

## Answer

{answer}
""")

    def map(self, folder, title="Test map", status="Project.InProgress"):
        return self.write(f"wayfinder/{folder}/map.md", f"""---
wayfinder: map
status: {status}
tags:
  - wayfinder/map/{folder.replace('/', '-')}
---
# {title}

## Destination

Somewhere.

## Decisions so far

## Out of scope
""")
