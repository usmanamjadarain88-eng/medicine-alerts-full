from theme.tokens import BG_CARD, BORDER, NEON_GREEN, LOW_STOCK_YELLOW, LOW_STOCK_RED, RADIUS

CARD_STYLE = f"""
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: {RADIUS};
"""
CARD_STYLE_GLOW = f"""
    background-color: {BG_CARD};
    border: 1px solid {NEON_GREEN};
    border-radius: {RADIUS};
"""
CARD_STYLE_LOW = f"""
    background-color: {BG_CARD};
    border: 1px solid {LOW_STOCK_YELLOW};
    border-radius: {RADIUS};
"""
CARD_STYLE_CRITICAL = f"""
    background-color: {BG_CARD};
    border: 1px solid {LOW_STOCK_RED};
    border-radius: {RADIUS};
"""
