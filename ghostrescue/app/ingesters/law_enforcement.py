"""Law enforcement records ingester for public case data."""
import random
import uuid
from datetime import datetime, UTC, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from app.models.entity import Entity, EntityAlias
from app.models.signal import Signal
from app.models.case import Case
from app.ingesters.base import BaseIngester

# Simulated law enforcement case templates
LE_CASE_TEMPLATES = [
    {
        "description": "Investigation into labor trafficking ring operating agricultural labor camps",
        "location": "California Central Valley",
        "victim_count": random.randint(5, 20),
        "perpetrators": random.randint(2, 8),
        "signals": ["labor_trafficking_indicator", "document_fraud_detected", "isolation_behavior"],
    },
    {
        "description": "International sex trafficking operation dismantled, multiple victims recovered",
        "location": "Texas-Mexico Border",
        "victim_count": random.randint(3, 15),
        "perpetrators": random.randint(3, 12),
        "signals": ["sex_trafficking_indicator", "financial_transfer_alert", "coercion_language_detected"],
    },
    {
        "description": "Financial investigation into debt bondage scheme covering multiple states",
        "location": "Multi-state",
        "victim_count": random.randint(10, 50),
        "perpetrators": random.randint(5, 15),
        "signals": ["debt_bondage_pattern", "money_transfer_pattern", "financial_transfer_alert"],
    },
    {
        "description": "Document fraud network supplying false travel documents for trafficking victims",
        "location": "Border Region",
        "victim_count": random.randint(20, 100),
        "perpetrators": random.randint(8, 20),
        "signals": ["document_fraud_detected", "false_identity_detected", "border_crossing_anomaly"],
    },
    {
        "description": "Online recruitment scheme targeting vulnerable migrants",
        "location": "Digital/Multi-location",
        "victim_count": random.randint(15, 40),
        "perpetrators": random.randint(4, 10),
        "signals": ["labor_trafficking_indicator", "coercion_language_detected", "false_identity_detected"],
    },
]


class LawEnforcementIngester(BaseIngester):
    """Ingest simulated law enforcement case records."""

    def __init__(self, session: AsyncSession, case_count: int = 50):
        super().__init__(session)
        self.case_count = case_count

    async def ingest(self) -> dict[str, Any]:
        """Generate and ingest law enforcement cases."""
        self.start_time = datetime.now()
        
        print(f"🔄 Generating {self.case_count} law enforcement cases...")
        cases = await self._generate_cases()
        
        return {
            **self.report(),
            "cases_created": len(cases),
            "source": "law_enforcement_records",
        }

    async def _generate_cases(self) -> list[Case]:
        """Generate law enforcement cases."""
        cases = []

        for i in range(self.case_count):
            template = random.choice(LE_CASE_TEMPLATES)
            case_id = f"LE-{uuid.uuid4().hex[:6].upper()}"

            # Create entities for this case
            entity_ids = []
            
            # Create victim entities
            for _ in range(random.randint(1, min(5, template["victim_count"]))):
                victim = await self._create_victim_entity()
                entity_ids.append(victim.entity_id)

            # Create perpetrator entities
            for _ in range(random.randint(1, min(4, template["perpetrators"]))):
                perpetrator = await self._create_perpetrator_entity()
                entity_ids.append(perpetrator.entity_id)

            # Create organization entity (if applicable)
            if random.random() > 0.3:
                org = await self._create_criminal_org_entity()
                entity_ids.append(org.entity_id)

            # Create signals
            signal_ids = []
            for signal_type in template["signals"]:
                signal = Signal(
                    signal_id=f"SIG-{uuid.uuid4().hex[:12].upper()}",
                    signal_type=signal_type,
                    label=signal_type.replace("_", " ").title(),
                    confidence=random.uniform(0.8, 1.0),
                    evidence=f"LE Investigation: {template['description']}",
                    source_name="law_enforcement_report",
                    detected_at=datetime.now(UTC) - timedelta(days=random.randint(30, 365)),
                    extra_metadata={
                        "case_type": "law_enforcement",
                        "location": template["location"],
                        "investigation_status": random.choice(["open", "closed", "ongoing"]),
                    }
                )
                self.session.add(signal)
                await self.session.flush()
                signal_ids.append(signal.signal_id)

            # Create case
            case = Case(
                case_id=case_id,
                status=random.choice(["closed", "under_review"]),
                risk_score=random.uniform(0.8, 1.0),
                confidence_score=random.uniform(0.75, 0.98),
                system_confidence=random.uniform(0.8, 0.95),
                entity_ids=entity_ids,
                signal_ids=signal_ids,
                notes=template["description"],
                extra_metadata={
                    "source": "law_enforcement",
                    "victim_count": template["victim_count"],
                    "perpetrator_count": template["perpetrators"],
                    "location": template["location"],
                    "report_status": "public_record",
                }
            )

            self.session.add(case)
            self.imported_count += 1
            cases.append(case)

            if (i + 1) % 5 == 0:
                await self.session.flush()
                print(f"  ✓ Generated {i + 1}/{self.case_count} cases")

        await self.session.commit()
        return cases

    async def _create_victim_entity(self) -> Entity:
        """Create a victim entity."""
        first_names = ["Maria", "Sofia", "Ana", "Elena", "Rosa", "Carmen", "Juan", "Miguel", "Carlos"]
        last_names = ["Garcia", "Rodriguez", "Martinez", "Lopez", "Sanchez", "Torres"]
        
        entity_id = f"LE-VICTIM-{uuid.uuid4().hex[:8].upper()}"
        entity = Entity(
            entity_id=entity_id,
            canonical_name=f"{random.choice(first_names)} {random.choice(last_names)}",
            entity_type="person",
            confidence=0.95,
            extra_metadata={
                "profile": "trafficking_victim",
                "case_status": random.choice(["recovered", "missing", "deceased"]),
                "source": "law_enforcement",
            }
        )
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def _create_perpetrator_entity(self) -> Entity:
        """Create a perpetrator entity."""
        entity_id = f"LE-PERP-{uuid.uuid4().hex[:8].upper()}"
        entity = Entity(
            entity_id=entity_id,
            canonical_name=f"Suspect-{uuid.uuid4().hex[:6].upper()}",
            entity_type="person",
            confidence=0.85,
            extra_metadata={
                "profile": "trafficking_suspect",
                "case_status": random.choice(["arrested", "at_large", "deported"]),
                "source": "law_enforcement",
            }
        )
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def _create_criminal_org_entity(self) -> Entity:
        """Create a criminal organization entity."""
        entity_id = f"LE-ORG-{uuid.uuid4().hex[:8].upper()}"
        entity = Entity(
            entity_id=entity_id,
            canonical_name=f"Criminal Network {uuid.uuid4().hex[:4].upper()}",
            entity_type="organization",
            confidence=0.8,
            extra_metadata={
                "profile": "trafficking_organization",
                "operational_countries": random.randint(2, 5),
                "source": "law_enforcement",
            }
        )
        self.session.add(entity)
        await self.session.flush()
        return entity
