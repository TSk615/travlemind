"""Map internal errors to a small, safe public contract; never echo log text."""


def public_job_error_code(status: str, message: str | None) -> str | None:
    if status != "failed":
        return None
    text = (message or "").casefold()
    if "今天已经没有足够的行程生成与准备时间" in text:
        return "same_day_planning_window_closed"
    if "行程开始日期" in text and "已经过期" in text:
        return "expired_trip_start_date"
    if 'poi“' in text and "重复" in text and "行程可执行性校验失败：" in text:
        return "planning_duplicate_poi"
    if "行程可执行性校验失败：" in text or "itinerary still failed deterministic validation" in text:
        return "planning_validation_failed"
    if any(token in text for token in ("schema_validation_failed", "duplicate_key", "planner slot repair rejected", "planner output still invalid", "planner repair budget exhausted")):
        return "planning_validation_failed"
    return "job_failed"
