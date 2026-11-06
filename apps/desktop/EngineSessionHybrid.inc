// Included after the bounded JSON helpers. No network or model calls occur here.
juce::File computeRoot()
{
    const auto path=juce::SystemStats::getEnvironmentVariable("EMUSICIAN_COMPUTE_ROOT","E:/MusicAgent&DAW/cloud-inference");
    return juce::File::isAbsolutePath(path)?juce::File(path):juce::File("E:/MusicAgent&DAW/cloud-inference");
}
juce::var computeRegistry()
{
    juce::var value;if(analysisJson(computeRoot().getChildFile("compute-registry.json"),value,256*1024).failed())return {};
    return value;
}
bool configuredCompute(const juce::var& registry)
{
    const auto python=registry["python_executable"].toString();
    return int(registry["schema_version"])==1&&bool(registry["available"])&&juce::File::isAbsolutePath(python)&&juce::File(python).existsAsFile();
}
juce::Array<juce::var> cloudProviders(const juce::var& registry,const juce::String& kind={})
{
    juce::Array<juce::var> out;const auto providers=registry["providers"];
    if(providers.isArray())for(const auto& p:*providers.getArray())if(p.isObject()&&(kind.isEmpty()||p["kind"].toString()==kind)&&p["execution"].toString()=="cloud"){
        auto v=p.clone();v.getDynamicObject()->setProperty("available",configuredCompute(registry)&&bool(p["available"]));
        v.getDynamicObject()->setProperty("default",bool(p["default"])||registry["defaults"][juce::Identifier(p["kind"].toString())].toString()==p["model_id"].toString());out.add(v);
    }return out;
}
juce::Result selectAnalysisRoute(const juce::var& providers,const juce::String& kind,const juce::var& args,juce::var& selected)
{
    const auto execution=args.getProperty("execution","auto").toString(),model=args["model_id"].toString();
    if(execution!="auto"&&execution!="local"&&execution!="cloud")return juce::Result::fail("Choose Auto, Local or Cloud execution.");
    if((args.hasProperty("model_id")&&!args["model_id"].isString())||model.length()>256)return juce::Result::fail("Invalid model identifier.");
    int best=-1;
    if(providers.isArray())for(const auto& p:*providers.getArray()){
        if(p["kind"].toString()!=kind||!bool(p["available"])||(execution!="auto"&&p["execution"].toString()!=execution)||(model.isNotEmpty()&&p["model_id"].toString()!=model))continue;
        const int rank=(bool(p["default"])?2:0)+(p["execution"].toString()=="cloud"?1:0);
        if(rank>best){selected=p;best=rank;}
    }
    return best>=0?juce::Result::ok():juce::Result::fail("The selected model and execution location are not available. Choose an available model; no fallback was started.");
}
juce::var candidateMidiTracks(const juce::var& value)
{
    if(value["midi_tracks"].isArray())return value["midi_tracks"];
    juce::Array<juce::var> tracks;
    if(value["notes"].isArray()&&value["notes"].size()>0)tracks.add(object({{"id","notes"},{"name","Transcribed MIDI"},{"instrument","unknown"},{"program",0},{"channel",1},{"is_drum",false},{"notes",value["notes"]},{"controllers",juce::var(juce::Array<juce::var>{})}}));
    return tracks;
}
juce::var candidateSummary(const juce::var& value)
{
    int notes=0,controls=0,tracks=0;const auto midi=candidateMidiTracks(value);
    for(const auto& track:*midi.getArray()){
        notes+=track["notes"].size();controls+=track["controllers"].size();std::set<int> channels;
        for(const auto* key:{"notes","controllers"})if(track[key].isArray())for(const auto& event:*track[key].getArray())channels.insert(int(event.getProperty("channel",track.getProperty("channel",1))));
        tracks+=int(channels.size());
    }
    if(value["kind"].toString()=="separate")tracks=value["stems"].size();
    return object({{"track_count",tracks},{"note_count",notes},{"controller_count",controls},{"program_change_count",value["kind"].toString()=="separate"?0:tracks},{"chord_count",value["chord_regions"].size()},
        {"beat_count",value["beat_events"].size()},{"annotation_count",value["structure_regions"].size()}});
}
juce::Result validateCandidateMidi(const juce::var& value,double duration)
{
    const auto midi=candidateMidiTracks(value);if(midi.size()>64)return juce::Result::fail("Too many transcribed instruments.");
    int notes=0,controllers=0;std::set<juce::String> ids;
    for(const auto& track:*midi.getArray()){
        if(!track.isObject()||!track["notes"].isArray()||!track["controllers"].isArray()||!track["program"].isInt()||int(track["program"])<0||int(track["program"])>127
           ||!track["is_drum"].isBool()||!track["id"].isString()||track["id"].toString().isEmpty()||track["id"].toString().length()>128||!ids.insert(track["id"].toString()).second
           ||!track["instrument"].isString()||track["instrument"].toString().length()>128||track["name"].toString().length()>128)return juce::Result::fail("Invalid MIDI instrument candidate.");
        for(const auto* key:{"notes","controllers"})for(const auto& event:*track[key].getArray()){
            const auto channel=event.getProperty("channel",track.getProperty("channel",1));
            if(!event.isObject()||!channel.isInt()||int(channel)<1||int(channel)>16)return juce::Result::fail("Invalid candidate MIDI channel.");
            if(juce::String(key)=="notes"){
                ++notes;const auto start=event["start_seconds"],length=event["duration_seconds"];
                if(!analysisNumber(start)||!analysisNumber(length)||double(start)<0||double(length)<=0||double(start)+double(length)>duration+1e-7
                   ||!event["pitch"].isInt()||int(event["pitch"])<0||int(event["pitch"])>127||!event["velocity"].isInt()||int(event["velocity"])<1||int(event["velocity"])>127)return juce::Result::fail("Invalid transcribed MIDI note.");
            }else{
                ++controllers;const auto at=event["time_seconds"];
                if(!analysisNumber(at)||double(at)<0||double(at)>duration||!event["controller"].isInt()||int(event["controller"])<0||int(event["controller"])>127
                   ||!event["value"].isInt()||int(event["value"])<0||int(event["value"])>127)return juce::Result::fail("Invalid transcribed MIDI controller.");
            }
        }
    }
    if(notes>100000||controllers>100000||int(candidateSummary(value)["track_count"])>64)return juce::Result::fail("Transcribed events exceed project limits.");
    return juce::Result::ok();
}
juce::var candidateAnnotations(const juce::var& result)
{
    auto value=object({});for(const auto* key:{"beat_events","structure_regions","tempo"})if(!result[key].isVoid())value.getDynamicObject()->setProperty(key,result[key]);return value;
}
