from copy import deepcopy
import json

import pytest

from travelmind_api.services.planner_slot_repair import prepare_slot_repair, SlotRepairError
from travelmind_api.services.planner_day_repair import ConflictDayRepair


def fixture():
    def item(ref,name='景点',kind='sight',start='10:00',end='11:00'):
        return {'item_ref':ref,'type':kind,'name':name,'start_time':start,'end_time':end,'end_day_offset':0,'booking_info':None}
    original={'summary':'原行程','days':[{'title':f'第{di}天','items':[item(f'd{di}i1',f'地点{di}'),item(f'd{di}i2',f'转场{di}','transfer','11:00','12:00')]} for di in range(1,6)],'lodging_costs':[{'kept':'server ledger'}]}
    train=item('d1i0','已核实列车','transport','08:00','09:00');train['booking_info']={'schedule_verified':True,'service_number':'G1','source_urls':['https://official.invalid/train']}
    original['days'][0]['items'].insert(0,train)
    targets=[{'item_ref':ref,'day_index':di,'dependent_transfer':False} for di,ref in [(1,'d1i1'),(2,'d2i1'),(4,'d4i1')]]
    payload={'previous_itinerary':original,'validation_errors':['多个硬冲突'],'repair_targets':targets,'repair_flexible_window_days':[1,4]}
    return original,payload


def test_interacting_hard_conflicts_get_one_coordinated_day_scope():
    original,payload=fixture();contract=prepare_slot_repair(payload)
    assert isinstance(contract,ConflictDayRepair) and contract.days==frozenset({1,2,4})
    assert set(contract.payload['structured_output_schema']['properties']['day_replacements']['properties'])=={'1','2','4'}
    patch={'day_replacements':{str(di):deepcopy(original['days'][di-1]) for di in contract.days}}
    patch['day_replacements']['4']['items'][0]['start_time']='09:00'
    patch['day_replacements']['4']['items'][0]['end_time']='10:00'
    patch['day_replacements']['2']['items'].append({'type':'sight','name':'不同的有据候选','start_time':'13:00','end_time':'14:00'})
    merged,audit=contract.apply(json.dumps(patch))
    assert merged['days'][2]==original['days'][2] and merged['days'][4]==original['days'][4]
    assert merged['lodging_costs']==original['lodging_costs']
    assert merged['days'][0]['items'][0]==original['days'][0]['items'][0]
    assert audit['authorized_days']==[1,2,4] and audit['unaffected_days_preserved']
    assert original==fixture()[0]  # Applying never mutates caller input.


@pytest.mark.parametrize('fault',['missing_day','extra_day','changed_train','removed_train','extra_root'])
def test_day_repair_rejects_out_of_scope_or_locked_transport_changes(fault):
    original,payload=fixture();c=prepare_slot_repair(payload)
    patch={'day_replacements':{str(di):deepcopy(original['days'][di-1]) for di in c.days}}
    if fault=='missing_day':patch['day_replacements'].pop('2')
    if fault=='extra_day':patch['day_replacements']['3']=deepcopy(original['days'][2])
    if fault=='changed_train':patch['day_replacements']['1']['items'][0]['end_time']='10:00'
    if fault=='removed_train':patch['day_replacements']['1']['items'].pop(0)
    if fault=='extra_root':patch['summary']='unauthorized'
    with pytest.raises(SlotRepairError):c.apply(json.dumps(patch))


def test_day_repair_cannot_overwrite_existing_transport_evidence():
    original,payload=fixture();c=prepare_slot_repair(payload)
    patch={'day_replacements':{str(di):deepcopy(original['days'][di-1]) for di in c.days}}
    patch['day_replacements']['1']['items'][0]['booking_info']={'schedule_verified':False,'service_number':'FAKE'}
    patch['day_replacements']['4']['title']='已修复的日期'
    merged,_=c.apply(json.dumps(patch))
    assert merged['days'][0]['items'][0]==original['days'][0]['items'][0]


def test_single_or_soft_or_explicit_field_only_targets_do_not_expand_scope():
    _,payload=fixture()
    payload['validation_errors']=[]
    assert not isinstance(prepare_slot_repair(payload),ConflictDayRepair)
    payload['validation_errors']=['硬冲突'];payload['repair_targets'][0]['allowed_fields']=['note']
    assert not isinstance(prepare_slot_repair(payload),ConflictDayRepair)
    payload['repair_targets']=payload['repair_targets'][:1]
    assert not isinstance(prepare_slot_repair(payload),ConflictDayRepair)
