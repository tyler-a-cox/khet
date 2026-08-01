//! Alpha-beta search over Khet positions.
//!
//! Iterative-deepening negamax with a transposition table, killer moves and
//! history ordering, plus one combined technique: every move after the first is
//! searched with a null window, and moves late in the ordering are searched
//! with the depth reduced as well. A search that comes back better than
//! expected is redone properly.
//!
//! What is deliberately not here
//! -----------------------------
//! Four techniques were implemented, measured and removed. The numbers are
//! recorded because "we tried it and it did not pay" is the useful part, and
//! without it someone re-adds them:
//!
//! * **Aspiration windows** - narrow the root window around the previous
//!   iteration's score. Worth about 5% of nodes here, which did not justify the
//!   widen-and-retry loop it needs.
//! * **Null-move pruning** - about 36% fewer nodes at depth 4 with no
//!   measurable accuracy loss, but only engaging from depth 4 up. Cut mostly
//!   because Khet is a poor fit for the assumption it rests on: moving *forces*
//!   you to fire, so a position where every legal move costs you something is
//!   real zugzwang, and this misjudges exactly those.
//! * **Capture extensions** - hold depth constant when a move destroys a piece.
//!   About 18x the nodes at depth 3, because in Khet every move fires a laser
//!   and so "extend on capture" triggers constantly rather than occasionally.
//!   It was there to label training positions more accurately; if a training
//!   pipeline comes back, it comes back with it.
//! * **PVS and LMR as separate switches.** They were never separable: the
//!   reduced search is performed *against* the null window, so turning PVS off
//!   silently disabled LMR too. Measured with PVS off, enabling LMR changed the
//!   node count by exactly zero. They are one technique and are now written as
//!   one.
//!
//! Together those techniques are worth roughly 12x at depth 7 (2.3M nodes
//! against 28.6M for plain alpha-beta), which is why [`Mode::Reference`] is
//! kept: it runs the plain version so a test can diff against a search with no
//! bets in it at all.

use std::collections::HashMap;
use std::hash::{BuildHasherDefault, Hasher};
use std::sync::OnceLock;
use std::time::Instant;

use crate::board::{GameBoard, MoveList, MAX_MOVES, MOVE_SPACE};
use crate::eval;

/// Score of a win at ply 0.  Comfortably above any static evaluation.
pub const MATE: i32 = 1_000_000;
pub const INFINITY: i32 = 2_000_000;
/// Scores beyond this are mate scores rather than heuristic ones.
pub const MATE_THRESHOLD: i32 = MATE - 10_000;

pub const EXACT: u8 = 0;
pub const LOWER_BOUND: u8 = 1;
pub const UPPER_BOUND: u8 = 2;

const MAX_PLY: usize = 128;

// --------------------------------------------------------------------------
// Transposition table
// --------------------------------------------------------------------------
// Zobrist keys are already uniformly mixed, so hashing them again is pure
// overhead.  This pass-through hasher is also what Python does implicitly:
// `hash(int) == int` for keys in this range.

#[derive(Default)]
pub struct IdentityHasher(u64);

impl Hasher for IdentityHasher {
    #[inline(always)]
    fn finish(&self) -> u64 {
        self.0
    }
    #[inline(always)]
    fn write(&mut self, bytes: &[u8]) {
        for &b in bytes {
            self.0 = self.0.rotate_left(8) ^ b as u64;
        }
    }
    #[inline(always)]
    fn write_u64(&mut self, value: u64) {
        self.0 = value;
    }
}

pub type IdentityBuild = BuildHasherDefault<IdentityHasher>;

#[derive(Clone, Copy)]
pub struct TtEntry {
    pub depth: i32,
    pub score: i32,
    pub flag: u8,
    pub mv: u16,
}

// --------------------------------------------------------------------------
// Late move reduction table
// --------------------------------------------------------------------------

const RED_DEPTHS: usize = 64;
const RED_MOVES: usize = 128;

/// `REDUCTIONS[depth][move_index]` -> plies to shave off.
///
/// The usual logarithmic shape: reduce more as the search gets deeper and as a
/// move sits further down the ordering, but never enough to skip a move
/// outright, since a reduced search that beats alpha gets re-searched.
fn reductions() -> &'static [[i8; RED_MOVES]; RED_DEPTHS] {
    static TABLE: OnceLock<Box<[[i8; RED_MOVES]; RED_DEPTHS]>> = OnceLock::new();
    TABLE.get_or_init(|| {
        let mut table = Box::new([[0i8; RED_MOVES]; RED_DEPTHS]);
        for depth in 0..RED_DEPTHS {
            for index in 0..RED_MOVES {
                if depth < 3 || index < 3 {
                    continue;
                }
                let raw = 0.5 + (depth as f64).ln() * (index as f64).ln() / 2.6;
                // Python's `int()` truncates toward zero; `as i32` matches.
                let clamped = (raw as i32).min(depth as i32 - 2).max(0);
                table[depth][index] = clamped as i8;
            }
        }
        table
    })
}

// --------------------------------------------------------------------------
// Mode
// --------------------------------------------------------------------------

/// Depth below which a move is never reduced, and position in the move list
/// before which a move is never reduced. The first three moves at any node are
/// the ones the ordering is most confident about, so they get searched properly.
const LMR_MIN_DEPTH: i32 = 3;
const LMR_MIN_MOVE: usize = 3;

/// Which search to run.
///
/// There is one search for playing. [`Mode::Reference`] exists so that a test
/// can compare against a search containing no bets at all: null windows and
/// reductions are both wagers on the move ordering being good, and when
/// something looks wrong the first question is always whether the ordering is
/// the thing that broke. It is roughly 12x slower at depth 7 and is not
/// intended for play.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub enum Mode {
    /// Null windows and late move reductions. What the engine plays with.
    #[default]
    Pruned,
    /// Plain alpha-beta. Every move searched at full depth with a full window.
    Reference,
}

// --------------------------------------------------------------------------
// Evaluator
// --------------------------------------------------------------------------

/// Pluggable static evaluation.
///
/// A trait rather than a function pointer so that the default evaluator
/// monomorphises and inlines into the leaf; an indirect call at every leaf is a
/// measurable fraction of a search this cheap.
pub trait Evaluator {
    fn evaluate(&self, board: &GameBoard, color: u8) -> i32;
}

/// Material, pyramid advancement and a pharaoh shield.
#[derive(Clone, Copy, Default)]
pub struct BasicEval;

impl Evaluator for BasicEval {
    #[inline(always)]
    fn evaluate(&self, board: &GameBoard, color: u8) -> i32 {
        eval::evaluate(board, color)
    }
}

// --------------------------------------------------------------------------
// Result
// --------------------------------------------------------------------------

pub struct SearchResult {
    pub mv: Option<u16>,
    pub score: i32,
    pub depth: i32,
    pub nodes: u64,
    pub elapsed: f64,
    pub principal_variation: Vec<u16>,
    /// `(move, score)` for every root move, best first.  Needed to sample a
    /// move rather than always taking the best one, which is what keeps
    /// self-play games from being carbon copies of each other.
    pub root_moves: Vec<(u16, i32)>,
}

impl SearchResult {
    pub fn nodes_per_second(&self) -> f64 {
        if self.elapsed > 0.0 {
            self.nodes as f64 / self.elapsed
        } else {
            0.0
        }
    }
}

// --------------------------------------------------------------------------
// Mate score bookkeeping
// --------------------------------------------------------------------------
// Mate scores are "distance from the root", but the transposition table is
// keyed on the position, which can turn up at a different ply in another
// branch.  Storing distance-from-here and converting back on probe keeps
// "mate in 3" from becoming "mate in 5" two plies deeper.

#[inline(always)]
fn mate_score_to_table(score: i32, ply: usize) -> i32 {
    if score > MATE_THRESHOLD {
        score + ply as i32
    } else if score < -MATE_THRESHOLD {
        score - ply as i32
    } else {
        score
    }
}

#[inline(always)]
fn mate_score_from_table(score: i32, ply: usize) -> i32 {
    if score > MATE_THRESHOLD {
        score - ply as i32
    } else if score < -MATE_THRESHOLD {
        score + ply as i32
    } else {
        score
    }
}

/// How often the clock is read while a time limit is active.  Retuned during
/// the search rather than fixed, because the right interval depends entirely
/// on what a node costs, and that varies by orders of magnitude between a
/// hand-written evaluation and a network one.
const CHECK_TARGET_SECONDS: f64 = 0.002;
const CHECK_MASK_MAX: u64 = 1023;

// --------------------------------------------------------------------------
// Searcher
// --------------------------------------------------------------------------

/// Iterative-deepening negamax with alpha-beta pruning.
///
/// Reusing one instance across the moves of a game is worthwhile: the
/// transposition table and history table stay warm.
pub struct Searcher<E: Evaluator = BasicEval> {
    pub evaluator: E,
    pub mode: Mode,
    pub max_table_size: usize,
    pub table: HashMap<u64, TtEntry, IdentityBuild>,
    /// Flat array standing in for Python's history dict; moves are < 2^16, so
    /// `history[mv]` and `history.get(mv, 0)` agree by construction.
    history: Vec<i32>,
    killers: Vec<[u16; 2]>,
    pub nodes: u64,
    pub re_searches: u64,
    start: Instant,
    deadline: Option<f64>,
    aborted: bool,
    check_mask: u64,
    check_nodes: u64,
    check_time: f64,
}

impl Default for Searcher<BasicEval> {
    fn default() -> Self {
        Self::basic()
    }
}

impl Searcher<BasicEval> {
    /// The searcher the engine plays with: material evaluation, pruned search.
    pub fn basic() -> Self {
        Self::new(BasicEval, Mode::Pruned)
    }

    /// Plain alpha-beta, for tests that need a search with no bets in it.
    pub fn reference() -> Self {
        Self::new(BasicEval, Mode::Reference)
    }
}

impl<E: Evaluator> Searcher<E> {
    pub fn new(evaluator: E, mode: Mode) -> Self {
        Searcher {
            evaluator,
            mode,
            max_table_size: 1 << 20,
            table: HashMap::with_hasher(IdentityBuild::default()),
            history: vec![0; MOVE_SPACE],
            killers: vec![[0, 0]; MAX_PLY],
            nodes: 0,
            re_searches: 0,
            start: Instant::now(),
            deadline: None,
            // Start at "check every node" and let the search widen it.
            // Starting wide and narrowing would spend the first interval
            // blind, which for an expensive evaluator is most of the budget.
            aborted: false,
            check_mask: 0,
            check_nodes: 0,
            check_time: 0.0,
        }
    }

    #[inline(always)]
    fn now(&self) -> f64 {
        self.start.elapsed().as_secs_f64()
    }

    // -- public API --------------------------------------------------------

    /// Search `board` for the side to move.
    ///
    /// Deepens one ply at a time so that a time limit always leaves a usable
    /// move from the last completed depth, and so that each iteration's best
    /// move can order the next one.
    pub fn search(
        &mut self,
        board: &mut GameBoard,
        max_depth: i32,
        time_limit: Option<f64>,
    ) -> SearchResult {
        self.start = Instant::now();
        self.deadline = time_limit;
        self.aborted = false;
        self.nodes = 0;
        self.re_searches = 0;
        self.check_mask = 0;
        self.check_nodes = 0;
        self.check_time = 0.0;
        self.history.iter_mut().for_each(|h| *h = 0);

        let mut best_move: Option<u16> = None;
        let mut best_score: i32 = 0;
        let mut completed_depth: i32 = 0;
        let mut principal_variation: Vec<u16> = Vec::new();
        let mut root_moves: Vec<(u16, i32)> = Vec::new();

        if board.legal_moves().is_empty() {
            return SearchResult {
                mv: None,
                score: 0,
                depth: 0,
                nodes: 0,
                elapsed: 0.0,
                principal_variation: Vec::new(),
                root_moves: Vec::new(),
            };
        }

        for depth in 1..=max_depth {
            self.killers.iter_mut().for_each(|k| *k = [0, 0]);
            let (score, mv, ordered) = self.search_root(
                board,
                depth,
                best_move.unwrap_or(0),
                -INFINITY,
                INFINITY,
            );

            // An aborted iteration is incomplete, so its best move is not
            // trustworthy; fall back on the last depth that finished.
            if self.aborted {
                break;
            }

            best_move = Some(mv);
            best_score = score;
            completed_depth = depth;
            root_moves = ordered;
            principal_variation = self.collect_pv(board, depth as usize, mv);

            // A forced mate has been proved; deeper search cannot improve.
            if best_score.abs() > MATE_THRESHOLD {
                break;
            }
        }

        SearchResult {
            mv: best_move,
            score: best_score,
            depth: completed_depth,
            nodes: self.nodes,
            elapsed: self.now(),
            principal_variation,
            root_moves,
        }
    }

    // -- root --------------------------------------------------------------

    fn search_root(
        &mut self,
        board: &mut GameBoard,
        depth: i32,
        previous_best: u16,
        mut alpha: i32,
        beta: i32,
    ) -> (i32, u16, Vec<(u16, i32)>) {
        let mut moves = board.legal_moves();
        self.order(&mut moves, previous_best, 0, depth);
        if moves.is_empty() {
            return (0, 0, Vec::new());
        }

        let mut best_move = moves.moves[0];
        let mut best_score = -INFINITY;
        let mut scored: Vec<(u16, i32)> = Vec::with_capacity(moves.len);

        for index in 0..moves.len {
            let mv = moves.moves[index];
            let undo = board.make(mv);

            let mut score;
            if index == 0 || self.mode == Mode::Reference {
                score = -self.negamax(board, depth - 1, -beta, -alpha, 1);
            } else {
                // Null window first: most root moves only need refuting.
                score = -self.negamax(board, depth - 1, -alpha - 1, -alpha, 1);
                if score == alpha {
                    // A fail-low null-window result is an upper *bound*, and
                    // when that bound lands exactly on alpha the move looks
                    // tied with the best move even though its true score may
                    // be far lower.  `root_moves` feeds tie-breaking and
                    // sampling in the bot, so scores at the top have to be
                    // exact.  Verify with the null window shifted one point
                    // down: this search proving >= alpha, combined with the
                    // first proving <= alpha, pins the score to exactly alpha,
                    // and a genuinely worse move fails low against the
                    // narrowest possible window and drops out of the tie set.
                    //
                    // Verification runs on every iteration on purpose: the
                    // shallow verify searches seed the transposition table
                    // that makes the deep ones nearly free.
                    self.re_searches += 1;
                    let verified = -self.negamax(board, depth - 1, -alpha, 1 - alpha, 1);
                    if verified < alpha {
                        score = verified;
                    } else if verified > alpha {
                        // The two bounds disagree (search instability, e.g.
                        // LMR inside the subtrees).  Settle it properly.
                        self.re_searches += 1;
                        score = -self.negamax(board, depth - 1, -beta, -alpha, 1);
                    }
                } else if alpha < score && score < beta {
                    self.re_searches += 1;
                    score = -self.negamax(board, depth - 1, -beta, -alpha, 1);
                }
            }
            board.unmake(undo);

            if self.aborted {
                break;
            }
            scored.push((mv, score));
            if score > best_score {
                best_score = score;
                best_move = mv;
            }
            if score > alpha {
                alpha = score;
            }
        }

        // Stable descending sort, matching Python's `sort(key=..., reverse=True)`.
        scored.sort_by(|a, b| b.1.cmp(&a.1));
        (best_score, best_move, scored)
    }

    // -- time control ------------------------------------------------------

    /// Re-aim the clock-read interval at `CHECK_TARGET_SECONDS`.
    ///
    /// Measures what a node has actually been costing since the last read and
    /// picks the largest power-of-two-minus-one mask that keeps the next read
    /// inside the target window.  One reading is enough to converge.
    fn retune_check_interval(&mut self, now: f64) {
        let counted = self.nodes - self.check_nodes;
        let elapsed = now - self.check_time;
        self.check_nodes = self.nodes;
        self.check_time = now;
        if counted == 0 || elapsed <= 0.0 {
            // Below the clock's resolution.  Leave the mask alone and measure
            // again over a longer stretch rather than dividing by ~zero.
            return;
        }
        let wanted = CHECK_TARGET_SECONDS * counted as f64 / elapsed;
        let mut mask: u64 = 0;
        while mask < CHECK_MASK_MAX && ((mask << 1 | 1) as f64) < wanted {
            mask = mask << 1 | 1;
        }
        self.check_mask = mask;
    }

    // -- search core -------------------------------------------------------

    /// Value of `board` from the side to move's point of view.
    ///
    /// Fail-soft: the returned value may lie outside `[alpha, beta]`, in which
    /// case it is a bound rather than the exact score.  The bound type is what
    /// gets recorded in the transposition table.
    fn negamax(
        &mut self,
        board: &mut GameBoard,
        depth: i32,
        mut alpha: i32,
        mut beta: i32,
        ply: usize,
    ) -> i32 {
        self.nodes += 1;
        if self.deadline.is_some() && (self.nodes & self.check_mask) == 0 {
            let now = self.now();
            if now > self.deadline.unwrap() {
                self.aborted = true;
            } else {
                self.retune_check_interval(now);
            }
        }
        if self.aborted {
            return 0;
        }

        // Terminal first: a decided game is worth a mate score, never a
        // heuristic one, and the margin has to shrink with distance so that
        // faster wins and slower losses are preferred.
        if board.winner >= 0 {
            return if board.winner == board.side_to_move as i8 {
                MATE - ply as i32
            } else {
                -MATE + ply as i32
            };
        }

        if depth <= 0 {
            return self.evaluator.evaluate(board, board.side_to_move);
        }

        let mut table_move: u16 = 0;
        if let Some(entry) = self.table.get(&board.key).copied() {
            table_move = entry.mv;
            if entry.depth >= depth {
                let score = mate_score_from_table(entry.score, ply);
                if entry.flag == EXACT {
                    return score;
                }
                if entry.flag == LOWER_BOUND && score > alpha {
                    alpha = score;
                } else if entry.flag == UPPER_BOUND && score < beta {
                    beta = score;
                }
                if alpha >= beta {
                    return score;
                }
            }
        }

        // Snapshot *after* the table probe.  The probe can raise alpha, and the
        // bound flag stored at the end must describe the window the moves were
        // actually searched with: a best score at or below the raised alpha is
        // an upper bound, and snapshotting first mislabelled it EXACT.
        let original_alpha = alpha;
        let is_pv = beta - alpha > 1;

        let mut moves = board.legal_moves();
        self.order(&mut moves, table_move, ply, depth);
        if moves.is_empty() {
            return self.evaluator.evaluate(board, board.side_to_move);
        }

        let mut best_score = -INFINITY;
        let mut best_move = moves.moves[0];
        // Reductions are only sound where the ordering is trustworthy and the
        // window is narrow: inside a principal variation an under-searched move
        // that is actually good would go unnoticed.
        let may_reduce = depth >= LMR_MIN_DEPTH && !is_pv;
        let reduction_table = reductions();

        for index in 0..moves.len {
            let mv = moves.moves[index];
            let undo = board.make(mv);

            let score;
            if index == 0 || self.mode == Mode::Reference {
                // The first move is the one the ordering believes in, so it
                // gets a real window and the full depth.
                score = -self.negamax(board, depth - 1, -beta, -alpha, ply + 1);
            } else {
                // Everything after it only has to answer "is this better than
                // what we already have?", which a null window settles far
                // cheaper than a real search - and a move far down the ordering
                // can answer it from a shallower depth as well.  A move that
                // destroyed a piece is never reduced: in Khet that is the
                // position the evaluation is least able to judge.
                let mut reduction = 0i32;
                if may_reduce && index >= LMR_MIN_MOVE && !undo.captured() {
                    reduction = reduction_table[depth.min(63) as usize][index.min(127)] as i32;
                }

                let mut s =
                    -self.negamax(board, depth - 1 - reduction, -alpha - 1, -alpha, ply + 1);
                // Either bet coming back better than expected means it was not
                // trustworthy, so pay for the real answer.
                if s > alpha && (reduction != 0 || is_pv) {
                    self.re_searches += 1;
                    s = -self.negamax(board, depth - 1, -beta, -alpha, ply + 1);
                }
                score = s;
            }

            board.unmake(undo);

            if self.aborted {
                return best_score;
            }
            if score > best_score {
                best_score = score;
                best_move = mv;
            }
            if score > alpha {
                alpha = score;
            }
            if alpha >= beta {
                // Beta cutoff.  Remember this move: the same refutation tends
                // to work in sibling positions at the same ply.
                self.record_cutoff(mv, depth, ply);
                break;
            }
        }

        self.store(board.key, depth, best_score, original_alpha, beta, best_move, ply);
        best_score
    }

    // -- move ordering -----------------------------------------------------

    /// Order moves best-first: transposition-table move, killers, then history.
    ///
    /// At frontier nodes each child costs a single evaluation, so a full sort
    /// of ~60 moves is comparable in cost to the work it saves.  There, only
    /// the table move is hoisted.
    ///
    /// This ordering is already close to optimal: measured over depths 1-5 the
    /// effective branching factor is about 9.0 against a theoretical alpha-beta
    /// floor of sqrt(79) = 8.9, which is why laser-aware ordering on top
    /// measured exactly neutral in the Python engine and was removed.
    fn order(&self, moves: &mut MoveList, preferred: u16, ply: usize, depth: i32) {
        if moves.len < 2 {
            return;
        }

        if depth <= 1 {
            if preferred != 0 {
                if let Some(index) = moves.position(preferred) {
                    moves.move_to_front(index);
                }
            }
            return;
        }

        let killers = if ply < self.killers.len() {
            self.killers[ply]
        } else {
            [0, 0]
        };

        // (score, original index).  Sorting by score descending with the index
        // as tie-breaker reproduces Python's stable `sort(reverse=True)`
        // exactly, without the allocation a stable sort would need here.
        let mut keyed = [(0i32, 0u16); MAX_MOVES];
        for index in 0..moves.len {
            let mv = moves.moves[index];
            let score = if mv == preferred {
                1 << 30
            } else if mv == killers[0] {
                1 << 29
            } else if mv == killers[1] {
                1 << 28
            } else {
                self.history[mv as usize]
            };
            keyed[index] = (score, index as u16);
        }
        keyed[..moves.len].sort_unstable_by(|a, b| b.0.cmp(&a.0).then(a.1.cmp(&b.1)));

        let original = moves.moves;
        for index in 0..moves.len {
            moves.moves[index] = original[keyed[index].1 as usize];
        }
    }

    fn record_cutoff(&mut self, mv: u16, depth: i32, ply: usize) {
        if ply < self.killers.len() {
            let killers = &mut self.killers[ply];
            if killers[0] != mv {
                killers[1] = killers[0];
                killers[0] = mv;
            }
        }
        // Deeper cutoffs are stronger evidence, hence the depth weighting.
        // Saturating rather than wrapping: Python's ints are unbounded, and the
        // only way to reach i32::MAX here is a search far longer than any this
        // engine runs, but silently wrapping into negative history would be a
        // real ordering bug.
        let slot = &mut self.history[mv as usize];
        *slot = slot.saturating_add(depth * depth);
    }

    // -- transposition table ----------------------------------------------

    #[allow(clippy::too_many_arguments)]
    fn store(
        &mut self,
        key: u64,
        depth: i32,
        score: i32,
        alpha: i32,
        beta: i32,
        mv: u16,
        ply: usize,
    ) {
        let flag = if score <= alpha {
            UPPER_BOUND
        } else if score >= beta {
            LOWER_BOUND
        } else {
            EXACT
        };

        let existing = self.table.get(&key);
        if let Some(entry) = existing {
            if entry.depth > depth {
                return;
            }
        } else if self.table.len() >= self.max_table_size {
            self.table.clear();
        }

        self.table.insert(
            key,
            TtEntry {
                depth,
                score: mate_score_to_table(score, ply),
                flag,
                mv,
            },
        );
    }

    /// Walk the transposition table to recover the principal variation.
    ///
    /// Two deliberate departures from the Python engine, both fixing the same
    /// bug from opposite ends:
    ///
    /// **The first move is always `root_move`, not a table probe.**
    /// `search_root` never writes to the transposition table, so a walk that
    /// starts by probing the root position usually finds nothing and returns an
    /// empty PV. Worse is the case where it *does* find something: the entry
    /// belongs to some unrelated deeper context that transposed back to the
    /// opening, so the reported line starts with a move the engine is not going
    /// to play. That is not hypothetical - at depth 5 the Python engine reports
    /// `f5xg6 c2-c3 ...` while playing `h7-h6`. The root move is known to the
    /// caller, and it is the authoritative answer.
    ///
    /// **The walk runs on a copy.** The Python version makes and unmakes moves
    /// on the live board, and `unmake` restores a captured piece to the *end*
    /// of `piece_squares` rather than its original slot. Move generation walks
    /// that list in order, so a diagnostic readout was quietly permuting the
    /// move ordering the next iteration would see. Searching a copy costs one
    /// 136-byte memcpy per iteration and removes the coupling entirely.
    ///
    /// Together these shift depth-6 node counts by about 0.13% against the
    /// Python engine (703,652 -> 702,712) and leave depths 1-5 identical. That
    /// is the price of the fix and it is recorded in `tests/reference/`.
    fn collect_pv(&self, board: &GameBoard, max_length: usize, root_move: u16) -> Vec<u16> {
        let mut position = *board;
        let mut pv = Vec::new();
        let mut seen = std::collections::HashSet::new();

        for _ in 0..max_length {
            let mv = if pv.is_empty() {
                root_move
            } else {
                match self.table.get(&position.key) {
                    Some(entry) => entry.mv,
                    None => break,
                }
            };
            if !seen.insert(position.key) {
                break;
            }
            if mv == 0 || !position.legal_moves().contains(mv) {
                break;
            }
            pv.push(mv);
            position.make(mv);
            if position.winner >= 0 {
                break;
            }
        }
        pv
    }
}

/// Convenience wrapper: search once and return the [`SearchResult`].
///
/// Builds a fresh searcher, so it throws away the transposition table each
/// call. Fine for one-off analysis; use a long-lived [`Searcher`] to play a
/// game, where keeping the table warm between moves is most of the benefit.
pub fn find_best_move(
    board: &mut GameBoard,
    depth: i32,
    time_limit: Option<f64>,
) -> SearchResult {
    Searcher::basic().search(board, depth, time_limit)
}
