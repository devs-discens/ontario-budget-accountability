#!/usr/bin/env python3
"""
Download Elections Ontario bulk contribution data.

Elections Ontario Political Finance portal: https://finances.elections.on.ca/en/downloads
The site is an Angular SPA (Single Page Application). The bulk download page
provides CSV files for contributions data from 2014 onward.

KNOWN SITE STRUCTURE (as of 2025):
- The Angular app at finances.elections.on.ca loads data via REST API calls.
- The download page offers multiple CSV downloads, typically organized by year
  or by data type (contributions, expenses, returns).
- Direct CSV links are often served from an API endpoint, not static files.

This script attempts multiple strategies to obtain the data.

Usage:
    python3 download_elections_ontario.py

Output:
    CSV files saved to: ../raw-data/elections-ontario/
"""

import os
import sys
import json
import urllib.request
import urllib.error
import ssl
import time

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "raw-data", "elections-ontario"
)

# Known and attempted URLs for Elections Ontario data.
# The Angular SPA likely calls these API endpoints.
CANDIDATE_URLS = [
    # Direct download page
    "https://finances.elections.on.ca/en/downloads",
    # Common API patterns for Angular apps backed by .NET or similar
    "https://finances.elections.on.ca/api/downloads",
    "https://finances.elections.on.ca/api/contributions",
    "https://finances.elections.on.ca/api/financial-statements/contributions",
    # Open data portal alternatives
    "https://www.elections.on.ca/en/political-financing0/financial-statements.html",
    # Ontario Open Data catalogue
    "https://data.ontario.ca/dataset/political-party-and-constituency-association-financial-data",
]

# Known CSV download patterns (these are educated guesses based on
# the typical structure of Ontario government data portals)
CSV_PATTERNS = [
    "https://finances.elections.on.ca/api/contributions/download?format=csv",
    "https://finances.elections.on.ca/api/contributions/bulk",
    "https://finances.elections.on.ca/api/download/contributions",
]


def make_request(url, timeout=30):
    """Make an HTTPS request, returning (status_code, headers, body)."""
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; research-tool/1.0)",
        "Accept": "text/html,application/json,text/csv,*/*",
    })
    try:
        resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
        body = resp.read()
        return resp.status, dict(resp.headers), body
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers) if hasattr(e, 'headers') else {}, e.read() if hasattr(e, 'read') else b""
    except Exception as e:
        return None, {}, str(e).encode()


def probe_urls():
    """Try all known URLs and report what we find."""
    results = []
    for url in CANDIDATE_URLS + CSV_PATTERNS:
        print(f"  Probing: {url}")
        status, headers, body = make_request(url)
        content_type = headers.get("Content-Type", headers.get("content-type", ""))
        result = {
            "url": url,
            "status": status,
            "content_type": content_type,
            "body_length": len(body) if body else 0,
            "is_csv": "text/csv" in content_type or (body and body[:100].count(b",") > 3),
            "is_html": "text/html" in content_type,
            "is_json": "application/json" in content_type,
        }
        # Check for redirect
        if status and 300 <= status < 400:
            result["redirect"] = headers.get("Location", "")
        results.append(result)
        print(f"    Status: {status}, Type: {content_type}, Size: {result['body_length']}")

        # If we found a CSV, save it
        if result["is_csv"] and body and len(body) > 100:
            filename = url.split("/")[-1].split("?")[0] or "contributions.csv"
            if not filename.endswith(".csv"):
                filename += ".csv"
            filepath = os.path.join(OUTPUT_DIR, filename)
            with open(filepath, "wb") as f:
                f.write(body)
            print(f"    -> Saved CSV to {filepath}")
            result["saved_to"] = filepath

        # If we found HTML, look for download links
        if result["is_html"] and body:
            text = body.decode("utf-8", errors="replace")
            # Look for .csv links
            import re
            csv_links = re.findall(r'href=["\']([^"\']*\.csv[^"\']*)["\']', text, re.IGNORECASE)
            api_links = re.findall(r'href=["\']([^"\']*(?:download|export|bulk)[^"\']*)["\']', text, re.IGNORECASE)
            if csv_links:
                result["csv_links_found"] = csv_links
                print(f"    -> Found CSV links: {csv_links}")
            if api_links:
                result["api_links_found"] = api_links
                print(f"    -> Found API/download links: {api_links}")

        # If we found JSON, check for download URLs in it
        if result["is_json"] and body:
            try:
                data = json.loads(body)
                result["json_preview"] = str(data)[:500]
                print(f"    -> JSON preview: {result['json_preview'][:200]}")
            except json.JSONDecodeError:
                pass

        time.sleep(0.5)  # Be polite

    return results


def try_ontario_open_data():
    """Try the Ontario Open Data catalogue for political finance data."""
    print("\nTrying Ontario Open Data catalogue...")
    search_url = "https://data.ontario.ca/api/3/action/package_search?q=political+contributions+elections"
    status, headers, body = make_request(search_url)
    if status == 200 and body:
        try:
            data = json.loads(body)
            if data.get("success") and data.get("result", {}).get("results"):
                for dataset in data["result"]["results"]:
                    print(f"  Dataset: {dataset.get('title')}")
                    for resource in dataset.get("resources", []):
                        fmt = resource.get("format", "")
                        url = resource.get("url", "")
                        print(f"    Resource: {fmt} - {url}")
                        if fmt.upper() == "CSV" and url:
                            print(f"    -> Downloading CSV...")
                            s2, h2, b2 = make_request(url)
                            if s2 == 200 and b2 and len(b2) > 100:
                                name = resource.get("name", "open-data").replace(" ", "-") + ".csv"
                                path = os.path.join(OUTPUT_DIR, name)
                                with open(path, "wb") as f:
                                    f.write(b2)
                                print(f"    -> Saved to {path}")
                return data
        except json.JSONDecodeError:
            pass
    return None


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("=" * 70)
    print("Elections Ontario Contribution Data Downloader")
    print("=" * 70)
    print(f"\nOutput directory: {OUTPUT_DIR}")
    print(f"\nStep 1: Probing known URLs...\n")

    results = probe_urls()

    print(f"\nStep 2: Trying Ontario Open Data catalogue...\n")
    open_data = try_ontario_open_data()

    # Save probe results for debugging
    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "probe_results": results,
        "open_data_results": str(open_data)[:2000] if open_data else None,
        "csv_files_downloaded": [],
    }

    # Check what we actually saved
    for f in os.listdir(OUTPUT_DIR):
        if f.endswith(".csv"):
            path = os.path.join(OUTPUT_DIR, f)
            size = os.path.getsize(path)
            report["csv_files_downloaded"].append({"file": f, "size_bytes": size})

    report_path = os.path.join(OUTPUT_DIR, "download-probe-report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nProbe report saved to: {report_path}")

    if not report["csv_files_downloaded"]:
        print("\n" + "=" * 70)
        print("WARNING: No CSV files were automatically downloaded.")
        print("=" * 70)
        print("""
MANUAL DOWNLOAD REQUIRED:

The Elections Ontario financial data portal (https://finances.elections.on.ca)
is an Angular Single Page Application. The bulk download functionality likely
requires JavaScript execution to trigger the actual CSV download.

To manually obtain the data:

1. Open https://finances.elections.on.ca/en/downloads in a web browser
2. Look for "Bulk Download" or "Download All Contributions" buttons
3. Select the date range (2014 to present)
4. Download the CSV file(s)
5. Save them to: {output_dir}

Alternative sources:
- Ontario Open Data: https://data.ontario.ca (search "political contributions")
- Elections Ontario main site: https://www.elections.on.ca/en/political-financing0/

Expected CSV columns typically include:
- Contributor name (LAST, FIRST format)
- Contribution amount
- Recipient (party or candidate name)
- Contribution date
- Contribution type (monetary, goods/services, etc.)
- Electoral district (for riding associations)

After downloading, run:
    python3 cross_reference_donations.py

to cross-reference with our tracked people and organizations.
""".format(output_dir=OUTPUT_DIR))

    return len(report["csv_files_downloaded"])


if __name__ == "__main__":
    count = main()
    sys.exit(0 if count > 0 else 1)
