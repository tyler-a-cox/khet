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
)

# Setup positions and orientations for the different game pieces in each game modes
# TODO: Consider moving this to a config file
GAME_MODES = {
    "classic": {
        "red": {
            "pharaoh": [((0, 5), 2)],
            "pyramid": [
                ((1, 2), 2),
                ((0, 7), 1),
                ((3, 0), 0),
                ((4, 0), 1),
                ((3, 7), 1),
                ((4, 7), 0),
                ((5, 6), 1),
            ],
            "scarab": [((3, 4), 3), ((3, 5), 0)],
            "anubis": [((0, 4), 2), ((0, 6), 2)],
            "sphinx": [((0, 0), 2)],
        },
        "silver": {
            "pharaoh": [((7, 4), 0)],
            "pyramid": [
                ((7, 2), 3),
                ((6, 7), 0),
                ((3, 2), 2),
                ((4, 2), 3),
                ((3, 9), 3),
                ((4, 9), 2),
                ((2, 3), 3),
            ],
            "scarab": [((4, 4), 1), ((4, 5), 2)],
            "anubis": [((7, 3), 0), ((7, 5), 0)],
            "sphinx": [((7, 9), 0)],
        },
    },
    "imhotep": {
        "red": {
            "pharaoh": [((0, 5), 2)],
            "pyramid": [
                ((1, 2), 2),
                ((0, 7), 1),
                ((3, 0), 0),
                ((4, 0), 1),
                ((3, 7), 1),
                ((4, 7), 0),
                ((5, 6), 1),
            ],
            "scarab": [((3, 4), 3), ((3, 5), 0)],
            "anubis": [((0, 4), 2), ((0, 6), 2)],
            "sphinx": [((0, 0), 2)],
        },
        "silver": {
            "pharaoh": [((7, 4), 0)],
            "pyramid": [
                ((7, 2), 3),
                ((6, 7), 0),
                ((3, 2), 2),
                ((4, 2), 3),
                ((3, 9), 3),
                ((4, 9), 2),
                ((2, 3), 3),
            ],
            "scarab": [((4, 4), 1), ((4, 5), 2)],
            "anubis": [((7, 3), 0), ((7, 5), 0)],
            "sphinx": [((7, 9), 0)],
        },
    },
    "dynasty": {
        "red": {
            "pharaoh": [((0, 5), 2)],
            "pyramid": [
                ((1, 2), 2),
                ((0, 7), 1),
                ((3, 0), 0),
                ((4, 0), 1),
                ((3, 7), 1),
                ((4, 7), 0),
                ((5, 6), 1),
            ],
            "scarab": [((3, 4), 3), ((3, 5), 0)],
            "anubis": [((0, 4), 2), ((0, 6), 2)],
            "sphinx": [((0, 0), 2)],
        },
        "silver": {
            "pharaoh": [((7, 4), 0)],
            "pyramid": [
                ((7, 2), 3),
                ((6, 7), 0),
                ((3, 2), 2),
                ((4, 2), 3),
                ((3, 9), 3),
                ((4, 9), 2),
                ((2, 3), 3),
            ],
            "scarab": [((4, 4), 1), ((4, 5), 2)],
            "anubis": [((7, 3), 0), ((7, 5), 0)],
            "sphinx": [((7, 9), 0)],
        },
    },
}

GAME_PIECES = {
    "pharaoh": Pharaoh,
    "pyramid": Pyramid,
    "scarab": Scarab,
    "anubis": Anubis,
    "sphinx": Sphinx,
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
        self._board = [[None for _ in range(10)] for _ in range(8)]
        self.active_pieces = {"red": [], "silver": []}

        # Populate the board
        self._populate_board(game_mode)

    def _populate_board(self, game_mode) -> None:
        """ """
        for color in ["red", "silver"]:
            for piece in GAME_PIECES:
                for position, orientation in GAME_MODES[game_mode][color].get(
                    piece, []
                ):
                    self._add_piece(color, piece, position, orientation)

    def _add_piece(self, color, piece, position, orientation) -> None:
        """ """
        assert piece in GAME_PIECES, "Invalid piece type"
        assert color in ["red", "silver"], "Invalid color"

        # Create the piece
        new_piece = GAME_PIECES[piece](position, orientation, color)

        # Add the piece to the board
        self._board[position[0]][position[1]] = new_piece

        # Add the piece to the active pieces
        self.active_pieces[color].append(new_piece)

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
