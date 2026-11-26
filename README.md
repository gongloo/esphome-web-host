# esphome-web-host

A high-performance, generic, declarative static asset and Progressive Web App (PWA) web hosting external component for **ESPHome**.

Typically, ESPHome's web server is restricted to displaying standard entity dashboards. `esphome-web-host` allows you to host complex, interactive, and beautiful frontends, custom single-page applications, or offline-capable PWAs directly from your ESP32 or ESP8266 device with minimal runtime overhead.

---

## ✨ Features

- **Declarative Resource Mapping**: Map any local static file (HTML, CSS, JS, manifest, icons, images) to any URL route via clean YAML configuration.
- **Compile-Time Gzip (Zopfli) & Brotli Compression**: Assets are deterministically compressed at compile time (`gzip` by default, or `br` via `compression: br`) and embedded as byte arrays in `PROGMEM` (Flash memory) whenever compression reduces the payload size. When `zopfli` is installed, `gzip` mode automatically uses Zopfli for tighter compression (and logs a one-time warning if `zopfli` is missing).
- **Automatic Asset Minification**: HTML, CSS, JS, JSON, and `.webmanifest` files are automatically minified at compile time (configurable via `minify`, enabled by default) using Python's stdlib (`json`, `html.parser`) and git-cached `rjsmin` / `rcssmin`.
- **Dynamic MDI SVG Downloader & Inliner**: Natively pulls requested Material Design Icons using ESPHome's GitHub cache, parses their path definitions, and injects them directly into your HTML code before compilation.
- **Configurable Version Substitutions**: Automatically replaces `${version}` placeholders in your HTML/resource code with your ESPHome project's declared version string.
- **Asynchronous Processing**: Leverages `ESPAsyncWebServer` for lightning-fast concurrent requests without blocking sensor loops or automation routines.

---

## 🛠️ Usage and Configuration

Add the component to your ESPHome configuration file (e.g., `device.yaml`):

```yaml
external_components:
  - source:
      type: git
      url: https://github.com/gongloo/esphome-web-host.git
      ref: main
    components: [web_host]

# Enable standard web server dependencies
web_server:
  local: true

# Map and host your custom web assets
web_host:
  source: "." # Resolve paths relative to the current folder (default)
  files:
    - id: ui_page
      file: "data/htdocs/index.html"
      url: "/dashboard"
    - id: ui_favicon
      file: "data/htdocs/favicon.ico"
      url: "/favicon.ico"
```

### 📦 Smart Static Asset Resolution

To resolve relative file paths (e.g. `data/htdocs/...`), `esphome-web-host` executes a smart, highly robust lookup sequence.

When searching for static assets, it scans the following directories in order of precedence:

1. **Explicit `source` Directory (Strict/Exclusive)**:
   If a global `source` parameter is explicitly provided, `esphome-web-host` resolves files **exclusively** relative to it and disables all downstream fallbacks.
   - If `source` is set to a local path (e.g. `../../OutEquipAC`), it resolves files relative to that directory.
   - If `source` is set to a Git repository target (e.g., shorthand `github://` or explicit Git URL), ESPHome will **automatically clone or update the repository** to its local cache at compile time and resolve files relative to the cloned folder root.
2. **Declaring YAML Package Directory (Zero-Configuration Fallback)**:
   If the `source` parameter is omitted, `esphome-web-host` automatically checks relative to the **directory of the `.yaml` package configuration file** that declared the `web_host:` block.
   - This allows package creators to write base configs with completely zero-configuration pathing! When imported locally via `!include` or pulled remotely as a GitHub package, the static files automatically resolve relative to the package folder out of the box.
3. **Main Configuration Directory (Central Fallback)**:
   If the file is not found in the declaring YAML directory (or if the path is absolute), the loader falls back to resolving relative to your main ESPHome configuration folder (`CORE.config_dir`, e.g. `/ESPHome/config/`).

#### Example: Sourcing assets dynamically from a local workspace

```yaml
web_host:
  source: "../../OutEquipAC"
  files:
    - id: ui_page
      file: "data/htdocs/thermostat.html"
      url: "/thermostat"
```

#### Example: Sourcing assets dynamically from a remote GitHub repository

```yaml
web_host:
  source: "github://gongloo/OutEquipAC@main"
  files:
    - id: ui_page
      file: "data/htdocs/thermostat.html"
      url: "/thermostat"
```

#### Example: Hosting files from multiple sources simultaneously

```yaml
web_host:
  - source: "../../OutEquipAC"
    files:
      - id: ui_page
        file: "data/htdocs/thermostat.html"
        url: "/thermostat"
  - source: "../../HyHeat"
    files:
      - id: hyheat_readme
        file: "README.md"
        url: "/hyheat-readme"
```

---

## ⚙️ Configuration Variables

### Global Configuration

| Variable     | Type          | Requirement  | Description                                                                                                               |
| :----------- | :------------ | :----------- | :------------------------------------------------------------------------------------------------------------------------ |
| **`source`**        | Source Schema | _Optional_   | The base path or Git source (local path, Git URL, or `github://` shorthand). Defaults to `.` (the ESPHome config folder). |
| **`minify`**        | Boolean       | _Optional_   | Enable compile-time minification for HTML, CSS, JS, JSON, and `.webmanifest` assets. Defaults to `true`.                  |
| **`compression`**   | String        | _Optional_   | Compression algorithm (`gzip` or `br`), matching ESPHome's `web_server` / `captive_portal` syntax. Defaults to `gzip`.    |
| **`cache_control`** | String        | _Optional_   | Default HTTP `Cache-Control` response header for all files in this block (omitted by default).                            |
| **`files`**         | List of Files | **Required** | The list of static asset files to map and compile under this source.                                                      |

### File Definition (`files:`)

| Variable            | Type          | Requirement  | Description                                                                                                                |
| :------------------ | :------------ | :----------- | :------------------------------------------------------------------------------------------------------------------------- |
| **`id`**            | ID            | **Required** | The internal identifier for the asset instance.                                                                            |
| **`file`**          | String / Path | **Required** | The file path to compile (resolved relative to the global `source` folder).                                                |
| **`url`**           | String        | **Required** | The URL endpoint path where the asset will be served (e.g. `/`, `/thermostat`).                                            |
| **`content_type`**  | String        | _Optional_   | Mime type of the resource. By default, it is auto-detected from the file extension.                                        |
| **`minify`**        | Boolean       | _Optional_   | Override the global `minify` setting for this specific file.                                                               |
| **`compression`**   | String        | _Optional_   | Override the global `compression` setting (`gzip` or `br`) for this specific file.                                         |
| **`cache_control`** | String        | _Optional_   | Override the global `cache_control` header for this file. Set to `""` to omit an inherited global header.                 |

---

## 🚀 Advanced Compile-time Capabilities

### 1. Material Design Icon Inlining

To render high-quality vector icons without loading heavy external web fonts, add a `data-mdi` attribute to standard SVG tags:

```html
<svg class="icon" data-mdi="fan"></svg>
```

During compilation, `esphome-web-host` will automatically fetch the `fan` icon path from the Material Design Icons catalog, extract the `<path d="..." />` vector data, and transform it into:

```html
<svg class="icon" data-mdi="fan"><path d="M12,18.5C11.5 ... Z" /></svg>
```

### 2. Project Version Injection

Embed version numbers dynamically inside your HTML/JS:

```html
<span class="version-label">v${version}</span>
```

It will be replaced at compile-time with the version specified under your YAML's `esphome.project.version` block.

---

## 📱 Hosting PWAs with `pwa_host`

This repository also provides **`pwa_host`**, a companion component built on top of `web_host` that eliminates duplicated `sw.js` and `manifest.webmanifest` boilerplate across ESPHome PWA projects.

### ✨ `pwa_host` Features

- **Auto-Generated `sw.js`**: Generates an ESP32/ESP8266-safe Service Worker with sequential precaching (avoiding lwIP socket exhaustion), deterministic content-hash `CACHE_NAME` busting on OTA updates, reverse-proxy-safe `new URL(asset, self.location.href)` scoping, `{ ignoreSearch: true }` offline fallback, and `Cache-Control: no-cache` by default.
- **Per-Asset Caching Strategies**: Defaults to `network_first`, with per-file `cache_first` or `stale_while_revalidate` overrides (e.g., for large `.glb` models or decoder scripts).
- **Auto-Generated `manifest.webmanifest`**: Defaults `name`/`short_name` from `esphome.friendly_name`/`esphome.name`, serves with `application/manifest+json`, and auto-reads PNG icon dimensions when `sizes` is omitted (skipped automatically if you supply your own manifest file).
- **Multi-Source & Multi-PWA Ready**: Supports multiple `sources:` groups per PWA (including remote Git repos) and `MULTI_CONF` under different `base_path` prefixes with prefix-isolated cache eviction.
- **Subpath Landing Page & Redirect**: When `base_path` is non-root (e.g. `"/level/"`), `pwa_host` automatically serves the designated landing page at `/level/` (sharing the `PROGMEM` data with zero duplicate flash) and adds a relative `/level` → `level/` redirect so relative URLs and SW scopes resolve correctly.

### Single-Source PWA Example

```yaml
external_components:
  - source: github://gongloo/esphome-web-host@main
    components: [web_host, pwa_host]

pwa_host:
  name: "HyHeat"
  start_url: "thermostat"
  theme_color: "#0c0c0e"
  background_color: "#0c0c0e"
  icons:
    - file: "data/htdocs/apple-touch-icon.png"
      url: "apple-touch-icon.png"
      purpose: "any maskable"
  files:
    - file: "data/htdocs/thermostat.html"
      url: "thermostat"
      aliases: ["thermostat.html"]
    - file: "data/htdocs/icon-96.png"
      url: "icon-96.png"
    - file: "data/htdocs/favicon.ico"
      url: "favicon.ico"
```

### Multi-Source & Subpath PWA Example

```yaml
pwa_host:
  - id: rv_level_pwa
    base_path: "/level/"
    name: "RV Level"
    landing_page: "level"
    orientation: any
    theme_color: "#070E1B"
    background_color: "#070E1B"
    icons:
      - file: "data/htdocs/apple-touch-icon.png"
        url: "apple-touch-icon.png"
    sources:
      - files:
          - file: "data/htdocs/level.html"
            url: "level"
            aliases: ["level.html"]
          - file: "data/htdocs/ProMaster_2015_White_meshopt.glb"
            url: "ProMaster_2015_White_meshopt.glb"
            content_type: "model/gltf-binary"
            strategy: stale_while_revalidate
      - source:
          type: git
          url: https://github.com/zeux/meshoptimizer.git
          ref: v1.3
          path: js
        files:
          - file: "meshopt_decoder_reference.js"
            url: "meshopt_decoder.js"
            strategy: stale_while_revalidate
```

### `pwa_host` Configuration Variables

| Variable                  | Type           | Default                      | Description                                                                                               |
| :------------------------ | :------------- | :--------------------------- | :-------------------------------------------------------------------------------------------------------- |
| **`id`**                  | Name           | _Optional_                   | Identifier for this PWA instance (also used as the default `CACHE_NAME` prefix).                          |
| **`base_path`**           | String         | `"/"`                        | URL prefix where the PWA is mounted. Non-root paths add a trailing-slash redirect and landing alias.      |
| **`name` / `short_name`** | String         | `esphome.friendly_name`      | Web App Manifest display names.                                                                           |
| **`start_url`**           | String         | `"./"` (subpath) / landing   | Manifest `start_url` (relative to `base_path`).                                                           |
| **`landing_page`**        | String         | Auto (`index.html`/first HTML) | Asset `url` or `file` to serve directly at `base_path` for subpath PWAs.                                  |
| **`display`**             | String         | `"standalone"`               | Manifest `display` mode (`fullscreen`, `standalone`, `minimal-ui`, `browser`).                            |
| **`orientation`**         | String         | _Optional_                   | Manifest `orientation` (e.g. `any`, `portrait`).                                                          |
| **`theme_color`**         | String         | _Optional_                   | Manifest `theme_color`.                                                                                   |
| **`background_color`**    | String         | _Optional_                   | Manifest `background_color`.                                                                              |
| **`manifest_url`**        | String         | `"manifest.webmanifest"`     | Manifest URL relative to `base_path`.                                                                     |
| **`generate_manifest`**   | Boolean        | `true`                       | Auto-generate the manifest unless disabled or explicitly provided in `files:`.                            |
| **`source`**              | Source Schema  | _Optional_                   | Base path or Git source for top-level `files:` and `icons:` (falls back to declaring YAML directory).     |
| **`minify`**              | Boolean        | `true`                       | Default compile-time minification setting across `files:`, `sources:`, `manifest`, and `sw.js`.           |
| **`compression`**         | String         | `"gzip"`                     | Default compression algorithm (`gzip` or `br`) across `files:`, `sources:`, `manifest`, and `sw.js`.      |
| **`cache_control`**       | String         | _Optional_                   | Default `Cache-Control` header for PWA files and generated manifest (`sw.js` defaults to `"no-cache"`).   |
| **`icons`**               | List of Icons  | `[]`                         | Extends `web_host` file fields with optional `sizes` (auto-detected for PNGs) and `purpose` (`"any"`).    |
| **`files` / `sources`**   | List           | **One required**             | Single-source `files:` list or multi-source `sources:` groups. Per-file options add `strategy`, `precache` (`true`), and `aliases` (`[]`, SW-intercepted offline fallback paths). |
| **`service_worker`**      | Object         | `{}`                         | Sub-options: `enabled` (`true`), `url` (`"sw.js"`), `strategy` (`network_first`), `cache_name_prefix`, `cache_control` (`"no-cache"`), `minify`, `compression`. |
