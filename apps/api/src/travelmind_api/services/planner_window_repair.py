"""Let the model annotate real free gaps; never let it invent overlapping gaps."""
from copy import deepcopy
from dataclasses import dataclass
import hashlib

VERSION = 'free-gap-annotations.v1'
SYSTEM_PROMPT = '''你是行程留白标注修复器。只输出符合 structured_output_schema 的 JSON。
实际行程已固定，不能修改任何活动。free_gap_candidates 是服务器从全部活动（含跨夜占用）算出的真实空闲区间，不是已核实的餐厅、交通或服务。
对每个空闲区间，选择 null 表示不标注，或选择 purpose 和 note 说明自由活动、自由用餐、休息、候车或机动用途；只标注有意义的留白，不强求填满。
服务器用候选区间的原始起止时间生成标注，并整体替换授权日期的旧 flexible_windows；不保留旧的冲突标注，不重排日程，不编造任何事实。'''


def _clock(value):
    try:
        h,m=map(int,value.split(':'))
        return h*60+m if 0<=h<24 and 0<=m<60 else None
    except (ValueError,TypeError,AttributeError):
        return None


def _hhmm(value):
    return f'{value//60:02d}:{value%60:02d}'


def free_gaps(original, day_index):
    """Half-open interval complement, bounded by that day's described horizon."""
    day=original['days'][day_index-1]
    bounds=[]
    for value in [*day['items'],*day.get('flexible_windows',[])]:
        for key in ['start_time','end_time']:
            time=_clock(value.get(key))
            if time is not None:bounds.append(time)
    if not bounds:return []
    lower,upper=min(bounds),max(bounds)
    occupied=[];offset=(day_index-1)*1440
    for di,other in enumerate(original['days']):
        for item in other['items']:
            a,b=_clock(item.get('start_time')),_clock(item.get('end_time'))
            if a is None or b is None:raise ValueError('Invalid fixed activity clock')
            a+=di*1440-offset;b+=(di+int(item.get('end_day_offset') or 0))*1440-offset
            if b>a and b>lower and a<upper:occupied.append((max(a,lower),min(b,upper)))
    result=[];cursor=lower
    for a,b in sorted(occupied):
        if a>cursor:result.append((cursor,a))
        cursor=max(cursor,b)
    if cursor<upper:result.append((cursor,upper))
    return [{'gap_id':f'g{i}','start_time':_hhmm(a),'end_time':_hhmm(b)}
            for i,(a,b) in enumerate(result,1) if b-a>=5]


@dataclass(frozen=True)
class FreeGapRepair:
    original: dict
    payload: dict
    gaps: dict
    system_prompt: str = SYSTEM_PROMPT
    version: str = VERSION

    def apply(self,content):
        from travelmind_api.services.planner_slot_repair import _read,SlotRepairError
        patch=_read(content)
        if set(patch)!={'window_annotations'} or not isinstance(patch['window_annotations'],dict) or set(patch['window_annotations'])!=set(self.gaps):
            raise SlotRepairError('invalid_window_annotation_days')
        merged=deepcopy(self.original)
        for di,gaps in self.gaps.items():
            values=patch['window_annotations'][di]
            if not isinstance(values,dict) or set(values)!={g['gap_id'] for g in gaps}:raise SlotRepairError('invalid_gap_choices')
            windows=[]
            for gap in gaps:
                choice=values[gap['gap_id']]
                if choice is None:continue
                if not isinstance(choice,dict) or set(choice)!={'purpose','note'} or not isinstance(choice['purpose'],str) or choice['purpose'] not in {'free_time','meal_break','rest','station_buffer','contingency'} or not isinstance(choice['note'],str) or not 1<=len(choice['note'].strip())<=1000:
                    raise SlotRepairError('invalid_gap_annotation')
                windows.append({'start_time':gap['start_time'],'end_time':gap['end_time'],**choice})
            merged['days'][int(di)-1]['flexible_windows']=windows
        if merged==self.original:raise SlotRepairError('empty_patch')
        return merged,{'version':VERSION,'day_updates':len(self.gaps),'activity_items_unchanged':True,
                       'wire_response_chars':len(content),'wire_response_sha256':hashlib.sha256(content.encode()).hexdigest()}


def prepare_free_gap_repair(payload,original,days):
    from travelmind_api.services.planner_output_schema import _object
    gaps={str(di):free_gaps(original,di) for di in sorted(set(days))}
    choice={'anyOf':[{'type':'null'},_object({'purpose':{'type':'string','enum':['free_time','meal_break','rest','station_buffer','contingency']},'note':{'type':'string','minLength':1,'maxLength':1000}})]}
    schema=_object({'window_annotations':_object({di:_object({gap['gap_id']:deepcopy(choice) for gap in values}) for di,values in gaps.items()})})
    wire=deepcopy(payload)
    wire.update(repair_mode=VERSION,structured_output_schema=schema,output_schema=schema,
                repair_instruction=SYSTEM_PROMPT,free_gap_candidates=gaps,
                repair_contract={'version':VERSION,'allowed_window_days':sorted(set(days)),'activity_items_are_server_preserved':True})
    return FreeGapRepair(deepcopy(original),wire,gaps)
