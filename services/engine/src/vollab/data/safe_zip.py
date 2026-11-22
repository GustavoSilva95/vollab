"""Leitura segura de ZIPs baixados (PRD-NF-05): arquivos da B3 são entrada não confiável.

Regras:
- exatamente um membro, com nome simples (sem diretórios, `..`, caminho absoluto ou link);
- só extensões de texto aceitas (`.txt`, `.csv`);
- tamanho descompactado limitado, conferido **durante** a leitura; a razão de compressão
  declarada é só um filtro barato (os tamanhos declarados podem mentir: o limite real é a
  contagem de bytes lidos); só os métodos stored e deflate;
- linhas lidas com limite de tamanho (streaming);
- ZIP corrompido vira `UnsafeArchiveError` com mensagem fixa (nada do arquivo no log);
- nada é gravado no disco a partir do nome do membro: o conteúdo só é lido em memória ou
  em streaming. Os nomes em `data/raw/` são gerados pelo engine (raw_cache).
"""

import io
import stat
import zipfile
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

ALLOWED_EXTENSIONS = (".txt", ".csv")
ALLOWED_METHODS = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
MAX_LINE_BYTES = 4096
# Erros de ZIP corrompido: viram UnsafeArchiveError com mensagem fixa, sem ecoar bytes do arquivo
# (a mensagem do BadZipFile pode conter o nome do membro, controlado pela fonte).
_ARCHIVE_ERRORS = (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, OSError, ValueError)
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
    if info.compress_type not in ALLOWED_METHODS:
        raise UnsafeArchiveError("Método de compressão não aceito (só stored e deflate).")
    if info.flag_bits & 0x1:
        raise UnsafeArchiveError("ZIP criptografado não é aceito.")
    if info.file_size > max_bytes:
        raise UnsafeArchiveError(f"Arquivo descompactado acima do limite ({max_bytes} bytes).")
    if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
        raise UnsafeArchiveError("Razão de compressão suspeita.")
    return info


@contextmanager
def _archive_errors() -> Iterator[None]:
    try:
        yield
    except UnsafeArchiveError:
        raise
    except _ARCHIVE_ERRORS:
        raise UnsafeArchiveError("ZIP corrompido ou fora do formato esperado.") from None


def _open(source: bytes | io.BufferedIOBase) -> zipfile.ZipFile:
    fh = io.BytesIO(source) if isinstance(source, bytes) else source
    try:
        return zipfile.ZipFile(fh)
    except _ARCHIVE_ERRORS:
        raise UnsafeArchiveError("Arquivo não é um ZIP válido.") from None


def read_single_member(content: bytes, *, max_bytes: int) -> tuple[ZipMember, bytes]:
    """Lê o único membro do ZIP para a memória, com limite real de bytes."""
    with _archive_errors(), _open(content) as archive:
        info = _single_member(archive, max_bytes)
        out = bytearray()
        with archive.open(info) as fh:
            while chunk := fh.read(_CHUNK):
                out += chunk
                if len(out) > max_bytes:
                    raise UnsafeArchiveError(f"Arquivo descompactado acima do limite ({max_bytes} bytes).")
        return ZipMember(info.filename, info.file_size), bytes(out)


def iter_member_lines(path_or_bytes: bytes | io.BufferedIOBase, *, max_bytes: int) -> Iterator[bytes]:
    """Lê o único membro linha a linha (streaming), para arquivos grandes como o COTAHIST anual.

    Cada linha é lida com limite (`readline(MAX_LINE_BYTES + 1)`): uma linha gigante sem quebra
    nunca é carregada inteira na memória (revisão de segurança da Etapa 2, M-1).
    """
    with _archive_errors(), _open(path_or_bytes) as archive:
        info = _single_member(archive, max_bytes)
        total = 0
        with archive.open(info) as fh:
            while line := fh.readline(MAX_LINE_BYTES + 1):
                if len(line) > MAX_LINE_BYTES:
                    raise UnsafeArchiveError("Linha longa demais para o formato esperado.")
                total += len(line)
                if total > max_bytes:
                    raise UnsafeArchiveError(f"Arquivo descompactado acima do limite ({max_bytes} bytes).")
                yield line
