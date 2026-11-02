from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session

from travelmind_api.db.models import GenerationQuota


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
