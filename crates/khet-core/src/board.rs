//! Khet game board.
//!
//! A direct port of `khet/engine/board.py`.  The board is a flat array of 80
//! piece codes indexed `row * 10 + col`, with row 0 at the top (red's home
//! rank) and column 0 on the left (red's file).  Moves are applied with
//! [`GameBoard::make`] / [`GameBoard::unmake`] rather than by copying.
//!
//! Fidelity notes
//! --------------
//! Two details of the Python implementation are load-bearing for *comparing*
//! the two engines and are reproduced exactly rather than tidied up:
//!
//! * `piece_squares` is an ordered list, not a set.  A move replaces the entry
//!   in place, a capture removes it (shifting the tail down), and an *unmake*
//!   pushes the restored piece onto the **end**.  So the list permutes over the
//!   course of a search.  Since move generation walks it in order, the move
//!   ordering the search sees depends on that permutation - reproducing it is
//!   what makes the two engines' node counts directly comparable.
//! * Move generation emits moves in exactly the Python order: for each piece,
//!   slides in `NEIGHBORS` order, then clockwise rotation, then anticlockwise.

use crate::pieces::{
    can_rotate, encode, opponent, piece_color, piece_type, rotate_code, ABSORB, ANUBIS,
    CODE_RANGE, DESTROY, DOWN, EMPTY, LASER, LEFT, PHARAOH, PYRAMID, RED, RIGHT, SCARAB, SILVER,
    SPHINX, UP,
};

pub const ROWS: usize = 8;
pub const COLS: usize = 10;
pub const NUM_SQUARES: usize = ROWS * COLS;

/// Any beam without a repeated (square, direction) state is at most this long,
/// so exceeding it means the beam is looping between two scarabs.
pub const MAX_LASER_STEPS: usize = NUM_SQUARES * 4;

/// Upper bound on legal moves in any position.
///
/// 13 pieces a side: the pharaoh contributes at most 8 slides and no rotations,
/// the sphinx at most 1 rotation and no slides, and the other 11 pieces at most
/// 8 slides plus 2 rotations.  That is `8 + 11*10 + 1 = 119`.
pub const MAX_MOVES: usize = 128;

#[inline(always)]
pub const fn square(row: usize, col: usize) -> usize {
    row * COLS + col
}

#[inline(always)]
pub const fn row_col(sq: usize) -> (usize, usize) {
    (sq / COLS, sq % COLS)
}

/// Algebraic-ish name of a square, e.g. `a1` for the top-left corner.
pub fn square_name(sq: usize) -> String {
    let (row, col) = row_col(sq);
    format!("{}{}", b"abcdefghij"[col] as char, row + 1)
}

// --------------------------------------------------------------------------
// Precomputed geometry
// --------------------------------------------------------------------------

const fn build_step_table() -> [[i8; 4]; NUM_SQUARES] {
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
            if new_row >= 0 && new_row < ROWS as i32 && new_col >= 0 && new_col < COLS as i32 {
                table[sq][dir] = (new_row * COLS as i32 + new_col) as i8;
            }
            dir += 1;
        }
        sq += 1;
    }
    table
}

/// `STEP[sq][direction]` -> adjacent square, or -1 if off the board.
pub static STEP: [[i8; 4]; NUM_SQUARES] = build_step_table();

/// Padded neighbour lists: up to 8 entries plus a count.
pub struct NeighborTable {
    pub squares: [[u8; 8]; NUM_SQUARES],
    pub counts: [u8; NUM_SQUARES],
}

const fn build_neighbor_table() -> NeighborTable {
    let mut squares = [[0u8; 8]; NUM_SQUARES];
    let mut counts = [0u8; NUM_SQUARES];

    let mut sq = 0usize;
    while sq < NUM_SQUARES {
        let row = (sq / COLS) as i32;
        let col = (sq % COLS) as i32;
        let mut n = 0usize;
        let mut dr = -1i32;
        while dr <= 1 {
            let mut dc = -1i32;
            while dc <= 1 {
                if !(dr == 0 && dc == 0) {
                    let new_row = row + dr;
                    let new_col = col + dc;
                    if new_row >= 0
                        && new_row < ROWS as i32
                        && new_col >= 0
                        && new_col < COLS as i32
                    {
                        squares[sq][n] = (new_row * COLS as i32 + new_col) as u8;
                        n += 1;
                    }
                }
                dc += 1;
            }
            dr += 1;
        }
        counts[sq] = n as u8;
        sq += 1;
    }

    NeighborTable { squares, counts }
}

// `const` rather than `static` because the tables below read it during const
// evaluation, and only `const` items are readable at compile time.
const NEIGHBOR_TABLE: NeighborTable = build_neighbor_table();

/// `NEIGHBORS` -> the up-to-8 adjacent squares, in Python's iteration order
/// (NW, N, NE, W, E, SW, S, SE).
pub static NEIGHBORS: NeighborTable = NEIGHBOR_TABLE;

const fn build_restriction_table() -> [i8; NUM_SQUARES] {
    // Each player owns the file their sphinx sits on, plus the two squares in
    // the corners of the file next to the opponent's.  These stop either
    // player from walling off a corner into an unreachable fortress.
    let mut table = [-1i8; NUM_SQUARES];
    let mut row = 0usize;
    while row < ROWS {
        table[square(row, 0)] = RED as i8;
        table[square(row, COLS - 1)] = SILVER as i8;
        row += 1;
    }
    table[square(0, COLS - 2)] = RED as i8;
    table[square(ROWS - 1, COLS - 2)] = RED as i8;
    table[square(0, 1)] = SILVER as i8;
    table[square(ROWS - 1, 1)] = SILVER as i8;
    table
}

const RESTRICTION_TABLE: [i8; NUM_SQUARES] = build_restriction_table();

/// `RESTRICTED[sq]` -> the only color allowed on that square, else -1.
pub static RESTRICTED: [i8; NUM_SQUARES] = RESTRICTION_TABLE;

const fn build_allowed_neighbor_table(color: i8) -> NeighborTable {
    // Folding the restriction test into the neighbour list at build time
    // removes it from the hottest loop in the engine.  The filtered lists
    // preserve NEIGHBORS order, so the emitted move list is identical.
    let mut squares = [[0u8; 8]; NUM_SQUARES];
    let mut counts = [0u8; NUM_SQUARES];

    // Bound once: referencing a `const` re-materialises its whole value at
    // every use, and this loop would otherwise rebuild both tables ~1300 times
    // during const evaluation.
    let neighbors = NEIGHBOR_TABLE;
    let restricted = RESTRICTION_TABLE;

    let mut sq = 0usize;
    while sq < NUM_SQUARES {
        let total = neighbors.counts[sq] as usize;
        let mut i = 0usize;
        let mut n = 0usize;
        while i < total {
            let nb = neighbors.squares[sq][i];
            let r = restricted[nb as usize];
            if r == -1 || r == color {
                squares[sq][n] = nb;
                n += 1;
            }
            i += 1;
        }
        counts[sq] = n as u8;
        sq += 1;
    }

    NeighborTable { squares, counts }
}

/// `ALLOWED_NEIGHBORS[color]` -> neighbours `color` may legally enter.
pub static ALLOWED_NEIGHBORS: [NeighborTable; 2] = [
    build_allowed_neighbor_table(RED as i8),
    build_allowed_neighbor_table(SILVER as i8),
];

const fn build_code_tables() -> ([bool; CODE_RANGE], [bool; CODE_RANGE], [bool; CODE_RANGE]) {
    let mut can_cw = [false; CODE_RANGE];
    let mut can_ccw = [false; CODE_RANGE];
    let mut swap_target = [false; CODE_RANGE];
    let mut code = 1usize;
    while code < CODE_RANGE {
        can_cw[code] = can_rotate(code as u8, true);
        can_ccw[code] = can_rotate(code as u8, false);
        let t = (code >> 3) as u8;
        swap_target[code] = t == PYRAMID || t == ANUBIS;
        code += 1;
    }
    (can_cw, can_ccw, swap_target)
}

const CODE_TABLES: ([bool; CODE_RANGE], [bool; CODE_RANGE], [bool; CODE_RANGE]) =
    build_code_tables();
pub static CAN_CW: [bool; CODE_RANGE] = CODE_TABLES.0;
pub static CAN_CCW: [bool; CODE_RANGE] = CODE_TABLES.1;
pub static SWAP_TARGET: [bool; CODE_RANGE] = CODE_TABLES.2;

// --------------------------------------------------------------------------
// Zobrist keys
// --------------------------------------------------------------------------
// Generated at compile time with splitmix64 seeded from the same constant the
// Python engine uses.  Deterministic, so transposition-table bugs reproduce.

/// Returns `(value, next_state)`.  Written without `&mut` so that it is a
/// plain `const fn` on every toolchain that can build the rest of this crate.
const fn splitmix64(state: u64) -> (u64, u64) {
    let next = state.wrapping_add(0x9E37_79B9_7F4A_7C15);
    let mut z = next;
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    (z ^ (z >> 31), next)
}

const fn build_zobrist() -> ([[u64; CODE_RANGE]; NUM_SQUARES], u64) {
    let mut state: u64 = 0xC0FFEE;
    let mut table = [[0u64; CODE_RANGE]; NUM_SQUARES];
    let mut sq = 0usize;
    while sq < NUM_SQUARES {
        let mut code = 0usize;
        while code < CODE_RANGE {
            let (value, next) = splitmix64(state);
            table[sq][code] = value;
            state = next;
            code += 1;
        }
        sq += 1;
    }
    let (side, _) = splitmix64(state);
    (table, side)
}

const ZOBRIST_TABLES: ([[u64; CODE_RANGE]; NUM_SQUARES], u64) = build_zobrist();
pub static ZOBRIST: [[u64; CODE_RANGE]; NUM_SQUARES] = ZOBRIST_TABLES.0;
pub static ZOBRIST_SIDE: u64 = ZOBRIST_TABLES.1;

// --------------------------------------------------------------------------
// Move encoding
// --------------------------------------------------------------------------
// A move is one u16: from | to << 7 | kind << 14.

pub const MOVE: u16 = 0;
pub const SWAP: u16 = 1;
pub const ROT_CW: u16 = 2;
pub const ROT_CCW: u16 = 3;

const SWAP_BITS: u16 = SWAP << 14;
const ROT_CW_BITS: u16 = ROT_CW << 14;
const ROT_CCW_BITS: u16 = ROT_CCW << 14;

/// Moves live in `0 .. 1 << 16`, so a flat array indexed by move is a valid
/// stand-in for the Python engine's history dictionary.
pub const MOVE_SPACE: usize = 1 << 16;

#[inline(always)]
pub const fn make_move(from_sq: usize, to_sq: usize, kind: u16) -> u16 {
    (from_sq as u16) | ((to_sq as u16) << 7) | (kind << 14)
}

#[inline(always)]
pub const fn move_from(mv: u16) -> usize {
    (mv & 0x7F) as usize
}

#[inline(always)]
pub const fn move_to(mv: u16) -> usize {
    ((mv >> 7) & 0x7F) as usize
}

#[inline(always)]
pub const fn move_kind(mv: u16) -> u16 {
    mv >> 14
}

/// Readable form of a move, e.g. `c3-d4` or `c3cw`.
pub fn move_name(mv: u16) -> String {
    match move_kind(mv) {
        ROT_CW => format!("{}cw", square_name(move_from(mv))),
        ROT_CCW => format!("{}ccw", square_name(move_from(mv))),
        kind => {
            let joiner = if kind == SWAP { "x" } else { "-" };
            format!(
                "{}{}{}",
                square_name(move_from(mv)),
                joiner,
                square_name(move_to(mv))
            )
        }
    }
}

// --------------------------------------------------------------------------
// Move list
// --------------------------------------------------------------------------

/// A fixed-capacity, stack-allocated move list.
///
/// The Python engine allocates a fresh list at every node; here the list lives
/// in the caller's stack frame, so move generation performs no allocation at
/// all.  This is the one structural change made for the spike, and it is not a
/// semantic one - the contents and their order are identical.
#[derive(Clone, Copy)]
pub struct MoveList {
    pub moves: [u16; MAX_MOVES],
    pub len: usize,
}

impl Default for MoveList {
    fn default() -> Self {
        Self::new()
    }
}

impl MoveList {
    #[inline(always)]
    pub const fn new() -> Self {
        MoveList {
            moves: [0; MAX_MOVES],
            len: 0,
        }
    }

    #[inline(always)]
    pub fn push(&mut self, mv: u16) {
        debug_assert!(self.len < MAX_MOVES, "move list overflow");
        self.moves[self.len] = mv;
        self.len += 1;
    }

    #[inline(always)]
    pub fn as_slice(&self) -> &[u16] {
        &self.moves[..self.len]
    }

    #[inline(always)]
    pub fn as_mut_slice(&mut self) -> &mut [u16] {
        &mut self.moves[..self.len]
    }

    #[inline(always)]
    pub fn is_empty(&self) -> bool {
        self.len == 0
    }

    /// Move the element at `index` to the front, shifting the prefix right.
    /// Mirrors `moves.insert(0, moves.pop(index))`.
    ///
    /// The rotation has to span `..=index`, not `1..=index`: rotating the tail
    /// and then writing the moved element into slot 0 overwrites whatever was
    /// there, which drops one legal move and duplicates another.  That version
    /// shipped briefly and was invisible for four plies, because it only fires
    /// at frontier nodes where every child costs exactly one evaluation - the
    /// *node count* is identical whichever moves are in the list, so only the
    /// scores drift, and only far enough up the tree to matter around depth 5.
    /// `move_to_front_matches_python_list_semantics` pins it directly.
    #[inline]
    pub fn move_to_front(&mut self, index: usize) {
        if index == 0 || index >= self.len {
            return;
        }
        self.moves[..=index].rotate_right(1);
    }

    pub fn position(&self, mv: u16) -> Option<usize> {
        self.as_slice().iter().position(|&m| m == mv)
    }

    pub fn contains(&self, mv: u16) -> bool {
        self.as_slice().contains(&mv)
    }
}

// --------------------------------------------------------------------------
// Piece list
// --------------------------------------------------------------------------

/// Ordered list of the squares one color occupies.
///
/// Deliberately a list rather than a set, and deliberately with Python's exact
/// mutation semantics (see the module docs): replace in place on a move, shift
/// down on a capture, append on restore.
#[derive(Clone, Copy)]
pub struct PieceList {
    squares: [u8; 16],
    len: usize,
}

impl Default for PieceList {
    fn default() -> Self {
        Self::new()
    }
}

impl PieceList {
    pub const fn new() -> Self {
        PieceList {
            squares: [0; 16],
            len: 0,
        }
    }

    #[inline(always)]
    pub fn len(&self) -> usize {
        self.len
    }

    #[inline(always)]
    pub fn is_empty(&self) -> bool {
        self.len == 0
    }

    #[inline(always)]
    pub fn as_slice(&self) -> &[u8] {
        &self.squares[..self.len]
    }

    #[inline(always)]
    pub fn push(&mut self, sq: u8) {
        debug_assert!(self.len < 16);
        self.squares[self.len] = sq;
        self.len += 1;
    }

    /// `list[list.index(old)] = new`
    #[inline(always)]
    pub fn replace(&mut self, old: u8, new: u8) {
        let mut i = 0;
        while i < self.len {
            if self.squares[i] == old {
                self.squares[i] = new;
                return;
            }
            i += 1;
        }
        debug_assert!(false, "square not present in piece list");
    }

    /// `list.remove(sq)` - removes the first occurrence and shifts the tail.
    #[inline(always)]
    pub fn remove(&mut self, sq: u8) {
        let mut i = 0;
        while i < self.len {
            if self.squares[i] == sq {
                let mut j = i;
                while j + 1 < self.len {
                    self.squares[j] = self.squares[j + 1];
                    j += 1;
                }
                self.len -= 1;
                return;
            }
            i += 1;
        }
        debug_assert!(false, "square not present in piece list");
    }
}

// --------------------------------------------------------------------------
// Starting positions
// --------------------------------------------------------------------------
// Entries are (color, piece_type, row, col, orientation), listed in exactly the
// order Python's nested dicts iterate so that `piece_squares` is built up
// identically.
//
// Every official Khet setup is symmetric under a 180 degree rotation of the
// board with the colors exchanged: (row, col) -> (7 - row, 9 - col) and
// orientation -> orientation + 2.

pub type Placement = (u8, u8, usize, usize, u8);

pub static CLASSIC: [Placement; 26] = [
    // red
    (RED, PHARAOH, 0, 5, DOWN),
    (RED, PYRAMID, 1, 2, DOWN),
    (RED, PYRAMID, 0, 7, RIGHT),
    (RED, PYRAMID, 3, 0, UP),
    (RED, PYRAMID, 4, 0, RIGHT),
    (RED, PYRAMID, 3, 7, RIGHT),
    (RED, PYRAMID, 4, 7, UP),
    (RED, PYRAMID, 5, 6, RIGHT),
    (RED, SCARAB, 3, 4, UP),
    (RED, SCARAB, 3, 5, RIGHT),
    (RED, ANUBIS, 0, 4, DOWN),
    (RED, ANUBIS, 0, 6, DOWN),
    (RED, SPHINX, 0, 0, DOWN),
    // silver
    (SILVER, PHARAOH, 7, 4, UP),
    (SILVER, PYRAMID, 6, 7, UP),
    (SILVER, PYRAMID, 7, 2, LEFT),
    (SILVER, PYRAMID, 4, 9, DOWN),
    (SILVER, PYRAMID, 3, 9, LEFT),
    (SILVER, PYRAMID, 4, 2, LEFT),
    (SILVER, PYRAMID, 3, 2, DOWN),
    (SILVER, PYRAMID, 2, 3, LEFT),
    (SILVER, SCARAB, 4, 5, DOWN),
    (SILVER, SCARAB, 4, 4, LEFT),
    (SILVER, ANUBIS, 7, 5, UP),
    (SILVER, ANUBIS, 7, 3, UP),
    (SILVER, SPHINX, 7, 9, UP),
];

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum GameMode {
    /// `imhotep` and `dynasty` are placeholders in the Python engine too - the
    /// printed rules differ but the data does not, so they are aliased
    /// explicitly rather than duplicated as identical tables.
    Classic,
}

/// The undo record returned by [`GameBoard::make`].
#[derive(Clone, Copy)]
pub struct Undo {
    pub mv: u16,
    /// Square of the piece the laser destroyed, or -1.
    pub hit_sq: i8,
    pub captured_code: u8,
}

impl Undo {
    #[inline(always)]
    pub fn captured(&self) -> bool {
        self.hit_sq >= 0
    }
}

#[derive(Clone, Copy)]
pub struct GameBoard {
    pub squares: [u8; NUM_SQUARES],
    pub piece_squares: [PieceList; 2],
    pub sphinx_squares: [i8; 2],
    pub pharaoh_squares: [i8; 2],
    pub side_to_move: u8,
    /// -1 when the game is still running.
    pub winner: i8,
    pub key: u64,
}

impl Default for GameBoard {
    fn default() -> Self {
        Self::new(GameMode::Classic)
    }
}

impl GameBoard {
    pub fn empty() -> Self {
        GameBoard {
            squares: [EMPTY; NUM_SQUARES],
            piece_squares: [PieceList::new(), PieceList::new()],
            sphinx_squares: [-1, -1],
            pharaoh_squares: [-1, -1],
            // Silver moves first in Khet.
            side_to_move: SILVER,
            winner: -1,
            key: 0,
        }
    }

    pub fn new(mode: GameMode) -> Self {
        let mut board = Self::empty();
        match mode {
            GameMode::Classic => {}
        }
        for &(color, ptype, row, col, orient) in CLASSIC.iter() {
            board.add_piece(square(row, col), encode(ptype, color, orient));
        }
        board
    }

    /// Place a piece on an empty square, updating all incremental state.
    pub fn add_piece(&mut self, sq: usize, code: u8) {
        assert!(self.squares[sq] == EMPTY, "square {} is occupied", sq);
        let color = piece_color(code) as usize;
        self.squares[sq] = code;
        self.piece_squares[color].push(sq as u8);
        self.key ^= ZOBRIST[sq][code as usize];
        match piece_type(code) {
            SPHINX => self.sphinx_squares[color] = sq as i8,
            PHARAOH => self.pharaoh_squares[color] = sq as i8,
            _ => {}
        }
    }

    // -- move generation ---------------------------------------------------

    /// All legal moves for the side to move.
    ///
    /// Pharaoh rotations are omitted: a pharaoh has no orientation-dependent
    /// behaviour, so rotating one is a null move that only inflates the
    /// branching factor.
    #[inline]
    pub fn legal_moves(&self) -> MoveList {
        self.legal_moves_for(self.side_to_move)
    }

    pub fn legal_moves_for(&self, color: u8) -> MoveList {
        let mut moves = MoveList::new();
        if self.winner >= 0 {
            return moves;
        }

        let board = &self.squares;
        let allowed = &ALLOWED_NEIGHBORS[color as usize];

        for &from_sq in self.piece_squares[color as usize].as_slice() {
            let from = from_sq as usize;
            let code = board[from];
            let ptype = code >> 3;

            if ptype != SPHINX {
                let count = allowed.counts[from] as usize;
                let row = &allowed.squares[from];
                if ptype == SCARAB {
                    for &to in row.iter().take(count) {
                        let occupant = board[to as usize];
                        if occupant == EMPTY {
                            moves.push(from_sq as u16 | ((to as u16) << 7));
                        } else if SWAP_TARGET[occupant as usize] {
                            // A swap moves the occupant backwards onto from_sq,
                            // so that square has to be legal for the occupant's
                            // color too.  Otherwise a scarab standing on its own
                            // reserved square could park an enemy piece
                            // somewhere it is not allowed to be.
                            let back = RESTRICTED[from];
                            if back == -1 || back == ((occupant >> 2) & 1) as i8 {
                                moves.push(from_sq as u16 | ((to as u16) << 7) | SWAP_BITS);
                            }
                        }
                    }
                } else {
                    for &to in row.iter().take(count) {
                        if board[to as usize] == EMPTY {
                            moves.push(from_sq as u16 | ((to as u16) << 7));
                        }
                    }
                }
            }

            if ptype != PHARAOH {
                let rotation = from_sq as u16 | ((from_sq as u16) << 7);
                if CAN_CW[code as usize] {
                    moves.push(rotation | ROT_CW_BITS);
                }
                if CAN_CCW[code as usize] {
                    moves.push(rotation | ROT_CCW_BITS);
                }
            }
        }

        moves
    }

    /// Whether `mv` appears in the legal move list.  For UI validation.
    pub fn is_legal(&self, mv: u16) -> bool {
        self.legal_moves().contains(mv)
    }

    // -- make / unmake -----------------------------------------------------

    /// Apply `mv`, fire the mover's laser, and switch sides.
    pub fn make(&mut self, mv: u16) -> Undo {
        let color = self.side_to_move as usize;
        let from_sq = (mv & 0x7F) as usize;
        let to_sq = ((mv >> 7) & 0x7F) as usize;
        let kind = mv >> 14;

        if kind == MOVE {
            let code = self.squares[from_sq];
            self.squares[from_sq] = EMPTY;
            self.squares[to_sq] = code;
            self.key ^= ZOBRIST[from_sq][code as usize] ^ ZOBRIST[to_sq][code as usize];
            self.piece_squares[color].replace(from_sq as u8, to_sq as u8);
            if (code >> 3) == PHARAOH {
                self.pharaoh_squares[color] = to_sq as i8;
            }
        } else if kind == SWAP {
            let mover = self.squares[from_sq];
            let occupant = self.squares[to_sq];
            self.squares[from_sq] = occupant;
            self.squares[to_sq] = mover;
            self.key ^= ZOBRIST[from_sq][mover as usize]
                ^ ZOBRIST[to_sq][mover as usize]
                ^ ZOBRIST[from_sq][occupant as usize]
                ^ ZOBRIST[to_sq][occupant as usize];
            self.piece_squares[color].replace(from_sq as u8, to_sq as u8);
            let other = ((occupant >> 2) & 1) as usize;
            self.piece_squares[other].replace(to_sq as u8, from_sq as u8);
            // A scarab may only swap with a pyramid or anubis, so neither the
            // pharaoh nor the sphinx caches can be affected here.
        } else {
            let code = self.squares[from_sq];
            let new_code = rotate_code(code, kind == ROT_CW);
            self.squares[from_sq] = new_code;
            self.key ^= ZOBRIST[from_sq][code as usize] ^ ZOBRIST[from_sq][new_code as usize];
        }

        let hit_sq = self.fire_laser(color as u8);

        let mut captured_code = EMPTY;
        if hit_sq >= 0 {
            captured_code = self.squares[hit_sq as usize];
            self.remove_piece(hit_sq as usize);
            if (captured_code >> 3) == PHARAOH {
                self.winner = (((captured_code >> 2) & 1) ^ 1) as i8;
            }
        }

        self.side_to_move = (color as u8) ^ 1;
        self.key ^= ZOBRIST_SIDE;
        Undo {
            mv,
            hit_sq,
            captured_code,
        }
    }

    /// Undo a move produced by [`GameBoard::make`].
    pub fn unmake(&mut self, undo: Undo) {
        let mv = undo.mv;
        let from_sq = (mv & 0x7F) as usize;
        let to_sq = ((mv >> 7) & 0x7F) as usize;
        let kind = mv >> 14;

        self.key ^= ZOBRIST_SIDE;
        let color = (self.side_to_move ^ 1) as usize;
        self.side_to_move = color as u8;

        if undo.hit_sq >= 0 {
            let hit = undo.hit_sq as usize;
            let captured_color = ((undo.captured_code >> 2) & 1) as usize;
            self.squares[hit] = undo.captured_code;
            // Python appends here rather than restoring the original index.
            // Reproduced on purpose - see the module docs.
            self.piece_squares[captured_color].push(hit as u8);
            self.key ^= ZOBRIST[hit][undo.captured_code as usize];
            if (undo.captured_code >> 3) == PHARAOH {
                self.pharaoh_squares[captured_color] = hit as i8;
                self.winner = -1;
            }
        }

        if kind == MOVE {
            let code = self.squares[to_sq];
            self.squares[to_sq] = EMPTY;
            self.squares[from_sq] = code;
            self.key ^= ZOBRIST[from_sq][code as usize] ^ ZOBRIST[to_sq][code as usize];
            self.piece_squares[color].replace(to_sq as u8, from_sq as u8);
            if (code >> 3) == PHARAOH {
                self.pharaoh_squares[color] = from_sq as i8;
            }
        } else if kind == SWAP {
            let mover = self.squares[to_sq];
            let occupant = self.squares[from_sq];
            self.squares[from_sq] = mover;
            self.squares[to_sq] = occupant;
            self.key ^= ZOBRIST[from_sq][mover as usize]
                ^ ZOBRIST[to_sq][mover as usize]
                ^ ZOBRIST[from_sq][occupant as usize]
                ^ ZOBRIST[to_sq][occupant as usize];
            self.piece_squares[color].replace(to_sq as u8, from_sq as u8);
            let other = ((occupant >> 2) & 1) as usize;
            self.piece_squares[other].replace(from_sq as u8, to_sq as u8);
        } else {
            let code = self.squares[from_sq];
            // Rotating back is the opposite direction from the one applied.
            let old_code = rotate_code(code, kind == ROT_CCW);
            self.squares[from_sq] = old_code;
            self.key ^= ZOBRIST[from_sq][code as usize] ^ ZOBRIST[from_sq][old_code as usize];
        }
    }

    /// Pass the turn without moving a piece or firing the laser.
    ///
    /// Only for null-move pruning in the search; it is not a legal Khet move.
    /// Khet weakens the null-move assumption more than chess does, because
    /// moving *forces* you to fire and a forced shot can destroy your own
    /// piece - so positions where every move costs you something are genuine
    /// zugzwang and this will misjudge exactly those.
    #[inline]
    pub fn make_null(&mut self) {
        self.side_to_move = opponent(self.side_to_move);
        self.key ^= ZOBRIST_SIDE;
    }

    #[inline]
    pub fn unmake_null(&mut self) {
        self.side_to_move = opponent(self.side_to_move);
        self.key ^= ZOBRIST_SIDE;
    }

    fn remove_piece(&mut self, sq: usize) {
        let code = self.squares[sq];
        let color = ((code >> 2) & 1) as usize;
        self.squares[sq] = EMPTY;
        self.piece_squares[color].remove(sq as u8);
        self.key ^= ZOBRIST[sq][code as usize];
        if (code >> 3) == PHARAOH {
            self.pharaoh_squares[color] = -1;
        }
    }

    // -- laser -------------------------------------------------------------

    /// Walk the beam from `color`'s sphinx.
    ///
    /// Returns the square of the piece destroyed, or -1 if the beam left the
    /// board, was absorbed, or entered a loop.
    #[inline]
    pub fn fire_laser(&self, color: u8) -> i8 {
        let board = &self.squares;
        let start = self.sphinx_squares[color as usize] as usize;
        let mut direction = (board[start] & 3) as usize;
        let mut sq = STEP[start][direction];

        // Two facing scarabs can trap a beam forever.  The bound is exact: a
        // path longer than the number of (square, direction) states must
        // revisit one, and the beam is deterministic, so it is a cycle.
        for _ in 0..MAX_LASER_STEPS {
            if sq < 0 {
                return -1;
            }
            let s = sq as usize;
            let code = board[s];
            if code != EMPTY {
                let outcome = LASER[code as usize][direction];
                if outcome == DESTROY {
                    return sq;
                }
                if outcome == ABSORB {
                    return -1;
                }
                direction = outcome as usize;
            }
            sq = STEP[s][direction];
        }
        -1
    }

    /// One laser walk returning `(target, destroys, path_len)`.
    ///
    /// `target` is where the beam ends, or -1 if it leaves the board or loops.
    /// `destroys` says whether the piece there would be removed, as opposed to
    /// absorbing the beam harmlessly like a sphinx or a head-on anubis.
    pub fn beam_scan(&self, color: u8) -> (i8, bool, Vec<u8>) {
        let board = &self.squares;
        let start = self.sphinx_squares[color as usize] as usize;
        let mut direction = (board[start] & 3) as usize;
        let mut path = vec![start as u8];
        let mut sq = STEP[start][direction];

        for _ in 0..MAX_LASER_STEPS {
            if sq < 0 {
                return (-1, false, path);
            }
            let s = sq as usize;
            path.push(sq as u8);
            let code = board[s];
            if code != EMPTY {
                let outcome = LASER[code as usize][direction];
                if outcome == DESTROY {
                    return (sq, true, path);
                }
                if outcome == ABSORB {
                    return (sq, false, path);
                }
                direction = outcome as usize;
            }
            sq = STEP[s][direction];
        }
        (-1, false, path)
    }

    /// The beam's route as `(square, incoming_direction)` pairs.  For the UI.
    pub fn laser_path(&self, color: u8) -> Vec<(u8, u8)> {
        let board = &self.squares;
        let start = self.sphinx_squares[color as usize] as usize;
        let mut direction = (board[start] & 3) as usize;
        let mut sq = STEP[start][direction];
        let mut path = Vec::new();

        for _ in 0..MAX_LASER_STEPS {
            if sq < 0 {
                break;
            }
            let s = sq as usize;
            path.push((sq as u8, direction as u8));
            let code = board[s];
            if code != EMPTY {
                let outcome = LASER[code as usize][direction];
                if outcome == DESTROY || outcome == ABSORB {
                    break;
                }
                direction = outcome as usize;
            }
            sq = STEP[s][direction];
        }
        path
    }

    // -- status ------------------------------------------------------------

    #[inline(always)]
    pub fn is_game_over(&self) -> bool {
        self.winner >= 0
    }

    /// Number of pieces `color` still has on the board.
    #[inline(always)]
    pub fn material(&self, color: u8) -> usize {
        self.piece_squares[color as usize].len()
    }
}

impl std::fmt::Display for GameBoard {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let glyphs = [' ', '^', 'S', 'A', 'P', 'X'];
        writeln!(f, "   a b c d e f g h i j")?;
        for row in 0..ROWS {
            write!(f, "{:2} ", row + 1)?;
            for col in 0..COLS {
                let code = self.squares[square(row, col)];
                if code == EMPTY {
                    write!(f, ".")?;
                } else {
                    let glyph = glyphs[piece_type(code) as usize];
                    if piece_color(code) == SILVER {
                        write!(f, "{}", glyph.to_ascii_lowercase())?;
                    } else {
                        write!(f, "{}", glyph)?;
                    }
                }
                if col + 1 < COLS {
                    write!(f, " ")?;
                }
            }
            writeln!(f)?;
        }
        write!(f, "{} to move", crate::pieces::COLOR_NAMES[self.side_to_move as usize])?;
        if self.winner >= 0 {
            write!(
                f,
                "  ({} wins)",
                crate::pieces::COLOR_NAMES[self.winner as usize]
            )?;
        }
        Ok(())
    }
}
