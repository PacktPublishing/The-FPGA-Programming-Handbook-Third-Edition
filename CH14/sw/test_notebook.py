"""The notebook, checked without running it.

WHY THIS EXISTS

CH13's notebook shipped once with a cell collapsed into a single
1116-character line -- `import ipywidgets as widgetsfrom IPython.display
import display...` -- which is a syntax error the moment anyone runs it.

The cause is a trap in nbformat that looks like nothing: a cell's `source` is
a LIST OF LINES, and Jupyter joins them with NO separator. Every line except
the last has to carry its own trailing newline. Build the list with
`text.split("\n")` and the newlines are gone, so the cell becomes one line,
and it looks perfectly correct in the JSON.

Nothing catches that except looking, so this looks. It compiles every code
cell too, which is free and needs no board.
"""
import ast
import json
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
NOTEBOOK = os.path.join(HERE, os.pardir, "project_sysmon_lcd", "notebooks",
                        "ch14_sysmon_lcd.ipynb")


class TheNotebook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(NOTEBOOK):
            raise unittest.SkipTest(f"not found: {NOTEBOOK}")
        with open(NOTEBOOK) as handle:
            cls.notebook = json.load(handle)
        cls.cells = cls.notebook["cells"]

    def test_it_is_a_version_4_notebook(self):
        self.assertEqual(self.notebook["nbformat"], 4)

    def test_it_has_cells(self):
        self.assertGreater(len(self.cells), 0)

    def test_every_source_line_but_the_last_ends_in_a_newline(self):
        """Jupyter joins a cell's source list with NO separator. A list built
        by splitting on newlines and not putting them back collapses the whole
        cell onto one line -- which for a code cell is a syntax error, and for
        a markdown cell is a wall of text."""
        for index, cell in enumerate(self.cells):
            source = cell["source"]
            for line in source[:-1]:
                self.assertTrue(
                    line.endswith("\n"),
                    f"cell {index} ({cell['cell_type']}): line {line[:40]!r} "
                    f"has no trailing newline, so this cell will render as "
                    f"one line")

    def test_no_code_cell_is_suspiciously_one_long_line(self):
        """The symptom the newline bug produces, checked directly as well as
        by its cause -- a cell can be collapsed by hand too."""
        for index, cell in enumerate(self.cells):
            if cell["cell_type"] != "code":
                continue
            text = "".join(cell["source"])
            if len(text) > 200:
                self.assertIn("\n", text.strip(),
                              f"code cell {index} is {len(text)} characters "
                              f"on a single line")

    def test_every_code_cell_compiles(self):
        """A syntax error needs no board and no execution to find."""
        for index, cell in enumerate(self.cells):
            if cell["cell_type"] != "code":
                continue
            text = "".join(cell["source"])
            try:
                compile(text, f"cell {index}", "exec")
            except SyntaxError as problem:
                self.fail(f"code cell {index} does not compile: {problem}\n"
                          f"{text[:400]}")

    def test_the_code_cells_only_import_what_is_deployed(self):
        """The deploy script copies a fixed list of modules. An import the
        notebook picked up from the repository, and that the script does not
        copy, works here and fails on the board."""
        deployed = {"ch14", "mailbox", "paths", "sysmon", "grove_lcd",
                    "microblaze_v", "elf", "os", "sys", "time", "json"}
        allowed_third_party = {"pynq", "numpy", "matplotlib", "ipywidgets",
                               "IPython"}
        for index, cell in enumerate(self.cells):
            if cell["cell_type"] != "code":
                continue
            tree = ast.parse("".join(cell["source"]))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module.split(".")[0]]
                for name in names:
                    self.assertIn(name, deployed | allowed_third_party,
                                  f"cell {index} imports {name!r}, which "
                                  f"deploy/deploy.sh does not copy")

    def test_it_explains_the_two_masters_rule_before_taking_the_panel(self):
        """Driving the IIC from the PS while the processor runs produces
        nonsense rather than an error, and nothing in the hardware prevents
        it. If the cell that does it stops explaining why it halts first,
        someone will remove the halt."""
        text = json.dumps(self.notebook)
        self.assertIn("take_panel", text)
        self.assertIn("two masters", text.lower())


if __name__ == "__main__":
    unittest.main()
