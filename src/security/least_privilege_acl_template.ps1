# Run as Administrator. Adapt identities to actual local/service accounts.
# Goal: agents retrieve only from production data; quarantine workers write only in security rooms.

$SecurityRoot = "Z:\36_chambers\.security"
$ProductionRoots = @(
  "R:\repos\active\devz-kb",
  "R:\mempalace",
  "U:\_sist2\data",
  "Z:\36_chambers\The_Buch"
)

# Replace these placeholders with real local/domain users or service accounts.
$IngestWorker = ".\svc_shaolin_ingest"
$RetrievalWorker = ".\svc_shaolin_retrieval"
$Publisher = ".\svc_shaolin_publisher"
$ArchiveWorker = ".\svc_shaolin_archive"
$Administrators = "BUILTIN\Administrators"

# Security root: stop inherited permissive ACLs, retain administrator/system control.
icacls $SecurityRoot /inheritance:r
icacls $SecurityRoot /grant:r "$Administrators:(OI)(CI)F" "SYSTEM:(OI)(CI)F"

# Ingestion may write only to inbound rooms; it cannot write production databases.
icacls "$SecurityRoot\00_Invitation_Quarantine" /grant "$IngestWorker:(OI)(CI)M"
icacls "$SecurityRoot\01_Rookie_Validation" /grant "$IngestWorker:(OI)(CI)RX"

# Publisher may read validation and write only candidate/publish staging, not arbitrary production roots.
icacls "$SecurityRoot\01_Rookie_Validation" /grant "$Publisher:(OI)(CI)M"
icacls "$SecurityRoot\98_Retirement_Quarantine" /grant "$ArchiveWorker:(OI)(CI)M"
icacls "$SecurityRoot\99_Deletion_Hold" /grant "$ArchiveWorker:(OI)(CI)M"

# Retrieval identity gets read/execute only. Never grant Modify or Full Control to RAG agents.
foreach ($root in $ProductionRoots) {
  icacls $root /grant "$RetrievalWorker:(OI)(CI)RX"
}

# Verify effective ACLs manually after execution.
icacls $SecurityRoot
