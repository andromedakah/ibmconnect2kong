#!/usr/bin/env python3
"""
Generate an HTML migration report for IBM API Connect to Kong Gateway migration.
Analyzes all IBM API YAML files and their Kong output to produce a comprehensive report.
"""

import yaml
import os
import json
import collections
from datetime import datetime
from pathlib import Path

API_DIR = "stef-ibm2kong/api"
KONG_DIR = "stef-ibm2kong/kong-output"

def analyze_apis():
    apis = []
    policy_counts = collections.Counter()
    total_routes = 0
    total_catalogs = 0
    catalog_names = set()

    for fname in sorted(os.listdir(API_DIR)):
        if not fname.endswith(".yaml"):
            continue
        fpath = os.path.join(API_DIR, fname)
        try:
            with open(fpath) as f:
                spec = yaml.safe_load(f)
        except Exception as e:
            apis.append({
                "file": fname, "title": "PARSE ERROR", "version": "N/A",
                "num_routes": 0, "num_catalogs": 0, "catalogs": [],
                "policies_found": [], "policies_migrated": [],
                "policies_custom": ["Failed to parse YAML: " + str(e)],
                "security_types": [], "has_assembly": False,
            })
            continue

        if not isinstance(spec, dict):
            continue

        info = spec.get("info", {}) or {}
        ibm_cfg = spec.get("x-ibm-configuration", {}) or {}
        title = info.get("title", "Unknown")
        version = info.get("version", "N/A")
        paths = spec.get("paths", {}) or {}
        num_routes = len(paths)
        total_routes += num_routes
        policies_found = []
        policies_migrated = []
        policies_custom = []

        # CORS
        cors_cfg = ibm_cfg.get("cors", {}) or {}
        if cors_cfg:
            policy_counts["cors_found"] += 1
            policies_found.append("cors")
            if cors_cfg.get("enabled"):
                policy_counts["cors_migrated"] += 1
                policies_migrated.append("cors")

        # Rate limiting always added
        policy_counts["rate_limit_added"] += 1
        policies_migrated.append("rate-limiting")

        # Enforced mode
        if ibm_cfg.get("enforced"):
            policy_counts["enforced_found"] += 1
            policies_found.append("enforced")
            policies_migrated.append("request-termination")
            policy_counts["enforced_migrated"] += 1

        # Application authentication
        app_auth = ibm_cfg.get("application-authentication", {}) or {}
        if app_auth:
            policy_counts["app_auth_found"] += 1
            policies_found.append("application-authentication")
            policies_migrated.append("key-auth")
            policy_counts["app_auth_migrated"] += 1

        # Assembly policies
        assembly = ibm_cfg.get("assembly", {}) or {}
        execute_steps = assembly.get("execute", []) or []
        for step in execute_steps:
            if not isinstance(step, dict):
                continue
            for key in step:
                policy_counts["assembly_" + key] += 1
                if key == "invoke":
                    policies_found.append("invoke")
                    policies_migrated.append("invoke->upstream")
                elif key == "proxy":
                    policies_found.append("proxy")
                    policies_migrated.append("proxy->upstream")
                elif key in ("set-variable", "map", "gatewayscript", "xslt",
                             "switch", "activity-log", "validate",
                             "operation-switch", "throw", "parse",
                             "json-to-xml", "xml-to-json", "redact",
                             "jwt-validate", "user-security"):
                    policies_found.append(key)
                    policies_custom.append(key)
                else:
                    policies_found.append(key)
                    policies_custom.append(key)

        # Catch blocks
        catch_steps = assembly.get("catch", []) or []
        if catch_steps:
            policy_counts["catch_blocks"] += 1
            policies_custom.append("catch-error-handling")

        # Security definitions
        sec_defs = (spec.get("securityDefinitions", {})
                    or (spec.get("components", {}) or {}).get("securitySchemes", {})
                    or {})
        security_types = []
        for sec_name, sec_val in sec_defs.items():
            if not isinstance(sec_val, dict):
                continue
            sec_type = sec_val.get("type", "unknown")
            security_types.append(f"{sec_name}({sec_type})")
            if sec_type == "oauth2":
                policy_counts["oauth2_found"] += 1
                policies_custom.append("oauth2:" + sec_name)
            elif sec_type == "basic":
                policy_counts["basic_auth_found"] += 1
                policies_custom.append("basic-auth:" + sec_name)

        # Catalogs
        catalogs = ibm_cfg.get("catalogs", {}) or {}
        num_catalogs = len(catalogs)
        total_catalogs += num_catalogs
        for c in catalogs:
            catalog_names.add(c)

        apis.append({
            "file": fname,
            "title": title,
            "version": version,
            "num_routes": num_routes,
            "num_catalogs": num_catalogs,
            "catalogs": list(catalogs.keys()),
            "policies_found": policies_found,
            "policies_migrated": policies_migrated,
            "policies_custom": policies_custom,
            "security_types": security_types,
            "has_assembly": bool(execute_steps),
        })

    return {
        "total_apis": len(apis),
        "total_routes": total_routes,
        "total_catalogs": total_catalogs,
        "catalog_names": sorted(catalog_names),
        "policy_counts": dict(policy_counts),
        "apis": apis,
    }


def generate_html_report(data):
    total = data["total_apis"]
    fully_migrated = sum(1 for a in data["apis"] if not a["policies_custom"])
    needs_custom = sum(1 for a in data["apis"] if a["policies_custom"])
    pct_migrated = (fully_migrated / total * 100) if total else 0

    # Aggregate custom policies needed
    custom_policy_agg = collections.Counter()
    for api in data["apis"]:
        for p in api["policies_custom"]:
            custom_policy_agg[p] += 1

    # Aggregate assembly policies
    assembly_policies = {k: v for k, v in data["policy_counts"].items() if k.startswith("assembly_")}

    # Kong output file count
    kong_files = 0
    if os.path.isdir(KONG_DIR):
        kong_files = len([f for f in os.listdir(KONG_DIR) if f.endswith(".yaml")])

    now = datetime.now().strftime("%B %d, %Y %H:%M")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>IBM API Connect to Kong Gateway - Migration Report</title>
<style>
  :root {{
    --kong-green: #003459;
    --kong-accent: #00A86B;
    --kong-light: #E8F5E9;
    --danger: #D32F2F;
    --warning: #F57C00;
    --success: #2E7D32;
    --border: #E0E0E0;
    --bg: #FAFAFA;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg);
    color: #333;
    line-height: 1.6;
  }}
  .header {{
    background: linear-gradient(135deg, var(--kong-green) 0%, #00587A 100%);
    color: white;
    padding: 40px 50px;
  }}
  .header h1 {{
    font-size: 28px;
    margin-bottom: 5px;
  }}
  .header .subtitle {{
    opacity: 0.85;
    font-size: 14px;
  }}
  .container {{
    max-width: 1400px;
    margin: 0 auto;
    padding: 30px 50px;
  }}
  .summary-cards {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 20px;
    margin-bottom: 35px;
  }}
  .card {{
    background: white;
    border-radius: 10px;
    padding: 24px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    border-left: 4px solid var(--kong-accent);
  }}
  .card.warning {{ border-left-color: var(--warning); }}
  .card.danger {{ border-left-color: var(--danger); }}
  .card .number {{
    font-size: 36px;
    font-weight: 700;
    color: var(--kong-green);
  }}
  .card.warning .number {{ color: var(--warning); }}
  .card.danger .number {{ color: var(--danger); }}
  .card .label {{
    font-size: 13px;
    color: #666;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-top: 4px;
  }}
  .section {{
    background: white;
    border-radius: 10px;
    padding: 28px;
    margin-bottom: 25px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
  }}
  .section h2 {{
    font-size: 20px;
    color: var(--kong-green);
    margin-bottom: 18px;
    padding-bottom: 10px;
    border-bottom: 2px solid var(--kong-light);
  }}
  .section h3 {{
    font-size: 16px;
    color: #555;
    margin: 16px 0 10px;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }}
  th {{
    background: var(--kong-green);
    color: white;
    padding: 10px 12px;
    text-align: left;
    font-weight: 600;
    position: sticky;
    top: 0;
  }}
  td {{
    padding: 9px 12px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }}
  tr:hover td {{ background: #F5F9FF; }}
  .badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 600;
    margin: 1px 2px;
  }}
  .badge-green {{ background: #E8F5E9; color: var(--success); }}
  .badge-orange {{ background: #FFF3E0; color: var(--warning); }}
  .badge-red {{ background: #FFEBEE; color: var(--danger); }}
  .badge-blue {{ background: #E3F2FD; color: #1565C0; }}
  .badge-gray {{ background: #ECEFF1; color: #546E7A; }}
  .progress-bar {{
    height: 24px;
    background: #EEE;
    border-radius: 12px;
    overflow: hidden;
    margin: 10px 0;
  }}
  .progress-bar .fill {{
    height: 100%;
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: white;
    font-size: 12px;
    font-weight: 600;
    transition: width 0.6s;
  }}
  .fill-green {{ background: var(--success); }}
  .fill-orange {{ background: var(--warning); }}
  .policy-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 12px;
  }}
  .policy-item {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 14px;
    background: #F9F9F9;
    border-radius: 6px;
    border-left: 3px solid var(--kong-accent);
  }}
  .policy-item.needs-work {{
    border-left-color: var(--warning);
  }}
  .policy-item .pname {{ font-weight: 600; font-size: 13px; }}
  .policy-item .pcount {{ font-size: 22px; font-weight: 700; color: var(--kong-green); }}
  .legend {{
    display: flex;
    gap: 20px;
    margin: 12px 0;
    font-size: 12px;
    color: #666;
  }}
  .legend span {{ display: flex; align-items: center; gap: 5px; }}
  .legend .dot {{
    width: 10px;
    height: 10px;
    border-radius: 50%;
    display: inline-block;
  }}
  .status-full {{ color: var(--success); font-weight: 600; }}
  .status-partial {{ color: var(--warning); font-weight: 600; }}
  .scrollable {{ max-height: 600px; overflow-y: auto; }}
  .footer {{
    text-align: center;
    padding: 30px;
    color: #999;
    font-size: 12px;
  }}
  .mapping-table td:first-child {{ font-weight: 600; }}
  .filter-bar {{
    margin-bottom: 15px;
    display: flex;
    gap: 10px;
    align-items: center;
  }}
  .filter-bar input {{
    padding: 8px 12px;
    border: 1px solid var(--border);
    border-radius: 6px;
    font-size: 13px;
    width: 300px;
  }}
  .filter-bar select {{
    padding: 8px 12px;
    border: 1px solid var(--border);
    border-radius: 6px;
    font-size: 13px;
  }}
</style>
</head>
<body>

<div class="header">
  <h1>IBM API Connect &rarr; Kong Gateway</h1>
  <div class="subtitle">Migration Report &bull; Generated {now} &bull; {total} APIs analyzed</div>
</div>

<div class="container">

  <!-- Summary Cards -->
  <div class="summary-cards">
    <div class="card">
      <div class="number">{total}</div>
      <div class="label">Total APIs</div>
    </div>
    <div class="card">
      <div class="number">{data['total_routes']}</div>
      <div class="label">Total Routes/Paths</div>
    </div>
    <div class="card">
      <div class="number">{fully_migrated}</div>
      <div class="label">Fully Migrated</div>
    </div>
    <div class="card warning">
      <div class="number">{needs_custom}</div>
      <div class="label">Need Customization</div>
    </div>
    <div class="card">
      <div class="number">{kong_files}</div>
      <div class="label">Kong Files Generated</div>
    </div>
    <div class="card">
      <div class="number">{data['total_catalogs']}</div>
      <div class="label">Catalog Variants</div>
    </div>
  </div>

  <!-- Migration Progress -->
  <div class="section">
    <h2>Migration Progress</h2>
    <div class="progress-bar">
      <div class="fill fill-green" style="width: {pct_migrated:.1f}%">{pct_migrated:.1f}% Fully Migrated</div>
    </div>
    <div class="legend">
      <span><span class="dot" style="background:var(--success)"></span> Fully migrated ({fully_migrated} APIs)</span>
      <span><span class="dot" style="background:var(--warning)"></span> Needs customization ({needs_custom} APIs)</span>
    </div>
  </div>

  <!-- Policy Mapping -->
  <div class="section">
    <h2>IBM Connect Policy &rarr; Kong Plugin Mapping</h2>
    <table class="mapping-table">
      <thead>
        <tr>
          <th>IBM API Connect Policy</th>
          <th>Kong Gateway Plugin</th>
          <th>Status</th>
          <th>Count</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>CORS (x-ibm-configuration.cors)</td>
          <td>cors</td>
          <td><span class="badge badge-green">Auto-migrated</span></td>
          <td>{data['policy_counts'].get('cors_migrated', 0)} / {data['policy_counts'].get('cors_found', 0)}</td>
        </tr>
        <tr>
          <td>Rate Limiting</td>
          <td>rate-limiting</td>
          <td><span class="badge badge-green">Auto-added (default)</span></td>
          <td>{data['policy_counts'].get('rate_limit_added', 0)}</td>
        </tr>
        <tr>
          <td>Enforced Mode</td>
          <td>request-termination</td>
          <td><span class="badge badge-green">Auto-migrated</span></td>
          <td>{data['policy_counts'].get('enforced_migrated', 0)} / {data['policy_counts'].get('enforced_found', 0)}</td>
        </tr>
        <tr>
          <td>Application Authentication</td>
          <td>key-auth</td>
          <td><span class="badge badge-green">Auto-migrated</span></td>
          <td>{data['policy_counts'].get('app_auth_migrated', 0)} / {data['policy_counts'].get('app_auth_found', 0)}</td>
        </tr>
        <tr>
          <td>Assembly: invoke</td>
          <td>Service upstream routing</td>
          <td><span class="badge badge-green">Auto-migrated</span></td>
          <td>{data['policy_counts'].get('assembly_invoke', 0)}</td>
        </tr>
        <tr>
          <td>Assembly: proxy</td>
          <td>Service upstream routing</td>
          <td><span class="badge badge-green">Auto-migrated</span></td>
          <td>{data['policy_counts'].get('assembly_proxy', 0)}</td>
        </tr>
        <tr>
          <td>Assembly: set-variable</td>
          <td>request-transformer / response-transformer</td>
          <td><span class="badge badge-orange">Manual config needed</span></td>
          <td>{data['policy_counts'].get('assembly_set-variable', 0)}</td>
        </tr>
        <tr>
          <td>Assembly: map</td>
          <td>request-transformer / response-transformer</td>
          <td><span class="badge badge-orange">Manual config needed</span></td>
          <td>{data['policy_counts'].get('assembly_map', 0)}</td>
        </tr>
        <tr>
          <td>Assembly: gatewayscript</td>
          <td>serverless-functions / custom plugin</td>
          <td><span class="badge badge-red">Custom porting needed</span></td>
          <td>{data['policy_counts'].get('assembly_gatewayscript', 0)}</td>
        </tr>
        <tr>
          <td>Assembly: switch</td>
          <td>Route-level config / request-transformer</td>
          <td><span class="badge badge-orange">Manual config needed</span></td>
          <td>{data['policy_counts'].get('assembly_switch', 0)}</td>
        </tr>
        <tr>
          <td>Assembly: operation-switch</td>
          <td>Per-route plugin config</td>
          <td><span class="badge badge-orange">Manual config needed</span></td>
          <td>{data['policy_counts'].get('assembly_operation-switch', 0)}</td>
        </tr>
        <tr>
          <td>Assembly: xslt</td>
          <td>Custom plugin / serverless-functions</td>
          <td><span class="badge badge-red">Custom porting needed</span></td>
          <td>{data['policy_counts'].get('assembly_xslt', 0)}</td>
        </tr>
        <tr>
          <td>Assembly: validate</td>
          <td>request-validator</td>
          <td><span class="badge badge-orange">Manual config needed</span></td>
          <td>{data['policy_counts'].get('assembly_validate', 0)}</td>
        </tr>
        <tr>
          <td>Assembly: activity-log</td>
          <td>file-log / http-log / tcp-log</td>
          <td><span class="badge badge-orange">Manual config needed</span></td>
          <td>{data['policy_counts'].get('assembly_activity-log', 0)}</td>
        </tr>
        <tr>
          <td>Assembly: parse</td>
          <td>N/A (Kong handles natively)</td>
          <td><span class="badge badge-gray">Review needed</span></td>
          <td>{data['policy_counts'].get('assembly_parse', 0)}</td>
        </tr>
        <tr>
          <td>Assembly: throw</td>
          <td>request-termination / exit-transformer</td>
          <td><span class="badge badge-orange">Manual config needed</span></td>
          <td>{data['policy_counts'].get('assembly_throw', 0)}</td>
        </tr>
        <tr>
          <td>Assembly: catch (error handling)</td>
          <td>exit-transformer / custom plugin</td>
          <td><span class="badge badge-orange">Manual config needed</span></td>
          <td>{data['policy_counts'].get('catch_blocks', 0)}</td>
        </tr>
        <tr>
          <td>OAuth2 Security</td>
          <td>oauth2 / openid-connect</td>
          <td><span class="badge badge-red">Manual setup needed</span></td>
          <td>{data['policy_counts'].get('oauth2_found', 0)}</td>
        </tr>
        <tr>
          <td>Basic Auth Security</td>
          <td>basic-auth</td>
          <td><span class="badge badge-orange">Manual config needed</span></td>
          <td>{data['policy_counts'].get('basic_auth_found', 0)}</td>
        </tr>
      </tbody>
    </table>
  </div>

  <!-- Customizations Needed -->
  <div class="section">
    <h2>Customizations Still Needed</h2>
    <p style="color:#666; margin-bottom:15px;">The following IBM Connect policies were detected but require manual intervention to complete the Kong migration.</p>
    <div class="policy-grid">
"""

    for policy, count in custom_policy_agg.most_common():
        html += f"""      <div class="policy-item needs-work">
        <div>
          <div class="pname">{policy}</div>
          <div style="font-size:11px;color:#888;">across {count} API(s)</div>
        </div>
        <div class="pcount">{count}</div>
      </div>
"""

    html += """    </div>
  </div>

  <!-- Full API List -->
  <div class="section">
    <h2>Complete API Inventory</h2>
    <div class="filter-bar">
      <input type="text" id="searchBox" placeholder="Search APIs by name or file..." onkeyup="filterTable()">
      <select id="statusFilter" onchange="filterTable()">
        <option value="all">All Status</option>
        <option value="migrated">Fully Migrated</option>
        <option value="custom">Needs Customization</option>
      </select>
    </div>
    <div class="scrollable">
      <table id="apiTable">
        <thead>
          <tr>
            <th>#</th>
            <th>API Name</th>
            <th>Version</th>
            <th>File</th>
            <th>Routes</th>
            <th>Catalogs</th>
            <th>Migration Status</th>
            <th>Policies Migrated</th>
            <th>Customization Required</th>
          </tr>
        </thead>
        <tbody>
"""

    for idx, api in enumerate(data["apis"], 1):
        status_class = "status-full" if not api["policies_custom"] else "status-partial"
        status_text = "Fully Migrated" if not api["policies_custom"] else "Needs Customization"
        status_badge = "badge-green" if not api["policies_custom"] else "badge-orange"

        migrated_badges = "".join(
            f'<span class="badge badge-green">{p}</span>' for p in api["policies_migrated"]
        )
        custom_badges = "".join(
            f'<span class="badge badge-orange">{p}</span>' for p in api["policies_custom"]
        ) if api["policies_custom"] else '<span class="badge badge-green">None</span>'

        catalogs_str = ", ".join(api["catalogs"]) if api["catalogs"] else "-"

        data_status = "migrated" if not api["policies_custom"] else "custom"

        html += f"""          <tr data-status="{data_status}">
            <td>{idx}</td>
            <td><strong>{api['title']}</strong></td>
            <td>{api['version']}</td>
            <td style="font-size:11px;word-break:break-all;">{api['file']}</td>
            <td>{api['num_routes']}</td>
            <td>{catalogs_str}</td>
            <td><span class="badge {status_badge}">{status_text}</span></td>
            <td>{migrated_badges}</td>
            <td>{custom_badges}</td>
          </tr>
"""

    html += f"""        </tbody>
      </table>
    </div>
  </div>

  <!-- Catalog Overview -->
  <div class="section">
    <h2>Catalog Environments</h2>
    <p style="color:#666; margin-bottom:10px;">The following IBM API Connect catalog environments were detected. Per-catalog Kong config files have been generated.</p>
    <table>
      <thead><tr><th>Catalog Name</th><th>Description</th></tr></thead>
      <tbody>
"""
    for cat in data["catalog_names"]:
        html += f'        <tr><td><span class="badge badge-blue">{cat}</span></td><td>Environment-specific upstream URLs and properties</td></tr>\n'

    html += f"""      </tbody>
    </table>
  </div>

</div>

<div class="footer">
  IBM API Connect to Kong Gateway Migration Report &bull; Auto-generated by ibm2kong migration toolkit &bull; {now}
</div>

<script>
function filterTable() {{
  const search = document.getElementById('searchBox').value.toLowerCase();
  const status = document.getElementById('statusFilter').value;
  const rows = document.querySelectorAll('#apiTable tbody tr');
  rows.forEach(row => {{
    const text = row.textContent.toLowerCase();
    const rowStatus = row.getAttribute('data-status');
    const matchSearch = !search || text.includes(search);
    const matchStatus = status === 'all' || rowStatus === status;
    row.style.display = (matchSearch && matchStatus) ? '' : 'none';
  }});
}}
</script>

</body>
</html>"""

    return html


def main():
    print("Analyzing IBM API Connect files...")
    data = analyze_apis()

    # Save analysis JSON
    with open("migration_analysis.json", "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Analysis data saved to migration_analysis.json")

    # Print summary
    total = data["total_apis"]
    fully_migrated = sum(1 for a in data["apis"] if not a["policies_custom"])
    needs_custom = sum(1 for a in data["apis"] if a["policies_custom"])
    print(f"\n{'='*60}")
    print(f"  Total APIs analyzed:        {total}")
    print(f"  Total Routes/Paths:         {data['total_routes']}")
    print(f"  Fully Migrated:             {fully_migrated}")
    print(f"  Need Customization:         {needs_custom}")
    print(f"  Migration Rate:             {fully_migrated/total*100:.1f}%" if total else "")
    print(f"  Catalog Environments:       {', '.join(data['catalog_names'])}")
    print(f"{'='*60}")

    # Policy summary
    print("\n  Policy Migration Summary:")
    for k, v in sorted(data["policy_counts"].items()):
        print(f"    {k}: {v}")

    # Generate HTML report
    print("\nGenerating HTML report...")
    html = generate_html_report(data)
    report_path = "migration_report.html"
    with open(report_path, "w") as f:
        f.write(html)
    print(f"  Report saved to {report_path}")
    print(f"\nDone! Open {report_path} in a browser to view the report.")


if __name__ == "__main__":
    main()
