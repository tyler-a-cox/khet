"""
Python file for evaluation of the board state

TODO: Implement evaluation function

IDEAS:
Classical evaluation:
- Count number of pieces in each color
- Count number of pieces in each color that are active
- Count number of pieces within each color that are in the opponent's half

Advanced evaluation:
- Train a neural network to evaluate the board state
- Use a pre-trained neural network to evaluate the board state
- Generate a dataset of board states and their corresponding evaluations and train a neural network on it
"""

PIECE_SCORES = {
    "Pharaoh": 1000,
    "Scarab": 0,
    "Pyramid": 200,
    "Anubis": 30,
}

def evaluate_board_simple(board, color):
    """
    """
    # List for each color
    score = 0

    for row in board:
        for piece in row:
            if piece and piece.color == color:
                score += PIECE_SCORES[piece.__name__]
            else:
                score -= PIECE_SCORES[piece.__name__]

    return score
    