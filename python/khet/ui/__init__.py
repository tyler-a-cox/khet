"""Browser UI for playing against the engine.

``khet play`` starts a small stdlib HTTP server that serves a single page
and a JSON API over one ``GameBoard``. Nothing in here is imported by the
engine, so the search has no idea a UI exists.
"""

from khet.ui.server import GameSession, serve

__all__ = ["GameSession", "serve"]
