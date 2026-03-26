#!/usr/bin/env python3
"""Deeper probe of Elections Ontario API based on initial findings."""
import urllib.request, ssl, re, json, os, sys

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "raw-data", "elections-ontario")
ctx = ssl.create_default_context()
BASE = "https://finances.elections.on.ca"

def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json, text/csv, */*"})
    try:
        resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
        return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        body = b""
        try: body = e.read()
        except: pass
        return e.code, {}, body
    except Exception as e:
        return None, {}, str(e).encode()

# 1. Fetch /api/bulk-data which returned 200
print("=== /api/bulk-data ===")
s, h, b = fetch(BASE + "/api/bulk-data")
print(f"Status: {s}, Content-Type: {h.get('Content-Type','')}, Size: {len(b)}")
if b:
    try:
        data = json.loads(b)
        with open(os.path.join(OUTPUT_DIR, "api-bulk-data.json"), "w") as f:
            json.dump(data, f, indent=2)
        print(json.dumps(data, indent=2)[:3000])
    except:
        print(b[:2000].decode("utf-8", errors="replace"))

# 2. Fetch /api/meta/bootstrap (referenced in script tag)
print("\n=== /api/meta/bootstrap ===")
s, h, b = fetch(BASE + "/api/meta/bootstrap")
print(f"Status: {s}, Content-Type: {h.get('Content-Type','')}, Size: {len(b)}")
if b:
    try:
        data = json.loads(b)
        with open(os.path.join(OUTPUT_DIR, "api-meta-bootstrap.json"), "w") as f:
            json.dump(data, f, indent=2)
        print(json.dumps(data, indent=2)[:3000])
    except:
        text = b.decode("utf-8", errors="replace")
        print(text[:2000])

# 3. Fetch environment-settings.js
print("\n=== /assets/environment-settings.js ===")
s, h, b = fetch(BASE + "/assets/environment-settings.js?v=1")
print(f"Status: {s}")
if b:
    text = b.decode("utf-8", errors="replace")
    print(text[:2000])
    with open(os.path.join(OUTPUT_DIR, "environment-settings.js"), "w") as f:
        f.write(text)

# 4. Search the main JS bundle more carefully for API paths
print("\n=== Searching main JS for API paths ===")
js_path = os.path.join(OUTPUT_DIR, "js-main.eaad7c0a58e4e6c8.js")
if os.path.exists(js_path):
    with open(js_path) as f:
        js = f.read()
    # Look for string patterns with /api/
    api_paths = re.findall(r'["\'](/api/[^"\']{3,80})["\']', js)
    print(f"Found {len(api_paths)} /api/ paths:")
    for p in sorted(set(api_paths)):
        print(f"  {p}")

    # Look for download URL patterns
    dl_patterns = re.findall(r'(?:url|href|src|endpoint|path)\s*[:=]\s*["\']([^"\']{5,200})["\']', js, re.IGNORECASE)
    print(f"\nFound {len(set(dl_patterns))} URL-like assignments:")
    for p in sorted(set(dl_patterns)):
        if any(kw in p.lower() for kw in ["api", "download", "contrib", "export", "csv", "bulk"]):
            print(f"  {p}")

    # Look for downloadSettings object patterns
    dl_settings = re.findall(r'download[^{]*\{[^}]{0,500}\}', js, re.IGNORECASE)
    print(f"\nFound {len(dl_settings)} download-related object patterns:")
    for d in dl_settings[:10]:
        if len(d) < 300:
            print(f"  {d}")

# 5. Try variations on bulk-data endpoint
print("\n=== Probing bulk-data variations ===")
for path in [
    "/api/bulk-data/contributions",
    "/api/bulk-data/download",
    "/api/bulk-data/files",
    "/api/bulk-data/list",
    "/api/bulk-data?type=contributions",
    "/api/bulk-data?category=contributions",
]:
    s, h, b = fetch(BASE + path, timeout=10)
    ct = h.get("Content-Type", "") if h else ""
    print(f"  {path} -> {s} ({ct}, {len(b) if b else 0} bytes)")
    if s == 200 and b and len(b) < 5000:
        try:
            print(f"    {json.loads(b)}")
        except:
            print(f"    {b[:200].decode('utf-8', errors='replace')}")
