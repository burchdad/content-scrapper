#!/usr/bin/env python3
"""Fetch public NamUs Missing Persons search results and save them to JSON.

Usage examples:
    python scripts/fetch_namus_missing_persons.py
    python scripts/fetch_namus_missing_persons.py --pages 4 --per-page 25
    python scripts/fetch_namus_missing_persons.py --last-name burch --output data/namus.json
    python scripts/fetch_namus_missing_persons.py --case-number MP127395
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.ingesters.namus import NamUsIngester


async def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch live NamUs missing person records")
    parser.add_argument("--pages", type=int, default=1, help="Number of result pages to fetch")
    parser.add_argument("--per-page", type=int, default=25, help="Rows per page (max 100)")
    parser.add_argument("--no-details", action="store_true", help="Skip case detail enrichment")
    parser.add_argument("--last-name", type=str, default=None, help="Filter by last name contains")
    parser.add_argument("--first-name", type=str, default=None, help="Filter by first name contains")
    parser.add_argument("--case-number", type=str, default=None, help="Filter by NamUs case number")
    parser.add_argument("--city", type=str, default=None, help="Filter by city of last contact")
    parser.add_argument("--state", type=str, default=None, help="Filter by state of last contact")
    parser.add_argument(
        "--output",
        type=str,
        default=str(Path(__file__).parent.parent / "sample_data" / "namus_missing_persons_live.json"),
        help="Output JSON path",
    )
    args = parser.parse_args()

    database_url = "sqlite+aiosqlite:///./ghostrescue.db"
    engine = create_async_engine(database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        ingester = NamUsIngester(
            session,
            live=True,
            pages=args.pages,
            per_page=args.per_page,
            fetch_details=not args.no_details,
            last_name=args.last_name,
            first_name=args.first_name,
            case_number=args.case_number,
            city=args.city,
            state=args.state,
        )
        records = await ingester._load_records()

    await engine.dispose()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(records, indent=2), encoding="utf-8")

    print(f"Saved {len(records)} NamUs records to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
