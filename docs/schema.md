# Data schema

> **Full design:** [DATA_MODEL.md](DATA_MODEL.md)

SQLAlchemy models power the evidence store (`app/models/entities.py`). The same models run on SQLite for local development and PostgreSQL for Docker, pilot, and Kubernetes.

Embeddings are stored as JSON hybrid payloads (`sparse`, `dense`, `model`) on document chunks. Optional cloud embedding models may be selected through `EMBEDDING_MODEL`.

Primary entities:

- Organizations (facility tenants)
- Patients, clinical notes, labs, medications, procedures, imaging metadata, claims
- Documents and chunks
- Insurance policies and criteria
- Authorization cases and review runs (HITL state)
- Audit events

See also: [HLD.md](HLD.md), [LLD.md](LLD.md), [INDEX.md](INDEX.md).
