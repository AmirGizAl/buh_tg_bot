import ast
import operator
import re
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from html import escape as html_escape

from bot.config import MSK

TWO_PLACES = Decimal("0.01")

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def safe_eval_expr(expr: str) -> Decimal:
    """Evaluate a plain arithmetic expression (+ - * / and unary +/-) into a Decimal.

    Never uses eval()/exec(). Walks the parsed AST and only accepts number literals,
    binary +-*/ and unary +/- — any other node (names, calls, attributes, comparisons,
    power, literals other than numbers, ...) raises ValueError. This is the only
    entry point that should ever be used to turn user-typed text into a number."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ValueError("Invalid expression") from exc
    try:
        return _eval_node(tree.body)
    except (ZeroDivisionError, TypeError) as exc:
        raise ValueError("Invalid expression") from exc


def _eval_node(node: ast.AST) -> Decimal:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("Invalid expression")
        return Decimal(str(node.value))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        return _BIN_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand))
    raise ValueError("Invalid expression")


def parse_amount_and_comment(text: str) -> tuple[Decimal, str | None]:
    """Parse "[sum] [comment]" input: sum is a number or arithmetic expression up to
    the first whitespace, the rest of the line (verbatim) is an optional comment."""
    stripped = text.strip()
    if not stripped:
        raise ValueError("Empty input")
    parts = re.split(r"\s+", stripped, maxsplit=1)
    expr = parts[0].replace(",", ".")
    comment = parts[1].strip() if len(parts) > 1 else None
    comment = comment or None

    try:
        value = safe_eval_expr(expr).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError("Invalid number") from exc
    if value <= 0:
        raise ValueError("Amount must be positive")
    return value, comment


def format_amount(value, force_sign: bool = False) -> str:
    d = Decimal(str(value)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    if d < 0:
        sign = "-"
    elif force_sign and d > 0:
        sign = "+"
    else:
        sign = ""
    d = abs(d)
    int_part, frac_part = f"{d:,.2f}".split(".")
    int_part = int_part.replace(",", ".")
    return f"{sign}{int_part},{frac_part}"


def to_msk(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(MSK)


def fmt_dt(dt: datetime) -> str:
    return to_msk(dt).strftime("%Y-%m-%d %H:%M:%S MSK")


def fmt_date(dt: datetime) -> str:
    return to_msk(dt).strftime("%Y-%m-%d")


def fmt_time(dt: datetime) -> str:
    return to_msk(dt).strftime("%H:%M:%S")


def actor_label(user) -> str:
    if user.username_display:
        return f"@{user.username_display}"
    if user.full_name:
        return user.full_name
    return str(user.telegram_user_id or user.id)


def esc(text) -> str:
    return html_escape(str(text))
