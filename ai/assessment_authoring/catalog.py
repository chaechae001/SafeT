"""실행 정책과 카탈로그 일관성 검사."""
from backend.domain.risk_policy import MATRIX, POLICY
from .contracts import require

def catalog_index(snapshot):
    require(snapshot.get("policy_version") == POLICY, "catalog policy mismatch")
    rows = snapshot["scenarios"]
    ids = [s["id"] for s in rows]
    require(len(ids) == len(set(ids)), "duplicate catalog scenario")
    for s in rows:
        require(s["policy_version"] == POLICY and type(s["severity"]) is int
                and s["severity"] in MATRIX, "invalid catalog policy/severity")
        controls = s["controls"]
        names = [c["id"] for c in controls]
        require(len(names) == len(set(names)) and any(c["critical"] for c in controls),
                "invalid catalog controls")
    return {s["id"]: s for s in rows}

