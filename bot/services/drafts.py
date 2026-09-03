"""In-memory registry for pending transaction drafts (Приход/Расход awaiting
"Сохранить"/"Отмена").

A draft is intentionally NOT tracked via the per-user FSM state: aiogram's FSMContext
holds exactly one "current state" per user, so if a draft's confirmation used a
state-gated handler, starting any other action (another transaction, "Сверить",
account management, ...) would overwrite that state and silently strand the draft —
its buttons would stop responding, even though they're still visible in the chat.

Instead each draft gets its own id, embedded directly in the "Сохранить"/"Отмена"
button's callback_data (see bot/keyboards/inline.py:draft_keyboard). The handlers in
bot/handlers/transactions.py are filtered purely on that callback_data, independent of
FSM state, so a draft stays fully functional — findable and actionable — no matter
what the user does elsewhere in the meantime, until it's explicitly confirmed or
cancelled. Same lifetime caveat as the FSM's own MemoryStorage: a draft is in-process
memory only and is lost if the bot restarts before it's resolved.

A draft normally leaves this registry the moment it's confirmed or cancelled — but one
that's simply forgotten (nobody ever presses either button) would otherwise sit here
forever, growing unboundedly over a long container uptime. DRAFT_TTL bounds that: a
draft older than this is treated as gone the next time anyone touches the registry, so
memory use stays capped by "drafts created in the last DRAFT_TTL", not by total uptime.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# Generous enough to cover "waiting for the client to confirm" (the whole reason drafts
# outlive the FSM at all) without letting a truly-forgotten draft linger indefinitely.
# Matches the Telegram message-edit window (48h) already referenced elsewhere in this
# codebase (rollback/reconcile), so it reads as one consistent "how long we still care"
# horizon rather than an arbitrary second number.
DRAFT_TTL = timedelta(hours=48)


@dataclass(frozen=True)
class TransactionDraft:
    account_id: int
    direction: str  # "income" | "expense"
    amount: Decimal
    comment: str | None
    actor_telegram_id: int
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_drafts: dict[str, TransactionDraft] = {}


def _evict_expired() -> None:
    cutoff = datetime.now(timezone.utc) - DRAFT_TTL
    expired_ids = [draft_id for draft_id, draft in _drafts.items() if draft.created_at < cutoff]
    for draft_id in expired_ids:
        _drafts.pop(draft_id, None)


def create_draft(
    *, account_id: int, direction: str, amount: Decimal, comment: str | None, actor_telegram_id: int
) -> str:
    _evict_expired()
    draft_id = uuid.uuid4().hex[:10]
    _drafts[draft_id] = TransactionDraft(
        account_id=account_id,
        direction=direction,
        amount=amount,
        comment=comment,
        actor_telegram_id=actor_telegram_id,
    )
    return draft_id


def get_draft(draft_id: str) -> TransactionDraft | None:
    _evict_expired()
    return _drafts.get(draft_id)


def pop_draft(draft_id: str) -> TransactionDraft | None:
    return _drafts.pop(draft_id, None)
