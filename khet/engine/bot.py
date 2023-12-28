"""
File for handling the game-bot
"""
class Player:
    """
    """
    def __init__(self, color, evaluator='naive'):
        """

        Parameters:
            color: str
                Color of the player
            evaluator: str
                Name of the evaluation function to use
        """
        self.color = color
        self.evaluator = evaluator

    def get_move(self, board):
        """
        """
        pass