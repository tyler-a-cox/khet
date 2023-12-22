"""
File for handling the pieces in the game
"""


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

    def rotate(self, direction) -> None:
        """ """
        assert direction in ["clockwise", "counterclockwise"], "Invalid direction"

        if direction == "clockwise":
            self.orientation = (self.orientation + 1) % 4
        elif direction == "counterclockwise":
            self.orientation = (self.orientation - 1) % 4

    def move(self, direction) -> None:
        """ """
        assert direction in ["up", "down", "left", "right"], "Invalid direction"

        if direction == "up":
            self.position[1] += 1
        elif direction == "down":
            self.position[1] -= 1
        elif direction == "left":
            self.position[0] -= 1
        elif direction == "right":
            self.position[0] += 1
        elif direction == "up-left":
            self.position[0] -= 1
            self.position[1] += 1
        elif direction == "up-right":
            self.position[0] += 1
            self.position[1] += 1
        elif direction == "down-left":
            self.position[0] -= 1
            self.position[1] -= 1
        elif direction == "down-right":
            self.position[0] += 1
            self.position[1] -= 1

    def is_valid_move(self, direction=None, rotation=None) -> None:
        """ """
        assert (
            direction is not None or rotation is not None
        ), "Must specify either direction or rotation"
        # XXX: Add logic for
        return True


class Pyramid(GamePiece):
    """ """

    def __init__(self, position, orientation, color):
        """ """
        super().__init__(position, orientation, color)

    def resolve_laser_interaction(self, side):
        """ """
        # XXX: Add logic for
        return True


class Scarab(GamePiece):
    """ """

    def __init__(self, position, orientation, color):
        """ """
        super().__init__(position, orientation, color)

    def resolve_laser_interaction(self, side):
        """
        Return
        """
        # XXX: Add logic for
        return True

    def is_valid_move(self, direction=None, rotation=None):
        """ """
        assert (
            direction is not None or rotation is not None
        ), "Must specify either direction or rotation"
        # XXX: Add logic for
        return True


class Anubis(GamePiece):
    """ """

    def __init__(self, position, orientation, color):
        """ """
        super().__init__(position, orientation, color)

    def resolve_laser_interaction(self, side):
        """ """
        # XXX: Add logic for
        return True


class Sphinx(GamePiece):
    """ """

    def __init__(self, position, orientation, color):
        """ """
        super().__init__(position, orientation, color)

    def resolve_laser_interaction(self, side):
        """ """
        # XXX: Add logic for
        return True

    def is_valid_move(self, direction=None, rotation=None):
        """ """
        assert direction is None, "Sphinx cannot move from its position"
        assert rotation is not None, "Must specify rotation"

        # XXX: Add logic for
        return True


class Pharaoh(GamePiece):
    """ """

    def __init__(self, position, orientation, color):
        """ """
        super().__init__(position, orientation, color)

    def resolve_laser_interaction(self, side):
        """ """
        # XXX: Add logic for
        return True


# Expansion Pieces
class EyeOfHorus(GamePiece):
    """ """

    def __init__(self, position, orientation, color):
        """ """
        super().__init__(position, orientation, color)
