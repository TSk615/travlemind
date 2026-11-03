"""Regression coverage for schema failures previously reduced to one blind code."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from travelmind_api.services.llm.client import OpenAICompatibleClient
from travelmind_api.services.llm.config import LlmEndpointConfig
from travelmind_api.services.llm.parser import PlanningResponseValidationError, parse_planning_response
from travelmind_api.services.llm.role_invoker import OpenAICompatibleRoleInvoker, RoleInvocation
from travelmind_api.services.planner_output_schema import full_plan_schema
from travelmind_api.services.planner_reliability import decode_plan


def test_schema_failure_preserves_safe_field_paths_without_values():
    secret = 'NEVER_PERSIST_PRIVATE_INPUT_5678'
    response = {'summary': None, 'days': [{'title': '汕头', 'items': [
        {'type': 'sight', 'name': None, 'start_time': '09:00', 'end_time': '10:00',
         'booking_info': {'notes': secret}}]}]}
    with pytest.raises(PlanningResponseValidationError) as raised:
        parse_planning_response(json.dumps(response))
    assert secret not in str(raised.value)
    issues = raised.value.issues
    assert {'path': ['summary'], 'code': 'string_type'} in issues
    assert {'path': ['days', 0, 'items', 0, 'name'], 'code': 'string_type'} in issues
    assert {'path': ['days', 0, 'items', 0, 'booking_info', 'notes'], 'code': 'list_type'} in issues
    payload, error = decode_plan(None, SimpleNamespace(content=json.dumps(response)), None)
    assert payload == {} and error['code'] == 'schema_validation_failed'
    assert error['issues'] == issues and secret not in json.dumps(error)


def test_schema_diagnostics_are_bounded_and_exclude_custom_messages():
    from pydantic import BaseModel, field_validator, ValidationError
    from travelmind_api.services.planner_schema_diagnostics import schema_validation_issues
    class Entry(BaseModel):
        name: str
        @field_validator('name')
        @classmethod
        def fail(cls, value):
            raise ValueError('PRIVATE ' + value)
    with pytest.raises(ValidationError) as raised:
        Entry(name='SECRET')
    assert schema_validation_issues(raised.value) == [{'path': ['name'], 'code': 'value_error'}]
    response={'summary': '行程', 'days': [{'title': '一天', 'items': [
        {'type': 'sight','name': None,'start_time':'09:00','end_time':'10:00'} for _ in range(60)]}]}
    _, error = decode_plan(None,SimpleNamespace(content=json.dumps(response)),None)
    assert len(error['issues']) == 20


def assert_closed(node):
    if isinstance(node, dict):
        if node.get('type') == 'object':
            assert node['additionalProperties'] is False
            assert set(node['required']) == set(node['properties'])
        for value in node.values():
            assert_closed(value)
    elif isinstance(node, list):
        for value in node:
            assert_closed(value)


def test_schema_is_built_from_active_parser_and_preserves_nullable_types():
    schema=full_plan_schema()
    assert_closed(schema)
    assert schema['properties']['days']['minItems'] == 1
    assert 'title' in schema['$defs']['LlmPlanDay']['properties']
    assert 'title' in schema['$defs']['LlmPlanDay']['required']
    assert schema['properties']['summary']['minLength'] == 1
    assert schema['$defs']['LlmPlanItem']['properties']['start_time']['pattern']
    assert {'type':'null'} in schema['properties']['total_budget_estimate']['anyOf']


def test_rich_production_schema_not_only_simplified_published_model(monkeypatch):
    # Contract-only fixture from the deployed parser; no requests, facts or keys.
    from travelmind_api.services.llm import parser
    original=json.loads((Path(__file__).parent/'fixtures/planner-rich-schema.json').read_text(encoding='utf8'))
    unchanged=json.dumps(original,sort_keys=True)
    monkeypatch.setattr(parser,'LlmPlanningPayload',SimpleNamespace(model_json_schema=lambda:original))
    schema=full_plan_schema()
    assert_closed(schema)
    assert json.dumps(original,sort_keys=True)==unchanged
    for name, definition in original['$defs'].items():
        excluded = {'operation_evidence'} if name=='LlmBookingInfo' else ({'railway_snapshot'} if name=='TransportServiceCandidate' else set())
        assert set(schema['$defs'][name].get('properties',{})) == set(definition.get('properties',{}))-excluded
    assert set(schema['properties'])==set(original['properties'])
    assert 'schedule_intent' in schema['$defs']['LlmPlanItem']['properties']
    assert schema['$defs']['FlexibleWindow']['properties']['purpose']['enum'] == ['free_time','meal_break','rest','station_buffer','contingency']
    assert schema['$defs']['LodgingCostEstimate']['properties']['pricing_unit']['enum'] == ['per_room_per_night','per_stay']
    assert schema['$defs']['ScheduleIntent']['properties']['purpose']['anyOf'][0]['enum']
    assert 'operation_evidence' not in schema['$defs']['LlmBookingInfo']['properties']
    assert 'railway_snapshot' not in schema['$defs']['TransportServiceCandidate']['properties']


@pytest.mark.parametrize('wire',['responses','chat_completions'])
def test_real_role_wire_constrains_full_plan_and_replaces_stale_example(wire):
    captured={}
    class Client(OpenAICompatibleClient):
        def create_chat_completion(self, **kwargs):
            captured.update(self._build_text_payload(**kwargs,wire_api=wire))
            return '{}'
    endpoint=LlmEndpointConfig(base_url='https://fixture.invalid/v1',api_key='fixture',model='fixture',provider_protocol='newapi',wire_api=wire)
    invocation=RoleInvocation(role_name='itinerary_planner',prompt_version='fixture',system_prompt='规划JSON',
        input_payload={'output_schema':{'obsolete_sample':True},'planning_brief':{'destination':'汕头'}},endpoint=endpoint)
    OpenAICompatibleRoleInvoker(client_factory=Client).invoke(invocation)
    fmt=captured['text']['format'] if wire=='responses' else captured['response_format']['json_schema']
    assert fmt['strict'] is True and fmt['schema']==full_plan_schema()
    serialized=json.dumps(captured,ensure_ascii=False)
    assert 'obsolete_sample' not in serialized and '汕头' in serialized
    assert invocation.input_payload['output_schema']=={'obsolete_sample':True}


def test_role_preserves_narrow_slot_schema_and_does_not_constrain_research():
    clients=[]
    class Client:
        last_citations=[];last_usage=None;last_retry_count=0;last_request_count=1
        def __init__(self, config):clients.append(self)
        def create_chat_completion(self,**kwargs):return '{}'
    endpoint=LlmEndpointConfig(base_url='https://fixture.invalid/v1',api_key='fixture',model='fixture',provider_protocol='newapi')
    schema={'type':'object','properties':{},'required':[],'additionalProperties':False}
    for role in ['itinerary_planner','poi_specialist']:
        OpenAICompatibleRoleInvoker(client_factory=Client).invoke(RoleInvocation(role_name=role,prompt_version='fixture',system_prompt='JSON',input_payload={'structured_output_schema':schema},endpoint=endpoint))
    assert clients[0].structured_output_schema == schema
    assert clients[1].structured_output_schema is None and not clients[1].json_object_mode


def test_schema_annotation_names_are_not_deleted_from_property_names():
    from travelmind_api.services.planner_output_schema import _strict
    model={'type':'object','title':'Model annotation','properties': {
        name:{'type':'string','title':'Field annotation','default':'not output'}
        for name in ['title','default','examples']}}
    schema=_strict(model)
    assert schema['required']==['title','default','examples']
    assert schema['properties']=={name:{'type':'string'} for name in ['title','default','examples']}
    assert 'title' not in schema
