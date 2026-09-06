import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

MARKER = "investment-analyzer-v2"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository:
    """Checkpoints use existing memo RLS; no cloud migration is required.

    Original documents are base64 within the versioned JSON envelope. This favors
    transactional privacy/compatibility over object-storage efficiency for now.
    """
    def __init__(self, client=None, owner=None, root="investment_memos/runs"):
        if client is not None and not owner:
            raise ValueError("Cloud storage requires an authenticated owner.")
        self.client, self.owner = client, owner
        self.root = Path(root)
        self.lock = threading.RLock()

    def create(self, inputs: dict, documents: list[dict]) -> dict:
        state = {"format": MARKER, "id": str(uuid4()), "company_name": inputs["company_name"],
                 "created_at": now(), "updated_at": now(), "status": "queued", "phase": "Queued",
                 "inputs": inputs, "documents": documents, "steps": {}, "usage": [], "errors": [],
                 "model": inputs["model"], "prompt_version": "2026-09-invest-pass-v1"}
        if self.client:
            self.client.table("memos").insert({"id": state["id"], "owner_id": self.owner,
                "company_name": state["company_name"], "memo_content": json.dumps(state),
                "description": inputs.get("description", ""), "terms": inputs.get("terms", "")}).execute()
        else:
            self.save(state)
        return state

    def save(self, state: dict):
        with self.lock:
            state["updated_at"] = now()
            payload = json.dumps(state, ensure_ascii=False, allow_nan=False)
            if self.client:
                self.client.table("memos").update({"memo_content": payload}).eq("id", state["id"]).eq("owner_id", self.owner).execute()
            else:
                self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
                target = self.root / f"{state['id']}.json"
                temp = target.with_suffix(".tmp")
                with open(temp, "w", encoding="utf-8") as file:
                    os.chmod(temp, 0o600)
                    file.write(payload)
                temp.replace(target)

    def load(self, identifier: str) -> dict | None:
        if self.client:
            rows = self.client.table("memos").select("memo_content").eq("id", identifier).eq("owner_id", self.owner).limit(1).execute().data
            return self.decode(rows[0]["memo_content"]) if rows else None
        # Identifiers are UUIDs, never paths supplied by the UI.
        from uuid import UUID
        UUID(identifier)
        target = self.root / f"{identifier}.json"
        with self.lock:
            return json.loads(target.read_text()) if target.exists() else None

    @staticmethod
    def decode(content):
        try:
            value = json.loads(content)
            return value if isinstance(value, dict) and value.get("format") == MARKER else None
        except (ValueError, TypeError):
            return None

    def list(self) -> list[dict]:
        if self.client:
            # Only metadata; documents are loaded for the selected record.
            rows = self.client.table("memos").select("id,company_name,created_at").eq("owner_id", self.owner).order("created_at", desc=True).limit(200).execute().data
            return rows
        if not self.root.exists():
            return []
        result = []
        for path in self.root.glob("*.json"):
            try:
                state = json.loads(path.read_text())
                result.append({key: state[key] for key in ("id", "company_name", "created_at", "status")})
            except (ValueError, KeyError):
                continue
        return sorted(result, key=lambda item: item["created_at"], reverse=True)
