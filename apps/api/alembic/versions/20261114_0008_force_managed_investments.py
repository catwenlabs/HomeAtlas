"""force managed investments: every investment needs an investment account

Revision ID: 0008_force_managed
Revises: 0007_phase_2c_3
Create Date: 2026-11-14

Legacy unmanaged investments are migrated onto one investment account per
(household, currency). The account receives an opening-balance transaction
equal to the sum of the migrated principals, so the net-worth formula
(account balance + current_value - principal) is unchanged by the migration.
"""

from collections.abc import Sequence
from decimal import Decimal
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision: str = "0008_force_managed"
down_revision: str | None = "0007_phase_2c_3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MIGRATED_ACCOUNT_NAME = "投资账户（迁移）"
MIGRATED_OPENING_DESCRIPTION = "迁移：投资账户期初余额"


def _latest_rate(connection: sa.Connection, household_id: object, base: str, quote: str) -> Decimal:
    """Resolve 1 base = <rate> quote; mirror the service lookup rules."""
    if base == quote:
        return Decimal("1")
    direct = connection.execute(
        sa.text(
            """
            SELECT rate
            FROM finance.exchange_rates
            WHERE household_id = :household_id
              AND base_currency = :base
              AND quote_currency = :quote
              AND rate_date <= CURRENT_DATE
            ORDER BY rate_date DESC, created_at DESC
            LIMIT 1
            """
        ),
        {"household_id": household_id, "base": base, "quote": quote},
    ).first()
    if direct is not None:
        return Decimal(direct[0])
    inverse = connection.execute(
        sa.text(
            """
            SELECT rate
            FROM finance.exchange_rates
            WHERE household_id = :household_id
              AND base_currency = :quote
              AND quote_currency = :base
              AND rate_date <= CURRENT_DATE
            ORDER BY rate_date DESC, created_at DESC
            LIMIT 1
            """
        ),
        {"household_id": household_id, "base": base, "quote": quote},
    ).first()
    if inverse is not None:
        return Decimal(1) / Decimal(inverse[0])
    # Migration must not invent exchange data; 1 keeps the row internally
    # consistent and the user can correct the rate later.
    return Decimal("1")


def upgrade() -> None:
    connection = op.get_bind()

    # Snapshots with no principal still need a cost basis for the new
    # account balance: derive it from the registered holdings when possible.
    connection.execute(
        sa.text(
            """
            UPDATE finance.investments AS i
            SET principal = h.cost
            FROM (
                SELECT investment_id, SUM(quantity * cost_price) AS cost
                FROM finance.holdings
                GROUP BY investment_id
            ) AS h
            WHERE i.account_id IS NULL
              AND i.principal = 0
              AND i.status <> 'redeemed'
              AND h.investment_id = i.id
              AND h.cost > 0
            """
        )
    )
    # Redeemed snapshots are impossible through the API; zero the basis so
    # they cannot inflate the migrated account balance.
    connection.execute(
        sa.text(
            """
            UPDATE finance.investments
            SET principal = 0
            WHERE account_id IS NULL AND status = 'redeemed'
            """
        )
    )

    groups = connection.execute(
        sa.text(
            """
            SELECT household_id, currency, SUM(principal) AS principal
            FROM finance.investments
            WHERE account_id IS NULL
            GROUP BY household_id, currency
            ORDER BY household_id, currency
            """
        )
    ).all()

    for household_id, currency, principal in groups:
        account_id = uuid4()
        connection.execute(
            sa.text(
                """
                INSERT INTO core.accounts
                    (id, household_id, name, account_type, currency, is_active)
                VALUES
                    (:id, :household_id, :name, 'investment', :currency, true)
                """
            ),
            {
                "id": account_id,
                "household_id": household_id,
                "name": MIGRATED_ACCOUNT_NAME,
                "currency": currency,
            },
        )
        connection.execute(
            sa.text(
                """
                UPDATE finance.investments
                SET account_id = :account_id
                WHERE household_id = :household_id
                  AND currency = :currency
                  AND account_id IS NULL
                """
            ),
            {
                "account_id": account_id,
                "household_id": household_id,
                "currency": currency,
            },
        )

        amount = Decimal(principal or 0)
        if amount == 0:
            continue
        base_currency = connection.execute(
            sa.text("SELECT base_currency FROM core.households WHERE id = :id"),
            {"id": household_id},
        ).scalar_one()
        rate = _latest_rate(
            connection, household_id, str(currency).strip(), str(base_currency).strip()
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO finance.transactions
                    (id, household_id, account_id, transaction_type, amount,
                     currency, base_amount, base_currency, exchange_rate,
                     exchange_rate_date, transaction_date, description,
                     source, status)
                VALUES
                    (:id, :household_id, :account_id, 'opening_balance',
                     :amount, :currency, :base_amount, :base_currency,
                     :exchange_rate, CURRENT_DATE, now(), :description,
                     'manual', 'confirmed')
                """
            ),
            {
                "id": uuid4(),
                "household_id": household_id,
                "account_id": account_id,
                "amount": amount,
                "currency": currency,
                "base_amount": amount * rate,
                "base_currency": base_currency,
                "exchange_rate": rate,
                "description": MIGRATED_OPENING_DESCRIPTION,
            },
        )

    op.alter_column(
        "investments",
        "account_id",
        existing_type=sa.Uuid(),
        nullable=False,
        schema="finance",
    )


def downgrade() -> None:
    op.alter_column(
        "investments",
        "account_id",
        existing_type=sa.Uuid(),
        nullable=True,
        schema="finance",
    )
