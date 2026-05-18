#!/usr/bin/env python3
"""Remove _info and description fields from all Kong YAML files in kong-output/."""
import yaml
import os

DEV_DIR = os.path.join(os.path.dirname(__file__), "stef-ibm2kong", "kong-output")

def strip_fields(obj):
    """Recursively remove 'description' keys from dicts."""
    if isinstance(obj, dict):
        return {k: strip_fields(v) for k, v in obj.items() if k != "description"}
    elif isinstance(obj, list):
        return [strip_fields(item) for item in obj]
    return obj

count = 0
for fname in sorted(os.listdir(DEV_DIR)):
    if not fname.endswith(".yaml"):
        continue
    fpath = os.path.join(DEV_DIR, fname)
    with open(fpath) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        continue

    # Remove top-level _info
    data.pop("_info", None)

    # Remove all description fields recursively
    data = strip_fields(data)

    with open(fpath, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    count += 1

print(f"Cleaned {count} files in kong-output/")
