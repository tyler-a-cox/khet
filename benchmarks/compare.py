#!/usr/bin/env python3
"""Run both engines back to back and report the ratio.

    python3 benchmarks/compare.py                 # perft 3, search 5
    python3 benchmarks/compare.py --perft-depth 4 --search-depth 7   # Rust-only scale
    python3 benchmarks/compare.py --python-engine ~/Projects/khet_python

Absolute timings drift with machine load, so the only number worth quoting is
the ratio between two runs taken in the same sitting.  That is the whole reason
this runs both engines itself instead of comparing against numbers written down
earlier.

Correctness first
-----------------
A faster engine that searches a different tree has not measured anything, so
the report is gated on two equalities before any timing is shown:

* perft must match at every depth (pure rules: move generation, make/unmake,
  laser resolution);
* the search must visit the *same node count* and return the same best move at
  every depth (rules plus ordering, transposition table, and every pruning
  decision).

The second is the strict one.  Node counts agreeing to the node means the two
searches made an identical sequence of decisions, which is a far stronger claim
than "both engines think the position is equal".
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    # Defaults chosen by what CPython can finish in about fifteen seconds.
    # perft 4 is 37.8M nodes - two seconds of Rust, seven minutes of Python.
    parser.add_argument("--perft-depth", type=int, default=3)
    parser.add_argument("--search-depth", type=int, default=5)
    parser.add_argument("--python-engine", default=str(REPO.parent / "khet_python"),
                        help="path to the Python khet checkout")
    parser.add_argument("--python", default=sys.executable,
                        help="interpreter to benchmark (try pypy3)")
    parser.add_argument("--cargo", default=None,
                        help="path to cargo, if it is not on PATH")
    parser.add_argument("--skip-build", action="store_true")
    return parser.parse_args()


# --------------------------------------------------------------------------
# Locating the tools
# --------------------------------------------------------------------------

CARGO_MISSING = """\
cargo was not found{where}.

Install the Rust toolchain:

    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

then either open a new shell or run:

    source "$HOME/.cargo/env"

If Rust is already installed somewhere unusual, point at it directly:

    python3 benchmarks/compare.py --cargo /path/to/cargo
"""


def find_cargo(explicit):
    """Locate cargo, checking the usual place a conda shell will have missed.

    rustup writes `~/.cargo/bin` into the shell profile, but a conda or
    mambaforge base environment often prepends its own PATH afterwards, so a
    perfectly good toolchain can be invisible to `which cargo`.  Check for it
    before telling anyone to install anything.
    """
    if explicit:
        if not Path(explicit).expanduser().exists():
            sys.exit("no cargo at {}".format(explicit))
        return str(Path(explicit).expanduser())

    found = shutil.which("cargo")
    if found:
        return found

    for candidate in (Path.home() / ".cargo" / "bin" / "cargo",
                      Path("/opt/homebrew/bin/cargo"),
                      Path("/usr/local/bin/cargo")):
        if candidate.exists():
            print("note: cargo is not on PATH; using {}".format(candidate))
            return str(candidate)

    sys.exit(CARGO_MISSING.format(where=" on PATH, or in ~/.cargo/bin"))


def find_interpreter(name):
    found = shutil.which(name) or (name if Path(name).exists() else None)
    if found:
        return found
    hint = ""
    if "pypy" in name:
        hint = ("\n\nPyPy is the comparison that should actually inform the "
                "decision - the\nPython engine is written to be PyPy-friendly. "
                "Install it with:\n\n    brew install pypy3\n\n"
                "or benchmark CPython instead by dropping --python.")
    sys.exit("interpreter {!r} not found{}".format(name, hint))


# --------------------------------------------------------------------------
# Rust side
# --------------------------------------------------------------------------

def run_rust(cargo, perft_depth, search_depth, skip_build):
    if not skip_build:
        print("building (release)...", flush=True)
        subprocess.run(
            [cargo, "build", "--release", "--bin", "bench"],
            cwd=REPO, check=True,
        )

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "rust.json"
        subprocess.run(
            [
                cargo, "run", "--release", "--quiet", "--bin", "bench", "--",
                "--perft-depth", str(perft_depth),
                "--search-depth", str(search_depth),
                "--json", str(out),
            ],
            cwd=REPO, check=True,
        )
        return json.loads(out.read_text())


# --------------------------------------------------------------------------
# Python side
# --------------------------------------------------------------------------

PYTHON_DRIVER = r"""
import json, sys, time
sys.path.insert(0, sys.argv[1])
from khet.engine.board import GameBoard, move_name
from khet.engine.tree_search import Searcher

perft_depth = int(sys.argv[2])
search_depth = int(sys.argv[3])

def perft(board, depth):
    if depth == 0 or board.winner is not None:
        return 1
    total = 0
    for move in board.legal_moves():
        undo = board.make(move)
        total += perft(board, depth - 1)
        board.unmake(undo)
    return total

result = {"engine": "python", "perft": [], "search": []}
import platform
result["runtime"] = "{} {} on {} {}".format(
    platform.python_implementation(), platform.python_version(),
    platform.system(), platform.machine())

for depth in range(1, perft_depth + 1):
    if depth < perft_depth:
        perft(GameBoard("classic"), depth)      # warm the JIT under PyPy
    start = time.perf_counter()
    nodes = perft(GameBoard("classic"), depth)
    result["perft"].append(
        {"depth": depth, "nodes": nodes, "seconds": time.perf_counter() - start})

Searcher().search(GameBoard("classic"), 3)      # warm the JIT under PyPy
for depth in range(1, search_depth + 1):
    outcome = Searcher().search(GameBoard("classic"), depth)
    result["search"].append({
        "depth": depth,
        "nodes": outcome.nodes,
        "seconds": outcome.elapsed,
        "score": outcome.score,
        "best": move_name(outcome.move) if outcome.move else "-",
    })
    if outcome.elapsed > 120:
        break

print(json.dumps(result))
"""


def run_python(interpreter, engine_path, perft_depth, search_depth):
    print("running the Python engine (this is the slow half)...", flush=True)
    proc = subprocess.run(
        [interpreter, "-c", PYTHON_DRIVER, str(engine_path),
         str(perft_depth), str(search_depth)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        sys.exit("python benchmark failed:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

def fmt(n):
    return "{:,}".format(int(n))


def rate(row):
    return row["nodes"] / row["seconds"] if row["seconds"] > 0 else 0.0


def report(section, py_rows, rs_rows, extra_columns=()):
    print("\n" + section)
    header = "  {:>5}  {:>13}  {:>11}  {:>11}  {:>8}".format(
        "depth", "nodes", "python", "rust", "speedup")
    print(header)
    print("  " + "-" * (len(header) - 2))

    by_depth = {row["depth"]: row for row in rs_rows}
    problems = []
    speedups = []

    for py in py_rows:
        rs = by_depth.get(py["depth"])
        if rs is None:
            continue
        if py["nodes"] != rs["nodes"]:
            problems.append(
                "depth {}: node counts differ (python {}, rust {})".format(
                    py["depth"], fmt(py["nodes"]), fmt(rs["nodes"])))
        for column in extra_columns:
            if py.get(column) != rs.get(column):
                problems.append("depth {}: {} differs (python {!r}, rust {!r})".format(
                    py["depth"], column, py.get(column), rs.get(column)))

        speedup = py["seconds"] / rs["seconds"] if rs["seconds"] > 0 else float("inf")
        speedups.append(speedup)
        print("  {:>5}  {:>13}  {:>10.3f}s  {:>10.3f}s  {:>7.1f}x".format(
            py["depth"], fmt(py["nodes"]), py["seconds"], rs["seconds"], speedup))

    # The deepest measurement is the one to quote: the shallow ones are
    # dominated by fixed startup costs that shrink to nothing in real use.
    if speedups:
        print("\n  deepest measured speedup: {:.1f}x".format(speedups[-1]))
    return problems


def main():
    args = parse_args()

    # Resolve everything up front.  Discovering a missing tool after the slow
    # half of the benchmark has already run is a waste of a few minutes.
    engine = Path(args.python_engine).expanduser().resolve()
    if not (engine / "khet" / "engine" / "board.py").exists():
        sys.exit("no Python khet engine at {} (pass --python-engine)".format(engine))
    cargo = find_cargo(args.cargo)
    interpreter = find_interpreter(args.python)

    rust = run_rust(cargo, args.perft_depth, args.search_depth, args.skip_build)
    python = run_python(interpreter, engine, args.perft_depth, args.search_depth)

    print("\n" + "=" * 66)
    print("python: {}".format(python["runtime"]))
    print("rust:   {}".format(rust["runtime"]))
    print("=" * 66)

    problems = []
    problems += report("perft  (move generation + make/unmake + laser)",
                       python["perft"], rust["perft"])
    problems += report("search (alpha-beta, TT, ordering, LMR)",
                       python["search"], rust["search"],
                       extra_columns=("score", "best"))

    print()
    if problems:
        print("ENGINES DISAGREE - the timings above are not comparable:")
        for problem in problems:
            print("  - " + problem)
        return 1
    print("engines agree exactly on every node count, score and best move.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
