#!/usr/bin/env python3
"""
IBM API Connect to Kong Gateway declarative config converter.

Reads an IBM API Connect OAS spec (with x-ibm-configuration) and produces
a Kong declarative configuration (decK format) YAML file.

Usage:
    python3 ibm2kong.py <input_ibm_oas.yaml> [output_kong.yaml]

If no output path is given, writes to kong-<input_basename>.yaml.
"""

import sys
import re
import copy
import yaml
from pathlib import Path


# ────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    """Turn arbitrary text into a DNS-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def extract_url(raw: str) -> str:
    """
    IBM spec URLs are sometimes wrapped in markdown-style links like
    [label](https://actual-url).  Extract the real URL.
    """
    md_match = re.search(r"\(([^)]+)\)", raw)
    if md_match:
        return md_match.group(1).rstrip("/")
    return raw.strip().rstrip("/")


def split_url(url: str):
    """Return (protocol, host, port, path) from a URL string."""
    # Handle relative/path-only URLs (no scheme, no host)
    if url.startswith("/") or (not url.startswith("http://") and not url.startswith("https://") and "/" in url and "." not in url.split("/")[0]):
        return "https", "<UPSTREAM_HOST>", 443, url

    protocol = "https"
    if url.startswith("http://"):
        protocol = "http"
    host_path = re.sub(r"^https?://", "", url)
    parts = host_path.split("/", 1)
    host_port = parts[0]
    path = "/" + parts[1] if len(parts) > 1 else "/"

    if ":" in host_port:
        host, port = host_port.rsplit(":", 1)
        port = int(port)
    else:
        host = host_port
        port = 443 if protocol == "https" else 80

    return protocol, host, port, path


# ────────────────────────────────────────────────────────────────────
# Core conversion
# ────────────────────────────────────────────────────────────────────

def build_kong_config(ibm_spec: dict, catalog: str | None = None) -> dict:
    """
    Convert a parsed IBM API Connect OAS dict into a Kong declarative
    config dict.  If *catalog* is given, use that catalog's property
    overrides (e.g. sandbox / production target-url).
    """
    info = ibm_spec.get("info", {})
    ibm_cfg = ibm_spec.get("x-ibm-configuration", {})

    service_name = slugify(info.get("title", "ibm-service"))
    api_version = info.get("version", "1.0.0")

    # ── Resolve target URL ──────────────────────────────────────────
    # Priority: catalog override → assembly invoke → properties → server
    properties = ibm_cfg.get("properties", {})
    target_url_raw = properties.get("target-url", {}).get("value", "")

    # Catalog override
    if catalog:
        catalogs = ibm_cfg.get("catalogs", {})
        cat_props = catalogs.get(catalog, {}).get("properties", {})
        if "target-url" in cat_props:
            target_url_raw = cat_props["target-url"]

    # Assembly invoke – may append a sub-path
    invoke_path = ""
    assembly = ibm_cfg.get("assembly", {})
    for step in assembly.get("execute", []):
        if "invoke" in step:
            invoke_target = step["invoke"].get("target-url", "")
            # Replace IBM variable references like $(target-url)
            resolved = re.sub(
                r"\$\(([^)]+)\)",
                lambda m: properties.get(m.group(1), {}).get("value", m.group(0)),
                invoke_target,
            )
            # If the resolved value has a path suffix, capture it
            url_part = extract_url(resolved)
            proto, host, port, path = split_url(url_part)
            if path and path != "/":
                invoke_path = path

    # Fallback to servers block
    if not target_url_raw:
        servers = ibm_spec.get("servers", [])
        if servers:
            target_url_raw = servers[0].get("url", "")

    upstream_url = extract_url(target_url_raw)
    protocol, host, port, base_path = split_url(upstream_url)

    # ── Service ─────────────────────────────────────────────────────
    service = {
        "name": service_name,
        "protocol": protocol,
        "host": host,
        "port": port,
        "path": base_path if base_path != "/" else invoke_path or "/",
        "tags": [f"ibm-migrated", f"version:{api_version}"],
    }

    # ── Routes ──────────────────────────────────────────────────────
    routes = []
    paths = ibm_spec.get("paths", {})
    for path_key, methods_obj in paths.items():
        http_methods = [
            m.upper()
            for m in methods_obj
            if m.lower() in ("get", "post", "put", "patch", "delete", "options", "head")
        ]
        route_name = f"{service_name}-{slugify(path_key)}"
        route = {
            "name": route_name,
            "paths": [path_key],
            "methods": sorted(http_methods),
            "strip_path": False,
            "tags": [f"ibm-migrated"],
        }
        routes.append(route)

    service["routes"] = routes

    # ── Plugins ─────────────────────────────────────────────────────
    plugins = []

    # CORS plugin
    cors_cfg = ibm_cfg.get("cors", {})
    if cors_cfg.get("enabled"):
        origins = cors_cfg.get("allow-origin", "*")
        methods_str = cors_cfg.get("allow-methods", "GET, OPTIONS")
        headers_str = cors_cfg.get("allow-headers", "*")

        cors_origins = [o.strip() for o in origins.split(",") if o.strip()]
        cors_methods = [m.strip() for m in methods_str.split(",") if m.strip()]
        cors_headers = [h.strip() for h in headers_str.split(",") if h.strip()]

        cors_plugin = {
            "name": "cors",
            "config": {
                "origins": cors_origins,
                "methods": cors_methods,
                "headers": cors_headers,
                "exposed_headers": [],
                "max_age": 3600,
                "credentials": False,
            },
            "enabled": True,
            "tags": ["ibm-migrated"],
        }
        plugins.append(cors_plugin)

    # Rate-limiting (sensible default for migrated APIs)
    plugins.append({
        "name": "rate-limiting",
        "config": {
            "minute": 60,
            "policy": "local",
        },
        "enabled": True,
        "tags": ["ibm-migrated"],
    })

    # Request-termination on unmatched – mirrors IBM "enforced" mode
    if ibm_cfg.get("enforced"):
        plugins.append({
            "name": "request-termination",
            "config": {
                "status_code": 403,
                "message": "Forbidden – API enforcement enabled",
            },
            "enabled": False,       # disabled by default; enable if needed
            "tags": ["ibm-migrated"],
        })

    # Key-auth if IBM spec indicates application authentication
    app_auth = ibm_cfg.get("application-authentication", {})
    if app_auth:
        plugins.append({
            "name": "key-auth",
            "config": {
                "key_names": ["apikey"],
                "hide_credentials": True,
            },
            "enabled": True,
            "tags": ["ibm-migrated"],
        })

    service["plugins"] = plugins

    # ── Build final deck config ─────────────────────────────────────
    kong_config = {
        "_format_version": "3.0",
        "_info": {
            "description": (
                f"Auto-generated Kong config migrated from IBM API Connect – "
                f"{info.get('title', 'Unknown')} v{api_version}"
            ),
        },
        "services": [service],
    }

    return kong_config


# ────────────────────────────────────────────────────────────────────
# OAS cleanup (strip IBM extensions) for a clean Kong-compatible spec
# ────────────────────────────────────────────────────────────────────

def strip_ibm_extensions(spec: dict) -> dict:
    """Return a copy of the spec with all x-ibm-* keys removed."""
    cleaned = {}
    for key, value in spec.items():
        if key.startswith("x-ibm"):
            continue
        if isinstance(value, dict):
            cleaned[key] = strip_ibm_extensions(value)
        elif isinstance(value, list):
            cleaned[key] = [
                strip_ibm_extensions(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            cleaned[key] = value
    return cleaned


# ────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"Error: file not found – {input_path}")
        sys.exit(1)

    with open(input_path, "r") as f:
        ibm_spec = yaml.safe_load(f)

    ibm_cfg = ibm_spec.get("x-ibm-configuration", {})
    catalogs = ibm_cfg.get("catalogs", {})

    # Determine output directory
    if len(sys.argv) >= 3:
        out_dir = Path(sys.argv[2])
    else:
        out_dir = input_path.parent / "kong-output"
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. Generate Kong deck config (default / no catalog) ─────────
    kong_cfg = build_kong_config(ibm_spec)
    default_out = out_dir / f"kong-{input_path.stem}.yaml"
    with open(default_out, "w") as f:
        yaml.dump(kong_cfg, f, default_flow_style=False, sort_keys=False)
    print(f"[✓] Kong config (default)  → {default_out}")

    # ── 2. Generate per-catalog overrides ───────────────────────────
    for catalog_name in catalogs:
        cat_cfg = build_kong_config(ibm_spec, catalog=catalog_name)
        cat_out = out_dir / f"kong-{input_path.stem}-{catalog_name}.yaml"
        with open(cat_out, "w") as f:
            yaml.dump(cat_cfg, f, default_flow_style=False, sort_keys=False)
        print(f"[✓] Kong config ({catalog_name:>10s}) → {cat_out}")

    # ── 3. Produce a clean OAS without IBM extensions ───────────────
    clean_spec = strip_ibm_extensions(ibm_spec)
    clean_out = out_dir / f"oas-clean-{input_path.stem}.yaml"
    with open(clean_out, "w") as f:
        yaml.dump(clean_spec, f, default_flow_style=False, sort_keys=False)
    print(f"[✓] Clean OAS (no x-ibm)  → {clean_out}")

    # ── Summary ─────────────────────────────────────────────────────
    print("\n── Migration summary ──")
    print(f"  Service name : {kong_cfg['services'][0]['name']}")
    print(f"  Upstream     : {kong_cfg['services'][0]['protocol']}://"
          f"{kong_cfg['services'][0]['host']}:{kong_cfg['services'][0]['port']}"
          f"{kong_cfg['services'][0]['path']}")
    print(f"  Routes       : {len(kong_cfg['services'][0]['routes'])}")
    print(f"  Plugins      : {', '.join(p['name'] for p in kong_cfg['services'][0]['plugins'])}")
    if catalogs:
        print(f"  Catalogs     : {', '.join(catalogs.keys())}")
    print(f"\nFiles written to: {out_dir}/")


if __name__ == "__main__":
    main()
