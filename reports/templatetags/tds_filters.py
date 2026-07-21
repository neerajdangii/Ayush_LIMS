from django import template
import re

register = template.Library()


@register.filter(is_safe=True)
def strip_hfb(value):
    """Strip <header>, <footer> and outer <body> wrappers from HTML.

    This keeps inner content but removes header/footer blocks which
    should only be used for ADS documents.
    """
    if not value:
        return value

    s = str(value)

    # If there's a <body> wrapper, keep its inner content
    body_match = re.search(r"<body\b[^>]*>(.*)</body>", s, flags=re.IGNORECASE | re.DOTALL)
    if body_match:
        s = body_match.group(1)

    # Remove header and footer blocks entirely
    s = re.sub(r"<header\b[^>]*>.*?</header>", "", s, flags=re.IGNORECASE | re.DOTALL)
    s = re.sub(r"<footer\b[^>]*>.*?</footer>", "", s, flags=re.IGNORECASE | re.DOTALL)

    return s

