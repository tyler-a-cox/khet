"""
Create a tree of possible moves and evaluate them
Use minimax algorithm to find the best move
Incorporate alpha-beta pruning to reduce the number of nodes to evaluate
"""
import math
from khet.engine.evaluation import evaluate_board_simple

def alpha_beta_pruning(board, depth, alpha, beta, maximizingPlayer):
    """
    """
    if depth == 0 or board.is_game_over():
        return evaluate_board_simple(board)
    
    if maximizingPlayer:
        maxEval = -math.inf
        for move in board.get_all_valid_moves():
            eval = alpha_beta_pruning(board, depth - 1, alpha, beta, False)
            maxEval = max(maxEval, eval)
            alpha = max(alpha, eval)
            if beta <= alpha:
                break
        return maxEval
    else:
        minEval = math.inf
        for move in board.get_all_valid_moves():
            eval = alpha_beta_pruning(board, depth - 1, alpha, beta, True)
            minEval = min(minEval, eval)
            beta = min(beta, eval)
            if beta <= alpha:
                break
        return minEval