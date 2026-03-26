#!/usr/bin/env python3
"""
Ontario Lobbyist Registry Scraper
==================================
Scrapes the Office of the Integrity Commissioner of Ontario (OICO)
Lobbyist Registry at: https://lobbyist.oico.on.ca/Pages/Public/PublicSearch/

ARCHITECTURE NOTES:
- The registry is an ASP.NET Web Forms application with Telerik RadControls.
- ASP.NET Web Forms uses __VIEWSTATE, __EVENTVALIDATION, and __VIEWSTATEGENERATOR
  hidden fields that must be extracted from each page and submitted back with
  every POST request. These are base64-encoded blobs of server-side state.
- The search form POSTs back to the same URL (postback pattern).
- Telerik RadAjaxManager may intercept some requests as partial postbacks,
  requiring specific headers (X-MicrosoftAjax: Delta=true).
- Pagination uses __EVENTTARGET / __EVENTARGUMENT for grid page navigation.

LIMITATIONS (documented 2026-03-24):
- This scraper was built without live access to the registry during development.
  The form field names, control IDs, and postback patterns are based on known
  conventions for OICO's Telerik-based ASP.NET application, but MUST be validated
  against the live page before production use.
- The __VIEWSTATE values are unique per session and can be very large (100KB+).
- ASP.NET event validation means you can only submit values the server has
  previously rendered — you cannot inject arbitrary search terms without first
  loading the form.
- The site may use CAPTCHA or rate-limiting. If so, the scraper will detect
  this and stop gracefully.
- Results may be paginated with Telerik RadGrid, which uses JavaScript-heavy
  client-side pagination that may not work with simple HTTP requests.

USAGE:
    python3 scrape_lobbyist_registry.py --mode organizations
    python3 scrape_lobbyist_registry.py --mode people
    python3 scrape_lobbyist_registry.py --mode targets
    python3 scrape_lobbyist_registry.py --mode all
    python3 scrape_lobbyist_registry.py --mode single --query "Rubicon Strategy"

POLITE SCRAPING:
- 2-second minimum delay between requests
- Identifies itself with a descriptive User-Agent
- Stops immediately on HTTP errors or blocks
- Saves progress after each search to allow resumption
"""

import argparse
import html.parser
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

# ============================================================================
# CONFIGURATION
# ============================================================================

BASE_URL = "https://lobbyist.oico.on.ca/Pages/Public/PublicSearch/"
# The default.aspx is often implied; the form posts back to itself
SEARCH_URL = BASE_URL

REQUEST_DELAY_SECONDS = 2.5  # Be polite — at least 2 seconds between requests
MAX_RETRIES = 2
TIMEOUT_SECONDS = 30

USER_AGENT = (
    "Ontario-Budget-Audit-Research/1.0 "
    "(Academic/journalistic research; contact: nphilip@example.com)"
)

# Paths
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
DATA_DIR = PROJECT_DIR / "audits" / "2025-26" / "data"
OUTPUT_DIR = PROJECT_DIR / "raw-data" / "lobbyist-registry"
PROGRESS_FILE = OUTPUT_DIR / "scrape_progress.json"

# ============================================================================
# HTML PARSER for ASP.NET form fields
# ============================================================================

class ASPNetFormParser(html.parser.HTMLParser):
    """
    Parses an ASP.NET Web Forms page to extract:
    - Hidden fields (__VIEWSTATE, __EVENTVALIDATION, __VIEWSTATEGENERATOR, etc.)
    - Form action URL
    - Search input field names and IDs
    - Result table rows
    - Pagination controls
    """

    def __init__(self):
        super().__init__()
        self.hidden_fields = {}
        self.form_action = None
        self.input_fields = []  # list of (name, id, type, value)
        self.select_fields = []  # list of (name, id, options)
        self.buttons = []  # list of (name, id, value, text)

        # For result parsing
        self.in_results_table = False
        self.in_row = False
        self.in_cell = False
        self.current_row = []
        self.current_cell_text = ""
        self.current_cell_links = []
        self.result_rows = []
        self.table_depth = 0

        # For link extraction
        self.current_link_href = None
        self.in_link = False
        self.all_links = []

        # Track if we found key elements
        self.found_search_button = False
        self.found_results_grid = False

        # For detecting errors/blocks
        self.page_text = []
        self.in_body = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        if tag == "body":
            self.in_body = True

        if tag == "form":
            action = attrs_dict.get("action", "")
            if action:
                self.form_action = action

        if tag == "input":
            name = attrs_dict.get("name", "")
            input_type = attrs_dict.get("type", "text").lower()
            value = attrs_dict.get("value", "")
            input_id = attrs_dict.get("id", "")

            if input_type == "hidden" and name:
                self.hidden_fields[name] = value

            self.input_fields.append({
                "name": name,
                "id": input_id,
                "type": input_type,
                "value": value
            })

            # Detect search button
            if input_type == "submit" and ("search" in name.lower() or "search" in value.lower()):
                self.found_search_button = True
                self.buttons.append({
                    "name": name,
                    "id": input_id,
                    "value": value,
                    "type": "submit"
                })

        if tag == "select":
            self.select_fields.append({
                "name": attrs_dict.get("name", ""),
                "id": attrs_dict.get("id", "")
            })

        if tag == "button":
            name = attrs_dict.get("name", "")
            if "search" in name.lower() or "search" in attrs_dict.get("id", "").lower():
                self.found_search_button = True
                self.buttons.append({
                    "name": name,
                    "id": attrs_dict.get("id", ""),
                    "value": attrs_dict.get("value", ""),
                    "type": "button"
                })

        # Detect results grid (Telerik RadGrid typically uses specific CSS classes)
        if tag == "table":
            self.table_depth += 1
            table_id = attrs_dict.get("id", "")
            table_class = attrs_dict.get("class", "")
            if ("grid" in table_id.lower() or "radgrid" in table_class.lower()
                    or "rgMasterTable" in table_class):
                self.in_results_table = True
                self.found_results_grid = True

        if self.in_results_table:
            if tag == "tr":
                self.in_row = True
                self.current_row = []
            if tag == "td":
                self.in_cell = True
                self.current_cell_text = ""
                self.current_cell_links = []

        if tag == "a":
            href = attrs_dict.get("href", "")
            self.all_links.append(href)
            if self.in_cell:
                self.current_link_href = href
                self.in_link = True

    def handle_endtag(self, tag):
        if tag == "body":
            self.in_body = False

        if tag == "table":
            self.table_depth -= 1
            if self.table_depth <= 0:
                self.in_results_table = False

        if self.in_results_table:
            if tag == "td" and self.in_cell:
                self.current_row.append({
                    "text": self.current_cell_text.strip(),
                    "links": self.current_cell_links
                })
                self.in_cell = False
            if tag == "tr" and self.in_row:
                if self.current_row:
                    self.result_rows.append(self.current_row)
                self.in_row = False

        if tag == "a":
            self.in_link = False
            self.current_link_href = None

    def handle_data(self, data):
        if self.in_body:
            self.page_text.append(data)

        if self.in_cell:
            self.current_cell_text += data
            if self.in_link and self.current_link_href:
                self.current_cell_links.append({
                    "text": data.strip(),
                    "href": self.current_link_href
                })

    def get_full_text(self):
        return " ".join(self.page_text)


class RegistrationDetailParser(html.parser.HTMLParser):
    """
    Parses an individual lobbyist registration detail page to extract:
    - Lobbyist name and type (consultant vs in-house)
    - Firm/employer
    - Client name
    - Subject matters
    - Government institutions and officials contacted
    - Registration dates
    - Activity descriptions
    """

    def __init__(self):
        super().__init__()
        self.fields = {}
        self.current_label = None
        self.current_value = ""
        self.in_label = False
        self.in_value = False
        self.in_span = False
        self.span_id = ""
        self.all_text_by_id = {}
        self.current_id_text = ""

        # Track all labeled fields
        self.label_for = ""
        self.labels = {}
        self.in_body = False
        self.page_text = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        if tag == "body":
            self.in_body = True

        # ASP.NET often uses <span> with specific IDs for field values
        if tag == "span":
            span_id = attrs_dict.get("id", "")
            if span_id:
                self.span_id = span_id
                self.in_span = True
                self.current_id_text = ""

        if tag == "label":
            self.in_label = True
            self.label_for = attrs_dict.get("for", "")
            self.current_label = ""

    def handle_endtag(self, tag):
        if tag == "body":
            self.in_body = False
        if tag == "span" and self.in_span:
            if self.span_id:
                self.all_text_by_id[self.span_id] = self.current_id_text.strip()
            self.in_span = False
            self.span_id = ""
        if tag == "label" and self.in_label:
            self.in_label = False

    def handle_data(self, data):
        if self.in_body:
            self.page_text.append(data)
        if self.in_span:
            self.current_id_text += data
        if self.in_label:
            if self.current_label is None:
                self.current_label = ""
            self.current_label += data

    def get_full_text(self):
        return " ".join(self.page_text)


# ============================================================================
# HTTP CLIENT (stdlib only)
# ============================================================================

class RegistryClient:
    """HTTP client for the Ontario Lobbyist Registry, handling ASP.NET state."""

    def __init__(self):
        self.viewstate = ""
        self.eventvalidation = ""
        self.viewstategenerator = ""
        self.other_hidden_fields = {}
        self.last_request_time = 0
        self.request_count = 0

        # Cookie-aware opener — required to maintain session across GET and POST.
        # The registry server issues a session cookie on the initial GET; subsequent
        # POSTs must send that cookie or the server ignores the search and returns
        # the empty form page.
        import http.cookiejar
        self._cookie_jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._cookie_jar)
        )

    def _wait_politely(self):
        """Enforce minimum delay between requests."""
        elapsed = time.time() - self.last_request_time
        if elapsed < REQUEST_DELAY_SECONDS:
            sleep_time = REQUEST_DELAY_SECONDS - elapsed
            print(f"  [Waiting {sleep_time:.1f}s to be polite...]")
            time.sleep(sleep_time)
        self.last_request_time = time.time()

    def _make_request(self, url, data=None, headers=None, method=None):
        """
        Make an HTTP request with proper headers and error handling.
        Returns (response_body_str, response_headers, status_code) or raises.
        """
        self._wait_politely()
        self.request_count += 1

        default_headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "identity",  # No compression for simplicity
            "Connection": "keep-alive",
        }

        if headers:
            default_headers.update(headers)

        if data is not None:
            if isinstance(data, dict):
                data = urllib.parse.urlencode(data, doseq=True).encode("utf-8")
            elif isinstance(data, str):
                data = data.encode("utf-8")
            default_headers["Content-Type"] = "application/x-www-form-urlencoded"

        req = urllib.request.Request(url, data=data, headers=default_headers, method=method)

        try:
            response = self._opener.open(req, timeout=TIMEOUT_SECONDS)
            body = response.read().decode("utf-8", errors="replace")
            return body, dict(response.headers), response.status
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            print(f"  [HTTP Error {e.code}: {e.reason}]")
            return body, {}, e.code
        except urllib.error.URLError as e:
            print(f"  [URL Error: {e.reason}]")
            return "", {}, 0
        except Exception as e:
            print(f"  [Request Error: {e}]")
            return "", {}, 0

    def fetch_search_page(self):
        """
        Fetch the initial search page to obtain ViewState and form structure.
        Returns the parsed form structure or None on failure.
        """
        print(f"Fetching search page: {SEARCH_URL}")

        body, headers, status = self._make_request(SEARCH_URL)

        if status != 200:
            print(f"ERROR: Got status {status} from search page")
            return None

        parser = ASPNetFormParser()
        parser.feed(body)

        # Extract ASP.NET state fields
        self.viewstate = parser.hidden_fields.get("__VIEWSTATE", "")
        self.eventvalidation = parser.hidden_fields.get("__EVENTVALIDATION", "")
        self.viewstategenerator = parser.hidden_fields.get("__VIEWSTATEGENERATOR", "")

        # Store all hidden fields for form submission
        self.other_hidden_fields = {
            k: v for k, v in parser.hidden_fields.items()
            if k not in ("__VIEWSTATE", "__EVENTVALIDATION", "__VIEWSTATEGENERATOR")
        }

        # Check if page looks like the lobbyist registry
        full_text = parser.get_full_text().lower()
        if "lobbyist" not in full_text and "registry" not in full_text:
            print("WARNING: Page does not appear to be the lobbyist registry.")
            print(f"  Page text preview: {full_text[:500]}")

        # Diagnostic output
        print(f"  ViewState length: {len(self.viewstate)} chars")
        print(f"  EventValidation length: {len(self.eventvalidation)} chars")
        print(f"  Hidden fields found: {list(parser.hidden_fields.keys())}")
        print(f"  Input fields found: {len(parser.input_fields)}")
        print(f"  Select fields found: {len(parser.select_fields)}")
        print(f"  Search button found: {parser.found_search_button}")
        print(f"  Results grid found: {parser.found_results_grid}")

        # Save raw HTML for debugging
        debug_path = OUTPUT_DIR / "debug_search_page.html"
        with open(debug_path, "w", encoding="utf-8") as f:
            f.write(body)
        print(f"  Saved raw HTML to: {debug_path}")

        # Save form structure for analysis
        form_structure = {
            "timestamp": datetime.now().isoformat(),
            "status_code": status,
            "form_action": parser.form_action,
            "viewstate_length": len(self.viewstate),
            "eventvalidation_length": len(self.eventvalidation),
            "hidden_field_names": list(parser.hidden_fields.keys()),
            "input_fields": parser.input_fields,
            "select_fields": parser.select_fields,
            "buttons": parser.buttons,
            "found_search_button": parser.found_search_button,
            "found_results_grid": parser.found_results_grid,
            "sample_links": parser.all_links[:50],
            "page_text_preview": full_text[:2000]
        }

        form_path = OUTPUT_DIR / "form_structure.json"
        with open(form_path, "w", encoding="utf-8") as f:
            json.dump(form_structure, f, indent=2)
        print(f"  Saved form structure to: {form_path}")

        return parser

    def submit_search(self, search_params, search_type="client"):
        """
        Submit a search to the registry.

        search_params: dict of field name -> value to fill in the search form.
        search_type: one of "client", "lobbyist", "subject", "target"

        This is the CRITICAL function that needs to be calibrated against
        the live site. The form field names below are BEST GUESSES based on
        typical OICO registry structure and must be verified.

        KNOWN FORM PATTERNS FOR OICO REGISTRY:
        The public search typically has these fields:
        - Organization/Client Name (text input)
        - Lobbyist Name (First/Last, text inputs)
        - Type of Lobbyist (Consultant / In-house, dropdown)
        - Subject Matter (dropdown or checkboxes)
        - Government Institution (dropdown)
        - Registration Status (Active/Inactive, dropdown)
        - Date Range (from/to date pickers, Telerik RadDatePicker)
        - A "Search" button that triggers a postback

        Returns: list of result dicts, or None on failure
        """
        if not self.viewstate:
            print("ERROR: No ViewState — call fetch_search_page() first")
            return None

        # Build the POST data with ASP.NET state
        post_data = {
            "__VIEWSTATE": self.viewstate,
            "__EVENTVALIDATION": self.eventvalidation,
            "__VIEWSTATEGENERATOR": self.viewstategenerator,
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
        }

        # Add other hidden fields
        post_data.update(self.other_hidden_fields)

        # Always set status to "Any Status" to find both active and inactive registrations.
        # Verified against live site 2026-03-24: defaulting to rdoCurrentlyActive returns
        # no results for many searches because registrations may be inactive.
        post_data["ctl00$BodyContent$ucQuickSearch$rdoStatusGroup1"] = "rdoAnyStatus"
        post_data["ctl00$BodyContent$ucQuickSearch$rdoStatusGroup2"] = "rdoActiveAnyDate"

        # Add search-specific parameters
        post_data.update(search_params)

        # Store search params for pagination (needed for ASP.NET postback)
        self._last_search_params = dict(search_params)

        print(f"  Submitting search with {len(search_params)} params...")

        # POST back to the same URL (ASP.NET postback pattern)
        body, headers, status = self._make_request(
            SEARCH_URL,
            data=post_data,
            headers={"Referer": SEARCH_URL}
        )

        if status != 200:
            print(f"  ERROR: Search returned status {status}")
            return None

        # Parse results
        parser = ASPNetFormParser()
        parser.feed(body)

        # Update state for subsequent requests (pagination, etc.)
        if parser.hidden_fields.get("__VIEWSTATE"):
            self.viewstate = parser.hidden_fields["__VIEWSTATE"]
        if parser.hidden_fields.get("__EVENTVALIDATION"):
            self.eventvalidation = parser.hidden_fields["__EVENTVALIDATION"]
        if parser.hidden_fields.get("__VIEWSTATEGENERATOR"):
            self.viewstategenerator = parser.hidden_fields["__VIEWSTATEGENERATOR"]

        # Check for blocking/CAPTCHA
        full_text = parser.get_full_text()
        full_text_lower = full_text.lower()
        if "captcha" in full_text_lower or "access denied" in full_text_lower or "forbidden" in full_text_lower:
            print("  BLOCKED: Site appears to be blocking automated access.")
            print("  STOPPING SCRAPER — do not continue.")
            return None

        # Check for results page (as opposed to the empty form page)
        # The results page contains "Search Results" header and registration data
        is_results_page = "search results" in full_text_lower or "registration no" in full_text_lower
        if not is_results_page:
            print("  No results found (server returned search form, not results).")
            return []

        # Save the raw result HTML for debugging
        debug_results_path = OUTPUT_DIR / "debug_last_results.html"
        with open(debug_results_path, "w", encoding="utf-8") as f:
            f.write(body)

        # Parse result rows from table (Telerik RadGrid)
        results = self._parse_result_rows(parser.result_rows)

        # Fallback: if table parser didn't work, try text-based parsing
        if not results and is_results_page:
            results = self._parse_results_from_text(full_text)
            if results:
                print(f"  (Used text-based fallback parser)")

        # Detect pagination: find the "Next Page" postback target from the pager.
        # The Telerik RadGrid pager uses __doPostBack with specific control IDs.
        # The "Next Page" button has class="rgPageNext" and onclick with __doPostBack.
        # HTML attribute order varies, so we find the full <input> element first.
        self._next_page_target = None
        self._has_more_pages = False

        next_page_pattern = re.compile(
            r'<input[^>]*class="rgPageNext"[^>]*/>'
            r'|<input[^>]*title="Next Page"[^>]*/>',
            re.IGNORECASE
        )
        match = next_page_pattern.search(body)
        if match:
            element = match.group(0)
            # Extract __doPostBack target from onclick
            target_match = re.search(r"__doPostBack\(&#39;([^&]+)&#39;", element)
            if target_match:
                # Enabled: onclick starts with "javascript:__doPostBack"
                # Disabled: onclick starts with "return false;__doPostBack"
                if 'return false;__doPostBack' not in element:
                    self._next_page_target = target_match.group(1)
                    self._has_more_pages = True

        # Also update other_hidden_fields from results page for pagination POSTs
        self.other_hidden_fields = {
            k: v for k, v in parser.hidden_fields.items()
            if k not in ("__VIEWSTATE", "__EVENTVALIDATION", "__VIEWSTATEGENERATOR")
        }

        print(f"  Found {len(results)} results on this page.")
        if self._has_more_pages:
            print(f"  More pages available.")

        return results

    def fetch_next_page(self):
        """
        Fetch the next page of results using Telerik RadGrid pagination.
        Must be called after submit_search() found results with more pages.
        Returns list of results or None.
        """
        if not self._has_more_pages or not self._next_page_target:
            return None

        print(f"  Fetching next page...")

        post_data = {
            "__VIEWSTATE": self.viewstate,
            "__EVENTVALIDATION": self.eventvalidation,
            "__VIEWSTATEGENERATOR": self.viewstategenerator,
            "__EVENTTARGET": self._next_page_target,
            "__EVENTARGUMENT": "",
        }
        post_data.update(self.other_hidden_fields)

        body, headers, status = self._make_request(
            SEARCH_URL,
            data=post_data,
            headers={"Referer": SEARCH_URL}
        )

        if status != 200:
            print(f"  ERROR: Page navigation returned status {status}")
            return None

        parser = ASPNetFormParser()
        parser.feed(body)

        # Update state
        if parser.hidden_fields.get("__VIEWSTATE"):
            self.viewstate = parser.hidden_fields["__VIEWSTATE"]
        if parser.hidden_fields.get("__EVENTVALIDATION"):
            self.eventvalidation = parser.hidden_fields["__EVENTVALIDATION"]
        if parser.hidden_fields.get("__VIEWSTATEGENERATOR"):
            self.viewstategenerator = parser.hidden_fields["__VIEWSTATEGENERATOR"]
        self.other_hidden_fields = {
            k: v for k, v in parser.hidden_fields.items()
            if k not in ("__VIEWSTATE", "__EVENTVALIDATION", "__VIEWSTATEGENERATOR")
        }

        full_text = parser.get_full_text()
        full_text_lower = full_text.lower()

        is_results_page = "search results" in full_text_lower or "registration no" in full_text_lower
        if not is_results_page:
            self._has_more_pages = False
            return []

        results = self._parse_result_rows(parser.result_rows)
        if not results and is_results_page:
            results = self._parse_results_from_text(full_text)

        # Check for next page again
        self._next_page_target = None
        self._has_more_pages = False
        next_page_pattern = re.compile(
            r'<input[^>]*class="rgPageNext"[^>]*/>'
            r'|<input[^>]*title="Next Page"[^>]*/>',
            re.IGNORECASE
        )
        match = next_page_pattern.search(body)
        if match:
            element = match.group(0)
            target_match = re.search(r"__doPostBack\(&#39;([^&]+)&#39;", element)
            if target_match:
                if 'return false;__doPostBack' not in element:
                    self._next_page_target = target_match.group(1)
                    self._has_more_pages = True

        print(f"  Found {len(results)} results on this page.")

        return results

    def _parse_result_rows(self, rows):
        """
        Parse result table rows into structured data.

        Verified column order from live site (2026-03-24):
        0: Lobbyist Name
        1: Last Amendment Date
        2: Client Name
        3: Company/Organization (firm)
        4: Lobbyist Type (Consultant Lobbyist / In-house)
        5: Registration No.
        6: Document Type (hidden column, often empty)
        7: Status (Active/Inactive)
        8: Client ID (hidden)
        9: (hidden)
        4: Subject Matter
        5: Status (Active/Inactive)
        6: Registration Date

        The exact columns WILL vary. The form_structure.json and debug HTML
        should be used to determine the actual column layout.
        """
        if not rows:
            return []

        results = []

        # Skip header row (first row is usually headers)
        data_rows = rows[1:] if len(rows) > 1 else rows

        for row in data_rows:
            if len(row) < 3:
                continue  # Skip rows that are too short (likely decoration)

            result = {
                "raw_cells": [cell["text"] for cell in row],
                "links": []
            }

            # Extract any links (to detail pages)
            for cell in row:
                for link in cell.get("links", []):
                    result["links"].append(link)

            # Map columns based on verified live site layout (2026-03-24)
            try:
                if len(row) >= 8:
                    result["lobbyist_name"] = row[0]["text"]
                    result["last_amendment_date"] = row[1]["text"]
                    result["client"] = row[2]["text"]
                    result["firm"] = row[3]["text"]
                    result["lobbyist_type"] = row[4]["text"]
                    result["registration_no"] = row[5]["text"]
                    result["status"] = row[7]["text"]
                elif len(row) >= 6:
                    result["lobbyist_name"] = row[0]["text"]
                    result["last_amendment_date"] = row[1]["text"]
                    result["client"] = row[2]["text"]
                    result["firm"] = row[3]["text"]
                    result["lobbyist_type"] = row[4]["text"]
                    result["registration_no"] = row[5]["text"]
                elif len(row) >= 4:
                    result["lobbyist_name"] = row[0]["text"]
                    result["client"] = row[1]["text"] if len(row) > 1 else ""
                    result["firm"] = row[2]["text"] if len(row) > 2 else ""
                    result["status"] = row[3]["text"] if len(row) > 3 else ""
            except (IndexError, KeyError):
                pass  # Keep raw_cells as fallback

            results.append(result)

        return results

    def _parse_results_from_text(self, full_text):
        """
        Fallback parser: extract registration data from plain text of the results page.

        The OICO registry results page (when JavaScript is not available) renders
        results as a table with these columns (verified 2026-03-24):
          Lobbyist | Last Amendment Date | Client Name | Company/Organization |
          Lobbyist Type | Registration No. | Document Type | Status | Status Terminated By

        This parser uses heuristics to find records by looking for the registration
        number pattern (e.g., "CL9951-20220120027723") as an anchor.
        """
        results = []
        # Registration numbers follow pattern: CL<digits>-<digits> or ORG-<digits>
        # Find all registration numbers and extract surrounding context
        reg_pattern = re.compile(
            r'(CL\d+-\d+|ORG-\d+-\d+|IH\d+-\d+)\s+',
            re.IGNORECASE
        )

        # Tokenize text into words/tokens
        tokens = [t.strip() for t in re.split(r'\s{2,}|\n|\t', full_text) if t.strip()]

        # Find positions of registration numbers
        for i, token in enumerate(tokens):
            if reg_pattern.match(token):
                # The registration number is our anchor
                # Look backwards for lobbyist name, amendment date, client, firm, type
                # and forward for status
                result = {
                    "registration_no": token.strip(),
                    "raw_tokens": tokens[max(0, i-8):i+5]
                }

                # Try to find lobbyist name (typically 2-3 tokens before registration no)
                # Pattern: look for date (MM-DD-YYYY) to locate amendment date
                date_pattern = re.compile(r'\d{2}-\d{2}-\d{4}')
                for j in range(max(0, i-8), i):
                    if date_pattern.match(tokens[j]):
                        # tokens[j] = amendment date
                        # tokens before j = lobbyist name
                        # tokens after j = client, firm, type
                        result["last_amendment_date"] = tokens[j]
                        # Lobbyist name is the token(s) just before the date
                        lobbyist_tokens = []
                        for k in range(j-1, max(0, j-4), -1):
                            if k < 0:
                                break
                            # Stop if this looks like a column header
                            if tokens[k].lower() in ('lobbyist', 'client', 'status', 'active', 'inactive', 'terminated'):
                                break
                            lobbyist_tokens.insert(0, tokens[k])
                        result["lobbyist_name"] = " ".join(lobbyist_tokens).strip()

                        # Client, firm, type come between amendment date and registration no
                        context_tokens = tokens[j+1:i]
                        if len(context_tokens) >= 1:
                            result["client_name"] = context_tokens[0]
                        if len(context_tokens) >= 2:
                            result["firm"] = context_tokens[1]
                        if len(context_tokens) >= 3:
                            result["lobbyist_type"] = context_tokens[2]
                        break

                # Status comes after registration no (skip doc type token)
                if i + 2 < len(tokens):
                    status_token = tokens[i + 2]
                    if status_token.lower() in ("active", "inactive", "terminated"):
                        result["status"] = status_token
                    elif i + 1 < len(tokens) and tokens[i + 1].lower() in ("active", "inactive", "terminated"):
                        result["status"] = tokens[i + 1]

                if result.get("lobbyist_name") or result.get("client_name"):
                    results.append(result)

        return results

    def fetch_registration_detail(self, detail_url):
        """
        Fetch and parse an individual registration detail page.
        Returns a dict of extracted fields or None on failure.
        """
        # Resolve relative URLs
        if detail_url.startswith("/"):
            detail_url = "https://lobbyist.oico.on.ca" + detail_url
        elif not detail_url.startswith("http"):
            detail_url = BASE_URL + detail_url

        print(f"  Fetching detail: {detail_url}")

        body, headers, status = self._make_request(detail_url)

        if status != 200:
            print(f"  ERROR: Detail page returned status {status}")
            return None

        parser = RegistrationDetailParser()
        parser.feed(body)

        detail = {
            "url": detail_url,
            "all_text_by_id": parser.all_text_by_id,
            "full_text_preview": parser.get_full_text()[:3000]
        }

        # Try to extract structured fields from the text
        full_text = parser.get_full_text()

        # Common field patterns in registration detail pages
        field_patterns = {
            "lobbyist_name": r"(?:Lobbyist|Name)[:\s]+([^\n]+)",
            "registration_type": r"(?:Registration Type|Type)[:\s]+([^\n]+)",
            "firm": r"(?:Firm|Employer|Organization)[:\s]+([^\n]+)",
            "client": r"(?:Client|On behalf of)[:\s]+([^\n]+)",
            "subject_matters": r"(?:Subject Matter|Subject)[:\s]+([^\n]+)",
            "government_institutions": r"(?:Government Institution|Institution)[:\s]+([^\n]+)",
            "government_officials": r"(?:Government Official|Official|Target)[:\s]+([^\n]+)",
            "effective_date": r"(?:Effective Date|Start Date|Registration Date)[:\s]+([^\n]+)",
            "status": r"(?:Status)[:\s]+(Active|Inactive|Terminated)",
        }

        for field_name, pattern in field_patterns.items():
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                detail[field_name] = match.group(1).strip()

        return detail


# ============================================================================
# SEARCH ORCHESTRATION
# ============================================================================

def load_search_targets():
    """Load organizations and people from our data files."""
    targets = {
        "organizations": [],
        "people": [],
        "government_targets": [
            "Premier",
            "Minister of Labour",
            "Minister of Energy",
            "Minister of Transportation",
            "Minister of Finance",
            "Minister of Economic Development",
            "Minister of Infrastructure",
            "Minister of Health",
            "Minister of Municipal Affairs",
        ]
    }

    # Load organizations
    org_path = DATA_DIR / "organizations.json"
    if org_path.exists():
        with open(org_path, "r") as f:
            data = json.load(f)
        for org in data.get("organizations", []):
            targets["organizations"].append({
                "id": org["id"],
                "name": org["name"],
                "org_type": org.get("org_type", "unknown"),
                "known_lobbyists": org.get("lobbyists", []),
                "connection_strength": org.get("connection_strength", "none")
            })

    # Load people
    people_path = DATA_DIR / "people.json"
    if people_path.exists():
        with open(people_path, "r") as f:
            data = json.load(f)
        for person in data.get("people", []):
            if person.get("type") in ("lobbyist", "lobbyist-insider"):
                targets["people"].append({
                    "id": person["id"],
                    "name": person["name"],
                    "firm": person.get("firm"),
                    "type": person.get("type")
                })

    print(f"Loaded {len(targets['organizations'])} organizations to search as clients")
    print(f"Loaded {len(targets['people'])} people to search as lobbyists")
    print(f"Loaded {len(targets['government_targets'])} government targets")

    return targets


def load_progress():
    """Load scraping progress for resumability."""
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, "r") as f:
            return json.load(f)
    return {
        "completed_org_searches": [],
        "completed_people_searches": [],
        "completed_target_searches": [],
        "errors": [],
        "last_updated": None
    }


def save_progress(progress):
    """Save scraping progress."""
    progress["last_updated"] = datetime.now().isoformat()
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)


def save_results(results, filename):
    """Save search results to a JSON file."""
    filepath = OUTPUT_DIR / filename
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"  Saved {len(results) if isinstance(results, list) else 'N/A'} results to {filepath}")
    return filepath


def discover_form_fields(client):
    """
    Step 1: Fetch the search page and discover the actual form field names.
    This is essential before any searches can be submitted.
    Returns a dict mapping logical field names to actual ASP.NET control names.
    """
    parser = client.fetch_search_page()
    if parser is None:
        return None

    # Analyze the discovered form structure to map fields
    field_map = {}

    for field in parser.input_fields:
        name = field["name"].lower()
        field_id = field["id"].lower()
        actual_name = field["name"]

        # Map text inputs by their likely purpose
        if field["type"] in ("text", ""):
            if any(kw in name or kw in field_id for kw in ["client", "organization", "org"]):
                field_map["client_name"] = actual_name
            elif any(kw in name or kw in field_id for kw in ["firstname", "first_name", "fname"]):
                field_map["first_name"] = actual_name
            elif any(kw in name or kw in field_id for kw in ["lastname", "last_name", "lname"]):
                field_map["last_name"] = actual_name
            elif "keyword" in name or "keyword" in field_id:
                field_map["keyword"] = actual_name
            elif "name" in name or "name" in field_id:
                # Generic name field
                if "lobbyist_name" not in field_map:
                    field_map["lobbyist_name"] = actual_name

    # Map dropdowns
    for field in parser.select_fields:
        name = field["name"].lower()
        field_id = field["id"].lower()
        actual_name = field["name"]

        if any(kw in name or kw in field_id for kw in ["type", "lobbyisttype"]):
            field_map["lobbyist_type"] = actual_name
        elif any(kw in name or kw in field_id for kw in ["subject", "matter"]):
            field_map["subject_matter"] = actual_name
        elif any(kw in name or kw in field_id for kw in ["institution", "government", "ministry"]):
            field_map["institution"] = actual_name
        elif any(kw in name or kw in field_id for kw in ["status"]):
            field_map["status"] = actual_name

    # Map search button — check only the control's short name (last segment after $),
    # because the full path always contains "ucQuickSearch" which would falsely match.
    for field in parser.input_fields:
        if field["type"] == "submit":
            short_name = field["name"].split("$")[-1].lower()
            value_lower = field.get("value", "").lower()
            if short_name == "btnsearch" or value_lower == "search":
                field_map["search_button"] = field["name"]
                break

    # Fallback: also add known lobbyist search field
    for field in parser.input_fields:
        if field["type"] in ("text", ""):
            short_name = field["name"].split("$")[-1].lower()
            if "lobbyist" in short_name:
                field_map["lobbyist_name"] = field["name"]
                break

    # Save the field map
    field_map_path = OUTPUT_DIR / "field_map.json"
    with open(field_map_path, "w") as f:
        json.dump(field_map, f, indent=2)
    print(f"\nDiscovered field map: {json.dumps(field_map, indent=2)}")
    print(f"Saved to: {field_map_path}")

    return field_map


def run_organization_searches(client, field_map, targets, progress):
    """Search the registry for each organization as a client."""
    all_results = []
    org_results_path = OUTPUT_DIR / "org_search_results.json"

    # Load existing results for resumability
    if org_results_path.exists():
        with open(org_results_path, "r") as f:
            all_results = json.load(f)

    for org in targets["organizations"]:
        org_id = org["id"]
        org_name = org["name"]

        # Skip if already completed
        if org_id in progress["completed_org_searches"]:
            print(f"  Skipping {org_name} (already searched)")
            continue

        print(f"\n--- Searching for client: {org_name} ---")

        # Build search parameters
        search_params = {}

        # Use the client name field if we found it
        if "client_name" in field_map:
            search_params[field_map["client_name"]] = org_name
        elif "keyword" in field_map:
            search_params[field_map["keyword"]] = org_name
        else:
            print(f"  WARNING: No client name field found in form. Cannot search.")
            progress["errors"].append({
                "type": "no_client_field",
                "org": org_name,
                "timestamp": datetime.now().isoformat()
            })
            continue

        # Add search button
        if "search_button" in field_map:
            search_params[field_map["search_button"]] = "Search"

        # Need to re-fetch the search page before each search to get fresh ViewState
        # (ASP.NET ties ViewState to specific page state)
        if client.request_count > 0:
            client.fetch_search_page()

        results = client.submit_search(search_params, search_type="client")

        if results is None:
            print(f"  ERROR: Search failed for {org_name}")
            progress["errors"].append({
                "type": "search_failed",
                "org": org_name,
                "timestamp": datetime.now().isoformat()
            })
            save_progress(progress)
            # If we got blocked, stop entirely
            return all_results

        # Paginate to get all results
        max_pages = 20  # Safety limit
        page = 1
        while client._has_more_pages and page < max_pages:
            page += 1
            next_results = client.fetch_next_page()
            if next_results is None or not next_results:
                break
            results.extend(next_results)

        # Store results with metadata
        search_record = {
            "search_type": "organization_as_client",
            "query": org_name,
            "org_id": org_id,
            "org_type": org.get("org_type"),
            "known_lobbyists": org.get("known_lobbyists", []),
            "result_count": len(results),
            "results": results,
            "timestamp": datetime.now().isoformat()
        }
        all_results.append(search_record)

        # Mark as completed
        progress["completed_org_searches"].append(org_id)
        save_progress(progress)

        # Save incrementally
        save_results(all_results, "org_search_results.json")

    return all_results


def run_people_searches(client, field_map, targets, progress):
    """Search the registry for each person as a lobbyist."""
    all_results = []
    people_results_path = OUTPUT_DIR / "people_search_results.json"

    if people_results_path.exists():
        with open(people_results_path, "r") as f:
            all_results = json.load(f)

    for person in targets["people"]:
        person_id = person["id"]
        person_name = person["name"]

        if person_id in progress["completed_people_searches"]:
            print(f"  Skipping {person_name} (already searched)")
            continue

        print(f"\n--- Searching for lobbyist: {person_name} ---")

        # Split name for first/last fields
        name_parts = person_name.split()
        first_name = name_parts[0] if name_parts else ""
        last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

        search_params = {}

        if "first_name" in field_map and "last_name" in field_map:
            search_params[field_map["first_name"]] = first_name
            search_params[field_map["last_name"]] = last_name
        elif "lobbyist_name" in field_map:
            search_params[field_map["lobbyist_name"]] = person_name
        elif "keyword" in field_map:
            search_params[field_map["keyword"]] = person_name
        else:
            print(f"  WARNING: No lobbyist name field found. Cannot search.")
            progress["errors"].append({
                "type": "no_name_field",
                "person": person_name,
                "timestamp": datetime.now().isoformat()
            })
            continue

        if "search_button" in field_map:
            search_params[field_map["search_button"]] = "Search"

        # Re-fetch for fresh ViewState
        if client.request_count > 0:
            client.fetch_search_page()

        results = client.submit_search(search_params, search_type="lobbyist")

        if results is None:
            print(f"  ERROR: Search failed for {person_name}")
            progress["errors"].append({
                "type": "search_failed",
                "person": person_name,
                "timestamp": datetime.now().isoformat()
            })
            save_progress(progress)
            return all_results

        # Paginate
        max_pages = 20
        page = 1
        while client._has_more_pages and page < max_pages:
            page += 1
            next_results = client.fetch_next_page()
            if next_results is None or not next_results:
                break
            results.extend(next_results)

        search_record = {
            "search_type": "person_as_lobbyist",
            "query": person_name,
            "person_id": person_id,
            "firm": person.get("firm"),
            "result_count": len(results),
            "results": results,
            "timestamp": datetime.now().isoformat()
        }
        all_results.append(search_record)

        progress["completed_people_searches"].append(person_id)
        save_progress(progress)
        save_results(all_results, "people_search_results.json")

    return all_results


def run_target_searches(client, field_map, targets, progress):
    """Search the registry by government target (e.g., 'Premier', 'Minister of Labour')."""
    all_results = []
    target_results_path = OUTPUT_DIR / "target_search_results.json"

    if target_results_path.exists():
        with open(target_results_path, "r") as f:
            all_results = json.load(f)

    for target in targets["government_targets"]:
        if target in progress["completed_target_searches"]:
            print(f"  Skipping target: {target} (already searched)")
            continue

        print(f"\n--- Searching for government target: {target} ---")

        search_params = {}

        # Government targets might be searchable via an institution dropdown
        # or a keyword search
        if "institution" in field_map:
            search_params[field_map["institution"]] = target
        elif "keyword" in field_map:
            search_params[field_map["keyword"]] = target
        else:
            print(f"  WARNING: No institution or keyword field found. Cannot search.")
            continue

        if "search_button" in field_map:
            search_params[field_map["search_button"]] = "Search"

        if client.request_count > 0:
            client.fetch_search_page()

        results = client.submit_search(search_params, search_type="target")

        if results is None:
            print(f"  ERROR: Search failed for target {target}")
            progress["errors"].append({
                "type": "search_failed",
                "target": target,
                "timestamp": datetime.now().isoformat()
            })
            save_progress(progress)
            return all_results

        # Paginate
        max_pages = 20
        page = 1
        while client._has_more_pages and page < max_pages:
            page += 1
            next_results = client.fetch_next_page()
            if next_results is None or not next_results:
                break
            results.extend(next_results)

        search_record = {
            "search_type": "government_target",
            "query": target,
            "result_count": len(results),
            "results": results,
            "timestamp": datetime.now().isoformat()
        }
        all_results.append(search_record)

        progress["completed_target_searches"].append(target)
        save_progress(progress)
        save_results(all_results, "target_search_results.json")

    return all_results


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Scrape the Ontario Lobbyist Registry (OICO)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
MODES:
  discover     Just fetch the search page and discover form structure
  organizations Search for all organizations in our data as clients
  people       Search for all lobbyist-type people in our data
  targets      Search by government targets (Premier, Ministers)
  all          Run all search modes
  single       Run a single search query (use --query)

EXAMPLES:
  %(prog)s --mode discover
  %(prog)s --mode organizations
  %(prog)s --mode all
  %(prog)s --mode single --query "Rubicon Strategy"

NOTES:
  - Run 'discover' first to identify the form structure
  - The scraper is resumable — it saves progress after each search
  - Minimum 2.5s delay between requests to be polite to the server
  - If blocked, the scraper will stop and document what happened
        """
    )

    parser.add_argument(
        "--mode",
        choices=["discover", "organizations", "people", "targets", "all", "single"],
        default="discover",
        help="Scraping mode (default: discover)"
    )
    parser.add_argument(
        "--query",
        type=str,
        default="",
        help="Search query for 'single' mode"
    )
    parser.add_argument(
        "--field",
        choices=["client", "lobbyist", "keyword"],
        default="client",
        help="Which search field to use in single mode (default: client)"
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset progress and start fresh"
    )

    args = parser.parse_args()

    # Ensure output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("ONTARIO LOBBYIST REGISTRY SCRAPER")
    print(f"Date: {datetime.now().isoformat()}")
    print(f"Mode: {args.mode}")
    print(f"Output: {OUTPUT_DIR}")
    print("=" * 70)

    # Load or reset progress
    if args.reset:
        progress = {
            "completed_org_searches": [],
            "completed_people_searches": [],
            "completed_target_searches": [],
            "errors": [],
            "last_updated": None
        }
        save_progress(progress)
        print("Progress reset.")
    else:
        progress = load_progress()
        if progress["last_updated"]:
            print(f"Resuming from: {progress['last_updated']}")
            print(f"  Completed org searches: {len(progress['completed_org_searches'])}")
            print(f"  Completed people searches: {len(progress['completed_people_searches'])}")
            print(f"  Completed target searches: {len(progress['completed_target_searches'])}")

    # Initialize client
    client = RegistryClient()

    # Step 1: Discover form structure
    print("\n" + "=" * 70)
    print("STEP 1: Discovering form structure...")
    print("=" * 70)

    field_map = discover_form_fields(client)

    if field_map is None:
        print("\nFATAL: Could not fetch or parse the search page.")
        print("Possible causes:")
        print("  - Site is down or blocking requests")
        print("  - Network connectivity issue")
        print("  - SSL/TLS issue")
        print("\nCheck debug_search_page.html in the output directory for details.")
        sys.exit(1)

    if not field_map:
        print("\nWARNING: Could not identify any form fields.")
        print("The page HTML has been saved for manual analysis.")
        print("Check:")
        print(f"  {OUTPUT_DIR / 'debug_search_page.html'}")
        print(f"  {OUTPUT_DIR / 'form_structure.json'}")

        if args.mode == "discover":
            print("\nDiscovery complete. Review the saved files to identify form fields.")
            sys.exit(0)
        else:
            print("\nCannot proceed with searches without identified form fields.")
            sys.exit(1)

    if args.mode == "discover":
        print("\nDiscovery complete. Review the saved files:")
        print(f"  {OUTPUT_DIR / 'form_structure.json'}")
        print(f"  {OUTPUT_DIR / 'field_map.json'}")
        print(f"  {OUTPUT_DIR / 'debug_search_page.html'}")
        sys.exit(0)

    # Load search targets
    targets = load_search_targets()

    # Step 2: Run searches
    if args.mode in ("single",):
        if not args.query:
            print("ERROR: --query is required for single mode")
            sys.exit(1)

        print(f"\n--- Single search: {args.query} ---")
        search_params = {}
        field_preference = {
            "client": ["client_name", "keyword", "lobbyist_name"],
            "lobbyist": ["lobbyist_name", "keyword", "client_name"],
            "keyword": ["keyword", "client_name", "lobbyist_name"],
        }
        for key in field_preference.get(args.field, ["client_name", "keyword"]):
            if key in field_map:
                search_params[field_map[key]] = args.query
                print(f"  Using field '{key}' ({field_map[key]}) for query")
                break
        else:
            print("ERROR: No usable search field found in field_map")
            sys.exit(1)

        if "search_button" in field_map:
            search_params[field_map["search_button"]] = "Search"

        results = client.submit_search(search_params)
        if results is not None:
            # Paginate
            max_pages = 20
            page = 1
            while client._has_more_pages and page < max_pages:
                page += 1
                next_results = client.fetch_next_page()
                if next_results is None or not next_results:
                    break
                results.extend(next_results)
            save_results(results, f"single_search_{args.query.replace(' ', '_')}.json")

    if args.mode in ("organizations", "all"):
        print("\n" + "=" * 70)
        print("STEP 2a: Searching for organizations as clients...")
        print("=" * 70)
        org_results = run_organization_searches(client, field_map, targets, progress)
        print(f"\nCompleted {len(org_results)} organization searches.")

    if args.mode in ("people", "all"):
        print("\n" + "=" * 70)
        print("STEP 2b: Searching for people as lobbyists...")
        print("=" * 70)
        people_results = run_people_searches(client, field_map, targets, progress)
        print(f"\nCompleted {len(people_results)} people searches.")

    if args.mode in ("targets", "all"):
        print("\n" + "=" * 70)
        print("STEP 2c: Searching by government targets...")
        print("=" * 70)
        target_results = run_target_searches(client, field_map, targets, progress)
        print(f"\nCompleted {len(target_results)} target searches.")

    # Summary
    print("\n" + "=" * 70)
    print("SCRAPING COMPLETE")
    print("=" * 70)
    print(f"Total HTTP requests: {client.request_count}")
    print(f"Errors encountered: {len(progress['errors'])}")
    print(f"Results saved to: {OUTPUT_DIR}")

    if progress["errors"]:
        print("\nErrors:")
        for err in progress["errors"][-10:]:  # Show last 10
            print(f"  - [{err.get('type')}] {err.get('org', err.get('person', err.get('target', 'unknown')))}")


if __name__ == "__main__":
    main()
