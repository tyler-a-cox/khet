"""Console script for khet.

argparse rather than Click, so the installed wheel has no Python dependencies
at all - the whole engine is the compiled extension and the rest is stdlib.
The command surface matches the Python engine's CLI:

    khet play --color red --time-limit 5
    khet selfplay --depth 5
    khet bench
"""

import argparse
import platform
import sys
import threading
import time
import webbrowser

from khet import (
    COLOR_NAMES,
    NAME_TO_COLOR,
    RED,
    SILVER,
    GameBoard,
    Searcher,
    __version__,
    move_name,
    perft,
)
from khet.bot import AlphaBetaPlayer, RandomPlayer


def cmd_play(args):
    """Play against the engine in a browser."""
    from khet.ui.server import serve

    httpd = serve(
        host=args.host,
        port=args.port,
        human_color=NAME_TO_COLOR[args.color],
        mode=args.mode,
        time_limit=args.time_limit,
        max_depth=args.max_depth,
    )
    bound_port = httpd.server_address[1]
    url = "http://{}:{}/".format(args.host, bound_port)

    # Flushed explicitly: stdout is block-buffered when it is not a terminal,
    # so piping or redirecting `khet play` would otherwise hide the URL
    # until the server exits, which is exactly when it stops being useful.
    print("Khet is running at {}".format(url), flush=True)
    print("You are {}; the bot gets {:g}s per move.  Ctrl-C to stop.".format(
        args.color, args.time_limit), flush=True)
    # The Python engine printed the interpreter here, because `khet play` could
    # quietly be CPython where PyPy was intended and nothing else said so.
    # That failure mode is gone - the search is compiled in - so what is worth
    # printing instead is that you are on the Rust engine at all.
    print("Engine: khet {} (native), driven by {} {}".format(
        __version__, platform.python_implementation(), platform.python_version()),
        flush=True)

    if not args.no_browser:
        # Delayed so the browser cannot beat serve_forever to the socket.
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
    return 0


def cmd_selfplay(args):
    """Play the engine against itself.

    Useful as an end-to-end check: a full game exercises move generation, the
    laser, make/unmake and the search together.
    """
    board = GameBoard(args.mode)
    players = {
        SILVER: AlphaBetaPlayer(SILVER, depth=args.depth,
                                time_limit=args.time_limit, seed=args.seed),
        RED: AlphaBetaPlayer(RED, depth=max(1, args.depth - 2),
                             time_limit=args.time_limit, seed=args.seed),
    }

    for ply in range(args.max_moves):
        if board.winner is not None:
            break
        player = players[board.side_to_move]
        move = player.get_move(board)
        if move is None:
            break
        result = player.last_result
        if not args.quiet:
            print("{:>3}. {:<6} {:<10} score {:>7}  depth {}  {:,} nodes  {:.2f}s".format(
                ply + 1,
                COLOR_NAMES[board.side_to_move],
                move_name(move),
                result.score,
                result.depth,
                result.nodes,
                result.elapsed,
            ))
        board.make(move)

    print()
    print(board)
    if board.winner is None:
        print("No result after {} plies.".format(args.max_moves))
    return 0


def cmd_strength(args):
    """Play the search against a random mover.

    A sanity check on strength rather than speed: if the search is wired up
    correctly it should not lose to random play.
    """
    wins = {RED: 0, SILVER: 0, None: 0}
    for game in range(args.games):
        board = GameBoard("classic")
        # Alternate which color the engine takes.
        engine_color = SILVER if game % 2 == 0 else RED
        players = {
            engine_color: AlphaBetaPlayer(engine_color, depth=args.depth),
            engine_color ^ 1: RandomPlayer(engine_color ^ 1, seed=args.seed + game),
        }
        for _ in range(300):
            if board.winner is not None:
                break
            move = players[board.side_to_move].get_move(board)
            if move is None:
                break
            board.make(move)
        wins[board.winner] += 1
        print("game {}: engine as {:<6} -> {}".format(
            game + 1,
            COLOR_NAMES[engine_color],
            "draw" if board.winner is None else COLOR_NAMES[board.winner],
        ))
    print("\nred {}  silver {}  unfinished {}".format(
        wins[RED], wins[SILVER], wins[None]))
    return 0


def cmd_bench(args):
    """perft and fixed-depth search, through the Python bindings.

    The numbers here are a little below `cargo run --bin bench` because each
    call crosses the FFI boundary; the gap is the cost of the boundary, which
    is worth knowing when deciding what belongs on which side of it.
    """
    print("khet {} via {} {}".format(
        __version__, platform.python_implementation(), platform.python_version()))

    print("\nperft (move generation + make/unmake)")
    for depth in range(1, args.perft_depth + 1):
        board = GameBoard("classic")
        start = time.perf_counter()
        nodes = perft(board, depth)
        elapsed = time.perf_counter() - start
        print("  depth {}: {:>12,}  {:>8.3f}s  {:>14,.0f} nodes/s".format(
            depth, nodes, elapsed, nodes / elapsed if elapsed else 0))

    print("\nalpha-beta search")
    for depth in range(1, args.search_depth + 1):
        board = GameBoard("classic")
        result = Searcher().search(board, depth)
        print("  depth {}: {:>12,}  {:>8.3f}s  {:>14,.0f} nodes/s  score {:>7}  best {}".format(
            depth, result.nodes, result.elapsed, result.nodes_per_second,
            result.score, move_name(result.move) if result.move is not None else "-"))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="khet", description="Khet: laser chess.")
    parser.add_argument("--version", action="version",
                        version="khet {}".format(__version__))
    sub = parser.add_subparsers(dest="command", required=True)

    play = sub.add_parser("play", help="play against the engine in a browser")
    play.add_argument("--color", choices=COLOR_NAMES, default="silver",
                      help="which side you play; silver moves first")
    play.add_argument("--time-limit", type=float, default=2.0,
                      help="seconds the bot may think per move")
    play.add_argument("--max-depth", type=int, default=32,
                      help="ceiling on iterative deepening; the clock normally stops it first")
    play.add_argument("--mode", default="classic", help="starting configuration")
    play.add_argument("--port", type=int, default=8000,
                      help="port to serve on; 0 picks a free one")
    play.add_argument("--host", default="127.0.0.1", help="interface to bind")
    play.add_argument("--no-browser", action="store_true",
                      help="do not open a browser window")
    play.set_defaults(func=cmd_play)

    selfplay = sub.add_parser("selfplay", help="watch the engine play itself")
    selfplay.add_argument("--depth", type=int, default=4)
    selfplay.add_argument("--time-limit", type=float, default=None,
                          help="seconds per move; overrides depth as the stopping rule")
    selfplay.add_argument("--max-moves", type=int, default=200)
    selfplay.add_argument("--mode", default="classic")
    selfplay.add_argument("--seed", type=int, default=None)
    selfplay.add_argument("--quiet", action="store_true")
    selfplay.set_defaults(func=cmd_selfplay)

    strength = sub.add_parser("strength", help="play the search against a random mover")
    strength.add_argument("--depth", type=int, default=4)
    strength.add_argument("--games", type=int, default=10)
    strength.add_argument("--seed", type=int, default=0)
    strength.set_defaults(func=cmd_strength)

    bench = sub.add_parser("bench", help="perft and search timings through the bindings")
    bench.add_argument("--perft-depth", type=int, default=3)
    bench.add_argument("--search-depth", type=int, default=6)
    bench.set_defaults(func=cmd_bench)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
