import json
import base64
import hashlib
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

MARKER = "investment-analyzer-v2"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def document_fingerprint(documents):
    hashes = sorted({hashlib.sha256(base64.b64decode(doc["data"])).hexdigest() for doc in documents})
    return hashlib.sha256("|".join(hashes).encode()).hexdigest() if hashes else None


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
                 "model": inputs["model"], "prompt_version": "2026-09-invest-pass-v1",
                 "investment_action": "undecided"}
        state["document_fingerprint"] = document_fingerprint(documents)
        if self.client:
            self.client.table("memos").insert({"id": state["id"], "owner_id": self.owner,
                "company_name": state["company_name"], "memo_content": json.dumps(state),
                "description": inputs.get("description", ""), "terms": inputs.get("terms", "")}).execute()
        else:
            self.save(state)
        return state

    @staticmethod
    def _is_transient_cloud_error(error: Exception) -> bool:
        return type(error).__name__ in {"RemoteProtocolError", "ConnectError", "ReadError", "ReadTimeout", "WriteError"}

    def _cloud_execute(self, operation):
        """Retry safe cloud reads and updates when an HTTP connection is interrupted."""
        for attempt in range(3):
            try:
                return operation()
            except Exception as error:
                if not self._is_transient_cloud_error(error) or attempt == 2:
                    raise
                time.sleep(0.5 * (attempt + 1))

    def find_duplicate(self, documents):
        fingerprint = document_fingerprint(documents)
        if not fingerprint:
            return None
        if self.client:
            offset = 0
            while True:
                rows = self.client.table("memos").select("memo_content").eq("owner_id", self.owner).order("created_at", desc=True).range(offset, offset + 49).execute().data
                for row in rows:
                    state = self.decode(row["memo_content"])
                    if state and (state.get("document_fingerprint") or document_fingerprint(state.get("documents", []))) == fingerprint:
                        return state
                if len(rows) < 50:
                    return None
                offset += 50
        for record in self.list():
            state = self.load(record["id"])
            if state and (state.get("document_fingerprint") or document_fingerprint(state.get("documents", []))) == fingerprint:
                return state
        return None

    def save(self, state: dict):
        with self.lock:
            state["updated_at"] = now()
            payload = json.dumps(state, ensure_ascii=False, allow_nan=False)
            if self.client:
                self._cloud_execute(lambda: self.client.table("memos").update({
                    "company_name": state["company_name"], "memo_content": payload
                }).eq("id", state["id"]).eq("owner_id", self.owner).execute())
            else:
                self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
                target = self.root / f"{state['id']}.json"
                temp = target.with_suffix(".tmp")
                with open(temp, "w", encoding="utf-8") as file:
                    os.chmod(temp, 0o600)
                    file.write(payload)
                temp.replace(target)

    def rename(self, identifier: str, company_name: str, legacy: bool = False) -> str:
        """Rename an analysis within the current owner's storage scope."""
        company_name = " ".join(company_name.split()).strip()
        if not company_name:
            raise ValueError("Company name is required.")
        if len(company_name) > 120:
            raise ValueError("Company name must be 120 characters or fewer.")
        if not legacy:
            state = self.load(identifier)
            if state is None:
                raise ValueError("Analysis was not found.")
            state["company_name"] = company_name
            state.setdefault("inputs", {})["company_name"] = company_name
            self.save(state)
            return identifier
        if self.client:
            self.client.table("memos").update({"company_name": company_name}).eq(
                "id", identifier
            ).eq("owner_id", self.owner).execute()
            return identifier
        path = Path(identifier)
        if path.is_symlink() or path.resolve().parent != self.root.resolve().parent or path.suffix != ".md":
            raise ValueError("Not a local history memo.")
        suffix = ""
        match = re.search(r"(_\d{8}_\d{6})$", path.stem)
        if match:
            suffix = match.group(1)
        slug = "_".join(part for part in re.sub(r"[^\w\s-]", "", company_name).split())
        target = path.with_name(f"{slug or 'Untitled_company'}{suffix}.md")
        if target != path and target.exists():
            raise ValueError("An analysis with this name already exists.")
        path.rename(target)
        return str(target)

    def set_investment_action(self, identifier: str, action: str) -> None:
        if action not in {"undecided", "buy", "pass"}:
            raise ValueError("Unknown investment action.")
        state = self.load(identifier)
        if state is None:
            raise ValueError("Analysis was not found.")
        state["investment_action"] = action
        self.save(state)

    def load(self, identifier: str) -> dict | None:
        if self.client:
            rows = self._cloud_execute(lambda: self.client.table("memos").select("memo_content").eq(
                "id", identifier
            ).eq("owner_id", self.owner).limit(1).execute()).data
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

    def delete(self, identifier: str) -> None:
        """Delete one analysis and its embedded documents within the owner's scope."""
        from uuid import UUID
        UUID(identifier)
        if self.client:
            self.client.table("memos").delete().eq("id", identifier).eq("owner_id", self.owner).execute()
        else:
            with self.lock:
                (self.root / f"{identifier}.json").unlink(missing_ok=True)

    def delete_legacy(self, filename: str) -> None:
        """Only local Markdown memos directly inside the history directory."""
        if self.client:
            raise ValueError("Local files cannot be deleted through cloud storage.")
        path = Path(filename)
        if path.is_symlink() or path.resolve().parent != self.root.resolve().parent or path.suffix != ".md":
            raise ValueError("Not a local history memo.")
        path.unlink(missing_ok=True)

    def list(self) -> list[dict]:
        if self.client:
            rows = self._cloud_execute(lambda: self.client.table("memos").select(
                "id,company_name,created_at,memo_content"
            ).eq("owner_id", self.owner).order("created_at", desc=True).limit(200).execute()).data
            return [{"id": row["id"], "company_name": row["company_name"], "created_at": row["created_at"],
                     "investment_action": (self.decode(row.get("memo_content")) or {}).get("investment_action", "undecided")}
                    for row in rows]
        if not self.root.exists():
            return []
        result = []
        for path in self.root.glob("*.json"):
            try:
                state = json.loads(path.read_text())
                result.append({key: state[key] for key in ("id", "company_name", "created_at", "status")}
                              | {"investment_action": state.get("investment_action", "undecided")})
            except (ValueError, KeyError):
                continue
        return sorted(result, key=lambda item: item["created_at"], reverse=True)
