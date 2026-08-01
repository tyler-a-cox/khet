//! Python bindings for the Khet engine.
//!
//! The surface is shaped to match `khet.engine.board` / `khet.engine.tree_search`
//! from the Python original, so the browser UI and any scripts written against
//! those modules port with an import change rather than a rewrite.
//!
//! Two deliberate departures from the Python API, both places where mirroring
//! it exactly would have been worse:
//!
//! * The undo record is an opaque [`Undo`] object with named attributes rather
//!   than a `(move, hit_sq, captured_code)` tuple. It still unpacks, so
//!   existing `_, hit_sq, captured = undo` code keeps working.
//! * [`GameBoard::beam_after`] is a real method. The Python server had to
//!   reach into `board.squares`, write the captured piece back, walk the beam
//!   and undo the write, because `make` fires the laser before returning. That
//!   is now one call that borrows the board immutably.
//!
//! GIL handling: [`Searcher::search`] releases the GIL for the duration of the
//! search. The UI server is threaded and a person's `/api/state` poll must not
//! block behind someone else's two-second search.

use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyModule, PyTuple};

use khet_core::board as cb;
use khet_core::eval as ce;
use khet_core::pieces as cp;
use khet_core::search as cs;

// --------------------------------------------------------------------------
// Undo record
// --------------------------------------------------------------------------

/// What [`GameBoard::make`] returns and [`GameBoard::unmake`] consumes.
#[pyclass(module = "khet._engine")]
#[derive(Clone, Copy)]
pub struct Undo {
    inner: cb::Undo,
}

#[pymethods]
impl Undo {
    #[getter]
    fn r#move(&self) -> u16 {
        self.inner.mv
    }

    /// Square of the piece the laser destroyed, or -1.
    #[getter]
    fn hit_sq(&self) -> i8 {
        self.inner.hit_sq
    }

    #[getter]
    fn captured_code(&self) -> u8 {
        self.inner.captured_code
    }

    #[getter]
    fn captured(&self) -> bool {
        self.inner.hit_sq >= 0
    }

    /// Unpacks as `(move, hit_sq, captured_code)`, matching the Python engine's
    /// tuple so code written against it keeps working.
    fn __iter__(slf: PyRef<'_, Self>, py: Python<'_>) -> PyResult<PyObject> {
        let tuple = PyTuple::new_bound(
            py,
            [
                slf.inner.mv.into_py(py),
                slf.inner.hit_sq.into_py(py),
                slf.inner.captured_code.into_py(py),
            ],
        );
        // `as_any().iter()` rather than `tuple.iter()`: the latter is PyO3's
        // typed inherent iterator, which is a Rust value, not a Python object.
        Ok(tuple.as_any().iter()?.into_py(py))
    }

    fn __repr__(&self) -> String {
        format!(
            "<Undo {} hit={} captured={}>",
            cb::move_name(self.inner.mv),
            self.inner.hit_sq,
            self.inner.captured_code
        )
    }
}

// --------------------------------------------------------------------------
// Board
// --------------------------------------------------------------------------

#[pyclass(module = "khet._engine")]
#[derive(Clone)]
pub struct GameBoard {
    pub(crate) inner: cb::GameBoard,
}

#[pymethods]
impl GameBoard {
    #[new]
    #[pyo3(signature = (game_mode = "classic"))]
    fn new(game_mode: &str) -> PyResult<Self> {
        match game_mode {
            // `imhotep` and `dynasty` are aliases in the Python engine too:
            // the printed rules differ but the setup data never did.
            "classic" | "imhotep" | "dynasty" => Ok(GameBoard {
                inner: cb::GameBoard::new(cb::GameMode::Classic),
            }),
            other => Err(PyValueError::new_err(format!(
                "Invalid game mode: {:?}",
                other
            ))),
        }
    }

    #[getter]
    fn squares(&self) -> Vec<u8> {
        self.inner.squares.to_vec()
    }

    #[getter]
    fn side_to_move(&self) -> u8 {
        self.inner.side_to_move
    }

    /// `None` while the game is running, matching the Python engine.
    #[getter]
    fn winner(&self) -> Option<u8> {
        if self.inner.winner < 0 {
            None
        } else {
            Some(self.inner.winner as u8)
        }
    }

    #[getter]
    fn key(&self) -> u64 {
        self.inner.key
    }

    #[getter]
    fn sphinx_squares(&self) -> Vec<i8> {
        self.inner.sphinx_squares.to_vec()
    }

    #[getter]
    fn pharaoh_squares(&self) -> Vec<i8> {
        self.inner.pharaoh_squares.to_vec()
    }

    #[getter]
    fn piece_squares(&self) -> (Vec<u8>, Vec<u8>) {
        (
            self.inner.piece_squares[0].as_slice().to_vec(),
            self.inner.piece_squares[1].as_slice().to_vec(),
        )
    }

    #[pyo3(signature = (color = None))]
    fn legal_moves(&self, color: Option<u8>) -> Vec<u16> {
        let color = color.unwrap_or(self.inner.side_to_move);
        self.inner.legal_moves_for(color).as_slice().to_vec()
    }

    #[pyo3(signature = (mv, color = None))]
    fn is_legal(&self, mv: u16, color: Option<u8>) -> bool {
        let color = color.unwrap_or(self.inner.side_to_move);
        self.inner.legal_moves_for(color).contains(mv)
    }

    fn make(&mut self, mv: u16) -> Undo {
        Undo {
            inner: self.inner.make(mv),
        }
    }

    fn unmake(&mut self, undo: &Undo) {
        self.inner.unmake(undo.inner);
    }

    fn make_null(&mut self) {
        self.inner.make_null();
    }

    fn unmake_null(&mut self) {
        self.inner.unmake_null();
    }

    #[pyo3(signature = (color = None))]
    fn laser_path(&self, color: Option<u8>) -> Vec<(u8, u8)> {
        let color = color.unwrap_or(self.inner.side_to_move);
        self.inner.laser_path(color)
    }

    /// The route the beam took on the move that has just been made.
    ///
    /// `make` fires the laser and removes whatever it destroyed before
    /// returning, so a plain `laser_path` afterwards walks a board the shot has
    /// already changed - the beam carries on through the now-empty square and
    /// draws a route that was never fired. Pass the `hit_sq` and
    /// `captured_code` from the undo record and the piece is put back for the
    /// length of one read-only walk.
    fn beam_after(&self, color: u8, hit_sq: i8, captured_code: u8) -> Vec<(u8, u8)> {
        if hit_sq < 0 {
            return self.inner.laser_path(color);
        }
        // A local copy, so the caller's board is untouched even transiently -
        // the Python version mutated and restored, which is not safe to do
        // while another thread might be reading the same board.
        let mut snapshot = self.inner;
        snapshot.squares[hit_sq as usize] = captured_code;
        snapshot.laser_path(color)
    }

    fn is_game_over(&self) -> bool {
        self.inner.is_game_over()
    }

    fn material(&self, color: u8) -> usize {
        self.inner.material(color)
    }

    fn clone(&self) -> Self {
        GameBoard { inner: self.inner }
    }

    fn __copy__(&self) -> Self {
        self.clone()
    }

    #[pyo3(signature = (_memo = None))]
    fn __deepcopy__(&self, _memo: Option<PyObject>) -> Self {
        self.clone()
    }

    fn __str__(&self) -> String {
        format!("{}", self.inner)
    }

    fn __repr__(&self) -> String {
        format!(
            "<GameBoard {} to move{}>",
            cp::COLOR_NAMES[self.inner.side_to_move as usize],
            if self.inner.winner >= 0 {
                format!(", {} wins", cp::COLOR_NAMES[self.inner.winner as usize])
            } else {
                String::new()
            }
        )
    }
}

// --------------------------------------------------------------------------
// Search result
// --------------------------------------------------------------------------

#[pyclass(module = "khet._engine")]
pub struct SearchResult {
    inner: cs::SearchResult,
}

#[pymethods]
impl SearchResult {
    #[getter]
    fn r#move(&self) -> Option<u16> {
        self.inner.mv
    }
    #[getter]
    fn score(&self) -> i32 {
        self.inner.score
    }
    #[getter]
    fn depth(&self) -> i32 {
        self.inner.depth
    }
    #[getter]
    fn nodes(&self) -> u64 {
        self.inner.nodes
    }
    #[getter]
    fn elapsed(&self) -> f64 {
        self.inner.elapsed
    }
    #[getter]
    fn principal_variation(&self) -> Vec<u16> {
        self.inner.principal_variation.clone()
    }
    /// `(move, score)` per root move, best first.  Drives tie-breaking and
    /// temperature sampling in the bot.
    #[getter]
    fn root_moves(&self) -> Vec<(u16, i32)> {
        self.inner.root_moves.clone()
    }
    #[getter]
    fn nodes_per_second(&self) -> f64 {
        self.inner.nodes_per_second()
    }

    fn __repr__(&self) -> String {
        let pv: Vec<String> = self
            .inner
            .principal_variation
            .iter()
            .map(|&m| cb::move_name(m))
            .collect();
        format!(
            "<SearchResult depth={} score={} nodes={} {:.2}s ({:.0} n/s) pv={}>",
            self.inner.depth,
            self.inner.score,
            self.inner.nodes,
            self.inner.elapsed,
            self.inner.nodes_per_second(),
            pv.join(" ")
        )
    }
}

// --------------------------------------------------------------------------
// Searcher
// --------------------------------------------------------------------------

// Not `unsendable`: `ThreadingHTTPServer` hands consecutive requests for the
// same game to different worker threads, and an unsendable pyclass raises the
// moment it is touched from a thread other than the one that built it.  Every
// field is plain data, so the searcher is genuinely `Send`.
#[pyclass(module = "khet._engine")]
pub struct Searcher {
    inner: cs::Searcher<cs::BasicEval>,
}

#[pymethods]
impl Searcher {
    /// `reference=True` runs plain alpha-beta with no null windows and no
    /// reductions. It is about 12x slower at depth 7 and exists so tests can
    /// compare against a search that makes no bets about the move ordering.
    #[new]
    #[pyo3(signature = (reference = false, max_table_size = 1 << 20))]
    fn new(reference: bool, max_table_size: usize) -> Self {
        let mode = if reference {
            cs::Mode::Reference
        } else {
            cs::Mode::Pruned
        };
        let mut inner = cs::Searcher::new(cs::BasicEval, mode);
        inner.max_table_size = max_table_size;
        Searcher { inner }
    }

    #[getter]
    fn reference(&self) -> bool {
        self.inner.mode == cs::Mode::Reference
    }

    /// Search `board` for the side to move.
    ///
    /// The GIL is released for the duration: the UI server is threaded, and one
    /// person's search must not stall everyone else's requests.
    #[pyo3(signature = (board, max_depth = 4, time_limit = None))]
    fn search(
        &mut self,
        py: Python<'_>,
        board: &Bound<'_, GameBoard>,
        max_depth: i32,
        time_limit: Option<f64>,
    ) -> PyResult<SearchResult> {
        // Copy the position out, search without the GIL, then write it back.
        // `GameBoard` is 136 bytes of plain data, so the copy is far cheaper
        // than holding a borrow of a Python object across the search - and it
        // means a concurrent reader of the same board sees a consistent
        // position rather than one mid-make.
        let mut position = board
            .try_borrow()
            .map_err(|_| PyRuntimeError::new_err("board is already borrowed"))?
            .inner;

        let searcher = &mut self.inner;
        let result = py.allow_threads(move || searcher.search(&mut position, max_depth, time_limit));

        board
            .try_borrow_mut()
            .map_err(|_| PyRuntimeError::new_err("board is already borrowed"))?
            .inner = position;
        Ok(SearchResult { inner: result })
    }

    #[getter]
    fn nodes(&self) -> u64 {
        self.inner.nodes
    }

    #[getter]
    fn re_searches(&self) -> u64 {
        self.inner.re_searches
    }

    /// Drop the transposition table.  Rarely wanted - it is the thing that
    /// makes reusing a searcher across the moves of a game worthwhile.
    fn clear_table(&mut self) {
        self.inner.table.clear();
    }

    #[getter]
    fn table_size(&self) -> usize {
        self.inner.table.len()
    }
}

// --------------------------------------------------------------------------
// Module-level functions
// --------------------------------------------------------------------------

#[pyfunction]
fn make_move(from_sq: usize, to_sq: usize, kind: u16) -> u16 {
    cb::make_move(from_sq, to_sq, kind)
}

#[pyfunction]
fn move_from(mv: u16) -> usize {
    cb::move_from(mv)
}

#[pyfunction]
fn move_to(mv: u16) -> usize {
    cb::move_to(mv)
}

#[pyfunction]
fn move_kind(mv: u16) -> u16 {
    cb::move_kind(mv)
}

#[pyfunction]
fn move_name(mv: u16) -> String {
    cb::move_name(mv)
}

#[pyfunction]
fn square(row: usize, col: usize) -> usize {
    cb::square(row, col)
}

#[pyfunction]
fn row_col(sq: usize) -> (usize, usize) {
    cb::row_col(sq)
}

#[pyfunction]
fn square_name(sq: usize) -> String {
    cb::square_name(sq)
}

#[pyfunction]
fn opponent(color: u8) -> u8 {
    cp::opponent(color)
}

#[pyfunction]
fn piece_type(code: u8) -> u8 {
    cp::piece_type(code)
}

#[pyfunction]
fn piece_color(code: u8) -> u8 {
    cp::piece_color(code)
}

#[pyfunction]
fn orientation(code: u8) -> u8 {
    cp::orientation(code)
}

#[pyfunction]
fn encode(piece_type: u8, color: u8, orientation: u8) -> u8 {
    cp::encode(piece_type, color, orientation)
}

#[pyfunction]
fn describe(code: u8) -> String {
    cp::describe(code)
}

/// Static evaluation from `color`'s point of view.  Positive is good for them.
#[pyfunction]
fn evaluate(board: &GameBoard, color: u8) -> i32 {
    ce::evaluate(&board.inner, color)
}

#[pyfunction]
fn evaluate_board_simple(board: &GameBoard, color: u8) -> i32 {
    ce::evaluate_board_simple(&board.inner, color)
}

/// Count leaf nodes at `depth`.  Move generation plus make/unmake, no search.
#[pyfunction]
fn perft(py: Python<'_>, board: &GameBoard, depth: u32) -> u64 {
    let mut position = board.inner;
    py.allow_threads(move || khet_core::perft(&mut position, depth))
}

// --------------------------------------------------------------------------
// Module
// --------------------------------------------------------------------------

#[pymodule]
fn _engine(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<GameBoard>()?;
    m.add_class::<Undo>()?;
    m.add_class::<SearchResult>()?;
    m.add_class::<Searcher>()?;

    m.add_function(wrap_pyfunction!(make_move, m)?)?;
    m.add_function(wrap_pyfunction!(move_from, m)?)?;
    m.add_function(wrap_pyfunction!(move_to, m)?)?;
    m.add_function(wrap_pyfunction!(move_kind, m)?)?;
    m.add_function(wrap_pyfunction!(move_name, m)?)?;
    m.add_function(wrap_pyfunction!(square, m)?)?;
    m.add_function(wrap_pyfunction!(row_col, m)?)?;
    m.add_function(wrap_pyfunction!(square_name, m)?)?;
    m.add_function(wrap_pyfunction!(opponent, m)?)?;
    m.add_function(wrap_pyfunction!(piece_type, m)?)?;
    m.add_function(wrap_pyfunction!(piece_color, m)?)?;
    m.add_function(wrap_pyfunction!(orientation, m)?)?;
    m.add_function(wrap_pyfunction!(encode, m)?)?;
    m.add_function(wrap_pyfunction!(describe, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate_board_simple, m)?)?;
    m.add_function(wrap_pyfunction!(perft, m)?)?;

    // Geometry
    m.add("ROWS", cb::ROWS)?;
    m.add("COLS", cb::COLS)?;
    m.add("NUM_SQUARES", cb::NUM_SQUARES)?;
    m.add("RESTRICTED", cb::RESTRICTED.to_vec())?;

    // Move kinds
    m.add("MOVE", cb::MOVE)?;
    m.add("SWAP", cb::SWAP)?;
    m.add("ROT_CW", cb::ROT_CW)?;
    m.add("ROT_CCW", cb::ROT_CCW)?;

    // Directions
    m.add("UP", cp::UP)?;
    m.add("RIGHT", cp::RIGHT)?;
    m.add("DOWN", cp::DOWN)?;
    m.add("LEFT", cp::LEFT)?;
    m.add("DIR_NAMES", cp::DIR_NAMES.to_vec())?;

    // Colors
    m.add("RED", cp::RED)?;
    m.add("SILVER", cp::SILVER)?;
    m.add("COLOR_NAMES", cp::COLOR_NAMES.to_vec())?;

    // Piece types
    m.add("EMPTY", cp::EMPTY)?;
    m.add("PYRAMID", cp::PYRAMID)?;
    m.add("SCARAB", cp::SCARAB)?;
    m.add("ANUBIS", cp::ANUBIS)?;
    m.add("PHARAOH", cp::PHARAOH)?;
    m.add("SPHINX", cp::SPHINX)?;
    m.add("TYPE_NAMES", cp::TYPE_NAMES.to_vec())?;

    // Search score scale
    m.add("MATE", cs::MATE)?;
    m.add("INFINITY", cs::INFINITY)?;
    m.add("MATE_THRESHOLD", cs::MATE_THRESHOLD)?;

    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
