# Security Policy

## Security Model

The project enforces four-room ingestion/retirement controls, least-privilege service accounts, signed/hashed manifests, audit logs and versioned candidate indexes. See [docs/security/FOUR_ROOM_PIPELINE.md](docs/security/FOUR_ROOM_PIPELINE.md).

## Reporting a Vulnerability

Do not open a public issue for undisclosed vulnerabilities.

Report privately via GitHub Security Advisories or by contacting the project maintainers through: `https://github.com/Bonzokoles/36_chambers/security/advisories`

Include:
- affected version, release tag or commit SHA;
- clear reproduction steps;
- expected and observed behavior;
- security impact and affected assets;
- suggested remediation, if available.

Do not include credentials, personal data, production database extracts, private canaries or active exploit payloads in any report.

## Out of Scope

- Testing systems you do not own or lack written permission to test;
- attempts to discover or trigger private provenance canaries in third-party systems;
- social engineering;
- destructive testing against production resources.
