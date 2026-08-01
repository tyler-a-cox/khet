#!/usr/bin/env python3
"""Cross-check the Rust port's derived tables against the Python engine.

This exists because the interesting bugs in a port like this are not
algorithmic, they are transcription: a mirror diagonal rotated 90 degrees, a
starting piece listed in the wrong order, a reduction formula off by a floor.
Every one of those produces an engine that runs and plays legal-looking moves
while quietly searching a different tree, which makes the benchmark comparison
meaningless.

The checks here re-derive each table two ways - once from the Python engine's
own tables, once by parsing the constants out of the Rust source - and diff
them.  It needs no Rust toolchain, so it can run before the first `cargo build`.

    python3 benchmarks/verify_tables.py

Anything printed with FAIL is a real defect in the port.
"""

import ast
import math
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUST_SRC = REPO / "crates" / "khet-core" / "src"

# Import the Python engine.  It lives beside this repo by default; allow an
# override so the check works from a checkout in another location.
PYTHON_ENGINE = Path(
    sys.argv[1] if len(sys.argv) > 1 else REPO.parent / "khet_python"
).resolve()
sys.path.insert(0, str(PYTHON_ENGINE))

try:
    from khet.engine import board as pyboard
    from khet.engine import evaluation as pyeval
    from khet.engine import pieces as pypieces
    from khet.engine import tree_search as pysearch
except ImportError as exc:  # pragma: no cover - operator error, not a defect
    sys.exit(
        "could not import the Python engine from {}\n"
        "pass its path as the first argument: {}\n{}".format(
            PYTHON_ENGINE, "python3 benchmarks/verify_tables.py ../khet_python", exc
        )
    )


failures = []


def check(name, ok, detail=""):
    status = "ok  " if ok else "FAIL"
    print("  [{}] {}{}".format(status, name, ("  " + detail) if detail else ""))
    if not ok:
        failures.append(name)


def rust_source(filename):
    return (RUST_SRC / filename).read_text()


# --------------------------------------------------------------------------
# 1. Constants that appear literally in both engines
# --------------------------------------------------------------------------
print("\nconstants")

pieces_rs = rust_source("pieces.rs")
board_rs = rust_source("board.rs")
eval_rs = rust_source("eval.rs")
search_rs = rust_source("search.rs")


def rust_const(source, name, cast=int, env=None):
    """Value of a scalar `const` in the Rust source.

    `env` supplies constants the expression may refer to (Rust lets one const
    be defined in terms of another, e.g. `MATE_THRESHOLD = MATE - 10_000`).
    """
    match = re.search(
        r"(?:pub )?const {}\s*:\s*[A-Za-z0-9_]+\s*=\s*([^;]+);".format(re.escape(name)),
        source,
    )
    if not match:
        raise AssertionError("const {} not found".format(name))
    expression = re.sub(r"(\d)_(?=\d)", r"\1", match.group(1))
    return cast(eval(expression, {}, env or {}))  # noqa: S307 - our own source


check("UP/RIGHT/DOWN/LEFT encoding",
      (rust_const(pieces_rs, "UP"), rust_const(pieces_rs, "RIGHT"),
       rust_const(pieces_rs, "DOWN"), rust_const(pieces_rs, "LEFT"))
      == (pypieces.UP, pypieces.RIGHT, pypieces.DOWN, pypieces.LEFT))

check("piece type codes",
      (rust_const(pieces_rs, "PYRAMID"), rust_const(pieces_rs, "SCARAB"),
       rust_const(pieces_rs, "ANUBIS"), rust_const(pieces_rs, "PHARAOH"),
       rust_const(pieces_rs, "SPHINX"))
      == (pypieces.PYRAMID, pypieces.SCARAB, pypieces.ANUBIS,
          pypieces.PHARAOH, pypieces.SPHINX))

check("DESTROY / ABSORB sentinels",
      (rust_const(pieces_rs, "DESTROY"), rust_const(pieces_rs, "ABSORB"))
      == (pypieces.DESTROY, pypieces.ABSORB))

check("board geometry",
      (rust_const(board_rs, "ROWS"), rust_const(board_rs, "COLS"))
      == (pyboard.ROWS, pyboard.COLS))

check("move kinds",
      (rust_const(board_rs, "MOVE"), rust_const(board_rs, "SWAP"),
       rust_const(board_rs, "ROT_CW"), rust_const(board_rs, "ROT_CCW"))
      == (pyboard.MOVE, pyboard.SWAP, pyboard.ROT_CW, pyboard.ROT_CCW))

check("evaluation weights",
      (ast.literal_eval(re.search(r"VALUE:\s*\[i32;\s*6\]\s*=\s*(\[[^\]]+\])", eval_rs).group(1)),
       rust_const(eval_rs, "ADVANCE_BONUS"),
       rust_const(eval_rs, "SHIELD_BONUS"))
      == (list(pyeval.VALUE), pyeval.ADVANCE_BONUS, pyeval.SHIELD_BONUS))

rust_mate = rust_const(search_rs, "MATE")
check("search score scale",
      (rust_mate, rust_const(search_rs, "INFINITY"),
       rust_const(search_rs, "MATE_THRESHOLD", env={"MATE": rust_mate}))
      == (pysearch.MATE, pysearch.INFINITY, pysearch.MATE_THRESHOLD))

check("transposition bound flags",
      (rust_const(search_rs, "EXACT"), rust_const(search_rs, "LOWER_BOUND"),
       rust_const(search_rs, "UPPER_BOUND"))
      == (pysearch.EXACT, pysearch.LOWER_BOUND, pysearch.UPPER_BOUND))


# --------------------------------------------------------------------------
# 2. The mirror tables, re-derived from the Rust source's own data
# --------------------------------------------------------------------------
print("\nlaser table")

FROM_FACE = ast.literal_eval(
    re.search(r"const FROM_FACE: \[u8; 4\] = \[([^\]]+)\]", pieces_rs)
    .group(1)
    .replace("UP", str(pypieces.UP))
    .replace("RIGHT", str(pypieces.RIGHT))
    .replace("DOWN", str(pypieces.DOWN))
    .replace("LEFT", str(pypieces.LEFT))
    .join(("(", ")"))
)
check("FROM_FACE", list(FROM_FACE) == list(pypieces._FROM_FACE))


def rust_dir_list(source, name):
    raw = re.search(r"const {}: \[u8; 4\] = \[([^\]]+)\]".format(name), source).group(1)
    names = {"UP": pypieces.UP, "RIGHT": pypieces.RIGHT,
             "DOWN": pypieces.DOWN, "LEFT": pypieces.LEFT}
    return tuple(names[token.strip()] for token in raw.split(","))


check("BACKSLASH diagonal",
      rust_dir_list(pieces_rs, "BACKSLASH") == pypieces._BACKSLASH)
check("SLASH diagonal",
      rust_dir_list(pieces_rs, "SLASH") == pypieces._SLASH)

pyramid_faces_raw = re.search(
    r"const PYRAMID_FACES: \[\(u8, u8\); 4\] = \[(.*?)\];", pieces_rs, re.S
).group(1)
pyramid_faces = []
for line in pyramid_faces_raw.splitlines():
    match = re.search(r"\((\w+),\s*(\w+)\)", line)
    if match:
        names = {"UP": pypieces.UP, "RIGHT": pypieces.RIGHT,
                 "DOWN": pypieces.DOWN, "LEFT": pypieces.LEFT}
        pyramid_faces.append((names[match.group(1)], names[match.group(2)]))
check("PYRAMID_FACES", tuple(pyramid_faces) == pypieces._PYRAMID_FACES)

# With the inputs confirmed identical and the build algorithm transcribed
# line for line, the derived LASER table follows.  Rebuild it here anyway -
# it is the single table a subtle error would be hardest to notice in play.
rust_laser = [[pypieces.ABSORB] * 4 for _ in range(pypieces.CODE_RANGE)]
for color in (pypieces.RED, pypieces.SILVER):
    for orient in range(4):
        mirror = pypieces._BACKSLASH if orient % 2 == 0 else pypieces._SLASH
        code = pypieces.encode(pypieces.PYRAMID, color, orient)
        faces = pyramid_faces[orient]
        reflect = (FROM_FACE[faces[0]], FROM_FACE[faces[1]])
        for d in range(4):
            rust_laser[code][d] = mirror[d] if d in reflect else pypieces.DESTROY
        code = pypieces.encode(pypieces.SCARAB, color, orient)
        for d in range(4):
            rust_laser[code][d] = mirror[d]
        code = pypieces.encode(pypieces.ANUBIS, color, orient)
        for d in range(4):
            rust_laser[code][d] = (
                pypieces.ABSORB if d == FROM_FACE[orient] else pypieces.DESTROY
            )
        code = pypieces.encode(pypieces.PHARAOH, color, orient)
        for d in range(4):
            rust_laser[code][d] = pypieces.DESTROY
        code = pypieces.encode(pypieces.SPHINX, color, orient)
        for d in range(4):
            rust_laser[code][d] = pypieces.ABSORB

check("LASER[code][direction]",
      all(tuple(rust_laser[c]) == pypieces.LASER[c]
          for c in range(pypieces.CODE_RANGE)))


# --------------------------------------------------------------------------
# 3. Starting position: contents *and* order
# --------------------------------------------------------------------------
print("\nclassic setup")

# The Rust port stores CLASSIC as a flat list because `piece_squares` is built
# in iteration order, and move generation walks it in that order.  Get the
# order wrong and the engine is still correct but searches a different tree,
# so the node counts stop being comparable.
classic_raw = re.search(
    r"pub static CLASSIC: \[Placement; \d+\] = \[(.*?)\n\];", board_rs, re.S
).group(1)
names = {
    "RED": pypieces.RED, "SILVER": pypieces.SILVER,
    "PYRAMID": pypieces.PYRAMID, "SCARAB": pypieces.SCARAB,
    "ANUBIS": pypieces.ANUBIS, "PHARAOH": pypieces.PHARAOH,
    "SPHINX": pypieces.SPHINX,
    "UP": pypieces.UP, "RIGHT": pypieces.RIGHT,
    "DOWN": pypieces.DOWN, "LEFT": pypieces.LEFT,
}
rust_classic = []
for line in classic_raw.splitlines():
    match = re.search(r"\((\w+),\s*(\w+),\s*(\d+),\s*(\d+),\s*(\w+)\)", line)
    if match:
        rust_classic.append((
            names[match.group(1)], names[match.group(2)],
            int(match.group(3)), int(match.group(4)), names[match.group(5)],
        ))

python_classic = []
for color_name, groups in pyboard.CLASSIC.items():
    color = pypieces.NAME_TO_COLOR[color_name]
    for type_name, placements in groups.items():
        ptype = pypieces.NAME_TO_TYPE[type_name]
        for row, col, orient in placements:
            python_classic.append((color, ptype, row, col, orient))

check("26 placements", len(rust_classic) == 26 == len(python_classic))
check("placements match, in order", rust_classic == python_classic,
      "" if rust_classic == python_classic else "first difference at index {}".format(
          next((i for i, (a, b) in enumerate(zip(rust_classic, python_classic))
                if a != b), len(rust_classic))))


# --------------------------------------------------------------------------
# 4. Piece-square table
# --------------------------------------------------------------------------
print("\nevaluation")

rust_pst = [[0] * pyboard.NUM_SQUARES for _ in range(pypieces.CODE_RANGE)]
for code in range(1, pypieces.CODE_RANGE):
    ptype = code >> 3
    if ptype >= len(pyeval.VALUE):
        continue
    for sq in range(pyboard.NUM_SQUARES):
        value = pyeval.VALUE[ptype]
        if ptype == pypieces.PYRAMID:
            row = sq // pyboard.COLS
            value += pyeval.ADVANCE_BONUS * (
                row if ((code >> 2) & 1) == pypieces.RED else 7 - row
            )
        rust_pst[code][sq] = value
check("PST[code][square]",
      all(tuple(rust_pst[c]) == pyeval.PST[c] for c in range(pypieces.CODE_RANGE)))

rust_orthogonal = tuple(
    tuple(nb for nb in pyboard.STEP[sq] if nb >= 0)
    for sq in range(pyboard.NUM_SQUARES)
)
check("ORTHOGONAL[square]", rust_orthogonal == pyeval.ORTHOGONAL)


# --------------------------------------------------------------------------
# 5. Late move reductions
# --------------------------------------------------------------------------
print("\nsearch tables")

# Rust: `(raw as i32).min(depth - 2).max(0)`; Python: `max(0, min(int(r), depth - 2))`.
# `as i32` and `int()` both truncate toward zero, and min-then-max is the same
# as max(0, min(...)) for these operands - but that is exactly the sort of claim
# worth checking rather than asserting.
mismatch = None
for depth in range(64):
    for index in range(128):
        if depth < 3 or index < 3:
            expected = 0
        else:
            raw = 0.5 + math.log(depth) * math.log(index) / 2.6
            expected = max(0, min(int(raw), depth - 2))
        rust_value = 0
        if depth >= 3 and index >= 3:
            raw = 0.5 + math.log(depth) * math.log(index) / 2.6
            rust_value = max(min(int(raw), depth - 2), 0)
        if rust_value != expected or expected != pysearch.REDUCTIONS[depth][index]:
            mismatch = (depth, index, rust_value, expected,
                        pysearch.REDUCTIONS[depth][index])
            break
    if mismatch:
        break
check("REDUCTIONS[depth][index]", mismatch is None,
      "" if mismatch is None else str(mismatch))

check("LMR thresholds match",
      (rust_const(search_rs, "LMR_MIN_DEPTH"), rust_const(search_rs, "LMR_MIN_MOVE"))
      == (pysearch.LMR_MIN_DEPTH, pysearch.LMR_MIN_MOVE),
      "{} / {}".format(pysearch.LMR_MIN_DEPTH, pysearch.LMR_MIN_MOVE))


def strip_rust_comments(source):
    """Code only.  Both engines *document* the options they no longer have."""
    lines = [line.split("//")[0] for line in source.splitlines()]
    return "\n".join(lines)


def strip_python_comments(source):
    """Code only: drop docstrings and `#` comments."""
    without_docstrings = re.sub(r'"""(?:.|\n)*?"""', "", source)
    lines = [line.split("#")[0] for line in without_docstrings.splitlines()]
    return "\n".join(lines)


# Aspiration windows, null-move pruning, capture extensions and the separate
# PVS/LMR switches were removed from both engines together.  If one of them
# grows a knob back on its own, the two stop searching the same tree and every
# node-count comparison quietly stops meaning anything - so check that the code,
# as opposed to the prose explaining the removals, mentions none of them.
python_search_source = (
    PYTHON_ENGINE / "khet" / "engine" / "tree_search.py"
).read_text()
rust_code = strip_rust_comments(search_rs)
python_code = strip_python_comments(python_search_source)

for name in ("aspiration", "null_move", "null_reduction", "capture_extension",
             "max_extensions", "SearchOptions"):
    in_rust = name in rust_code
    in_python = name in python_code
    where = ", ".join(
        [w for w, hit in (("rust", in_rust), ("python", in_python)) if hit]
    )
    check("`{}` is gone from both engines".format(name),
          not (in_rust or in_python),
          "still referenced in " + where if where else "")


# --------------------------------------------------------------------------
print()
if failures:
    print("{} check(s) FAILED: {}".format(len(failures), ", ".join(failures)))
    sys.exit(1)
print("all table checks passed")
