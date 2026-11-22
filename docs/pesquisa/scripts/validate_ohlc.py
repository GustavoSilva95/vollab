"""Valida regras de OHLC (QA-13) contra o COTAHIST oficial. Descartável."""
import csv
import io
import sys
import zipfile
from collections import Counter
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cotahist import read  # noqa: E402

MAX_UNZIPPED = 200_000_000


def load_trades(path: Path) -> list[dict]:
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        assert len(names) == 1, names
        n = names[0]
        assert "/" not in n and "\\" not in n and ".." not in n, n
        assert z.getinfo(n).file_size < MAX_UNZIPPED
        text = z.read(n).decode("latin-1")
    rows = list(csv.DictReader(io.StringIO(text), delimiter=";"))
    for r in rows:
        r["PrecoNegocio"] = Decimal(r["PrecoNegocio"].replace(",", "."))
        r["QuantidadeNegociada"] = int(r["QuantidadeNegociada"])
    return rows


def ohlc(rows):
    if not rows:
        return None
    rows = sorted(rows, key=lambda r: int(r["CodigoIdentificadorNegocio"]))
    px = [r["PrecoNegocio"] for r in rows]
    q = sum(r["QuantidadeNegociada"] for r in rows)
    vol = sum(r["PrecoNegocio"] * r["QuantidadeNegociada"] for r in rows)
    return dict(n=len(rows), o=px[0], h=max(px), l=min(px), c=px[-1], q=q, vwap=round(vol / q, 4))


RULES = {
    "R0 tudo": lambda r: True,
    "R1 data=ref": lambda r: r["DataNegocio"] == r["DataReferencia"],
    "R2 R1+acao=0": lambda r: r["DataNegocio"] == r["DataReferencia"] and r["AcaoAtualizacao"] == "0",
    "R3 R2+sessao=1": lambda r: r["DataNegocio"] == r["DataReferencia"] and r["AcaoAtualizacao"] == "0" and r["TipoSessaoPregao"] == "1",
}


def r4(rows):
    """R4: sessão regular do pregão de referência, sem negócios cancelados (AcaoAtualizacao=2 anula o ID)."""
    canc = {r["CodigoIdentificadorNegocio"] for r in rows if r["AcaoAtualizacao"] != "0"}
    return [r for r in rows if r["DataNegocio"] == r["DataReferencia"] and r["TipoSessaoPregao"] == "1"
            and r["AcaoAtualizacao"] == "0" and r["CodigoIdentificadorNegocio"] not in canc]

if __name__ == "__main__":
    base = Path(sys.argv[1])
    off = {}
    for f in [*base.glob("COTAHIST_D*.ZIP"), *(base.parent / "cotahist").glob("COTAHIST_D*.ZIP")]:
        for r in read(str(f)):
            off[(r["codneg"], f"{r['data'][:4]}-{r['data'][4:6]}-{r['data'][6:]}")] = r
    acoes, sessoes = Counter(), Counter()
    score = Counter()
    total = 0
    for f in sorted(base.glob("*_2026-11-1[789].zip")):
        t, d = f.stem.rsplit("_", 1)
        if not zipfile.is_zipfile(f):
            print("nao-zip", f.name); continue
        rows = load_trades(f)
        acoes.update(r["AcaoAtualizacao"] for r in rows)
        sessoes.update(r["TipoSessaoPregao"] for r in rows)
        o = off.get((t, d))
        if not o:
            print("sem oficial", t, d)
            continue
        total += 1
        ref = dict(n=o["totneg"], o=o["preabe"], h=o["premax"], l=o["premin"], c=o["preult"], q=o["quatot"], vwap=o["premed"])
        line = [f"{t:9} {d}"]
        for name, fn in RULES.items():
            got = ohlc([r for r in rows if fn(r)])
        for name, got in [("R4", ohlc(r4(rows)))]:
            diff = [k for k in ref if got is None or (abs(got[k]-ref[k]) > Decimal("0.01") if k=="vwap" else got[k] != ref[k])]
            score[name] += not diff
            line.append(f"R4:{'OK' if not diff else ','.join(diff)}")
        for name, fn in []:
            got = None
            diff = [k for k in ref if got is None or (abs(got[k]-ref[k]) > Decimal("0.01") if k=="vwap" else got[k] != ref[k])]
            if not diff:
                score[name] += 1
            extra = f"({got['vwap']}≠{ref['vwap']})" if got and "vwap" in diff else ""
            line.append(f"{name.split()[0]}:{'OK' if not diff else ','.join(diff)}{extra}")
        print("  ".join(line), f"| oficial n={o['totneg']} o={o['preabe']} c={o['preult']}")
    print("AcaoAtualizacao:", dict(acoes), "TipoSessaoPregao:", dict(sessoes))
    print("acertos por regra (de", total, "):", dict(score))
