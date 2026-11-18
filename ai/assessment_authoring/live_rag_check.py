"""SSH로 확보한 실제 검색 응답을 사용해 관문 모델·최종 행 연결을 검사한다."""
import json, time
from pathlib import Path
from .contracts import load_catalog
from .live_text_check import load_settings, request_json, build_messages, output_budget, parse_completion, model_response_format
from .evidence_qualification import qualify_direct_evidence
from .pipeline import run_pipeline

def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--env-file",required=True)
    p.add_argument("--rag-file",required=True)
    p.add_argument("--links-file",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args()
    raw=json.loads(Path(args.rag_file).read_text(encoding="utf-8"))
    rows=json.loads(Path(args.links_file).read_text(encoding="utf-8"))["rows"]
    filtered, exclusions=qualify_direct_evidence(raw, rows)
    env=load_settings(args.env_file)
    base=env["SAFET_AI_GATEWAY_URL"].rstrip("/")
    if base!="https://gdqtaahjfkzgzzxr.tunnel.elice.io/proxy/8010":raise ValueError("관문 불일치")
    model=env["SAFET_AI_MODEL"];key=env["SAFET_AI_API_KEY"]
    context=dict(contract_version="assessment-authoring-1",catalog_version="CATALOG-MVP-1.1",
        media=[dict(id="TEXT",kind="text",text="주방에서 튀김기로 조리를 합니다.")],equipment_ids=["EQ_FRYER"])
    report=dict(status="running",input=context,exclusions=exclusions,batches=[],source="SSH existing RAG service")
    start=time.perf_counter()
    def extract(i,r,c,evidence):
        messages=build_messages(i,r,c,evidence)
        entry=dict(scenario_ids=[row["scenario_id"] for row in r["candidates"]],messages=messages)
        report["batches"].append(entry)
        count=request_json(base,key,"/tokenize",dict(model=model,messages=messages,add_generation_prompt=True))["count"]
        budget=output_budget(count)
        entry.update(input_tokens=count,output_budget=budget)
        response=request_json(base,key,"/v1/chat/completions",
            dict(model=model,messages=messages,temperature=0,max_tokens=budget,response_format=model_response_format(i, r, c)))
        entry["usage"]=response.get("usage")
        entry["raw_analysis"]=parse_completion(response, i)
        return entry["raw_analysis"]
    try:
        out=run_pipeline(context,build_context=lambda x:x,extract_analysis=None,catalog_snapshot=load_catalog(),
            rag_provider=lambda *a,**kw:filtered,rag_links={"EQ_FRYER:burn":["FRY"],"EQ_FRYER:slip":["ENV"]},
            extract_with_evidence=extract,batch_size=1)
        sent={sid:docs for b in report["batches"] for sid,docs in json.loads(b["messages"][-1]["content"])["reference_documents"].items()}
        checks=[]
        for row in out["assessment"]["rows"]:
            sid=row["scenario_id"]
            checks.append(dict(scenario_id=sid,identical=sent[sid]==row["document_evidence"],
                grade=row["grade"],evidence_ids=[d["evidence_id"] for d in row["document_evidence"]]))
        if {c["scenario_id"] for c in checks}!={"FRY","ENV"} or not all(c["identical"] for c in checks):
            raise ValueError("근거 전달 누락")
        if any(e["state"]!="unknown" for c in out["analysis"]["candidates"] for e in c["control_evidence"]):
            raise ValueError("문헌이 현장 조치로 승격됨")
        report.update(status="passed",pipeline=out,checks=checks)
    except Exception as e:
        report.update(status="failed",error=str(e),error_type=type(e).__name__)
    report["elapsed_seconds"]=round(time.perf_counter()-start,2)
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in ("pipeline","batches")},ensure_ascii=False))
    if report["status"]!="passed":raise SystemExit(1)
if __name__=="__main__":main()

