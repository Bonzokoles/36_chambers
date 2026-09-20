# Data and Example Assets

## Not included and not licensed

The following are private operational assets. They are excluded from this repository and no rights are granted to access, infer, reconstruct, redistribute, or commercially exploit them:

- production SQLite databases, Chroma stores, HNSW directories, sist2 indexes;
- agent memory, graph knowledge, business/commerce records, invoices and customer data;
- API keys, credentials, secrets, `.env` files and tokens;
- production telemetry, prompts containing user data and raw trace logs;
- private canary markers, canary registry, export-recipient mapping and private audit queries;
- private manifests, backups and archive artifacts.

## Demo material

All examples under `examples/` must be synthetic and non-production. Their purpose is testing and documentation.

- `examples/sample_canary/` contains a public demonstration canary only.
- The public canary must never be reused as a production leak-detection marker.
- Example datasets must not contain personal data, secrets or business data.

## Third-party data

Contributors must document source, license, attribution and redistribution rights for any third-party material added to the repository.
