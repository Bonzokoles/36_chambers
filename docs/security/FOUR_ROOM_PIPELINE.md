# Four-Room Security Pipeline

## Names and purpose

| Technical ID | Alias | Minimum hold | Purpose |
|---|---|---:|---|
| `00_Invitation_Quarantine` | The Invitation Room | 36 h | Intake of untrusted files and batches |
| `01_Rookie_Validation` | The Rookie Room | 36 h | Independent validation, model review and candidate preparation |
| `98_Retirement_Quarantine` | You-No-Longer-Need-Me Room | 36 h | Dependency, use and backup review before retirement |
| `99_Deletion_Hold` | The Bye-Bye Room | 36 h | Restore test and final human approval before archive/delete |

## Ingress

```text
source -> Invitation -> Rookie -> candidate index -> golden queries -> approved promotion
```

Mandatory checks: source manifest, SHA-256, extension/MIME policy, malware scan, content normalization, prompt-injection scan, model JSON review, provenance and owner fields.

## Egress

```text
active asset -> Retirement -> Deletion Hold -> archive or approved deletion
```

Mandatory checks: dependency report, retrieval use, retention class, immutable backup, restore test and final approval.

## Non-negotiable rules

- No automatic production publication.
- No automatic deletion.
- No direct editing of Chroma internals.
- Every transition writes an append-only audit event.
- Hold time is a minimum, not automatic approval.
