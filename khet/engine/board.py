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
import string
from khet.engine.pieces import (
    Pharaoh,
    Pyramid,
    Scarab,
    Anubis,
    Sphinx,
    EyeOfHorus,
)

MOVEMENT_DICT = {
    "up": (-1, 0),
    "down": (1, 0),
    "left": (0, -1),
    "right": (0, 1),
    "up-left": (-1, -1),
    "up-right": (-1, 1),
    "down-left": (1, -1),
    "down-right": (1, 1),
}

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

    def remove_piece(self, color, piece) -> None:
        """ """
        pass

    def move_piece(
        self, position, color=None, direction=None, rotation=None, check_color=True
    ) -> None:
        """

        Parameters:
            color: str
                Color of the piece to move
            piece: str
                Type of piece to move
            direction: tuple
                Direction to move the piece. Options are up, down, left, right,
                up-left, up-right, down-left, and down-right.
            rotation: str
                Direction to rotate the piece. Options are clockwise and counterclockwise.
        """
        assert (
            direction is not None or rotation is not None
        ), "Must specify either position or rotation"

        assert direction in [
            "up",
            "down",
            "left",
            "right",
            "up-left",
            "up-right",
            "down-left",
            "down-right",
            None,
        ], "Invalid direction"

        assert rotation in ["clockwise", "counterclockwise", None], "Invalid rotation"

        # Get the piece
        piece = self._board[position[0]][position[1]]

        # Check if the piece is the correct color
        if check_color and color is not None:
            assert piece.color == color, "Invalid color"

        # Move the piece
        if direction is not None:
            piece.move(direction)

            # Move the piece on the board
            #old_piece = self._board[piece.position[0]][piece.position[0]]
            self._board[position[0]][position[1]] = None
            self._board[piece.position[0]][piece.position[1]] = piece
        elif rotation is not None:
            piece.rotate(rotation)


    def end_turn(self, color) -> None:
        """

        Parameters:
            color: str
                Color of the player ending their turn
        """
        # XXX: Fire the laser
        # Find the positon and orientation of the laser
        active_pieces = [piece for row in self._board for piece in row if piece]

        # Find the sphinx piece for the player
        for piece in active_pieces:
            if piece and piece.color == color and piece.__name__.lower() == "sphinx":
                sphinx = piece
                break

        # Get the position and orientation of the sphinx
        sphinx_orientation = sphinx.orientation
        laser_x, laser_y = sphinx.position

        if sphinx_orientation == 0:
            # Fire the laser up
            laser_direction = "up"
            laser_x -= 1
        elif sphinx_orientation == 1:
            # Fire the laser right
            laser_direction = "right"
            laser_y += 1
        elif sphinx_orientation == 2:
            # Fire the laser down
            laser_direction = "down"
            laser_x += 1
        elif sphinx_orientation == 3:
            # Fire the laser left
            laser_direction = "left"
            laser_y -= 1

        # Loop through the board until the laser hits a piece
        # TODO: Consider moving this to a separate function
        # TODO: Consider having a better stopping condition
        # TODO: Consider having a better way to remove pieces
        # TODO: Don't hardcode board size
        while (
            laser_x >= 0
            and laser_x < 8
            and laser_y >= 0
            and laser_y < 10
            and laser_direction is not None
        ):

            # Get the piece at the current position
            piece = self._board[laser_x][laser_y]

            if piece is not None:
                # Check if the piece is a pyramid
                laser_direction = piece.resolve_laser_interaction(laser_direction)

            # Move the laser
            if laser_direction == "up":
                laser_x -= 1
            elif laser_direction == "down":
                laser_x += 1
            elif laser_direction == "left":
                laser_y -= 1
            elif laser_direction == "right":
                laser_y += 1

        # Check for a hit
        removal_index = []
        for pi, piece in enumerate(active_pieces):
            if not piece.is_active:
                removal_index.append(pi)

        # Reverse the removal index list
        removal_index = sorted(removal_index, reverse=True)

        # Remove the pieces
        for pi in removal_index:
            pos_y, pos_x = active_pieces[pi].position
            self._board[pos_y][pos_x] = None
            active_pieces.pop(pi)

    def get_all_valid_moves(self, color) -> list:
        """

        Parameters:
            color: str
                Color of the player to get the valid moves for
        """
        all_moves = []
        active_pieces = [
            piece
            for row in self._board
            for piece in row
            if piece and piece.color == color
        ]
        for piece in active_pieces:
            moves = piece.get_valid_moves()
            #valid_moves = (move for move in moves if self.is_move_valid(piece, move[0], move[1]))
            valid_moves = list(
                filter(lambda x: self.is_move_valid(piece, x[0], x[1]), moves)
            )
            #valid_moves = filter(lambda x: self.is_move_valid(piece, x[0], x[1]), moves)
            all_moves.append((piece, valid_moves))

        return all_moves

    def is_move_valid(self, piece, move, rotation):
        """

        Parameters:
            piece: str
                Type of piece to move
            move: str
                Direction to move the piece. Options are up, down, left, right,
                up-left, up-right, down-left, and down-right.
            rotation: str
                Direction to rotate the piece. Options are clockwise and counterclockwise.

        Returns:
            bool
                True if the move is valid, False otherwise
        """
        i, j = piece.position
        # Check if the move is valid
        if move:
            # Get the new position
            new_position = (
                i + MOVEMENT_DICT[move][0],
                j + MOVEMENT_DICT[move][1]
            )

            if (
                new_position[0] >= 0
                and new_position[0] < 8
                and new_position[1] >= 0
                and new_position[1] < 10
                and self._board[new_position[0]][new_position[1]] is None
            ):
                return True
            else:
                return False

        # Rotation is always valid if previous conditions are met
        return True

    def is_game_over(self) -> bool:
        """
        Function to check if the game is over

        Returns:
            bool
                True if the game is over, False otherwise
        """
        # Check if the game is over
        pieces = [
            piece
            for row in self._board
            for piece in row
            if piece and piece.__name__.lower() == "pharaoh"
        ]

        # There should only be two pharaohs
        return len(pieces) == 2
    
    def board_repr(self) -> str:
        """ """
        output = ''
        rot2char = {0: 'u', 1: 'r', 2: 'd', 3: 'l'}
        for ri, row in enumerate(self._board):
            for ci, piece in zip(string.ascii_lowercase[:len(row)], row):
                if piece:
                    if piece.__name__ == 'Pyramid':
                        name = "p"
                    else:
                        name = piece.__name__[0]

                    output += f'{name}{rot2char[piece.orientation]}{piece.color[0]}{ci}{ri}.'

        return output