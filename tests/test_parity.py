"""The Rust engine must reproduce the Python engine's search exactly.

Run with ``pytest`` after ``maturin develop``. The fixture in
``tests/reference/python_engine.json`` is recorded by
``benchmarks/record_reference.py``; regenerate it if the Python engine changes.

What "exactly" means, and why the node count is the assertion that matters
-------------------------------------------------------------------------
Two engines returning the same best move is weak evidence - a coarse evaluation
leaves most positions full of ties, so two quite different searches will often
agree on the move. Two engines visiting the *same number of nodes* means they
made an identical sequence of ordering, transposition and pruning decisions.

This is not hypothetical carefulness. The first version of this port dropped a
legal move and duplicated another at frontier nodes, and it was invisible for
four plies: at a frontier node every child costs exactly one evaluation, so the
node count is the same whichever moves are in the list. It only began to shift
the tree at depth 5, and a parity check pinned at depth 5 under the pruned
search happened to agree anyway. Hence ``reference`` mode - plain alpha-beta,
no null windows and no reductions - which strips away the pruning that lets a
bug hide behind a coincidence.
"""

import json
from pathlib import Path

import pytest

import khet as K

FIXTURE = Path(__file__).parent / "reference" / "python_engine.json"
REFERENCE = json.loads(FIXTURE.read_text())


def search_cases():
    for name, config in sorted(REFERENCE["search"].items()):
        for row in config["rows"]:
            yield pytest.param(
                name, config["reference"], row,
                id="{}-d{}".format(name, row["depth"]),
            )


@pytest.mark.parametrize("depth,expected", [
    (row["depth"], row["nodes"]) for row in REFERENCE["perft"]
])
def test_perft_matches_python(depth, expected):
    assert K.perft(K.GameBoard("classic"), depth) == expected


@pytest.mark.parametrize("name,reference,expected", list(search_cases()))
def test_search_matches_python(name, reference, expected):
    searcher = K.Searcher(reference=reference)
    result = searcher.search(K.GameBoard("classic"), expected["depth"])

    assert result.nodes == expected["nodes"], "node count"
    assert result.score == expected["score"], "score"
    best = K.move_name(result.move) if result.move is not None else None
    assert best == expected["best"], "best move"
    # Re-searches are a second, independent view of the same claim: it counts
    # how often a null-window or reduced search had to be redone, which depends
    # on the ordering the search actually saw.
    assert searcher.re_searches == expected["re_searches"], "re-searches"
    # Both engines now recover the PV the same way, so this is comparable too.
    assert [K.move_name(m) for m in result.principal_variation] == expected["pv"]


@pytest.mark.parametrize("name,reference,expected", list(search_cases()))
def test_principal_variation_is_playable(name, reference, expected):
    """Beyond matching Python, the PV has to be a real line.

    Both engines used to return an empty PV at most depths: the walk started by
    probing the root position, which the root search never stores. Where it did
    find something it was worse than empty - the entry belonged to an unrelated
    deeper context that transposed back to the opening, so the reported line did
    not even begin with the move being played. Fixed in both, so these
    properties should now hold everywhere.
    """
    result = K.Searcher(reference=reference).search(
        K.GameBoard("classic"), expected["depth"]
    )
    pv = result.principal_variation

    assert pv, "PV should never be empty when a move was found"
    assert K.move_name(pv[0]) == expected["best"], "PV must start with the move played"
    assert len(pv) <= expected["depth"], "PV cannot be longer than the search"

    # Replaying it has to work: every move legal in the position it is played in.
    board = K.GameBoard("classic")
    for move in pv:
        assert move in board.legal_moves(), K.move_name(move)
        board.make(move)
        if board.winner is not None:
            break


def test_pruning_is_worth_having():
    """The justification for the one technique that survived.

    Four others were measured and removed. This one stayed because it is worth
    roughly 12x at depth 7; if the ratio collapses, the reduction table or the
    move ordering has broken.
    """
    pruned = K.Searcher().search(K.GameBoard("classic"), 6).nodes
    plain = K.Searcher(reference=True).search(K.GameBoard("classic"), 6).nodes
    assert plain > pruned * 2, "pruned {:,} vs plain {:,}".format(pruned, plain)


def test_search_is_reproducible():
    first = K.Searcher().search(K.GameBoard("classic"), 5)
    second = K.Searcher().search(K.GameBoard("classic"), 5)
    assert (first.nodes, first.score, first.move) == (
        second.nodes, second.score, second.move
    )


def test_searcher_reports_its_mode():
    assert K.Searcher().reference is False
    assert K.Searcher(reference=True).reference is True


def test_make_unmake_round_trips():
    board = K.GameBoard("classic")
    reference = K.GameBoard("classic")
    for move in board.legal_moves():
        undo = board.make(move)
        board.unmake(undo)
        assert board.squares == reference.squares, K.move_name(move)
        assert board.key == reference.key, K.move_name(move)
        assert board.side_to_move == reference.side_to_move


def test_undo_record_unpacks_like_the_python_tuple():
    board = K.GameBoard("classic")
    undo = board.make(board.legal_moves()[0])
    move, hit_sq, captured_code = undo
    assert (move, hit_sq, captured_code) == (
        undo.move, undo.hit_sq, undo.captured_code
    )


def test_winner_is_none_while_the_game_runs():
    # The Python engine used `None`, and the server tests `is not None`
    # everywhere; -1 would be quietly truthy.
    assert K.GameBoard("classic").winner is None


def test_invalid_game_mode_raises():
    with pytest.raises(ValueError):
        K.GameBoard("not-a-mode")
