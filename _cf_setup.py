#!/usr/bin/env python3
"""Add custom domain to Cloudflare Pages project."""
import json, subprocess, re, sys

# Read token from wrangler config (never hardcode it)
config_path = r"C:\Users\admin\AppData\Roaming\xdg.config\.wrangler\config\default.toml"
with open(config_path) as f:
    content = f.read()
m = re.search(r'oauth_token\s*=\s*"([^"]+)"', content)
if not m:
    print("ERROR: Could not read oauth_token from wrangler config", file=sys.stderr)
    sys.exit(1)
token = m.group(1)

account_id = "8a6eff0c024ed9f19246be71bba94d19"
project = "neo-blog"
domain = "skychat.eu.org"

headers = [
    f"Authorization: Bearer {token}",
    "Content-Type: application/json"
]

# Step 1: Check if domain exists in Cloudflare zones
r = subprocess.run(
    ["curl", "-s", "-X", "GET",
     f"https://api.cloudflare.com/client/v4/zones?name={domain}",
     "-H", headers[0], "-H", headers[1]],
    capture_output=True, text=True, timeout=30
)
data = json.loads(r.stdout)
print(f"[1] Zone lookup: success={data.get('success')}, count={len(data.get('result',[]))}")

if data.get('result'):
    zone_id = data['result'][0]['id']
    print(f"    Zone exists: {data['result'][0]['name']} (ID: {zone_id}), Status: {data['result'][0]['status']}")
else:
    # List all zones to see what's available
    r2 = subprocess.run(
        ["curl", "-s", "-X", "GET",
         "https://api.cloudflare.com/client/v4/zones",
         "-H", headers[0], "-H", headers[1]],
        capture_output=True, text=True, timeout=30
    )
    data2 = json.loads(r2.stdout)
    print(f"    Domain not found in Cloudflare. Existing zones ({len(data2.get('result',[]))}):")
    for z in data2.get('result', []):
        print(f"      - {z['name']} (Status: {z['status']})")
    if data2.get('errors'):
        for e in data2['errors']:
            print(f"    API Error: {e}")

# Step 2: Try to add custom domain to Pages project
print(f"\n[2] Adding '{domain}' to Pages project '{project}'...")
r3 = subprocess.run(
    ["curl", "-s", "-X", "POST",
     f"https://api.cloudflare.com/client/v4/accounts/{account_id}/pages/projects/{project}/domains",
     "-H", headers[0], "-H", headers[1],
     "-d", json.dumps({"name": domain})],
    capture_output=True, text=True, timeout=30
)

try:
    data3 = json.loads(r3.stdout)
    if data3.get('success'):
        result = data3['result']
        print(f"    OK! Domain: {result.get('name')}")
        print(f"    Status: {result.get('status')}")
        if result.get('verification_data'):
            print(f"    Verification data: {result['verification_data']}")
    else:
        print(f"    Failed. Errors:")
        for e in data3.get('errors', []):
            code = e.get('code', '')
            msg = e.get('message', '')
            print(f"      [{code}] {msg}")
        # Print full response for debugging
        print(f"    Full: {json.dumps(data3, indent=2)}")
except json.JSONDecodeError:
        print(f"    Could not parse response: {r3.stdout[:500]}")
