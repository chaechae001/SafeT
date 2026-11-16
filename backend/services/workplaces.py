"""사업장 업무 처리 (B01 · B02 · B02-E · 화면설계서 08~09쪽)

- 업종을 고르면 그 업종의 DB 기기(machine_category, use_yn='Y')를 고를 수 있음
- 직접 추가 기기: workplace_machine.machine_code = NULL. 업종 기기와 이름이 같으면 그 기기로 합침
- 수정: 사업장명과 보유 기기만 (업종 변경 불가). 이미 작성한 평가표의 기기 기록(eval_machine)은 그대로
- 삭제: 데이터를 지우지 않고 use_yn='N'. 목록·평가 사업장 선택에서 숨김
- 본인(email) 사업장만 보고 고칠 수 있음. 남의 사업장·삭제한 사업장은 '없음(404)'으로 처리
"""
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from services.auth import AuthError, now


def _not_found():
    return AuthError(404, "WORKPLACE_NOT_FOUND", "사업장을 찾을 수 없어요.")


def biz_categories(db: Session) -> list[dict]:
    rows = db.execute(text("SELECT biz_code, biz_nm FROM biz_category ORDER BY biz_code")).mappings()
    return [dict(r) for r in rows]


def machines(db: Session, biz_code: str) -> list[dict]:
    if not db.execute(text("SELECT 1 FROM biz_category WHERE biz_code = :b"), {"b": biz_code}).first():
        raise AuthError(404, "BIZ_NOT_FOUND", "업종을 찾을 수 없어요.")
    rows = db.execute(
        text(
            "SELECT machine_code, machine_nm FROM machine_category "
            "WHERE biz_code = :b AND COALESCE(use_yn, 'Y') = 'Y' ORDER BY machine_code"
        ),
        {"b": biz_code},
    ).mappings()
    return [dict(r) for r in rows]


def _resolve_machines(db: Session, biz_code: str, codes: list[str], custom: list[str]) -> list[tuple]:
    """저장할 기기 목록 [(machine_code | None, machine_nm)] — 업종 기기 검사, 직접 추가 이름 합치기"""
    catalog = {m["machine_code"]: m["machine_nm"] for m in machines(db, biz_code)}
    by_name = {(nm or "").strip().lower(): code for code, nm in catalog.items()}

    chosen: list[str] = []
    for code in codes:
        if code not in catalog:
            raise AuthError(400, "INVALID_MACHINE", "이 업종의 기기 목록에 없는 기기가 있어요. 다시 불러와 주세요.")
        if code not in chosen:
            chosen.append(code)

    result = [(c, catalog[c]) for c in chosen]
    for name in custom:
        code = by_name.get(name.lower())
        if code:                                   # 목록에 있는 이름이면 그 기기로 합침
            if code not in chosen:
                chosen.append(code)
                result.append((code, catalog[code]))
        else:
            result.append((None, name))
    return result


def _insert_machines(db: Session, work_no: int, items: list[tuple], who: str) -> None:
    t = now()
    for code, name in items:
        db.execute(
            text(
                "INSERT INTO workplace_machine (work_no, machine_code, machine_nm, ins_dt, ins_nm, upt_dt, upt_nm) "
                "VALUES (:w, :c, :n, :t, :u, :t, :u)"
            ),
            {"w": work_no, "c": code, "n": name, "t": t, "u": who},
        )


def _owned(db: Session, email: str, work_no: int):
    row = db.execute(
        text(
            "SELECT w.work_no, w.workplace, w.biz_code, b.biz_nm FROM workplaces w "
            "LEFT JOIN biz_category b ON b.biz_code = w.biz_code "
            "WHERE w.work_no = :w AND w.email = :e AND COALESCE(w.use_yn, 'Y') = 'Y'"
        ),
        {"w": work_no, "e": email},
    ).mappings().first()
    if not row:
        raise _not_found()
    return row


def _machines_of(db: Session, work_nos: list[int]) -> dict:
    if not work_nos:
        return {}
    rows = db.execute(
        text(
            "SELECT work_no, machine_code, machine_nm FROM workplace_machine "
            "WHERE work_no IN :ws ORDER BY work_no, (machine_code IS NULL), machine_code, wp_machine_no"
        ).bindparams(bindparam("ws", expanding=True)),
        {"ws": work_nos},
    ).mappings()
    out: dict = {w: [] for w in work_nos}
    for r in rows:
        out[r["work_no"]].append({"machine_code": r["machine_code"], "machine_nm": r["machine_nm"], "custom": r["machine_code"] is None})
    return out


def _draft_counts(db: Session, work_nos: list[int]) -> dict:
    if not work_nos:
        return {}
    rows = db.execute(
        text(
            "SELECT work_no, COUNT(*) n FROM eval_mst "
            "WHERE work_no IN :ws AND eval_status = 'W' AND COALESCE(del_yn, 'N') = 'N' GROUP BY work_no"
        ).bindparams(bindparam("ws", expanding=True)),
        {"ws": work_nos},
    ).mappings()
    return {r["work_no"]: int(r["n"]) for r in rows}


def list_workplaces(db: Session, email: str) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT w.work_no, w.workplace, w.biz_code, b.biz_nm FROM workplaces w "
            "LEFT JOIN biz_category b ON b.biz_code = w.biz_code "
            "WHERE w.email = :e AND COALESCE(w.use_yn, 'Y') = 'Y' ORDER BY w.work_no"
        ),
        {"e": email},
    ).mappings().all()
    nos = [r["work_no"] for r in rows]
    ms = _machines_of(db, nos)
    drafts = _draft_counts(db, nos)
    return [{**dict(r), "machines": ms.get(r["work_no"], []), "draft_count": drafts.get(r["work_no"], 0)} for r in rows]


def get_workplace(db: Session, email: str, work_no: int) -> dict:
    row = _owned(db, email, work_no)
    return {
        **dict(row),
        "machines": _machines_of(db, [work_no]).get(work_no, []),
        "draft_count": _draft_counts(db, [work_no]).get(work_no, 0),
    }


def create_workplace(db: Session, email: str, name: str, biz_code: str, codes: list[str], custom: list[str]) -> dict:
    items = _resolve_machines(db, biz_code, codes, custom)      # 업종이 없으면 404
    t = now()
    res = db.execute(
        text(
            "INSERT INTO workplaces (email, workplace, biz_code, use_yn, ins_dt, ins_nm, upt_dt, upt_nm) "
            "VALUES (:e, :n, :b, 'Y', :t, :e, :t, :e)"
        ),
        {"e": email, "n": name, "b": biz_code, "t": t},
    )
    work_no = res.lastrowid
    _insert_machines(db, work_no, items, email)
    db.commit()
    return {"work_no": work_no}


def update_workplace(db: Session, email: str, work_no: int, name: str, codes: list[str], custom: list[str]) -> dict:
    row = _owned(db, email, work_no)
    items = _resolve_machines(db, row["biz_code"], codes, custom)   # 업종은 기존 값 그대로
    db.execute(
        text("UPDATE workplaces SET workplace = :n, upt_dt = :t, upt_nm = :e WHERE work_no = :w"),
        {"n": name, "t": now(), "e": email, "w": work_no},
    )
    # 보유 기기는 통째로 교체 (평가표의 기기 기록은 eval_machine 이라 영향 없음)
    db.execute(text("DELETE FROM workplace_machine WHERE work_no = :w"), {"w": work_no})
    _insert_machines(db, work_no, items, email)
    db.commit()
    return get_workplace(db, email, work_no)


def delete_workplace(db: Session, email: str, work_no: int) -> None:
    _owned(db, email, work_no)
    db.execute(
        text("UPDATE workplaces SET use_yn = 'N', upt_dt = :t, upt_nm = :e WHERE work_no = :w"),
        {"t": now(), "e": email, "w": work_no},
    )
    db.commit()
