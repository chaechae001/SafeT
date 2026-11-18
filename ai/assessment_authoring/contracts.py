"""공통 계약의 사용 중인 Schema 부분집합 검사."""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "contracts/assessment_authoring/v1"
def read(path):
    return json.loads((KIT/path).read_text(encoding="utf-8-sig"))
def load_catalog():
    return json.loads((ROOT/"contracts/catalog_risk/catalog.json").read_text(encoding="utf-8-sig"))
def require(ok, message):
    if not ok:
        raise ValueError(message)


def check(value, schema, path="$"):
    if "const" in schema:
        require(value == schema["const"], path + ": const")
    if "enum" in schema:
        require(value in schema["enum"], path + ": enum")
    kind = schema.get("type")
    if kind == "object":
        require(isinstance(value, dict), path + ": object")
        require(set(schema.get("required", [])) <= value.keys(), path + ": required")
        props = schema["properties"]
        if schema.get("additionalProperties") is False:
            require(value.keys() <= props.keys(), path + ": extra field")
        for key, child in value.items():
            if key in props:
                check(child, props[key], path + "." + key)
    elif kind == "array":
        require(isinstance(value, list), path + ": array")
        require(schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 100000), path + ": length")
        for n, child in enumerate(value):
            check(child, schema["items"], path + "[" + str(n) + "]")
    elif kind == "string":
        require(isinstance(value, str) and len(value.strip()) >= schema.get("minLength", 0), path + ": string")
    elif kind == "integer":
        require(type(value) is int and value >= schema.get("minimum", -100000), path + ": integer")


def schema(name, value):
    check(value, read("schemas/"+name+".schema.json"))
