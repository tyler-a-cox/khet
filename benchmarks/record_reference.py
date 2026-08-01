#!/usr/bin/env python3
"""Record the Python engine's behaviour as a fixture for the parity tests.

    python3 benchmarks/record_reference.py --python-engine ~/Projects/khet_python

Writes ``tests/reference/python_engine.json``: perft counts, and for several
option sets the node count, score, best move, principal variation and
re-search count at each depth.

Why a fixture and not just "run both engines in the test"
---------------------------------------------------------
The Python engine takes about a minute to produce these numbers and the Rust
engine takes under a second. Recording once and asserting against the recording
keeps `pytest` fast enough to run on every change, which is the only way a
parity check actually gets run.

Why this file exists at all
---------------------------
The first version of this port had a bug in `MoveList::move_to_front` that
dropped one legal move and duplicated another at frontier nodes. It was
invisible through depth 4 - at a frontier node every child costs exactly one
evaluation, so the *node count* is identical whichever moves are in the list -
and only started shifting the tree around depth 5. A parity check pinned at
depth 5 with the default options missed it by luck; this one spans depths and
option sets precisely so that a bug has nowhere quiet to sit.

The script is resumable: it writes after each configuration, and skips work
already present in the fixture. The Python engine is slow enough that this
matters.
"""

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "tests" / "reference" / "python_engine.json"

#: (name, `reference` flag, deepest depth to record).
#:
#: Both searches, because the pruned one is the one that ships and the plain one
#: is the one with no bets in it - an ordering bug that the pruned search hides
#: behind a coincidence shows up immediately in the other.
#:
#: Depth caps are set by what CPython will finish in a reasonable time, not by
#: what is interesting: the reference search has no reductions and explodes.
CONFIGS = [
    ("pruned", False, 6),
    ("reference", True, 5),
]

PERFT_DEPTH = 3


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-engine", default=str(REPO.parent / "khet_python"))
    parser.add_argument("--force", action="store_true",
                        help="re-record everything instead of resuming")
    return parser.parse_args()


def main():
    args = parse_args()
    engine = Path(args.python_engine).expanduser().resolve()
    if not (engine / "khet" / "engine" / "board.py").exists():
        sys.exit("no Python khet engine at {} (pass --python-engine)".format(engine))
    sys.path.insert(0, str(engine))

    from khet.engine.board import GameBoard, move_name
    from khet.engine.tree_search import Searcher

    def perft(board, depth):
        if depth == 0 or board.winner is not None:
            return 1
        total = 0
        for move in board.legal_moves():
            undo = board.make(move)
            total += perft(board, depth - 1)
            board.unmake(undo)
        return total

    fixture = {}
    if FIXTURE.exists() and not args.force:
        fixture = json.loads(FIXTURE.read_text())
    fixture.setdefault("search", {})
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)

    import platform
    fixture["recorded_with"] = "{} {}".format(
        platform.python_implementation(), platform.python_version())

    if "perft" not in fixture:
        print("perft...", flush=True)
        fixture["perft"] = [
            {"depth": d, "nodes": perft(GameBoard("classic"), d)}
            for d in range(1, PERFT_DEPTH + 1)
        ]
        FIXTURE.write_text(json.dumps(fixture, indent=2) + "\n")

    for name, reference, max_depth in CONFIGS:
        if name in fixture["search"]:
            print("{}: already recorded, skipping".format(name), flush=True)
            continue
        print("{}: recording depths 1-{}...".format(name, max_depth),
              end="", flush=True)
        rows = []
        for depth in range(1, max_depth + 1):
            searcher = Searcher(reference=reference)
            result = searcher.search(GameBoard("classic"), depth)
            rows.append({
                "depth": depth,
                "nodes": result.nodes,
                "score": result.score,
                "best": move_name(result.move) if result.move else None,
                "pv": [move_name(m) for m in result.principal_variation],
                "re_searches": searcher.re_searches,
            })
            print(" {}".format(depth), end="", flush=True)
        print()
        fixture["search"][name] = {"reference": reference, "rows": rows}
        # Write after every configuration: the slow ones are slow enough that
        # losing the whole run to a timeout would be genuinely annoying.
        FIXTURE.write_text(json.dumps(fixture, indent=2) + "\n")

    print("\nwrote {}".format(FIXTURE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
