"""Cache bruto imutável em disco (ADR-06, RF-DAD-04, PRD-NF-05).

O caminho é gerado pelo engine a partir do SHA-256 do conteúdo:
`{fonte}/{sha[:2]}/{sha}.{ext}`. Nada da resposta (nome do arquivo no ZIP, cabeçalhos)
entra no caminho. Conteúdo idêntico é gravado uma vez só; um arquivo existente nunca é
sobrescrito (gravação atômica com `O_EXCL` num temporário + rename).
"""

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

_SOURCE = re.compile(r"^[a-z0-9_]{1,40}$")
_EXTENSIONS = frozenset({"zip", "json", "csv", "bin"})


@dataclass(frozen=True)
class StoredFile:
    relative_path: str
    sha256: str
    size_bytes: int


class RawCache:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _target(self, source: str, sha: str, ext: str) -> Path:
        if not _SOURCE.match(source) or ext not in _EXTENSIONS:
            raise ValueError("Fonte ou extensão inválida para o cache bruto.")
        path = (self.root / source / sha[:2] / f"{sha}.{ext}").resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Caminho fora do cache bruto.")
        return path

    def store(self, source: str, content: bytes, ext: str) -> StoredFile:
        sha = hashlib.sha256(content).hexdigest()
        target = self._target(source, sha, ext)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(f".{sha}.{os.getpid()}.tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(content)
                    fh.flush()
                    os.fsync(fh.fileno())
                tmp.replace(target)
            finally:
                tmp.unlink(missing_ok=True)
        return StoredFile(str(target.relative_to(self.root)), sha, len(content))

    def read(self, relative_path: str, *, expected_sha256: str) -> bytes:
        path = (self.root / relative_path).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Caminho fora do cache bruto.")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected_sha256:
            raise ValueError("Arquivo do cache bruto não confere com o hash registrado.")
        return content
