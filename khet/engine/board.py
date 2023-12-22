"""
Module for handling the khet game board

TODO:
    - Add logic for the laser
    - Add logic for moving game pieces on the board
    - Add logic for resolving laser interactions
    - Add logic for determining valid moves
    - Add logic for determining valid rotations
    - Add logic for obtaining a player's score for the board
"""
from khet.engine.pieces import (
    Pharaoh,
    Pyramid,
    Scarab,
    Anubis,
    Sphinx,
    EyeOfHorus,
    Obelisk,
)

GAME_MODES = {
    "classic": {
        "pharaoh": 1,
        "pyramid": 2,
        "scarab": 2,
        "anubis": 2,
        "sphinx": 1,
    },
    "imhotep": {
        "pharaoh": 1,
        "pyramid": 2,
        "scarab": 2,
        "anubis": 2,
        "sphinx": 1,
        "eyeofhorus": 1,
    },
    "dynasty": {
        "pharaoh": 1,
        "pyramid": 2,
        "scarab": 2,
        "anubis": 2,
        "sphinx": 1,
        "eyeofhorus": 1,
    },
}

GAME_PIECES = {
    "pharaoh": Pharaoh,
    "pyramid": Pyramid,
    "scarab": Scarab,
    "anubis": Anubis,
    "sphinx": Sphinx,
    "obelisk": Obelisk,
    "eyeofhorus": EyeOfHorus,
}


class GameBoard:
    """ """

    def __init__(self, game_mode) -> None:
        """ """
        assert game_mode in GAME_MODES, "Invalid game mode"

        # Store the game mode
        self.game_mode = game_mode

        # Initialize the board
        self._populate_board(game_mode)
        self.active_pieces = {"red": [], "silver": []}

    def _populate_board(self, game_mode) -> None:
        """ """
        for color in ["red", "silver"]:
            for piece in GAME_PIECES:
                self._add_piece(color, piece, None, None)

    def _add_piece(self, color, piece, position, orientation) -> None:
        """ """
        pass

    def remove_piece(self, color, piece) -> None:
        """ """
        pass

    def move_piece(self, color, piece, position=None, rotation=None) -> None:
        """
        Parameters:
            color: str
                Color of the piece to move
            piece: str
                Type of piece to move
            position: tuple
                (x, y) position to move the piece to
            rotation: str
                Direction to rotate the piece
        """
        assert (
            position is not None or rotation is not None
        ), "Must specify either position or rotation"

    def end_turn(self, color) -> None:
        """

        Parameters:
            color: str
                Color of the player ending their turn
        """
        # XXX: Fire the laser
        # Find the positon and orientation of the laser
        sphinx = self.active_pieces[color]["sphinx"]

        # Get the position and orientation of the sphinx
        sphinx_position = sphinx.position
        sphinx_orientation = sphinx.orientation

        laser_direction = None

        if sphinx_orientation == 0:
            # Fire the laser up
            laser_direction = "up"
        elif sphinx_orientation == 1:
            # Fire the laser left
            laser_direction = "left"

    def get_all_valid_moves(self, color) -> list:
        """

        Parameters:
            color: str
                Color of the player to get the valid moves for
        """
        all_moves = []
        for piece in self.active_pieces[color]:
            moves = self.get_valid_move(piece, color)
            all_moves.append(moves)

        return all_moves

    def get_valid_move(self, piece, color) -> list:
        """
        Get valid moves for a given piece

        Parameters:
            piece: str
                Type of piece to get the valid moves for
            color: str
                Color of the player to get the valid moves for
        """
        # Loop through all the pieces of the given color
        piece.is_valid_move()

        return []

    def assess_valid_moves(self, color) -> list:
        """
        Assess the valid moves for a given color

        TODO: consider moving this to the game ai module
        """
        # Generate a list of all valid moves for the given color
        valid_moves = self.get_all_valid_moves(color)

        # Loop through all the valid moves on the board and assess their value
        for move in valid_moves:
            pass
