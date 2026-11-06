// Public validators shared by immutable candidates and schema 8 persistence.
bool isSupportedChordLabel(const juce::String& label)
{
    if(label.isEmpty()||label.length()>128||label.trim()!=label)return false;
    for(auto c:label)if(c<32||c==127)return false;
    return true; // Preserve model spelling/extensions/slash bass; no vocabulary reduction.
}
juce::Result validateAnalysisAnnotations(const juce::var& value,double duration)
{
    const auto fail=[](const char* message){return juce::Result::fail(message);};
    const auto numeric=[](const juce::var& x){return (x.isInt()||x.isInt64()||x.isDouble())&&std::isfinite(double(x));};
    if(!value.isObject())return fail("Accepted analysis metadata must be an object.");
    for(const auto* key:{"beat_events","structure_regions","midi_tracks"}){
        const auto list=value[key];if(list.isVoid())continue;
        if(!list.isArray()||list.size()>(juce::String(key)=="midi_tracks"?64:10000))return fail("Accepted analysis metadata exceeds its limit.");
        double previous=-1;
        for(const auto& item:*list.getArray()){
            if(!item.isObject())return fail("Invalid accepted analysis item.");
            if(juce::String(key)=="beat_events"){
                if(!numeric(item["time_seconds"])||double(item["time_seconds"])<0||double(item["time_seconds"])>=duration||double(item["time_seconds"])<=previous||!item["is_downbeat"].isBool())return fail("Invalid accepted beat position.");
                previous=double(item["time_seconds"]);
            }else if(juce::String(key)=="structure_regions"){
                if(!item["label"].isString()||!isSupportedChordLabel(item["label"].toString())||!numeric(item["start_seconds"])||!numeric(item["end_seconds"])
                   ||double(item["start_seconds"])<0||double(item["end_seconds"])<=double(item["start_seconds"])||double(item["end_seconds"])>duration+1e-7)return fail("Invalid accepted section range.");
            }else{
                if(!item["instrument"].isString()||item["instrument"].toString().length()>128||!item["program"].isInt()||int(item["program"])<0||int(item["program"])>127
                   ||!item["channel"].isInt()||int(item["channel"])<1||int(item["channel"])>16||!item["is_drum"].isBool())return fail("Invalid accepted MIDI instrument metadata.");
            }
        }
    }
    const auto tempo=value["tempo"];
    if(!tempo.isVoid()&&(!tempo.isObject()||juce::JSON::toString(tempo).getNumBytesAsUTF8()>4096))return fail("Invalid accepted tempo metadata.");
    if(tempo.isObject()&&!tempo["bpm"].isVoid()&&(!numeric(tempo["bpm"])||double(tempo["bpm"])<=0||double(tempo["bpm"])>1000))return fail("Invalid estimated tempo.");
    return juce::Result::ok();
}
