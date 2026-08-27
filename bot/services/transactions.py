from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.db.models import Account, Transaction, User, utcnow


class InsufficientFundsError(Exception):
    pass


class AlreadyReconciledError(Exception):
    pass


class NotAuthorError(Exception):
    pass


@dataclass(frozen=True)
class RolledBackTx:
    """Snapshot of a transaction taken right before it's hard-deleted, since the ORM
    object is gone/expired afterward but callers (handlers, notifications) still need
    to describe what was rolled back."""

    tx_id: int
    account_label: str
    amount: Decimal
    comment: str | None
    actor_label: str
    created_at: datetime
    origin_message_id: int | None
    author_telegram_id: int | None


async def create_transaction(
    session: AsyncSession,
    *,
    account_id: int,
    direction: str,
    amount: Decimal,
    comment: str | None,
    actor: User,
) -> tuple[Transaction, Account]:
    assert direction in ("income", "expense")
    account = await session.get(Account, account_id)
    if account is None or account.deleted_at is not None:
        raise LookupError("Account not found")

    signed = amount if direction == "income" else -amount
    new_balance = Decimal(str(account.balance)) + signed
    if direction == "expense" and new_balance < 0:
        raise InsufficientFundsError()

    account.balance = new_balance
    tx = Transaction(account_id=account.id, amount=signed, comment=comment, created_by_id=actor.id)
    session.add(tx)
    await session.commit()
    await session.refresh(tx)
    return tx, account


async def get_transaction(session: AsyncSession, tx_id: int) -> Transaction | None:
    result = await session.execute(
        select(Transaction)
        .options(selectinload(Transaction.account), selectinload(Transaction.created_by))
        .where(Transaction.id == tx_id)
    )
    return result.scalar_one_or_none()


async def set_origin_message(session: AsyncSession, tx_id: int, message_id: int) -> None:
    tx = await session.get(Transaction, tx_id)
    if tx is not None:
        tx.origin_message_id = message_id
        await session.commit()


def _snapshot(tx: Transaction) -> RolledBackTx:
    from bot.utils import actor_label

    return RolledBackTx(
        tx_id=tx.id,
        account_label=tx.account.label,
        amount=Decimal(str(tx.amount)),
        comment=tx.comment,
        actor_label=actor_label(tx.created_by),
        created_at=tx.created_at,
        origin_message_id=tx.origin_message_id,
        author_telegram_id=tx.created_by.telegram_user_id,
    )


async def rollback_transaction(session: AsyncSession, tx_id: int, actor_telegram_id: int) -> RolledBackTx:
    result = await session.execute(
        select(Transaction)
        .options(selectinload(Transaction.account), selectinload(Transaction.created_by))
        .where(Transaction.id == tx_id)
    )
    tx = result.scalar_one_or_none()
    if tx is None:
        raise LookupError("Transaction not found")
    if tx.reconciled:
        raise AlreadyReconciledError()
    if tx.created_by.telegram_user_id != actor_telegram_id:
        raise NotAuthorError()

    snapshot = _snapshot(tx)
    tx.account.balance = Decimal(str(tx.account.balance)) - Decimal(str(tx.amount))
    await session.delete(tx)
    await session.commit()
    return snapshot


async def rollback_all_unreconciled_for_account(session: AsyncSession, account_id: int) -> list[RolledBackTx]:
    result = await session.execute(
        select(Transaction)
        .options(selectinload(Transaction.account), selectinload(Transaction.created_by))
        .where(Transaction.account_id == account_id, Transaction.reconciled.is_(False))
    )
    txs = list(result.scalars())
    snapshots = [_snapshot(tx) for tx in txs]
    for tx in txs:
        tx.account.balance = Decimal(str(tx.account.balance)) - Decimal(str(tx.amount))
        await session.delete(tx)
    if txs:
        await session.commit()
    return snapshots


async def reconcile(session: AsyncSession, *, account_id: int | None) -> list[Transaction]:
    query = select(Transaction).options(
        selectinload(Transaction.account), selectinload(Transaction.created_by)
    ).where(Transaction.reconciled.is_(False))
    if account_id is not None:
        query = query.where(Transaction.account_id == account_id)
    result = await session.execute(query)
    txs = list(result.scalars())
    now = utcnow()
    for tx in txs:
        tx.reconciled = True
        tx.reconciled_at = now
    if txs:
        await session.commit()
    return txs
