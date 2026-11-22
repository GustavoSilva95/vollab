"""Parser exploratório (descartável) do COTAHIST da B3 — layout fixo de 245 colunas."""
import sys
import zipfile
from decimal import Decimal

FIELDS = [  # nome, início (1-based), fim (inclusive), tipo
    ("tipreg", 1, 2, "s"), ("data", 3, 10, "s"), ("codbdi", 11, 12, "s"),
    ("codneg", 13, 24, "s"), ("tpmerc", 25, 27, "s"), ("nomres", 28, 39, "s"),
    ("especi", 40, 49, "s"), ("prazot", 50, 52, "s"), ("modref", 53, 56, "s"),
    ("preabe", 57, 69, "p"), ("premax", 70, 82, "p"), ("premin", 83, 95, "p"),
    ("premed", 96, 108, "p"), ("preult", 109, 121, "p"), ("preofc", 122, 134, "p"),
    ("preofv", 135, 147, "p"), ("totneg", 148, 152, "i"), ("quatot", 153, 170, "i"),
    ("voltot", 171, 188, "p"), ("preexe", 189, 201, "p"), ("indopc", 202, 202, "s"),
    ("datven", 203, 210, "s"), ("fatcot", 211, 217, "i"), ("ptoexe", 218, 230, "s"),
    ("codisi", 231, 242, "s"), ("dismes", 243, 245, "s"),
]


def parse_line(line: str) -> dict:
    r = {}
    for name, a, b, t in FIELDS:
        v = line[a - 1 : b]
        if t == "s":
            r[name] = v.strip()
        elif t == "i":
            r[name] = int(v)
        else:
            r[name] = Decimal(int(v)) / 100
    return r


def read(path: str):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        assert len(names) == 1 and names[0].upper().endswith(".TXT"), names
        info = z.getinfo(names[0])
        assert info.file_size < 2_000_000_000
        with z.open(names[0]) as f:
            for raw in f:
                line = raw.decode("latin-1").rstrip("\r\n")
                if line[:2] == "01":
                    yield parse_line(line)


if __name__ == "__main__":
    for r in read(sys.argv[1]):
        print(r)
