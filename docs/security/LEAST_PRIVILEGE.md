# Least Privilege

## Roles

| Identity | Allowed | Denied |
|---|---|---|
| `svc_shaolin_retrieval` | Read-only production retrieval | Writes, deletes, ACL changes, quarantine writes |
| `svc_shaolin_ingest` | Modify Invitation Room only | Production DB access, publishing |
| `svc_shaolin_publisher` | Candidate index write and approved version switch | Arbitrary delete, unrestricted production writes |
| `svc_shaolin_archive` | Retirement, deletion-hold and archive paths | Active-data changes |
| `human_security_admin` | ACL, break-glass and final approvals | Routine service execution |

## Enforcement

- Separate OS identities and API keys.
- Use NTFS ACLs: deny by default, explicit grants only.
- Use `sqlite3` URI `mode=ro` for retrieval.
- Use read-only database credentials where supported.
- Keep secrets in a secret store/environment, never in code or logs.
- Test expected denial cases monthly.

See `src/security/least_privilege_acl_template.ps1` for a review-first Windows template.
