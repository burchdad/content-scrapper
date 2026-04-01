from datetime import UTC, datetime

from app.models.entity import Entity, EntityAlias, EntityMergeLog


class EntityMerger:
    """
    Merges a source entity into a target entity.

    All aliases from the source are absorbed into the target.
    A merge log entry is created for full auditability.
    Source entity should be deleted by the caller after merge.
    """

    def merge(
        self,
        source: Entity,
        target: Entity,
        merge_score: float,
        merge_reason: str,
        merged_by: str = "system",
    ) -> tuple[Entity, EntityMergeLog]:
        """
        Returns (updated_target, merge_log_entry).
        """
        existing_aliases = {a.alias.lower() for a in target.aliases}

        # Carry the source canonical name as an alias on target if distinct
        if source.canonical_name.lower() not in existing_aliases:
            target.aliases.append(
                EntityAlias(
                    entity_id=target.entity_id,
                    alias=source.canonical_name,
                    alias_type="name",
                    source=f"merged-from:{source.entity_id}",
                )
            )
            existing_aliases.add(source.canonical_name.lower())

        # Absorb all source aliases
        for alias in source.aliases:
            if alias.alias.lower() not in existing_aliases:
                target.aliases.append(
                    EntityAlias(
                        entity_id=target.entity_id,
                        alias=alias.alias,
                        alias_type=alias.alias_type,
                        source=alias.source or f"merged-from:{source.entity_id}",
                    )
                )
                existing_aliases.add(alias.alias.lower())

        # Update aggregates
        target.source_count += source.source_count
        target.confidence = min(1.0, round((target.confidence + merge_score / 100.0) / 2, 3))
        target.updated_at = datetime.now(UTC)

        target.audit_log = list(target.audit_log or []) + [
            {
                "event": "entity_merged",
                "source_entity_id": source.entity_id,
                "merge_score": merge_score,
                "merge_reason": merge_reason,
                "merged_by": merged_by,
                "merged_at": datetime.now(UTC).isoformat(),
            }
        ]

        merge_log = EntityMergeLog(
            source_entity_id=source.entity_id,
            target_entity_id=target.entity_id,
            merge_score=merge_score,
            merge_reason=merge_reason,
            merged_by=merged_by,
        )
        return target, merge_log
