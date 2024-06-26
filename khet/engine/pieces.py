"""
File for handling the pieces in the game
"""

from khet.engine.exceptions import MovementError

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


class GamePiece:
    """
    Base class for all game pieces
    """

    def __init__(self, position, orientation, color) -> None:
        """
        Parameters:
            position: tuple
                (x, y) position of the piece
            orientation: int:
                0-3, 0 is facing up, 1 is facing right, etc.
            color: str
                Color of the piece
        """
        self.position = position
        self.orientation = orientation
        self.color = color
        self.is_active = True

    def rotate(self, direction) -> None:
        """ """
        if direction not in ["clockwise", "counterclockwise"]:
            raise MovementError(f"Invalid rotation direction: {direction}")

        if direction == "clockwise":
            self.orientation = (self.orientation + 1) % 4
        elif direction == "counterclockwise":
            self.orientation = (self.orientation - 1) % 4

    def move(self, direction) -> None:
        """ """
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

        # Dictionary for movement
        upmove, rightmove = MOVEMENT_DICT[direction]

        # Update positions
        self.position = (self.position[0] + upmove, self.position[1] + rightmove)

    def get_valid_moves(self) -> list:
        """ """
        for direction in [
            "up",
            "down",
            "left",
            "right",
            "up-left",
            "up-right",
            "down-left",
            "down-right",
        ]:
            if self.is_valid_move(direction=direction):
                yield (direction, None)

        for rotation in ["clockwise", "counterclockwise"]:
            if self.is_valid_move(rotation=rotation):
                yield (None, rotation)

    def is_valid_move(self, direction=None, rotation=None) -> bool:
        """ """
        assert (
            direction is not None or rotation is not None
        ), "Must specify either direction or rotation"

        # For the base class, all moves are valid
        return True


class Pyramid(GamePiece):
    """ """

    def __init__(self, position, orientation, color):
        """ """
        super().__init__(position, orientation, color)
        self.__name__ = "Pyramid"

    def resolve_laser_interaction(self, laser_direction):
        """
        Function for handling interactions between the laser and the pyramid
        """
        if laser_direction == "down":
            if self.orientation == 1 or self.orientation == 2:
                self.is_active = False
            elif self.orientation == 0:
                return "right"
            elif self.orientation == 3:
                return "left"
        elif laser_direction == "up":
            if self.orientation == 0 or self.orientation == 3:
                self.is_active = False
            elif self.orientation == 1:
                return "right"
            elif self.orientation == 2:
                return "left"
        elif laser_direction == "left":
            if self.orientation == 2 or self.orientation == 3:
                self.is_active = False
            elif self.orientation == 0:
                return "up"
            elif self.orientation == 1:
                return "down"
        elif laser_direction == "right":
            if self.orientation == 0 or self.orientation == 1:
                self.is_active = False
            elif self.orientation == 2:
                return "down"
            elif self.orientation == 3:
                return "up"


class Scarab(GamePiece):
    """ """

    def __init__(self, position, orientation, color):
        """ """
        super().__init__(position, orientation, color)
        self.__name__ = "Scarab"

    def resolve_laser_interaction(self, laser_direction):
        """
        Return
        """
        if laser_direction == "down":
            if self.orientation == 0 or self.orientation == 2:
                return "left"
            else:
                return "right"
        elif laser_direction == "up":
            if self.orientation == 0 or self.orientation == 2:
                return "right"
            else:
                return "left"
        elif laser_direction == "left":
            if self.orientation == 0 or self.orientation == 2:
                return "down"
            else:
                return "up"
        elif laser_direction == "right":
            if self.orientation == 0 or self.orientation == 2:
                return "up"
            else:
                return "down"


class Anubis(GamePiece):
    """ """

    def __init__(self, position, orientation, color):
        """ """
        super().__init__(position, orientation, color)
        self.__name__ = "Anubis"

    def resolve_laser_interaction(self, laser_direction):
        """ """
        if laser_direction == "down":
            if self.orientation == 0:
                return
            else:
                self.is_active = False
                return

        elif laser_direction == "up":
            if self.orientation == 2:
                return
            else:
                self.is_active = False
                return
        elif laser_direction == "left":
            if self.orientation == 1:
                return
            else:
                self.is_active = False
                return
        elif laser_direction == "right":
            if self.orientation == 3:
                return
            else:
                self.is_active = False
                return


class Sphinx(GamePiece):
    """ """

    def __init__(self, position, orientation, color):
        """ """
        super().__init__(position, orientation, color)
        self.__name__ = "Sphinx"

    def resolve_laser_interaction(self, laser_direction):
        """ """
        # Nothing happens if the sphinx is hit from any side
        return

    def move(self, direction) -> None:
        """
        Overwrite the move method to prevent the sphinx from moving
        """
        raise MovementError("Sphinx cannot move")

    def rotate(self, rotation) -> None:
        """
        Overwrite the rotate method to prevent the sphinx from rotating invalidly
        """
        if self.orientation == 0 and rotation == "counterclockwise":
            self.orientation = 3
        elif self.orientation == 3 and rotation == "clockwise":
            self.orientation = 0
        elif self.orientation == 1 and rotation == "clockwise":
            self.orientation = 2
        elif self.orientation == 2 and rotation == "counterclockwise":
            self.orientation = 1
        else:
            raise MovementError(
                f"{rotation} rotation invalid for {self.color.capitalize()} Sphinx in orientation {self.orientation}"
            )

    def is_valid_move(self, direction=None, rotation=None) -> bool:
        """ """
        if direction is not None:
            return False
        
        if self.orientation == 0 and rotation == "clockwise":
            return False
        elif self.orientation == 3 and rotation == "counterclockwise":
            return False
        elif self.orientation == 1 and rotation == "counterclockwise":
            return False
        elif self.orientation == 2 and rotation == "clockwise":
            return False

        return True


class Pharaoh(GamePiece):
    """ """

    def __init__(self, position, orientation, color):
        """ """
        super().__init__(position, orientation, color)
        self.__name__ = "Pharaoh"

    def resolve_laser_interaction(self, laser_direction):
        """ """
        self.is_active = False


# Expansion Pieces
class EyeOfHorus(GamePiece):
    """ """

    def __init__(self, position, orientation, color):
        """ """
        super().__init__(position, orientation, color)
        self.__name__ = "EyeOfHorus"
