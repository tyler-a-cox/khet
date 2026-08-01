"""The browser UI, driven over HTTP.

``static/index.html`` came over from the Python engine untouched, so the JSON
contract is the thing under test here: if a field changed name, type or
nullability, the page would break in ways no engine test would catch.

The server is started on port 0 and driven with ``urllib`` on a background
thread, which is also the only way to exercise the parts that only exist
because it is threaded - per-session cookies, per-session locks, and a search
that releases the GIL.
"""

import json
import threading
import urllib.error
import urllib.request

import pytest

import khet as K
from khet.ui.server import GameSession, serve

#: Every key the page or a client may rely on, with the type it must have.
STATE_CONTRACT = {
    "rows": int, "cols": int,
    "squares": list, "restricted": list, "sphinxes": list,
    "side_to_move": int, "human_color": int, "bot_color": int,
    "your_turn": bool, "legal_moves": list, "moves": list,
    "time_limit": (int, float), "can_undo": bool, "color_names": list,
}


@pytest.fixture(scope="module")
def server():
    httpd = serve(host="127.0.0.1", port=0, time_limit=0.05, max_depth=4)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:{}".format(httpd.server_address[1])
    httpd.shutdown()
    httpd.server_close()


class Client:
    """A browser: keeps its cookie, so it keeps its game."""

    def __init__(self, base):
        self.base = base
        self.cookie = None

    def request(self, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(self.base + path, data=data)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if self.cookie:
            request.add_header("Cookie", self.cookie)
        with urllib.request.urlopen(request, timeout=30) as response:
            header = response.headers.get("Set-Cookie")
            if header:
                self.cookie = header.split(";", 1)[0]
            return json.loads(response.read())


def test_index_page_is_served(server):
    with urllib.request.urlopen(server + "/", timeout=10) as response:
        body = response.read()
    assert response.status == 200
    assert b"<html" in body.lower()


def test_state_payload_matches_the_contract(server):
    state = Client(server).request("/api/state")
    for key, expected in STATE_CONTRACT.items():
        assert key in state, "missing {}".format(key)
        assert isinstance(state[key], expected), "{} is {}".format(key, type(state[key]))
    # Nullable by design: the page tests all three for absence.
    assert state["winner"] is None
    assert state["last"] is None
    assert state["thinking"] is None
    assert len(state["squares"]) == K.ROWS * K.COLS
    assert len(state["restricted"]) == K.ROWS * K.COLS
    assert state["your_turn"] is True
    assert len(state["legal_moves"]) == 79


def test_playing_a_move_and_a_bot_reply(server):
    client = Client(server)
    state = client.request("/api/state")
    move = state["legal_moves"][0]["move"]

    state = client.request("/api/move", {"move": move})
    assert state["your_turn"] is False
    assert len(state["moves"]) == 1
    assert state["last"]["by_bot"] is False
    # The beam is reconstructed against a board the shot has already changed,
    # so a non-empty path here is what proves `beam_after` puts the captured
    # piece back before walking.
    assert len(state["last"]["beam"]) > 0

    state = client.request("/api/bot", {})
    assert state["your_turn"] is True
    assert len(state["moves"]) == 2
    assert state["last"]["by_bot"] is True
    assert state["thinking"]["nodes"] > 0
    assert state["thinking"]["depth"] >= 1
    assert state["can_undo"] is True


def test_undo_returns_the_turn_to_the_person(server):
    client = Client(server)
    state = client.request("/api/state")
    client.request("/api/move", {"move": state["legal_moves"][0]["move"]})
    client.request("/api/bot", {})
    state = client.request("/api/undo", {})
    # Undo takes back the person's move *and* the reply: one ply would just
    # hand the position straight back to the bot.
    assert state["moves"] == []
    assert state["your_turn"] is True


def test_illegal_move_is_rejected(server):
    client = Client(server)
    client.request("/api/state")
    with pytest.raises(urllib.error.HTTPError) as caught:
        client.request("/api/move", {"move": 0})
    assert caught.value.code == 400
    assert "illegal move" in json.loads(caught.value.read())["error"]


def test_each_browser_gets_its_own_game(server):
    one, two = Client(server), Client(server)
    state = one.request("/api/state")
    one.request("/api/move", {"move": state["legal_moves"][0]["move"]})
    assert one.request("/api/state")["moves"] != []
    # A second browser must not inherit the first one's board.
    assert two.request("/api/state")["moves"] == []
    assert one.cookie != two.cookie


def test_new_game_can_switch_colours(server):
    client = Client(server)
    client.request("/api/state")
    state = client.request("/api/new", {"human_color": "red", "time_limit": 0.05})
    assert state["human_color"] == K.RED
    assert state["bot_color"] == K.SILVER
    # Silver moves first, so playing red means it is not your turn yet.
    assert state["your_turn"] is False
    assert state["moves"] == []


def test_time_limit_is_capped(server):
    client = Client(server)
    client.request("/api/state")
    state = client.request("/api/new", {"time_limit": 9999})
    assert state["time_limit"] <= 30.0


def test_concurrent_browsers_are_not_serialised(server):
    """One person's search must not block another person's poll.

    The searcher releases the GIL, so a `/api/state` read on a second session
    should complete while the first session is mid-search.
    """
    slow, quick = Client(server), Client(server)
    slow.request("/api/new", {"time_limit": 1.0})
    quick.request("/api/state")

    state = slow.request("/api/state")
    slow.request("/api/move", {"move": state["legal_moves"][0]["move"]})

    done = threading.Event()
    thread = threading.Thread(target=lambda: (slow.request("/api/bot", {}), done.set()))
    thread.start()
    try:
        # This would time out, or block for the full search, if the GIL were
        # held for the duration.
        assert quick.request("/api/state")["your_turn"] is True
    finally:
        thread.join(timeout=30)
    assert done.is_set()


def test_a_whole_game_plays_out_in_process():
    """Bot against bot through the session layer.

    Exercises move generation, the laser, make/unmake, the search and the
    serialisation together, and would catch a state payload that only happens
    to serialise from the opening position.
    """
    session = GameSession(human_color=K.RED, time_limit=None, max_depth=2)
    opponent = K.Searcher()

    for _ in range(120):
        if session.board.winner is not None:
            break
        if session.board.side_to_move == session.human_color:
            result = opponent.search(session.board, 2)
            if result.move is None:
                break
            session.play_human(result.move)
        else:
            if session.play_bot() is None:
                break
        json.dumps(session.state())      # must stay serialisable throughout

    state = session.state()
    assert len(state["moves"]) > 10
    if state["winner"] is not None:
        assert state["winner"] in (K.RED, K.SILVER)
        assert state["your_turn"] is False
