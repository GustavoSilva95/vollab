"""PRD-NF-05: ZIPs baixados são entrada não confiável."""

import io
import stat
import zipfile

import pytest

from vollab.data.safe_zip import UnsafeArchiveError, iter_member_lines, read_single_member


def _zip(members: dict[str, bytes], *, symlink: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            if name == symlink:
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, data)
    return buf.getvalue()


def test_reads_single_text_member() -> None:
    member, data = read_single_member(_zip({"a.txt": b"ola"}), max_bytes=100)
    assert (member.name, data) == ("a.txt", b"ola")


@pytest.mark.parametrize(
    "members",
    [
        {"a.txt": b"1", "b.txt": b"2"},
        {"../fora.txt": b"x"},
        {"dir/a.txt": b"x"},
        {"/etc/passwd.txt": b"x"},
        {"a.exe": b"x"},
        {".oculto.txt": b"x"},
    ],
)
def test_rejects_unsafe_members(members: dict[str, bytes]) -> None:
    with pytest.raises(UnsafeArchiveError):
        read_single_member(_zip(members), max_bytes=1000)


def test_rejects_symlink() -> None:
    with pytest.raises(UnsafeArchiveError):
        read_single_member(_zip({"a.txt": b"/etc/passwd"}, symlink="a.txt"), max_bytes=1000)


def test_rejects_zip_bomb_by_ratio() -> None:
    with pytest.raises(UnsafeArchiveError):
        read_single_member(_zip({"a.txt": b"0" * 5_000_000}), max_bytes=10_000_000)


def test_rejects_oversized_member() -> None:
    with pytest.raises(UnsafeArchiveError):
        read_single_member(_zip({"a.txt": bytes(range(256)) * 100}), max_bytes=1000)
    with pytest.raises(UnsafeArchiveError):
        list(iter_member_lines(_zip({"a.txt": bytes(range(256)) * 100}), max_bytes=1000))


def test_rejects_lying_declared_size() -> None:
    """O tamanho declarado no cabeçalho pode mentir: o limite vale durante a leitura."""
    payload = bytearray(_zip({"a.txt": bytes(range(256)) * 40}))
    # Reescreve o tamanho descompactado no diretório central para 10 bytes.
    cd = payload.rfind(b"PK\x01\x02")
    payload[cd + 24 : cd + 28] = (10).to_bytes(4, "little")
    with pytest.raises((UnsafeArchiveError, zipfile.BadZipFile)):
        read_single_member(bytes(payload), max_bytes=1000)


def test_rejects_non_zip() -> None:
    with pytest.raises(UnsafeArchiveError):
        read_single_member(b"<html>bloqueado</html>", max_bytes=1000)
