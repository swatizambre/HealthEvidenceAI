"""Queryable evidence graph from a completed review."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.api import AuthorizationReviewResponse


@dataclass
class GraphNode:
    id: str
    type: str
    label: str


@dataclass
class GraphEdge:
    source: str
    target: str
    type: str


@dataclass
class EvidenceGraph:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)

    def query(self, *, node_type: str | None = None, edge_type: str | None = None) -> EvidenceGraph:
        nodes = [n for n in self.nodes if node_type is None or n.type == node_type]
        node_ids = {n.id for n in nodes}
        edges = [
            e
            for e in self.edges
            if (edge_type is None or e.type == edge_type)
            and (node_type is None or (e.source in node_ids or e.target in node_ids))
        ]
        if edge_type and node_type is None:
            related = {e.source for e in edges} | {e.target for e in edges}
            nodes = [n for n in self.nodes if n.id in related]
        return EvidenceGraph(nodes=nodes, edges=edges)


def build_evidence_graph(review: AuthorizationReviewResponse) -> EvidenceGraph:
    graph = EvidenceGraph()
    patient_id = f"patient:{review.patient_id}"
    policy_id = f"policy:{review.policy_id}"
    graph.nodes.append(GraphNode(id=patient_id, type="Patient", label=review.patient_id))
    graph.nodes.append(GraphNode(id=policy_id, type="Policy", label=review.policy_id))
    graph.edges.append(GraphEdge(source=patient_id, target=policy_id, type="GOVERNED_BY"))
    for criterion in review.criteria:
        criterion_id = f"criterion:{criterion.criterion_id}"
        graph.nodes.append(
            GraphNode(id=criterion_id, type="PolicyCriterion", label=criterion.criterion)
        )
        graph.edges.append(GraphEdge(source=criterion_id, target=policy_id, type="BELONGS_TO"))
        graph.edges.append(GraphEdge(source=policy_id, target=criterion_id, type="REQUIRES"))
        for item in criterion.evidence:
            document_id = f"document:{item.document_id}"
            chunk_id = f"chunk:{item.chunk_id}"
            if not any(node.id == document_id for node in graph.nodes):
                graph.nodes.append(
                    GraphNode(id=document_id, type="ClinicalDocument", label=item.document_id)
                )
            if not any(node.id == chunk_id for node in graph.nodes):
                graph.nodes.append(
                    GraphNode(id=chunk_id, type="EvidenceChunk", label=item.chunk_id)
                )
            graph.edges.append(GraphEdge(source=document_id, target=chunk_id, type="CONTAINS"))
            graph.edges.append(GraphEdge(source=patient_id, target=document_id, type="BELONGS_TO"))
            relation = "SUPPORTS" if criterion.status == "SUPPORTED" else "DERIVED_FROM"
            if criterion.status == "NOT_SUPPORTED":
                relation = "CONTRADICTS"
            graph.edges.append(GraphEdge(source=chunk_id, target=criterion_id, type=relation))
            graph.edges.append(GraphEdge(source=document_id, target=criterion_id, type=relation))
        result_id = f"result:{criterion.criterion_id}:{criterion.status}"
        graph.nodes.append(
            GraphNode(id=result_id, type="ReviewResult", label=criterion.status)
        )
        graph.edges.append(GraphEdge(source=criterion_id, target=result_id, type="HAS_RESULT"))
    for contradiction in review.contradictions:
        left = f"contradiction:{contradiction.criterion}:a"
        right = f"contradiction:{contradiction.criterion}:b"
        graph.nodes.append(GraphNode(id=left, type="EvidenceChunk", label="evidence_a"))
        graph.nodes.append(GraphNode(id=right, type="EvidenceChunk", label="evidence_b"))
        graph.edges.append(GraphEdge(source=left, target=right, type="CONTRADICTS"))
    for missing in review.missing_evidence:
        missing_id = f"missing:{missing}"
        graph.nodes.append(GraphNode(id=missing_id, type="MissingEvidence", label=missing))
        graph.edges.append(GraphEdge(source=policy_id, target=missing_id, type="REQUIRES"))
    return graph
