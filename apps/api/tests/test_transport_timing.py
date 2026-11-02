from datetime import date
from types import SimpleNamespace as NS

from travelmind_api.services.transport_timing import service_timing_errors
from travelmind_api.services.execution_validation import validate_timeline


def item(**updates):
    base = dict(name='铁路建议窗口', type='transport', start_time='22:22', end_time='00:16', end_day_offset=1, note='',
                visit_requirements=None, booking_info=NS(duration_minutes_min=None, transport_scope='outbound', schedule_verified=False, service_number='', notes=[]))
    base.update(updates)
    return NS(**base)


def candidate(**updates):
    base = dict(scope='outbound', departure_date=date(2026,11,2), arrival_date=date(2026,11,3), service_number='D123', departure_time='22:22', arrival_time='00:16', evidence_status='verified')
    base.update(updates)
    return NS(**base)


def test_unknown_cross_midnight_window_is_not_rejected_by_aggregate_route_arrival_date():
    trip_item=item()
    route=NS(scope='outbound', departure_date=date(2026,11,2), arrival_date=date(2026,11,2), duration_minutes_min=114)
    transport=NS(legs=[route], service_candidates=[], station_buffer_minutes=40)
    request=NS(start_date=date(2026,11,2), planning_generated_at=None)
    payload=NS(days=[NS(items=[trip_item]), NS(items=[])])
    assert validate_timeline(payload,request,transport)==[]
    assert trip_item.booking_info.schedule_verified is False and trip_item.end_day_offset==1


def test_route_duration_remains_a_hard_constraint_for_unknown_windows():
    trip_item=item(end_time='23:00',end_day_offset=0)
    route=NS(scope='outbound', departure_date=date(2026,11,2), arrival_date=date(2026,11,2), duration_minutes_min=114)
    transport=NS(legs=[route], service_candidates=[], station_buffer_minutes=40)
    errors=validate_timeline(NS(days=[NS(items=[trip_item])]),NS(start_date=date(2026,11,2),planning_generated_at=None),transport)
    assert any('短于交通专家线路耗时' in e for e in errors)


def test_selected_sourced_service_still_binds_exact_clocks_and_arrival_date():
    trip_item=item()
    booking=NS(transport_scope='outbound', service_number='D123', schedule_verified=True)
    transport=NS(service_candidates=[candidate()])
    assert service_timing_errors(trip_item,booking,transport,date(2026,11,2),date(2026,11,3))==[]
    trip_item.end_time='23:59'
    errors=service_timing_errors(trip_item,booking,transport,date(2026,11,2),date(2026,11,2))
    assert len(errors)==2


def test_fabricated_verified_service_is_rejected_not_downgraded_by_validator():
    booking=NS(transport_scope='outbound', service_number='FAKE123', schedule_verified=True)
    assert service_timing_errors(item(),booking,NS(service_candidates=[]),date(2026,11,2),date(2026,11,3))
    booking.service_number=''
    assert service_timing_errors(item(),booking,NS(service_candidates=[]),date(2026,11,2),date(2026,11,3))


def test_conflicting_sourced_service_times_fail_closed():
    booking=NS(transport_scope='outbound', service_number='D123', schedule_verified=True)
    transport=NS(service_candidates=[candidate(),candidate(arrival_time='00:30')])
    assert '互相冲突' in service_timing_errors(item(),booking,transport,date(2026,11,2),date(2026,11,3))[0]
