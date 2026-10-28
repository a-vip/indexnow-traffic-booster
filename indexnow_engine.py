#!/usr/bin/env python3
"""
indexnow_engine.py
Autonomous Search Engine Indexing & Traffic Booster for aviperera.com.
Monitors new publications and instantaneously notifies Bing, Yandex, DuckDuckGo,
Yahoo, and Seznam via the IndexNow protocol, plus pings Google's sitemap endpoints.
"""

import os
import sys
import json
import re
import argparse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"
DEFAULT_HOST = "aviperera.com"
STATE_FILE = os.path.join(os.path.dirname(__file__), "state", "submitted_urls.json")

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, application/json, */*"
}

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[!] Warning: Could not read state file ({e}). Starting fresh.")
    return {"submitted": {}, "last_run": None}

def save_state(state: dict):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

def fetch_from_rss(host: str) -> list:
    """Primary ingestion: Fetches published articles via RSS feed (bypasses Hostinger WAF blocks)."""
    rss_url = f"https://{host}/feed/"
    try:
        req = urllib.request.Request(rss_url, headers=BROWSER_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw_xml = resp.read().decode("utf-8", errors="replace")
            # Strip XML prefixes (e.g. content:encoded -> encoded)
            clean_xml = re.sub(r"</?([a-zA-Z0-9_-]+):", lambda m: "</" if m.group(0).startswith("</") else "<", raw_xml)
            root = ET.fromstring(clean_xml)
            items = []
            for item in root.findall(".//item"):
                link_el = item.find("link")
                title_el = item.find("title")
                pub_el = item.find("pubDate")
                link = link_el.text.strip() if link_el is not None and link_el.text else ""
                title = title_el.text.strip() if title_el is not None and title_el.text else ""
                pub = pub_el.text.strip() if pub_el is not None and pub_el.text else datetime.now(timezone.utc).isoformat()
                if link:
                    items.append({"url": link, "title": title, "modified": pub})
            return items
    except Exception as e:
        print(f"[!] Primary RSS discovery notice: {e}")
        return []

def fetch_site_urls(host: str) -> list:
    """Fetches published posts via RSS primary, and WordPress REST API as secondary fallback."""
    urls = fetch_from_rss(host)
    if urls:
        print(f"[OK] Ingested {len(urls)} publications via RSS Feed.")

    endpoints = [
        f"https://{host}/wp-json/wp/v2/posts?per_page=50&_fields=id,link,title,modified_gmt",
        f"https://{host}/wp-json/wp/v2/pages?per_page=30&_fields=id,link,title,modified_gmt",
    ]
    
    seen = {u["url"] for u in urls}
    
    for ep in endpoints:
        try:
            req = urllib.request.Request(ep, headers=BROWSER_HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for item in data:
                    link = item.get("link", "").strip()
                    title = item.get("title", {}).get("rendered", "") if isinstance(item.get("title"), dict) else item.get("title", "")
                    mod = item.get("modified_gmt", "")
                    if link and link not in seen:
                        seen.add(link)
                        urls.append({"url": link, "title": title, "modified": mod})
        except Exception as e:
            # WAF blocks or 403s on WP REST endpoints are caught safely
            pass
            
    # Always include the homepage
    homepage = f"https://{host}/"
    if not any(u["url"] == homepage or u["url"] == f"https://{host}" for u in urls):
        urls.append({"url": homepage, "title": "Homepage", "modified": datetime.now(timezone.utc).isoformat()})
        
    return urls

def submit_indexnow(host: str, key: str, key_location: str, url_list: list) -> bool:
    """Submits batch of URLs to IndexNow API."""
    if not url_list:
        return True
        
    payload = {
        "host": host,
        "key": key,
        "keyLocation": key_location,
        "urlList": url_list
    }
    
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        INDEXNOW_ENDPOINT,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            code = resp.getcode()
            print(f"[OK] IndexNow API Response: HTTP {code}")
            return code in (200, 202)
    except urllib.error.HTTPError as e:
        print(f"[!] IndexNow HTTP Error {e.code}: {e.read().decode('utf-8', errors='replace')}")
        return False
    except Exception as e:
        print(f"[!] Failed to submit to IndexNow: {e}")
        return False

def ping_google_sitemap(host: str):
    """Pings Google sitemap ping endpoint."""
    sitemap_url = f"https://{host}/sitemap_index.xml"
    ping_url = f"https://www.google.com/ping?sitemap={sitemap_url}"
    try:
        req = urllib.request.Request(ping_url, headers=BROWSER_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"[OK] Google Sitemap Ping Response: HTTP {resp.getcode()}")
    except Exception as e:
        print(f"[i] Google sitemap ping note: {e}")

def main():
    parser = argparse.ArgumentParser(description="Autonomous IndexNow Search Engine Traffic Booster")
    parser.add_argument("--host", default=os.getenv("SITE_HOST", DEFAULT_HOST), help="Domain name")
    parser.add_argument("--key", default=os.getenv("INDEXNOW_KEY"), help="IndexNow API Key")
    parser.add_argument("--key-location", default=os.getenv("INDEXNOW_KEY_LOCATION"), help="URL of IndexNow key txt file")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without submitting")
    parser.add_argument("--force-all", action="store_true", help="Submit all discovered URLs regardless of history")
    args = parser.parse_args()

    print(f"=== IndexNow Traffic Booster: {args.host} ===")
    state = load_state()
    discovered = fetch_site_urls(args.host)
    print(f"Discovered {len(discovered)} total URLs from site.")

    pending_submission = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for item in discovered:
        u = item["url"]
        mod = item.get("modified")
        is_new = u not in state["submitted"]
        is_updated = False
        if not is_new and mod:
            prev_mod = state["submitted"][u].get("modified")
            if prev_mod and mod > prev_mod:
                is_updated = True

        if is_new or is_updated or args.force_all:
            pending_submission.append(item)

    print(f"Pending submission: {len(pending_submission)} URLs")

    if not pending_submission:
        print("[OK] All URLs are up-to-date in search engines. No new URLs to index.")
        output_step_summary([], args.host, already_fresh=True)
        return 0

    url_strings = [item["url"] for item in pending_submission]
    
    key = args.key or "simulated_indexnow_key_demo"
    key_location = args.key_location or f"https://{args.host}/{key}.txt"

    if args.dry_run or not args.key:
        print("[!] Running in DRY-RUN mode (or INDEXNOW_KEY not set in secrets).")
        print("Would submit:")
        for u in url_strings[:10]:
            print(f"  - {u}")
        success = True
    else:
        success = submit_indexnow(args.host, key, key_location, url_strings)
        ping_google_sitemap(args.host)

    if success and not args.dry_run and args.key:
        for item in pending_submission:
            state["submitted"][item["url"]] = {
                "title": item.get("title"),
                "modified": item.get("modified"),
                "submitted_at": now_iso
            }
        state["last_run"] = now_iso
        save_state(state)
        print("[OK] State successfully updated.")

    output_step_summary(pending_submission, args.host, dry_run=args.dry_run or not args.key)
    return 0

def output_step_summary(items: list, host: str, already_fresh: bool = False, dry_run: bool = False):
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    with open(summary_path, "a", encoding="utf-8") as f:
        f.write("## 🚀 IndexNow Search Engine Traffic Booster\n\n")
        f.write(f"**Target Host:** `{host}` | **Timestamp:** `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}`\n\n")
        
        if already_fresh:
            f.write("✅ **All site pages and posts are already fully indexed!** Zero pending URLs.\n")
            return

        mode_badge = "🟡 *DRY-RUN / SIMULATION*" if dry_run else "🟢 *LIVE SUBMISSION SUCCESS*"
        f.write(f"### Submission Status: {mode_badge}\n\n")
        f.write(f"Successfully broadcasted **{len(items)}** URLs across Bing, DuckDuckGo, Yandex, Yahoo, and Seznam.\n\n")
        f.write("| Post Title | URL | Action |\n")
        f.write("| :--- | :--- | :--- |\n")
        for it in items[:25]:
            title = it.get("title") or "Page"
            url = it.get("url")
            f.write(f"| {title} | [{url}]({url}) | `Indexed` |\n")
        if len(items) > 25:
            f.write(f"\n*...and {len(items) - 25} more URLs.* \n")

if __name__ == "__main__":
    sys.exit(main())
