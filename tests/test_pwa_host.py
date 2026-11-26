import asyncio
import gzip
import importlib
import json
import re
import struct
import sys
import zlib
from pathlib import Path
from unittest.mock import patch

import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.core import CORE
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPONENTS_DIR = REPO_ROOT / "components"

if str(COMPONENTS_DIR) not in sys.path:
    sys.path.insert(0, str(COMPONENTS_DIR))

web_host = importlib.import_module("web_host")
pwa_host = importlib.import_module("pwa_host")


@pytest.fixture(autouse=True)
def reset_esphome_core(tmp_path):
    """Reset ESPHome CORE state around every test."""
    CORE.reset()
    CORE.config_path = tmp_path / "test.yaml"
    CORE.build_path = tmp_path / "build"
    CORE.config = {"esphome": {"name": "test-device", "friendly_name": "Test Device", "project": {"version": "1.0.0"}}}
    yield
    CORE.reset()


def _make_png(width: int, height: int) -> bytes:
    """Create a minimal valid RGBA PNG with exact IHDR dimensions."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    raw_scanlines = b"".join(b"\x00" + (b"\x00\x00\x00\x00" * width) for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw_scanlines))
        + chunk(b"IEND", b"")
    )


def _extract_payload(header_path: Path) -> bytes:
    text = header_path.read_text(encoding="utf-8")
    arr_match = re.search(r"PROGMEM\s*=\s*\{([^}]*)\};", text, re.DOTALL)
    assert arr_match is not None
    hex_items = [x.strip() for x in arr_match.group(1).split(",") if x.strip()]
    payload = bytes(int(x, 16) for x in hex_items)
    try:
        return gzip.decompress(payload)
    except gzip.BadGzipFile:
        return payload


def _run_to_code(config):
    registered = []

    async def fake_register_component(var, cfg):
        registered.append((var, cfg))

    with (
        patch.object(cg, "add_global"),
        patch.object(cg, "new_Pvariable", side_effect=lambda *args: args) as mock_new_pvar,
        patch.object(cg, "register_component", side_effect=fake_register_component),
    ):
        asyncio.run(pwa_host.to_code(config))
        return mock_new_pvar, registered


class TestBasePathAndUrlHelpers:
    def test_validate_base_path_normalization(self):
        assert pwa_host.validate_base_path("/") == "/"
        assert pwa_host.validate_base_path("") == "/"
        assert pwa_host.validate_base_path("/level") == "/level/"
        assert pwa_host.validate_base_path("level") == "/level/"
        assert pwa_host.validate_base_path("/apps/rv/level/") == "/apps/rv/level/"

    @pytest.mark.parametrize("bad", ["/../etc", "/level?x=1", "/level#hash", "/level\nX"])
    def test_validate_base_path_rejects_invalid(self, bad):
        with pytest.raises(cv.Invalid):
            pwa_host.validate_base_path(bad)

    def test_join_base_url(self):
        assert pwa_host.join_base_url("/", "/thermostat") == ("/thermostat", "thermostat")
        assert pwa_host.join_base_url("/", "/") == ("/", "./")
        assert pwa_host.join_base_url("/level/", "level") == ("/level/level", "level")
        assert pwa_host.join_base_url("/level/", "/") == ("/level/", "./")


class TestPwaHostValidation:
    def test_requires_files_or_sources(self):
        with pytest.raises(cv.Invalid, match="at least one file"):
            pwa_host.CONFIG_SCHEMA({"name": "Empty"})

    def test_rejects_duplicate_urls_within_pwa(self, tmp_path):
        (tmp_path / "a.html").write_text("<h1>A</h1>", encoding="utf-8")
        (tmp_path / "b.html").write_text("<h1>B</h1>", encoding="utf-8")
        with pytest.raises(cv.Invalid, match="Duplicate URL"):
            pwa_host.CONFIG_SCHEMA(
                {
                    "base_path": "/app",
                    "files": [
                        {"file": "a.html", "url": "index"},
                        {"file": "b.html", "url": "/index"},
                    ],
                }
            )

    def test_subpath_requires_landing_page_or_html(self, tmp_path):
        (tmp_path / "data.json").write_text("{}", encoding="utf-8")
        with pytest.raises(cv.Invalid, match="landing_page"):
            pwa_host.CONFIG_SCHEMA(
                {
                    "base_path": "/api-app",
                    "files": [{"file": "data.json", "url": "data.json"}],
                }
            )

    def test_pwa_host_only_yaml_autoloads_web_host_without_error(self, tmp_path):
        from esphome.config import read_config
        from esphome.loader import clear_component_meta_finders

        assert web_host.MULTI_CONF_NO_DEFAULT is True
        assert pwa_host.MULTI_CONF_NO_DEFAULT is True

        (tmp_path / "index.html").write_text("<html>Only PWA</html>", encoding="utf-8")
        yaml_path = tmp_path / "pwa_only.yaml"
        yaml_path.write_text(
            f"""esphome:
  name: pwa-only-test

esp32:
  board: esp32dev
  framework:
    type: esp-idf

external_components:
  - source:
      type: local
      path: {COMPONENTS_DIR}
    components: [web_host, pwa_host]

wifi:
  ssid: "TestSSID"
  password: "TestPassword"

web_server:
  local: true

pwa_host:
  files:
    - file: "index.html"
      url: "/app"
""",
            encoding="utf-8",
        )

        CORE.config_path = yaml_path
        try:
            validated = read_config({})
            assert validated is not None
            assert validated.errors == []
            assert validated.get("web_host") == []
            assert len(validated.get("pwa_host", [])) == 1
        finally:
            clear_component_meta_finders()


class TestPwaHostCodegen:
    def test_single_source_generates_manifest_and_sw(self, tmp_path):
        CORE.config_path = tmp_path / "device.yaml"
        (tmp_path / "thermostat.html").write_text("<html><body>Hi</body></html>", encoding="utf-8")
        (tmp_path / "app.js").write_text("console.log('app');", encoding="utf-8")
        (tmp_path / "apple-touch-icon.png").write_bytes(_make_png(180, 180))

        config = pwa_host.CONFIG_SCHEMA(
            {
                "name": "HyHeat",
                "short_name": "HyHeat",
                "start_url": "thermostat",
                "theme_color": "#0c0c0e",
                "background_color": "#0c0c0e",
                "icons": [
                    {
                        "file": "apple-touch-icon.png",
                        "url": "apple-touch-icon.png",
                        "purpose": "any maskable",
                    }
                ],
                "files": [
                    {
                        "file": "thermostat.html",
                        "url": "/thermostat",
                        "aliases": ["thermostat.html"],
                    },
                    {
                        "file": "app.js",
                        "url": "/app.js",
                        "strategy": "stale_while_revalidate",
                    },
                ],
            }
        )

        mock_new_pvar, _ = _run_to_code(config)
        calls = [call.args for call in mock_new_pvar.call_args_list]
        by_url = {args[1]: args for args in calls}

        assert "/thermostat" in by_url
        assert "/app.js" in by_url
        assert "/apple-touch-icon.png" in by_url
        assert "/manifest.webmanifest" in by_url
        assert "/sw.js" in by_url
        assert "/" not in by_url  # Root '/' stays free for ESPHome dashboard

        manifest_args = by_url["/manifest.webmanifest"]
        assert manifest_args[2] == "application/manifest+json"
        manifest_json = json.loads(_extract_payload(CORE.build_path / "src" / f"{manifest_args[0]}_web_host.h"))
        assert manifest_json == {
            "name": "HyHeat",
            "short_name": "HyHeat",
            "start_url": "thermostat",
            "scope": "./",
            "display": "standalone",
            "theme_color": "#0c0c0e",
            "background_color": "#0c0c0e",
            "icons": [
                {
                    "src": "apple-touch-icon.png",
                    "type": "image/png",
                    "purpose": "any maskable",
                    "sizes": "180x180",
                }
            ],
        }

        sw_args = by_url["/sw.js"]
        assert sw_args[2] == "application/javascript"
        assert sw_args[6] == "no-cache"
        sw_js = _extract_payload(CORE.build_path / "src" / f"{sw_args[0]}_web_host.h").decode("utf-8")
        assert "hyheat-" in sw_js
        assert "k.startsWith(CACHE_PREFIX)" in sw_js
        assert re.search(r"for\s*\(const url of PRECACHE_URLS\)", sw_js) is not None
        assert '"stale_while_revalidate"' in sw_js
        assert '"thermostat.html"' in sw_js

    def test_sw_cache_hash_changes_when_asset_changes(self, tmp_path):
        CORE.config_path = tmp_path / "device.yaml"
        html = tmp_path / "index.html"
        html.write_text("<h1>v1</h1>", encoding="utf-8")

        config = pwa_host.CONFIG_SCHEMA(
            {
                "name": "HashTest",
                "files": [{"file": "index.html", "url": "index"}],
            }
        )
        mock_1, _ = _run_to_code(config)
        sw_id_1 = next(c.args[0] for c in mock_1.call_args_list if c.args[1] == "/sw.js")
        sw_1 = _extract_payload(CORE.build_path / "src" / f"{sw_id_1}_web_host.h").decode("utf-8")

        html.write_text("<h1>v2</h1>", encoding="utf-8")
        config_2 = pwa_host.CONFIG_SCHEMA(
            {
                "name": "HashTest",
                "files": [{"file": "index.html", "url": "index"}],
            }
        )
        mock_2, _ = _run_to_code(config_2)
        sw_id_2 = next(c.args[0] for c in mock_2.call_args_list if c.args[1] == "/sw.js")
        sw_2 = _extract_payload(CORE.build_path / "src" / f"{sw_id_2}_web_host.h").decode("utf-8")

        match_1 = re.search(r"hashtest-([0-9a-f]{8})", sw_1)
        match_2 = re.search(r"hashtest-([0-9a-f]{8})", sw_2)
        assert match_1 is not None and match_2 is not None
        assert match_1.group(1) != match_2.group(1)

    def test_multi_source_subpath_landing_alias_and_redirect(self, tmp_path):
        CORE.config_path = tmp_path / "device.yaml"
        local_dir = tmp_path / "local"
        extra_dir = tmp_path / "extra"
        local_dir.mkdir()
        extra_dir.mkdir()
        (local_dir / "level.html").write_text("<html>Level</html>", encoding="utf-8")
        (extra_dir / "decoder.js").write_text("var d=1;", encoding="utf-8")

        config = pwa_host.CONFIG_SCHEMA(
            {
                "id": "rv_level",
                "base_path": "/level",
                "name": "RV Level",
                "landing_page": "level",
                "sources": [
                    {
                        "source": str(local_dir),
                        "files": [{"file": "level.html", "url": "level"}],
                    },
                    {
                        "source": str(extra_dir),
                        "files": [
                            {
                                "file": "decoder.js",
                                "url": "decoder.js",
                                "strategy": "cache_first",
                                "precache": False,
                            }
                        ],
                    },
                ],
            }
        )

        mock_new_pvar, _ = _run_to_code(config)
        calls = [call.args for call in mock_new_pvar.call_args_list]
        web_assets = {args[1]: args for args in calls if len(args) > 3}
        redirects = {args[1]: args[2] for args in calls if len(args) == 3}

        assert "/level/level" in web_assets
        assert "/level/" in web_assets
        assert "/level/decoder.js" in web_assets
        assert "/level/manifest.webmanifest" in web_assets
        assert "/level/sw.js" in web_assets
        assert redirects == {"/level": "level/"}

        # Landing alias reuses the exact same PROGMEM data symbol (zero duplicate flash)
        level_data_sym = web_assets["/level/level"][3]
        alias_data_sym = web_assets["/level/"][3]
        assert str(level_data_sym) == str(alias_data_sym)

        manifest_id = web_assets["/level/manifest.webmanifest"][0]
        manifest_json = json.loads(_extract_payload(CORE.build_path / "src" / f"{manifest_id}_web_host.h"))
        assert manifest_json["start_url"] == "./"
        assert manifest_json["scope"] == "./"

        sw_id = web_assets["/level/sw.js"][0]
        sw_js = _extract_payload(CORE.build_path / "src" / f"{sw_id}_web_host.h").decode("utf-8")
        assert '"rv-level-' in sw_js
        assert '"cache_first"' in sw_js
        # decoder.js had precache=False so it's in ROUTE_STRATEGIES but not PRECACHE_URLS
        precache_match = re.search(r"PRECACHE_URLS\s*=\s*(\[[^\]]*\])", sw_js)
        assert precache_match is not None
        assert "decoder.js" not in precache_match.group(1)

    def test_multiple_pwas_have_unique_ids_and_isolated_caches(self, tmp_path):
        CORE.config_path = tmp_path / "device.yaml"
        (tmp_path / "heat.html").write_text("<html>Heat</html>", encoding="utf-8")
        (tmp_path / "ac.html").write_text("<html>AC</html>", encoding="utf-8")

        cfg_heat = pwa_host.CONFIG_SCHEMA(
            {"id": "heat_pwa", "base_path": "/heat", "files": [{"file": "heat.html", "url": "index.html"}]}
        )
        cfg_ac = pwa_host.CONFIG_SCHEMA(
            {"id": "ac_pwa", "base_path": "/ac", "files": [{"file": "ac.html", "url": "index.html"}]}
        )

        mock_1, _ = _run_to_code(cfg_heat)
        calls_1 = [c.args for c in mock_1.call_args_list]
        mock_2, _ = _run_to_code(cfg_ac)
        calls_2 = [c.args for c in mock_2.call_args_list]

        ids_1 = {str(c[0]) for c in calls_1}
        ids_2 = {str(c[0]) for c in calls_2}
        assert ids_1.isdisjoint(ids_2)

        sw_1_id = next(c[0] for c in calls_1 if len(c) > 3 and c[1] == "/heat/sw.js")
        sw_2_id = next(c[0] for c in calls_2 if len(c) > 3 and c[1] == "/ac/sw.js")
        sw_1 = _extract_payload(CORE.build_path / "src" / f"{sw_1_id}_web_host.h").decode("utf-8")
        sw_2 = _extract_payload(CORE.build_path / "src" / f"{sw_2_id}_web_host.h").decode("utf-8")
        assert '"heat-pwa-' in sw_1
        assert '"ac-pwa-' in sw_2

    def test_explicit_manifest_and_sw_override_generation(self, tmp_path):
        CORE.config_path = tmp_path / "device.yaml"
        (tmp_path / "index.html").write_text("<html>Custom</html>", encoding="utf-8")
        (tmp_path / "manifest.webmanifest").write_text('{"name":"Custom"}', encoding="utf-8")
        (tmp_path / "sw.js").write_text("// custom sw", encoding="utf-8")

        config = pwa_host.CONFIG_SCHEMA(
            {
                "files": [
                    {"file": "index.html", "url": "/index"},
                    {"file": "manifest.webmanifest", "url": "/manifest.webmanifest"},
                    {"file": "sw.js", "url": "/sw.js"},
                ]
            }
        )
        assert pwa_host.CONF_MANIFEST_ID not in config
        assert pwa_host.CONF_SW_ID not in config

        mock_new_pvar, _ = _run_to_code(config)
        assert len(mock_new_pvar.call_args_list) == 3
