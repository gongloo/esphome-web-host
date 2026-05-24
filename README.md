# esphome-web-host

A high-performance, generic, declarative static asset and Progressive Web App (PWA) web hosting external component for **ESPHome**.

Typically, ESPHome's web server is restricted to displaying standard entity dashboards. `esphome-web-host` allows you to host complex, interactive, and beautiful frontends, custom single-page applications, or offline-capable PWAs directly from your ESP32 or ESP8266 device with minimal runtime overhead.

---

## ✨ Features

- **Declarative Resource Mapping**: Map any local static file (HTML, CSS, JS, manifest, icons, images) to any URL route via clean YAML configuration.
- **On-the-Fly Gzip Compression**: Assets are compressed during compile-time and embedded as byte arrays in `PROGMEM` (Flash memory), drastically reducing runtime RAM usage and flash size.
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
| **`source`** | Source Schema | _Optional_   | The base path or Git source (local path, Git URL, or `github://` shorthand). Defaults to `.` (the ESPHome config folder). |
| **`files`**  | List of Files | **Required** | The list of static asset files to map and compile under this source.                                                      |

### File Definition (`files:`)

| Variable           | Type          | Requirement  | Description                                                                         |
| :----------------- | :------------ | :----------- | :---------------------------------------------------------------------------------- |
| **`id`**           | ID            | **Required** | The internal identifier for the asset instance.                                     |
| **`file`**         | String / Path | **Required** | The file path to compile (resolved relative to the global `source` folder).         |
| **`url`**          | String        | **Required** | The URL endpoint path where the asset will be served (e.g. `/`, `/thermostat`).     |
| **`content_type`** | String        | _Optional_   | Mime type of the resource. By default, it is auto-detected from the file extension. |

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
