//! Static evaluation of a Khet position.
//!
//! A direct port of `khet/engine/evaluation.py`.  Always returned from one
//! color's point of view: positive is good for that color.  The search calls it
//! with the side to move, which is what negamax needs, and it must be
//! antisymmetric - `evaluate(board, RED) == -evaluate(board, SILVER)` - or the
//! values negamax backs up are meaningless.
//!
//! What is deliberately not here
//! -----------------------------
//! This evaluation has no representation of pharaoh vulnerability, so it cannot
//! predict the tactical laser shots that decide most Khet games.  A larger
//! beam-aware evaluator was measured against it in the Python engine and lost
//! on the clock (roughly 25% in a 20 game match) because the extra knowledge
//! cost about a ply of depth and only fired in the ~4% of positions where a
//! beam terminates on something destructible.  Closing the gap is the job of a
//! learned evaluation, not of more hand-written terms.

use crate::board::{GameBoard, COLS, NUM_SQUARES};
use crate::pieces::{CODE_RANGE, PYRAMID, RED};

/// Material value indexed by piece type constant.
///
/// Scarabs and sphinxes are worth nothing because they can never be destroyed,
/// and the pharaoh is worth nothing because losing one is terminal and the
/// search scores that with a mate score.  Giving the pharaoh a large material
/// value instead is how engines end up nursing a "winning" score they never
/// convert.
pub const VALUE: [i32; 6] = [0, 100, 0, 40, 0, 0];

/// Per rank a pyramid has advanced toward the opponent's home rank.
pub const ADVANCE_BONUS: i32 = 3;

/// Per friendly piece orthogonally adjacent to your own pharaoh.  Only the four
/// orthogonal squares count: a beam travels along ranks and files, so a piece
/// sitting diagonally from the pharaoh blocks nothing.
pub const SHIELD_BONUS: i32 = 6;

const fn build_piece_square_table() -> [[i32; NUM_SQUARES]; CODE_RANGE] {
    // The evaluation runs at every leaf of the search, so the per-piece branch
    // ladder (type test, color test, row arithmetic) is folded into one table.
    let mut table = [[0i32; NUM_SQUARES]; CODE_RANGE];
    let mut code = 1usize;
    while code < CODE_RANGE {
        let ptype = (code >> 3) as u8;
        if (ptype as usize) < 6 {
            let mut sq = 0usize;
            while sq < NUM_SQUARES {
                let mut value = VALUE[ptype as usize];
                if ptype == PYRAMID {
                    let row = (sq / COLS) as i32;
                    // Red starts on row 0 and advances downward, silver reversed.
                    value += ADVANCE_BONUS
                        * if ((code >> 2) & 1) as u8 == RED {
                            row
                        } else {
                            7 - row
                        };
                }
                table[code][sq] = value;
                sq += 1;
            }
        }
        code += 1;
    }
    table
}

/// `PST[code][sq]` -> material plus advancement for that piece there.
pub static PST: [[i32; NUM_SQUARES]; CODE_RANGE] = build_piece_square_table();

const fn build_orthogonal_table() -> ([[u8; 4]; NUM_SQUARES], [u8; NUM_SQUARES]) {
    // The shield term only ever looks at the first square of each ray out of
    // the pharaoh, which is just the orthogonal neighbour.
    let mut squares = [[0u8; 4]; NUM_SQUARES];
    let mut counts = [0u8; NUM_SQUARES];
    let step = STEP_TABLE;
    let mut sq = 0usize;
    while sq < NUM_SQUARES {
        let mut n = 0usize;
        let mut dir = 0usize;
        while dir < 4 {
            let nb = step[sq][dir];
            if nb >= 0 {
                squares[sq][n] = nb as u8;
                n += 1;
            }
            dir += 1;
        }
        counts[sq] = n as u8;
        sq += 1;
    }
    (squares, counts)
}

// `STEP` is a `static`, which const evaluation cannot read; rebuild the same
// table as a `const` for use here.  Identical data, checked by `tests`.
const STEP_TABLE: [[i8; 4]; NUM_SQUARES] = {
    let mut table = [[-1i8; 4]; NUM_SQUARES];
    let row_delta: [i32; 4] = [-1, 0, 1, 0];
    let col_delta: [i32; 4] = [0, 1, 0, -1];
    let mut sq = 0usize;
    while sq < NUM_SQUARES {
        let row = (sq / COLS) as i32;
        let col = (sq % COLS) as i32;
        let mut dir = 0usize;
        while dir < 4 {
            let new_row = row + row_delta[dir];
            let new_col = col + col_delta[dir];
            if new_row >= 0 && new_row < 8 && new_col >= 0 && new_col < COLS as i32 {
                table[sq][dir] = (new_row * COLS as i32 + new_col) as i8;
            }
            dir += 1;
        }
        sq += 1;
    }
    table
};

const ORTHOGONAL_TABLES: ([[u8; 4]; NUM_SQUARES], [u8; NUM_SQUARES]) = build_orthogonal_table();
pub static ORTHOGONAL: [[u8; 4]; NUM_SQUARES] = ORTHOGONAL_TABLES.0;
pub static ORTHOGONAL_COUNT: [u8; NUM_SQUARES] = ORTHOGONAL_TABLES.1;

/// Material, pyramid advancement and a pharaoh shield.  The default evaluator.
///
/// Both sides are scored in one pass.  This runs at every leaf of the search -
/// about three quarters of all nodes.
#[inline]
pub fn evaluate(board: &GameBoard, color: u8) -> i32 {
    let squares = &board.squares;
    let mut score: i32 = 0;

    for &sq in board.piece_squares[color as usize].as_slice() {
        score += PST[squares[sq as usize] as usize][sq as usize];
    }
    for &sq in board.piece_squares[(color ^ 1) as usize].as_slice() {
        score -= PST[squares[sq as usize] as usize][sq as usize];
    }

    let pharaoh_sq = board.pharaoh_squares[color as usize];
    if pharaoh_sq >= 0 {
        let p = pharaoh_sq as usize;
        for &nb in ORTHOGONAL[p].iter().take(ORTHOGONAL_COUNT[p] as usize) {
            if squares[nb as usize] != 0 {
                score += SHIELD_BONUS;
            }
        }
    }
    let pharaoh_sq = board.pharaoh_squares[(color ^ 1) as usize];
    if pharaoh_sq >= 0 {
        let p = pharaoh_sq as usize;
        for &nb in ORTHOGONAL[p].iter().take(ORTHOGONAL_COUNT[p] as usize) {
            if squares[nb as usize] != 0 {
                score -= SHIELD_BONUS;
            }
        }
    }

    score
}

/// Material only.  Used to adjudicate games on material.
pub fn evaluate_board_simple(board: &GameBoard, color: u8) -> i32 {
    let squares = &board.squares;
    let mut score = 0;
    for &sq in board.piece_squares[color as usize].as_slice() {
        score += VALUE[(squares[sq as usize] >> 3) as usize];
    }
    for &sq in board.piece_squares[(color ^ 1) as usize].as_slice() {
        score -= VALUE[(squares[sq as usize] >> 3) as usize];
    }
    score
}
