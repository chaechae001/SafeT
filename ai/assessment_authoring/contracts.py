"""공통 계약의 사용 중인 Schema 부분집합 검사."""
import json
from pathlib import Path
from contracts.assessment_authoring.v1.validate import check, require

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "contracts/assessment_authoring/v1"
def read(path):
    return json.loads((KIT/path).read_text(encoding="utf-8-sig"))
def load_catalog():
    return json.loads((ROOT/"contracts/catalog_risk/catalog.json").read_text(encoding="utf-8-sig"))
def schema(name, value):
    check(value, read("schemas/"+name+".schema.json"))
