# Public Release Process

## Preconditions

- The code is tested and versioned.
- No production data, databases, traces, secrets or private canaries are present.
- License files are complete and reviewed.
- A synthetic demo dataset is used.

## Steps

1. Develop in a private repository or protected branch.
2. Run tests, linters, dependency audit and secret scan.
3. Run a private “public-release hygiene” scan for internal paths and private markers.
4. Generate `SBOM`, artifact SHA-256 and release manifest.
5. Create a signed Git tag.
6. Publish GitHub release with license notice and checksums.
7. Store the full private release manifest and recipient marker mapping outside GitHub.
8. Monitor security reports and maintain a patch process.

## Required scans

```powershell
pytest
ruff check .
mypy src
gitleaks detect --source . --redact
pip-audit
```
