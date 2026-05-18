#!/usr/bin/env python3
"""Add version suffix to service and route names in all catalog YAML files."""
import yaml
import os
import re

KONG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "stef-ibm2kong", "kong3.0")

CATALOGS = [
    "QUA", "dev", "dev.target-url", "ext", "for", "int",
    "ppr", "prd", "qua", "quaext", "rec", "sandbox", "sec", "test",
]

# Build regex alternation from catalog names (escape dots)
catalog_pattern = "|".join(re.escape(c) for c in CATALOGS)
FILE_RE = re.compile(
    rf"^kong-(.+)-(\d+\.\d+\.\d+)-({catalog_pattern})\.yaml$"
)

svc_count = 0
route_count = 0
file_count = 0
for fname in sorted(os.listdir(KONG_DIR)):
    if not fname.endswith(".yaml"):
        continue
    m = FILE_RE.match(fname)
    if not m:
        continue
    base_name = m.group(1)
    version = m.group(2)
    catalog = m.group(3)

    fpath = os.path.join(KONG_DIR, fname)
    with open(fpath) as f:
        data = yaml.safe_load(f)
    if not data or "services" not in data:
        continue

    changed = False

    for svc in data["services"]:
        # --- Service ---
        name = svc.get("name", "")
        if name and not name.endswith(version):
            svc["name"] = name + "-" + version
            svc_count += 1
            changed = True

        # --- Routes: use the same version as the service ---
        for route in svc.get("routes", []):
            rname = route.get("name", "")
            if rname and not rname.endswith(version):
                route["name"] = rname + "-" + version
                route_count += 1
                changed = True

    if changed:
        with open(fpath, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        file_count += 1
        print(f"  [{catalog}] {fname}: {base_name} -> {base_name}-{version}")

print(f"\nUpdated {file_count} files ({svc_count} services, {route_count} routes)")
