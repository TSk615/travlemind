from copy import deepcopy
import json

import pytest

from travelmind_api.services.planner_slot_repair import prepare_slot_repair,SlotRepairError
from travelmind_api.services.planner_window_repair import free_gaps,FreeGapRepair


def plan():
    return {'summary':'三日游','days':[
        {'title':'第一天','items':[{'type':'transport','name':'跨夜列车','start_time':'23:00','end_time':'08:00','end_day_offset':1}]},
        {'title':'第二天','items':[{'type':'transfer','name':'转场','start_time':'10:00','end_time':'12:00'},{'type':'meal','name':'晚餐','start_time':'18:00','end_time':'19:00'}],
         'flexible_windows':[{'start_time':'07:00','end_time':'13:00','purpose':'rest','note':'无效重叠标注'},{'start_time':'14:00','end_time':'15:00','purpose':'rest','note':'另一标注'}]},
        {'title':'第三天','items':[{'type':'sight','name':'景点','start_time':'09:00','end_time':'10:00'}]}]}


def contract():
    original=plan()
    return prepare_slot_repair({'previous_itinerary':original,'repair_targets':[],
        'repair_flexible_window_days':[2],'validation_errors':['留白重叠']}),original


def test_actual_gaps_include_overnight_occupancy_and_merge_overlapping_spans():
    assert free_gaps(plan(),2)==[{'gap_id':'g1','start_time':'08:00','end_time':'10:00'}, {'gap_id':'g2','start_time':'12:00','end_time':'18:00'}]


def test_model_annotates_only_real_gaps_without_retiming_activities():
    c,original=contract();assert isinstance(c,FreeGapRepair)
    patch={'window_annotations':{'2':{'g1':None,'g2':{'purpose':'free_time','note':'自由午餐与休息，不假称餐饮已核实'}}}}
    merged,audit=c.apply(json.dumps(patch))
    assert merged['days'][1]['flexible_windows']==[{'start_time':'12:00','end_time':'18:00','purpose':'free_time','note':'自由午餐与休息，不假称餐饮已核实'}]
    assert all(a['items']==b['items'] for a,b in zip(merged['days'],original['days']))
    assert merged['days'][0]==original['days'][0] and merged['days'][2]==original['days'][2]
    assert original==plan() and audit['activity_items_unchanged']


@pytest.mark.parametrize('fault',['extra_day','missing_gap','extra_gap','invent_time','bad_purpose'])
def test_window_choices_cannot_invent_interval_or_modify_other_days(fault):
    c,_=contract();patch={'window_annotations':{'2':{'g1':None,'g2':None}}}
    if fault=='extra_day':patch['window_annotations']['3']={}
    if fault=='missing_gap':patch['window_annotations']['2'].pop('g1')
    if fault=='extra_gap':patch['window_annotations']['2']['g3']=None
    if fault=='invent_time':patch['window_annotations']['2']['g1']={'purpose':'rest','note':'休息','start_time':'07:00'}
    if fault=='bad_purpose':patch['window_annotations']['2']['g1']={'purpose':'sight','note':'插入景点'}
    with pytest.raises(SlotRepairError):c.apply(json.dumps(patch))


def test_model_can_explicitly_omit_optional_annotations_but_not_activities():
    c,original=contract();merged,_=c.apply(json.dumps({'window_annotations':{'2':{'g1':None,'g2':None}}}))
    assert merged['days'][1]['flexible_windows']==[]
    assert merged['days'][1]['items']==original['days'][1]['items']
