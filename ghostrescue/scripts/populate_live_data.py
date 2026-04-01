#!/usr/bin/env python
"""Populate GhostRescue database with live data from multiple sources."""
import asyncio
import os
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.ingesters.synthetic import SyntheticDataIngester
from app.ingesters.social_media import SocialMediaIngester
from app.ingesters.law_enforcement import LawEnforcementIngester
from app.ingesters.public_data import PublicDataIngester
from app.ingesters.newsapi import NewsAPIIngester
from app.ingesters.namus import NamUsIngester
from app.ingesters.interpol import InterpolIngester


async def main():
    """Run all data ingesters."""
    print("🚀 GhostRescue Live Data Population")
    print("=" * 60)

    # Database setup
    DATABASE_URL = "sqlite+aiosqlite:///./ghostrescue.db"
    engine = create_async_engine(DATABASE_URL, echo=False)

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    results = {
        "timestamp": str(__import__("datetime").datetime.now()),
        "ingesters": {}
    }

    async with async_session() as session:
        # 1. Synthetic data (baseline)
        print("\n📊 INGESTER 1: Synthetic Trafficking Data Generator")
        print("-" * 60)
        ingester = SyntheticDataIngester(session, entity_count=300, case_count=60)
        result = await ingester.ingest()
        results["ingesters"]["synthetic"] = result
        print(f"✅ Imported {result['imported_count']} entities/cases")
        print(f"   Duration: {result['duration_seconds']:.2f}s")

        # 2. Social media (simulated)
        print("\n📱 INGESTER 2: Social Media (Trafficking Indicators)")
        print("-" * 60)
        ingester = SocialMediaIngester(session, post_count=100)
        result = await ingester.ingest()
        results["ingesters"]["social_media"] = result
        print(f"✅ Processed {result['imported_count']} social media posts/signals")
        print(f"   Duration: {result['duration_seconds']:.2f}s")

        # 3. Public databases
        print("\n🏛️  INGESTER 3: Public Trafficking Databases (UNODC, IOM, State Dept)")
        print("-" * 60)
        ingester = PublicDataIngester(session, entity_count=200)
        result = await ingester.ingest()
        results["ingesters"]["public_data"] = result
        print(f"✅ Ingested {result['imported_count']} public dataset entities")
        print(f"   Duration: {result['duration_seconds']:.2f}s")

        # 4. Law enforcement cases
        print("\n🚔 INGESTER 4: Law Enforcement Records")
        print("-" * 60)
        ingester = LawEnforcementIngester(session, case_count=50)
        result = await ingester.ingest()
        results["ingesters"]["law_enforcement"] = result
        print(f"✅ Created {result['imported_count']} LE case records")
        print(f"   Duration: {result['duration_seconds']:.2f}s")

        # 5. News API (if configured)
        print("\n📰 INGESTER 5: News Articles (NewsAPI)")
        print("-" * 60)
        ingester = NewsAPIIngester(session)
        result = await ingester.ingest()
        results["ingesters"]["newsapi"] = result
        if result.get("skipped"):
            print(f"⏭️  Skipped: {result['reason']}")
            print("   (Set NEWSAPI_KEY env variable to enable)")
        else:
            print(f"✅ Processed {result['imported_count']} news articles")
        print(f"   Duration: {result['duration_seconds']:.2f}s")

        # 6. NamUs ingestion
        print("\n🔎 INGESTER 6: NamUs Missing Persons")
        print("-" * 60)
        namus_live = os.getenv("NAMUS_LIVE", "false").lower() in {"1", "true", "yes", "on"}
        if namus_live:
            ingester = NamUsIngester(
                session,
                live=True,
                pages=int(os.getenv("NAMUS_PAGES", "1")),
                per_page=int(os.getenv("NAMUS_PER_PAGE", "25")),
                fetch_details=os.getenv("NAMUS_FETCH_DETAILS", "true").lower() in {"1", "true", "yes", "on"},
                last_name=os.getenv("NAMUS_LAST_NAME"),
                first_name=os.getenv("NAMUS_FIRST_NAME"),
                case_number=os.getenv("NAMUS_CASE_NUMBER"),
                city=os.getenv("NAMUS_CITY"),
                state=os.getenv("NAMUS_STATE"),
            )
            print("   Mode: live registry")
        else:
            namus_file = os.getenv("NAMUS_DATA_FILE", "sample_data/namus_missing_persons.json")
            ingester = NamUsIngester(session, data_file=namus_file)
            print("   Mode: local export file")
        result = await ingester.ingest()
        results["ingesters"]["namus"] = result
        if result.get("skipped"):
            print(f"⏭️  Skipped: {result['reason']}")
            print("   (Set NAMUS_LIVE=true for live registry access, or NAMUS_DATA_FILE for local JSON/CSV)")
        else:
            print(f"✅ Ingested {result.get('records_loaded', 0)} NamUs records")
        print(f"   Duration: {result['duration_seconds']:.2f}s")

        # 7. Interpol Red Notices export file ingestion
        print("\n🔎 INGESTER 7: Interpol Red Notices (Local Export)")
        print("-" * 60)
        interpol_file = os.getenv("INTERPOL_DATA_FILE", "sample_data/interpol_red_notices.json")
        ingester = InterpolIngester(session, data_file=interpol_file)
        result = await ingester.ingest()
        results["ingesters"]["interpol"] = result
        if result.get("skipped"):
            print(f"⏭️  Skipped: {result['reason']}")
            print("   (Set INTERPOL_DATA_FILE to your Interpol JSON/CSV export path)")
        else:
            print(f"✅ Ingested {result.get('records_loaded', 0)} Interpol notices")
        print(f"   Duration: {result['duration_seconds']:.2f}s")

    # Summary
    print("\n" + "=" * 60)
    print("📈 INGESTION SUMMARY")
    print("=" * 60)
    
    total_imported = sum(r.get("imported_count", 0) for r in results["ingesters"].values())
    total_errors = sum(r.get("error_count", 0) for r in results["ingesters"].values())
    
    print(f"✅ Total Imported: {total_imported}")
    print(f"❌ Total Errors: {total_errors}")
    print(f"🗄️  Database: ghostrescue.db")
    print("\n📊 Breakdown:")
    for ingester_name, result in results["ingesters"].items():
        print(f"  • {ingester_name:20} → {result.get('imported_count', 0):4} items")

    print("\n✨ Live data population complete!")
    print("🎯 Next: python scripts/run_live_test.py")
    print("💻 Then: Access dashboard at http://localhost:8000/dashboard")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
