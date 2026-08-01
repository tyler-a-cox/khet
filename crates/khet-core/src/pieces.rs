//! Piece representation.
//!
//! A direct port of `khet/engine/pieces.py`.  Pieces are 6-bit codes:
//!
//! ```text
//! code = (piece_type << 3) | (color << 2) | orientation
//! ```
//!
//! `0` is "empty square", so `piece_type` starts at 1.
//!
//! Orientations and laser travel directions share one encoding:
//! `0 = up, 1 = right, 2 = down, 3 = left`.  For a *travel direction* this is
//! the direction the beam is moving, so a beam entering a square from its
//! north face is travelling `DOWN`.
//!
//! Every lookup table here is built by a `const fn` and materialised at compile
//! time.  The Python version builds the same tables at import; doing it in
//! `const fn` keeps the derivation readable (the rules are still spelled out in
//! code, not typed in as magic numbers) while costing nothing at runtime.

// --------------------------------------------------------------------------
// Directions
// --------------------------------------------------------------------------
pub const UP: u8 = 0;
pub const RIGHT: u8 = 1;
pub const DOWN: u8 = 2;
pub const LEFT: u8 = 3;

pub const DIR_NAMES: [&str; 4] = ["up", "right", "down", "left"];

/// Direction a beam travels when it arrives from face `f`.
const FROM_FACE: [u8; 4] = [DOWN, LEFT, UP, RIGHT];

// --------------------------------------------------------------------------
// Colors
// --------------------------------------------------------------------------
pub const RED: u8 = 0;
pub const SILVER: u8 = 1;

pub const COLOR_NAMES: [&str; 2] = ["red", "silver"];

#[inline(always)]
pub const fn opponent(color: u8) -> u8 {
    color ^ 1
}

// --------------------------------------------------------------------------
// Piece types
// --------------------------------------------------------------------------
pub const EMPTY: u8 = 0;
pub const PYRAMID: u8 = 1;
pub const SCARAB: u8 = 2;
pub const ANUBIS: u8 = 3;
pub const PHARAOH: u8 = 4;
pub const SPHINX: u8 = 5;

pub const TYPE_NAMES: [&str; 6] = ["", "pyramid", "scarab", "anubis", "pharaoh", "sphinx"];

/// Largest possible code + 1, used to size the lookup tables.
pub const CODE_RANGE: usize = (((SPHINX << 3) | (1 << 2) | 3) + 1) as usize; // 48

#[inline(always)]
pub const fn encode(piece_type: u8, color: u8, orientation: u8) -> u8 {
    (piece_type << 3) | (color << 2) | orientation
}

#[inline(always)]
pub const fn piece_type(code: u8) -> u8 {
    code >> 3
}

#[inline(always)]
pub const fn piece_color(code: u8) -> u8 {
    (code >> 2) & 1
}

#[inline(always)]
pub const fn orientation(code: u8) -> u8 {
    code & 3
}

/// `code` rotated 90 degrees, preserving type and color.
#[inline(always)]
pub const fn rotate_code(code: u8, clockwise: bool) -> u8 {
    let step: u8 = if clockwise { 1 } else { 3 };
    (code & !3) | ((code.wrapping_add(step)) & 3)
}

pub fn describe(code: u8) -> String {
    if code == EMPTY {
        return "empty".to_string();
    }
    format!(
        "{} {} facing {}",
        COLOR_NAMES[piece_color(code) as usize],
        TYPE_NAMES[piece_type(code) as usize],
        DIR_NAMES[orientation(code) as usize],
    )
}

// --------------------------------------------------------------------------
// Laser interaction table
// --------------------------------------------------------------------------
/// The beam terminates and the piece it struck is removed from play.
pub const DESTROY: i8 = -1;
/// The beam terminates but the piece survives (sphinx, or anubis hit head on).
pub const ABSORB: i8 = -2;

// Mirror diagonals, as maps from incoming travel direction to outgoing.
//   "\" runs NW->SE and swaps up<->left, down<->right
//   "/" runs NE->SW and swaps up<->right, down<->left
const BACKSLASH: [u8; 4] = [LEFT, DOWN, RIGHT, UP];
const SLASH: [u8; 4] = [RIGHT, UP, LEFT, DOWN];

/// Which two faces of a pyramid carry the mirror, indexed by orientation.
/// Orientation names a corner (NE, SE, SW, NW) and the mirror spans its sides.
const PYRAMID_FACES: [(u8, u8); 4] = [
    (UP, RIGHT),   // o=0 -> NE corner -> north and east faces
    (DOWN, RIGHT), // o=1 -> SE corner
    (DOWN, LEFT),  // o=2 -> SW corner
    (UP, LEFT),    // o=3 -> NW corner
];

/// The diagonal a pyramid or scarab of this orientation lies on.
const fn mirror_for(orient: usize) -> [u8; 4] {
    if orient % 2 == 0 {
        BACKSLASH
    } else {
        SLASH
    }
}

const fn build_laser_table() -> [[i8; 4]; CODE_RANGE] {
    let mut table = [[ABSORB; 4]; CODE_RANGE];

    let mut color = 0u8;
    while color < 2 {
        let mut orient = 0usize;
        while orient < 4 {
            let mirror = mirror_for(orient);

            // Pyramid: reflects off two adjacent faces, dies on the other two.
            let code = encode(PYRAMID, color, orient as u8) as usize;
            let faces = PYRAMID_FACES[orient];
            let reflect_a = FROM_FACE[faces.0 as usize];
            let reflect_b = FROM_FACE[faces.1 as usize];
            let mut dir = 0usize;
            while dir < 4 {
                table[code][dir] = if dir as u8 == reflect_a || dir as u8 == reflect_b {
                    mirror[dir] as i8
                } else {
                    DESTROY
                };
                dir += 1;
            }

            // Scarab: double sided mirror, reflects from every direction and
            // can never be destroyed.
            let code = encode(SCARAB, color, orient as u8) as usize;
            let mut dir = 0usize;
            while dir < 4 {
                table[code][dir] = mirror[dir] as i8;
                dir += 1;
            }

            // Anubis: survives a hit on its front face, dies otherwise.
            let code = encode(ANUBIS, color, orient as u8) as usize;
            let front = FROM_FACE[orient];
            let mut dir = 0usize;
            while dir < 4 {
                table[code][dir] = if dir as u8 == front { ABSORB } else { DESTROY };
                dir += 1;
            }

            // Pharaoh: dies from any direction.
            let code = encode(PHARAOH, color, orient as u8) as usize;
            let mut dir = 0usize;
            while dir < 4 {
                table[code][dir] = DESTROY;
                dir += 1;
            }

            // Sphinx: immune from every direction, including its own beam.
            let code = encode(SPHINX, color, orient as u8) as usize;
            let mut dir = 0usize;
            while dir < 4 {
                table[code][dir] = ABSORB;
                dir += 1;
            }

            orient += 1;
        }
        color += 1;
    }

    table
}

/// `LASER[code][travel_direction]` -> new travel direction, `DESTROY` or `ABSORB`.
pub static LASER: [[i8; 4]; CODE_RANGE] = build_laser_table();

// --------------------------------------------------------------------------
// Rotation legality
// --------------------------------------------------------------------------
// A sphinx has only two legal facings: along its file, or along its rank toward
// the board.  Red sits at the top-left and fires down or right; silver sits at
// the bottom-right and fires up or left.
const SPHINX_FACINGS: [[u8; 2]; 2] = [[DOWN, RIGHT], [UP, LEFT]];

/// Whether rotating this piece 90 degrees yields a legal orientation.
/// Only the sphinx is constrained.
pub const fn can_rotate(code: u8, clockwise: bool) -> bool {
    if piece_type(code) != SPHINX {
        return true;
    }
    let step: u8 = if clockwise { 1 } else { 3 };
    let target = (orientation(code) + step) & 3;
    let facings = SPHINX_FACINGS[piece_color(code) as usize];
    target == facings[0] || target == facings[1]
}

/// Whether this piece may change squares at all.  The sphinx may not.
pub const fn can_move(code: u8) -> bool {
    piece_type(code) != SPHINX
}

/// Whether `mover` may move onto a square holding `occupant`.
///
/// Only a scarab may enter an occupied square, and only to swap with a pyramid
/// or an anubis of either color.
pub const fn can_swap_onto(mover: u8, occupant: u8) -> bool {
    if occupant == EMPTY {
        return true;
    }
    if piece_type(mover) != SCARAB {
        return false;
    }
    let t = piece_type(occupant);
    t == PYRAMID || t == ANUBIS
}
