from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Account, Currency, utcnow
from bot.services.transactions import RolledBackTx, rollback_all_unreconciled_for_account


async def list_accounts(session: AsyncSession) -> list[Account]:
    result = await session.execute(
        select(Account).where(Account.deleted_at.is_(None)).order_by(Account.created_at)
    )
    return list(result.scalars())


async def get_account(session: AsyncSession, account_id: int) -> Account | None:
    return await session.get(Account, account_id)


async def create_account(session: AsyncSession, currency: Currency, name: str) -> Account:
    account = Account(currency=currency, name=name.strip())
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


async def delete_account(session: AsyncSession, account_id: int) -> tuple[Account, list[RolledBackTx]]:
    account = await session.get(Account, account_id)
    if account is None or account.deleted_at is not None:
        raise LookupError("Account not found")

    rolled_back = await rollback_all_unreconciled_for_account(session, account_id)
    account.deleted_at = utcnow()
    await session.commit()
    await session.refresh(account)
    return account, rolled_back
