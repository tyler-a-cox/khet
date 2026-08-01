"""Khet (laser chess): a Rust engine with a Python front end.

Everything in this module namespace comes from the compiled ``_engine``
extension - the board, move generation, laser resolution, evaluation and the
alpha-beta search are all Rust. What stays in Python is the part that is not
in the hot loop: the HTTP server, the bot's move-selection policy, and the CLI.

The names here deliberately match ``khet.engine.board`` / ``khet.engine.pieces``
/ ``khet.engine.tree_search`` from the pure-Python original, so code written
against that engine ports with an import change:

    from khet.engine.board import GameBoard, move_name     # before
    from khet import GameBoard, move_name             # after

Differences worth knowing about
-------------------------------
* ``board.make()`` returns an :class:`Undo` object rather than a tuple. It
  still unpacks as ``(move, hit_sq, captured_code)``, and it also has those as
  named attributes.
* ``Searcher`` takes no ``evaluator`` argument. The evaluation is compiled in,
  because an indirect call back into Python at every leaf would cost more than
  the rewrite saves. A pluggable evaluator belongs on the Rust side.
* ``Searcher`` takes no ``options`` argument either. Aspiration windows,
  null-move pruning and capture extensions were measured and removed, and the
  PVS and LMR switches turned out not to be separable - the reduced search is
  performed against the null window, so disabling one disabled both. What is
  left is ``Searcher(reference=True)``, which runs plain alpha-beta for tests
  that need a search making no bets about the move ordering.
* ``Searcher.search()`` releases the GIL, so a threaded server keeps serving
  while a search runs.
"""

from khet._engine import (  # noqa: F401
    ANUBIS,
    COLOR_NAMES,
    COLS,
    DIR_NAMES,
    DOWN,
    EMPTY,
    INFINITY,
    LEFT,
    MATE,
    MATE_THRESHOLD,
    MOVE,
    NUM_SQUARES,
    PHARAOH,
    PYRAMID,
    RED,
    RESTRICTED,
    RIGHT,
    ROT_CCW,
    ROT_CW,
    ROWS,
    SCARAB,
    SILVER,
    SPHINX,
    SWAP,
    TYPE_NAMES,
    UP,
    GameBoard,
    Searcher,
    SearchResult,
    Undo,
    describe,
    encode,
    evaluate,
    evaluate_board_simple,
    make_move,
    move_from,
    move_kind,
    move_name,
    move_to,
    opponent,
    orientation,
    perft,
    piece_color,
    piece_type,
    row_col,
    square,
    square_name,
    __version__,
)

#: Name -> constant lookups, matching the Python engine's module-level dicts.
NAME_TO_COLOR = {name: index for index, name in enumerate(COLOR_NAMES)}
NAME_TO_DIR = {name: index for index, name in enumerate(DIR_NAMES)}
NAME_TO_TYPE = {name: index for index, name in enumerate(TYPE_NAMES) if name}

#: Accepted starting configurations. ``imhotep`` and ``dynasty`` are aliases of
#: ``classic``: they are genuinely different setups in the printed rules, but
#: the data has never differed, and aliasing them keeps that visible rather
#: than shipping three identical tables.
GAME_MODES = ("classic", "imhotep", "dynasty")

__all__ = [
    "GameBoard", "Undo", "Searcher", "SearchResult",
    "make_move", "move_from", "move_to", "move_kind", "move_name",
    "square", "row_col", "square_name",
    "encode", "piece_type", "piece_color", "orientation", "describe",
    "opponent", "evaluate", "evaluate_board_simple", "perft",
    "ROWS", "COLS", "NUM_SQUARES", "RESTRICTED",
    "MOVE", "SWAP", "ROT_CW", "ROT_CCW",
    "UP", "RIGHT", "DOWN", "LEFT", "DIR_NAMES", "NAME_TO_DIR",
    "RED", "SILVER", "COLOR_NAMES", "NAME_TO_COLOR",
    "EMPTY", "PYRAMID", "SCARAB", "ANUBIS", "PHARAOH", "SPHINX",
    "TYPE_NAMES", "NAME_TO_TYPE", "GAME_MODES",
    "MATE", "INFINITY", "MATE_THRESHOLD",
    "__version__",
]
