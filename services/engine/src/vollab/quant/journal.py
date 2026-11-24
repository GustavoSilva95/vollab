"""Livro de lançamentos de uma operação (PRD 1.10 §5.9; BRD 1.7 RF-DIA-02/03, RS-06, RN-GES-04).

Puro, sem I/O. Os lançamentos são imutáveis: um erro se corrige por **estorno** (`void`), que anula o
lançamento ligado. As quantidades, o status e as transações (para a linha de execução e custos da
atribuição) saem da **reexecução** dos lançamentos válidos em ordem de execução; a mesma reexecução
valida um lançamento novo (inclusive retroativo) e um estorno (que não pode quebrar os posteriores).

Convenções: quantidade com sinal (+ compra, − venda), em opções ou ações; dinheiro em `Decimal`.
- `exercise` / `assignment`: `quantity` é a variação da perna de opção (exercício de perna comprada:
  negativa; designação de perna vendida: positiva). A ação entra ou sai ao strike efetivo gravado em
  `price` (call exercida: +ações; put exercida: −ações; call designada: −ações; put designada: +ações).
- `strike_adjustment`: `quantity` é a **quantidade da perna depois do ajuste** (mesmo sinal) e
  `strike_after` o novo strike efetivo. A diferença de quantidade entra a preço 0 (o valor da perna
  é preservado pelo ajuste; o dia aparece com resíduo alto e o sinal de erro, se for o caso).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from zoneinfo import ZoneInfo

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
ZERO = Decimal(0)


class EntryKind(StrEnum):
    ENTRY = "entry"
    HEDGE = "hedge"
    STRIKE_ADJUSTMENT = "strike_adjustment"
    EXERCISE = "exercise"
    ASSIGNMENT = "assignment"
    EXIT = "exit"
    ROLL = "roll"
    VOID = "void"


# Tipos que o usuário lança por `POST /positions/{id}/entries` (`entry` e `roll` vêm do registro).
USER_KINDS = (
    EntryKind.HEDGE,
    EntryKind.STRIKE_ADJUSTMENT,
    EntryKind.EXERCISE,
    EntryKind.ASSIGNMENT,
    EntryKind.EXIT,
    EntryKind.VOID,
)


@dataclass(frozen=True, slots=True)
class OptionInfo:
    """Perna de opção da posição (do retrato da decisão e do cadastro de séries)."""

    code: str
    series_id: int
    is_call: bool
    expiry: date
    european: bool


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    id: int
    kind: EntryKind
    instrument: str  # código da série ou ticker do ativo-objeto
    quantity: int
    price: Decimal
    fees: Decimal
    brokerage: Decimal
    executed_at: datetime
    series_id: int | None = None
    linked_entry_id: int | None = None
    strike_after: Decimal | None = None

    @property
    def costs(self) -> Decimal:
        return self.fees + self.brokerage

    @property
    def day(self) -> date:
        """Data da execução no relógio de Brasília."""
        return self.executed_at.astimezone(SAO_PAULO).date()


@dataclass(frozen=True, slots=True)
class Transaction:
    """Efeito de um lançamento num instrumento: variação de quantidade a um preço, com custos."""

    entry_id: int
    instrument: str
    quantity: int
    price: Decimal
    costs: Decimal
    day: date


@dataclass(slots=True)
class Ledger:
    """Estado depois da reexecução: quantidades por instrumento e transações em ordem."""

    holdings: dict[str, int] = field(default_factory=dict)
    transactions: list[Transaction] = field(default_factory=list)
    strikes_after: dict[str, Decimal] = field(default_factory=dict)
    # Livro gravado inconsistente (não deveria acontecer: as escritas travam a operação). A leitura
    # segue com o motivo, sem derrubar o diário e a carteira.
    error: str | None = None

    @property
    def is_open(self) -> bool:
        return any(q != 0 for q in self.holdings.values())


class LedgerError(ValueError):
    """Lançamento inconsistente (RS-06): a API devolve 422 com a mensagem."""


@dataclass(frozen=True, slots=True)
class PositionBook:
    """O que a validação precisa saber da posição."""

    stock: str  # ticker do ativo-objeto
    options: dict[str, OptionInfo]  # por código da série


def active_entries(entries: Iterable[LedgerEntry]) -> list[LedgerEntry]:
    """Lançamentos válidos (sem os estornos e sem os anulados), em ordem de execução."""
    items = list(entries)
    voided = {e.linked_entry_id for e in items if e.kind is EntryKind.VOID}
    kept = [e for e in items if e.kind is not EntryKind.VOID and e.id not in voided]
    return sorted(kept, key=lambda e: (e.executed_at, e.id))


def transactions_of(entry: LedgerEntry, book: PositionBook, holdings: dict[str, int]) -> list[Transaction]:
    day = entry.day
    k = entry.kind
    if k in (EntryKind.ENTRY, EntryKind.HEDGE, EntryKind.EXIT, EntryKind.ROLL):
        return [Transaction(entry.id, entry.instrument, entry.quantity, entry.price, entry.costs, day)]
    if k in (EntryKind.EXERCISE, EntryKind.ASSIGNMENT):
        opt = book.options[entry.instrument]
        n = abs(entry.quantity)
        # Exercício de call e designação de put recebem ações; os outros dois entregam.
        receives = opt.is_call == (k is EntryKind.EXERCISE)
        shares = n if receives else -n
        return [
            Transaction(entry.id, entry.instrument, entry.quantity, ZERO, ZERO, day),
            Transaction(entry.id, book.stock, shares, entry.price, entry.costs, day),
        ]
    if k is EntryKind.STRIKE_ADJUSTMENT:
        change = entry.quantity - holdings.get(entry.instrument, 0)
        if change == 0:
            return [Transaction(entry.id, entry.instrument, 0, ZERO, entry.costs, day)]
        return [Transaction(entry.id, entry.instrument, change, ZERO, entry.costs, day)]
    raise LedgerError(f"Tipo de lançamento sem efeito em quantidades: {k.value}.")


def _check_step(entry: LedgerEntry, book: PositionBook, holdings: dict[str, int], first_at: datetime) -> None:
    """Regras de consistência de um lançamento contra as quantidades antes dele (RS-06)."""
    k = entry.kind
    code = entry.instrument
    if k is not EntryKind.ENTRY and entry.executed_at < first_at:
        raise LedgerError("Data de execução anterior à entrada da operação.")
    if k is EntryKind.ENTRY:
        return
    is_stock = code == book.stock
    opt = book.options.get(code)
    if not is_stock and opt is None:
        raise LedgerError(f"{code} não pertence à operação (pernas do retrato ou ação do ativo-objeto).")
    current = holdings.get(code, 0)
    if k is EntryKind.HEDGE:
        if not is_stock:
            raise LedgerError("Hedge só com a ação do ativo-objeto.")
        if entry.quantity == 0:
            raise LedgerError("Hedge com quantidade zero.")
        return
    if k in (EntryKind.EXIT, EntryKind.ROLL):
        if k is EntryKind.ROLL and is_stock:
            raise LedgerError("Rolagem só nas pernas de opção.")
        if current == 0:
            raise LedgerError(f"{code} sem quantidade em aberto para sair.")
        if (entry.quantity > 0) == (current > 0) or abs(entry.quantity) > abs(current):
            raise LedgerError(
                f"Saída de {code} deve reduzir a quantidade em direção a zero (em aberto: {current}; "
                f"lançado: {entry.quantity})."
            )
        return
    if opt is None:
        raise LedgerError(f"{k.value} só em perna de opção.")
    day = entry.day
    if k in (EntryKind.EXERCISE, EntryKind.ASSIGNMENT):
        long_leg = current > 0
        if k is EntryKind.EXERCISE and not long_leg:
            raise LedgerError(f"Exercício só em perna comprada ({code} em aberto: {current}).")
        if k is EntryKind.ASSIGNMENT and (current >= 0):
            raise LedgerError(f"Designação só em perna vendida ({code} em aberto: {current}).")
        if (entry.quantity > 0) == (current > 0) or abs(entry.quantity) > abs(current):
            raise LedgerError(
                f"Quantidade de {k.value} incompatível com a perna (em aberto: {current}; lançado: "
                f"{entry.quantity})."
            )
        if entry.price <= 0:
            raise LedgerError("Exercício e designação exigem o strike efetivo em `price`.")
        if opt.european and day != opt.expiry:
            raise LedgerError(f"{code} é europeia: exercício e designação só no vencimento ({opt.expiry}).")
        if day > opt.expiry:
            raise LedgerError(f"{code} venceu em {opt.expiry}: exercício ou designação depois do vencimento.")
        return
    if k is EntryKind.STRIKE_ADJUSTMENT:
        if current == 0:
            raise LedgerError(f"{code} sem quantidade em aberto para ajustar.")
        if entry.quantity == 0 or (entry.quantity > 0) != (current > 0):
            raise LedgerError("A quantidade depois do ajuste deve ter o mesmo sinal da perna.")
        if entry.strike_after is None or entry.strike_after <= 0:
            raise LedgerError("Ajuste de strike exige o novo strike efetivo (`strike_after`).")
        return
    raise LedgerError(f"Tipo de lançamento inválido: {k.value}.")


def replay(entries: Sequence[LedgerEntry], book: PositionBook) -> Ledger:
    """Reexecuta os lançamentos válidos em ordem e valida cada um. `LedgerError` no primeiro erro."""
    items = active_entries(entries)
    ledger = Ledger()
    entry_times = [e.executed_at for e in items if e.kind is EntryKind.ENTRY]
    if not entry_times:
        raise LedgerError("Operação sem lançamento de entrada.")
    first_at = min(entry_times)
    for e in items:
        _check_step(e, book, ledger.holdings, first_at)
        for tx in transactions_of(e, book, ledger.holdings):
            ledger.transactions.append(tx)
            ledger.holdings[tx.instrument] = ledger.holdings.get(tx.instrument, 0) + tx.quantity
        if e.kind is EntryKind.STRIKE_ADJUSTMENT and e.strike_after is not None:
            ledger.strikes_after[e.instrument] = e.strike_after
    return ledger


def replay_or_flag(entries: Sequence[LedgerEntry], book: PositionBook) -> Ledger:
    """Para leitura: como `replay`, mas um livro inconsistente vira um `Ledger` com `error` e as
    quantidades somadas sem validação (a operação aparece com o aviso em vez de derrubar a tela)."""
    try:
        return replay(entries, book)
    except LedgerError as exc:
        ledger = Ledger(error=str(exc))
        for e in active_entries(entries):
            try:
                txs = transactions_of(e, book, ledger.holdings)
            except (LedgerError, KeyError):
                continue
            for tx in txs:
                ledger.transactions.append(tx)
                ledger.holdings[tx.instrument] = ledger.holdings.get(tx.instrument, 0) + tx.quantity
        return ledger


def validate_new(
    existing: Sequence[LedgerEntry], new: LedgerEntry, book: PositionBook, *, now: datetime
) -> Ledger:
    """Valida um lançamento novo contra os existentes e devolve o livro resultante (RS-06)."""
    if new.executed_at > now:
        raise LedgerError("Data de execução no futuro.")
    before = replay(existing, book)
    if new.kind is EntryKind.VOID:
        target = next((e for e in existing if e.id == new.linked_entry_id), None)
        if target is None:
            raise LedgerError("Estorno de um lançamento que não é desta operação.")
        if target.kind is EntryKind.ENTRY:
            raise LedgerError("A entrada não se estorna: encerre a operação com lançamentos de saída.")
        if target.kind is EntryKind.VOID:
            raise LedgerError("Um estorno não se estorna.")
        if any(e.kind is EntryKind.VOID and e.linked_entry_id == target.id for e in existing):
            raise LedgerError("Este lançamento já foi estornado.")
        try:
            return replay([*existing, new], book)
        except LedgerError as exc:
            raise LedgerError(f"O estorno deixaria lançamentos posteriores inconsistentes: {exc}") from None
    if new.kind not in USER_KINDS:
        raise LedgerError(f"Tipo de lançamento não aceito aqui: {new.kind.value}.")
    if not before.is_open:
        raise LedgerError("Operação encerrada: não aceita lançamentos (só estorno).")
    return replay([*existing, new], book)


def pending_expiry(ledger: Ledger, book: PositionBook, today: date) -> list[str]:
    """Pernas vencidas ainda em aberto: falta lançar exercício, designação ou vencimento sem
    exercício (LC-08)."""
    return sorted(
        code for code, opt in book.options.items() if opt.expiry < today and ledger.holdings.get(code, 0) != 0
    )


def holdings_until(ledger: Ledger, day: date) -> dict[str, int]:
    """Quantidades no fechamento de `day` (transações executadas até o fim do dia)."""
    out: dict[str, int] = {}
    for tx in ledger.transactions:
        if tx.day <= day:
            out[tx.instrument] = out.get(tx.instrument, 0) + tx.quantity
    return out


def with_id(entry: LedgerEntry, new_id: int) -> LedgerEntry:
    return replace(entry, id=new_id)
