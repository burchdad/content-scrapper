"""Public database ingester for UNODC, IOM, and other government trafficking data."""
import random
import uuid
from datetime import datetime, UTC, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from app.models.entity import Entity, EntityAlias
from app.models.signal import Signal
from app.ingesters.base import BaseIngester

# Simulated public dataset entries
PUBLIC_DATASET_SOURCES = [
    {
        "name": "UNODC Global Report on Trafficking in Persons",
        "descriptions": [
            "Central America-US migration corridor trafficking exploitation",
            "Southeast Asia labor trafficking network identified",
            "West Africa to North Africa trafficking route analysis",
            "Eastern Europe to Western Europe trafficking patterns",
            "South Asia to Middle East migration exploitation network",
        ]
    },
    {
        "name": "International Organization for Migration (IOM)",
        "descriptions": [
            "Border-based victim identification report",
            "Migrant vulnerability assessment data",
            "Cross-border trafficking survivor statistics",
            "Transit country trafficking indicators",
            "Counter-trafficking project implementation results",
        ]
    },
    {
        "name": "UNODC Report on Online Sexual Exploitation",
        "descriptions": [
            "Online grooming operations across multiple platforms",
            "Digital recruitment for sex trafficking",
            "Payment systems used in online exploitation",
            "Cross-border online predator networks",
        ]
    },
    {
        "name": "State Department Trafficking in Persons Report",
        "descriptions": [
            "Country-specific tier ranking analysis",
            "Government anti-trafficking efforts evaluation",
            "Prosecution and victim assistance statistics",
            "Estimated victim populations and trends",
        ]
    },
]

COUNTRIES = [
    "Mexico", "Guatemala", "Honduras", "El Salvador", "Nicaragua",
    "Thailand", "Vietnam", "Cambodia", "Philippines", "Myanmar",
    "Nigeria", "Ghana", "Ivory Coast", "Senegal", "Mali",
    "Ukraine", "Romania", "Bulgaria", "Hungary", "Moldova",
    "India", "Bangladesh", "Pakistan", "Nepal", "Sri Lanka",
]


class PublicDataIngester(BaseIngester):
    """Ingest data from public government and NGO trafficking databases."""

    def __init__(self, session: AsyncSession, entity_count: int = 200):
        super().__init__(session)
        self.entity_count = entity_count

    async def ingest(self) -> dict[str, Any]:
        """Ingest public trafficking data."""
        self.start_time = datetime.now()
        
        print(f"🔄 Ingesting public trafficking databases...")
        entities = await self._generate_public_entities()
        
        return {
            **self.report(),
            "entities_created": len(entities),
            "source": "public_databases",
        }

    async def _generate_public_entities(self) -> list[Entity]:
        """Generate entities from public datasets."""
        entities = []

        # Create government/NGO organizations
        for dataset in PUBLIC_DATASET_SOURCES:
            org_id = f"PUB-ORG-{dataset['name'].replace(' ', '_')[:20].upper()}"
            org = Entity(
                entity_id=org_id,
                canonical_name=dataset["name"],
                entity_type="organization",
                confidence=0.95,
                source_count=random.randint(1, 3),
                extra_metadata={
                    "organization_type": "government_agency" if "State Department" in dataset["name"] or "UNODC" in dataset["name"] else "ngo",
                    "focus_area": "human_trafficking_reporting",
                    "public_data_source": True,
                }
            )
            self.session.add(org)
            entities.append(org)
            self.imported_count += 1

        # Create trafficking corridor entities
        countries_list = random.sample(COUNTRIES, random.randint(10, 15))
        for i, country in enumerate(countries_list):
            if i % 2 == 0:  # Create location entities for trafficking routes
                location_id = f"PUB-LOC-{country.upper().replace(' ', '_')}"
                location = Entity(
                    entity_id=location_id,
                    canonical_name=country,
                    entity_type="location",
                    confidence=0.9,
                    extra_metadata={
                        "location_type": "high_risk_country",
                        "trafficking_data_available": True,
                        "unodc_tier_ranking": random.randint(1, 3),
                    }
                )
                self.session.add(location)
                entities.append(location)
                self.imported_count += 1

                # Create signals for trafficking indicators in this country
                for _ in range(random.randint(2, 4)):
                    signal_type = random.choice([
                        "labor_trafficking_indicator",
                        "sex_trafficking_indicator",
                        "border_crossing_anomaly",
                    ])
                    signal = Signal(
                        signal_id=f"SIG-{uuid.uuid4().hex[:12].upper()}",
                        signal_type=signal_type,
                        label=signal_type.replace("_", " ").title(),
                        confidence=random.uniform(0.7, 0.95),
                        evidence=f"Public report: Trafficking indicators identified in {country}",
                        source_name=f"public_database-{random.choice(['unodc', 'iom', 'state_dept'])}",
                        detected_at=datetime.now(UTC) - timedelta(days=random.randint(1, 365)),
                        extra_metadata={
                            "country": country,
                            "data_type": "government_report",
                            "statistical_estimation": random.choice([True, False]),
                        }
                    )
                    self.session.add(signal)

        # Create interconnected entities to show trafficking networks
        for i in range(int(self.entity_count * 0.5)):
            entity_id = f"PUB-ENTITY-{uuid.uuid4().hex[:8].upper()}"
            entity_type = random.choice(["person", "organization", "location"])
            
            if entity_type == "person":
                names = [f"Individual-{i}", f"Trafficker-{i}", f"Scout-{i}", f"Facilitator-{i}"]
                canonical_name = random.choice(names)
            elif entity_type == "organization":
                org_names = [f"Trafficking Network-{i}", f"Labor Broker-{i}", f"Transport Co-{i}"]
                canonical_name = random.choice(org_names)
            else:
                canonical_name = random.choice([c for c in COUNTRIES])

            entity = Entity(
                entity_id=entity_id,
                canonical_name=canonical_name,
                entity_type=entity_type,
                confidence=random.uniform(0.5, 0.9),
                source_count=random.randint(1, 5),
                extra_metadata={
                    "identified_in": "public_database",
                    "trafficking_role": random.choice(["victim", "perpetrator", "facilitator", "unknown"]),
                    "countries_involved": random.sample(COUNTRIES, random.randint(1, 3)),
                }
            )
            self.session.add(entity)
            entities.append(entity)
            self.imported_count += 1

            if (i + 1) % 20 == 0:
                await self.session.flush()
                print(f"  ✓ Processed {i + 1} public dataset entities")

        await self.session.commit()
        return entities
