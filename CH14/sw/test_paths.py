"""Artifact lookup across the three layouts these files are deployed into."""
import os
import tempfile
import unittest

import paths


class Finding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _make(self, *parts):
        path = os.path.join(self.tmp.name, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").close()
        return path

    def test_it_finds_a_file_in_a_directory_it_is_given(self):
        made = self._make("out", "ch14_sysmon_lcd.bit")
        found = paths.find_artifact("ch14_sysmon_lcd.bit",
                                    [os.path.join(self.tmp.name, "out")])
        self.assertEqual(os.path.realpath(found), os.path.realpath(made))

    def test_it_returns_none_when_nothing_has_the_file(self):
        self.assertIsNone(paths.find_artifact("nonesuch.bit",
                                              [self.tmp.name]))

    def test_a_directory_it_is_given_wins_over_the_built_in_ones(self):
        """The notebook passes the directory it worked out from its own
        location, and that has to beat a stale copy in the repository."""
        made = self._make("mine", "ch14_sysmon_lcd.bit")
        found = paths.find_artifact("ch14_sysmon_lcd.bit",
                                    [os.path.join(self.tmp.name, "mine")])
        self.assertEqual(os.path.realpath(found), os.path.realpath(made))

    def test_requiring_a_missing_file_says_where_it_looked(self):
        """A path error that does not say what it tried is a worse error than
        no error at all, on a board reached only over ssh."""
        with self.assertRaises(FileNotFoundError) as caught:
            paths.require_artifact("nonesuch.bit", [self.tmp.name])
        message = str(caught.exception)
        self.assertIn(self.tmp.name, message)
        self.assertIn("build.tcl", message)

    def test_it_covers_both_deployed_layouts(self):
        """The Jupyter tree keeps out/ under project_sysmon_lcd/; the test
        harness flattens it up next to sw/. Both have to be searched or the
        notebook works in one place and not the other."""
        relative = [os.path.relpath(d, paths.HERE)
                    for d in paths.CANDIDATE_DIRS]
        self.assertIn(os.path.join(os.pardir, "project_sysmon_lcd", "out"),
                      relative)
        self.assertIn(os.path.join(os.pardir, "out"), relative)


if __name__ == "__main__":
    unittest.main()
