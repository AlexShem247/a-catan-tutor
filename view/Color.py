from enum import Enum


def rgb_to_ansi(r: int, g: int, b: int) -> str:
    """Convert (R,G,B) to 24-bit ANSI escape sequence."""
    return f"\033[38;2;{r};{g};{b}m"


class Color(Enum):
    GREY = (140, 140, 140)
    GOLD = (220, 170, 25)
    LIME_GREEN = (130, 170, 15)
    DARK_GREEN = (20, 110, 20)
    RED_ORANGE = (180, 35, 35)
    BEIGE = (200, 170, 120)
    BROWN = (140, 70, 25)
    WHITE = (225, 225, 225)

    BLUE = (0, 0, 255)
    RED = (255, 0, 0)
    GREEN = (0, 230, 0)
    YELLOW = (240, 225, 0)

    RESET = "reset"

    def apply(self, text: str) -> str:
        """Return the text wrapped in this RGB colour."""
        if self is Color.RESET:
            return text

        r, g, b = self.value
        ansi = rgb_to_ansi(r, g, b)
        return f"{ansi}{text}\033[0m"

    def ansi(self) -> str:
        """Return ANSI code for this colour."""
        if self is Color.RESET:
            return "\033[0m"
        r, g, b = self.value
        return rgb_to_ansi(r, g, b)


def colorise(text: str, color: Color, bold: bool = False, underline: bool = False) -> str:
    if color is Color.RESET:
        return text

    if hasattr(color, "value"):
        r, g, b = color.value
    else:
        r, g, b = color

    # Build ANSI prefix
    prefix_codes = []
    if bold:
        prefix_codes.append("1")  # bold
    if underline:
        prefix_codes.append("4")  # underline

    prefix_codes.append(f"38;2;{r};{g};{b}")  # RGB foreground
    ansi_prefix = f"\033[{';'.join(prefix_codes)}m"

    return f"{ansi_prefix}{text}\033[0m"


def brighten(color: Color, value: int = 50):
    r, g, b = color.value
    return min(r + value, 255), min(g + value, 255), min(b + value, 255)
