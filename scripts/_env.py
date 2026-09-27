"""Stop early, with instructions, if a script is run with the wrong Python.

The Mac's built-in `python3` doesn't have the project's libraries; they live in the
`misconstrue` conda environment that `make setup` creates.
"""
import sys


def require_project_python() -> None:
    try:
        import dotenv  # noqa: F401
        import numpy  # noqa: F401
        import pydantic  # noqa: F401
    except ImportError:
        script = sys.argv[0].rsplit("/", 1)[-1]
        sys.exit(
            f"{script} needs the project's Python environment, not {sys.executable}.\n\n"
            "Use the make commands instead (from the project folder), e.g.:\n"
            "  make fixtures ARGS=\"tjqn57np\"     # import recordings (by link id or recording number)\n"
            "  make bench                         # run the benchmark\n"
            "  make cli ARGS='mask \"hello there\"' # the command-line tool\n\n"
            "Or run it with the environment's Python directly:\n"
            "  /opt/homebrew/Caskroom/miniforge/base/envs/misconstrue/bin/python " + " ".join(sys.argv)
        )
