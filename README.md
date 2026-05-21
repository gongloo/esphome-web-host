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
    components: [ web_host ]

# Enable standard web server dependencies
web_server:
  local: true

# Map and host your custom web assets
web_host:
  - id: ui_page
    file: "data/htdocs/index.html"
    url: "/dashboard"
  - id: ui_manifest
    file: "data/htdocs/manifest.webmanifest"
    url: "/manifest.webmanifest"
  - id: ui_sw
    file: "data/htdocs/sw.js"
    url: "/sw.js"
  - id: ui_favicon
    file: "data/htdocs/favicon.ico"
    url: "/favicon.ico"
```

---

## ⚙️ Configuration Variables

| Variable | Type | Requirement | Description |
| :--- | :--- | :--- | :--- |
| **`id`** | ID | **Required** | The internal identifier for the asset instance. |
| **`file`** | String / Path | **Required** | The local file path to compile (relative to your ESPHome config directory or absolute). |
| **`url`** | String | **Required** | The URL endpoint path where the asset will be served (e.g. `/`, `/dashboard`). |
| **`content_type`** | String | *Optional* | Mime type of the resource. By default, it is auto-detected from the file extension. |

---

## 🚀 Advanced Compile-time Capabilities

### 1. Material Design Icon Inlining
To render high-quality vector icons without loading heavy external web fonts, add a `data-mdi` attribute to standard SVG tags:

```html
<svg class="icon" data-mdi="fan"></svg>
```

During compilation, `esphome-web-host` will automatically fetch the `fan` icon path from the Material Design Icons catalog, extract the `<path d="..." />` vector data, and transform it into:

```html
<svg class="icon" data-mdi="fan"><path d="M12,18.5C11.5 ... Z"/></svg>
```

### 2. Project Version Injection
Embed version numbers dynamically inside your HTML/JS:

```html
<span class="version-label">v${version}</span>
```

It will be replaced at compile-time with the version specified under your YAML's `esphome.project.version` block.

---

## 👨‍💻 Author and License

- **Author**: [@gongloo]
- **License**: MIT
