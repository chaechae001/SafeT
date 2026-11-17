"""위험성평가 결과서 PDF (문서 다운로드)

참고: dev_docs/report_service.py · dev_docs/report.html (WeasyPrint 기준 초안)
바꾼 점 (2026-11-17)
- PDF 엔진: WeasyPrint 대신 xhtml2pdf (pip 설치만으로 동작, Windows·Linux 공통. GTK/Pango 불필요)
- 판단 기준표(가능성×중대성 임시 조합표)와 가능성·중대성 열은 뺌 (팀 결정 전 · 음식점 v2는 다른 기준)
- 신호 이름은 화면과 같게 (상·중·하·판단 필요). '판단 필요'는 낮은 위험으로 세지 않고 따로 셈
- 개선 후 신호가 '판단 필요'(N)인 항목은 '내려감'으로 세지 않음 (참고 코드는 N 을 0으로 보고 셈)
- 작성 중(W) 문서는 '미확정본'으로 표시, demo 생성 문서는 '시험용 합성 자료'로 표시

한글 폰트: TTF 파일 경로를 .env 의 REPORT_FONT_REGULAR / REPORT_FONT_BOLD 로 지정.
비워 두면 Windows 맑은 고딕 → Linux 나눔고딕(apt install fonts-nanum) 순서로 찾음.
(Noto CJK .otf 는 reportlab 이 읽지 못함)
"""
import io
import os
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from services.auth import AuthError

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

GRADE_NM = {"R": "상 · 우선 개선", "Y": "중 · 개선 필요", "G": "하 · 유지 관리", "N": "판단 필요"}
STATUS_NM = {"W": "작성 중 · 미확정", "C": "확정", "S": "서명 완료", "A": "조치 완료"}
GRADE_RANK = {"R": 3, "Y": 2, "G": 1}
METHOD_NM = {
    "restaurant_v2": "음식점 위험성평가 v2 기준 (상·중·하 3단계)",
    "demo": "개발 시험용 합성 자료 · 실제 현장 판정 아님",
    "unavailable": "AI 판단 미연결 · 판단 필요 항목은 담당자 확인 필요",
}

FONT_CANDIDATES = [
    (r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\malgunbd.ttf"),
    ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
]


def _d(v, fmt="%Y.%m.%d"):
    if not v:
        return None
    if isinstance(v, str):
        v = datetime.fromisoformat(v)
    return v.strftime(fmt)


def build_context(eval_no: int, fetch, share: bool = False) -> dict:
    """fetch(sql, params) -> list[dict] 를 받아 템플릿 값을 만든다. 소유권 확인은 호출하는 쪽에서.

    share=True: 공유 링크로 내려주는 공유본. 서명 이미지(원본)는 넣지 않고 서명 여부·시각만 (화면설계서 29·30쪽)
    """
    m = fetch(
        """
        SELECT e.*, w.workplace, b.biz_nm
          FROM eval_mst e
          JOIN workplaces w        ON w.work_no = e.work_no
          LEFT JOIN biz_category b ON b.biz_code = w.biz_code
         WHERE e.eval_no = :no
        """,
        {"no": eval_no},
    )[0]

    members = fetch("SELECT member_no, member_nm FROM eval_member WHERE eval_no = :no ORDER BY sort, member_no",
                    {"no": eval_no})
    machines = [r["machine_nm"] for r in fetch(
        "SELECT machine_nm FROM eval_machine WHERE eval_no = :no AND check_yn = 'Y' ORDER BY eval_machine_no",
        {"no": eval_no})]

    dtls = fetch("SELECT * FROM eval_dtl WHERE eval_no = :no ORDER BY sort, eval_dtl_no", {"no": eval_no})
    acts = fetch(
        """
        SELECT a.* FROM eval_action a
          JOIN eval_dtl d ON d.eval_dtl_no = a.eval_dtl_no
         WHERE d.eval_no = :no AND a.check_yn = 'Y'
         ORDER BY a.eval_dtl_no, a.action_type, a.sort
        """,
        {"no": eval_no},
    )

    items, plans_total, after_down, dues = [], 0, 0, []
    for d in dtls:
        mine = [a for a in acts if a["eval_dtl_no"] == d["eval_dtl_no"]]
        curr = [a["action_text"] for a in mine if a["action_type"] == "C"]
        plans = [{"text": a["action_text"], "ai": a["ai_yn"] != "N"} for a in mine if a["action_type"] == "P"]
        grade = d["curr_risk_grade"] or "N"
        keep = grade == "G" and d["keep_yn"] == "Y"
        if keep:
            plans = []
        plans_total += len(plans)
        after = d["after_risk_grade"] if d["after_risk_grade"] in GRADE_NM else None
        if not keep and after in GRADE_RANK and GRADE_RANK[after] < GRADE_RANK.get(grade, 0):
            after_down += 1
        if d["due_dt"] and not keep:
            dues.append(d["due_dt"])
        items.append({
            "job": d["job"], "risk_factor": d["risk_factor"], "risk_type": d["risk_type"],
            "reason": d["reason"], "curr": curr, "curr_none": d["curr_none_yn"] == "Y",
            "grade": grade, "plans": plans, "keep": keep, "after": after,
            "manager": None if keep else d["manager_nm"],
            "due_dt": None if keep else _d(d["due_dt"]),
            "law": d["law"], "law_summary": d["law_summary"],
        })

    signed = {s["member_no"]: s for s in fetch(
        "SELECT * FROM eval_sign WHERE eval_no = :no AND sign_yn = 'Y'", {"no": eval_no})}
    signs = []
    for r in members:
        s = signed.get(r["member_no"])
        img = s["sign_img"] if s else None
        signs.append({
            "name": r["member_nm"],
            # 서명 이미지는 data URL(PNG/JPEG)만 사용. 외부 주소는 PDF 생성 중 불러오지 않음
            "img": img if not share and img and str(img).startswith(("data:image/png", "data:image/jpeg")) else None,
            "signed": s is not None,
            "confirm": bool(s and s["confirm_yn"] == "Y"),
            "sign_dt": _d(s["sign_dt"], "%Y.%m.%d %H:%M") if s else None,
        })

    grades = [i["grade"] for i in items]
    source = m.get("generation_source") or "unavailable"
    return {
        "workplace": m["workplace"], "biz_nm": m["biz_nm"] or "—", "eval_nm": m["eval_nm"],
        "eval_dt": _d(m["eval_dt"]), "writer": m["eval_writer"],
        "confirm_dt": _d(m["confirm_dt"]), "sign_end_dt": _d(m["sign_end_dt"]),
        "status": m["eval_status"], "status_nm": STATUS_NM.get(m["eval_status"], ""),
        "draft": m["eval_status"] == "W", "demo": source == "demo", "share": share,
        "method": METHOD_NM.get(source, source),
        "members": [r["member_nm"] for r in members], "machines": machines, "rows": items, "signs": signs,
        "sum": {
            "total": len(items), "R": grades.count("R"), "Y": grades.count("Y"), "G": grades.count("G"),
            "N": grades.count("N"), "plans": plans_total, "after_down": after_down,
            "last_due": _d(max(dues)) if dues else None,
        },
        "generated_at": datetime.now().strftime("%Y.%m.%d %H:%M"),
    }


_env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=select_autoescape(["html"]))


def render_html(ctx: dict) -> str:
    return _env.get_template("report.html").render(r=ctx, grade_nm=GRADE_NM)


_font_ready = False


def _register_font():
    """reportlab 에 한글 폰트를 'kr' 이름으로 한 번만 등록"""
    global _font_ready
    if _font_ready:
        return
    from reportlab.lib.fonts import addMapping
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from xhtml2pdf.default import DEFAULT_FONT

    regular, bold = os.getenv("REPORT_FONT_REGULAR", ""), os.getenv("REPORT_FONT_BOLD", "")
    if not regular:
        for r, b in FONT_CANDIDATES:
            if Path(r).is_file():
                regular, bold = r, b
                break
    if not regular or not Path(regular).is_file():
        raise AuthError(503, "REPORT_FONT_MISSING", "문서에 쓸 한글 폰트가 서버에 없어요. 관리자에게 알려 주세요.")
    if not bold or not Path(bold).is_file():
        bold = regular
    pdfmetrics.registerFont(TTFont("KR", regular))
    pdfmetrics.registerFont(TTFont("KR-Bold", bold))
    for b_ in (0, 1):
        for i in (0, 1):
            addMapping("kr", b_, i, "KR-Bold" if b_ else "KR")
    DEFAULT_FONT["kr"] = "KR"
    _font_ready = True


def _no_fetch(uri, rel):
    """템플릿 밖 파일·주소는 읽지 않음 (data URL 이미지만 허용)"""
    return uri if str(uri).startswith("data:") else ""


def render_pdf(ctx: dict) -> bytes:
    from xhtml2pdf import pisa  # 무거운 import는 필요할 때만
    _register_font()
    out = io.BytesIO()
    result = pisa.CreatePDF(render_html(ctx), dest=out, encoding="utf-8", link_callback=_no_fetch)
    if result.err:
        raise AuthError(500, "REPORT_FAILED", "문서를 만들지 못했어요. 잠시 뒤 다시 시도해 주세요.")
    return out.getvalue()


def file_name(ctx: dict) -> str:
    """내려받을 파일 이름: 평가명_위험성평가결과서(_미확정).pdf · 파일 이름에 못 쓰는 글자는 _"""
    base = "".join("_" if ch in '\\/:*?"<>|\r\n\t' else ch for ch in (ctx["eval_nm"] or "평가표")).strip() or "평가표"
    return f"{base[:80]}_위험성평가결과서{'_미확정' if ctx['draft'] else ''}.pdf"
