#!/usr/bin/env python3
"""Fetch INTERPOL Red Notices from the public API and save to a local JSON file.

The INTERPOL public web service (ws-public.interpol.int/notices/v1/red) is
accessible with browser-like HTTP headers.  This script replicates those
headers so you can pull live data from the command line and seed the database.

Usage
-----
# Pull page 1 (20 records), with charge details, save to default path:
    python scripts/fetch_interpol_notices.py

# Pull 5 pages (up to 100 records), no detail enrichment (faster):
    python scripts/fetch_interpol_notices.py --pages 5 --no-details

# Save to a custom path:
    python scripts/fetch_interpol_notices.py --pages 3 --output data/interpol.json

# Then ingest the saved file:
    INTERPOL_DATA_FILE=data/interpol.json python scripts/populate_live_data.py

Notes
-----
- Each page contains up to 20 records; the API caps resultPerPage at 20.
- --details fetches one additional HTTP request per notice to retrieve
  charge/arrest_warrant data.  Polite rate-limiting (0.3 s between requests)
  is applied automatically.
- The INTERPOL notice list is public information published to alert the public.
  Per their disclaimer, data may only be used for its designated purpose.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import httpx

_API_BASE = "https://ws-public.interpol.int/notices/v1/red"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.interpol.int/",
    "Origin": "https://www.interpol.int",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}
_RATE_LIMIT_S = 0.3


def fetch_notices(pages: int, per_page: int, fetch_details: bool) -> list[dict]:
    all_notices: list[dict] = []

    with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=15) as client:
        for page in range(1, pages + 1):
            print(f"  Fetching page {page}/{pages} ...", end=" ", flush=True)
            resp = client.get(_API_BASE, params={"resultPerPage": per_page, "page": page})
            resp.raise_for_status()
            data = resp.json()
            notices = data.get("_embedded", {}).get("notices", [])
            print(f"{len(notices)} notices  (total in API: {data.get('total', '?')})")
            if not notices:
                print("  No more results.")
                break

            if fetch_details:
                for i, notice in enumerate(notices, start=1):
                    detail_url = notice.get("_links", {}).get("self", {}).get("href", "")
                    if detail_url:
                        time.sleep(_RATE_LIMIT_S)
                        dr = client.get(detail_url)
                        if dr.status_code == 200:
                            notice.update(dr.json())
                        print(
                            f"    [{i:02d}/{len(notices)}] {notice.get('forename', '')} "
                            f"{notice.get('name', '')} — charges: "
                            + (
                                "; ".join(
                                    w.get("charge_translation") or w.get("charge", "")
                                    for w in notice.get("arrest_warrants", [])
                                )
                                or "n/a"
                            )
                        )

            all_notices.extend(notices)
            time.sleep(_RATE_LIMIT_S)

    return all_notices


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch INTERPOL Red Notices")
    parser.add_argument("--pages", type=int, default=1, help="Number of pages to fetch (20 records each)")
    parser.add_argument("--per-page", type=int, default=20, help="Results per page (max 20)")
    parser.add_argument("--details", action="store_true", default=True, help="Fetch charge details per notice (default: on)")
    parser.add_argument("--no-details", dest="details", action="store_false", help="Skip per-notice detail requests (faster)")
    parser.add_argument(
        "--output",
        type=str,
        default=str(Path(__file__).parent.parent / "sample_data" / "interpol_red_notices.json"),
        help="Output JSON file path",
    )
    args = parser.parse_args()

    per_page = min(max(1, args.per_page), 20)

    print(f"INTERPOL Red Notice Fetcher")
    print(f"  Pages:        {args.pages}")
    print(f"  Per page:     {per_page}")
    print(f"  Fetch details:{args.details}")
    print(f"  Output:       {args.output}")
    print()

    try:
        notices = fetch_notices(pages=args.pages, per_page=per_page, fetch_details=args.details)
    except httpx.HTTPStatusError as e:
        print(f"\nHTTP error: {e}", file=sys.stderr)
        sys.exit(1)
    except httpx.RequestError as e:
        print(f"\nNetwork error: {e}", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(notices, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nSaved {len(notices)} notices → {out_path}")
    print("Next: python scripts/populate_live_data.py  (or use the dashboard Import button)")


if __name__ == "__main__":
    main()
