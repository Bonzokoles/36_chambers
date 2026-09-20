"""36 Chambers four-room quarantine controller (metadata + file operations).

Safety properties:
- Never writes into production databases or Chroma internals.
- Never promotes automatically; it creates a candidate/pending state only.
- Uses SHA-256, magic bytes MIME verification, extension allow/block lists,
  Defender invocation if available, text heuristic scan, manifests, and 36-hour transition gates.
- Use service accounts/ACLs externally; code cannot replace OS permissions.
"""
from __future__ import annotations
import argparse, hashlib, json, mimetypes, os, re, shutil, subprocess, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(r"Z:\36_chambers\.security")
POLICY = Path(__file__).with_name("four_room_policy.json")

# Fallback prompt resolver
_prompt_txt = Path(__file__).with_name("ingestion_security_prompt.txt")
_prompt_md = Path(__file__).with_name("ingestion_security_prompt.md")
PROMPT = _prompt_txt if _prompt_txt.exists() else _prompt_md

INJECTION = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"system\s*:",
    r"developer\s*:",
    r"reveal\s+(the\s+)?(secret|password|token)",
    r"execute\s+(this|the)?\s*(command|script)",
    r"bypass\s+(security|policy|guardrail)",
    r"you\s+are\s+now"
]
ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u2060\ufeff]")

ROOMS = [
    "00_Invitation_Quarantine",
    "01_Rookie_Validation",
    "98_Retirement_Quarantine",
    "99_Deletion_Hold"
]

ROOM_ALIASES = {
    "00_Invitation_Quarantine": "The Invitation Room",
    "01_Rookie_Validation": "The Rookie Room",
    "98_Retirement_Quarantine": "You-No-Longer-Need-Me Room",
    "99_Deletion_Hold": "The Bye-Bye Room"
}

def detect_magic(p: Path) -> str | None:
    try:
        import magic
        return magic.from_file(str(p), mime=True)
    except Exception:
        return None

def iso(): 
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def read_policy(): 
    return json.loads(POLICY.read_text(encoding="utf-8"))

def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""): 
            h.update(b)
    return h.hexdigest()

def paths(room: str) -> Path:
    base = ROOT / room
    for x in [base, base / "items", base / "manifests", base / "reviews", base / "rejected"]: 
        x.mkdir(parents=True, exist_ok=True)
    return base

def manifest_path(room: str, item: str) -> Path: 
    return ROOT / room / "manifests" / f"{item}.json"

def save_manifest(room: str, m: dict): 
    manifest_path(room, m["item_id"]).write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")

def load_manifest(room: str, item: str) -> dict: 
    return json.loads(manifest_path(room, item).read_text(encoding="utf-8"))

def technical_scan(p: Path, policy: dict) -> dict:
    ext = p.suffix.lower()
    findings = []
    size = p.stat().st_size
    mime_guess = mimetypes.guess_type(p.name)[0]
    magic_mime = detect_magic(p)

    if ext in policy.get("blocked_extensions", []): 
        findings.append(f"blocked_extension:{ext}")
    if ext not in policy.get("allowed_extensions", []): 
        findings.append(f"extension_not_allowlisted:{ext}")
    if size > policy.get("max_file_size_mb", 250) * 1024 * 1024: 
        findings.append("file_exceeds_size_limit")
    
    # Check for polyglot executable disguise (e.g. .txt/.md masquerading PE/ELF)
    if magic_mime and any(x in magic_mime for x in ["x-dosexec", "x-executable", "x-sharedlib", "x-msdownload"]):
        findings.append(f"disguised_executable_mime:{magic_mime}")

    return {
        "extension": ext,
        "mime_guess": mime_guess,
        "mime_magic": magic_mime,
        "size_bytes": size,
        "findings": findings,
        "passed": not findings
    }

def text_scan(p: Path) -> dict:
    try: 
        text = p.read_text(encoding="utf-8", errors="ignore")[:2_000_000]
    except Exception: 
        return {"readable_text": False, "findings": []}
    findings = []
    if ZERO_WIDTH.search(text): 
        findings.append("unicode_zero_width_or_control")
    for pat in INJECTION:
        if re.search(pat, text, re.I): 
            findings.append(f"prompt_injection_pattern:{pat}")
    if "-----BEGIN " in text and "PRIVATE KEY-----" in text: 
        findings.append("possible_private_key")
    return {"readable_text": True, "findings": findings, "preview_chars": len(text)}

def defender_scan(path: Path) -> dict:
    # Best effort only. Defender/permissions may be unavailable; treat absence as review signal.
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"Start-MpScan -ScanType CustomScan -ScanPath '{path}'"],
            capture_output=True, text=True, timeout=600
        )
        return {"attempted": True, "returncode": r.returncode, "passed": r.returncode == 0, "stderr": r.stderr[-500:]}
    except Exception as e: 
        return {"attempted": False, "passed": False, "error": str(e)}

def submit(src: str, target_chamber: int, submitted_by: str):
    policy = read_policy()
    src_path = Path(src).resolve()
    if not src_path.exists():
        raise FileNotFoundError(f"Source file does not exist: {src_path}")
    
    paths("00_Invitation_Quarantine")
    item = str(uuid.uuid4())
    dest = ROOT / "00_Invitation_Quarantine" / "items" / f"{item}{src_path.suffix.lower()}"
    shutil.copy2(src_path, dest)
    
    tech = technical_scan(dest, policy)
    text = text_scan(dest)
    av = defender_scan(dest)
    
    risk = "low" if tech["passed"] and not text["findings"] and av.get("passed") else "medium"
    if any("blocked_extension" in f or "disguised_executable" in f for f in tech["findings"]) or "possible_private_key" in text["findings"]: 
        risk = "critical"
    
    earliest_transition = (datetime.now(timezone.utc) + timedelta(hours=policy.get("minimum_hold_hours", 36))).isoformat(timespec="seconds")
    
    m = {
        "item_id": item,
        "state": "INVITATION_PENDING",
        "submitted_at": iso(),
        "earliest_next_transition": earliest_transition,
        "submitted_by": submitted_by,
        "target_chamber": target_chamber,
        "original_path": str(src_path),
        "quarantine_path": str(dest),
        "sha256": sha256(dest),
        "technical_scan": tech,
        "heuristic_content_scan": text,
        "defender_scan": av,
        "risk_level": risk,
        "model_prompt_path": str(PROMPT),
        "model_review": "PENDING",
        "provenance": {"source_uri": str(src_path), "owner": None, "license": None, "complete": False},
        "history": [{"at": iso(), "action": "submitted_to_invitation"}]
    }
    save_manifest("00_Invitation_Quarantine", m)
    result = {
        "item_id": item,
        "room": "00_Invitation_Quarantine",
        "room_alias": ROOM_ALIASES["00_Invitation_Quarantine"],
        "state": m["state"],
        "risk_level": risk,
        "sha256": m["sha256"],
        "earliest_next_transition": earliest_transition,
        "manifest": str(manifest_path("00_Invitation_Quarantine", item))
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result

def move(room_from: str, room_to: str, item: str, model_review_path: str | None = None, bypass_hold: bool = False):
    policy = read_policy()
    m = load_manifest(room_from, item)
    now = datetime.now(timezone.utc)
    earliest = datetime.fromisoformat(m["earliest_next_transition"])
    if now < earliest and not bypass_hold: 
        remaining = earliest - now
        raise SystemExit(f"Hold time not completed. Remaining: {remaining}")
    
    src = Path(m["quarantine_path"])
    if not src.exists():
        raise SystemExit(f"Quarantine item missing: {src}")
    
    current_hash = sha256(src)
    if current_hash != m["sha256"]: 
        raise SystemExit(f"SHA-256 mismatch! Expected {m['sha256']}, got {current_hash}")
    
    if model_review_path:
        review_file = Path(model_review_path)
        if not review_file.exists():
            raise SystemExit(f"Model review file not found: {review_file}")
        review = json.loads(review_file.read_text(encoding="utf-8"))
        m["model_review"] = review
        if review.get("risk_level") in {"high", "critical"} or review.get("recommended_action") == "reject": 
            raise SystemExit(f"Model review rejected transition: risk={review.get('risk_level')}")
    
    paths(room_to)
    dest = ROOT / room_to / "items" / src.name
    shutil.move(str(src), str(dest))
    
    m["quarantine_path"] = str(dest)
    m["state"] = "ROOKIE_PENDING" if room_to.startswith("01_") else ("RETIREMENT_PENDING" if room_to.startswith("98_") else "DELETION_HOLD")
    m["earliest_next_transition"] = (now + timedelta(hours=policy.get("minimum_hold_hours", 36))).isoformat(timespec="seconds")
    m["history"].append({"at": iso(), "action": f"moved_{room_from}_to_{room_to}", "bypass_hold": bypass_hold})
    
    save_manifest(room_to, m)
    # Remove old manifest to avoid orphaned duplicate records
    try:
        manifest_path(room_from, item).unlink(missing_ok=True)
    except Exception:
        pass
    print(f"Moved {item} -> {room_to} ({ROOM_ALIASES.get(room_to, room_to)})")

def status(target_room: str | None = None):
    rooms_to_check = [target_room] if target_room else ROOMS
    report = {"timestamp": iso(), "rooms": {}}
    for room in rooms_to_check:
        base = ROOT / room
        manifest_dir = base / "manifests"
        items_count = 0
        items_list = []
        if manifest_dir.exists():
            for mf in manifest_dir.glob("*.json"):
                try:
                    data = json.loads(mf.read_text(encoding="utf-8"))
                    now = datetime.now(timezone.utc)
                    earliest = datetime.fromisoformat(data["earliest_next_transition"])
                    hold_done = now >= earliest
                    items_list.append({
                        "item_id": data["item_id"],
                        "target_chamber": data.get("target_chamber"),
                        "risk_level": data.get("risk_level"),
                        "state": data.get("state"),
                        "submitted_at": data.get("submitted_at"),
                        "earliest_transition": data.get("earliest_next_transition"),
                        "hold_completed": hold_done,
                        "original_path": data.get("original_path")
                    })
                    items_count += 1
                except Exception:
                    pass
        report["rooms"][room] = {
            "alias": ROOM_ALIASES.get(room, room),
            "item_count": items_count,
            "items": items_list
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report

def generate_review(room: str, item: str, out_path: str | None = None):
    m = load_manifest(room, item)
    src = Path(m["quarantine_path"])
    try:
        content = src.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        content = f"<UNABLE_TO_READ_TEXT: {e}>"
    
    prompt_template = PROMPT.read_text(encoding="utf-8")
    filled_prompt = prompt_template.replace("{{DOCUMENT_TEXT}}", content)
    
    dest_path = Path(out_path) if out_path else (ROOT / room / "reviews" / f"review_prompt_{item}.txt")
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_text(filled_prompt, encoding="utf-8")
    print(f"Generated review prompt for {item}: {dest_path}")
    return dest_path

def main():
    ap = argparse.ArgumentParser(description="36 Chambers Four-Room Security Quarantine Controller")
    sub = ap.add_subparsers(dest="cmd", required=True)
    
    # submit
    s = sub.add_parser("submit", help="Submit untrusted file into 00_Invitation_Quarantine")
    s.add_argument("file", help="Path to file to quarantine")
    s.add_argument("--target-chamber", type=int, required=True, help="Target destination chamber ID (1-36)")
    s.add_argument("--submitted-by", default="manual_user", help="Submitter identifier")
    
    # move
    m = sub.add_parser("move", help="Transition an item between quarantine rooms")
    m.add_argument("--from-room", required=True, choices=ROOMS, help="Source room")
    m.add_argument("--to-room", required=True, choices=ROOMS, help="Destination room")
    m.add_argument("--item", required=True, help="UUID item id")
    m.add_argument("--model-review", help="Path to model review JSON evaluation")
    m.add_argument("--bypass-hold", action="store_true", help="Bypass the 36h hold (requires admin intent)")
    
    # status
    st = sub.add_parser("status", help="Inspect inventory and holds across all 4 rooms")
    st.add_argument("--room", choices=ROOMS, help="Specific room to inspect")
    
    # review
    rev = sub.add_parser("generate-review", help="Generate ready-to-evaluate prompt for an item")
    rev.add_argument("--room", required=True, choices=ROOMS, help="Room containing the item")
    rev.add_argument("--item", required=True, help="UUID item id")
    rev.add_argument("--out", help="Output path for filled prompt")
    
    a = ap.parse_args()
    if a.cmd == "submit":
        submit(a.file, a.target_chamber, a.submitted_by)
    elif a.cmd == "move":
        move(a.from_room, a.to_room, a.item, a.model_review, a.bypass_hold)
    elif a.cmd == "status":
        status(a.room)
    elif a.cmd == "generate-review":
        generate_review(a.room, a.item, a.out)

if __name__ == "__main__":
    main()
