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
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class TransactionDraft:
    account_id: int
    direction: str  # "income" | "expense"
    amount: Decimal
    comment: str | None
    actor_telegram_id: int


_drafts: dict[str, TransactionDraft] = {}


def create_draft(
    *, account_id: int, direction: str, amount: Decimal, comment: str | None, actor_telegram_id: int
) -> str:
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
    return _drafts.get(draft_id)


def pop_draft(draft_id: str) -> TransactionDraft | None:
    return _drafts.pop(draft_id, None)
