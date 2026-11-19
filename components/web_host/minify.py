from __future__ import annotations

from html.parser import HTMLParser
import importlib.util
import json
import logging
import os
import re
from typing import Any

_LOGGER = logging.getLogger(__name__)

_RJSMIN_REPO = "https://github.com/ndparker/rjsmin.git"
_RJSMIN_REF = "1.3.0"
_RCSSMIN_REPO = "https://github.com/ndparker/rcssmin.git"
_RCSSMIN_REF = "1.3.0"

_MODULE_CACHE: dict[str, Any] = {}

_RAW_WHITESPACE_TAGS = frozenset({"pre", "textarea", "code", "script", "style"})
_JS_SCRIPT_TYPES = frozenset({"", "text/javascript", "application/javascript", "module"})
_JSON_SCRIPT_TYPES = frozenset({"application/json", "application/ld+json"})


def _load_git_module(module_name: str, repo_url: str, ref: str) -> Any | None:
    """Clone/cache a pinned pure-Python repo via ESPHome's git helper and load a module from it."""
    if module_name in _MODULE_CACHE:
        return _MODULE_CACHE[module_name]

    try:
        from esphome import git

        repo_dir, _ = git.clone_or_update(
            url=repo_url,
            ref=ref,
            refresh=None,
            domain="web_host",
        )
        module_path = os.path.join(str(repo_dir), f"{module_name}.py")
        spec = importlib.util.spec_from_file_location(f"web_host_{module_name}", module_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not create module spec for {module_path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _MODULE_CACHE[module_name] = mod
        return mod
    except Exception as err:
        _LOGGER.warning("Could not load %s (%s@%s): %s", module_name, repo_url, ref, err)
        _MODULE_CACHE[module_name] = None
        return None


def minify_js(text: str) -> str:
    """Minify JavaScript using rjsmin if available."""
    mod = _load_git_module("rjsmin", _RJSMIN_REPO, _RJSMIN_REF)
    if mod is None:
        return text
    return mod.jsmin(text)


def minify_css(text: str) -> str:
    """Minify CSS using rcssmin if available."""
    mod = _load_git_module("rcssmin", _RCSSMIN_REPO, _RCSSMIN_REF)
    if mod is None:
        return text
    return mod.cssmin(text)


def minify_json(text: str) -> str:
    """Minify JSON using Python's built-in json module."""
    return json.dumps(json.loads(text), separators=(",", ":"), ensure_ascii=False)


class _HTMLMinifier(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._out: list[str] = []
        self._tag_stack: list[str] = []
        self._script_type: str = ""
        self._raw_buf: list[str] | None = None

    def _in_raw_tag(self) -> bool:
        return any(t in _RAW_WHITESPACE_TAGS for t in self._tag_stack)

    def handle_decl(self, decl: str) -> None:
        self._out.append(f"<!{decl}>")

    def handle_pi(self, data: str) -> None:
        self._out.append(f"<?{data}>")

    def handle_comment(self, data: str) -> None:
        # Preserve IE conditional comments just in case; strip standard comments.
        if data.lstrip().startswith("[if "):
            self._out.append(f"<!--{data}-->")

    def handle_entityref(self, name: str) -> None:
        if self._raw_buf is not None:
            self._raw_buf.append(f"&{name};")
        else:
            self._out.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._raw_buf is not None:
            self._raw_buf.append(f"&#{name};")
        else:
            self._out.append(f"&#{name};")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        self._tag_stack.append(tag_lower)
        start_text = self.get_starttag_text() or f"<{tag}>"
        self._out.append(re.sub(r"\s+", " ", start_text))
        if tag_lower in ("script", "style"):
            self._raw_buf = []
            if tag_lower == "script":
                attr_map = {k.lower(): (v or "").strip().lower() for k, v in attrs}
                self._script_type = attr_map.get("type", "").split(";")[0].strip()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        start_text = self.get_starttag_text() or f"<{tag}/>"
        self._out.append(re.sub(r"\s+", " ", start_text))

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if self._raw_buf is not None and tag_lower in ("script", "style"):
            raw = "".join(self._raw_buf)
            self._raw_buf = None
            if tag_lower == "style":
                self._out.append(minify_css(raw))
            elif self._script_type in _JS_SCRIPT_TYPES:
                self._out.append(minify_js(raw))
            elif self._script_type in _JSON_SCRIPT_TYPES:
                try:
                    self._out.append(minify_json(raw))
                except json.JSONDecodeError:
                    self._out.append(raw)
            else:
                self._out.append(raw)

        if self._tag_stack and self._tag_stack[-1] == tag_lower:
            self._tag_stack.pop()
        self._out.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self._raw_buf is not None:
            self._raw_buf.append(data)
        elif self._in_raw_tag():
            self._out.append(data)
        elif data.strip() == "":
            # Collapse pure-whitespace nodes between tags; keep a single space
            # only if adjacent to text rather than another tag.
            if self._out and not self._out[-1].endswith((">", " ")):
                self._out.append(" ")
        else:
            collapsed = re.sub(r"\s+", " ", data)
            self._out.append(collapsed.strip() if self._out and self._out[-1].endswith(">") else collapsed)

    def result(self) -> str:
        return "".join(self._out)


def minify_html(text: str) -> str:
    """Minify HTML (including inline <style> and <script> blocks)."""
    parser = _HTMLMinifier()
    parser.feed(text)
    parser.close()
    return parser.result()


def minify_content(file_content: bytes, content_type: str, resolved_path: str) -> bytes:
    """Minify supported text assets, returning original bytes on unsupported types or errors."""
    ext = os.path.splitext(resolved_path)[1].lower()
    is_json = content_type == "application/json" or content_type.endswith("+json") or ext in (".json", ".webmanifest")
    is_html = content_type == "text/html" or ext in (".html", ".htm")
    is_css = content_type == "text/css" or ext == ".css"
    is_js = content_type in ("application/javascript", "text/javascript") or ext == ".js"

    if not (is_json or is_html or is_css or is_js):
        return file_content

    try:
        text = file_content.decode("utf-8")
        if is_json:
            minified = minify_json(text)
        elif is_html:
            minified = minify_html(text)
        elif is_css:
            minified = minify_css(text)
        else:
            minified = minify_js(text)
        return minified.encode("utf-8")
    except Exception as err:
        _LOGGER.warning("Failed to minify '%s': %s", resolved_path, err)
        return file_content
