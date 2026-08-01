//! Khet (laser chess) engine core.
//!
//! A port of the board, laser resolution, move generation, evaluation and
//! alpha-beta search from the Python engine at
//! <https://github.com/tyler-a-cox/khet_python>.
//!
//! The port is deliberately faithful: the same representation, the same move
//! ordering, the same tie-breaking, so that node counts are directly comparable
//! between the two engines. Both have since had four search options removed -
//! aspiration windows, null-move pruning, capture extensions, and the separate
//! PVS/LMR switches - after measuring what each was actually worth. The numbers
//! are recorded in [`search`].
//!
//! The one structural difference from Python is that move lists are fixed-size
//! and live on the stack rather than being heap-allocated at every node; see
//! [`board::MoveList`].

pub mod board;
pub mod eval;
pub mod pieces;
pub mod search;

pub use board::{GameBoard, GameMode, MoveList, Undo};
pub use search::{BasicEval, Mode, SearchResult, Searcher};

/// Count leaf nodes at `depth`.  Move generation plus make/unmake, no search
/// logic and no evaluation - the number to watch when optimising the board.
pub fn perft(board: &mut GameBoard, depth: u32) -> u64 {
    if depth == 0 || board.winner >= 0 {
        return 1;
    }
    let moves = board.legal_moves();
    let mut total = 0;
    for &mv in moves.as_slice() {
        let undo = board.make(mv);
        total += perft(board, depth - 1);
        board.unmake(undo);
    }
    total
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::board::{move_name, square, NUM_SQUARES, ROWS, COLS};
    use crate::pieces::{piece_color, piece_type, orientation, EMPTY, SILVER};

    /// Pinned against the Python engine's `tests/test_engine.py`.
    const PERFT_CLASSIC: [(u32, u64); 3] = [(1, 79), (2, 6232), (3, 488195)];

    #[test]
    fn perft_matches_python_reference() {
        for &(depth, expected) in PERFT_CLASSIC.iter() {
            let mut board = GameBoard::default();
            assert_eq!(perft(&mut board, depth), expected, "perft depth {}", depth);
        }
    }

    #[test]
    fn move_to_front_matches_python_list_semantics() {
        // `moves.insert(0, moves.pop(index))`: the element at `index` goes to
        // the front and everything before it shifts right by one.  Nothing is
        // dropped and nothing is duplicated - which is exactly what the first
        // version of this got wrong, silently, for four plies of search.
        for len in 1..=8usize {
            for index in 0..len {
                let mut list = MoveList::new();
                for value in 0..len {
                    list.push(100 + value as u16);
                }
                list.move_to_front(index);

                let mut expected: Vec<u16> = (0..len).map(|v| 100 + v as u16).collect();
                let moved = expected.remove(index);
                expected.insert(0, moved);

                assert_eq!(list.as_slice(), &expected[..], "len {} index {}", len, index);
                // Belt and braces: a permutation, not a rewrite.
                let mut sorted = list.as_slice().to_vec();
                sorted.sort_unstable();
                assert_eq!(
                    sorted,
                    (0..len).map(|v| 100 + v as u16).collect::<Vec<_>>(),
                    "len {} index {} lost or duplicated a move",
                    len,
                    index
                );
            }
        }
    }

    #[test]
    fn make_unmake_restores_the_position() {
        let mut board = GameBoard::default();
        let before_squares = board.squares;
        let before_key = board.key;
        let moves = board.legal_moves();
        for &mv in moves.as_slice() {
            let undo = board.make(mv);
            board.unmake(undo);
            assert_eq!(board.squares, before_squares, "after {}", move_name(mv));
            assert_eq!(board.key, before_key, "key after {}", move_name(mv));
            assert_eq!(board.side_to_move, SILVER);
        }
    }

    #[test]
    fn zobrist_key_matches_a_fresh_rebuild() {
        // Incremental hashing has to agree with hashing from scratch, or the
        // transposition table is silently keyed on nonsense.
        let mut board = GameBoard::default();
        for _ in 0..6 {
            // Re-generate each time: a move that was legal in the starting
            // position need not be legal two plies later.
            let moves = board.legal_moves();
            assert!(!moves.is_empty());
            board.make(moves.moves[0]);
        }

        let mut rebuilt = 0u64;
        for sq in 0..NUM_SQUARES {
            let code = board.squares[sq];
            if code != EMPTY {
                rebuilt ^= board::ZOBRIST[sq][code as usize];
            }
        }
        if board.side_to_move != SILVER {
            rebuilt ^= board::ZOBRIST_SIDE;
        }
        assert_eq!(board.key, rebuilt);
    }

    #[test]
    fn classic_setup_is_symmetric_under_180_rotation() {
        // Every official Khet setup maps onto itself under (row, col) ->
        // (7 - row, 9 - col) with the colors exchanged and orientation + 2.
        let board = GameBoard::default();
        for row in 0..ROWS {
            for col in 0..COLS {
                let code = board.squares[square(row, col)];
                let mirror = board.squares[square(ROWS - 1 - row, COLS - 1 - col)];
                if code == EMPTY {
                    assert_eq!(mirror, EMPTY, "({}, {})", row, col);
                    continue;
                }
                assert_eq!(piece_type(code), piece_type(mirror));
                assert_eq!(piece_color(code) ^ 1, piece_color(mirror));
                assert_eq!((orientation(code) + 2) & 3, orientation(mirror));
            }
        }
    }

    #[test]
    fn search_is_deterministic_and_finds_a_move() {
        let mut board = GameBoard::default();
        let first = Searcher::basic().search(&mut board, 4, None);
        let mut board = GameBoard::default();
        let second = Searcher::basic().search(&mut board, 4, None);
        assert!(first.mv.is_some());
        assert_eq!(first.mv, second.mv);
        assert_eq!(first.score, second.score);
        assert_eq!(first.nodes, second.nodes, "node count must be reproducible");
    }

    /// Pinned from the Python engine.
    ///
    /// `(depth, nodes, re-searches, score, best move)`.  Node counts agreeing
    /// to the node is the strong claim: it means both engines made an identical
    /// sequence of ordering and pruning decisions, not merely that they liked
    /// the same move.
    ///
    /// This runs to depth 6 rather than 5 on purpose.  A `move_to_front` bug
    /// that dropped one legal move and duplicated another survived a check
    /// pinned at depth 5 - frontier nodes cost one evaluation per child
    /// whatever the list contains, so the damage only reached the node count
    /// two plies later.  `tests/test_parity.py` widens the same check to both
    /// modes; this is the fast in-crate version.
    const SEARCH_REFERENCE: [(i32, u64, u64, i32, &str); 6] = [
        (1, 94, 15, 3, "h7-h6"),
        (2, 1_900, 80, 0, "h7-h6"),
        (3, 11_675, 86, 6, "h7-h6"),
        (4, 36_066, 112, 3, "c8-d7"),
        (5, 274_683, 252, 6, "h7-h6"),
        (6, 747_513, 413, 3, "h7-h6"),
    ];

    #[test]
    fn search_matches_the_python_engine_node_for_node() {
        for &(depth, nodes, re_searches, score, best) in SEARCH_REFERENCE.iter() {
            let mut board = GameBoard::default();
            let mut searcher = Searcher::basic();
            let result = searcher.search(&mut board, depth, None);
            assert_eq!(result.nodes, nodes, "node count at depth {}", depth);
            assert_eq!(
                searcher.re_searches, re_searches,
                "re-searches at depth {}",
                depth
            );
            assert_eq!(result.score, score, "score at depth {}", depth);
            assert_eq!(
                result.mv.map(move_name).unwrap_or_default(),
                best,
                "best move at depth {}",
                depth
            );
        }
    }

    /// Turning LMR off strips away the pruning that lets an ordering bug hide
    /// behind a coincidence, so these numbers are a sharper instrument than the
    /// default-options ones even though they are larger.
    #[test]
    fn principal_variation_is_a_playable_line() {
        // The Python engine returns an empty PV at these depths, because its
        // walk probes the root position and the root search never stores it.
        for depth in 1..=5 {
            let mut board = GameBoard::default();
            let result = Searcher::basic().search(&mut board, depth, None);
            let pv = &result.principal_variation;

            assert!(!pv.is_empty(), "empty PV at depth {}", depth);
            assert_eq!(Some(pv[0]), result.mv, "PV must start with the best move");

            let mut replay = GameBoard::default();
            for &mv in pv {
                assert!(
                    replay.legal_moves().contains(mv),
                    "PV move {} is not legal at depth {}",
                    move_name(mv),
                    depth
                );
                replay.make(mv);
                if replay.winner >= 0 {
                    break;
                }
            }
        }
    }

    #[test]
    fn searching_leaves_the_position_unchanged() {
        // Every `make` in the search is paired with an `unmake`, so the
        // position that comes back must be the one that went in.
        //
        // Note what is *not* asserted: `piece_squares` order.  A capture
        // removes an entry and the matching `unmake` appends it, so the list
        // legitimately permutes over a search.  That is load-bearing behaviour
        // (see `board.rs`), not a leak - the position it describes is identical.
        let mut board = GameBoard::default();
        let reference = GameBoard::default();
        let result = Searcher::basic().search(&mut board, 5, None);

        assert!(!result.principal_variation.is_empty());
        assert_eq!(board.squares, reference.squares);
        assert_eq!(board.key, reference.key);
        assert_eq!(board.side_to_move, reference.side_to_move);
        assert_eq!(board.winner, reference.winner);
        assert_eq!(board.pharaoh_squares, reference.pharaoh_squares);
        for color in 0..2 {
            let mut got = board.piece_squares[color].as_slice().to_vec();
            let mut want = reference.piece_squares[color].as_slice().to_vec();
            got.sort_unstable();
            want.sort_unstable();
            assert_eq!(got, want, "a piece went missing from the {} list", color);
        }
    }

    /// The same position under [`Mode::Reference`]: plain alpha-beta, no null
    /// windows and no reductions.
    ///
    /// Worth pinning separately because it is the configuration with no bets in
    /// it. The `move_to_front` bug that dropped a legal move was invisible under
    /// the pruned search for four plies and obvious here, so this is the row
    /// that would catch its successor.
    const REFERENCE_MODE: [(i32, u64, i32); 5] = [
        (1, 79, 3),
        (2, 589, 0),
        (3, 10_643, 6),
        (4, 32_921, 0),
        (5, 538_247, 9),
    ];

    #[test]
    fn reference_mode_matches_the_python_engine() {
        for &(depth, nodes, score) in REFERENCE_MODE.iter() {
            let mut board = GameBoard::default();
            let result = Searcher::reference().search(&mut board, depth, None);
            assert_eq!(result.nodes, nodes, "node count at depth {}", depth);
            assert_eq!(result.score, score, "score at depth {}", depth);
        }
    }

    #[test]
    fn pruning_does_not_change_the_answer_at_shallow_depth() {
        // Null windows are exact; reductions are not, and only engage from
        // depth 3. Through depth 2 the two modes must therefore agree exactly,
        // which pins the null-window machinery on its own.
        for depth in 1..=2 {
            let mut a = GameBoard::default();
            let mut b = GameBoard::default();
            let pruned = Searcher::basic().search(&mut a, depth, None);
            let plain = Searcher::reference().search(&mut b, depth, None);
            assert_eq!(pruned.score, plain.score, "score at depth {}", depth);
        }
    }

    #[test]
    fn pruning_is_worth_having() {
        // The whole justification for the one technique that survived. If this
        // ratio collapses, the reduction table or the ordering has broken and
        // the engine is quietly doing far more work than it should.
        let mut a = GameBoard::default();
        let mut b = GameBoard::default();
        let pruned = Searcher::basic().search(&mut a, 6, None).nodes;
        let plain = Searcher::reference().search(&mut b, 6, None).nodes;
        assert!(
            plain > pruned * 2,
            "pruned {} vs plain {} - pruning has stopped paying",
            pruned,
            plain
        );
    }
}
