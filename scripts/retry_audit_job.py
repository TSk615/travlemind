"""Retry a failed trip.generate job from its persisted role checkpoint."""
from __future__ import annotations

import argparse
import json

from travelmind_api.core.database import SessionLocal
from travelmind_api.db.models import JobRecord
from travelmind_api.jobs.handlers import process_job
from travelmind_api.services.job_service import create_job, extract_resume_checkpoint
from travelmind_api.jobs import handlers as handlers_module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id")
    parser.add_argument(
        "--main-wire-api",
        choices=("responses", "chat_completions"),
        default="",
        help="Temporarily override the primary planner wire API for this retry.",
    )
    args = parser.parse_args()
    if args.main_wire_api:
        original_resolve_llm_config = handlers_module._resolve_llm_config

        def retry_resolve_llm_config(user, payload):
            config = original_resolve_llm_config(user, payload)
            if config is None:
                return None
            return config.model_copy(update={"wire_api": args.main_wire_api})

        handlers_module._resolve_llm_config = retry_resolve_llm_config
    with SessionLocal() as session:
        source = session.get(JobRecord, args.job_id)
        if source is None or source.status != "failed" or source.type != "trip.generate":
            raise RuntimeError("来源任务必须是失败的 trip.generate")
        checkpoint = extract_resume_checkpoint(source)
        if checkpoint is None:
            raise RuntimeError("来源任务没有恢复检查点")
        source_payload = source.payload_json if isinstance(source.payload_json, dict) else {}
        payload = {key: value for key, value in source_payload.items() if key not in {"resume_checkpoint", "resume_from_job_id"}}
        payload.update({"trip_id": source.trip_id, "resume_from_job_id": source.id, "resume_checkpoint": checkpoint})
        retry = create_job(session, job_type="trip.generate", owner_user_id=source.owner_user_id,
                           trip_id=source.trip_id, payload=payload, max_attempts=1)
        retry_id = retry.id
    process_job(retry_id)
    with SessionLocal() as session:
        result = session.get(JobRecord, retry_id)
        print(json.dumps({"job_id": retry_id, "trip_id": result.trip_id, "status": result.status,
                          "error": result.error_message, "result": result.result_json}, ensure_ascii=False))


if __name__ == "__main__":
    main()
