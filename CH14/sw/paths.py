"""Finding the bitstream and the ELF, from wherever this happens to be running.

The same files sit in three different shapes, and none of them is wrong:

  the repository       CH14/sw/                       CH14/project_sysmon_lcd/out/
  the Jupyter tree     handbook/CH14/sw/              handbook/CH14/project_sysmon_lcd/out/
  the test harness     ch14_sysmon_lcd/sw/            ch14_sysmon_lcd/out/

Jupyter only serves notebooks from under its own directory, and pytest wants a
flat tree it can run in without the notebook's imports; the deploy script
therefore writes both, and the harness flattens out/ up next to sw/.

SEARCHING IS WHY ONE NOTEBOOK WORKS IN ALL THREE. Do not replace this with a
fixed path -- it will be right in whichever layout it was written in and
silently wrong in the other two.
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))

# Relative to sw/, in the order they are tried.
CANDIDATE_DIRS = (
    os.path.join(HERE, os.pardir, "project_sysmon_lcd", "out"),
    os.path.join(HERE, os.pardir, "out"),
    os.path.join(HERE, "out"),
)


def find_artifact(filename, extra_dirs=()):
    """The full path to `filename`, or None if no candidate directory has it."""
    for directory in tuple(extra_dirs) + CANDIDATE_DIRS:
        candidate = os.path.normpath(os.path.join(directory, filename))
        if os.path.isfile(candidate):
            return candidate
    return None


def require_artifact(filename, extra_dirs=()):
    """The same, but says where it looked rather than returning None."""
    found = find_artifact(filename, extra_dirs)
    if found is not None:
        return found
    looked = "\n".join("  " + os.path.normpath(d)
                       for d in tuple(extra_dirs) + CANDIDATE_DIRS)
    raise FileNotFoundError(
        f"could not find {filename}. Looked in:\n{looked}\n"
        f"Build it with:\n"
        f"  vivado -mode batch -source project_sysmon_lcd/build.tcl\n"
        f"  vitis -s sw_mb/build_app.py\n"
        f"and copy it over with deploy/deploy.sh")
