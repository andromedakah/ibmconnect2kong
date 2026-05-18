# ibmconnect2kong

A Python toolkit for migrating APIs from **IBM API Connect** to **Kong Gateway** (decK declarative format).

## Overview

This toolset converts IBM API Connect OpenAPI specs (enriched with `x-ibm-configuration`) into Kong-compatible declarative YAML files, and provides utilities to clean, organise, and report on the migration.

## Scripts

### `ibm2kong.py` — Core converter

Reads an IBM API Connect OAS spec and produces one or more Kong decK YAML files.

**What it does:**
- Extracts the upstream target URL from `x-ibm-configuration` properties, assembly `invoke` steps, or the `servers` block (in that priority order)
- Generates a Kong **Service** and **Routes** (one per API path)
- Maps IBM policies to Kong plugins:

| IBM policy | Kong plugin |
|---|---|
| `cors` (when enabled) | `cors` |
| *(always added)* | `rate-limiting` (60 req/min default) |
| `enforced` mode | `request-termination` (disabled by default) |
| `application-authentication` | `key-auth` |
- Generates **per-catalog variants** (e.g. sandbox, production) using catalog property overrides from `x-ibm-configuration.catalogs`
- Produces a **clean OAS** file with all `x-ibm-*` extensions stripped

**Usage:**

```bash
python3 ibm2kong.py <input_ibm_oas.yaml> [output_directory]
```

If no output directory is given, files are written to `kong-output/` next to the input file.

**Output files per input spec:**
- `kong-<name>.yaml` — default (no catalog override)
- `kong-<name>-<catalog>.yaml` — one file per catalog defined in the spec
- `oas-clean-<name>.yaml` — IBM-extension-free OpenAPI spec

---

### `generate_report.py` — HTML migration report

Analyses all IBM API YAML files and their generated Kong output to produce an interactive HTML report (`migration_report.html`).

**Report includes:**
- Total APIs, routes, and catalogs processed
- Migration coverage: fully migrated vs. APIs requiring custom work
- Per-API breakdown of policies found, migrated, and needing custom handling
- Assembly policy inventory (invoke, proxy, gatewayscript, xslt, etc.)
- Security scheme analysis (OAuth2, basic auth, etc.)

**Usage:**

```bash
python3 generate_report.py
```

Reads from `stef-ibm2kong/api/` and `stef-ibm2kong/kong-output/`. Output is written to `migration_report.html`.

---

### `organize_output.py` — Sort output by catalog

Copies generated Kong YAML files from `stef-ibm2kong/kong3.0/` into subdirectories named after the catalog suffix.

**Recognised catalog suffixes:** `dev`, `ext`, `for`, `int`, `ppr`, `prd`, `qua`, `quaext`, `rec`, `sandbox`, `sec`, `test`

Files not matching any suffix (including `oas-clean-*` files) go into `default/`.

**Usage:**

```bash
python3 organize_output.py
```

---

### `sanitize_output.py` — Clean Kong YAML files

Removes the `_info` block and all `description` fields from every Kong YAML file in `stef-ibm2kong/kong-output/`. Useful before importing into Kong to reduce noise.

**Usage:**

```bash
python3 sanitize_output.py
```

---

### `suffix_services-routes_versions.py` — Append version to names

Appends the API version string to the `name` field of every service and route in the catalog-specific YAML files under `stef-ibm2kong/kong3.0/`, ensuring uniqueness across versions.

**Usage:**

```bash
python3 suffix_services-routes_versions.py
```

---

## Prerequisites

- Python 3.10+
- [`PyYAML`](https://pypi.org/project/PyYAML/)

```bash
pip install pyyaml
```

## Typical workflow

```
# 1. Convert a single IBM spec
python3 ibm2kong.py path/to/my-api.yaml

# 2. Run the converter over all specs in a directory (bash loop)
for f in stef-ibm2kong/api/*.yaml; do python3 ibm2kong.py "$f" stef-ibm2kong/kong-output; done

# 3. Append version suffixes to service/route names
python3 suffix_services-routes_versions.py

# 4. Remove noise from generated files
python3 sanitize_output.py

# 5. Organise files by catalog
python3 organize_output.py

# 6. Generate the HTML migration report
python3 generate_report.py
```

## Output format

All generated Kong YAML files use **decK format version 3.0** and are tagged with `ibm-migrated` for easy identification.

```yaml
_format_version: "3.0"
services:
  - name: my-api
    protocol: https
    host: backend.example.com
    port: 443
    path: /
    tags: [ibm-migrated, "version:1.0.0"]
    routes:
      - name: my-api-v1-users
        paths: [/v1/users]
        methods: [GET, POST]
        strip_path: false
    plugins:
      - name: rate-limiting
        config:
          minute: 60
          policy: local
```
