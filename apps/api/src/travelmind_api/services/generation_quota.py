from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session

from travelmind_api.db.models import GenerationQuota, GenerationQuotaCharge, JobRecord


def lock_generation_quota(session: Session, user_id: str) -> bool:
    if session.get(GenerationQuota, user_id) is None:
        return False
    # A write (rather than SELECT FOR UPDATE) also serializes SQLite requests.
    # Keep this lock through idempotency lookup, debit and job insertion/commit.
    result = session.execute(
        update(GenerationQuota).where(GenerationQuota.user_id == user_id)
        .values(used=GenerationQuota.used).execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def consume_generation_quota(session: Session, user_id: str) -> None:
    result = session.execute(
        update(GenerationQuota)
        .where(GenerationQuota.user_id == user_id, GenerationQuota.used < GenerationQuota.generation_limit)
        .values(used=GenerationQuota.used + 1).execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        session.rollback()
        raise HTTPException(status_code=403, detail={
            "code": "generation_quota_exhausted",
            "message": "共享体验账户的 5 次行程生成额度已用尽，仍可查看已有行程。",
        })


def refund_failed_generation(session: Session, job: JobRecord) -> bool:
    """Caller commits the failed status, refund ledger and balance in one transaction.

    No inference from job type or a client payload: only an actual debit ledger
    entry can be refunded. The quota write lock serializes refunds with debits
    on both PostgreSQL and SQLite, including duplicate worker notifications.
    """
    if job.status != "failed" or not lock_generation_quota(session, job.owner_user_id):
        return False
    session.flush()
    charge = session.get(GenerationQuotaCharge, job.id, populate_existing=True)
    if charge is None or charge.user_id != job.owner_user_id or charge.refunded_at is not None:
        return False
    result = session.execute(
        update(GenerationQuota)
        .where(GenerationQuota.user_id == job.owner_user_id, GenerationQuota.used > 0)
        .values(used=GenerationQuota.used - 1).execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise RuntimeError("Generation quota ledger and balance are inconsistent")
    charge.refunded_at = datetime.now(timezone.utc)
    session.add(charge)
    return True
