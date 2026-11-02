from datetime import date, datetime, timezone, timedelta
from types import SimpleNamespace

import pytest

from travelmind_api.services.planning_time_constraints import planning_time_constraints


def request(generated, start=date(2026, 11, 2)):
    return SimpleNamespace(planning_generated_at=generated, start_date=start)


def test_same_day_boundary_matches_validator_minutes_and_includes_timezone():
    now = datetime(2026, 11, 2, 16, 53, 59, tzinfo=timezone(timedelta(hours=8)))
    policy = planning_time_constraints(request(now), SimpleNamespace(departure_transfer_minutes=45, station_buffer_minutes=30))
    assert policy['same_day_departure']['first_intercity_departure_not_before'] == '2026-11-02T18:38:00+08:00'
    assert policy['same_day_departure']['earliest_departure_day_offset'] == 0
    assert now.second == 59  # Does not mutate the request clock.


def test_late_generation_preserves_next_day_boundary_instead_of_wrapping_clock():
    now = datetime(2026, 11, 2, 23, 30)
    policy = planning_time_constraints(request(now), SimpleNamespace(departure_transfer_minutes=30, station_buffer_minutes=45))
    assert policy['same_day_departure']['first_intercity_departure_not_before'] == '2026-11-03T01:15:00'
    assert policy['same_day_departure']['earliest_departure_day_offset'] == 1


@pytest.mark.parametrize('generated,start', [(None, date(2026, 11, 2)), (datetime(2026, 11, 2, 16, 53), date(2026, 11, 3))])
def test_future_or_unknown_clock_does_not_invent_departure_constraint(generated, start):
    policy = planning_time_constraints(request(generated, start), SimpleNamespace(departure_transfer_minutes=45, station_buffer_minutes=30))
    assert 'same_day_departure' not in policy
    assert policy['flexible_windows_only_in_actual_gaps']
    assert policy['flexible_windows_must_not_overlap_items_or_each_other']
