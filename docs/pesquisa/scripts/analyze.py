"""Análises da Etapa 0 sobre o COTAHIST filtrado (stdlib). Descartável."""
import csv
import statistics as st
import sys
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

B = Path(sys.argv[1])
TASK = sys.argv[2]


def rows():
    with open(B / "cotahist2026_filtered.csv", newline="") as f:
        yield from csv.DictReader(f)


def d(s):
    return date(int(s[:4]), int(s[4:6]), int(s[6:]))


def q(xs, ps=(0.1, 0.25, 0.5, 0.75, 0.9)):
    xs = sorted(xs)
    if not xs:
        return {}
    return {p: xs[min(len(xs) - 1, int(p * len(xs)))] for p in ps}


if TASK == "qa13":
    sys.path.insert(0, str(Path(__file__).parent))
    from validate_ohlc import load_trades, ohlc, r4

    off = {r["data"]: r for r in rows() if r["codneg"] == "PETR4" and r["tpmerc"] == "010"}
    ok = 0
    files = sorted(B.glob("PETR4_2026-11-*.zip"))
    for f in files:
        dd = f.stem.split("_")[1].replace("-", "")
        o = off.get(dd)
        tr = load_trades(f)
        if o is None:
            print(dd, "sem pregão oficial; linhas:", len(tr))
            continue
        got = ohlc(r4(tr))
        ref = dict(n=int(o["totneg"]), o=Decimal(o["preabe"]), h=Decimal(o["premax"]), l=Decimal(o["premin"]),
                   c=Decimal(o["preult"]), q=int(o["quatot"]), vwap=Decimal(o["premed"]))
        diff = [k for k in ref if (abs(got[k] - ref[k]) > Decimal("0.01") if k == "vwap" else got[k] != ref[k])]
        ok += not diff
        excl = Counter((r["DataNegocio"] == r["DataReferencia"], r["AcaoAtualizacao"], r["TipoSessaoPregao"]) for r in tr)
        print(dd, "OK" if not diff else diff, f"n={got['n']} O={got['o']} H={got['h']} L={got['l']} C={got['c']}", dict(excl))
    print(f"R4 confere em {ok}/{len(files) - 1} pregões")

elif TASK == "top":
    by = Counter()
    name = {}
    for r in rows():
        if r["tpmerc"] in ("070", "080") and r["data"] >= "20260819":
            by[r["codisi"]] += int(r["totneg"])
        elif r["tpmerc"] == "010" and r["codbdi"] == "02":
            name[r["codisi"]] = r["codneg"]
    for isin, n in by.most_common(15):
        print(isin, name.get(isin, "?"), n)

elif TASK == "liq":
    # Distribuição de negócios por série-dia e volume de requisições (QA-06, PRD-NF-04), últimos 63 pregões
    targets = sys.argv[3].split(",")
    days = sorted({r["data"] for r in rows() if r["codneg"] == "PETR4" and r["tpmerc"] == "010"})
    win = set(days[-63:])
    spot = {}
    opt = defaultdict(list)
    for r in rows():
        if r["data"] not in win:
            continue
        if r["tpmerc"] == "010" and r["codneg"] in targets:
            spot[(r["codisi"], r["data"])] = (r["codneg"], Decimal(r["preult"]))
        elif r["tpmerc"] in ("070", "080"):
            opt[r["codisi"]].append(r)
    print("janela:", min(win), "→", max(win), len(win), "pregões")
    tot = Counter()
    for isin, rs in opt.items():
        rs = [r for r in rs if (isin, r["data"]) in spot]
        if not rs:
            continue
        tk = spot[(isin, rs[0]["data"])][0]
        n = [int(r["totneg"]) for r in rs]
        series = {r["codneg"] for r in rs}
        # filtro "relevante": moneyness 0,8–1,2 e vencimento ≤ 95 dias corridos
        rel = []
        for r in rs:
            s = spot[(isin, r["data"])][1]
            k = Decimal(r["preexe"])
            dte = (d(r["datven"]) - d(r["data"])).days
            if s and 0.8 <= float(k / s) <= 1.2 and 0 < dte <= 95:
                rel.append(r)
        out = {}
        for thr in (1, 5, 10, 20, 50):
            sel = [r for r in rel if int(r["totneg"]) >= thr]
            out[thr] = (len(sel), len({r["codneg"] for r in sel}))
            tot[thr] += len(sel)
        print(f"{tk:7} séries-dia={len(rs):6} séries={len(series):5} quantis negócios/série-dia={q(n)}")
        print("        relevantes (0,8–1,2; ≤95d) por limiar de negócios → (requisições série-dia, séries distintas):", out)
    print("TOTAL requisições série-dia por limiar:", dict(tot))

elif TASK == "strikes":
    # QA-01 / RN-DAD-03: séries cujo strike muda ao longo do tempo (ajuste por provento) e consistência do cadastro
    tk = sys.argv[3]
    hist = defaultdict(list)
    for r in rows():
        if r["tpmerc"] in ("070", "080") and r["codneg"].startswith(tk[:4]) and r["data"] >= "20260801":
            hist[r["codneg"]].append((r["data"], r["preexe"], r["datven"], r["nomres"], r["especi"], r["tpmerc"]))
    changed = {s: h for s, h in hist.items() if len({x[1] for x in h}) > 1}
    print(len(hist), "séries;", len(changed), "com strike alterado")
    when = Counter()
    for s, h in changed.items():
        h.sort()
        for a, b in zip(h, h[1:]):
            if a[1] != b[1]:
                when[(a[0], b[0], str(Decimal(a[1]) - Decimal(b[1])))] += 1
    for k, v in when.most_common(10):
        print("  entre", k[0], "e", k[1], "Δstrike=", k[2], "→", v, "séries")
    other = {s: h for s, h in hist.items() if len({(x[2], x[5]) for x in h}) > 1}
    print("séries com vencimento/tipo alterado:", len(other))
    for s in list(changed)[:3]:
        print(s, sorted(set(changed[s]))[:4])

if TASK == "liq2":
    targets = sys.argv[3].split(",")
    days = sorted({r["data"] for r in rows() if r["codneg"] == "PETR4" and r["tpmerc"] == "010"})
    win = set(days[-63:])
    spot, opt = {}, defaultdict(list)
    for r in rows():
        if r["data"] not in win:
            continue
        if r["tpmerc"] == "010" and r["codneg"] in targets:
            spot[(r["codisi"], r["data"])] = (r["codneg"], Decimal(r["preult"]))
        elif r["tpmerc"] in ("070", "080"):
            opt[r["codisi"]].append(r)
    monthly = lambda s: 15 <= int(s[6:]) <= 21
    scen = {"A: 0,9–1,1 | 2 mensais | ≥10": (0.9, 1.1, 2, 10), "B: 0,9–1,1 | 3 mensais | ≥5": (0.9, 1.1, 3, 5),
            "C: 0,85–1,15 | 3 mensais | ≥10": (0.85, 1.15, 3, 10)}
    tot = Counter()
    for isin, rs in opt.items():
        rs = [r for r in rs if (isin, r["data"]) in spot]
        if not rs:
            continue
        tk = spot[(isin, rs[0]["data"])][0]
        out = {}
        for name, (lo, hi, nexp, thr) in scen.items():
            n = 0
            per_day = defaultdict(list)
            for r in rs:
                per_day[r["data"]].append(r)
            for dd, rr in per_day.items():
                exps = sorted({r["datven"] for r in rr if monthly(r["datven"]) and r["datven"] > dd})[:nexp]
                s = spot[(isin, dd)][1]
                n += sum(1 for r in rr if r["datven"] in exps and lo <= float(Decimal(r["preexe"]) / s) <= hi and int(r["totneg"]) >= thr)
            out[name[:1]] = (n, round(n / len(win), 1))
            tot[name] += n
        print(f"{tk:7}", out)
    for k, v in tot.items():
        print(k, "→", v, "req;", round(v / 3600, 1), "h a 1 req/s;", round(v / 63 / 10, 1), "séries/ativo/dia")
