"""C23 — pull concrete corpus instances for #52's three seed rulings. ZERO SPEND.

Deterministic reads of `corpus/mark-schemes/*.json` only. No Gemini, no network.

C23 declined the "only cases that change the mark outcome" narrowing, on the
ground that pre-filtering by mark impact would be the agent exercising the
judgment the ruling exists to capture. So the selection rule here is
**mechanical and stated**, not editorial: within each category, take the first N
by scheme stem in sorted order after de-duplicating identical answer text.
Nothing is ranked by how interesting or how consequential it looked.
"""
import glob
import json
import re

FILES = sorted(glob.glob("corpus/mark-schemes/*.json"))
ECF = re.compile(r"\b(ecf|FT|follow[- ]through)\b", re.I)
OE = re.compile(r"\boe\b")
ANYN = re.compile(r"\b(any\s+(one|two|three|four|1|2|3|4))\b", re.I)


def leaves(q):
    parts = q.get("parts") or []
    if not parts:
        yield q
        return
    for c in parts:
        yield from leaves(c)


rows = {"ecf": [], "oe": [], "list_rule": []}
for f in FILES:
    stem = f.split("/")[-1][:-5]
    try:
        d = json.load(open(f))
    except Exception:
        continue
    for root in d.get("questions", []):
        for lf in leaves(root):
            pts = lf.get("answer_points") or []
            marks = lf.get("marks") or 0
            for ap in pts:
                txt = (ap.get("point") or "").strip()
                rec = {"scheme": stem, "question": lf.get("id"), "tariff": marks,
                       "point_marks": ap.get("marks"), "text": txt}
                if ECF.search(txt):
                    rows["ecf"].append(rec)
                if OE.search(txt):
                    rows["oe"].append(rec)
                m = ANYN.search(txt)
                if m and marks:
                    bullets = txt.count("•")
                    rows["list_rule"].append(
                        rec | {"trigger": m.group(0), "bullets_listed": bullets})


def dedupe(items, key=lambda r: r["text"]):
    seen, out = set(), []
    for r in items:
        k = key(r)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


out = {k: dedupe(v) for k, v in rows.items()}
# list-rule: keep only those that actually list MORE options than the tariff
out["list_rule"] = [r for r in out["list_rule"] if r["bullets_listed"] > r["tariff"]]
summary = {k: {"total_instances": len(rows[k]), "distinct_texts": len(v)} for k, v in out.items()}
payload = {"issue": 52, "ruling": "C23 — cases, not recommendations", "spend_usd": 0.0,
           "summary": summary,
           "cases": {k: v[:5] for k, v in out.items()}}
open("BUILD/accuracy-runs/c23-cases-52-2026-08-28/cases.json", "w").write(
    json.dumps(payload, indent=2) + "\n")
print(json.dumps(summary, indent=2))
for k, v in payload["cases"].items():
    print(f"\n===== {k} =====")
    for r in v:
        print(f"{r['scheme']} {r['question']} tariff={r['tariff']} point_marks={r['point_marks']}"
              + (f" bullets={r.get('bullets_listed')}" if 'bullets_listed' in r else ""))
        print("   ", r["text"][:300].replace("\n", " "))
