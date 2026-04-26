"""
Money helpers — Decimal-based amounts with 2dp quantization and a single
canonical currency (USD, see settings.default_currency).

Phase 2 policy:
- All monetary inputs/outputs from new code should go through `Money`.
- Persistence adds `*_cents` integer fields alongside existing floats.
- F5: frontend `formatMoney({amount_cents, currency})` is the read path.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Union

Numeric = Union[int, float, str, Decimal]

TWO_PLACES = Decimal("0.01")


class Money:
    __slots__ = ("amount", "currency")

    def __init__(self, amount: Numeric, currency: str = "USD"):
        # Plain class (not a frozen dataclass) so the module can be imported
        # via `importlib.util.spec_from_file_location` in tests and scripts
        # without tripping over the dataclass KW_ONLY type probe.
        self.amount = Money._quantize(amount)
        self.currency = (currency or "USD").upper()

    def __repr__(self) -> str:
        return f"Money({self.amount!r}, {self.currency!r})"

    def __eq__(self, other) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self.amount == other.amount and self.currency == other.currency

    def __hash__(self) -> int:
        return hash((self.amount, self.currency))

    # ---------- constructors ----------
    @staticmethod
    def _quantize(v: Numeric) -> Decimal:
        if isinstance(v, Decimal):
            d = v
        else:
            d = Decimal(str(v))
        return d.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

    @classmethod
    def from_cents(cls, cents: int, currency: str = "USD") -> "Money":
        return cls(Decimal(int(cents)) / Decimal(100), currency)

    @classmethod
    def from_float(cls, value: Numeric, currency: str = "USD") -> "Money":
        return cls(cls._quantize(value), currency)

    @classmethod
    def zero(cls, currency: str = "USD") -> "Money":
        return cls(Decimal("0.00"), currency)

    # ---------- outputs ----------
    def to_cents(self) -> int:
        return int((self.amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    def to_float(self) -> float:
        return float(self.amount)

    def to_revel_string(self) -> str:
        """Revel's REST API accepts stringified decimals, 2dp."""
        return f"{self.amount:.2f}"

    def __str__(self) -> str:
        return f"{self.currency} {self.amount:.2f}"

    # ---------- arithmetic ----------
    def _check(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise ValueError(f"currency mismatch: {self.currency} vs {other.currency}")

    def __add__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, factor: Numeric) -> "Money":
        return Money(self._quantize(self.amount * Decimal(str(factor))), self.currency)

    __rmul__ = __mul__

    def __lt__(self, other: "Money") -> bool:
        self._check(other)
        return self.amount < other.amount

    def __le__(self, other: "Money") -> bool:
        self._check(other)
        return self.amount <= other.amount


def dollars_to_cents(value: Numeric) -> int:
    """Convert a float/string/Decimal dollars value into integer cents."""
    return Money.from_float(value).to_cents()


def cents_to_dollars(cents: int) -> float:
    return Money.from_cents(int(cents)).to_float()
