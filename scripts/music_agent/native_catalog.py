"""Verify host effect metadata against the actual Agent edit surface.

This is control-thread schema work. A mismatch disables effect edits rather
than guessing a newly added parameter's units, range or meaning.
"""
from __future__ import annotations


class NativeCatalogError(ValueError):
    pass


def agent_effect_catalog():
    from .plans import _EFFECT_STATE, _SCHEMAS, EFFECT_NAMES
    definitions = {}
    for state in _EFFECT_STATE["oneOf"]:
        props = state["properties"]
        name = props["type"]["const"]
        per_band = "bands" in props
        controls = props["bands"]["items"]["properties"] if per_band else {
            key:value for key,value in props.items() if key not in {"version","type"}}
        specs = {}
        for parameter, value in controls.items():
            kind = value.get("type")
            if kind == "number":
                specs[parameter] = {"kind":"number", "minimum":value["minimum"],
                                    "maximum":value["maximum"], "per_band":per_band}
            elif kind == "boolean":
                specs[parameter] = {"kind":"boolean", "per_band":per_band}
            elif kind == "string" and isinstance(value.get("enum"),list) and value["enum"] and all(isinstance(item,str) for item in value["enum"]):
                specs[parameter] = {"kind":"enum", "values":list(value["enum"]), "per_band":per_band}
            else:
                raise NativeCatalogError("Agent 效果器参数 schema 不完整。")
        definitions[name] = {"bands": props["bands"]["minItems"] if per_band else 0,
                             "parameters": specs}
    editable_types = set(_SCHEMAS["add_native_effect"]["properties"]["effect_type"]["enum"])
    editable_params = set(_SCHEMAS["set_native_effect_parameter"]["properties"]["parameter"]["enum"])
    if set(definitions) != editable_types or set(definitions) != set(EFFECT_NAMES):
        raise NativeCatalogError("Agent 原生效果器类型定义不一致。")
    if editable_params != {key for value in definitions.values() for key in value["parameters"]}:
        raise NativeCatalogError("Agent 原生效果器参数没有完整开放。")
    return definitions


def validate_effect_catalog(catalog):
    if not isinstance(catalog,dict) or type(catalog.get("version")) is not int or catalog["version"] != 1 or not isinstance(catalog.get("types"),list):
        raise NativeCatalogError("当前 DAW 未提供兼容的原生效果器能力目录，请使用配套新版。")
    expected = agent_effect_catalog()
    actual = {}
    for device in catalog["types"]:
        if not isinstance(device,dict) or not isinstance(device.get("type"),str) or device["type"] in actual:
            raise NativeCatalogError("DAW 原生效果器类型目录无效。")
        if device.get("readable") is not True or device.get("writable") is not True or type(device.get("bands")) is not int:
            raise NativeCatalogError("DAW 没有声明完整可读写效果器能力。")
        values = device.get("parameters")
        if not isinstance(values,list): raise NativeCatalogError("效果器参数目录缺失。")
        parameters = {}
        for entry in values:
            if not isinstance(entry,dict) or not isinstance(entry.get("name"),str) or entry["name"] in parameters:
                raise NativeCatalogError("效果器参数目录无效。")
            fields = {k:v for k,v in entry.items() if k != "name"}
            if type(fields.get("per_band")) is not bool:
                raise NativeCatalogError("效果器参数频段描述无效。")
            parameters[entry["name"]] = fields
        actual[device["type"]] = {"bands":device["bands"], "parameters":parameters}
    if actual != expected:
        raise NativeCatalogError("DAW 与 Agent 原生效果器目录不一致；相关编辑已停用，请更新配套版本。")
    return True


def agent_instrument_catalog():
    from .plans import _SCHEMAS
    by_type={"sampler":("set_native_pad","set_native_sampler"),"drum_rack":("set_native_pad",)}
    result={}
    for device,commands in by_type.items():
        actions={}
        for command in commands:
            parameters={}
            for name,property_schema in _SCHEMAS[command]["properties"].items():
                if name in {"type","track_id"}:continue
                kind=property_schema.get("type")
                descriptor={"kind":kind,"per_band":False}
                if kind in {"integer","number"}:
                    descriptor.update(minimum=property_schema["minimum"],maximum=property_schema["maximum"])
                elif kind!="boolean":raise NativeCatalogError("Agent 原生乐器参数 schema 不完整。")
                parameters[name]=descriptor
            actions[command]=parameters
        result[device]={"actions":actions,"readable":True,"scope":"project","asynchronous":True,
                        "single_action":True,"sample_must_be_loaded":True,"model_can_assign_path":False,"model_can_create":False}
    return result


def validate_instrument_catalog(catalog):
    if not isinstance(catalog,dict) or type(catalog.get("version")) is not int or catalog["version"] != 1 or not isinstance(catalog.get("types"),list):
        raise NativeCatalogError("当前 DAW 未提供兼容的原生乐器能力目录，请使用配套新版。")
    expected=agent_instrument_catalog();actual={}
    for device in catalog["types"]:
        if not isinstance(device,dict) or not isinstance(device.get("type"),str) or device["type"] in actual or not isinstance(device.get("actions"),list):
            raise NativeCatalogError("DAW 原生乐器类型目录无效。")
        actions={}
        for action in device["actions"]:
            if not isinstance(action,dict) or not isinstance(action.get("command"),str) or action["command"] in actions or not isinstance(action.get("parameters"),list):
                raise NativeCatalogError("DAW 原生乐器动作目录无效。")
            parameters={}
            for parameter in action["parameters"]:
                if not isinstance(parameter,dict) or not isinstance(parameter.get("name"),str) or parameter["name"] in parameters:
                    raise NativeCatalogError("DAW 原生乐器参数目录无效。")
                parameters[parameter["name"]]={k:v for k,v in parameter.items() if k!="name"}
            actions[action["command"]]=parameters
        actual[device["type"]]={"actions":actions,**{field:device.get(field) for field in (
            "readable","scope","asynchronous","single_action","sample_must_be_loaded","model_can_assign_path","model_can_create")}}
    if actual!=expected:
        raise NativeCatalogError("DAW 与 Agent 原生乐器目录不一致；相关编辑已停用，请更新配套版本。")
    return True
