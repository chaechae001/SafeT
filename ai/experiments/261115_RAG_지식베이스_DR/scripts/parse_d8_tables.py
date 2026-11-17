"""Parse D8 VI-3 industry guide tables (PDF p247-275) into rows: task label / hazard bullets / measure bullets.

Method (reproducible, no manual edits):
- pypdf text runs with (x, y). y grows downward on these pages.
- Columns: task x < 1200, hazard 1200 <= x < measure_x - 60, measure x >= measure_x - 60
  (measure_x = bullet x of the right column on that page: 2671 or 2813).
- Table region: from header row ("주요 작업 … 예방대책") to the next non-table line
  (circled digit process description, '▷', '<표', '(n) 업종', page number) or page end.
- Rows: task labels are vertically centred and rows are contiguous, so bottom_i = 2*c_i - top_i.
  top_1 is chosen among candidate gaps so that computed boundaries split the fewest bullets.
  Bullets above top_1 on a page without header are a continuation of the previous page's last row.
Output: scratchpad/d8_rows.json
"""
import glob, json, re
import pypdf

RAG = r"<LOCAL_WORKSPACE>/RAG용/"
SC = r"<LOCAL_SCRATCH>/"
r = pypdf.PdfReader(glob.glob(RAG + "*최종보고서*")[0])
IND = re.compile(r"^\((\d)\) ?(한식|중식|피자|치킨|커피|제과제빵)\s*$")
STOP = re.compile(r"^([①②③④⑤⑥⑦⑧⑨]|▷|<표|\(\d\)|\d{3}$|[가-힣]{0,3}\s*\d{3}$)")


def runs_of(pno):
    out = []
    def v(t, cm, tm, fd, fs):
        if t and t.strip():
            out.append((cm[4] + tm[4], cm[5] + tm[5], t))
    r.pages[pno - 1].extract_text(visitor_text=v)
    # drop running page header (y≈1827 on odd pages: "Ⅵ. 가맹본부 산업재해 예방 조치 이행 촉진 방안")
    return [q for q in out if q[1] > 1900]


def group_lines(runs):
    ln = {}
    for x, y, t in runs:
        key = round(y)
        ln.setdefault(key, []).append((x, t))
    return [(y, min(x for x, _ in v), "".join(t for _, t in sorted(v))) for y, v in sorted(ln.items())]


def join(prev, s):
    if not prev:
        return s
    # Korean wrapped words in this report are split without space; keep a space if previous ends with space
    return prev + s if not prev.endswith(" ") else prev + s


def to_bullets(lines):
    bs = []
    for y, x, t in lines:
        s = t.rstrip()
        st = s.strip()
        if st.startswith("•"):
            bs.append({"y0": y, "y1": y, "text": st.lstrip("•").strip()})
        elif bs:
            bs[-1]["text"] = join(bs[-1]["text"], st)
            bs[-1]["y1"] = y
        else:
            bs.append({"y0": y, "y1": y, "text": "\u0000" + st, "headless": True})
    return bs


def labels_of(lines):
    groups = []
    for y, x, t in lines:
        if groups and y - groups[-1]["y1"] <= 140:
            groups[-1]["text"] += t.strip()
            groups[-1]["y1"] = y
        else:
            groups.append({"y0": y, "y1": y, "text": t.strip()})
    for g in groups:
        g["c"] = (g["y0"] + g["y1"]) / 2
    return groups


def extend(dst, src):
    """append bullets; a headless first bullet (marked \u0000) continues the previous bullet across a page break"""
    for k, t in enumerate(src):
        if k == 0 and t.startswith("\u0000") and dst:
            dst[-1] = dst[-1] + t[1:]
        else:
            dst.append(t.lstrip("\u0000"))


def split_score(bounds, bullets):
    bad = 0
    for b in bullets:
        for z in bounds:
            if b["y0"] < z < b["y1"]:
                bad += 1
    return bad


def parse():
    rows, industry = [], None
    for p in range(247, 276):
        runs = runs_of(p)
        bx = sorted({round(x) for x, y, t in runs if t.strip().startswith("•")})
        mx = min(b for b in bx if b > 2000)  # right-column bullet x (inline bullets lie further right)
        lines = group_lines(runs)
        # header rows: line containing 주요 and 작업 at x<1200 with 예방대책 on same y
        header_ys = [y for y, x, t in lines if "주요" in t and "예방대책" in t]
        # region segmentation
        segs, cur, i = [], None, 0
        for y, x, t in lines:
            st = t.strip()
            m = IND.match(st)
            if m:
                industry = m.group(2)
            if y in header_ys:
                if cur: segs.append(cur)
                cur = {"start": y, "end": None, "industry": industry, "header": True}
                continue
            if cur is None and p > 247 and not segs and x < 1300 and st.startswith("•"):
                cur = {"start": 0, "end": None, "industry": industry, "header": False}
            if cur is not None and x < 1200 and STOP.match(st):
                cur["end"] = y; segs.append(cur); cur = None
        if cur:
            cur["end"] = 10 ** 6; segs.append(cur)
        # continuation region when page starts with table bullets (before any stop line)
        for sg in segs:
            rr = [(x, y, t) for x, y, t in runs if sg["start"] < round(y) < sg["end"] and not (sg["header"] and round(y) == sg["start"])]
            # drop page-number like runs
            rr = [q for q in rr if not re.fullmatch(r"\s*\d{3}\s*", q[2])]
            task = [q for q in rr if q[0] < 1200]
            haz = [q for q in rr if 1200 <= q[0] < mx - 60]
            mea = [q for q in rr if q[0] >= mx - 60]
            hb, mb = to_bullets(group_lines(haz)), to_bullets(group_lines(mea))
            labs = labels_of(group_lines(task))
            allb = hb + mb
            ys = sorted({b["y0"] for b in allb} | {b["y1"] for b in allb})
            first = min(ys) if ys else 0
            if not labs:
                rows.append({"page": p, "industry": sg["industry"], "task": None, "continuation": True,
                             "hazards": [b["text"] for b in hb], "measures": [b["text"] for b in mb]})
                continue
            # candidate tops: content start, or midpoints of gaps before the first label centre
            cands = [first - 1] + [(a + b) / 2 for a, b in zip(ys, ys[1:]) if b < labs[0]["c"]]
            best = None
            for t0 in cands:
                bounds, top = [t0], t0
                ok = True
                for g in labs:
                    bot = 2 * g["c"] - top
                    if bot <= g["y1"]:
                        ok = False
                    bounds.append(bot); top = bot
                last_end = max(ys) + 60  # last row ends just below its tallest column
                sc = split_score(bounds, allb) * 1000 + (100000 if not ok else 0) + abs(bounds[-1] - last_end)
                if best is None or sc < best[0]:
                    best = (sc, bounds)
            sc, bounds = best
            sc = sc // 1000  # number of split bullets
            bounds[-1] = max(bounds[-1], max(ys) + 1)
            # continuation part above first top
            pre_h = [b["text"] for b in hb if b["y1"] < bounds[0]]
            pre_m = [b["text"] for b in mb if b["y1"] < bounds[0]]
            if pre_h or pre_m:
                rows.append({"page": p, "industry": sg["industry"], "task": None, "continuation": True,
                             "hazards": pre_h, "measures": pre_m})
            for k, g in enumerate(labs):
                lo, hi = bounds[k], bounds[k + 1]
                rows.append({"page": p, "industry": sg["industry"], "task": g["text"], "continuation": False,
                             "hazards": [b["text"] for b in hb if lo <= b["y0"] < hi],
                             "measures": [b["text"] for b in mb if lo <= b["y0"] < hi],
                             "split_conflicts_on_page_segment": sc})
    # attach continuation rows to the previous row (same industry)
    merged = []
    for row in rows:
        if row["continuation"] and merged:
            extend(merged[-1]["hazards"], row["hazards"]); extend(merged[-1]["measures"], row["measures"])
            merged[-1].setdefault("pages", [merged[-1]["page"]]).append(row["page"])
        else:
            merged.append(row)
    # a task label split by a page break: merge rows i, i+1 when label_i + label_i+1 equals a label used elsewhere
    for m in merged:
        m.setdefault("pages", [m["page"]])
    known = {m["task"] for m in merged if m["task"]}
    out = []
    for m in merged:
        if out and out[-1]["task"] and m["task"] and (out[-1]["task"] + m["task"]) in known and m["page"] != out[-1]["pages"][0]:
            out[-1]["task"] += m["task"]; extend(out[-1]["hazards"], m["hazards"]); extend(out[-1]["measures"], m["measures"])
            out[-1]["pages"] = sorted(set(out[-1]["pages"] + m["pages"]))
            out[-1]["label_merged_across_pages"] = True
        else:
            out.append(m)
    merged = out
    for m in merged:
        m["hazards"] = [t.lstrip("\u0000") for t in m["hazards"]]
        m["measures"] = [t.lstrip("\u0000") for t in m["measures"]]
    for i, m in enumerate(merged, 1):
        m["row_key"] = f"D8T-{i:03d}"
        m.setdefault("pages", [m["page"]])
    return merged


if __name__ == "__main__":
    rows = parse()
    json.dump(rows, open(SC + "d8_rows.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for m in rows:
        print(m["row_key"], m["pages"], m["industry"], m["task"], len(m["hazards"]), len(m["measures"]), m.get("split_conflicts_on_page_segment"))
