import asyncio
import gzip
import importlib
import json
import logging
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.const import (
    CONF_ID,
    CONF_PATH,
    CONF_REF,
    CONF_TYPE,
    CONF_URL,
    TYPE_GIT,
    TYPE_LOCAL,
)
from esphome.core import CORE
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPONENTS_DIR = REPO_ROOT / "components"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

if str(COMPONENTS_DIR) not in sys.path:
    sys.path.insert(0, str(COMPONENTS_DIR))

web_host = importlib.import_module("web_host")


@pytest.fixture(autouse=True)
def reset_esphome_core(tmp_path):
    """Reset ESPHome CORE state around every test."""
    CORE.reset()
    CORE.config_path = tmp_path / "test.yaml"
    CORE.build_path = tmp_path / "build"
    CORE.config = {}
    yield
    CORE.reset()


def _make_esp_key(name: str, document: str):
    """Create a string key carrying esp_range metadata like ESPHome's YAML loader."""

    class KeyWithRange(str):
        pass

    key = KeyWithRange(name)
    key.esp_range = SimpleNamespace(start_mark=SimpleNamespace(document=document))
    return key


class TestDetectContentType:
    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("index.html", "text/html"),
            ("page.htm", "text/html"),
            ("INDEX.HTML", "text/html"),
            ("styles.css", "text/css"),
            ("app.js", "application/javascript"),
            ("data.json", "application/json"),
            ("manifest.webmanifest", "application/json"),
            ("logo.png", "image/png"),
            ("favicon.ico", "image/x-icon"),
            ("icon.svg", "image/svg+xml"),
            ("robots.txt", "text/plain"),
            ("firmware.bin", "application/octet-stream"),
            ("no_extension", "application/octet-stream"),
        ],
    )
    def test_detect_content_type(self, filename, expected):
        assert web_host.detect_content_type(filename) == expected


class TestPathResolution:
    def test_resolve_source_path_local_relative_and_absolute(self, tmp_path):
        CORE.config_path = tmp_path / "device.yaml"
        assert web_host.resolve_source_path({CONF_TYPE: TYPE_LOCAL, CONF_PATH: "assets"}) == str(
            tmp_path / "assets"
        )
        abs_dir = str(tmp_path / "abs_assets")
        assert web_host.resolve_source_path({CONF_TYPE: TYPE_LOCAL, CONF_PATH: abs_dir}) == abs_dir

    def test_resolve_source_path_git(self, tmp_path):
        fake_repo = tmp_path / "cloned_repo"
        with patch("esphome.git.clone_or_update", return_value=(fake_repo, None)) as mock_clone:
            resolved = web_host.resolve_source_path(
                {
                    CONF_TYPE: TYPE_GIT,
                    CONF_URL: "https://github.com/example/repo.git",
                    CONF_REF: "main",
                }
            )
            assert resolved == str(fake_repo)
            mock_clone.assert_called_once()

            resolved_sub = web_host.resolve_source_path(
                {
                    CONF_TYPE: TYPE_GIT,
                    CONF_URL: "https://github.com/example/repo.git",
                    CONF_PATH: "dist",
                }
            )
            assert resolved_sub == str(fake_repo / "dist")

    def test_resolve_file_path_precedence(self, tmp_path):
        CORE.config_path = tmp_path / "device.yaml"
        pkg_dir = tmp_path / "packages"
        pkg_dir.mkdir()
        pkg_file = pkg_dir / "pkg_only.txt"
        pkg_file.write_text("from pkg", encoding="utf-8")

        root_file = tmp_path / "root_only.txt"
        root_file.write_text("from root", encoding="utf-8")

        config_with_range = {_make_esp_key("files", str(pkg_dir / "pkg.yaml")): []}

        # 1. Explicit source_dir is strict (no fallback)
        assert web_host.resolve_file_path(config_with_range, "a.html", str(tmp_path / "src")) == str(
            tmp_path / "src" / "a.html"
        )

        # 2. Omitted source_dir resolves relative to declaring YAML dir when file exists there
        assert web_host.resolve_file_path(config_with_range, "pkg_only.txt", None) == str(pkg_file)

        # 3. Omitted source_dir falls back to CORE.config_dir when not in declaring YAML dir
        assert web_host.resolve_file_path(config_with_range, "root_only.txt", None) == str(root_file)

        # 4. Absolute path without source_dir is preserved
        abs_file = str(tmp_path / "absolute.txt")
        assert web_host.resolve_file_path(config_with_range, abs_file, None) == abs_file


class TestSchemaValidation:
    def test_valid_config_with_defaults_and_overrides(self, tmp_path):
        CORE.config_path = tmp_path / "device.yaml"
        asset = tmp_path / "index.html"
        asset.write_text("<h1>Hello</h1>", encoding="utf-8")

        validated = web_host.CONFIG_SCHEMA(
            {
                "files": [
                    {
                        "id": "web_idx",
                        "file": "index.html",
                        "url": "/",
                    },
                    {
                        "id": "web_custom",
                        "file": "index.html",
                        "url": "/plain",
                        "content_type": "text/plain",
                        "minify": False,
                    },
                ]
            }
        )
        assert validated[web_host.CONF_MINIFY] is True
        assert len(validated[web_host.CONF_FILES]) == 2
        assert validated[web_host.CONF_FILES][1][web_host.CONF_CONTENT_TYPE] == "text/plain"
        assert validated[web_host.CONF_FILES][1][web_host.CONF_MINIFY] is False

    def test_missing_file_raises_invalid(self, tmp_path):
        CORE.config_path = tmp_path / "device.yaml"
        with pytest.raises(cv.Invalid, match="Resource file not found"):
            web_host.CONFIG_SCHEMA(
                {
                    "files": [
                        {
                            "id": "missing_asset",
                            "file": "does_not_exist.html",
                            "url": "/",
                        }
                    ]
                }
            )


class TestMdiInlining:
    def test_esphome_mdi_import_and_path_extraction(self, tmp_path):
        """Verify ESPHome's internal download_gh_svg & SOURCE_MDI import still works."""
        svg_file = tmp_path / "fan.svg"
        svg_file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            '<path d="M12,11A1,1 0 0,0 11,12Z" /></svg>',
            encoding="utf-8",
        )

        # Verify the upstream import path itself resolves in the current ESPHome version
        try:
            from esphome.components.file.image import download_gh_svg, SOURCE_MDI  # noqa: F401

            target = "esphome.components.file.image.download_gh_svg"
        except ImportError:
            from esphome.components.image import download_gh_svg, SOURCE_MDI  # noqa: F401

            target = "esphome.components.image.download_gh_svg"

        with patch(target, return_value=str(svg_file)) as mock_dl:
            # Also checks icon name sanitization (only alnum, '-', '_')
            path_data = web_host.get_mdi_path("Fan!@#")
            assert path_data == "M12,11A1,1 0 0,0 11,12Z"
            mock_dl.assert_called_once()
            assert mock_dl.call_args[0][0] == "fan"

    def test_mdi_missing_path_raises_runtime_error(self, tmp_path):
        bad_svg = tmp_path / "empty.svg"
        bad_svg.write_text("<svg></svg>", encoding="utf-8")

        try:
            from esphome.components.file.image import download_gh_svg  # noqa: F401

            target = "esphome.components.file.image.download_gh_svg"
        except ImportError:
            target = "esphome.components.image.download_gh_svg"

        with patch(target, return_value=str(bad_svg)):
            with pytest.raises(RuntimeError, match="Icon path not found"):
                web_host.get_mdi_path("empty")

        with patch(target, side_effect=OSError("offline")):
            with pytest.raises(RuntimeError, match="Failed to fetch or parse MDI icon"):
                web_host.get_mdi_path("home")


def _extract_generated_payload(header_path: Path):
    """Parse generated C++ header and return (byte_list, declared_size)."""
    text = header_path.read_text(encoding="utf-8")
    assert '#include "esphome/core/progmem.h"' in text
    assert "PROGMEM" in text
    arr_match = re.search(r"PROGMEM\s*=\s*\{([^}]*)\};", text, re.DOTALL)
    size_match = re.search(r"_WEB_HOST_DATA_SIZE\s*=\s*(\d+);", text)
    assert arr_match is not None
    assert size_match is not None
    hex_items = [x.strip() for x in arr_match.group(1).split(",") if x.strip()]
    payload = bytes(int(x, 16) for x in hex_items)
    declared_size = int(size_match.group(1))
    assert len(payload) == declared_size
    return payload, declared_size


class TestToCodeGeneration:
    def _run_to_code(self, config):
        registered = []

        async def fake_register_component(var, cfg):
            registered.append((var, cfg))

        with (
            patch.object(cg, "add_global") as mock_add_global,
            patch.object(cg, "new_Pvariable", side_effect=lambda *args: args) as mock_new_pvar,
            patch.object(cg, "register_component", side_effect=fake_register_component),
        ):
            asyncio.run(web_host.to_code(config))
            return mock_add_global, mock_new_pvar, registered

    def test_html_version_mdi_and_gzip(self, tmp_path):
        CORE.config_path = tmp_path / "device.yaml"
        CORE.config = {"esphome": {"project": {"version": "2.5.0"}}}

        html_file = tmp_path / "index.html"
        html_file.write_text(
            "<html><body>"
            "<span>v${version}</span>"
            '<svg class="i" data-mdi="home"></svg>'
            '<svg class="i" data-mdi="broken"></svg>'
            "<p>" + ("repeat-" * 40) + "</p>"
            "</body></html>",
            encoding="utf-8",
        )

        config = web_host.CONFIG_SCHEMA(
            {
                "files": [
                    {
                        "id": "web_idx",
                        "file": "index.html",
                        "url": "/",
                    }
                ]
            }
        )

        def fake_mdi(name):
            if name == "home":
                return "M10,20V14H14V20Z"
            raise RuntimeError("network unavailable")

        with patch.object(web_host, "get_mdi_path", side_effect=fake_mdi):
            mock_add_global, mock_new_pvar, registered = self._run_to_code(config)

        assert len(registered) == 1
        mock_add_global.assert_called_once()
        # Check new_Pvariable args: (id, url, content_type, data_expr, size_expr, use_gzip)
        pvar_args = mock_new_pvar.call_args[0]
        assert pvar_args[1] == "/"
        assert pvar_args[2] == "text/html"
        assert pvar_args[5] is True  # gzip applied

        header_path = CORE.build_path / "src" / "web_idx_web_host.h"
        payload, _ = _extract_generated_payload(header_path)
        first_header_text = header_path.read_text(encoding="utf-8")

        # Re-run to verify deterministic gzip (mtime=0) produces byte-identical output
        with patch.object(web_host, "get_mdi_path", side_effect=fake_mdi):
            self._run_to_code(config)
        assert header_path.read_text(encoding="utf-8") == first_header_text

        decompressed = gzip.decompress(payload).decode("utf-8")

        assert "v2.5.0" in decompressed
        assert "${version}" not in decompressed
        assert '<svg class="i" data-mdi="home"><path d="M10,20V14H14V20Z"/></svg>' in decompressed
        # Failed MDI icon falls back gracefully to original tag
        assert '<svg class="i" data-mdi="broken"></svg>' in decompressed

    def test_html_version_defaults_to_unknown(self, tmp_path):
        CORE.config_path = tmp_path / "device.yaml"
        CORE.config = {}  # No esphome.project.version

        html_file = tmp_path / "ver.html"
        html_file.write_text("<div>${version}</div>", encoding="utf-8")

        config = web_host.CONFIG_SCHEMA(
            {"files": [{"id": "web_ver", "file": "ver.html", "url": "/ver"}]}
        )
        self._run_to_code(config)

        header_path = CORE.build_path / "src" / "web_ver_web_host.h"
        payload, _ = _extract_generated_payload(header_path)
        # Tiny HTML might not gzip; handle either
        try:
            content = gzip.decompress(payload).decode("utf-8")
        except gzip.BadGzipFile:
            content = payload.decode("utf-8")
        assert content == "<div>unknown</div>"

    def test_json_minification_and_overrides(self, tmp_path):
        CORE.config_path = tmp_path / "device.yaml"
        pretty_json = '{\n  "a": 1,\n  "b": "hello"\n}\n'
        (tmp_path / "a.json").write_text(pretty_json, encoding="utf-8")
        (tmp_path / "b.webmanifest").write_text(pretty_json, encoding="utf-8")
        (tmp_path / "c.json").write_text(pretty_json, encoding="utf-8")
        (tmp_path / "bad.json").write_text("{not valid json", encoding="utf-8")

        config = web_host.CONFIG_SCHEMA(
            {
                "minify": True,
                "files": [
                    {"id": "j_min", "file": "a.json", "url": "/a.json"},
                    {
                        "id": "j_manifest",
                        "file": "b.webmanifest",
                        "url": "/b.webmanifest",
                        "content_type": "application/manifest+json",
                    },
                    {"id": "j_raw", "file": "c.json", "url": "/c.json", "minify": False},
                    {"id": "j_bad", "file": "bad.json", "url": "/bad.json"},
                ],
            }
        )
        self._run_to_code(config)

        def read_asset(var_id):
            payload, _ = _extract_generated_payload(CORE.build_path / "src" / f"{var_id}_web_host.h")
            try:
                return gzip.decompress(payload).decode("utf-8")
            except gzip.BadGzipFile:
                return payload.decode("utf-8")

        assert read_asset("j_min") == '{"a":1,"b":"hello"}'
        assert read_asset("j_manifest") == '{"a":1,"b":"hello"}'
        assert read_asset("j_raw") == pretty_json
        assert read_asset("j_bad") == "{not valid json"

    def test_gzip_skipped_when_compressed_not_smaller(self, tmp_path):
        CORE.config_path = tmp_path / "device.yaml"
        raw_bytes = b"TINY"
        (tmp_path / "tiny.bin").write_bytes(raw_bytes)

        config = web_host.CONFIG_SCHEMA(
            {"files": [{"id": "tiny_id", "file": "tiny.bin", "url": "/tiny"}]}
        )
        _, mock_new_pvar, _ = self._run_to_code(config)

        pvar_args = mock_new_pvar.call_args[0]
        assert pvar_args[2] == "application/octet-stream"
        assert pvar_args[5] is False  # use_gzip must be False

        payload, size = _extract_generated_payload(CORE.build_path / "src" / "tiny_id_web_host.h")
        assert payload == raw_bytes
        assert size == len(raw_bytes)

    def test_non_utf8_html_handled_gracefully(self, tmp_path):
        CORE.config_path = tmp_path / "device.yaml"
        raw_bytes = b"\xff\xfe\x00\x01<html>"
        (tmp_path / "bad_enc.html").write_bytes(raw_bytes)

        config = web_host.CONFIG_SCHEMA(
            {"files": [{"id": "bad_enc", "file": "bad_enc.html", "url": "/bad"}]}
        )
        self._run_to_code(config)

        payload, _ = _extract_generated_payload(CORE.build_path / "src" / "bad_enc_web_host.h")
        assert payload == raw_bytes or gzip.decompress(payload) == raw_bytes


class TestHtmlCssJsMinification:
    def test_html_strips_comments_and_preserves_pre_and_entities(self):
        minify_mod = importlib.import_module("web_host.minify")
        html = (
            "<!DOCTYPE html>\n"
            "<html>\n"
            "  <!-- strip this comment -->\n"
            "  <body>\n"
            "    <p>Temp: 72&deg;F</p>\n"
            "    <pre>  keep   spacing\n  here  </pre>\n"
            "  </body>\n"
            "</html>\n"
        )
        out = minify_mod.minify_html(html)
        assert "strip this comment" not in out
        assert "&deg;" in out
        assert "<pre>  keep   spacing\n  here  </pre>" in out
        assert "<!DOCTYPE html><html><body><p>Temp: 72&deg;F</p>" in out

    def test_css_and_js_minification(self):
        minify_mod = importlib.import_module("web_host.minify")
        css = "/* comment */\nbody {\n  color: #fff;\n  margin: 0px;\n}\n"
        js = "// line comment\nfunction add(a, b) {\n  return a + b;\n}\n"
        min_css = minify_mod.minify_css(css)
        min_js = minify_mod.minify_js(js)
        assert "comment" not in min_css
        assert "body{color:#fff;margin:0px}" in min_css or "body{color:#fff;margin:0}" in min_css
        assert "line comment" not in min_js
        assert "function add(a,b){return a+b;}" in min_js

    def test_offline_git_fallback_returns_original(self):
        minify_mod = importlib.import_module("web_host.minify")
        minify_mod._MODULE_CACHE.clear()
        js = "// comment\nconst x = 1;\n"
        css = "/* comment */\nbody { color: red; }\n"
        with patch("esphome.git.clone_or_update", side_effect=RuntimeError("offline")):
            assert minify_mod.minify_js(js) == js
            assert minify_mod.minify_css(css) == css
        minify_mod._MODULE_CACHE.clear()
