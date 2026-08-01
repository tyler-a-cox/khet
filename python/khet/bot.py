"""Bot players.

Ported from the Python engine's ``khet/engine/bot.py``. This layer stays in
Python on purpose: it runs once per move, not once per node, so it costs
nothing measurable, and move-selection policy is the part you actually want to
tinker with.

A bot only ever talks to the board through its public interface
(``legal_moves`` / ``make`` / ``unmake``), so a stronger search can be dropped
in later without the game logic knowing.

On randomness
-------------
A deterministic engine plays the same game every time from the same position,
which makes it useless as a source of training data: ten thousand self-play
games would be ten thousand copies of one game. :class:`AlphaBetaPlayer`
therefore supports sampling from the root move scores rather than always taking
the best move.

The sampling is over *scores*, not uniform over moves. Uniform noise mostly
produces blunders, and a corpus of blunders teaches a network what bad play
looks like. Softmax over scores at a low temperature keeps the games
recognisably sensible while still branching.
"""

import math
import random

from khet import MATE_THRESHOLD, NAME_TO_COLOR, Searcher

__all__ = ["Player", "RandomPlayer", "AlphaBetaPlayer"]


class Player:
    """Base class: something that can pick a move for a color."""

    def __init__(self, color):
        if isinstance(color, str):
            color = NAME_TO_COLOR[color]
        self.color = color

    def get_move(self, board):
        raise NotImplementedError


class RandomPlayer(Player):
    """Uniformly random legal move.  Useful as a baseline opponent."""

    def __init__(self, color, seed=None):
        super().__init__(color)
        self.rng = random.Random(seed)

    def get_move(self, board):
        moves = board.legal_moves(self.color)
        return self.rng.choice(moves) if moves else None


class AlphaBetaPlayer(Player):
    """Iterative-deepening alpha-beta player.

    Pass ``time_limit`` to search until the clock runs out rather than to a
    fixed depth; iterative deepening means there is always a completed depth to
    fall back on.

    Parameters
    ----------
    temperature:
        0 plays the best move every time.  Higher values sample more widely
        from the root moves.  Around 30-80 (in evaluation points) gives varied
        but still sensible play; the right value depends on your evaluation's
        scale.
    temperature_plies:
        Sample only for this many plies from the start of the game, then play
        best-move.  Randomising the opening and playing the rest properly is
        usually what you want for training data: it diversifies the positions
        without polluting the labels.
    top_k:
        Never sample outside the best ``k`` root moves, whatever the
        temperature says.
    blunder_margin:
        Never sample a move more than this far below the best score.  This is
        the guard rail that keeps temperature from throwing games away.
    break_ties_randomly:
        Choose uniformly among moves that tie for best, instead of taking
        whichever the move generator happened to list first.  On by default:
        see :meth:`_random_best` for why leaving it off skews play by colour.
        Turn it off only when you need bit-reproducible games.

    The ``evaluator`` and ``options`` arguments the Python version took are both
    gone. The evaluation is compiled into the Rust searcher, because calling
    back into Python at every leaf would cost far more than the rewrite saves;
    and there is only one search now, the options having been measured and
    removed.
    """

    def __init__(
        self,
        color,
        depth=4,
        time_limit=None,
        temperature=0.0,
        temperature_plies=None,
        top_k=8,
        blunder_margin=120,
        seed=None,
        break_ties_randomly=True,
    ):
        super().__init__(color)
        self.depth = depth
        self.time_limit = time_limit
        self.searcher = Searcher()
        self.temperature = temperature
        self.temperature_plies = temperature_plies
        self.top_k = top_k
        self.blunder_margin = blunder_margin
        self.break_ties_randomly = break_ties_randomly
        self.rng = random.Random(seed)
        self.last_result = None
        self.plies_played = 0

    def get_move(self, board):
        result = self.searcher.search(board, self.depth, self.time_limit)
        self.last_result = result
        self.plies_played += 1

        if result.move is None:
            return None
        if self._should_sample(result):
            return self._sample(result.root_moves)
        if self.break_ties_randomly:
            return self._random_best(result.root_moves)
        return result.move

    def _random_best(self, root_moves):
        """Pick uniformly among moves that tie for the best score.

        Free in strength terms - the moves are equal by definition - and it
        removes a systematic colour bias that is otherwise invisible.

        With a coarse evaluation most positions are *full* of ties: measured at
        depth 3, 21 of 26 positions had more than one move at the top score,
        averaging 9.5 tied moves.  Taking ``root_moves[0]`` then hands the
        decision to move-generation order, which walks each side's piece list
        and each square's neighbours in board order - and that order is not
        symmetric under the 180 degree colour swap.  So red and silver break
        ties toward different kinds of move, one of those habits is better, and
        play comes out lopsided even though the evaluation and the search are
        provably colour-symmetric.
        """
        if not root_moves:
            return None
        best = root_moves[0][1]
        tied = [move for move, score in root_moves if score == best]
        return self.rng.choice(tied) if len(tied) > 1 else tied[0]

    def _should_sample(self, result):
        if self.temperature <= 0 or not result.root_moves:
            return False
        if (
            self.temperature_plies is not None
            and self.plies_played > self.temperature_plies
        ):
            return False
        # Never gamble in a decided position: if a win is proved, take it, and
        # if the game is lost the sampling only obscures how it was lost.
        return abs(result.score) < MATE_THRESHOLD

    def _sample(self, root_moves):
        best_score = root_moves[0][1]
        candidates = [
            (move, score)
            for move, score in root_moves[: self.top_k]
            if best_score - score <= self.blunder_margin
        ]
        if len(candidates) < 2:
            return root_moves[0][0]

        # Softmax over scores.  Subtracting the best score first keeps exp()
        # from overflowing and makes the result depend only on differences.
        weights = [
            math.exp((score - best_score) / self.temperature)
            for _, score in candidates
        ]
        total = sum(weights)
        draw = self.rng.random() * total
        cumulative = 0.0
        for (move, _), weight in zip(candidates, weights):
            cumulative += weight
            if draw <= cumulative:
                return move
        return candidates[-1][0]
