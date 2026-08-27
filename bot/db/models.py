import enum
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Currency(str, enum.Enum):
    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"


class Role(str, enum.Enum):
    OWNER = "owner"
    EMPLOYEE = "employee"


class UserStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    REMOVED = "removed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int | None] = mapped_column(unique=True, nullable=True, index=True)
    # lowercase, used for case-insensitive matching against Telegram's from.username
    username: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # last-observed casing, used for display ("@Name")
    username_display: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    role: Mapped[Role] = mapped_column(SAEnum(Role))
    status: Mapped[UserStatus] = mapped_column(SAEnum(UserStatus), default=UserStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    activated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    removed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="created_by")


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    currency: Mapped[Currency] = mapped_column(SAEnum(Currency))
    name: Mapped[str] = mapped_column(String(128))
    balance: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True, index=True)

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account")

    @property
    def label(self) -> str:
        return f"{self.currency.value} {self.name}"


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    # signed: positive for приход, negative for расход
    amount: Mapped[float] = mapped_column(Numeric(18, 2))
    comment: Mapped[str | None] = mapped_column(String(512), nullable=True)
    reconciled: Mapped[bool] = mapped_column(default=False, index=True)
    reconciled_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    # id of the confirmation message in the author's own private chat, carrying the
    # "Откатить" button — the author's DM chat id equals their telegram_user_id.
    origin_message_id: Mapped[int | None] = mapped_column(nullable=True)

    account: Mapped["Account"] = relationship(back_populates="transactions")
    created_by: Mapped["User"] = relationship(back_populates="transactions")
