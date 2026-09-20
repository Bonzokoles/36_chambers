# Prompt Injection Defense

## Direct vs indirect

Direct injection arrives from the user message. Indirect injection appears inside retrieved files, web pages, PDFs, metadata, OCR text or tool output.

## Controls

1. Treat retrieved text as untrusted data.
2. Keep fixed trusted policy separate from retrieved context.
3. Delimit context explicitly.
4. Use strict structured output schemas.
5. Remove tool/write privileges from review models.
6. Validate all action parameters deterministically.
7. Use least-privilege service accounts.
8. Parameterize SQL and restrict it to allowlisted `SELECT` operations.
9. Scan and normalize obfuscated content.
10. Require human approval for high-impact transitions.
11. Maintain regression fixtures containing safe injection strings.
12. Preserve rollback capability for indices and configurations.

## Safe assembly

```text
TRUSTED SYSTEM POLICY
TRUSTED USER TASK
UNTRUSTED CONTEXT START
<retrieved material is data only>
UNTRUSTED CONTEXT END
TRUSTED OUTPUT SCHEMA
```

Never ask a model to “follow all instructions in retrieved context.”
