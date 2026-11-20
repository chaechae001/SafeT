"""평가 항목별로 검수한 L01 인덱스를 읽고 서버 측 근거만 반환한다."""
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

import chromadb
import torch
from transformers import AutoModel, AutoTokenizer
from rules import review
from observability import QueryTrace
from evaluator import legal_groundedness_v1

COLLECTION = "baseline-kure-6258660a191f"
PROMPT = Path(__file__).with_name("prompt.txt").read_text(encoding="utf-8-sig")


def candidates(collection, tokenizer, encoder, question):
    with torch.inference_mode():
        tokens = tokenizer(question, truncation=True, max_length=512, return_tensors="pt")
        vector = torch.nn.functional.normalize(encoder(**tokens).last_hidden_state[:, 0])
    hits = collection.query(query_embeddings=vector.tolist(), n_results=267)
    rows = []
    seen = set()
    for meta, text in zip(hits["metadatas"][0], hits["documents"][0]):
        section = meta["section"]
        article = re.match(r"제\d+조(?:의\d+)?", section)
        key = (meta["law"], article.group() if article else section)
        if key in seen:
            continue
        seen.add(key)
        rows.append(dict(chunk_id=meta["chunk_id"], law=meta["law"], locator=section, text=text))
        if len(rows) == 6:
            break
    return rows


def generate(question, rows):
    return request_completion([
                       dict(role="system", content=PROMPT),
                       dict(role="user", content=json.dumps({"hazard":{"description":question},
                            "candidates":rows}, ensure_ascii=False))])


def request_completion(messages, max_tokens=700):
    payload = dict(model=os.environ["SAFET_AI_MODEL"], temperature=0, max_tokens=max_tokens,
                   response_format={"type":"json_object"}, messages=messages)
    request = urllib.request.Request(os.environ["SAFET_AI_GATEWAY_URL"].rstrip("/") + "/v1/chat/completions",
        data=json.dumps(payload).encode(), headers={"Content-Type":"application/json",
        "Authorization":"Bearer " + os.environ["SAFET_AI_API_KEY"]})
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)


def parse_response(question, rows, content):
    try:
        output = json.loads(content)
        citations = output["evidence"]
        if not isinstance(citations,list) or not all(isinstance(c,dict) and isinstance(c.get("chunk"),str) for c in citations):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        citations = []
    return review(question, rows, {"selection":{"citations":citations}})


def evaluate(collection, tokenizer, encoder, question):
    recorder = QueryTrace()
    with recorder.stage("Legal RAG", "chain", {"question": question}) as overall:
        with recorder.stage("KURE-v1 / Chroma", "retriever", {"question": question}) as retrieval:
            rows = candidates(collection, tokenizer, encoder, question)
            retrieval["source_documents"] = rows
            overall["source_documents"] = rows
        with recorder.stage("8010 completion", "llm", {"question": question, "context": rows,
                            "system_prompt": PROMPT}) as generation:
            response = generate(question, rows)
            record_completion(generation, response)
            generation["answer"] = response["choices"][0]["message"]["content"]
        with recorder.stage("Parse / citation review", "parser", {"raw_answer": generation["answer"]}) as parsed:
            result = parse_response(question, rows, response["choices"][0]["message"]["content"])
            parsed["answer"] = result
            overall["answer"] = result
            overall["raw_answer"] = generation["answer"]
            overall["status_label"] = result["status"]
        if os.getenv("SAFET_LEGAL_EVALUATOR_ENABLED") == "true":
            try:
                with recorder.stage("legal_groundedness_v1", "chain", {"question": question,
                                    "context": rows, "answer": result}) as evaluated:
                    def judge(messages):
                        with recorder.stage("8010 judge", "llm", {"messages": messages}) as judged:
                            completion = request_completion(messages, max_tokens=600)
                            record_completion(judged, completion)
                            judged["answer"] = completion["choices"][0]["message"]["content"]
                            return completion
                    evaluated.update(legal_groundedness_v1(question, rows, result, judge))
                    overall["evaluation"] = dict(evaluated)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                overall["evaluation"] = {"key": "legal_groundedness_v1", "score": None,
                                         "error_type": type(exc).__name__}
    if "evaluation" in overall and overall["evaluation"].get("score") is not None:
        attach_feedback(recorder, overall["evaluation"])
    return result


def record_completion(target, response):
    target["model"] = response.get("model")
    target["completion_id"] = response.get("id")
    usage = response.get("usage") or {}
    if all(isinstance(usage.get(k), int) for k in ("prompt_tokens", "completion_tokens", "total_tokens")):
        target["usage_metadata"] = dict(input_tokens=usage["prompt_tokens"],
             output_tokens=usage["completion_tokens"], total_tokens=usage["total_tokens"])


def attach_feedback(recorder, evaluation):
    if os.getenv("LANGSMITH_TRACING", "").lower() != "true":
        return
    from uuid import uuid5
    from langsmith import run_trees
    client = run_trees.get_cached_client()
    client.flush()
    try:
        client.create_feedback(run_id=recorder.id, key=evaluation["key"],
            score=evaluation["score"], comment=evaluation["comment"],
            feedback_id=uuid5(recorder.id, evaluation["key"]),
            extend_trace_retention=False,
            feedback_source_type="model", source_info={"model": evaluation["judge_model"],
            "prompt_sha256": evaluation["prompt_sha256"], "target": evaluation["target"]})
    except Exception as exc:
        # 피드백 전송 실패에도 생성한 평가표와 로컬 결과를 유지한다.
        if os.getenv("SAFET_LEGAL_TRACE_DIR"):
            Path(os.environ["SAFET_LEGAL_TRACE_DIR"], str(recorder.id) + ".feedback-error.json").write_text(
                json.dumps({"error_type": type(exc).__name__}), encoding="utf8")


def main():
    questions = json.load(sys.stdin)
    torch.set_num_threads(4)
    weights = os.environ["SAFET_LEGAL_WEIGHTS"]
    tokenizer = AutoTokenizer.from_pretrained(weights, local_files_only=True)
    encoder = AutoModel.from_pretrained(weights, local_files_only=True).eval()
    collection = chromadb.PersistentClient(path=os.environ["SAFET_LEGAL_CHROMA"]).get_collection(COLLECTION)
    if collection.count() != 267:
        raise ValueError("L01 인덱스 건수가 다릅니다.")
    results = [evaluate(collection, tokenizer, encoder, q) for q in questions]
    json.dump(results, sys.stdout, ensure_ascii=True)


if __name__ == "__main__":
    main()
