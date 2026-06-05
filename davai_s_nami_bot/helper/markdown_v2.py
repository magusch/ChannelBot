import re

# Telegram MarkdownV2 special characters
_SPECIAL_CHARS = r'_*[]()~`>#+-=|{}.!'


def escape_v2(text: str) -> str:
    """Escape text for Telegram MarkdownV2 format."""
    if not text:
        return ''
    return re.sub(f'([{re.escape(_SPECIAL_CHARS)}])', r'\\\1', str(text))


def escape_v2_url(url: str) -> str:
    """Escape URL for use inside MarkdownV2 link parentheses.

    Only `)` and `\\` need escaping inside `(...)` of a link.
    """
    if not url:
        return ''
    return url.replace('\\', '\\\\').replace(')', '\\)')
