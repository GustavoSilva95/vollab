"""QA-04/QA-05: defasagem opção × ativo e candidatos de preço de referência. Descartável.

IV aproximada: Black-Scholes europeu, sem dividendos, r = Selic 13,65% a.a. (base 252, exponencial),
tempo em du/252. Serve para COMPARAR candidatos entre si, não como IV de produção.
"""
import bisect
import csv
import math
import statistics as st
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from validate_ohlc import load_trades, r4  # noqa: E402

B = Path(sys.argv[1])
DAY = "2026-11-19"
R = math.log(1.1365)
HOL = {date(2026, 12, 24), date(2026, 12, 25), date(2026, 12, 31), date(2027, 1, 1)}  # a confirmar (QA-02)


def du(a: date, b: date) -> int:
    n, x = 0, a
    while x < b:
        x += timedelta(days=1)
        if x.weekday() < 5 and x not in HOL:
            n += 1
    return n


def ms(h: str) -> int:
    h = h.zfill(9)
    return ((int(h[:2]) * 60 + int(h[2:4])) * 60 + int(h[4:6])) * 1000 + int(h[6:])


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(s, k, t, sig, call):
    d1 = (math.log(s / k) + (R + sig * sig / 2) * t) / (sig * math.sqrt(t))
    d2 = d1 - sig * math.sqrt(t)
    if call:
        return s * ncdf(d1) - k * math.exp(-R * t) * ncdf(d2)
    return k * math.exp(-R * t) * ncdf(-d2) - s * ncdf(-d1)


def iv(p, s, k, t, call):
    lo, hi = 1e-4, 5.0
    if p <= bs(s, k, t, lo, call) or p >= bs(s, k, t, hi, call):
        return None
    for _ in range(80):
        m = (lo + hi) / 2
        if bs(s, k, t, m, call) > p:
            hi = m
        else:
            lo = m
    return (lo + hi) / 2


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))]


reg = {}
for r in csv.DictReader(open(B / "cotahist2026_filtered.csv")):
    if r["data"] == "20261119" and r["tpmerc"] in ("070", "080"):
        reg[r["codneg"]] = r

und = {}
for tk in ("PETR4", "VALE3"):
    tr = sorted(r4(load_trades(B / f"{tk}_{DAY}.zip")), key=lambda r: ms(r["HoraFechamento"]))
    und[tk] = ([ms(r["HoraFechamento"]) for r in tr], [float(r["PrecoNegocio"]) for r in tr])

all_lags = []
print(f"{'série':9} {'neg':>4} {'lag p50':>8} {'p90':>7} {'p99':>8} {'%>5s':>5} | IV: últ-ingênuo  últ-sinc  VWAPxVWAP  med-60min  (σ intradia)")
for f in sorted(B.glob(f"*_{DAY}.zip")):
    tk = f.stem.split("_")[0]
    if tk not in reg:
        continue
    meta = reg[tk]
    ut = "PETR4" if tk.startswith("PETR") else "VALE3"
    times, px = und[ut]
    k = float(meta["preexe"])
    call = meta["tpmerc"] == "070"
    y, m, d = int(meta["datven"][:4]), int(meta["datven"][4:6]), int(meta["datven"][6:])
    t = du(date(2026, 11, 19), date(y, m, d)) / 252
    tr = sorted(r4(load_trades(f)), key=lambda r: int(r["CodigoIdentificadorNegocio"]))
    lags, ivs = [], []
    for r in tr:
        tm = ms(r["HoraFechamento"])
        i = bisect.bisect_right(times, tm) - 1
        if i < 0:
            continue
        lag = tm - times[i]
        lags.append(lag)
        v = iv(float(r["PrecoNegocio"]), px[i], k, t, call)
        if v:
            ivs.append((tm, v))
    all_lags += lags
    last = tr[-1]
    li = bisect.bisect_right(times, ms(last["HoraFechamento"])) - 1
    iv_naive = iv(float(last["PrecoNegocio"]), px[-1], k, t, call)
    iv_sync = iv(float(last["PrecoNegocio"]), px[li], k, t, call)
    vq = sum(r["QuantidadeNegociada"] for r in tr)
    vwap_o = float(sum(r["PrecoNegocio"] * r["QuantidadeNegociada"] for r in tr)) / vq
    iv_vwap = iv(vwap_o, float(Decimal(st.mean(px))), k, t, call)
    cut = ms(last["HoraFechamento"]) - 3_600_000
    tail = [v for tm, v in ivs if tm >= cut]
    iv_med = st.median(tail) if tail else None
    sd = st.pstdev([v for _, v in ivs]) if len(ivs) > 1 else 0
    f4 = lambda x: f"{x:9.4f}" if x else "     n/d"
    print(f"{tk:9} {len(tr):4} {pct(lags,.5)/1000:7.1f}s {pct(lags,.9)/1000:6.1f}s {pct(lags,.99)/1000:7.1f}s {100*sum(l>5000 for l in lags)/len(lags):4.0f}% |"
          f" {f4(iv_naive)} {f4(iv_sync)} {f4(iv_vwap)} {f4(iv_med)}  ({sd:.4f})  último negócio {last['HoraFechamento'][:4]}")
print("TODOS: n=", len(all_lags), {p: round(pct(all_lags, p) / 1000, 2) for p in (.5, .9, .95, .99, .999)}, "s")
print("ativo: último negócio PETR4", und["PETR4"][0][-1] / 3.6e6, "h")
