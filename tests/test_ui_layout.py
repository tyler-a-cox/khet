"""Static checks on the browser UI's markup, aimed at the phone case.

There is no browser here, so these do not prove the page *looks* right. What
they do prove is the set of things that were actually broken on an iPhone and
would silently break again: a fixed-width board that cannot shrink, form
controls small enough to trigger iOS Safari's focus-zoom, hover rules that latch
on a touchscreen, and rotation controls too small to hit.

Each assertion corresponds to a specific failure, named in its message.
"""

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).parent.parent / "python" / "khet" / "ui" / "static"
PAGE = (STATIC / "index.html").read_text()

# The board's intrinsic size, from its viewBox.
VIEW_W, VIEW_H = 684, 560
CELL = 62

#: iPhone 11 in portrait. The narrowest thing that has to work.
PHONE_CSS_WIDTH = 414


def style_block():
    return re.search(r"<style>(.*?)</style>", PAGE, re.S).group(1)


def test_viewport_allows_scaling_and_reports_safe_areas():
    viewport = re.search(r'<meta name="viewport" content="([^"]+)"', PAGE).group(1)
    assert "width=device-width" in viewport
    assert "viewport-fit=cover" in viewport, "safe-area insets report 0 without it"
    # Locking zoom is an accessibility regression and would also remove the only
    # escape hatch on a board this dense.
    assert "maximum-scale" not in viewport
    assert "user-scalable=no" not in viewport


def test_board_svg_has_no_fixed_pixel_size():
    svg = re.search(r"<svg id=\"board\"[^>]*>", PAGE).group(0)
    assert 'viewBox="0 0 {} {}"'.format(VIEW_W, VIEW_H) in svg
    # This is the original bug: width="684" made the board wider than the phone
    # and the right-hand files were cut off.
    assert "width=" not in svg, "a width attribute overrides the CSS and stops it scaling"
    assert "height=" not in svg
    assert re.search(r"#board\s*\{[^}]*width:\s*100%", style_block())
    assert re.search(r"#board\s*\{[^}]*height:\s*auto", style_block())


def test_board_wrapper_can_shrink_below_its_desktop_width():
    wrap = re.search(r"#board-wrap\s*\{(.*?)\}", style_block(), re.S).group(1)
    assert "max-width: 100%" in wrap, "without this the wrapper keeps its 706px width"
    # 684 board + 2x10 padding + 2x1 border, so desktop is pixel-identical.
    assert "width: 706px" in wrap


def test_form_controls_are_large_enough_to_stop_ios_zooming():
    # iOS Safari zooms the page in when a control with text under 16px takes
    # focus, and does not zoom back out - leaving the board cropped for the rest
    # of the game.
    phone = re.search(
        r"@media \(max-width: 760px\) \{(.*?)\n  \}", style_block(), re.S
    ).group(1)
    controls = re.search(r"select, input\[type=number\]\s*\{([^}]*)\}", phone).group(1)
    size = int(re.search(r"font-size:\s*(\d+)px", controls).group(1))
    assert size >= 16, "iOS zooms on focus below 16px"


def test_hover_rules_are_behind_a_hover_query():
    # A :hover rule on a touchscreen latches after the tap and stays lit.
    for selector in ("button:hover", "button.primary:hover", ".rotbtn:hover"):
        for match in re.finditer(re.escape(selector), style_block()):
            before = style_block()[: match.start()]
            assert "@media (hover: hover)" in before.rsplit("}", 1)[-1] or \
                   "(hover: hover)" in before[-400:], \
                   "{} is not inside a (hover: hover) query".format(selector)


def test_rotation_buttons_are_thumb_sized_on_a_touchscreen():
    """Rotation is mandatory in Khet - the sphinx is aimed only by rotating.

    The buttons are drawn in viewBox units, so their size on screen depends on
    how far the board has been scaled down. At iPhone width the desktop size
    works out around 17 CSS px, which is not hittable.
    """
    coarse = re.search(r"COARSE\s*\n?\s*\?\s*\{([^}]*)\}", PAGE).group(1)
    radius = int(re.search(r"radius:\s*(\d+)", coarse).group(1))

    # The transparent hit circle is what actually receives the tap.
    hit_padding = int(re.search(r"r:\s*ROT\.radius \+ (\d+)", PAGE).group(1))
    hit_diameter_units = 2 * (radius + hit_padding)

    scale = PHONE_CSS_WIDTH / VIEW_W
    hit_css_px = hit_diameter_units * scale
    assert hit_css_px >= 30, (
        "rotation hit target is {:.0f} CSS px at iPhone width".format(hit_css_px)
    )

    # And it must still be a transparent fill, not `none`, or it takes no taps.
    assert re.search(r"r:\s*ROT\.radius \+ \d+,\s*fill:\s*\"transparent\"", PAGE)


def test_touch_help_text_does_not_mention_keys():
    help_html = re.search(r'<div class="help">(.*?)</div>', PAGE, re.S).group(1)
    assert 'class="touch-only"' in help_html
    assert 'class="mouse-only"' in help_html
    # Q/E/Esc only exist with a keyboard, so they belong in the mouse variant.
    for key in ("<b>Q</b>", "<b>Esc</b>"):
        index = help_html.index(key)
        opening = help_html.rfind("<span", 0, index)
        assert 'class="mouse-only"' in help_html[opening:index], \
            "{} shown to touch users".format(key)


@pytest.mark.parametrize("width", [320, 375, 390, 414, 428])
def test_board_fits_common_phone_widths(width):
    """The board plus the page's own padding must fit the viewport."""
    body_padding = 12 * 2       # the <=760px rule
    wrap_chrome = 6 * 2 + 2     # padding + border, also from that rule
    available = width - body_padding - wrap_chrome
    assert available > 0
    scale = available / VIEW_W
    cell_px = CELL * scale
    # Not a guarantee of comfort, just that squares stay a plausible target.
    assert cell_px >= 24, "{}px cells at {}px wide".format(round(cell_px), width)


def test_landscape_cap_keeps_the_board_on_screen():
    landscape = re.search(
        r"@media \(orientation: landscape\)[^{]*\{(.*?)\n  \}", style_block(), re.S
    ).group(1)
    ratio = float(re.search(r"\* ([\d.]+) \+", landscape).group(1))
    # The width cap has to follow the board's own aspect ratio or it distorts
    # or overflows; 684/560 = 1.2214.
    assert abs(ratio - VIEW_W / VIEW_H) < 0.01
    assert "dvh" in landscape, "vh alone jumps as Safari's toolbar collapses"
    assert "100vh" in landscape, "dvh needs a fallback for iOS before 15.4"
