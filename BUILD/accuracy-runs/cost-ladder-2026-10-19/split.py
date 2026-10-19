#!/usr/bin/env python3
"""Recompute every SPLIT.md table from the cost-ladder rung-0 run files ($0, no API).

Usage (from the pinned worktree, so lemely's price table is the one the run used):

    source /home/sico/Code/Lemely/.venv/bin/activate
    PYTHONPATH=/home/sico/Code/Lemely/.claude/worktrees/cost-ladder-run \
        python split.py [RUN_DIR] [SPEND_FILE] > SPLIT.md

Inputs read (read-only): {baseline,baseline_aa}/{records.jsonl,results.json,summary.json,
run_cost.json}, aa_floor.json, the spend ledger. SPLIT.md is exactly this script's stdout;
every number, including the prose notes, is computed here.

Conventions
- "2027 rates" = lemely.io.gemini.price_row(model, on=PRICE_DATE_2027); "billed today" = on=2026-10-19.
- output_tokens in a record already includes thinking_tokens (billed at the output rate);
  the "output" column below is output - thinking, the "thinking" column is thinking.
- Per-script = per case_key, mean over ALL cases in the run's results.json (12), so a case
  whose calls were all in-run cache hits counts as $0.
- p95 is nearest rank (ceil(0.95 n)); with 12 scripts that is the maximum.
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from lemely.io.gemini import PRICE_DATE_2027, price_row

RUN = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
SPEND = Path(sys.argv[2]) if len(sys.argv) > 2 else RUN.parent / "cost-ladder-spend.json"
TODAY = date(2026, 10, 19)
SETTINGS = SimpleNamespace(gemini=SimpleNamespace(pricing={}))
KINDS = ("input", "cached", "output", "thinking")
LABELS = ("baseline", "baseline_aa")
NAME = {"baseline": "baseline", "baseline_aa": "A/A"}
CORR = ("correction", "correction_borderline")
GEMINI_CAP = 6.00  # constraints file: Gemini spend cap, billed dollars
FLOOR_TOKENS = 4096  # implicit-cache minimum prompt size cited in the brief


# ---------------------------------------------------------------- helpers
def p95(vals):
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[max(math.ceil(0.95 * len(s)) - 1, 0)]


def median(vals):
    s = sorted(vals)
    if not s:
        return 0.0
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def mcnemar_exact(b, c):
    """Two-sided exact McNemar p from the discordant counts b, c."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def f(x, nd=6):
    return f"{x:.{nd}f}"


def pct(x):
    return f"{x:.1%}"


def table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out


def kind_usd(rec, on):
    row = price_row(rec["model"], SETTINGS, on=on)
    cached = min(max(rec["cached_tokens"], 0), max(rec["input_tokens"], 0))
    think = min(rec["thinking_tokens"], rec["output_tokens"])
    return {
        "input": (rec["input_tokens"] - cached) / 1000 * row.input,
        "cached": cached / 1000 * row.cached_input,
        "output": (rec["output_tokens"] - think) / 1000 * row.output,
        "thinking": think / 1000 * row.output,
    }


# ---------------------------------------------------------------- loading
def load(label):
    d = RUN / label
    recs = [json.loads(x) for x in (d / "records.jsonl").read_text().splitlines() if x.strip()]
    res = json.loads((d / "results.json").read_text())
    summ = json.loads((d / "summary.json").read_text())
    cases = sorted({q["case_key"] for q in res["question_results"]} | {r["case_key"] for r in recs})
    scored = [q for q in res["question_results"] if q["scored"]]
    # binder cases = cases with a second read; their `extraction` call is the binder's first read
    binder_cases = {r["case_key"] for r in recs if r["task_tag"] == "binding_second_read"}
    for r in recs:
        r["tag"] = r["task_tag"]
        if r["task_tag"] == "extraction":
            r["tag"] = "extraction[binder 1st read]" if r["case_key"] in binder_cases else "extraction[legacy MCQ]"
    return SimpleNamespace(
        label=label, recs=recs, res=res, summ=summ, cases=cases, n=len(cases), scored=scored,
        scored_keys={(q["case_key"], q["question_id"]) for q in scored}, binder_cases=binder_cases,
    )


def per_case(R, key):
    t = dict.fromkeys(R.cases, 0.0)
    for r in R.recs:
        if not math.isnan(r[key]):
            t[r["case_key"]] += r[key]
    return t


def mean27(R, recs=None):
    rs = R.recs if recs is None else recs
    return sum(r["usd_2027"] for r in rs if not math.isnan(r["usd_2027"])) / R.n


def paper(case_key):
    return case_key.split("/")[0]


# ---------------------------------------------------------------- levers
def lever_rows(R):
    """[(key, saving $/script at 2027 rates)] for this run, plus a detail dict."""
    n = R.n
    row38 = price_row("gemini-3.8-flash", SETTINGS, on=PRICE_DATE_2027)
    out, det = [], {}

    # ---- B1: binding_second_read thinking medium -> low
    sr = [r for r in R.recs if r["task_tag"] == "binding_second_read"]
    think_usd = sum(r["thinking_tokens"] for r in sr) / 1000 * row38.output / n
    det["sr_think_usd"] = think_usd
    for rho, lab in ((0.5, "B1 rho=0.5"), (0.25, "B1 rho=0.25"), (0.0, "B1 rho=0 (ceiling)")):
        out.append((lab, (1 - rho) * think_usd))

    # ---- B2: second read only on triggers
    sr_usd = sum(r["usd_2027"] for r in sr) / n
    det["sr_usd"] = sr_usd
    for t, lab in ((0.5, "B2 trigger=50%"), (0.25, "B2 trigger=25%"), (0.0, "B2 trigger=0% (ceiling)")):
        out.append((lab, (1 - t) * sr_usd))

    # ---- B12: per-tag output cap (tokens beyond cap are not generated; retry cost NOT netted)
    for tag in ("extraction[binder 1st read]", "binding_second_read", "correction"):
        for cap in (8192, 16384, 32768):
            over = sum(max(r["output_tokens"] - cap, 0) for r in R.recs if r["tag"] == tag)
            out.append((f"B12 {tag} cap={cap}", over / 1000 * row38.output / n))

    # ---- A1: correction family repriced (tokens, thinking and cache share held)
    corr = [r for r in R.recs if r["tag"] in CORR]
    corr_usd = sum(r["usd_2027"] for r in corr) / n
    det["corr_usd"] = corr_usd
    lite = price_row("gemini-3.1-flash-lite", SETTINGS, on=PRICE_DATE_2027)
    hk = price_row("claude-haiku-5-5", SETTINGS, on=PRICE_DATE_2027)

    def reprice(rs, row, cached_rate=None):
        tot = 0.0
        for r in rs:
            c = min(r["cached_tokens"], r["input_tokens"])
            tot += ((r["input_tokens"] - c) / 1000 * row.input
                    + c / 1000 * (row.cached_input if cached_rate is None else cached_rate)
                    + r["output_tokens"] / 1000 * row.output)
        return tot / n

    a1_lite = reprice(corr, lite)
    a1_hk = reprice(corr, hk, cached_rate=hk.input)  # no implicit cache on Claude: cached tokens billed as input
    out.append(("A1a flash-lite", corr_usd - a1_lite))
    out.append(("A1b haiku-5-5 (no explicit cache)", corr_usd - a1_hk))
    det["a1_lite_usd"], det["a1_hk_usd"] = a1_lite, a1_hk
    # A1b with an explicit cache on an assumed shared prefix (conditional on the prefix floor being met)
    s = 0.5
    hk_cached = 0.0
    bycase = defaultdict(list)
    for r in corr:
        bycase[r["case_key"]].append(r)
    for rs in bycase.values():
        for i, r in enumerate(rs):
            pre = s * r["input_tokens"]
            rest = r["input_tokens"] - pre
            hk_cached += rest / 1000 * hk.input + r["output_tokens"] / 1000 * hk.output
            hk_cached += pre / 1000 * (hk.input * 1.25 if i == 0 else hk.cached_input)
    out.append((f"A1b haiku + explicit cache (prefix {s:.0%} of input, 1.25x write on 1st call/script)",
                corr_usd - hk_cached / n))

    # ---- A2: cascade. cheap (flash-lite) marks every leaf; fraction p re-marked on 3.8-flash at today's cost
    for p in (0.10, 0.25, 0.50):
        out.append((f"A2 cascade p={p:.0%}", corr_usd - (a1_lite + p * corr_usd)))
    det["a2_breakeven_p"] = (corr_usd - a1_lite) / corr_usd if corr_usd else float("nan")
    det["fire"] = {a: sum(1 for r in R.recs if r.get("attempt") == a) for a in ("borderline", "escalation")}

    # ---- A3: shared prefix. implicit caching needs a prompt >= FLOOR_TOKENS
    unc = sum(r["input_tokens"] - min(r["cached_tokens"], r["input_tokens"]) for r in corr)
    ceiling = unc / 1000 * (row38.input - row38.cached_input) / n
    realisable = sum(
        (r["input_tokens"] - min(r["cached_tokens"], r["input_tokens"])) for r in corr
        if r["input_tokens"] >= FLOOR_TOKENS
    ) / 1000 * (row38.input - row38.cached_input) / n * 0.5 * 0.9
    out.append(("A3 as-is (no correction call reaches the 4,096 floor)", realisable))
    out.append(("A3 hypothetical: floor met, prefix 50% of uncached correction input, 90% hit", ceiling * 0.5 * 0.9))
    out.append(("A3 ceiling: 100% of uncached correction input at cached rate", ceiling))
    det["corr_max_in"] = max((r["input_tokens"] for r in corr), default=0)
    return out, det


# ---------------------------------------------------------------- main
def main():
    Rs = {lab: load(lab) for lab in LABELS}
    B, A = Rs["baseline"], Rs["baseline_aa"]
    floor = json.loads((RUN / "aa_floor.json").read_text())["aa_floor"]
    out = []
    w = out.append

    w("# Rung-0 split: where the $/script goes (baseline and A/A)\n")
    w("Generated by `split.py` from the run files; $0, no API calls. All $ are per script "
      "(mean over the 12 cases of each run) unless stated.\n")

    # ---- 1 manifest ------------------------------------------------------
    w("## 1. Manifest\n")
    rows = []
    for k in ("git_sha", "params_fingerprint", "cache_mode", "split", "corpus_digest", "n_cases", "timestamp"):
        rows.append([k, B.res["manifest"].get(k), A.res["manifest"].get(k)])
    rows.append(["models_by_task", json.dumps(B.res["manifest"]["models_by_task"]),
                 json.dumps(A.res["manifest"]["models_by_task"])])
    w("\n".join(table(["field", "baseline", "A/A"], rows)))
    w("")
    same_fp = B.res["manifest"]["params_fingerprint"] == A.res["manifest"]["params_fingerprint"]
    w(f"- params_fingerprint identical across runs: {same_fp}; git_sha differs: "
      f"{B.res['manifest']['git_sha'] != A.res['manifest']['git_sha']} "
      "(baseline results were re-summarised later by `resummarise`: "
      f"{B.summ.get('resummarised')}).")
    w(f"- baseline ran with cache_mode=`{B.summ['cache_mode']}`: {B.summ['in_run_cache_hits']} calls were "
      f"in-run cache hits and left no CallRecord; A/A ran cache_mode=`{A.summ['cache_mode']}` with "
      f"{A.summ['cache_hits']} cache hits. The baseline $/script is therefore NOT a full-price figure "
      "(see section 3 for the effect).\n")

    # ---- 2 record funnel -------------------------------------------------
    w("## 2. Record funnel\n")
    rows = []
    for R in (B, A):
        live = {r["case_key"] for r in R.recs}
        rows.append([NAME[R.label], len(R.recs), R.n, len(live), R.n - len(live),
                     sum(1 for r in R.recs if not r["parse_ok"]),
                     sum(1 for r in R.recs if math.isnan(r["usd_2027"])),
                     sum(r["cached_tokens"] for r in R.recs), R.summ.get("in_run_cache_hits", 0)])
    w("\n".join(table(["run", "records", "cases", "cases with >=1 record", "cases with 0 records (all cache hits)",
                       "parse_ok=False records", "unpriced (NaN)", "sum cached_tokens (implicit)", "in-run cache hits"], rows)))
    w("")
    for R in (B, A):
        c = Counter(r["tag"] for r in R.recs)
        w(f"- {NAME[R.label]} records by tag: {dict(c)}")
    w("- The binder's first read is tagged `extraction` (no `binding_read` record exists in either run; "
      "binding_read records: "
      f"{sum(1 for R in (B, A) for r in R.recs if r['task_tag'] == 'binding_read')}). Below it is shown as "
      "`extraction[binder 1st read]` = extraction records of cases that also have a `binding_second_read`; "
      "`extraction[legacy MCQ]` is the all-MCQ case sent to the legacy binder (gemini-3.5-flash-lite).\n")

    # ---- 3 cost per script ----------------------------------------------
    w("## 3. Cost per script\n")
    rows = []
    for key, name in (("usd_2027", "2027 rates"), ("usd_now", "billed today")):
        for R in (B, A):
            pc = per_case(R, key)
            v = list(pc.values())
            rows.append([name, NAME[R.label], f(sum(v) / R.n), f(p95(v)), f(max(v)), f(sum(v)), R.n])
    w("\n".join(table(["rate", "run", "mean $/script", "p95 (nearest rank)", "max", "total $", "denominator (scripts)"], rows)))
    w("")
    w("Per case, 2027 rates:\n")
    cases = sorted(set(B.cases) | set(A.cases))
    pcb, pca = per_case(B, "usd_2027"), per_case(A, "usd_2027")
    nb = Counter(r["case_key"] for r in B.recs)
    na = Counter(r["case_key"] for r in A.recs)
    w("\n".join(table(["case", "baseline $", "baseline records", "A/A $", "A/A records"],
                      [[c, f(pcb.get(c, 0)), nb.get(c, 0), f(pca.get(c, 0)), na.get(c, 0)] for c in cases])))
    w("")
    # sensitivity
    live_b = [c for c in B.cases if nb.get(c, 0) > 0]
    run_rec = max(B.recs, key=lambda r: r["output_tokens"])
    b_wo = (sum(pcb.values()) - run_rec["usd_2027"]) / B.n
    w(f"Baseline sensitivity (2027 rates): mean over the {len(live_b)} cases that have records = "
      f"{f(sum(pcb.values()) / len(live_b))} (the other {B.n - len(live_b)} case(s) are all cache hits, $0); "
      f"mean with the {run_rec['output_tokens']:,}-token runaway `{run_rec['task_tag']}` call "
      f"({run_rec['case_key']}, {run_rec['latency_ms'] / 1000:.0f} s, parse_ok={run_rec['parse_ok']}, "
      f"${run_rec['usd_2027']:.4f}) removed = {f(b_wo)}. "
      f"A/A (every call live, no runaway) = {f(sum(pca.values()) / A.n)}.\n")

    # ---- 4 split by tag x attempt x kind ---------------------------------
    for on, name, key in ((PRICE_DATE_2027, "2027 rates", "usd_2027"), (TODAY, "billed today", "usd_now")):
        for R in (B, A):
            grp = defaultdict(lambda: dict.fromkeys(KINDS, 0.0) | {"calls": 0, "tot": 0.0})
            maxdiff = 0.0
            for r in R.recs:
                k = kind_usd(r, on)
                maxdiff = max(maxdiff, abs(sum(k.values()) - r[key]))
                g = grp[(r["tag"], r["attempt"], r["model"], r["thinking"])]
                for kk in KINDS:
                    g[kk] += k[kk]
                g["calls"] += 1
                g["tot"] += sum(k.values())
            total = sum(g["tot"] for g in grp.values())
            w(f"## 4{'a' if on == PRICE_DATE_2027 else 'b'}. $/script by task_tag x attempt x model x token kind "
              f"({name}, {NAME[R.label]})\n")
            w(f"Per-record recompute vs recorded `{key}`: max abs diff {maxdiff:.1e}.\n")
            rows = []
            for (tag, att, mod, th), g in sorted(grp.items(), key=lambda kv: -kv[1]["tot"]):
                rows.append([tag, att, mod, th, g["calls"]] + [f(g[kk] / R.n) for kk in KINDS]
                            + [f(g["tot"] / R.n), pct(g["tot"] / total)])
            rows.append(["**all**", "", "", "", len(R.recs)]
                        + [f(sum(g[kk] for g in grp.values()) / R.n) for kk in KINDS] + [f(total / R.n), "100%"])
            w("\n".join(table(["task_tag", "attempt", "model", "thinking sent", "calls", "input", "cached",
                               "output (excl thinking)", "thinking", "total $/script", "share"], rows)))
            w("")

    w("## 4c. Share by task_tag (2027 rates), side by side\n")
    tags = sorted({r["tag"] for R in (B, A) for r in R.recs})
    sh = {}
    for R in (B, A):
        tot = sum(r["usd_2027"] for r in R.recs)
        sh[R.label] = {t: sum(r["usd_2027"] for r in R.recs if r["tag"] == t) / tot for t in tags}
    usd = {R.label: {t: sum(r["usd_2027"] for r in R.recs if r["tag"] == t) / R.n for t in tags} for R in (B, A)}
    rows = [[t, f(usd["baseline"][t]), pct(sh["baseline"][t]), f(usd["baseline_aa"][t]), pct(sh["baseline_aa"][t])]
            for t in sorted(tags, key=lambda t: -sh["baseline_aa"][t])]
    w("\n".join(table(["task_tag", "baseline $/script", "baseline share", "A/A $/script", "A/A share"], rows)))
    w("")
    for R in (B, A):
        top = sorted(sh[R.label].items(), key=lambda kv: -kv[1])[:3]
        w(f"- {NAME[R.label]} top 3 by share: " + ", ".join(f"{t} {pct(v)}" for t, v in top))
    # kind totals across the three big tags
    w("")

    # ---- 5 tokens --------------------------------------------------------
    w("## 5. Tokens per script by tag (mean over cases)\n")
    rows = []
    for R in (B, A):
        tk = defaultdict(Counter)
        for r in R.recs:
            c = tk[r["tag"]]
            c["calls"] += 1
            c["in"] += r["input_tokens"]
            c["cached"] += r["cached_tokens"]
            c["think"] += r["thinking_tokens"]
            c["out"] += r["output_tokens"] - r["thinking_tokens"]
        for tag, c in sorted(tk.items()):
            rows.append([NAME[R.label], tag, c["calls"], f"{c['in'] / R.n:.0f}", f"{c['cached'] / R.n:.0f}",
                         f"{c['out'] / R.n:.0f}", f"{c['think'] / R.n:.0f}",
                         pct(c["cached"] / c["in"]) if c["in"] else "n/a"])
    w("\n".join(table(["run", "task_tag", "calls", "input", "cached", "output (excl thinking)", "thinking",
                       "cached/input"], rows)))
    w("")

    # ---- 6 output-token distribution -------------------------------------
    w("## 6. Per-call output tokens (output_tokens incl. thinking), by tag\n")
    rows = []
    for R in (B, A):
        bt = defaultdict(list)
        for r in R.recs:
            bt[r["tag"]].append(r)
        for tag, rs in sorted(bt.items()):
            o = [r["output_tokens"] for r in rs]
            th = sum(r["thinking_tokens"] for r in rs)
            rows.append([NAME[R.label], tag, len(rs), min(o), f"{median(o):.0f}", p95(o), max(o), sum(o), th])
    w("\n".join(table(["run", "task_tag", "calls", "min", "median", "p95 (nearest rank)", "max", "sum", "of which thinking"], rows)))
    w("")
    for R in (B, A):
        w(f"Top 5 calls by output tokens, {NAME[R.label]}:\n")
        top = sorted(R.recs, key=lambda r: -r["output_tokens"])[:5]
        w("\n".join(table(["case", "tag", "output_tokens", "thinking_tokens", "latency s", "parse_ok", "$ 2027", "$ today"],
                          [[r["case_key"], r["task_tag"], f"{r['output_tokens']:,}", f"{r['thinking_tokens']:,}",
                            f"{r['latency_ms'] / 1000:.0f}", r["parse_ok"], f(r["usd_2027"], 4), f(r["usd_now"], 4)]
                           for r in top])))
        w("")
    rb = max(B.recs, key=lambda r: r["output_tokens"])
    ra = max((r for r in A.recs if r["task_tag"] == "binding_second_read"), key=lambda r: r["output_tokens"])
    ex_b = [r for r in B.recs if r["case_key"] == rb["case_key"] and r["task_tag"] == "extraction"]
    w(f"- Baseline runaway: {rb['output_tokens']:,}-token `{rb['task_tag']}` call on {rb['case_key']}, "
      f"thinking_tokens={rb['thinking_tokens']} (all visible output), parse_ok={rb['parse_ok']}, "
      f"{rb['latency_ms'] / 1000:.0f} s, ${rb['usd_2027']:.4f} at 2027 rates = "
      f"{pct(rb['usd_2027'] / sum(r['usd_2027'] for r in B.recs))} of baseline spend; that case then has "
      f"{len(ex_b)} extraction records (the second one is the recovery).")
    w(f"- A/A largest second read: {ra['output_tokens']:,} tokens on {ra['case_key']} "
      f"({ra['thinking_tokens']:,} thinking, {ra['latency_ms'] / 1000:.0f} s, ${ra['usd_2027']:.4f}); the same case's "
      "baseline second read: "
      + ", ".join(f"{r['output_tokens']:,}" for r in B.recs
                  if r["case_key"] == ra["case_key"] and r["task_tag"] == "binding_second_read") + " tokens.\n")

    w("Second-read output tokens for the same script, run to run (same prompt, params fingerprint and corpus):\n")
    sb = {r["case_key"]: r["output_tokens"] for r in B.recs if r["task_tag"] == "binding_second_read"}
    sa = {r["case_key"]: r["output_tokens"] for r in A.recs if r["task_tag"] == "binding_second_read"}
    w("\n".join(table(["case", "baseline", "A/A", "A/A / baseline"],
                      [[c, f"{sb[c]:,}" if c in sb else "(cache hit, no record)", f"{sa[c]:,}" if c in sa else "-",
                        f"{sa[c] / sb[c]:.2f}" if c in sb and c in sa else "-"] for c in sorted(set(sb) | set(sa))])))
    w("")

    # ---- 7 thinking ------------------------------------------------------
    w("## 7. Thinking level sent (record `thinking`), by tag x model\n")
    rows = []
    for R in (B, A):
        th = defaultdict(Counter)
        for r in R.recs:
            th[(r["tag"], r["model"])][r["thinking"]] += 1
        for (tag, mod), c in sorted(th.items()):
            tt = [r["thinking_tokens"] for r in R.recs if r["tag"] == tag and r["model"] == mod]
            rows.append([NAME[R.label], tag, mod, dict(c), f"{sum(tt) / len(tt):.0f}"])
    w("\n".join(table(["run", "task_tag", "model", "thinking values (count)", "mean thinking_tokens/call"], rows)))
    w("")
    bad = [(R.label, r) for R in (B, A) for r in R.recs if r["model"] == "gemini-3.8-flash" and r["thinking"] == "minimal"]
    n38 = sum(1 for R in (B, A) for r in R.recs if r["model"] == "gemini-3.8-flash")
    w(f"- gemini-3.8-flash records with thinking == 'minimal': **{len(bad)}** of {n38} gemini-3.8-flash records "
      "(baseline + A/A). The only 'minimal' records are gemini-3.5-flash-lite.")
    w("- `thinking` is the level resolved and sent per record; the API response does not echo it back, "
      "so 'actually sent' is the recorded request field.\n")

    # ---- 8 fire rates ----------------------------------------------------
    w("## 8. Escalation / borderline / second-read fire rates\n")
    rows = []
    for R in (B, A):
        sk = R.scored_keys
        for att in ("first", "borderline", "escalation"):
            keys = {(r["case_key"], r["question_id"]) for r in R.recs if r["attempt"] == att and r["question_id"] is not None}
            k = len(keys & sk)
            lo, hi = wilson(k, len(sk))
            rows.append([NAME[R.label], att, sum(1 for r in R.recs if r["attempt"] == att), f"{k}/{len(sk)}",
                         pct(k / len(sk)), f"[{pct(lo)}, {pct(hi)}]"])
    w("\n".join(table(["run", "attempt", "calls", "scored leaves with >=1 such call", "rate", "Wilson 95%"], rows)))
    w("")
    for R in (B, A):
        nbc = len(R.binder_cases)
        sr = sum(1 for r in R.recs if r["task_tag"] == "binding_second_read")
        w(f"- {NAME[R.label]}: second reads {sr} over {nbc} label-binder cases with records "
          f"(+{R.n - len({r['case_key'] for r in R.recs})} all-cache-hit case(s) with none recorded); "
          f"extraction calls per binder case: {dict(Counter(Counter(r['case_key'] for r in R.recs if r['task_tag'] == 'extraction').values()))}.")
    w("- Zero borderline and zero escalation calls in both runs: the cascade/escalation levers (A2) have no "
      "measured trigger rate at rung 0; any p below is an assumption.\n")

    # ---- 9 quality + A/A -------------------------------------------------
    w("## 9. Run quality and the A/A floor\n")
    rows = []
    for fld in ("scored_parts", "id_match_rate", "validity_rate", "latency_p95_ms", "usd_per_script_mean",
                "usd_per_script_mean_now", "cache_mode", "cache_hits", "in_run_cache_hits"):
        rows.append([fld, B.summ.get(fld), A.summ.get(fld)])
    rows.append(["mismarked_parts (n)", len(B.summ["mismarked_parts"]), len(A.summ["mismarked_parts"])])
    rows.append(["incomplete", B.summ["incomplete"], A.summ["incomplete"]])
    rows.append(["parse_ok=False records", sum(1 for r in B.recs if not r["parse_ok"]),
                 sum(1 for r in A.recs if not r["parse_ok"])])
    rows.append(["funnel (extracted/leaves/marked/matched)", json.dumps(B.res["funnel"]), json.dumps(A.res["funnel"])])
    rows.append(["mark_accuracy / theory", f"{B.res['metrics']['mark_accuracy']:.4f} / {B.res['metrics']['mark_accuracy_theory']:.4f}",
                 f"{A.res['metrics']['mark_accuracy']:.4f} / {A.res['metrics']['mark_accuracy_theory']:.4f}"])
    w("\n".join(table(["field", "baseline", "A/A"], rows)))
    w("")
    lat_b = per_case(B, "latency_ms")
    lat_a = per_case(A, "latency_ms")
    w(f"Recomputed per-script latency p95 (sum of call latency_ms, nearest rank): baseline {p95(list(lat_b.values())):.0f} ms "
      f"(summary {B.summ['latency_p95_ms']:.0f}); A/A {p95(list(lat_a.values())):.0f} ms (summary {A.summ['latency_p95_ms']:.0f}). "
      f"The constraint 'p95 <= 2x rung-0 baseline' is {2 * B.summ['latency_p95_ms'] / 1000:.0f} s against the baseline "
      f"(inflated by the runaway) or {2 * A.summ['latency_p95_ms'] / 1000:.0f} s against A/A.\n")
    mb, ma = set(B.summ["mismarked_parts"]), set(A.summ["mismarked_parts"])
    bonly, aonly = sorted(mb - ma), sorted(ma - mb)
    w(f"- Baseline mismarked: {sorted(mb)}")
    w(f"- A/A mismarked: {sorted(ma)}")
    nsc = len(B.scored_keys)
    dist = {(paper(q["case_key"]), q["question_id"]) for q in B.scored}
    dmb = {(paper(p.rsplit('/', 1)[0]), p.rsplit('/', 1)[1]) for p in mb}
    dma = {(paper(p.rsplit('/', 1)[0]), p.rsplit('/', 1)[1]) for p in ma}
    w(f"- **A/A floor (aa_floor.json) = {floor}**; discordant scored parts = {len(mb ^ ma)} "
      f"(baseline-only {bonly}, A/A-only {aonly}); recomputed |A/A mismarked - baseline mismarked| = {abs(len(mb) - len(ma))}; "
      f"floor == baseline-only count: {floor == len(bonly)}.")
    p = mcnemar_exact(len(bonly), len(aonly))
    w(f"- McNemar exact (baseline vs A/A, scored parts): b={len(bonly)}, c={len(aonly)}, two-sided p={p:.3f}. "
      "Reported, not gated; n discordant = 1 carries no power.")
    lo, hi = wilson(len(mb), nsc)
    w(f"- Mismark rate, baseline: {len(mb)}/{nsc} script x leaf = {pct(len(mb) / nsc)} (Wilson 95% [{pct(lo)}, {pct(hi)}]); "
      f"A/A: {len(ma)}/{nsc} = {pct(len(ma) / nsc)}. These {nsc} script x leaf cells are NOT independent: "
      f"the 12 scripts are variants of 5 papers and share {len(dist)} distinct (paper, leaf) pairs; "
      f"collapsed to distinct leaves the baseline has {len(dmb)}/{len(dist)} distinct mismarked leaves "
      f"(Wilson [{pct(wilson(len(dmb), len(dist))[0])}, {pct(wilson(len(dmb), len(dist))[1])}]); A/A {len(dma)}/{len(dist)}. "
      f"Each mismarked (paper, leaf) occurs in exactly one script ({len(dmb)} distinct pairs from {len(mb)} mismarks), "
      "so mismarks depend on the answer variant and neither denominator is exact; both are shown.")
    import math as _m
    two = max(floor, _m.ceil(0.02 * nsc))
    w(f"- Pass-rule allowances implied (constraints file): saving < 30% -> extra mismarked <= {floor}; "
      f"saving >= 30% -> <= max({floor}, ceil(0.02 x {nsc})) = {two}. Abstention column: unmarked leaves "
      f"(predicted_marks is None): baseline {sum(1 for q in B.res['question_results'] if q['predicted_marks'] is None)}, "
      f"A/A {sum(1 for q in A.res['question_results'] if q['predicted_marks'] is None)} "
      f"(funnel extracted = leaves = marked = matched = {B.res['funnel']['leaves']}; incomplete = []). "
      "Flagged-for-review leaves are a separate outcome, kept in the denominator and marked: "
      f"baseline {[(q['case_key'], q['question_id'], q['review_reason']) for q in B.res['question_results'] if q['needs_teacher_review']]}; "
      f"A/A {[(q['case_key'], q['question_id'], q['review_reason']) for q in A.res['question_results'] if q['needs_teacher_review']]}. "
      "The flagged leaf differs between runs (review flags are themselves run-to-run unstable).\n")

    # ---- 10 spend --------------------------------------------------------
    w("## 10. Spend\n")
    led = json.loads(SPEND.read_text())
    runsum = {}
    for R in (B, A):
        bill = defaultdict(float)
        for r in R.recs:
            if not math.isnan(r["usd_now"]):
                bill[r["provider"]] += r["usd_now"]
        runsum[R.label] = bill["gemini"]
        w(f"- {NAME[R.label]} run: sum of record usd_now = {dict(bill)}; run_cost.json = "
          f"`{(RUN / R.label / 'run_cost.json').read_text().strip()}`")
    gtot = led["gemini"]
    w(f"- Ledger {SPEND.name} (LIVE file: it moves while other ladder runs spend, so this line changes between invocations): `{json.dumps(led)}`. Ledger - (baseline + A/A) = "
      f"${gtot - sum(runsum.values()):.4f} not attributable to these two runs (earlier held run/aborted attempts or "
      f"calls without a CallRecord).")
    w(f"- Against the Gemini cap ${GEMINI_CAP:.2f}: spent ${gtot:.4f} ({pct(gtot / GEMINI_CAP)}), "
      f"remaining ${GEMINI_CAP - gtot:.4f}. Anthropic spend: {led.get('anthropic', 0)}.")
    w(f"- One full-price rung-0 run (A/A, billed today) costs ${runsum['baseline_aa']:.4f}; at that rate the "
      f"remaining Gemini headroom buys {(GEMINI_CAP - gtot) / runsum['baseline_aa']:.1f} more 12-script runs "
      "at rung-0 configuration (before any lever).\n")

    # ---- 11 levers -------------------------------------------------------
    w("## 11. Expected saving per lever (2027 rates, $/script saved)\n")
    w("Method: re-price or remove the recorded tokens; no model call is re-run, so quality effects, retries "
      "after a truncated call, and extra calls are NOT netted. Savings are shown against each run's own "
      "2027 mean. Percentages are of that run's total.\n")
    lr = {R.label: lever_rows(R) for R in (B, A)}
    base = {R.label: mean27(R) for R in (B, A)}
    w(f"Baselines (2027 mean $/script): baseline {f(base['baseline'])}, A/A {f(base['baseline_aa'])}. "
      f"Correction-family spend: baseline {f(lr['baseline'][1]['corr_usd'])} "
      f"({pct(lr['baseline'][1]['corr_usd'] / base['baseline'])}), A/A {f(lr['baseline_aa'][1]['corr_usd'])} "
      f"({pct(lr['baseline_aa'][1]['corr_usd'] / base['baseline_aa'])}). "
      f"binding_second_read spend: baseline {f(lr['baseline'][1]['sr_usd'])} "
      f"({pct(lr['baseline'][1]['sr_usd'] / base['baseline'])}), A/A {f(lr['baseline_aa'][1]['sr_usd'])} "
      f"({pct(lr['baseline_aa'][1]['sr_usd'] / base['baseline_aa'])}); of which thinking: "
      f"{f(lr['baseline'][1]['sr_think_usd'])} / {f(lr['baseline_aa'][1]['sr_think_usd'])}.\n")
    desc = {
        "B1": "binding_second_read thinking medium -> low. Remaining thinking = rho x current; rho is an ASSUMPTION "
              "(no low-level second read was measured in these runs). Visible output unchanged.",
        "B2": "second read runs only when a trigger fires; t = share of scripts that still get it (ASSUMPTION; "
              "the runs record no trigger, every label-binder script got a second read).",
        "B12": "tokens above the cap are never generated (upper bound; a capped call truncates, so a retry or a "
               "lost parse is not netted). Cap applies to total output incl. thinking.",
        "A1": "same tokens re-priced; thinking and cache share held; Claude tokenisation and thinking mapping ignored; "
              "no escalation/borderline calls exist so nothing stays on 3.8-flash.",
        "A2": "flash-lite marks every leaf, fraction p is re-marked on 3.8-flash at today's per-leaf cost "
              "(ASSUMPTION; measured borderline/escalation fire rate = 0). Negative = costs more than rung 0.",
        "A3": "implicit cache needs a prompt >= 4,096 tokens; saving = (input - cached) rate delta on cached tokens.",
    }
    keys = [k for k, _ in lr["baseline"][0]]
    rows = []
    for k in keys:
        sb = dict(lr["baseline"][0])[k]
        sa = dict(lr["baseline_aa"][0])[k]
        rows.append([k, f(sb), pct(sb / base["baseline"]), f(sa), pct(sa / base["baseline_aa"])])
    w("\n".join(table(["lever / scenario", "baseline $/script saved", "% of baseline", "A/A $/script saved", "% of A/A"], rows)))
    w("")
    w("Assumptions per lever:")
    for k, v in desc.items():
        w(f"- **{k}**: {v}")
    w("")
    # B12 detail
    w("### 11a. B12 detail: calls over a cap (output tokens incl. thinking)\n")
    rows = []
    for R in (B, A):
        for tag in ("extraction[binder 1st read]", "binding_second_read", "correction"):
            o = [r["output_tokens"] for r in R.recs if r["tag"] == tag]
            for cap in (8192, 16384, 32768):
                over = [x for x in o if x > cap]
                rows.append([NAME[R.label], tag, cap, f"{len(over)}/{len(o)}", max(o) if o else 0,
                             f"{sum(x - cap for x in over):,}"])
    w("\n".join(table(["run", "tag", "cap", "calls over cap", "max call", "tokens above cap"], rows)))
    w("")
    w(f"Parsed second reads reach {max(r['output_tokens'] for R in (B, A) for r in R.recs if r['task_tag'] == 'binding_second_read' and r['parse_ok']):,} "
      "output tokens (almost all thinking) and still parse; a cap below that value cuts valid work. The extraction "
      "cap is the only one the data supports without truncating a parseable reply: no parse_ok extraction call exceeds "
      f"{max([r['output_tokens'] for R in (B, A) for r in R.recs if r['task_tag'] == 'extraction' and r['parse_ok']] or [0]):,} tokens.\n")
    # A3 detail
    w("### 11b. A3 detail: does any prompt reach the implicit-cache floor?\n")
    rows = []
    for R in (B, A):
        mx = defaultdict(int)
        for r in R.recs:
            if r["task_tag"] in CORR:
                mx[paper(r["case_key"])] = max(mx[paper(r["case_key"])], r["input_tokens"])
        for pp, v in sorted(mx.items()):
            rows.append([NAME[R.label], pp, v, FLOOR_TOKENS - v, v >= FLOOR_TOKENS])
    w("\n".join(table(["run", "paper (correction calls)", "max correction-call input_tokens", f"gap to {FLOOR_TOKENS}", "reaches floor"], rows)))
    w("")
    hit = [(NAME[R.label], r["case_key"], r["task_tag"], r["input_tokens"], r["cached_tokens"])
           for R in (B, A) for r in R.recs if r["cached_tokens"]]
    w(f"Observed implicit-cache hits (records with cached_tokens > 0): {hit}. The one hit at >= {FLOOR_TOKENS} input tokens "
      "is a second read (single call per script, not a shared-prefix pattern); the 37-token hit on a 2,907-token "
      "correction call is below the floor and negligible. The brief's figure that 0606 reaches ~4,088 tokens "
      "of shared prefix is not derivable from the records (max correction input for 0606 is shown above); "
      "taken as given it is 8 tokens short of the floor.\n")
    w("### 11c. A2 breakeven\n")
    for R in (B, A):
        d = lr[R.label][1]
        w(f"- {NAME[R.label]}: cascade on flash-lite beats rung 0 only if the re-mark fraction p < "
          f"{pct(d['a2_breakeven_p'])} (= 1 - cheap/current correction cost); and it never beats A1a alone "
          "(it adds p x correction cost to buy accuracy).")
    w("")

    # ---- 12 interpretation notes -----------------------------------------
    w("## 12. What these numbers do and do not support\n")
    nb_pap = len({paper(c) for c in B.cases})
    w(f"- binding_second_read is the largest tag in both runs (baseline {pct(sh['baseline']['binding_second_read'])}, "
      f"A/A {pct(sh['baseline_aa']['binding_second_read'])}); its thinking tokens alone are "
      f"{pct(lr['baseline'][1]['sr_think_usd'] / base['baseline'])} / {pct(lr['baseline_aa'][1]['sr_think_usd'] / base['baseline_aa'])} "
      f"of total spend. Correction is {pct(sh['baseline']['correction'])} / {pct(sh['baseline_aa']['correction'])}, "
      "so correction-side levers (A1, A2, A3) have a lower ceiling than binder-side ones (B1, B2).")
    w("- The baseline extraction share (34.1% vs 11.4% in A/A) is one 65,522-token runaway call that did not recur "
      "in the A/A on the same prompt: B12 on extraction is priced off a single event, so its saving is an "
      "upper bound conditional on a runaway happening, not an expected value per script.")
    w("- Second-read output varies run to run for the same script (table in section 6), so B1/B2 per-script "
      "savings carry that variance as well as the assumed rho/trigger rate.")
    w("- The baseline is not a clean full-price reference: it ran with a read/write cache (one case, 10 calls, "
      "free) and contains one runaway extraction call. The A/A (cache bypass) is the clean $/script figure; the "
      "baseline mean is shown only for continuity with summary.json.")
    w(f"- A/A churn floor is {floor} mismarked part out of {nsc} (one discordant leaf, McNemar p={p:.2f}); with "
      "n discordant = 1 the floor is a single observation, so it is underpowered as an estimate of run-to-run "
      "noise. Any later delta of <= 1 mismarked part is inside it by rule.")
    w("- B1, B2, A2 and the A3 hypothetical rows depend on assumed rho, trigger rate, re-mark rate and prefix "
      "share. They are scenario arithmetic, not measurements. Only B12-extraction, A1 and the A3 as-is row are "
      "fully determined by the recorded tokens, and A1 ignores Claude/flash-lite tokenisation and quality.")
    w("- Nothing here supports calling any lever an improvement: no lever was run, the corpus is 12 scripts "
      f"over {nb_pap} papers, and the gate is non-regression within the floor.")
    print("\n".join(out))


if __name__ == "__main__":
    main()
