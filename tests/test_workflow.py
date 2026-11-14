"""What .github/workflows/app-update.yaml must keep (D13), read from the file.

Standard library only (a line reader for the workflow's fixed layout, not a YAML
parser): python3 -m unittest discover -s tests -v

The provenance check runs in the real workflow only when a release is newer, which the
dry run (lint.yaml) does not do: nothing else would notice a workflow that opens pull
requests without having verified anything.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/app-update.yaml"
FORBIDDEN_TRIGGERS = {"pull_request", "pull_request_target", "workflow_run", "push"}


def block(lines: list[str], header: str, indent: int) -> list[str]:
    """The lines under `header` (at `indent`), up to the next line at that indent or less."""
    start = next((i for i, line in enumerate(lines) if line == " " * indent + header), None)
    if start is None:
        return []
    out: list[str] = []
    for line in lines[start + 1 :]:
        if line.strip() and not line.strip().startswith("#") and len(line) - len(line.lstrip()) <= indent:
            break
        out.append(line)
    return out


def split(lines: list[str], indent: int, marker: str = "") -> dict[str, list[str]]:
    """Children of a block, by key (`key:` at `indent`) or by step name (`- name: x`)."""
    items: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in lines:
        match = re.match(rf"^ {{{indent}}}{marker}(?P<key>[^\s#-][^:]*|name):\s*(?P<value>.*)$", line)
        if match and not line.startswith(" " * (indent + 1)):
            key = match["value"].strip().strip('"') if marker else match["key"]
            current = items.setdefault(key, [])
        if current is not None:
            current.append(line)
    return items


class AppUpdateWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.lines = cls.text.splitlines()
        cls.jobs = split(block(cls.lines, "jobs:", 0), 2)

    def steps(self, job: str) -> dict[str, list[str]]:
        return split(block(self.jobs[job], "steps:", 4), 6, marker="- ")

    def test_triggers_are_schedule_and_manual_only(self) -> None:
        # The App's key is in an environment limited to main; a pull request must not run this.
        triggers = split(block(self.lines, "on:", 0), 2)
        self.assertTrue(triggers, "no `on:` block read: the workflow's layout changed")
        self.assertEqual(set(triggers), {"schedule", "workflow_dispatch"})
        self.assertFalse(FORBIDDEN_TRIGGERS & set(triggers))
        # No inline form (`on: [pull_request]`) that this reader would not see.
        self.assertIsNone(re.search(r"(?m)^on:[ \t]*\S", self.text))

    def test_the_provenance_is_verified_in_the_check_job_before_the_summary(self) -> None:
        self.assertIn("check", self.jobs)
        steps = self.steps("check")
        names = list(steps)
        verify = [n for n, body in steps.items() if any("app_update.py verify" in line for line in body)]
        self.assertEqual(len(verify), 1, f"steps running `app_update.py verify`: {verify}")
        self.assertIn("Summary", names)
        self.assertLess(names.index(verify[0]), names.index("Summary"))
        run = [line for line in steps[verify[0]] if "app_update.py verify" in line]
        self.assertRegex(run[0].strip(), r'^run: python3 \.github/scripts/app_update\.py verify "\$LATEST" "\$DIGEST"$')
        self.assertNotIn("continue-on-error", "\n".join(steps[verify[0]]))

    def test_nothing_may_fail_silently(self) -> None:
        self.assertNotIn("continue-on-error", self.text)

    def test_every_job_that_opens_a_pull_request_waits_for_the_check(self) -> None:
        openers = [name for name, body in self.jobs.items() if any("gh pr create" in line for line in body)]
        self.assertTrue(openers, "no job opens the pull request any more")
        for name in openers:
            with self.subTest(job=name):
                self.assertNotEqual(name, "check")
                self.assertIn("    needs: check", self.jobs[name])
                self.assertTrue(
                    any("needs.check.outputs.newer == 'true'" in line for line in self.jobs[name] if line.startswith("    if:"))
                )


if __name__ == "__main__":
    unittest.main()
