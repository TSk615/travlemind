from datetime import date,timedelta
from types import SimpleNamespace
import json

import pytest
from travelmind_api.agents.base import PlanningRequest
from travelmind_api.agents.langgraph_orchestrator import LangGraphOrchestrator
from travelmind_api.agents.runtime import WorkflowRuntime
from travelmind_api.services.llm.config import LlmConfig,LlmEndpointConfig
from travelmind_api.services.llm.client import OpenAICompatibleClient
from travelmind_api.services.llm.role_invoker import RoleInvocation,RoleInvocationResult,OpenAICompatibleRoleInvoker
from travelmind_api.services.planner_reliability import can_repair,repair_counts,repair_update,duplicate_visit_constraints


def plan(*,duplicate=False):
    days=[]
    for i,name in enumerate(['小公园','西堤公园','中山公园']):
        if duplicate and i==2:name='小公园'
        days.append({'title':f'第{i+1}天','summary':'城市步行','items':[{'type':'sight','name':name,'start_time':'10:00','end_time':'11:00','location':'汕头','score':0.8,'note':''}]})
    return {'summary':'汕头三日游','total_budget_estimate':300,'days':days,'risks':[]}


def context(monkeypatch,contents):
    start=date.today()+timedelta(days=5)
    request=PlanningRequest(trip_id='reliability-fixture',title='汕头',origin='汕头',destination='汕头',start_date=start,end_date=start+timedelta(days=2),budget=2000,travelers=1,interests=[],accommodation_preference='安静',pace='relaxed',transport_mode='public_transit')
    o=LangGraphOrchestrator(LlmConfig(base_url='https://fixture.invalid/v1',api_key='fixture',model='fixture'))
    o._workflow_request=request;o._workflow_runtime=WorkflowRuntime(run_id='reliability-fixture')
    calls=[]
    def invoke(role,payload):
        calls.append(payload)
        assert len(calls)<=len(contents),'Unexpected extra model invocation'
        return RoleInvocationResult(request_id='fixture-'+str(len(calls)),role_name=role,content=contents[len(calls)-1],model='fixture',provider_protocol='openai',wire_api='responses',endpoint_host='fixture.invalid',prompt_version='fixture',latency_ms=0,usage={'prompt_tokens':10,'completion_tokens':5,'total_tokens':15},request_count=1),None
    monkeypatch.setattr(o,'_invoke_workflow_role',invoke)
    # Keep the real duplicate invariant. Avoid unrelated route/ticket requirements.
    def validate(payload,*args,**kwargs):
        conflicts=duplicate_visit_constraints(payload.model_dump(mode='json'))
        if conflicts:raise ValueError('行程可执行性校验失败：POI“小公园”在第 1 天和第 3 天重复')
    monkeypatch.setattr(o,'_validate_execution_constraints',validate)
    state={'trip_request':{'destination':'汕头'},'planning_brief':{'destination':'汕头','trip_days':3},'poi_collection':{'pois':[]},'poi_grounding':{},'weather_guidance':{'overall_outlook':'未知'},'hotel_recommendation':{},'transport_guidance':{}}
    return o,state,calls


def test_format_failure_retains_one_semantic_repair_and_finishes_in_three_calls(monkeypatch):
    o,s,calls=context(monkeypatch,['{"days":[',json.dumps(plan(duplicate=True)),json.dumps(plan())])
    s.update(o.draft_itinerary(s));s.update(o.validate_itinerary(s));s.update(o.repair_itinerary(s))
    assert repair_counts(s)==(1,0)
    s.update(o.validate_itinerary(s));assert s['validation_errors'] and can_repair(s,'semantic')
    s.update(o.repair_itinerary(s));s.update(o.validate_itinerary(s))
    assert not s['validation_errors'] and repair_counts(s)==(1,1) and s['repair_count']==2
    assert len(calls)==3 and len(s['planner_attempts'])==3
    assert calls[2]['duplicate_visit_constraints'][0]['poi_name']=='小公园'
    assert not can_repair(s,'semantic') and not can_repair(s,'format')
    with pytest.raises(ValueError,match='budget exhausted'):o.repair_itinerary(s)


def test_repeated_invalid_json_stops_after_two_calls(monkeypatch):
    o,s,calls=context(monkeypatch,['{"days":[','{"days":['])
    s.update(o.draft_itinerary(s));s.update(o.validate_itinerary(s));s.update(o.repair_itinerary(s))
    with pytest.raises(ValueError,match='budget exhausted'):o.validate_itinerary(s)
    assert len(calls)==2


def test_unfixed_content_stops_after_bounded_third_call(monkeypatch):
    duplicate=json.dumps(plan(duplicate=True))
    o,s,calls=context(monkeypatch,['{"days":[',duplicate,duplicate])
    s.update(o.draft_itinerary(s));s.update(o.validate_itinerary(s));s.update(o.repair_itinerary(s));s.update(o.validate_itinerary(s));s.update(o.repair_itinerary(s))
    with pytest.raises(ValueError,match='budget exhausted'):o.validate_itinerary(s)
    assert len(calls)==3 and repair_counts(s)==(1,1)


def test_invalid_semantic_repair_does_not_gain_whole_plan_retry(monkeypatch):
    o,s,calls=context(monkeypatch,[json.dumps(plan(duplicate=True)),'{"days":['])
    s.update(o.draft_itinerary(s));s.update(o.validate_itinerary(s));s.update(o.repair_itinerary(s))
    with pytest.raises(ValueError,match='budget exhausted'):o.validate_itinerary(s)
    assert len(calls)==2


def test_legacy_saved_format_repair_keeps_content_budget():
    old={'repair_count':1,'planner_attempts':[{'parse_error':{'code':'invalid_or_truncated_json'}},{'parse_error':None}]}
    assert repair_counts(old)==(1,0) and can_repair(old,'semantic')
    assert repair_update(old)=={'format_repair_count':1,'semantic_repair_count':1,'repair_count':2}
    assert not can_repair({'repair_count':1},'semantic')


@pytest.mark.parametrize('wire_api',['responses','chat_completions'])
def test_planner_json_object_mode_uses_correct_wire_field(wire_api):
    c=OpenAICompatibleClient(LlmEndpointConfig(base_url='https://fixture.invalid/v1',api_key='fixture',model='fixture',wire_api=wire_api))
    c.json_object_mode=True
    p=c._build_text_payload(messages=[{'role':'system','content':'JSON'}],temperature=0,max_tokens=100,wire_api=wire_api)
    assert (p['text']['format'] if wire_api=='responses' else p['response_format'])=={'type':'json_object'}
    c.json_object_mode=False
    p=c._build_text_payload(messages=[],temperature=0,max_tokens=None,wire_api=wire_api)
    assert 'text' not in p and 'response_format' not in p


@pytest.mark.parametrize('role,expected',[('itinerary_planner',True),('poi_specialist',False),('brief_parser',False)])
def test_json_mode_does_not_change_research_conversations(role,expected):
    class Client:
        last_citations=[];last_usage=None;last_retry_count=0;last_request_count=1
        def create_chat_completion(self,**kwargs):
            assert self.json_object_mode is expected
            if expected:assert 'JSON' in kwargs['messages'][0]['content']
            return '{}'
    endpoint=LlmEndpointConfig(base_url='https://fixture.invalid/v1',api_key='fixture',model='fixture',provider_protocol='newapi')
    OpenAICompatibleRoleInvoker(client_factory=lambda config:Client()).invoke(RoleInvocation(role_name=role,prompt_version='fixture',system_prompt='planner',input_payload={},endpoint=endpoint))


def test_real_graph_preserves_separate_budgets_across_validation_nodes(monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver
    from travelmind_api.agents.workflows.trip_generation import build_trip_generation_graph
    o, initial, calls = context(monkeypatch, ['{"days":[', json.dumps(plan(duplicate=True)), json.dumps(plan())])
    noop = lambda state: {}
    operations = SimpleNamespace(check_cancelled=lambda: None, parse_brief=noop,
        research_pois=noop, research_weather=noop, join_initial_research=noop,
        research_hotels=noop, research_transport=noop, verify_evidence=noop,
        verify_selected_operations=noop, draft_itinerary=o.draft_itinerary,
        validate_itinerary=o.validate_itinerary, repair_itinerary=o.repair_itinerary,
        assemble_result=lambda state: {"planning_result": {"validated": not state['validation_errors']}})
    graph = build_trip_generation_graph(operations, checkpointer=InMemorySaver())
    final = graph.invoke(initial, config={"configurable": {"thread_id": "reliability-budget-integration"}})
    assert final['planning_result']['validated'] is True
    assert repair_counts(final) == (1, 1) and len(calls) == 3
    assert len(final['planner_attempts']) == 3


def test_duplicate_json_keys_are_rejected_without_checkpointing_raw_output(monkeypatch):
    bad = '{"summary":"private-model-text", "summary":"conflict", "days":[]}'
    o, state, calls = context(monkeypatch, [bad, json.dumps(plan())])
    state.update(o.draft_itinerary(state))
    assert state['planning_parse_error']['code'] == 'duplicate_key'
    assert 'private-model-text' not in json.dumps(state)
    state.update(o.validate_itinerary(state));state.update(o.repair_itinerary(state));state.update(o.validate_itinerary(state))
    assert not state['validation_errors'] and len(calls) == 2


@pytest.mark.parametrize('wire',['responses','chat_completions'])
def test_strict_schema_wins_over_json_mode(wire):
    c=OpenAICompatibleClient(LlmEndpointConfig(base_url='https://fixture.invalid/v1',api_key='fixture',model='fixture'))
    c.json_object_mode=True;c.structured_output_schema={'type':'object','properties':{},'required':[],'additionalProperties':False}
    payload=c._build_text_payload(messages=[],temperature=0,max_tokens=None,wire_api=wire)
    fmt=payload['text']['format'] if wire=='responses' else payload['response_format']['json_schema']
    assert fmt['strict'] is True and fmt['schema']==c.structured_output_schema


def test_strict_patch_field_operations_preserve_unaffected_fields():
    from travelmind_api.services.planner_slot_repair import prepare_slot_repair,SlotRepairError
    original=plan()
    contract=prepare_slot_repair({'previous_itinerary':original,'repair_targets':[{'item_ref':'d1i1'}]})
    schema=contract.payload['structured_output_schema']
    def check(node):
        if isinstance(node,dict):
            if node.get('type')=='object':
                assert node['additionalProperties'] is False
                assert set(node['required'])==set(node['properties'])
            for value in node.values():check(value)
        if isinstance(node,list):
            for value in node:check(value)
    check(schema)
    merged,audit=contract.apply(json.dumps({'item_operations':[{'item_ref':'d1i1','field':'name','value':'新景点'},{'item_ref':'d1i1','field':'note','value':'有来源的候选'}],'day_updates':[]}))
    assert merged['days'][0]['items'][0]['name']=='新景点'
    assert merged['days'][1:]==original['days'][1:]
    with pytest.raises(SlotRepairError,match='duplicate_operation'):
        contract.apply(json.dumps({'item_operations':[{'item_ref':'d1i1','field':'name','value':'a'},{'item_ref':'d1i1','field':'name','value':'b'}]}))
    with pytest.raises(SlotRepairError,match='unauthorized_operation'):
        contract.apply(json.dumps({'item_operations':[{'item_ref':'d2i1','field':'name','value':'a'}]}))
