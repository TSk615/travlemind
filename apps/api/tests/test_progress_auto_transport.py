from concurrent.futures import ThreadPoolExecutor
import pytest
from travelmind_api.core.database import SessionLocal
from travelmind_api.db.models import JobRecord
from travelmind_api.jobs.handlers import _emit_agent_progress
from travelmind_api.services.job_service import create_job, update_job_state, serialize_job
from travelmind_api.services.transport_selection import transport_selection_policy, prefer_rail_followup
from travelmind_api.services.trip_intake_service import normalize_intake_draft
from travelmind_api.agents.planning_core import PlanningCore
from travelmind_api.services.planning.role_models import PlanningBrief
from travelmind_api.api.schemas.trips import TripCreateRequest
from test_api_contracts import _create_trip
from test_demo_quota import _demo
from test_langgraph_migration import _request

@pytest.mark.parametrize('mode', ['auto','rail','flight','car','walking','mixed'])
def test_intake_preserves_all_transport_choices(mode):
    assert normalize_intake_draft({'transport_mode':mode})['transport_mode'] == mode

@pytest.mark.parametrize('mode', ['auto','mixed','flight','car','walking',''])
def test_automatic_or_nonrail_choice_never_forces_rail_followup(mode):
    assert not prefer_rail_followup({'trip_request':{'transport_mode':mode}})

def test_explicit_rail_and_same_city_policy():
    assert prefer_rail_followup({'trip_request':{'transport_mode':'rail'}})
    assert not prefer_rail_followup({'trip_request':{'transport_mode':'rail'},'transport_context':{'intercity_required':False}})
    assert transport_selection_policy('auto',same_city=True)['compare_modes'] == []
    assert TripCreateRequest.model_fields['transport_mode'].default == 'auto'

@pytest.mark.parametrize('mode,expected', [('auto',['rail','flight']),('flight',['flight']),('rail',['rail'])])
def test_transport_research_receives_comparison_policy_without_overriding_preference(mode, expected):
    request=_request().model_copy(update={"transport_mode":mode})
    payload=PlanningCore(None)._build_transport_research_payload(request,PlanningBrief(destination=request.destination, trip_days=2))
    context=payload['transport_context']
    assert context['transport_mode'] == mode
    assert context['selection_policy']['compare_modes'] == expected
    assert context['selection_policy']['unverified_fares_must_remain_unknown']
    if mode == 'auto': assert 'comparison' in PlanningCore(None)._transport_focus_for_mode(mode)


def test_parallel_progress_keeps_each_event_and_never_decreases(client,monkeypatch):
    user=_demo(client,monkeypatch)
    trip=_create_trip(client).json()['data']['id']
    with SessionLocal() as s:
        job=create_job(s,job_type='trip.generate',owner_user_id=user,trip_id=trip,payload={}); job_id=job.id
    _emit_agent_progress(job_id,'poi_specialist','POI specialist','internal',44)
    _emit_agent_progress(job_id,'weather_specialist','Weather specialist','internal',52)
    def finish(index):
        _emit_agent_progress(job_id,('weather_specialist' if index%2 else 'poi_specialist')+':completed','','',0)
    with ThreadPoolExecutor(max_workers=4) as pool: list(pool.map(finish,range(8)))
    with SessionLocal() as s:
        job=s.get(JobRecord,job_id)
        assert len(job.timeline_json)==11
        assert job.progress_percent==52
        stages=[row.stage for row in serialize_job(job).timeline_json]
        assert 'role.weather_specialist.completed' in stages
        assert 'role.poi_specialist.completed' in stages
        update_job_state(s,job_id,status='completed',progress_percent=100,skip_if_terminal=True);s.commit()
    _emit_agent_progress(job_id,'weather_specialist:completed','','',0)
    with SessionLocal() as s:
        job=s.get(JobRecord,job_id)
        assert job.status=='completed' and job.progress_percent==100
        assert len(job.timeline_json)==12

@pytest.mark.parametrize('method,role,content', [
    ('research_weather','weather_specialist','{"overall_outlook":"天气参考"}'),
    ('research_hotels','hotel_specialist','{}'),
    ('research_transport','transport_specialist','{}'),
])
@pytest.mark.parametrize('valid', [True,False])
def test_research_completion_is_emitted_only_after_response_parses(method,role,content,valid):
    from types import SimpleNamespace
    from travelmind_api.agents.langgraph_orchestrator import LangGraphOrchestrator
    from travelmind_api.agents.runtime import WorkflowRuntime
    events=[]
    runner=LangGraphOrchestrator.__new__(LangGraphOrchestrator)
    runner._runtime=lambda:WorkflowRuntime(run_id='offline-progress',progress_callback=lambda *args:events.append(args))
    runner._request=_request
    runner._validate_weather_date_coverage=lambda *args:None
    runner._build_weather_research_payload=lambda *args,**kwargs:{}
    runner._build_hotel_research_payload=lambda *args,**kwargs:{}
    runner._build_transport_research_payload=lambda *args,**kwargs:{}
    result=SimpleNamespace(content=content if valid else 'not JSON',citations=[],checkpoint_metadata=lambda:{})
    runner._invoke_workflow_role=lambda *args,**kwargs:(result,{})
    state={'planning_brief':{'destination':'京都','trip_days':2},'poi_collection':{}}
    if valid:
        getattr(runner,method)(state)
        assert [event[0] for event in events]==[role+':completed']
    else:
        with pytest.raises(ValueError):getattr(runner,method)(state)
        assert not events

@pytest.mark.parametrize('departure,arrival,dep_time,arr_time,expected', [
    ('2026-11-07','2026-11-08','19:33','06:42',False),
    ('2026-11-07',None,'19:33','06:42',False),
    ('2026-11-07','2026-11-07','08:00','18:00',True),
    ('2026-11-07','2026-11-07','18:00','21:00',True),
    ('2026-11-06','2026-11-07','19:33','06:42',True),
])
def test_return_arrival_is_inside_trip_not_just_departure(departure,arrival,dep_time,arr_time,expected):
    from travelmind_api.services.transport_selection import transport_candidate_fits_dates
    candidate={'departure_date':departure,'arrival_date':arrival,'departure_time':dep_time,'arrival_time':arr_time}
    assert transport_candidate_fits_dates(candidate,'2026-11-05','2026-11-07') is expected


def test_captured_d921_overnight_failure_is_quarantined_without_faking_dates_or_relaxing_validation():
    from travelmind_api.services.transport_selection import constrain_transport_dates
    from travelmind_api.services.planning.role_models import TransportGuidance
    candidate={'scope':'return','mode':'rail','service_number':'D921','origin':'北京西','destination':'广州南','departure_date':'2026-11-07','departure_time':'19:33','arrival_date':'2026-11-08','arrival_time':'06:42','duration_minutes':669,'schedule_checked_at':'2026-11-04T14:24:23+00:00','source_url':'https://www.12306.cn/index/'}
    guidance=TransportGuidance.model_validate({'service_candidates':[candidate],'legs':[{'scope':'return','origin':'北京西','destination':'广州南','departure_date':'2026-11-07','arrival_date':'2026-11-08','mode':'rail','passenger_count':2}]})
    safe=constrain_transport_dates(guidance,'2026-11-05','2026-11-07')
    assert not safe.service_candidates and not safe.legs
    assert guidance.service_candidates[0].arrival_date.isoformat()=='2026-11-08'
    assert '不得延长日期' in safe.notes[-1]
    assert constrain_transport_dates(safe,'2026-11-05','2026-11-07').notes==safe.notes
