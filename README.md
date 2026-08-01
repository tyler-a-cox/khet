# khet

[Khet](https://en.wikipedia.org/wiki/Khet_(game)) (laser chess): a Rust engine
with a Python front end.

Rust holds the board, move generation, laser resolution, evaluation and the
alpha-beta search. Python holds the browser UI, the bot's move-selection policy
and the command line — the parts that run once per move rather than once per
node, where the language costs nothing and the ergonomics are worth keeping.

It is a port of [khet_python](https://github.com/tyler-a-cox/khet_python), which remains the
reference implementation: the two engines are held to identical node counts by a
recorded fixture. Against PyPy this one is roughly 25× faster, and about 14M
perft nodes/s and 5M search nodes/s in absolute terms.

## The game

Khet is played on an 8×10 board. Each side has 13 pieces:

| piece | count | behaviour |
|:--|--:|:--|
| **Sphinx** | 1 | Fires the laser. Cannot move; has only two legal facings. Immune to every beam, including its own. |
| **Pyramid** | 7 | A single mirror. Reflects a beam striking either of its two mirrored faces, and is destroyed by a beam striking either of the other two. |
| **Scarab** | 2 | A double-sided mirror. Reflects from all four directions and can never be destroyed. May swap places with an adjacent pyramid or anubis of either colour. |
| **Anubis** | 2 | Armoured on one face. Absorbs a beam striking that face, destroyed from any other. |
| **Pharaoh** | 1 | Destroyed by a beam from any direction, which ends the game. |

A turn is: move one piece one square in any of the eight directions, **or**
rotate it 90°, and then fire your own laser. Never both, and the shot is not
optional.

That last part is what makes Khet unlike chess. There is no quiet move — every
single turn ends in a beam crossing the board, which can just as easily destroy
your own piece as your opponent's. A player who moves a pyramid out of the way
may find their own laser now reaches their own pharaoh. Losing that way counts
as a loss.

Each colour also owns some **restricted squares** — their own file plus two
squares beside the opponent's — that the other colour may not enter. Silver
moves first.

## Installing and playing

Needs a Rust toolchain (1.75 or newer):

```
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"
```

Then:

```
pip install maturin
maturin develop --release
```

```
khet play                          # opens a browser game against the engine
khet play --color red --time-limit 5
khet selfplay --depth 6            # watch the engine play itself
khet strength --games 10           # the search against a random mover
khet bench                         # perft and search timings
```

`maturin develop` builds the extension and installs the package into the active
environment. `maturin build --release` produces a wheel you can install
elsewhere; it has no Python dependencies at all.

`khet play` starts a small local server and opens a browser. Click one of
your pieces, then a highlighted square to move it; hollow rings mark scarab
swaps. The curved arrows rotate the selected piece, as do <kbd>Q</kbd> and
<kbd>E</kbd>. <kbd>Esc</kbd> deselects. The board scales to fit a phone, so
`--host 0.0.0.0` plus a tunnel is enough to hand someone a game on their
mobile.

Useful flags for `play`: `--color`, `--time-limit` (seconds the bot may think),
`--max-depth`, `--port` (`0` picks a free one), `--host`, `--no-browser`.

> If `cargo` is not found after installing Rust: a conda or mambaforge base
> environment usually prepends its own PATH *after* rustup's line in your shell
> profile, which hides `~/.cargo/bin`.

## Modules

### Engine — `crates/khet-core/`

No dependencies at all, so it builds offline in a couple of seconds. Every
lookup table is built by a `const fn` and materialised at compile time, which
keeps the derivations readable in code rather than pasted in as magic numbers.

**`src/pieces.rs`** — Piece encoding and the laser rules. A piece is a 6-bit
integer packing type, colour and orientation. The laser interaction table
(`LASER[code][direction]` → new direction, destroyed, or absorbed) and the
rotation-legality tables are derived from the rules at compile time.

**`src/board.rs`** — The position and everything that mutates it. 80 piece codes
in a flat array, board geometry and Zobrist keys computed at compile time, moves
packed into a `u16`, and `make`/`unmake` so the search never copies a board.
`MoveList` is a fixed-size stack array, so move generation allocates nothing.
Also laser resolution: `fire_laser` for the search, `laser_path` and
`beam_after` for the UI.

**`src/eval.rs`** — What a position is worth, from one colour's point of view.
Material, pyramid advancement toward the far rank, and a bonus for friendly
pieces orthogonally adjacent to your own pharaoh, all folded into piece-square
tables. Scarabs and sphinxes score zero because they cannot be destroyed; the
pharaoh scores zero because losing it is terminal and the search handles that
with a mate score.

**`src/search.rs`** — The search. Iterative-deepening negamax with alpha-beta, a
transposition table, killer moves and history ordering. Every move after the
first is searched with a null window, and moves late in the ordering are
searched with the depth reduced as well; anything that comes back better than
expected is re-searched properly. `Mode::Reference` runs plain alpha-beta
instead — no null windows, no reductions — which the tests use to check the
pruned search against something with no bets in it. The evaluator is a trait, so
a different one monomorphises into the leaf rather than costing an indirect call
per node.

**`src/bin/bench.rs`** — `cargo run --release --bin bench`. Perft and
fixed-depth search timings, with `--json` for `benchmarks/compare.py`.

### Bindings — `crates/khet-py/`

PyO3, exposing the engine as `khet._engine`. `GameBoard`, `Undo`,
`Searcher`, `SearchResult`, plus the move helpers and constants. The names match
the Python engine's, so code written against that ports with an import change.

`Searcher.search()` releases the GIL for the duration, and the class is not
`unsendable`, both because the UI server is threaded and hands consecutive
requests for one game to different worker threads.

### Front end — `python/khet/`

**`bot.py`** — Move selection. `AlphaBetaPlayer` wraps the searcher and decides
what to actually play: best move, a random pick among moves tied for best, or a
softmax sample over the root scores when `temperature` is set. `RandomPlayer` is
a baseline opponent.

**`ui/server.py`** — A threaded HTTP server on the standard library only. Each
browser gets its own game, keyed by an opaque cookie, so the URL can be shared
without two people fighting over one board. Every response carries the whole
game state rather than a delta, which means the page can always re-render from
scratch.

**`ui/static/index.html`** — The page: a single file, no build step, no
dependencies. Draws the board as SVG, scales to fit a phone, and animates the
beam after each move.

**`cli.py`** — The `khet` command. `play`, `selfplay`, `strength`, `bench`.
argparse rather than Click, so the installed wheel has no Python dependencies.

### Benchmarks and fixtures — `benchmarks/`, `tests/`

**`compare.py`** — Runs both engines back to back and reports the ratio. It
refuses to print a speedup unless they agree on node counts, scores and best
moves at every depth.

```
python3 benchmarks/compare.py --python pypy3
```

**`verify_tables.py`** — Cross-checks every derived table — laser outcomes,
piece-square values, reductions, the starting position and its ordering —
against the Python engine. Needs no Rust toolchain, so it runs before the first
build.

**`record_reference.py`** — Regenerates `tests/reference/python_engine.json`,
the fixture the parity tests assert against. Re-run it after changing the Python
engine.

```
cargo test                            # engine, ~7s
pytest                                # parity fixture, HTTP server, UI layout
python3 benchmarks/verify_tables.py
```

## Not ported

Self-play generation lives in the Python repo and can drive this engine through
the same bindings the UI uses. A learned evaluation would go in `src/eval.rs`
behind the existing `Evaluator` trait.

## License

MIT
