from html import escape
from html.parser import HTMLParser
from urllib.parse import urlparse


ALLOWED_TAGS = {"a", "b", "blockquote", "br", "div", "em", "h1", "h2", "h3", "h4", "hr", "i", "img", "li", "ol", "p", "span", "strong", "u", "ul"}
ALLOWED_ATTRS = {"a": {"href", "target", "rel"}, "img": {"src", "alt"}, "span": {"class"}, "div": {"class"}, "p": {"class"}}


def _safe_url(value):
    parsed = urlparse(value.strip())
    return value if not parsed.scheme or parsed.scheme.lower() in {"http", "https", "mailto"} else ""


class _AnnouncementHTMLSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWED_TAGS:
            return
        allowed = []
        for name, value in attrs:
            if name.lower() not in ALLOWED_ATTRS.get(tag, set()) or value is None:
                continue
            if name.lower() in {"href", "src"}:
                value = _safe_url(value)
                if not value:
                    continue
            if name.lower() == "target" and value != "_blank":
                continue
            allowed.append(f' {name.lower()}="{escape(value, quote=True)}"')
        if tag == "a" and any(name == "target" for name, _ in attrs):
            allowed.append(' rel="noopener noreferrer"')
        self.parts.append(f"<{tag}{''.join(allowed)}>")

    def handle_endtag(self, tag):
        if tag in ALLOWED_TAGS and tag not in {"br", "hr"}:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        self.parts.append(escape(data))


def sanitize_announcement_html(value):
    sanitizer = _AnnouncementHTMLSanitizer()
    sanitizer.feed(value or "")
    return "".join(sanitizer.parts)
