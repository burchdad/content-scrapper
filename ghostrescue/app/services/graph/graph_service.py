from app.core.logging import get_logger
from app.models.schemas import GraphAnalyticsResponse, GraphEdge, GraphNode, GraphResponse

logger = get_logger(__name__)


class GraphService:
    """
    Manages the Neo4j knowledge graph.

    Node types  : Entity | Location | Event | Signal
    Relationships: LINKED_TO | LOCATED_AT | ASSOCIATED_WITH | TRIGGERED

    Falls back gracefully when Neo4j is not available (returns empty graph).
    """

    def __init__(self, driver) -> None:  # type: ignore[type-arg]
        self.driver = driver

    async def upsert_entity_node(
        self, entity_id: str, canonical_name: str, entity_type: str
    ) -> None:
        async with self.driver.session() as session:
            await session.run(
                """
                MERGE (e:Entity {entity_id: $entity_id})
                SET e.canonical_name = $canonical_name,
                    e.entity_type    = $entity_type
                """,
                entity_id=entity_id,
                canonical_name=canonical_name,
                entity_type=entity_type,
            )

    async def link_entities(
        self,
        source_id: str,
        target_id: str,
        relationship: str,
        properties: dict | None = None,
    ) -> None:
        props = properties or {}
        async with self.driver.session() as session:
            await session.run(
                f"""
                MATCH (a:Entity {{entity_id: $source_id}})
                MATCH (b:Entity {{entity_id: $target_id}})
                MERGE (a)-[r:{relationship}]->(b)
                SET r += $props
                """,
                source_id=source_id,
                target_id=target_id,
                props=props,
            )

    async def add_signal_node(
        self,
        signal_id: str,
        entity_id: str,
        signal_type: str,
        label: str,
        confidence: float,
    ) -> None:
        async with self.driver.session() as session:
            await session.run(
                """
                MERGE (s:Signal {signal_id: $signal_id})
                SET s.signal_type = $signal_type,
                    s.label       = $label,
                    s.confidence  = $confidence
                WITH s
                MATCH (e:Entity {entity_id: $entity_id})
                MERGE (e)-[:TRIGGERED]->(s)
                """,
                signal_id=signal_id,
                entity_id=entity_id,
                signal_type=signal_type,
                label=label,
                confidence=confidence,
            )

    async def get_entity_graph(self, entity_id: str) -> GraphResponse:
        try:
            async with self.driver.session() as session:
                result = await session.run(
                    """
                    MATCH path = (e:Entity {entity_id: $entity_id})-[*0..2]-(related)
                    RETURN nodes(path) AS nodes, relationships(path) AS rels
                    LIMIT 200
                    """,
                    entity_id=entity_id,
                )
                records = await result.data()

            nodes: dict[str, GraphNode] = {}
            edges: list[GraphEdge] = []

            for record in records:
                for node in record.get("nodes") or []:
                    node_id = node.get("entity_id") or node.get("signal_id") or str(node.id)
                    label = node.get("canonical_name") or node.get("label") or node_id
                    node_type = list(node.labels)[0] if node.labels else "Unknown"
                    nodes[node_id] = GraphNode(
                        id=node_id,
                        label=label,
                        node_type=node_type,
                        properties=dict(node),
                    )
                for rel in record.get("rels") or []:
                    edges.append(
                        GraphEdge(
                            source=str(rel.start_node.id),
                            target=str(rel.end_node.id),
                            relationship=rel.type,
                            properties=dict(rel),
                        )
                    )

            return GraphResponse(
                entity_id=entity_id,
                nodes=list(nodes.values()),
                edges=edges,
                disclaimer=(
                    "Graph data represents automated associations, not verified connections. "
                    "Human review required before drawing conclusions."
                ),
            )
        except Exception as exc:
            logger.warning("Graph query failed for %s: %s", entity_id, exc)
            return GraphResponse(
                entity_id=entity_id,
                nodes=[],
                edges=[],
                disclaimer="Graph service unavailable or entity not yet graphed.",
            )

    @staticmethod
    def analytics(graph: GraphResponse) -> GraphAnalyticsResponse:
        node_count = len(graph.nodes)
        edge_count = len(graph.edges)
        signal_node_count = sum(1 for n in graph.nodes if n.node_type.lower() == "signal")
        connected_entity_count = sum(
            1 for n in graph.nodes if n.node_type.lower() == "entity" and n.id != graph.entity_id
        )
        centrality_hint = round(min(1.0, (edge_count / max(1, node_count * 2))), 3)

        adjacency: dict[str, set[str]] = {}
        for edge in graph.edges:
            adjacency.setdefault(edge.source, set()).add(edge.target)
            adjacency.setdefault(edge.target, set()).add(edge.source)

        visited: set[str] = set()
        community_count = 0
        for node in [n.id for n in graph.nodes]:
            if node in visited:
                continue
            community_count += 1
            stack = [node]
            while stack:
                cur = stack.pop()
                if cur in visited:
                    continue
                visited.add(cur)
                stack.extend(list(adjacency.get(cur, set()) - visited))

        influence_score = round(min(1.0, centrality_hint * 0.65 + min(0.35, connected_entity_count * 0.07)), 3)
        insight = (
            f"Entity neighborhood contains {connected_entity_count} linked entities, "
            f"{signal_node_count} signal nodes, and {community_count} communities. "
            "Higher influence and centrality may indicate broader network relevance and should be reviewed by an analyst."
        )
        return GraphAnalyticsResponse(
            entity_id=graph.entity_id,
            node_count=node_count,
            edge_count=edge_count,
            signal_node_count=signal_node_count,
            connected_entity_count=connected_entity_count,
            centrality_hint=centrality_hint,
            community_count=community_count,
            influence_score=influence_score,
            insight=insight,
            disclaimer=graph.disclaimer,
        )
