import json
from copy import deepcopy

import pytest

from travelmind_api.services.planner_slot_repair import prepare_slot_repair, SlotRepairError, VERSION


@pytest.fixture
def payload():
    return {
        'previous_itinerary': {'summary': '两日安排', 'total_budget_estimate': 600, 'risks': ['班次须确认'], 'days': [
            {'title': '抵达', 'summary': '抵达', 'total_cost': 300, 'items': [
                {'item_ref': 'd1i1', 'name': '进站', 'type': 'transport', 'start_time': '21:37', 'end_time': '22:22', 'end_day_offset': 0,
                 'schedule_intent': {'transfer_minutes': 45, 'buffer_minutes': 40}},
                {'item_ref': 'd1i2', 'name': '铁路建议窗口', 'type': 'transport', 'start_time': '22:22', 'end_time': '00:16', 'end_day_offset': 1,
                 'booking_info': {'service_number': '', 'schedule_verified': False}},
            ]},
            {'title': '游览', 'summary': '散步', 'total_cost': 300, 'items': [
                {'item_ref': 'd2i1', 'name': '小公园', 'type': 'sight', 'start_time': '10:00', 'end_time': '11:30'},
            ], 'flexible_windows': []},
        ]},
        'repair_targets': [{'item_ref': 'd1i1', 'dependent_transfer': False}, {'item_ref': 'd1i2', 'dependent_transfer': True}],
        'repair_scope_kind': 'local_slots', 'output_format_error': None, 'repair_flexible_window_days': [2],
        'validation_errors': ['进站分配85分钟超过项目45分钟'], 'repair_hints': [],
        'research_evidence': {'documents': [{'url': 'https://example.com/source', 'content': '完整来源正文，不截断'}]},
        'output_schema': 'full itinerary schema',
    }


def encode(value):return json.dumps(value, ensure_ascii=False)


def test_local_patch_preserves_all_other_fields_and_all_source_data(payload):
    before = deepcopy(payload)
    contract = prepare_slot_repair(payload)
    assert contract.payload['repair_mode'] == VERSION
    assert contract.payload['research_evidence'] == before['research_evidence']
    assert contract.payload['output_schema'] != 'full itinerary schema'
    result, audit = contract.apply(encode({'item_updates': [{'item_ref': 'd1i1', 'changes': {'schedule_intent': {'transfer_minutes': 45, 'buffer_minutes': 0}}}]}))
    expected = deepcopy(before['previous_itinerary'])
    expected['days'][0]['items'][0]['schedule_intent']['buffer_minutes'] = 0
    assert result == expected and payload == before
    assert audit['wire_response_chars'] < len(encode(result))
    assert audit['item_updates'] == 1 and len(audit['wire_response_sha256']) == 64


def test_duplicate_keys_including_nested_fields_are_rejected(payload):
    contract = prepare_slot_repair(payload)
    for text in [
        '{"item_updates": [], "item_updates": []}',
        '{"item_updates":[{"item_ref":"d1i1","changes":{"note":"one","note":"two"}}]}',
    ]:
        with pytest.raises(SlotRepairError, match='duplicate_key'):contract.apply(text)


@pytest.mark.parametrize('patch', [
    {'days': []}, {'summary': '全部重做'},
    {'item_updates': [{'item_ref': 'd2i1', 'changes': {'name': '陌生地点'}}]},
    {'item_updates': [{'item_ref': 'd1i1', 'changes': {'item_ref': 'd2i1'}}]},
    {'item_updates': [{'item_ref': 'd1i2', 'changes': {'name': '另一列车'}}]},
    {'item_updates': [{'item_ref': 'd1i2', 'changes': {'booking_info': {'schedule_verified': True}}}]},
    {'item_updates': [{'item_ref': 'd1i1', 'changes': {'note': 'one'}}, {'item_ref': 'd1i1', 'changes': {'note': 'two'}}]},
    {'day_updates': [{'day_index': 1, 'flexible_windows': []}]},
    {'day_updates': [{'day_index': True, 'flexible_windows': []}]},
    {'day_updates': [{'day_index': 2, 'flexible_windows': []}, {'day_index': 2, 'flexible_windows': []}]},
    {'lodging_costs': []}, {'item_updates': []},
])
def test_unauthorized_or_ambiguous_edits_fail_closed(payload, patch):
    before = deepcopy(payload)
    with pytest.raises(SlotRepairError):prepare_slot_repair(payload).apply(encode(patch))
    assert payload == before


def test_dependent_clock_update_and_authorized_windows_only(payload):
    contract = prepare_slot_repair(payload)
    patch = {'item_updates': [{'item_ref': 'd1i2', 'changes': {'end_time': '00:30', 'end_day_offset': 1}}],
             'day_updates': [{'day_index': 2, 'flexible_windows': [{'start_time': '11:30', 'end_time': '12:30', 'note': '自由用餐'}]}]}
    result, _ = contract.apply(encode(patch))
    assert result['days'][0]['items'][1]['booking_info'] == payload['previous_itinerary']['days'][0]['items'][1]['booking_info']
    assert result['days'][1]['items'] == payload['previous_itinerary']['days'][1]['items']
    assert result['days'][1]['flexible_windows'] == patch['day_updates'][0]['flexible_windows']


def test_optional_lodging_requires_explicit_authorization(payload):
    payload['repair_lodging_costs'] = True
    result, _ = prepare_slot_repair(payload).apply('{"lodging_costs": []}')
    assert result['lodging_costs'] == []


@pytest.mark.parametrize('text', ['[]', '{}{}', '{"item_updates": [', 'explanation {}', '{"item_updates":[],"extra":NaN}', '{"item_updates":[{"item_ref":"d1i1","changes":{"score":1e999}}]}'])
def test_invalid_json_nonfinite_numbers_and_extra_text_are_not_salvaged(payload, text):
    with pytest.raises(SlotRepairError):prepare_slot_repair(payload).apply(text)


def test_single_exact_code_fence_is_nonsemantic(payload):
    value = {'item_updates': [{'item_ref': 'd1i1', 'changes': {'note': '出行前确认车站'}}]}
    result, _ = prepare_slot_repair(payload).apply('```json\n' + encode(value) + '\n```')
    assert result['days'][0]['items'][0]['note'] == '出行前确认车站'


def test_global_or_unparseable_original_uses_original_full_repair_contract(payload):
    for field, value in [('repair_scope_kind', 'global_structure'), ('output_format_error', {'code': 'duplicate_key'})]:
        trial = deepcopy(payload);trial[field] = value
        assert prepare_slot_repair(trial) is None


def test_legacy_unique_names_get_stable_local_refs_without_changing_saved_plan(payload):
    payload.pop('repair_targets')
    for d in payload['previous_itinerary']['days']:
        for i in d['items']:i.pop('item_ref')
    contract = prepare_slot_repair(payload)
    assert 'd1i1' in contract.allowed and 'd1i2' in contract.allowed
    result, _ = contract.apply('{"item_updates":[{"item_ref":"d1i1","changes":{"note":"保留未知"}}]}')
    assert 'item_ref' not in result['days'][0]['items'][0]


def test_duplicate_original_refs_are_not_repaired_by_guessing(payload):
    payload['previous_itinerary']['days'][0]['items'][1]['item_ref'] = 'd1i1'
    with pytest.raises(SlotRepairError, match='ambiguous_original_item_refs'):prepare_slot_repair(payload)
