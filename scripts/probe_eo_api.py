#!/usr/bin/env python3
"""Probe Elections Ontario website to discover API endpoints and download URLs."""
import urllib.request, ssl, re, json, os, sys

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "raw-data", "elections-ontario")
os.makedirs(OUTPUT_DIR, exist_ok=True)

ctx = ssl.create_default_context()

def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"})
    try:
        resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
        return resp.status, resp.read()
    except Exception as e:
        return None, str(e).encode()

# Step 1: Fetch main downloads page
print("Fetching https://finances.elections.on.ca/en/downloads ...")
status, body = fetch("https://finances.elections.on.ca/en/downloads")
if status != 200:
    print(f"Failed: status={status}")
    sys.exit(1)

html = body.decode("utf-8", errors="replace")

# Save raw HTML for inspection
with open(os.path.join(OUTPUT_DIR, "downloads-page.html"), "w") as f:
    f.write(html)
print(f"Saved HTML ({len(html)} chars)")

# Parse out useful info
scripts = re.findall(r'<script[^>]*src=["\']([^"\']+)["\']', html)
print(f"\n=== SCRIPT SOURCES ({len(scripts)}) ===")
for s in scripts:
    print(f"  {s}")

apis = re.findall(r'["\']((?:https?://|/api/|/rest/)[^"\']+)["\']', html)
print(f"\n=== API/URL REFERENCES ({len(set(apis))}) ===")
for a in sorted(set(apis)):
    print(f"  {a}")

downloads = re.findall(r'["\'](.*?(?:csv|download|export|bulk|contribution).*?)["\']', html, re.IGNORECASE)
print(f"\n=== DOWNLOAD REFERENCES ({len(set(downloads))}) ===")
for d in sorted(set(downloads)):
    print(f"  {d}")

# Step 2: Try to fetch the Angular app's main JS bundle to find API endpoints
base_url = "https://finances.elections.on.ca"
for script in scripts:
    if "main" in script.lower() or "app" in script.lower():
        url = script if script.startswith("http") else base_url + "/" + script.lstrip("/")
        print(f"\nFetching JS bundle: {url} ...")
        s2, b2 = fetch(url)
        if s2 == 200 and b2:
            js = b2.decode("utf-8", errors="replace")
            # Save the JS
            js_name = os.path.basename(script.split("?")[0])
            with open(os.path.join(OUTPUT_DIR, f"js-{js_name}"), "w") as f:
                f.write(js)
            # Look for API endpoints in the JS
            api_endpoints = re.findall(r'["\'](/api/[^"\']+)["\']', js)
            api_endpoints += re.findall(r'["\']([^"\']*(?:contribution|download|export|financial)[^"\']*)["\']', js, re.IGNORECASE)
            print(f"  Found {len(set(api_endpoints))} API-like references in JS:")
            for ep in sorted(set(api_endpoints))[:50]:
                if len(ep) < 200:
                    print(f"    {ep}")

# Step 3: Try common API patterns based on typical Angular+.NET finance portals
print("\n=== PROBING COMMON API PATTERNS ===")
api_attempts = [
    "/api/v1/contributions",
    "/api/v1/downloads",
    "/api/v1/financial-data/contributions",
    "/api/contributions",
    "/api/downloads",
    "/api/financial-statements",
    "/api/bulk-data",
    "/api/export/contributions",
    "/api/political-finance/contributions",
    "/api/pf/contributions",
    "/api/pf/downloads",
    "/api/pf/bulk",
]
for path in api_attempts:
    url = base_url + path
    s2, b2 = fetch(url, timeout=10)
    ct = ""
    if s2 and b2:
        try:
            # Check if JSON
            j = json.loads(b2)
            ct = "json"
        except:
            if b2[:20].count(b",") > 2:
                ct = "csv-like"
            else:
                ct = f"{len(b2)} bytes"
    print(f"  {path} -> {s2} ({ct})")

print("\nDone. Check raw-data/elections-ontario/ for saved files.")
