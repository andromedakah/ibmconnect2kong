#!/usr/bin/env python3
"""Organize kong-output files into subdirectories by catalog suffix."""
import os
import shutil

KONG_DIR = os.path.join(os.path.dirname(__file__), "stef-ibm2kong", "kong3.0")

SUFFIXES = ["dev", "ext", "for", "int", "ppr", "prd", "qua", "quaext",
            "rec", "sandbox", "sec", "test", "QUA"]
# Sort longest first so 'quaext' matches before 'qua'
SUFFIXES.sort(key=lambda x: -len(x))

counts = {}

for fname in sorted(os.listdir(KONG_DIR)):
    if not fname.endswith(".yaml"):
        continue
    # Skip subdirectories
    full = os.path.join(KONG_DIR, fname)
    if not os.path.isfile(full):
        continue

    # oas-clean files go to default/
    if fname.startswith("oas-clean-"):
        target_dir = "default"
    else:
        matched = None
        for s in SUFFIXES:
            if fname.endswith("-" + s + ".yaml"):
                matched = s
                break
        target_dir = matched if matched else "default"

    dest = os.path.join(KONG_DIR, target_dir)
    os.makedirs(dest, exist_ok=True)
    shutil.copy2(full, os.path.join(dest, fname))
    counts[target_dir] = counts.get(target_dir, 0) + 1

print("Files organized into subdirectories:")
for d in sorted(counts):
    print(f"  {d}/ -> {counts[d]} files")
print(f"\n  Total: {sum(counts.values())} files")
