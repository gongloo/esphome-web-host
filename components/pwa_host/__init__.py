from __future__ import annotations

import hashlib
import json
import os
import re
import struct

import esphome.config_validation as cv
from esphome.const import CONF_ID, CONF_URL

try:
    from esphome.components import web_host
except ImportError:
    import web_host

from .sw_template import generate_service_worker

CODEOWNERS = ["@gongloo"]
DEPENDENCIES = ["web_server_base"]
AUTO_LOAD = ["web_host"]
MULTI_CONF = True
MULTI_CONF_NO_DEFAULT = True

CONF_BASE_PATH = "base_path"
CONF_NAME = "name"
CONF_SHORT_NAME = "short_name"
CONF_START_URL = "start_url"
CONF_LANDING_PAGE = "landing_page"
CONF_DISPLAY = "display"
CONF_ORIENTATION = "orientation"
CONF_THEME_COLOR = "theme_color"
CONF_BACKGROUND_COLOR = "background_color"
CONF_MANIFEST_URL = "manifest_url"
CONF_GENERATE_MANIFEST = "generate_manifest"
CONF_ICONS = "icons"
CONF_SOURCES = "sources"
CONF_SERVICE_WORKER = "service_worker"
CONF_STRATEGY = "strategy"
CONF_PRECACHE = "precache"
CONF_ALIASES = "aliases"
CONF_SIZES = "sizes"
CONF_PURPOSE = "purpose"
CONF_ENABLED = "enabled"
CONF_CACHE_NAME_PREFIX = "cache_name_prefix"

CONF_MANIFEST_ID = "manifest_id"
CONF_SW_ID = "service_worker_id"
CONF_LANDING_ID = "landing_id"
CONF_REDIRECT_ID = "redirect_id"

STRATEGY_NETWORK_FIRST = "network_first"
STRATEGY_CACHE_FIRST = "cache_first"
STRATEGY_STALE_WHILE_REVALIDATE = "stale_while_revalidate"

STRATEGY_SCHEMA = cv.one_of(
    STRATEGY_NETWORK_FIRST,
    STRATEGY_CACHE_FIRST,
    STRATEGY_STALE_WHILE_REVALIDATE,
    lower=True,
)

DISPLAY_SCHEMA = cv.one_of("fullscreen", "standalone", "minimal-ui", "browser", lower=True)

PWA_FILE_SCHEMA = web_host.FILE_SCHEMA.extend(
    {
        cv.Optional(CONF_STRATEGY): STRATEGY_SCHEMA,
        cv.Optional(CONF_PRECACHE, default=True): cv.boolean,
        cv.Optional(CONF_ALIASES, default=[]): cv.ensure_list(cv.string),
    }
)

PWA_ICON_SCHEMA = PWA_FILE_SCHEMA.extend(
    {
        cv.Optional(CONF_SIZES): cv.string,
        cv.Optional(CONF_PURPOSE, default="any"): cv.string,
    }
)

PWA_SOURCE_GROUP_SCHEMA = cv.Schema(
    {
        cv.Optional(web_host.CONF_SOURCE): cv.SOURCE_SCHEMA,
        cv.Optional(web_host.CONF_MINIFY): cv.boolean,
        cv.Optional(web_host.CONF_CACHE_CONTROL): web_host.validate_cache_control,
        cv.Required(web_host.CONF_FILES): cv.ensure_list(PWA_FILE_SCHEMA),
    }
)

SERVICE_WORKER_SCHEMA = cv.Schema(
    {
        cv.Optional(CONF_ENABLED, default=True): cv.boolean,
        cv.Optional(CONF_URL, default="sw.js"): cv.string,
        cv.Optional(CONF_STRATEGY, default=STRATEGY_NETWORK_FIRST): STRATEGY_SCHEMA,
        cv.Optional(CONF_CACHE_NAME_PREFIX): cv.string,
        cv.Optional(web_host.CONF_CACHE_CONTROL, default="no-cache"): web_host.validate_cache_control,
        cv.Optional(web_host.CONF_MINIFY): cv.boolean,
    }
)


def validate_base_path(value):
    value = cv.string(value).strip()
    if any(ch in value for ch in ("\r", "\n", "?", "#")):
        raise cv.Invalid("base_path must not contain query strings, fragments, or newline characters")
    segments = [seg for seg in value.split("/") if seg]
    if any(seg in (".", "..") for seg in segments):
        raise cv.Invalid("base_path must not contain '.' or '..' segments")
    if not segments:
        return "/"
    return f"/{'/'.join(segments)}/"


def validate_relative_url(value, allow_empty=False):
    value = cv.string(value).strip()
    if any(ch in value for ch in ("\r", "\n", "?", "#")):
        raise cv.Invalid("url must not contain query strings, fragments, or newline characters")
    if value in ("", "/", "./"):
        if allow_empty:
            return ""
        raise cv.Invalid("url must not be empty")
    stripped = value.lstrip("/")
    segments = [seg for seg in stripped.split("/") if seg]
    if any(seg in (".", "..") for seg in segments):
        raise cv.Invalid("url must not contain '.' or '..' segments")
    return "/".join(segments)


def join_base_url(base_path: str, raw_url: str) -> tuple[str, str]:
    """Resolve an asset URL relative to base_path -> (full_server_url, sw_relative_url)."""
    rel = validate_relative_url(raw_url, allow_empty=True)
    if rel == "":
        return base_path, "./"
    if base_path == "/":
        return f"/{rel}", rel
    return f"{base_path}{rel}", rel


def _iter_source_groups(config: dict) -> list[dict]:
    groups: list[dict] = []
    if web_host.CONF_FILES in config:
        inline_group = {web_host.CONF_FILES: config[web_host.CONF_FILES]}
        if web_host.CONF_SOURCE in config:
            inline_group[web_host.CONF_SOURCE] = config[web_host.CONF_SOURCE]
        groups.append(inline_group)
    if CONF_SOURCES in config:
        groups.extend(config[CONF_SOURCES])
    return groups


def _select_landing_entry(config: dict, asset_entries: list[dict]) -> dict | None:
    base_path = config[CONF_BASE_PATH]
    landing_page = config.get(CONF_LANDING_PAGE)

    if landing_page is not None:
        normalized_target = validate_relative_url(landing_page, allow_empty=True)
        for entry in asset_entries:
            if entry["sw_rel"] == (normalized_target or "./") or entry["file"] == landing_page:
                return entry
        raise cv.Invalid(f"landing_page '{landing_page}' does not match any file in this pwa_host")

    for entry in asset_entries:
        if entry["full_url"] == base_path:
            return entry

    for entry in asset_entries:
        if entry["sw_rel"] == "index.html":
            return entry

    start_url = config.get(CONF_START_URL)
    if start_url is not None:
        start_rel = validate_relative_url(start_url, allow_empty=True) or "./"
        for entry in asset_entries:
            if entry["sw_rel"] == start_rel:
                return entry

    for entry in asset_entries:
        if entry["content_type"] == "text/html":
            return entry

    return None


def validate_pwa_host(config):
    has_files = bool(config.get(web_host.CONF_FILES))
    has_sources = bool(config.get(CONF_SOURCES))
    if not has_files and not has_sources:
        raise cv.Invalid("pwa_host requires at least one file under 'files' or 'sources'")

    base_path = config[CONF_BASE_PATH]
    seen_urls: set[str] = set()
    asset_entries: list[dict] = []

    def _register_entry(file_config: dict, group_config: dict, is_icon: bool = False):
        source_dir = None
        if web_host.CONF_SOURCE in group_config:
            source_dir = web_host.resolve_source_path(group_config[web_host.CONF_SOURCE])
        resolved_path = web_host.resolve_file_path(
            group_config, file_config[web_host.CONF_FILE], source_dir, fallback_config=config
        )
        if not os.path.exists(resolved_path):
            raise cv.Invalid(f"Resource file not found at path: {resolved_path}")

        full_url, sw_rel = join_base_url(base_path, file_config[web_host.CONF_URL])
        if full_url in seen_urls:
            raise cv.Invalid(f"Duplicate URL '{full_url}' in pwa_host configuration")
        seen_urls.add(full_url)

        content_type = file_config.get(web_host.CONF_CONTENT_TYPE) or web_host.detect_content_type(resolved_path)
        for alias in file_config[CONF_ALIASES]:
            validate_relative_url(alias, allow_empty=True)
        asset_entries.append(
            {
                "file": file_config[web_host.CONF_FILE],
                "full_url": full_url,
                "sw_rel": sw_rel,
                "content_type": content_type,
                "is_icon": is_icon,
            }
        )

    for group in _iter_source_groups(config):
        for file_config in group[web_host.CONF_FILES]:
            _register_entry(file_config, group, is_icon=False)

    icon_group = {web_host.CONF_SOURCE: config[web_host.CONF_SOURCE]} if web_host.CONF_SOURCE in config else {}
    for icon_config in config[CONF_ICONS]:
        _register_entry(icon_config, icon_group, is_icon=True)

    if CONF_START_URL in config:
        raw_start = config[CONF_START_URL].strip()
        if not (raw_start in ("", ".", "./", "/") and base_path != "/"):
            validate_relative_url(raw_start, allow_empty=True)

    landing_entry = _select_landing_entry(config, asset_entries)
    if base_path != "/" and landing_entry is None:
        raise cv.Invalid(
            "Subpath pwa_host requires a 'landing_page' or at least one HTML file to serve at base_path"
        )
    if base_path == "/" and landing_entry is None and CONF_START_URL not in config:
        raise cv.Invalid("pwa_host requires 'start_url', 'landing_page', or at least one HTML file")

    if base_path != "/":
        config[CONF_REDIRECT_ID] = cv.declare_id(web_host.WebRedirectComponent)(None)
        if landing_entry is not None and landing_entry["full_url"] != base_path:
            config[CONF_LANDING_ID] = cv.declare_id(web_host.WebHostComponent)(None)

    manifest_full_url, _ = join_base_url(base_path, config[CONF_MANIFEST_URL])
    if config[CONF_GENERATE_MANIFEST] and manifest_full_url not in seen_urls:
        config[CONF_MANIFEST_ID] = cv.declare_id(web_host.WebHostComponent)(None)
        seen_urls.add(manifest_full_url)

    sw_cfg = config[CONF_SERVICE_WORKER]
    sw_full_url, _ = join_base_url(base_path, sw_cfg[CONF_URL])
    if sw_cfg[CONF_ENABLED] and sw_full_url not in seen_urls:
        config[CONF_SW_ID] = cv.declare_id(web_host.WebHostComponent)(None)

    return config


CONFIG_SCHEMA = cv.All(
    cv.Schema(
        {
            cv.Optional(CONF_ID): cv.valid_name,
            cv.Optional(CONF_BASE_PATH, default="/"): validate_base_path,
            cv.Optional(CONF_NAME): cv.string,
            cv.Optional(CONF_SHORT_NAME): cv.string,
            cv.Optional(CONF_START_URL): cv.string,
            cv.Optional(CONF_LANDING_PAGE): cv.string,
            cv.Optional(CONF_DISPLAY, default="standalone"): DISPLAY_SCHEMA,
            cv.Optional(CONF_ORIENTATION): cv.string,
            cv.Optional(CONF_THEME_COLOR): cv.string,
            cv.Optional(CONF_BACKGROUND_COLOR): cv.string,
            cv.Optional(CONF_MANIFEST_URL, default="manifest.webmanifest"): cv.string,
            cv.Optional(CONF_GENERATE_MANIFEST, default=True): cv.boolean,
            cv.Optional(web_host.CONF_SOURCE): cv.SOURCE_SCHEMA,
            cv.Optional(web_host.CONF_MINIFY, default=True): cv.boolean,
            cv.Optional(web_host.CONF_CACHE_CONTROL): web_host.validate_cache_control,
            cv.Optional(CONF_ICONS, default=[]): cv.ensure_list(PWA_ICON_SCHEMA),
            cv.Optional(web_host.CONF_FILES): cv.ensure_list(PWA_FILE_SCHEMA),
            cv.Optional(CONF_SOURCES): cv.ensure_list(PWA_SOURCE_GROUP_SCHEMA),
            cv.Optional(CONF_SERVICE_WORKER, default={}): SERVICE_WORKER_SCHEMA,
        }
    ),
    validate_pwa_host,
)


def _detect_png_size(raw_bytes: bytes) -> str | None:
    if len(raw_bytes) >= 24 and raw_bytes[:8] == b"\x89PNG\r\n\x1a\n" and raw_bytes[12:16] == b"IHDR":
        width, height = struct.unpack(">II", raw_bytes[16:24])
        if width > 0 and height > 0:
            return f"{width}x{height}"
    return None


def _sanitize_cache_prefix(raw_name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9-]+", "-", raw_name.lower()).strip("-")
    return cleaned or "pwa"


def _resolve_id(id_obj):
    if id_obj.id is not None:
        return id_obj
    from esphome.core import CORE

    used_ids = getattr(CORE, "_pwa_host_resolved_ids", None)
    if used_ids is None:
        used_ids = set()
        setattr(CORE, "_pwa_host_resolved_ids", used_ids)
    used_ids.add(id_obj.resolve(used_ids))
    return id_obj


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


async def to_code(config):
    from esphome.core import CORE

    base_path = config[CONF_BASE_PATH]
    sw_cfg = config[CONF_SERVICE_WORKER]
    default_strategy = sw_cfg[CONF_STRATEGY]
    global_minify = config[web_host.CONF_MINIFY]
    global_cache_control = config.get(web_host.CONF_CACHE_CONTROL, "")

    hasher = hashlib.sha256()
    precache_urls: list[str] = []
    route_strategies: dict[str, str] = {}
    registered_assets: list[dict] = []
    manifest_icons: list[dict] = []

    async def _register_file_config(file_config: dict, group_config: dict, is_icon: bool = False):
        source_dir = None
        if web_host.CONF_SOURCE in group_config:
            source_dir = web_host.resolve_source_path(group_config[web_host.CONF_SOURCE])
        resolved_path = web_host.resolve_file_path(
            group_config, file_config[web_host.CONF_FILE], source_dir, fallback_config=config
        )
        content_type = file_config.get(web_host.CONF_CONTENT_TYPE) or web_host.detect_content_type(resolved_path)

        with open(resolved_path, "rb") as f:
            file_content = f.read()

        group_minify = group_config.get(web_host.CONF_MINIFY, global_minify)
        should_minify = file_config.get(web_host.CONF_MINIFY, group_minify)
        group_cache_control = group_config.get(web_host.CONF_CACHE_CONTROL, global_cache_control)
        cache_control = file_config.get(web_host.CONF_CACHE_CONTROL, group_cache_control)

        full_url, sw_rel = join_base_url(base_path, file_config[web_host.CONF_URL])
        var_id = _resolve_id(file_config[CONF_ID])

        _, payload_bytes, use_gzip = await web_host.register_bytes_asset(
            var_id,
            full_url,
            file_content,
            content_type,
            source_label=resolved_path,
            should_minify=should_minify,
            cache_control=cache_control,
            component_config=file_config,
        )

        strategy = file_config.get(CONF_STRATEGY, default_strategy)
        precache = file_config[CONF_PRECACHE]
        aliases = [validate_relative_url(a, allow_empty=True) or "./" for a in file_config[CONF_ALIASES]]

        if precache:
            precache_urls.append(sw_rel)
        hasher.update(sw_rel.encode("utf-8"))
        hasher.update(payload_bytes)
        route_strategies[sw_rel] = strategy
        for alias in aliases:
            route_strategies.setdefault(alias, strategy)

        registered_assets.append(
            {
                "file": file_config[web_host.CONF_FILE],
                "var_id": var_id,
                "full_url": full_url,
                "sw_rel": sw_rel,
                "content_type": content_type,
                "use_gzip": use_gzip,
                "cache_control": cache_control,
                "strategy": strategy,
                "precache": precache,
                "aliases": aliases,
            }
        )

        if is_icon:
            icon_entry: dict[str, str] = {
                "src": sw_rel,
                "type": content_type,
                "purpose": file_config[CONF_PURPOSE],
            }
            sizes = file_config.get(CONF_SIZES) or _detect_png_size(file_content)
            if sizes:
                icon_entry["sizes"] = sizes
            manifest_icons.append(icon_entry)

    for group in _iter_source_groups(config):
        for file_config in group[web_host.CONF_FILES]:
            await _register_file_config(file_config, group, is_icon=False)

    icon_group = {web_host.CONF_SOURCE: config[web_host.CONF_SOURCE]} if web_host.CONF_SOURCE in config else {}
    for icon_config in config[CONF_ICONS]:
        await _register_file_config(icon_config, icon_group, is_icon=True)

    landing_asset = _select_landing_entry(config, registered_assets)

    if base_path != "/":
        if CONF_LANDING_ID in config and landing_asset is not None:
            landing_id = _resolve_id(config[CONF_LANDING_ID])
            await web_host.register_alias_asset(
                landing_id,
                base_path,
                landing_asset["var_id"],
                landing_asset["content_type"],
                landing_asset["use_gzip"],
                cache_control=landing_asset["cache_control"],
            )
            if landing_asset["precache"]:
                precache_urls.append("./")
            route_strategies["./"] = landing_asset["strategy"]

        redirect_id = _resolve_id(config[CONF_REDIRECT_ID])
        trimmed = base_path.rstrip("/")
        leaf_dir = f"{trimmed.rsplit('/', 1)[-1]}/"
        await web_host.register_redirect(redirect_id, trimmed, leaf_dir)

    esphome_conf = CORE.config.get("esphome", {})
    default_name = esphome_conf.get("friendly_name") or esphome_conf.get("name") or "ESPHome App"
    app_name = config.get(CONF_NAME) or default_name
    short_name = config.get(CONF_SHORT_NAME) or app_name

    if CONF_START_URL in config:
        raw_start = config[CONF_START_URL].strip()
        start_url = "./" if raw_start in ("", ".", "./", "/") and base_path != "/" else (
            validate_relative_url(raw_start, allow_empty=True) or "./"
        )
    elif base_path != "/":
        start_url = "./"
    elif landing_asset is not None:
        start_url = landing_asset["sw_rel"]
    else:
        start_url = "./"

    if CONF_MANIFEST_ID in config:
        manifest_full_url, manifest_sw_rel = join_base_url(base_path, config[CONF_MANIFEST_URL])
        manifest_data: dict = {
            "name": app_name,
            "short_name": short_name,
            "start_url": start_url,
            "scope": "./",
            "display": config[CONF_DISPLAY],
        }
        if CONF_ORIENTATION in config:
            manifest_data["orientation"] = config[CONF_ORIENTATION]
        if CONF_THEME_COLOR in config:
            manifest_data["theme_color"] = config[CONF_THEME_COLOR]
        if CONF_BACKGROUND_COLOR in config:
            manifest_data["background_color"] = config[CONF_BACKGROUND_COLOR]
        if manifest_icons:
            manifest_data["icons"] = manifest_icons

        manifest_bytes = json.dumps(manifest_data, indent=2, ensure_ascii=False).encode("utf-8")
        manifest_id = _resolve_id(config[CONF_MANIFEST_ID])
        _, manifest_payload, _ = await web_host.register_bytes_asset(
            manifest_id,
            manifest_full_url,
            manifest_bytes,
            "application/manifest+json",
            source_label=manifest_full_url,
            should_minify=global_minify,
            cache_control=global_cache_control,
        )
        precache_urls.append(manifest_sw_rel)
        route_strategies[manifest_sw_rel] = default_strategy
        hasher.update(manifest_sw_rel.encode("utf-8"))
        hasher.update(manifest_payload)

    if CONF_SW_ID in config:
        sw_full_url, _ = join_base_url(base_path, sw_cfg[CONF_URL])
        fallback_prefix = base_path.strip("/") if base_path != "/" else (esphome_conf.get("name") or "pwa")
        prefix_source = (
            sw_cfg.get(CONF_CACHE_NAME_PREFIX)
            or config.get(CONF_ID)
            or config.get(CONF_SHORT_NAME)
            or config.get(CONF_NAME)
            or fallback_prefix
        )
        cache_prefix = _sanitize_cache_prefix(prefix_source)
        cache_version = hasher.hexdigest()[:8]

        fallback_urls: list[str] = []
        if landing_asset is not None:
            fallback_urls.append(landing_asset["sw_rel"])
            fallback_urls.extend(landing_asset["aliases"])
        if base_path != "/":
            fallback_urls.append("./")
        if start_url in route_strategies:
            fallback_urls.append(start_url)

        sw_source = generate_service_worker(
            cache_prefix=cache_prefix,
            cache_version=cache_version,
            precache_urls=_dedupe_preserve_order(precache_urls),
            route_strategies=route_strategies,
            fallback_urls=_dedupe_preserve_order(fallback_urls),
        )
        sw_id = _resolve_id(config[CONF_SW_ID])
        sw_minify = sw_cfg.get(web_host.CONF_MINIFY, global_minify)
        await web_host.register_bytes_asset(
            sw_id,
            sw_full_url,
            sw_source.encode("utf-8"),
            "application/javascript",
            source_label=sw_full_url,
            should_minify=sw_minify,
            cache_control=sw_cfg[web_host.CONF_CACHE_CONTROL],
        )
