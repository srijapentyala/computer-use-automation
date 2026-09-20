"""In-memory teller data for the Heritage Core stand-in."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Account:
    number: str
    product: str
    balance: float


@dataclass
class Member:
    member_id: str
    name: str
    ssn_last4: str
    status: str
    opened: str
    accounts: list[Account] = field(default_factory=list)


MEMBERS: dict[str, Member] = {
    "12345": Member(
        member_id="12345",
        name="Jane A. Doe",
        ssn_last4="4421",
        status="active",
        opened="2014-03-12",
        accounts=[
            Account("SV-001122", "Savings", 2450.00),
            Account("CK-009988", "Checking", 180.22),
        ],
    ),
    "67890": Member(
        member_id="67890",
        name="Robert Chen",
        ssn_last4="1188",
        status="active",
        opened="2019-07-01",
        accounts=[
            Account("SV-004400", "Savings", 87.15),
        ],
    ),
    "11111": Member(
        member_id="11111",
        name="Closed Membership",
        ssn_last4="0000",
        status="closed",
        opened="2008-01-09",
        accounts=[
            Account("SV-000001", "Savings", 0.00),
        ],
    ),
}

VALID_USER = "teller"
VALID_PASSWORD = "teller"


def money(value: float) -> str:
    return f"${value:,.2f}"
