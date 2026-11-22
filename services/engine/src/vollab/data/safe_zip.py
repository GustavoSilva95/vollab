"""Leitura segura de ZIPs baixados (PRD-NF-05): arquivos da B3 são entrada não confiável.

Regras:
- exatamente um membro, com nome simples (sem diretórios, `..`, caminho absoluto ou link);
- só extensões de texto aceitas (`.txt`, `.csv`);
- tamanho descompactado limitado, conferido **durante** a leitura (o tamanho declarado no
  cabeçalho do ZIP pode mentir) e razão de compressão limitada (zip bomb);
- nada é gravado no disco a partir do nome do membro: o conteúdo só é lido em memória ou
  em streaming. Os nomes em `data/raw/` são gerados pelo engine (raw_cache).
"""

import io
import stat
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass

ALLOWED_EXTENSIONS = (".txt", ".csv")
# Texto da B3 comprime ~10-25x; acima disso é suspeito.
MAX_COMPRESSION_RATIO = 200
_CHUNK = 1 << 20


class UnsafeArchiveError(ValueError):
    """ZIP rejeitado pelas regras de segurança. A mensagem não ecoa conteúdo do arquivo."""


@dataclass(frozen=True)
class ZipMember:
    name: str
    declared_size: int


def is_zip(content: bytes) -> bool:
    return content[:4] == b"PK\x03\x04"


def _single_member(archive: zipfile.ZipFile, max_bytes: int) -> zipfile.ZipInfo:
    infos = archive.infolist()
    if len(infos) != 1:
        raise UnsafeArchiveError(f"O ZIP deve ter exatamente 1 arquivo (tem {len(infos)}).")
    info = infos[0]
    name = info.filename
    if (
        not name
        or "/" in name
        or "\\" in name
        or ".." in name
        or name.startswith(".")
        or ":" in name
        or len(name) > 200
    ):
        raise UnsafeArchiveError("Nome de arquivo inválido dentro do ZIP.")
    if not name.lower().endswith(ALLOWED_EXTENSIONS):
        raise UnsafeArchiveError("Só arquivos de texto (.txt, .csv) são aceitos dentro do ZIP.")
    mode = info.external_attr >> 16
    if mode and (stat.S_ISLNK(mode) or stat.S_ISDIR(mode)):
        raise UnsafeArchiveError("Links e diretórios não são aceitos dentro do ZIP.")
    if info.flag_bits & 0x1:
        raise UnsafeArchiveError("ZIP criptografado não é aceito.")
    if info.file_size > max_bytes:
        raise UnsafeArchiveError(f"Arquivo descompactado acima do limite ({max_bytes} bytes).")
    if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
        raise UnsafeArchiveError("Razão de compressão suspeita.")
    return info


def _open(source: bytes | io.BufferedIOBase) -> zipfile.ZipFile:
    fh = io.BytesIO(source) if isinstance(source, bytes) else source
    try:
        return zipfile.ZipFile(fh)
    except zipfile.BadZipFile:
        raise UnsafeArchiveError("Arquivo não é um ZIP válido.") from None


def read_single_member(content: bytes, *, max_bytes: int) -> tuple[ZipMember, bytes]:
    """Lê o único membro do ZIP para a memória, com limite real de bytes."""
    with _open(content) as archive:
        info = _single_member(archive, max_bytes)
        out = bytearray()
        with archive.open(info) as fh:
            while chunk := fh.read(_CHUNK):
                out += chunk
                if len(out) > max_bytes:
                    raise UnsafeArchiveError(f"Arquivo descompactado acima do limite ({max_bytes} bytes).")
        return ZipMember(info.filename, info.file_size), bytes(out)


def iter_member_lines(path_or_bytes: bytes | io.BufferedIOBase, *, max_bytes: int) -> Iterator[bytes]:
    """Lê o único membro linha a linha (streaming), para arquivos grandes como o COTAHIST anual."""
    with _open(path_or_bytes) as archive:
        info = _single_member(archive, max_bytes)
        total = 0
        with archive.open(info) as fh:
            for line in fh:
                total += len(line)
                if total > max_bytes:
                    raise UnsafeArchiveError(f"Arquivo descompactado acima do limite ({max_bytes} bytes).")
                if len(line) > 4096:
                    raise UnsafeArchiveError("Linha longa demais para o formato esperado.")
                yield line
