"""Export the currently persisted itinerary and trace without calling external services."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from travelmind_api.core.database import SessionLocal
from travelmind_api.db.models import Trip


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("trip_id")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    with SessionLocal() as session:
        trip = session.get(Trip, args.trip_id)
        if trip is None:
            raise RuntimeError("行程不存在")
        payload = {
            "created_at": datetime.now().astimezone().isoformat(),
            "trip_id": trip.id,
            "title": trip.title,
            "request": {
                "origin": trip.origin,
                "destination": trip.destination,
                "start_date": trip.start_date.isoformat(),
                "end_date": trip.end_date.isoformat(),
                "budget": float(trip.budget),
                "travelers": trip.travelers,
                "interests": trip.interests,
            },
            "final_itinerary": trip.itinerary_json,
            "final_agent_trace": trip.latest_agent_trace_json,
        }
    output = Path(args.output) if args.output else Path(".tmp/agent-audit") / f"{args.trip_id}-snapshot.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(output))


if __name__ == "__main__":
    main()
