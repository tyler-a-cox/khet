"""A small HTTP server that lets a person play the engine in a browser.

Ported from the Python engine's ``khet/ui/server.py``. The board and the search
now live in Rust; everything here is unchanged in shape, and the JSON contract
the page consumes is byte-for-byte the same, so ``static/index.html`` came over
untouched.

Design notes
------------
A :class:`GameSession` owns one ``GameBoard`` and one ``AlphaBetaPlayer``.
Every request returns the *whole* game state rather than a delta, so the page
can be re-rendered from scratch and there is no client-side model to drift out
of sync with the board.

Only the standard library is used, so ``khet play`` works in a bare
checkout once the extension is built.

One game per browser
--------------------
Sessions live in a :class:`SessionStore` keyed by an opaque cookie rather than
in a single module-level slot, because the server is reachable by more than the
person who started it - over a tunnel, two people opening the URL would
otherwise share one board and take each other's turns. The store holds a
bounded number of games and evicts the least recently used, so an open URL
cannot accumulate sessions without limit.

Locking is per session, not global: a bot search holds its own game's lock for
the length of the search, and one person thinking must not stall the other's
requests. The store's own lock is only ever held for a dictionary lookup.

This is also why the Rust ``Searcher`` releases the GIL and is not marked
``unsendable``: ``ThreadingHTTPServer`` hands consecutive requests for one game
to different worker threads, and a search that held the GIL would serialise
every other browser behind it.

Why the beam is reconstructed
-----------------------------
``GameBoard.make`` fires the laser and removes whatever it destroyed before
returning, so calling ``laser_path`` afterwards walks a board the shot has
already changed - the beam would carry on through the empty square and draw a
route that was never fired. ``GameBoard.beam_after`` replays the walk against a
copy with the captured piece put back. In the Python original this was a helper
here that mutated ``board.squares`` and restored it in a ``finally``; on the
Rust side it is a method that takes no mutable borrow at all, which matters now
that another thread really can be reading the same board.
"""

import collections
import http.cookies
import json
import mimetypes
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from khet import (
    COLOR_NAMES,
    COLS,
    MATE_THRESHOLD,
    NAME_TO_COLOR,
    RESTRICTED,
    ROWS,
    SILVER,
    GameBoard,
    move_from,
    move_kind,
    move_name,
    move_to,
    opponent,
)
from khet.bot import AlphaBetaPlayer

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

#: Name of the cookie that ties a browser to its game.
COOKIE_NAME = "khet_session"

#: How many games to keep before evicting the least recently used.  Each one
#: holds a board, a history and the searcher's transposition table.
MAX_SESSIONS = 16

#: Ceiling on the per-move clock a client may ask for.  ``/api/new`` takes its
#: settings from the request body, so without this anyone with the URL could
#: ask for an hour-long search and pin the CPU.
MAX_TIME_LIMIT = 30.0


class GameSession:
    """One game between a person and the search."""

    def __init__(self, human_color=SILVER, mode="classic", time_limit=2.0,
                 max_depth=32):
        if isinstance(human_color, str):
            human_color = NAME_TO_COLOR[human_color]
        self.human_color = human_color
        self.mode = mode
        self.time_limit = time_limit
        self.max_depth = max_depth

        self.board = GameBoard(mode)
        self.bot = AlphaBetaPlayer(
            opponent(human_color),
            depth=max_depth,
            time_limit=time_limit,
        )
        #: ``(undo_record, description)`` per ply, so a move can be taken back.
        self.history = []
        self.last = None

    # -- play --------------------------------------------------------------

    def apply(self, move, by_bot=False):
        """Make ``move`` and record everything the UI needs to show it."""
        color = self.board.side_to_move
        undo = self.board.make(move)

        self.last = {
            "move": move,
            "from": move_from(move),
            "to": move_to(move),
            "kind": move_kind(move),
            "name": move_name(move),
            "color": color,
            "by_bot": by_bot,
            "beam": [
                {"square": sq, "direction": direction}
                for sq, direction in self.board.beam_after(
                    color, undo.hit_sq, undo.captured_code
                )
            ],
            "captured": None if undo.hit_sq < 0 else {
                "square": undo.hit_sq,
                "code": undo.captured_code,
            },
        }
        self.history.append((undo, dict(self.last)))

    def play_human(self, move):
        if self.board.winner is not None:
            raise ValueError("the game is over")
        if self.board.side_to_move != self.human_color:
            raise ValueError("it is not your turn")
        if move not in self.board.legal_moves(self.human_color):
            raise ValueError("illegal move: {}".format(move_name(move)))
        self.apply(move)

    def play_bot(self):
        """Search and play one bot move.  Returns the search result, or None."""
        if self.board.winner is not None:
            return None
        if self.board.side_to_move == self.human_color:
            return None
        move = self.bot.get_move(self.board)
        if move is None:
            return None
        self.apply(move, by_bot=True)
        return self.bot.last_result

    def undo(self):
        """Take back moves until it is the person's turn again.

        Undoing one ply would hand the position straight back to the bot, which
        would just play again; the useful unit is "my move and its reply".
        """
        if not self.history:
            return
        while self.history:
            undo, _ = self.history.pop()
            self.board.unmake(undo)
            if self.board.side_to_move == self.human_color:
                break
        self.last = self.history[-1][1] if self.history else None

    # -- serialisation -----------------------------------------------------

    def state(self):
        board = self.board
        legal = []
        if board.winner is None and board.side_to_move == self.human_color:
            legal = [
                {
                    "move": move,
                    "from": move_from(move),
                    "to": move_to(move),
                    "kind": move_kind(move),
                }
                for move in board.legal_moves(self.human_color)
            ]

        result = self.bot.last_result
        thinking = None
        if result is not None and result.move is not None:
            # The bot breaks ties at random, so the move it played is not
            # always the one the principal variation was built around. When
            # they differ the PV describes a line that never happened, which
            # is worse than showing nothing - so show nothing.
            played = self.last["move"] if self.last and self.last["by_bot"] else None
            variation = list(result.principal_variation)
            if played is not None and (not variation or variation[0] != played):
                variation = []
            thinking = {
                "score": result.score,
                "depth": result.depth,
                "nodes": result.nodes,
                "elapsed": round(result.elapsed, 2),
                "mate": abs(result.score) > MATE_THRESHOLD,
                "pv": [move_name(m) for m in variation],
            }

        return {
            "rows": ROWS,
            "cols": COLS,
            "squares": list(board.squares),
            "restricted": list(RESTRICTED),
            "sphinxes": list(board.sphinx_squares),
            "side_to_move": board.side_to_move,
            "human_color": self.human_color,
            "bot_color": opponent(self.human_color),
            "winner": board.winner,
            "your_turn": board.winner is None
            and board.side_to_move == self.human_color,
            "legal_moves": legal,
            "last": self.last,
            "moves": [entry["name"] for _, entry in self.history],
            "thinking": thinking,
            "time_limit": self.time_limit,
            "can_undo": any(
                entry["color"] == self.human_color for _, entry in self.history
            ),
            "color_names": list(COLOR_NAMES),
        }


class SessionStore:
    """The live games, one per browser, keyed by an opaque cookie.

    ``defaults`` are the settings a game gets when a browser arrives without a
    session of its own; :meth:`replace` is what ``/api/new`` calls, and it
    overrides them per game rather than for the server.
    """

    def __init__(self, defaults=None, max_sessions=MAX_SESSIONS):
        self.defaults = dict(defaults or {})
        self.max_sessions = max_sessions
        #: key -> (session, lock), in least-recently-used-first order.
        self._games = collections.OrderedDict()
        self._lock = threading.Lock()

    def _make(self, **overrides):
        settings = dict(self.defaults)
        settings.update(overrides)
        if "time_limit" in settings:
            settings["time_limit"] = min(
                float(settings["time_limit"]), MAX_TIME_LIMIT
            )
        return GameSession(**settings)

    def _evict(self):
        while len(self._games) > self.max_sessions:
            self._games.popitem(last=False)

    def acquire(self, key):
        """The game for ``key``, creating one if the cookie is new or stale.

        Returns ``(key, session, lock)``; the key differs from the one passed
        in when a new game had to be minted, and the caller is expected to set
        the cookie in that case.  The returned lock is *not* held - the caller
        takes it around the mutation so the store's lock is never held across a
        search.
        """
        with self._lock:
            entry = self._games.get(key) if key else None
            if entry is None:
                key = secrets.token_urlsafe(16)
                entry = (self._make(), threading.Lock())
                self._games[key] = entry
                self._evict()
            else:
                self._games.move_to_end(key)
            session, lock = entry
        return key, session, lock

    def replace(self, key, **overrides):
        """Start a fresh game under an existing key.  Returns the new session."""
        with self._lock:
            session = self._make(**overrides)
            self._games[key] = (session, threading.Lock())
            self._games.move_to_end(key)
            self._evict()
        return session

    def __len__(self):
        with self._lock:
            return len(self._games)


class _Handler(BaseHTTPRequestHandler):
    """Routes.  ``store`` is set on the class by :func:`serve`."""

    store = None
    server_version = "khet-ui"
    #: Set per request by :meth:`_session`.
    _session_key = None

    def log_message(self, fmt, *args):  # noqa: A003 - silence per-request noise
        pass

    # -- helpers -----------------------------------------------------------

    def _send_json(self, payload, status=200, set_cookie=None):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if set_cookie is not None:
            # HttpOnly because the page never reads it, SameSite=Lax because
            # every request that matters is same-origin and initiated by us.
            self.send_header(
                "Set-Cookie",
                "{}={}; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400".format(
                    COOKIE_NAME, set_cookie
                ),
            )
        self.end_headers()
        self.wfile.write(body)

    def _cookie_key(self):
        """The session key this browser presented, or None."""
        header = self.headers.get("Cookie")
        if not header:
            return None
        try:
            jar = http.cookies.SimpleCookie(header)
        except http.cookies.CookieError:
            return None
        morsel = jar.get(COOKIE_NAME)
        return morsel.value if morsel is not None else None

    def _session(self):
        """``(session, lock, cookie_to_set)`` for the browser making the call.

        The resolved key is kept on the handler so a route that needs to
        replace the game can name it without re-reading the header.
        """
        presented = self._cookie_key()
        key, session, lock = self.store.acquire(presented)
        self._session_key = key
        return session, lock, (None if key == presented else key)

    def _send_static(self, name):
        path = os.path.join(STATIC_DIR, name)
        # Refuse anything that escapes the static directory.
        if not os.path.abspath(path).startswith(STATIC_DIR) or not os.path.isfile(path):
            self.send_error(404)
            return
        with open(path, "rb") as handle:
            body = handle.read()
        content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    # -- routes ------------------------------------------------------------

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send_static("index.html")
        elif path == "/api/state":
            session, lock, cookie = self._session()
            with lock:
                state = session.state()
            self._send_json(state, set_cookie=cookie)
        elif path.startswith("/static/"):
            self._send_static(path[len("/static/"):])
        else:
            self.send_error(404)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            payload = self._read_json()
        except ValueError:
            self._send_json({"error": "malformed JSON"}, 400)
            return

        session, lock, cookie = self._session()
        try:
            if path == "/api/new":
                session = self._new_game(payload, session)
            else:
                with lock:
                    if path == "/api/move":
                        session.play_human(int(payload["move"]))
                    elif path == "/api/bot":
                        session.play_bot()
                    elif path == "/api/undo":
                        session.undo()
                    else:
                        self.send_error(404)
                        return
            state = session.state()
        except (ValueError, KeyError, TypeError, OverflowError) as error:
            self._send_json({"error": str(error)}, 400, set_cookie=cookie)
            return

        self._send_json(state, set_cookie=cookie)

    def _new_game(self, payload, current):
        """Replace *this browser's* game, leaving anyone else's alone."""
        color = payload.get("human_color", current.human_color)
        if isinstance(color, str):
            color = NAME_TO_COLOR[color]
        return self.store.replace(
            self._session_key,
            human_color=color,
            mode=payload.get("mode", current.mode),
            time_limit=float(payload.get("time_limit", current.time_limit)),
            max_depth=int(payload.get("max_depth", current.max_depth)),
        )


def serve(host="127.0.0.1", port=8000, human_color=SILVER, mode="classic",
          time_limit=2.0, max_depth=32, max_sessions=MAX_SESSIONS):
    """Build a server with a session store bound to it.

    The caller runs ``serve_forever()``.  Handing back an unstarted server
    rather than blocking here is what lets the tests drive the API on a
    background thread, and lets ``port=0`` be resolved with
    ``httpd.server_address[1]`` before anything tries to open a browser at it.

    No game exists yet: the first request from a browser mints one, so the
    settings here are the defaults every new game inherits rather than the
    state of a single shared game.
    """
    _Handler.store = SessionStore(
        defaults={
            "human_color": human_color,
            "mode": mode,
            "time_limit": min(time_limit, MAX_TIME_LIMIT),
            "max_depth": max_depth,
        },
        max_sessions=max_sessions,
    )
    httpd = ThreadingHTTPServer((host, port), _Handler)
    httpd.store = _Handler.store
    return httpd


__all__ = ["GameSession", "SessionStore", "serve", "STATIC_DIR"]
