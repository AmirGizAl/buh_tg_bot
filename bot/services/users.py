from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Role, User, UserStatus, utcnow


class AlreadyInvitedError(Exception):
    pass


async def get_or_seed_owner(session: AsyncSession, owner_id: int) -> User:
    """Ensure the bootstrap owner (from OWNER_ID) exists as an active User row.
    Called once at startup, before polling begins."""
    result = await session.execute(select(User).where(User.telegram_user_id == owner_id))
    user = result.scalar_one_or_none()
    if user is not None:
        if user.role != Role.OWNER or user.status != UserStatus.ACTIVE:
            user.role = Role.OWNER
            user.status = UserStatus.ACTIVE
            if user.activated_at is None:
                user.activated_at = utcnow()
            await session.commit()
            await session.refresh(user)
        return user
    user = User(telegram_user_id=owner_id, role=Role.OWNER, status=UserStatus.ACTIVE, activated_at=utcnow())
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def observe_user(
    session: AsyncSession,
    telegram_user_id: int,
    username: str | None,
    full_name: str | None,
) -> User | None:
    """Runs on every update (message/callback), in both DM and the group chat, for
    every sender regardless of access. Two jobs:
    1) activate a PENDING employee invite if this sender's username matches one
       (returns that User so the caller can push its Telegram "/" command scope), and
    2) opportunistically refresh the display name/username of an already-known user,
       so the report's "пользователь" column stays current."""
    username_lower = username.lower() if username else None

    if username_lower:
        result = await session.execute(
            select(User).where(
                User.status == UserStatus.PENDING,
                User.telegram_user_id.is_(None),
                User.username == username_lower,
            )
        )
        pending = result.scalar_one_or_none()
        if pending is not None:
            pending.telegram_user_id = telegram_user_id
            pending.status = UserStatus.ACTIVE
            pending.activated_at = utcnow()
            pending.username_display = username
            if full_name:
                pending.full_name = full_name
            try:
                await session.commit()
            except IntegrityError:
                # Defensive backstop: some other row still holds this telegram_user_id
                # (e.g. a pre-fix removed row on an older database — see
                # bot/db/engine.py's startup heal). Don't crash the update; just skip
                # activation this time, the next message from this user will retry.
                await session.rollback()
                return None
            await session.refresh(pending)
            return pending

    result = await session.execute(select(User).where(User.telegram_user_id == telegram_user_id))
    existing = result.scalar_one_or_none()
    if existing is None:
        return None
    changed = False
    if username_lower and existing.username != username_lower:
        existing.username = username_lower
        existing.username_display = username
        changed = True
    if full_name and existing.full_name != full_name:
        existing.full_name = full_name
        changed = True
    if changed:
        await session.commit()
    return None


async def resolve_role(session: AsyncSession, telegram_user_id: int | None) -> str | None:
    if telegram_user_id is None:
        return None
    result = await session.execute(
        select(User).where(User.telegram_user_id == telegram_user_id, User.status == UserStatus.ACTIVE)
    )
    user = result.scalar_one_or_none()
    return user.role.value if user else None


async def get_active_user(session: AsyncSession, telegram_user_id: int) -> User | None:
    result = await session.execute(
        select(User).where(User.telegram_user_id == telegram_user_id, User.status == UserStatus.ACTIVE)
    )
    return result.scalar_one_or_none()


async def invite_employee(session: AsyncSession, username: str) -> User:
    clean = username.strip().lstrip("@")
    if not clean:
        raise ValueError("Empty username")
    lower = clean.lower()
    result = await session.execute(
        select(User).where(
            User.username == lower,
            User.status.in_([UserStatus.PENDING, UserStatus.ACTIVE]),
        )
    )
    if result.scalar_one_or_none() is not None:
        raise AlreadyInvitedError(clean)
    user = User(username=lower, username_display=clean, role=Role.EMPLOYEE, status=UserStatus.PENDING)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def remove_employee(session: AsyncSession, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None or user.role != Role.EMPLOYEE:
        raise ValueError("Not an employee")
    user.status = UserStatus.REMOVED
    user.removed_at = utcnow()
    # Free up the telegram_user_id (unique) slot so this same person can be invited
    # and reactivated again later — a removed row keeping it would otherwise collide
    # with the fresh PENDING row created for them on re-invitation.
    user.telegram_user_id = None
    await session.commit()
    await session.refresh(user)
    return user


async def get_employee(session: AsyncSession, user_id: int) -> User | None:
    user = await session.get(User, user_id)
    if user is None or user.role != Role.EMPLOYEE:
        return None
    return user


async def list_active_employees(session: AsyncSession) -> list[User]:
    result = await session.execute(
        select(User)
        .where(User.role == Role.EMPLOYEE, User.status == UserStatus.ACTIVE)
        .order_by(User.activated_at)
    )
    return list(result.scalars())


async def list_pending_invites(session: AsyncSession) -> list[User]:
    result = await session.execute(
        select(User)
        .where(User.role == Role.EMPLOYEE, User.status == UserStatus.PENDING)
        .order_by(User.created_at)
    )
    return list(result.scalars())
