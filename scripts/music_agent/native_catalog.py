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
                raise NativeCatalogError("The Agent effect parameter schema is incomplete.")
        definitions[name] = {"bands": props["bands"]["minItems"] if per_band else 0,
                             "parameters": specs}
    editable_types = set(_SCHEMAS["add_native_effect"]["properties"]["effect_type"]["enum"])
    editable_params = set(_SCHEMAS["set_native_effect_parameter"]["properties"]["parameter"]["enum"])
    if set(definitions) != editable_types or set(definitions) != set(EFFECT_NAMES):
        raise NativeCatalogError("Agent native effect type definitions are inconsistent.")
    if editable_params != {key for value in definitions.values() for key in value["parameters"]}:
        raise NativeCatalogError("Agent native effect parameters are incomplete.")
    return definitions


def validate_effect_catalog(catalog):
    if not isinstance(catalog,dict) or type(catalog.get("version")) is not int or catalog["version"] != 1 or not isinstance(catalog.get("types"),list):
        raise NativeCatalogError("The DAW does not provide a compatible native effect catalog. Use matching versions.")
    expected = agent_effect_catalog()
    actual = {}
    for device in catalog["types"]:
        if not isinstance(device,dict) or not isinstance(device.get("type"),str) or device["type"] in actual:
            raise NativeCatalogError("Invalid DAW native effect type catalog.")
        if device.get("readable") is not True or device.get("writable") is not True or type(device.get("bands")) is not int:
            raise NativeCatalogError("The DAW does not declare complete effect read/write capabilities.")
        values = device.get("parameters")
        if not isinstance(values,list): raise NativeCatalogError("The effect parameter catalog is missing.")
        parameters = {}
        for entry in values:
            if not isinstance(entry,dict) or not isinstance(entry.get("name"),str) or entry["name"] in parameters:
                raise NativeCatalogError("Invalid effect parameter catalog.")
            fields = {k:v for k,v in entry.items() if k != "name"}
            if type(fields.get("per_band")) is not bool:
                raise NativeCatalogError("Invalid effect parameter band description.")
            parameters[entry["name"]] = fields
        actual[device["type"]] = {"bands":device["bands"], "parameters":parameters}
    if actual != expected:
        raise NativeCatalogError("DAW and Agent native effect catalogs differ. Related edits are disabled. Update to matching versions.")
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
                elif kind!="boolean":raise NativeCatalogError("The Agent native instrument parameter schema is incomplete.")
                parameters[name]=descriptor
            actions[command]=parameters
        result[device]={"actions":actions,"readable":True,"scope":"project","asynchronous":True,
                        "single_action":True,"sample_must_be_loaded":True,"model_can_assign_path":False,"model_can_create":False}
    return result


def validate_instrument_catalog(catalog):
    if not isinstance(catalog,dict) or type(catalog.get("version")) is not int or catalog["version"] != 1 or not isinstance(catalog.get("types"),list):
        raise NativeCatalogError("The DAW does not provide a compatible native instrument catalog. Use matching versions.")
    expected=agent_instrument_catalog();actual={}
    for device in catalog["types"]:
        if not isinstance(device,dict) or not isinstance(device.get("type"),str) or device["type"] in actual or not isinstance(device.get("actions"),list):
            raise NativeCatalogError("Invalid DAW native instrument type catalog.")
        actions={}
        for action in device["actions"]:
            if not isinstance(action,dict) or not isinstance(action.get("command"),str) or action["command"] in actions or not isinstance(action.get("parameters"),list):
                raise NativeCatalogError("Invalid DAW native instrument action catalog.")
            parameters={}
            for parameter in action["parameters"]:
                if not isinstance(parameter,dict) or not isinstance(parameter.get("name"),str) or parameter["name"] in parameters:
                    raise NativeCatalogError("Invalid DAW native instrument parameter catalog.")
                parameters[parameter["name"]]={k:v for k,v in parameter.items() if k!="name"}
            actions[action["command"]]=parameters
        actual[device["type"]]={"actions":actions,**{field:device.get(field) for field in (
            "readable","scope","asynchronous","single_action","sample_must_be_loaded","model_can_assign_path","model_can_create")}}
    if actual!=expected:
        raise NativeCatalogError("DAW and Agent native instrument catalogs differ. Related edits are disabled. Update to matching versions.")
    return True
