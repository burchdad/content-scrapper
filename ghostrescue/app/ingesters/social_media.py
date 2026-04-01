"""Social media ingester for trafficking indicators from public posts."""
import random
import uuid
from datetime import datetime, UTC, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from app.models.entity import Entity, EntityAlias
from app.models.signal import Signal
from app.ingesters.base import BaseIngester

# Simulated social media posts with trafficking indicators
SOCIAL_POSTS = [
    {
        "text": "Looking for workers for overseas employment. Free housing provided. Contact via Telegram. High pay guaranteed.",
        "indicators": ["labor_trafficking_indicator", "false_identity_detected"],
        "platform": "facebook",
    },
    {
        "text": "International escort service. Call now. Fresh arrivals daily. Discretion guaranteed.",
        "indicators": ["sex_trafficking_indicator", "coercion_language_detected"],
        "platform": "twitter",
    },
    {
        "text": "We help with visa processing. Fast and easy. Money transfer needed upfront. Document provided.",
        "indicators": ["document_fraud_detected", "financial_transfer_alert"],
        "platform": "instagram",
    },
    {
        "text": "If you can't pay your debt, you will disappear. Stop calling family members.",
        "indicators": ["debt_bondage_pattern", "coercion_language_detected"],
        "platform": "telegram",
    },
    {
        "text": "Your papers will be confiscated until work is complete. This is normal procedure.",
        "indicators": ["document_fraud_detected", "labor_trafficking_indicator"],
        "platform": "whatsapp",
    },
    {
        "text": "Job opportunity in agriculture. Room and board included. Salary upon completion.",
        "indicators": ["labor_trafficking_indicator", "financial_transfer_alert"],
        "platform": "facebook",
    },
    {
        "text": "Safe passage to North arranged. $5000 total. Payment in installments accepted.",
        "indicators": ["border_crossing_anomaly", "financial_transfer_alert"],
        "platform": "twitter",
    },
    {
        "text": "You are not allowed to leave the premises without supervisor approval.",
        "indicators": ["isolation_behavior", "coercion_language_detected"],
        "platform": "telegram",
    },
]

USERNAMES = [
    "maria.looking.work", "juancarlos1985", "sofia_international", "global.employment.svc",
    "visa.solutions.24", "overseas.jobs.agency", "travel_guide_2024", "employment_broker_mx",
    "border.facilitator", "document.services", "labor.opportunities", "international.transport",
]

CITIES = [
    "Los Angeles", "Houston", "NYC", "Phoenix", "Miami", "Cancun",
    "Tijuana", "Guatemala City", "San Salvador", "Tegucigalpa", "San Pedro Sula"
]


class SocialMediaIngester(BaseIngester):
    """Simulate social media post ingestion for trafficking indicators."""

    def __init__(self, session: AsyncSession, post_count: int = 100):
        super().__init__(session)
        self.post_count = post_count

    async def ingest(self) -> dict[str, Any]:
        """Generate and ingest simulated social media posts."""
        self.start_time = datetime.now()
        
        print(f"🔄 Generating {self.post_count} simulated social media posts...")
        posts = await self._generate_posts()
        
        return {
            **self.report(),
            "posts_processed": len(posts),
            "source": "social_media_simulator",
        }

    async def _generate_posts(self) -> list[dict]:
        """Generate simulated social media posts."""
        posts = []

        for i in range(self.post_count):
            post = random.choice(SOCIAL_POSTS)
            username = random.choice(USERNAMES)
            location = random.choice(CITIES)
            
            # Create poster entity
            poster_entity_id = f"SOCIAL-{uuid.uuid4().hex[:8].upper()}"
            poster_entity = Entity(
                entity_id=poster_entity_id,
                canonical_name=username,
                entity_type="person",
                confidence=random.uniform(0.5, 0.85),
                extra_metadata={
                    "social_platform": post["platform"],
                    "location": location,
                    "post_type": "trafficking_indicator",
                    "engagement": random.randint(10, 1000),
                }
            )

            # Add username as alias
            alias = EntityAlias(
                entity_id=poster_entity_id,
                alias=username,
                alias_type="username",
                source=f"social_media-{post['platform']}"
            )
            poster_entity.aliases.append(alias)

            self.session.add(poster_entity)
            self.session.add(alias)

            # Create signals from post content
            for signal_type in post["indicators"]:
                signal = Signal(
                    signal_id=f"SIG-{uuid.uuid4().hex[:12].upper()}",
                    signal_type=signal_type,
                    label=signal_type.replace("_", " ").title(),
                    confidence=random.uniform(0.6, 0.95),
                    evidence=f"Post by {username}: {post['text'][:80]}...",
                    source_name=f"social_media-{post['platform']}",
                    detected_at=datetime.now(UTC) - timedelta(days=random.randint(1, 60)),
                    extra_metadata={
                        "platform": post["platform"],
                        "post_content": post["text"],
                        "poster_username": username,
                        "detection_method": "keyword_matching",
                    }
                )
                self.session.add(signal)
                self.imported_count += 1

            posts.append({
                "entity_id": poster_entity_id,
                "platform": post["platform"],
                "signals": post["indicators"],
            })

            if (i + 1) % 10 == 0:
                await self.session.flush()
                print(f"  ✓ Generated {i + 1}/{self.post_count} posts")

        await self.session.commit()
        return posts
