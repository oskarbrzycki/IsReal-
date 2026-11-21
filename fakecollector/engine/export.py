"""Optional export of the campaign graph to CSV + a Cypher import script for Neo4j."""
from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

from fakecollector.core.models import Cluster, Edge

CYPHER = """\
// Neo4j import. Copy nodes.csv and edges.csv to the Neo4j `import/` folder first.
CREATE CONSTRAINT incident_id IF NOT EXISTS FOR (i:Incident) REQUIRE i.incident_id IS UNIQUE;
LOAD CSV WITH HEADERS FROM 'file:///nodes.csv' AS row
MERGE (i:Incident {incident_id: row.incident_id})
SET i.campaign_id = row.campaign_id, i.campaign_label = row.campaign_label;
LOAD CSV WITH HEADERS FROM 'file:///edges.csv' AS row
MATCH (a:Incident {incident_id: row.a}), (b:Incident {incident_id: row.b})
MERGE (a)-[r:SIMILAR_TO]-(b)
SET r.score = toFloat(row.score), r.reasons = row.reasons;
"""


def export_neo4j(edges: list[Edge], clusters: list[Cluster], out_dir: Path) -> Path:
    """Write nodes.csv, edges.csv and import.cypher into `out_dir` (usually data/graph/neo4j)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "nodes.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["incident_id", "campaign_id", "campaign_label"])
        for c in clusters:
            for m in c.members:
                w.writerow([m, c.campaign_id, c.label])
    with open(out_dir / "edges.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["a", "b", "score", "reasons"])
        for e in edges:
            w.writerow([e.a, e.b, e.score, json.dumps([asdict(r) for r in e.reasons], ensure_ascii=False)])
    (out_dir / "import.cypher").write_text(CYPHER, encoding="utf-8")
    return out_dir
