"""
Create a tree of possible moves and evaluate them
Use minimax algorithm to find the best move
Incorporate alpha-beta pruning to reduce the number of nodes to evaluate
"""
import math
from copy import deepcopy
from khet.engine.evaluation import evaluate_board_simple

def make_move(board, position, direction, rotation):
    """
    Make a move on the board
    """
    new_board = deepcopy(board)
    new_board.move_piece(position, direction, rotation)
    new_board.end_turn()
    return new_board

def alpha_beta_search(board, depth, alpha=-math.inf, beta=math.inf, maximizing_player=True):
    if depth == 0 or board.is_game_over():
        return evaluate_board_simple(board)

    legal_moves = board.get_all_valid_moves(board)

    if maximizing_player:
        max_eval = float('-inf')
        best_move = None
        for move in legal_moves:
            new_board = make_move(board, move)
            eval_score = alpha_beta_search(new_board, depth - 1, alpha, beta, False)
            if eval_score > max_eval:
                max_eval = eval_score
                best_move = move
            alpha = max(alpha, eval_score)
            if beta <= alpha:
                break  # Beta cutoff
        return best_move

    else:
        min_eval = float('inf')
        best_move = None
        for move in legal_moves:
            new_board = make_move(board, move)
            eval_score = alpha_beta_search(new_board, depth - 1, alpha, beta, True)
            if eval_score < min_eval:
                min_eval = eval_score
                best_move = move
            beta = min(beta, eval_score)
            if beta <= alpha:
                break  # Alpha cutoff
        return best_move