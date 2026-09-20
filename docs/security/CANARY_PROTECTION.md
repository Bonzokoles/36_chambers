# Canary and Export Protection

## Layers

1. Private global canary: detects broad corpus/export leakage.
2. Private per-chamber canaries: identify probable source domain.
3. Private per-recipient/export canaries: identify distribution channel.
4. Public demo canary: documentation/testing only; has no production detection value.

## Rules

- Private canaries remain outside the public repository.
- Do not place fake facts in production memory, commerce tables or Graph of Truth.
- Store private marker-to-recipient mapping in a restricted registry.
- Use hashes, manifests, release tags and access logs alongside canaries.
- Treat a marker finding as evidence requiring review, not automatic legal conclusion.

## Public repository

Only include `PUBLIC-DEMO-CANARY-NOT-FOR-PRODUCTION-001` or equivalent synthetic examples.
