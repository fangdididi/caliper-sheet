#!/usr/bin/env python3
"""partsheet: check a caliper measurement log and draw a true-scale three-view sheet.

Usage:
  python3 partsheet.py check part.json [--json]
  python3 partsheet.py svg part.json -o sheet.svg
  python3 partsheet.py table part.json

Only the Python standard library is used.
"""
import argparse
import ast
import json
import math
import statistics
import sys

DEFAULT_TOOLS = {"caliper": 0.02, "micrometer": 0.01, "ruler": 0.5, "tape": 1.0, "photo": 1.0, "gauge": 0.05}
DEFAULT_TOL = {"mating": 0.1, "clearance": 0.3, "free": 0.5}

# ISO 273 clearance holes (fine, medium) and common tap drills, in mm.
CLEARANCE = {"M2": (2.2, 2.4), "M2.5": (2.7, 2.9), "M3": (3.2, 3.4), "M4": (4.3, 4.5),
             "M5": (5.3, 5.5), "M6": (6.4, 6.6), "M8": (8.4, 9.0), "M10": (10.5, 11.0)}
TAP_DRILL = {"M2": 1.6, "M2.5": 2.05, "M3": 2.5, "M4": 3.3, "M5": 4.2, "M6": 5.0, "M8": 6.8, "M10": 8.5}

PAPER = {"A4": (297.0, 210.0), "A3": (420.0, 297.0), "letter": (279.4, 215.9)}
SCALES = [(5, 1), (2, 1), (1, 1), (1, 2), (1, 5), (1, 10)]


class PartError(Exception):
    pass


# ---------------------------------------------------------------- formulas
_ALLOWED = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult, ast.Div,
            ast.USub, ast.UAdd, ast.Constant, ast.Name, ast.Load)


def formula_names(expr):
    tree = _parse(expr)
    return sorted({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)})


def _parse(expr):
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise PartError(f"bad formula {expr!r}: {exc.msg}")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            raise PartError(f"formula {expr!r} may only use codes, numbers, + - * / and brackets")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            raise PartError(f"formula {expr!r} has a non-number constant")
    return tree


def eval_formula(expr, values):
    tree = _parse(expr)

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant):
            return float(n.value)
        if isinstance(n, ast.Name):
            if n.id not in values:
                raise PartError(f"formula {expr!r} uses unknown code {n.id}")
            v = values[n.id]
            if v is None:
                return None
            return float(v)
        if isinstance(n, ast.UnaryOp):
            v = ev(n.operand)
            return None if v is None else (-v if isinstance(n.op, ast.USub) else v)
        a, b = ev(n.left), ev(n.right)
        if a is None or b is None:
            return None
        if isinstance(n.op, ast.Add):
            return a + b
        if isinstance(n.op, ast.Sub):
            return a - b
        if isinstance(n.op, ast.Mult):
            return a * b
        if b == 0:
            raise PartError(f"formula {expr!r} divides by zero")
        return a / b

    return ev(tree)


# ---------------------------------------------------------------- hints
def imperial_hint(mm):
    """Return a fraction string like '1/4 in' when mm sits on a 1/64 inch grid but not on a metric grid."""
    if mm is None or mm <= 0:
        return None
    if abs(mm * 2 - round(mm * 2)) <= 0.03:  # on a 0.5 mm grid: metric is just as likely
        return None
    inches = mm / 25.4
    n64 = round(inches * 64)
    if n64 == 0 or abs(n64 / 64 * 25.4 - mm) > 0.03:
        return None
    whole, rest = divmod(n64, 64)
    den = 64
    while rest and rest % 2 == 0:
        rest //= 2
        den //= 2
    if rest == 0:
        return f"{whole} in"
    return (f"{whole} {rest}/{den} in" if whole else f"{rest}/{den} in")


def hole_hint(mm, tol=0.1):
    if mm is None:
        return None
    hits = []
    for size, (fine, medium) in CLEARANCE.items():
        if abs(mm - fine) <= tol:
            hits.append(f"{size} clearance (close)")
        elif abs(mm - medium) <= tol:
            hits.append(f"{size} clearance (normal)")
    for size, drill in TAP_DRILL.items():
        if abs(mm - drill) <= tol:
            hits.append(f"{size} tap drill")
    return ", ".join(hits) or None


# ---------------------------------------------------------------- loading
def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        raise PartError(f"file not found: {path}")
    except json.JSONDecodeError as exc:
        raise PartError(f"{path} is not valid JSON: {exc}")
    return data


def analyse(data):
    if not isinstance(data, dict) or not isinstance(data.get("dims"), list):
        raise PartError("part file needs a 'dims' list")
    tools = dict(DEFAULT_TOOLS)
    tools.update(data.get("tools") or {})
    tol_by_role = dict(DEFAULT_TOL)
    tol_by_role.update(data.get("tolerances") or {})

    rows, values, order = {}, {}, []
    for d in data["dims"]:
        code = d.get("code")
        if not code or not str(code).isidentifier():
            raise PartError(f"every dimension needs a code made of letters/digits, got {code!r}")
        if code in rows:
            raise PartError(f"duplicate code {code}")
        role = d.get("role", "free")
        if role not in tol_by_role:
            raise PartError(f"{code}: role must be one of {sorted(tol_by_role)}")
        tol = float(d.get("tol", tol_by_role[role]))
        row = {"code": code, "name": d.get("name", ""), "role": role, "tol": tol, "flags": [], "hints": [],
               "kind": None, "value": None, "spread": None, "tool": d.get("tool"), "formula": d.get("formula"),
               "readings": d.get("readings") or []}
        kinds = [k for k in ("readings", "formula", "tbd") if d.get(k)]
        if len(kinds) != 1:
            raise PartError(f"{code}: give exactly one of readings, formula or tbd")
        row["kind"] = {"readings": "measured", "formula": "derived", "tbd": "tbd"}[kinds[0]]
        if row["kind"] == "measured":
            rd = [float(x) for x in row["readings"]]
            if any(x <= 0 for x in rd):
                raise PartError(f"{code}: readings must be positive")
            tool = row["tool"] or "caliper"
            if tool not in tools:
                raise PartError(f"{code}: unknown tool {tool!r}; add it under 'tools' with its resolution")
            row["tool"] = tool
            res = float(tools[tool])
            row["value"] = round(statistics.median(rd), 4)
            row["spread"] = round(max(rd) - min(rd), 4)
            limit = max(3 * res, 0.05)
            if row["spread"] > limit:
                row["flags"].append(f"REMEASURE: readings spread {row['spread']:g} > {limit:g}")
            if res > tol / 2:
                row["flags"].append(f"TOOL_TOO_COARSE: {tool} reads {res:g}, tolerance is ±{tol:g}")
            if role == "mating" and len(rd) < 3:
                row["flags"].append("FEW_READINGS: mating dimensions need 3 readings")
        elif row["kind"] == "tbd":
            if role == "mating":
                row["flags"].append("TBD_ON_MATING: a mating size is unknown")
        rows[code] = row
        order.append(code)
        values[code] = row["value"]

    # derived values, resolved in dependency order
    pending = [c for c in order if rows[c]["kind"] == "derived"]
    for c in pending:
        for n in formula_names(rows[c]["formula"]):
            if n not in rows:
                raise PartError(f"{c}: formula uses unknown code {n}")
    guard = 0
    while pending:
        guard += 1
        if guard > len(order) + 2:
            raise PartError("formulas refer to each other in a loop: " + ", ".join(pending))
        nxt = []
        for c in pending:
            deps = formula_names(rows[c]["formula"])
            if any(rows[n]["kind"] == "derived" and n in pending and n != c for n in deps) or c in deps:
                if c in deps:
                    raise PartError(f"{c}: formula refers to itself")
                nxt.append(c)
                continue
            v = eval_formula(rows[c]["formula"], values)
            rows[c]["value"] = None if v is None else round(v, 4)
            values[c] = rows[c]["value"]
            if v is None:
                rows[c]["flags"].append("DERIVED_TBD: depends on an unknown size")
            elif v <= 0:
                rows[c]["flags"].append("NON_POSITIVE: formula gives zero or less")
        if len(nxt) == len(pending):
            raise PartError("formulas refer to each other in a loop: " + ", ".join(pending))
        pending = nxt

    for c in order:
        r = rows[c]
        if r["kind"] == "measured":
            h = imperial_hint(r["value"])
            if h:
                r["hints"].append(f"IMPERIAL?: {r['value']:g} mm is {h}")
            if c.upper().startswith("D") or "hole" in r["name"].lower():
                h = hole_hint(r["value"])
                if h:
                    r["hints"].append(f"LOOKS_LIKE: {h}")

    chains = []
    for ch in data.get("chains") or []:
        parts, overall = ch.get("parts") or [], ch.get("overall")
        for c in parts + [overall]:
            if c not in rows:
                raise PartError(f"chain {ch.get('name', '?')}: unknown code {c}")
        vals = [values[c] for c in parts]
        res = {"name": ch.get("name", "chain"), "parts": parts, "overall": overall}
        if any(v is None for v in vals) or values[overall] is None:
            res.update(status="OPEN", detail="a size in the chain is TBD")
        else:
            total = sum(vals)
            diff = round(total - values[overall], 4)
            tols = [rows[c]["tol"] for c in parts + [overall]]
            worst = round(sum(tols), 4)
            rss = round(math.sqrt(sum(t * t for t in tols)), 4)
            if abs(diff) <= rss:
                status = "CLOSES"
            elif abs(diff) <= worst:
                status = "LOOSE"
            else:
                status = "CLOSURE_FAIL"
            res.update(status=status, sum=round(total, 4), measured=values[overall], diff=diff, rss=rss, worst=worst,
                       detail=f"sum {total:g} vs {overall} {values[overall]:g}, off by {diff:+g} (rss {rss:g}, worst {worst:g})")
        chains.append(res)

    flags = [(c, f) for c in order for f in rows[c]["flags"]]
    blocking = [x for x in flags if x[1].split(":")[0] in ("REMEASURE", "TOOL_TOO_COARSE", "FEW_READINGS", "NON_POSITIVE")
                and rows[x[0]]["role"] == "mating"]
    blocking += [("chain", ch["name"]) for ch in chains if ch["status"] == "CLOSURE_FAIL"]
    tbd_mating = [x for x in flags if x[1].startswith(("TBD_ON_MATING", "DERIVED_TBD")) and rows[x[0]]["role"] == "mating"]
    if blocking:
        verdict = "MEASURE_AGAIN"
    elif tbd_mating:
        verdict = "DRAFT_ONLY"
    else:
        verdict = "READY"
    return {"part": data.get("part") or {}, "rows": [rows[c] for c in order], "values": values,
            "chains": chains, "verdict": verdict, "flag_count": len(flags)}


# ---------------------------------------------------------------- text output
def fmt(v):
    return "[TBD]" if v is None else f"{v:g}"


def report(res):
    p = res["part"]
    out = [f"PART {p.get('id', 'PART-001')}  {p.get('name', '')}".rstrip(),
           f"units {p.get('units', 'mm')}  purpose {p.get('purpose', 'document')}", ""]
    for r in res["rows"]:
        line = f"{r['code']:<5} {fmt(r['value']):>9}  ±{r['tol']:g}  {r['role']:<9} {r['kind']:<8} {r['name']}"
        if r["kind"] == "derived":
            line += f"  = {r['formula']}"
        out.append(line)
        for f in r["flags"]:
            out.append(f"      ! {f}")
        for h in r["hints"]:
            out.append(f"      ~ {h}")
    if res["chains"]:
        out.append("")
        for ch in res["chains"]:
            out.append(f"chain {ch['name']}: {ch['status']}  {ch['detail']}")
    out += ["", f"VERDICT {res['verdict']}"]
    return "\n".join(out)


def table_md(res):
    lines = ["| Code | Name | Value | Tol | Role | How |", "|---|---|---|---|---|---|"]
    for r in res["rows"]:
        how = {"measured": f"{r['tool']} ×{len(r['readings'])}", "derived": f"= {r['formula']}", "tbd": "unknown"}[r["kind"]]
        lines.append(f"| {r['code']} | {r['name']} | {fmt(r['value'])} | ±{r['tol']:g} | {r['role']} | {how} |")
    return "\n".join(lines)


# ---------------------------------------------------------------- svg
def pick_scale(L, W, T, paper):
    pw, ph = PAPER[paper]
    usable_w, usable_h = pw - 20 - 95, ph - 20 - 40  # margins, right table column, bottom title block
    need_w, need_h = L + T + 3 * 22, W + T + 3 * 22  # views plus room for dimension lines
    biggest = max(L, W, T)
    for num, den in SCALES:
        if num > den and biggest >= 15:  # enlarge only tiny parts; true scale is the point
            continue
        k = num / den
        if need_w * k <= usable_w and need_h * k <= usable_h:
            return num, den
    raise PartError("part is too big for the paper even at 1:10; choose a larger paper")


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Sheet:
    def __init__(self):
        self.el = []

    def line(self, x1, y1, x2, y2, cls="o"):
        self.el.append(f'<line class="{cls}" x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}"/>')

    def rect(self, x, y, w, h, cls="o"):
        self.el.append(f'<rect class="{cls}" x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}"/>')

    def circle(self, cx, cy, r, cls="o"):
        self.el.append(f'<circle class="{cls}" cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}"/>')

    def text(self, x, y, s, size=2.6, anchor="middle", rot=None):
        tr = f' transform="rotate({rot} {x:.2f} {y:.2f})"' if rot is not None else ""
        self.el.append(f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size}" text-anchor="{anchor}"{tr}>{esc(s)}</text>')

    def dim_h(self, x1, x2, y_feat, y_dim, label):
        self.line(x1, y_feat, x1, y_dim + (1.2 if y_dim > y_feat else -1.2), "t")
        self.line(x2, y_feat, x2, y_dim + (1.2 if y_dim > y_feat else -1.2), "t")
        self.line(x1, y_dim, x2, y_dim, "d")
        self.text((x1 + x2) / 2, y_dim - 0.8, label)

    def dim_v(self, y1, y2, x_feat, x_dim, label):
        self.line(x_feat, y1, x_dim + (1.2 if x_dim > x_feat else -1.2), y1, "t")
        self.line(x_feat, y2, x_dim + (1.2 if x_dim > x_feat else -1.2), y2, "t")
        self.line(x_dim, y1, x_dim, y2, "d")
        self.text(x_dim - 0.8, (y1 + y2) / 2, label, rot=-90)


def render_svg(data, res, paper=None):
    body = data.get("body") or {}
    for key in ("L", "W", "T"):
        if key not in body:
            raise PartError("svg needs body.L, body.W and body.T codes (the bounding block)")
    v = res["values"]
    L, W, T = (v.get(body[k]) for k in ("L", "W", "T"))
    if None in (L, W, T):
        raise PartError("body size has a TBD; measure L, W and T before drawing")
    paper = paper or (data.get("part") or {}).get("paper", "A4")
    if paper not in PAPER:
        raise PartError(f"paper must be one of {sorted(PAPER)}")
    num, den = pick_scale(L, W, T, paper)
    k = num / den
    pw, ph = PAPER[paper]
    s = Sheet()
    s.rect(5, 5, pw - 10, ph - 10, "o")
    gap = 22
    ox = 10 + gap  # left of top/front views
    top_y = 10 + gap
    front_y = top_y + W * k + gap
    right_x = ox + L * k + gap
    Lk, Wk, Tk = L * k, W * k, T * k
    # third-angle: top above front, right view right of front
    s.rect(ox, top_y, Lk, Wk)
    s.rect(ox, front_y, Lk, Tk)
    s.rect(right_x, front_y, Wk, Tk)
    s.text(ox + Lk / 2, top_y - 13, "TOP", 3)
    s.text(ox + Lk / 2, front_y + Tk + 16, "FRONT", 3)
    s.text(right_x + Wk / 2, front_y + Tk + 16, "RIGHT", 3)
    s.dim_h(ox, ox + Lk, top_y, top_y - 6, f"{body['L']}")
    s.dim_v(top_y, top_y + Wk, ox, ox - 6, f"{body['W']}")
    s.dim_v(front_y, front_y + Tk, ox, ox - 6, f"{body['T']}")
    s.dim_h(right_x, right_x + Wk, front_y + Tk, front_y + Tk + 6, f"{body['W']}")

    stack = 0
    drawn = set()
    for i, f in enumerate(data.get("features") or []):
        kind = f.get("kind")
        get = lambda key: v.get(f.get(key)) if f.get(key) else None
        x, y = get("x"), get("y")
        if kind == "hole":
            d = get("d")
            if None in (x, y, d):
                s.text(ox + Lk / 2, top_y + Wk / 2 + 4 * i, f"{f.get('d', '?')} position TBD", 2.2)
                continue
            depth = T if f.get("through", True) else (get("depth") or T)
            cx, cy, r = ox + x * k, top_y + y * k, d * k / 2
            s.circle(cx, cy, r)
            s.line(cx - r - 1.5, cy, cx + r + 1.5, cy, "c")
            s.line(cx, cy - r - 1.5, cx, cy + r + 1.5, "c")
            s.text(cx + r + 1, cy - r - 0.5, f"⌀{f['d']}" + ("" if f.get("through", True) else f" ↧{f.get('depth', 'TBD')}"), 2.4, "start")
            s.line(cx - r, front_y, cx - r, front_y + depth * k, "h")
            s.line(cx + r, front_y, cx + r, front_y + depth * k, "h")
            ry = right_x + y * k
            s.line(ry - r, front_y, ry - r, front_y + depth * k, "h")
            s.line(ry + r, front_y, ry + r, front_y + depth * k, "h")
            if ("x", f["x"]) not in drawn:
                stack += 1
                s.dim_h(ox, cx, top_y + Wk, top_y + Wk + 4 + 4 * stack, f["x"])
                drawn.add(("x", f["x"]))
            if ("y", f["y"]) not in drawn:
                s.dim_v(top_y, cy, ox + Lk, ox + Lk + 4 + 4 * len([1 for d in drawn if d[0] == "y"]) + 4, f["y"])
                drawn.add(("y", f["y"]))
        elif kind == "slot":
            ln, w = get("len"), get("w")
            if None in (x, y, ln, w):
                continue
            s.rect(ox + x * k, top_y + y * k - w * k / 2, ln * k, w * k)
            s.text(ox + (x + ln / 2) * k, top_y + y * k - w * k / 2 - 1, f"{f['len']} × {f['w']}", 2.4)
        else:
            raise PartError(f"feature {i}: kind must be hole or slot")

    # table column
    tx = pw - 100
    s.line(tx, 5, tx, ph - 5, "o")
    cols = (("CODE", 3, "start"), ("VALUE", 40, "end"), ("TOL", 58, "end"), ("ROLE", 62, "start"))
    for label, dx, anchor in cols:
        s.text(tx + dx, 12, label, 2.6, anchor)
    s.line(tx, 14, pw - 5, 14, "t")
    yy = 19
    for r in res["rows"]:
        if yy > ph - 45:
            s.text(tx + 3, yy, "... more in the dimension table", 2.2, "start")
            break
        cells = (r["code"], fmt(r["value"]), f"±{r['tol']:g}", r["role"])
        for (label, dx, anchor), cell in zip(cols, cells):
            s.text(tx + dx, yy, cell, 2.4, anchor)
        yy += 4
    # title block
    p = res["part"]
    by = ph - 42
    s.line(tx, by, pw - 5, by, "o")
    s.text(tx + 3, by + 6, f"{p.get('id', 'PART-001')}  {p.get('name', '')}", 3, "start")
    s.text(tx + 3, by + 12, f"UNITS {p.get('units', 'mm').upper()}   SCALE {num}:{den}   {paper}", 2.4, "start")
    s.text(tx + 3, by + 17, "THIRD-ANGLE PROJECTION   DO NOT SCALE UNLESS 100% PRINT", 2.0, "start")
    s.text(tx + 3, by + 22, f"VERDICT {res['verdict']}", 2.6, "start")
    # check bar: 50 mm of real length at this scale
    bar = 50 * k
    s.line(tx + 3, by + 28, tx + 3 + bar, by + 28, "o")
    for j in range(6):
        s.line(tx + 3 + bar * j / 5, by + 26.5, tx + 3 + bar * j / 5, by + 29.5, "o")
    s.text(tx + 3, by + 33, f"CHECK BAR = 50 mm real ({bar:g} mm on paper)", 2.0, "start")

    style = ("<style>line,rect,circle{fill:none;stroke:#111}.o{stroke-width:.5}.t{stroke-width:.18}"
             ".d{stroke-width:.25}.c{stroke-width:.18;stroke-dasharray:4 1 1 1}.h{stroke-width:.3;stroke-dasharray:1.5 1}"
             "text{font-family:Helvetica,Arial,sans-serif;fill:#111}</style>")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{pw}mm" height="{ph}mm" viewBox="0 0 {pw} {ph}">'
            f'{style}<rect x="0" y="0" width="{pw}" height="{ph}" fill="#fff" stroke="none"/>' + "".join(s.el) + "</svg>\n")


# ---------------------------------------------------------------- cli
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="statistics, closure, hints and a verdict")
    c.add_argument("file")
    c.add_argument("--json", action="store_true")
    t = sub.add_parser("table", help="markdown dimension table")
    t.add_argument("file")
    g = sub.add_parser("svg", help="true-scale three-view drawing")
    g.add_argument("file")
    g.add_argument("-o", "--out", required=True)
    g.add_argument("--paper", choices=sorted(PAPER))
    a = ap.parse_args(argv)
    try:
        data = load(a.file)
        res = analyse(data)
        if a.cmd == "check":
            print(json.dumps(res, ensure_ascii=False, indent=1) if a.json else report(res))
            return {"READY": 0, "DRAFT_ONLY": 0, "MEASURE_AGAIN": 2}[res["verdict"]]
        if a.cmd == "table":
            print(table_md(res))
            return 0
        svg = render_svg(data, res, a.paper)
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(svg)
        print(f"wrote {a.out} ({res['verdict']})")
        return 0
    except PartError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
