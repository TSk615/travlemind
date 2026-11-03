"""Strict provider schemas for the small, authorized slot operation protocol."""
from copy import deepcopy


def _object(properties):
    return {"type":"object", "properties":properties, "required":list(properties), "additionalProperties":False}


def _strict(node):
    if isinstance(node,list):return [_strict(v) for v in node]
    if not isinstance(node,dict):return node
    result = {}
    for key, value in node.items():
        if key in {"default", "title", "examples"}:
            continue  # Schema annotations only, never names in properties/$defs.
        if key in {"properties", "$defs", "patternProperties"}:
            result[key] = {name: _strict(child) for name, child in value.items()}
        else:
            result[key] = _strict(value)
    if "const" in result:result["enum"]=[result.pop("const")]
    if result.get("type")=="object" or "properties" in result:
        props=result.get("properties",{})
        result.update(type="object",properties=props,required=list(props),additionalProperties=False)
    return result


def slot_operation_schema(allowed_fields, window_days, allow_lodging):
    from travelmind_api.services.llm.parser import LlmPlanItem
    from travelmind_api.services import planning_details
    item=LlmPlanItem.model_json_schema()
    window_model=getattr(planning_details,"FlexibleWindow",None)
    lodging_model=getattr(planning_details,"LodgingCostEstimate",None)
    window=window_model.model_json_schema() if window_model else _object({"start_time":{"type":"string"},"end_time":{"type":"string"},"purpose":{"type":"string"}})
    lodging=lodging_model.model_json_schema() if lodging_model else _object({"hotel_name":{"type":"string"},"total_cost":{"type":"number"}})
    defs={**item.get("$defs",{}),**window.get("$defs",{}),**lodging.get("$defs",{})}
    by_field={}
    for ref,fields in allowed_fields.items():
        for field in fields:by_field.setdefault(field,[]).append(ref)
    operations=[]
    for field,refs in sorted(by_field.items()):
        operations.append(_object({"item_ref":{"type":"string","enum":sorted(refs)},"field":{"type":"string","enum":[field]},"value":deepcopy(item['properties'].get(field, {'type':'null'}))}))
    properties={}
    if operations:properties['item_operations']={"type":"array","items":{"anyOf":operations}}
    else:properties['item_operations']={"type":"array","maxItems":0,"items":_object({"item_ref":{"type":"string"},"field":{"type":"string"},"value":{"type":"null"}})}
    properties['day_updates']={"type":"array","items":_object({"day_index":{"type":"integer","enum":sorted(window_days) or [0]},"flexible_windows":{"type":"array","items":{k:v for k,v in window.items() if k!='$defs'}}})}
    if not window_days:properties['day_updates']['maxItems']=0
    if allow_lodging:properties['lodging_costs']={"type":"array","items":{k:v for k,v in lodging.items() if k!='$defs'}}
    schema=_object(properties)
    if defs:schema['$defs']=defs
    return _strict(schema)


def full_plan_schema():
    """The active parser is the contract, not the historical example itinerary.

    Raw evidence dictionaries are source/backend-owned, not planner-authored
    output. They stay untouched in research input and use parser defaults when
    absent from generated output. Every remaining field retains its real type,
    nullability, enum and bounds, including rich production-only model fields.
    """
    from travelmind_api.services.llm.parser import LlmPlanningPayload

    schema = deepcopy(LlmPlanningPayload.model_json_schema())
    for name, fields in {
        "LlmBookingInfo": ("operation_evidence",),
        "TransportServiceCandidate": ("railway_snapshot",),
    }.items():
        model = schema.get("$defs", {}).get(name, {})
        for field in fields:
            model.get("properties", {}).pop(field, None)
    return _strict(schema)
