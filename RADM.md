# RADM — Repository Architecture and Decision Manual

> **Project:** 36 Chambers Cognitive Matrix  
> **Status:** Living architecture baseline  
> **Audience:** maintainers, contributors, security reviewers, AI architects and deployment operators  
> **Version:** 0.1.0  
> **Last reviewed:** 2026-09-20

## 1. Purpose

This document is the authoritative map of repository boundaries, architecture decisions, security assumptions, data-flow rules and operational ownership.

It answers:

- What belongs in the public repository and what must remain private?
- Which components may read, write, publish, archive or delete data?
- How does knowledge move through the 36 Chambers?
- How are AI quality, latency, cost, provenance and security measured?
- Which architectural decisions are fixed, provisional or under review?

## 2. System scope

The system is a federated AI platform. Data remains in its native engine and location; agents discover and query resources via a registry rather than copying everything into one shared store.

```text
User / CLI / API
  -> Chamber 36 Orchestrator
  -> Router and policy gate
  -> Retrieval adapters (FTS, vector, graph, SQL)
  -> Evidence verification
  -> Answer with provenance + telemetry
```

Separate operational tracks:

```text
Knowledge ingress: Invitation -> Rookie -> candidate index -> approved publish
Knowledge egress: Retirement -> Deletion Hold -> archive or approved deletion
Observability: traces -> import -> knowledge observatory -> dashboard
```

## 3. Repository boundaries

### Public

- source code;
- policy templates and prompts without secrets;
- synthetic examples;
- schemas and test fixtures;
- documentation;
- public demo canaries with no production audit value.

### Private

- production data and all production indexes;
- real API credentials and environment files;
- private canary registry and export-recipient mapping;
- production logs/traces and user data;
- real infrastructure paths, internal hostnames and sensitive deployment manifests.

## 4. Component ownership and permissions

| Component | Responsibility | Required rights | Forbidden rights |
|---|---|---|---|
| Retrieval agent | Query active resources and return evidence | Read-only | Database writes, deletes, ACL changes |
| Ingestion worker | Receive untrusted files into Invitation Room | Write only to quarantine | Production reads/writes, promotion |
| Review model | Classify risk through strict JSON | Read supplied content only | Tools, network, writes, approvals |
| Publisher | Build candidate index and switch approved version | Candidate write, controlled promote | Arbitrary production delete |
| Archive worker | Stage retirement and archives | Retirement/hold/archive write | Active-data mutation |
| Security admin | Approval, ACL, incident action | Controlled administration | Daily agent runtime |
| Observatory | Aggregate metrics and lineage | Read logs/metadata; write analytics DB | Production data mutation |

## 5. Core decisions

### ADR-001 — Federated data, registry-first access

**Decision:** Resources retain their native storage and location. The registry maps logical chamber/resource IDs to adapters and paths.

**Why:** Avoids destructive migrations and hard-coded paths; improves lineage and controlled routing.

**Consequence:** Registry freshness and path health checks are required.

### ADR-002 — Read-only retrieval default

**Decision:** Retrieval identities use read-only file/database access and SQLite `mode=ro` when possible.

**Why:** Reduces blast radius of prompt injection, bugs and stolen agent credentials.

**Consequence:** Writes must be handled by separate identities and explicit workflows.

### ADR-003 — Four-room lifecycle gates

**Decision:** Untrusted ingress and retirement/egress each use two 36-hour hold rooms.

**Why:** Adds time, scanning, provenance and approval gates before irreversible or broad-impact changes.

**Consequence:** Urgent exceptions need a documented break-glass process.

### ADR-004 — Candidate index before production promotion

**Decision:** New knowledge is indexed in a versioned candidate area and evaluated before atomic routing switch.

**Why:** Enables rollback and reduces RAG poisoning/index corruption risk.

**Consequence:** Requires storage headroom and a promotion process.

### ADR-005 — Evidence-first answer synthesis

**Decision:** Final answers distinguish evidence, inference and uncertainty; every retrieval result preserves chamber, resource and record provenance.

**Why:** Enables auditability and quality evaluation.

**Consequence:** Adapters must normalize their output into a common evidence schema.

### ADR-006 — Canary records are audit-only

**Decision:** Private canaries are isolated from default user retrieval and production facts.

**Why:** Prevents false knowledge and preserves leak-detection value.

**Consequence:** Public demo canaries must differ from private markers.

## 6. Data lifecycle states

```text
UNTRUSTED
  -> INVITATION_PENDING
  -> ROOKIE_PENDING
  -> CANDIDATE_INDEXED
  -> ACTIVE
  -> RETIREMENT_PENDING
  -> DELETION_HOLD
  -> ARCHIVED | VERIFIED_DELETED | REJECTED
```

No model may independently move an asset between states. State transitions require deterministic checks and, for promotion/archive/delete, human approval as specified by policy.

## 7. Security controls

- SHA-256 manifests at intake, transition and release;
- source/provenance fields: owner, origin, timestamp, license, target chamber;
- strict separation of trusted system policy from untrusted document text;
- model output constrained by JSON schema;
- no LLM output is executed as shell, SQL, ACL or path instruction without deterministic validation;
- parameterized, allowlisted, read-only SQL for retrieval;
- NTFS ACL/service-account separation;
- signed tags/releases and secret scanning before publication;
- immutable/offline backup and restore test before final deletion;
- event logs and observability database for reviews and incidents.

## 8. Evaluation and SLOs

### Quality

- route correctness;
- Recall@k, Precision@k, nDCG@k;
- groundedness, completeness and citation coverage;
- safety pass rate.

### Operations

- p50/p95 end-to-end latency;
- retrieval timeout/error rate;
- empty-retrieval rate;
- cost per grounded answer;
- index freshness and embedding lag.

### Security

- quarantine policy pass rate;
- private-marker exposure rate: target `0`;
- secret-scanning findings: target `0` before release;
- successful restore-test rate: target `100%` for retirement candidates.

## 9. Change process

1. Create an issue/ADR for changes affecting data flow, model access, permissions, retention, routing or licenses.
2. Update policy, schema and tests before implementation where practical.
3. Run unit tests, golden-query regression, prompt-injection fixtures and secret scan.
4. Build candidate index or release artifact.
5. Record metrics: quality, latency, cost and security outcome.
6. Obtain review/approval appropriate to blast radius.
7. Publish atomically with rollback reference.
8. Update this RADM and the changelog.

## 10. Risk register

| Risk | Control | Owner | Trigger |
|---|---|---|---|
| Prompt injection through RAG | Quarantine, delimiters, no tool access, review model | Security owner | suspicious document/retrieval output |
| Data poisoning | Provenance, candidate index, golden queries, rollback | Data owner | quality regression/conflict |
| Accidental overwrite | Read-only roles, candidate builds, backups | Publisher owner | failed integrity check |
| Credential leak | `.gitignore`, gitleaks, separate keys, rotation | Security owner | secret scanner alert |
| Unauthorized data copy | Private canaries, manifests, audit logs | Security owner | marker detection |
| Wrong deletion | 72 h egress hold, dependencies, backup/restore, approval | Archive owner | archive request |

## 11. Review cadence

- Weekly: registry health, snapshot and storage changes.
- Monthly: cold assets, ACL membership, secret rotation status, canary registry review.
- Before release: license, README, NOTICE, SBOM, tests, scans and release manifest.
- Quarterly: threat model, risk register, backup restore exercise and architecture review.
