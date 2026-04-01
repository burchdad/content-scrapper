"""Synthetic data generator for realistic trafficking scenarios."""
import random
import uuid
from datetime import datetime, timedelta, UTC
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from app.models.entity import Entity, EntityAlias
from app.models.signal import Signal
from app.models.case import Case
from app.ingesters.base import BaseIngester

# Synthetic data templates
FIRST_NAMES = [
    "Maria", "Juan", "Sofia", "Carlos", "Ana", "Miguel", "Rosa", "Jorge",
    "Lucia", "Marco", "Isabella", "Diego", "Elena", "Felipe", "Valentina",
    "Ricardo", "Camila", "Antonio", "Gabriela", "Luis", "Martina", "Jose",
    "Emma", "Mateo", "Sophia", "Alexander", "Victoria", "Ethan", "Olivia"
]

LAST_NAMES = [
    "Rodriguez", "Garcia", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Sanchez", "Torres", "Flores", "Morales", "Jimenez", "Reyes", "Diaz",
    "Silva", "Santos", "Navarro", "Romero", "Rivas", "Ibarra", "Castillo",
    "Vasquez", "Ortega", "Medina", "Cuevas", "Rojas", "Cordova", "Herrera"
]

LOCATIONS = [
    "Los Angeles, CA", "Houston, TX", "New York, NY", "Atlanta, GA",
    "Chicago, IL", "Phoenix, AZ", "San Diego, CA", "Miami, FL",
    "Las Vegas, NV", "Denver, CO", "San Francisco, CA", "Seattle, WA",
    "Boston, MA", "Dallas, TX", "Washington, DC", "Mexico City",
    "Cancun", "Tijuana", "Guatemala City", "San Salvador", "Tegucigalpa"
]

ORGANIZATION_NAMES = [
    "Global Labor Network", "Safe Haven Operations", "Trans-Border Solutions",
    "Pacific Trade LLC", "Continental Supply Chain", "Border Commerce Inc",
    "International Logistics", "United Trade Partners", "Central Exchange Corp",
    "Harmony Transport", "Cross-Border Services", "Nations Commercial"
]

SIGNAL_TYPES = [
    "travel_document_anomaly",
    "financial_transfer_alert",
    "labor_trafficking_indicator",
    "sex_trafficking_indicator",
    "document_fraud_detected",
    "coercion_language_detected",
    "victim_interview_match",
    "law_enforcement_report",
    "ngo_report",
    "border_crossing_anomaly",
    "debt_bondage_pattern",
    "isolation_behavior",
    "money_transfer_pattern",
    "false_identity_detected"
]

SIGNAL_DESCRIPTIONS = {
    "travel_document_anomaly": "Unusual travel documents or patterns detected",
    "financial_transfer_alert": "Suspicious financial transfers to high-risk regions",
    "labor_trafficking_indicator": "Employment situation shows trafficking indicators",
    "sex_trafficking_indicator": "Behavioral or communication patterns suggest exploitation",
    "document_fraud_detected": "Documents appear fraudulent or forged",
    "coercion_language_detected": "Communications contain coercion or control language",
    "victim_interview_match": "Person matches known trafficking victim profile",
    "law_enforcement_report": "Referenced in law enforcement intelligence report",
    "ngo_report": "Mentioned in NGO trafficking report or alert",
    "border_crossing_anomaly": "Border crossing patterns indicate trafficking route",
    "debt_bondage_pattern": "Financial arrangements suggest debt bondage scheme",
    "isolation_behavior": "Communication patterns suggest isolation/control",
    "money_transfer_pattern": "Money transfers match known trafficking payment pattern",
    "false_identity_detected": "Multiple identities linked to same individual"
}


class SyntheticDataIngester(BaseIngester):
    """Generate realistic synthetic trafficking data for system testing."""

    def __init__(self, session: AsyncSession, entity_count: int = 300, case_count: int = 60):
        super().__init__(session)
        self.entity_count = entity_count
        self.case_count = case_count

    async def ingest(self) -> dict[str, Any]:
        """Generate and ingest synthetic data."""
        self.start_time = datetime.now()
        
        print(f"🔄 Generating {self.entity_count} synthetic entities...")
        entities = await self._generate_entities()
        
        print(f"🔄 Generating {self.case_count} synthetic cases...")
        cases = await self._generate_cases(entities)
        
        return {
            **self.report(),
            "entities_created": len(entities),
            "cases_created": len(cases),
            "source": "synthetic_generator",
        }

    async def _generate_entities(self) -> list[Entity]:
        """Generate synthetic entities."""
        entities = []
        
        # People (70%)
        for _ in range(int(self.entity_count * 0.7)):
            entity = await self._create_person_entity()
            entities.append(entity)
            self.imported_count += 1

        # Organizations (20%)
        for _ in range(int(self.entity_count * 0.2)):
            entity = await self._create_org_entity()
            entities.append(entity)
            self.imported_count += 1

        # Locations (10%)
        for _ in range(int(self.entity_count * 0.1)):
            entity = await self._create_location_entity()
            entities.append(entity)
            self.imported_count += 1

        return entities

    async def _create_person_entity(self) -> Entity:
        """Create a synthetic person entity."""
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        canonical_name = f"{first} {last}"
        entity_id = f"SYNTH-PERSON-{uuid.uuid4().hex[:8].upper()}"

        entity = Entity(
            entity_id=entity_id,
            canonical_name=canonical_name,
            entity_type="person",
            confidence=random.uniform(0.6, 1.0),
            source_count=random.randint(1, 5),
            extra_metadata={
                "last_known_location": random.choice(LOCATIONS),
                "age_estimate": random.randint(18, 65),
                "profile_risk": random.choice(["potential_victim", "potential_perpetrator", "witness", "unknown"]),
                "data_source": "synthetic",
            }
        )

        # Add aliases
        aliases = [
            f"{first[0]}. {last}",
            last,
            f"{first} {last[0]}.",
        ]
        
        for alias_name in aliases:
            alias = EntityAlias(
                entity_id=entity_id,
                alias=alias_name,
                alias_type="name",
                source="synthetic"
            )
            entity.aliases.append(alias)

        self.session.add(entity)
        await self.session.flush()
        return entity

    async def _create_org_entity(self) -> Entity:
        """Create a synthetic organization entity."""
        org_name = random.choice(ORGANIZATION_NAMES)
        entity_id = f"SYNTH-ORG-{uuid.uuid4().hex[:8].upper()}"

        entity = Entity(
            entity_id=entity_id,
            canonical_name=org_name,
            entity_type="organization",
            confidence=random.uniform(0.5, 1.0),
            source_count=random.randint(1, 3),
            extra_metadata={
                "location": random.choice(LOCATIONS),
                "operation_type": random.choice(["labor_service", "transport", "employment_agency", "trading", "import_export"]),
                "risk_profile": random.choice(["high", "medium", "low", "unknown"]),
                "data_source": "synthetic",
            }
        )

        self.session.add(entity)
        await self.session.flush()
        return entity

    async def _create_location_entity(self) -> Entity:
        """Create a synthetic location entity."""
        location = random.choice(LOCATIONS)
        entity_id = f"SYNTH-LOC-{uuid.uuid4().hex[:8].upper()}"

        entity = Entity(
            entity_id=entity_id,
            canonical_name=location,
            entity_type="location",
            confidence=1.0,
            source_count=random.randint(1, 2),
            extra_metadata={
                "location_type": random.choice(["city", "border_point", "transit_hub"]),
                "is_key_trafficking_route": random.choice([True, False]),
                "data_source": "synthetic",
            }
        )

        self.session.add(entity)
        await self.session.flush()
        return entity

    async def _generate_cases(self, entities: list[Entity]) -> list[Case]:
        """Generate synthetic cases connecting entities."""
        cases = []
        random.shuffle(entities)

        existing_synth_cases = await self.session.execute(
            select(func.count(Case.id)).where(Case.case_id.like("SYNTH-CASE-%"))
        )
        case_offset = existing_synth_cases.scalar() or 0

        for i in range(self.case_count):
            case_id = f"SYNTH-CASE-{case_offset + i + 1:04d}"
            
            # 3-7 entities per case
            num_entities = random.randint(3, 7)
            case_entities = random.sample(entities, min(num_entities, len(entities)))
            entity_ids = [e.entity_id for e in case_entities]

            # Generate signals for the case
            signal_ids = []
            for _ in range(random.randint(4, 8)):
                signal_type = random.choice(SIGNAL_TYPES)
                signal = Signal(
                    signal_id=f"SIG-{uuid.uuid4().hex[:12].upper()}",
                    signal_type=signal_type,
                    label=signal_type.replace("_", " ").title(),
                    confidence=random.uniform(0.3, 1.0),
                    evidence=SIGNAL_DESCRIPTIONS.get(signal_type, ""),
                    source_name="synthetic_generator",
                    detected_at=datetime.now(UTC) - timedelta(days=random.randint(1, 30)),
                    extra_metadata={
                        "detection_method": random.choice(["keyword_match", "pattern_analysis", "nlp_score", "manual_report"]),
                    }
                )
                self.session.add(signal)
                await self.session.flush()
                signal_ids.append(signal.signal_id)

            case = Case(
                case_id=case_id,
                status=random.choice(["open", "under_review", "escalated"]),
                risk_score=random.uniform(0.4, 1.0),
                confidence_score=random.uniform(0.3, 0.95),
                system_confidence=random.uniform(0.4, 0.9),
                entity_ids=entity_ids,
                signal_ids=signal_ids,
                notes=f"Synthetic case generated for testing trafficking indicators across {len(case_entities)} entities",
                extra_metadata={
                    "trafficking_type": random.choice(["labor", "sex", "mixed", "unknown"]),
                    "generator_version": "synthetic_v1",
                    "test_scenario": random.choice(["border_crossing", "labor_exploitation", "online_recruitment"]),
                }
            )

            self.session.add(case)
            self.imported_count += 1
            cases.append(case)

        await self.session.commit()
        return cases
