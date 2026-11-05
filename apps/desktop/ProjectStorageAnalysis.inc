// Schema 5 metadata is bounded and independently validated. No transient job
// paths, runtime credentials or candidate files belong in a saved project.
juce::var serializeAnalyses(const StoredProject& p)
{
    juce::Array<var> items;
    for(const auto& a:p.analyses){auto* v=new juce::DynamicObject();
        v->setProperty("id",a.id);v->setProperty("kind",a.kind);v->setProperty("model_id",a.modelId);v->setProperty("model_version",a.modelVersion);
        v->setProperty("source_clip_id",a.sourceClipId);v->setProperty("source_asset_id",a.sourceAssetId);v->setProperty("source_sha256",a.sourceSha256);v->setProperty("result_sha256",a.resultSha256);
        v->setProperty("parameters_json",a.parametersJson);v->setProperty("start_seconds",a.startSeconds);v->setProperty("duration_seconds",a.durationSeconds);items.add(v);
    }return items;
}
juce::var serializeChords(const StoredProject& p)
{
    juce::Array<var> items;
    for(const auto& a:p.chordRegions){auto* v=new juce::DynamicObject();v->setProperty("id",a.id);v->setProperty("label",a.label);v->setProperty("analysis_id",a.analysisId);
        v->setProperty("start_seconds",a.startSeconds);v->setProperty("end_seconds",a.endSeconds);v->setProperty("score",a.score);v->setProperty("uncertain",a.uncertain);items.add(v);
    }return items;
}
bool validChordLabel(const juce::String& label)
{
    if(label=="N")return true;
    for(const auto* root:{"C","C#","D","D#","E","F","F#","G","G#","A","A#","B"})
        for(const auto* quality:{"maj","min","7","maj7","min7","dim","aug","sus2","sus4","hdim7","dim7"})
            if(label==juce::String(root)+":"+quality)return true;
    return false;
}
Result validateAnalysis(const StoredProject& p)
{
    if((!p.analyses.empty()||!p.chordRegions.empty())&&p.schemaVersion!=5)return Result::fail("Analysis data requires project schema 5.");
    if(p.analyses.size()>maximumAnalyses||p.chordRegions.size()>maximumChordRegions)return Result::fail("Analysis metadata limit exceeded.");
    std::set<juce::String> ids,chords;
    for(const auto& a:p.analyses){
        if(!validIdentifier(a.id)||!ids.insert(a.id).second||!validIdentifier(a.sourceClipId)||!validIdentifier(a.sourceAssetId)
           ||(a.kind!="separate"&&a.kind!="transcribe"&&a.kind!="chords")||a.modelId.isEmpty()||a.modelId.length()>256||a.modelVersion.length()>128
           ||a.sourceSha256.length()!=64||!a.sourceSha256.containsOnly("0123456789abcdef")||a.resultSha256.length()!=64||!a.resultSha256.containsOnly("0123456789abcdef")
           ||a.parametersJson.getNumBytesAsUTF8()>4096||!juce::JSON::parse(a.parametersJson).isObject()
           ||!validTime(a.startSeconds)||!std::isfinite(a.durationSeconds)||a.durationSeconds<=0||!validTime(a.startSeconds+a.durationSeconds))return Result::fail("Invalid analysis provenance.");
    }
    for(const auto& c:p.chordRegions){
        if(!validIdentifier(c.id)||!chords.insert(c.id).second||!ids.contains(c.analysisId)||!validChordLabel(c.label)
           ||!validTime(c.startSeconds)||!validTime(c.endSeconds)||c.endSeconds<=c.startSeconds||!std::isfinite(c.score)||c.score<0||c.score>1)return Result::fail("Invalid chord region.");
    }return Result::ok();
}
Result parseAnalysis(const var& object,StoredProject& p)
{
    auto records=object["analyses"],regions=object["chord_regions"];
    if(!records.isArray()||!regions.isArray()||records.size()>int(maximumAnalyses)||regions.size()>int(maximumChordRegions))return Result::fail("Invalid analysis arrays.");
    for(const auto& a:*records.getArray()){
        if(!a.isObject())return Result::fail("Invalid analysis object.");
        for(const auto* key:{"id","kind","model_id","model_version","source_clip_id","source_asset_id","source_sha256","result_sha256","parameters_json"})
            if(!a[key].isString())return Result::fail("Invalid analysis string.");
        if(!number(a["start_seconds"])||!number(a["duration_seconds"]))return Result::fail("Invalid analysis time.");
        p.analyses.push_back({a["id"].toString(),a["kind"].toString(),a["model_id"].toString(),a["model_version"].toString(),a["source_clip_id"].toString(),a["source_asset_id"].toString(),a["source_sha256"].toString(),a["result_sha256"].toString(),a["parameters_json"].toString(),double(a["start_seconds"]),double(a["duration_seconds"])});
    }
    for(const auto& a:*regions.getArray()){
        if(!a.isObject()||!a["id"].isString()||!a["label"].isString()||!a["analysis_id"].isString()||!number(a["start_seconds"])||!number(a["end_seconds"])||!number(a["score"])||!a["uncertain"].isBool())return Result::fail("Invalid chord object.");
        p.chordRegions.push_back({a["id"].toString(),a["label"].toString(),a["analysis_id"].toString(),double(a["start_seconds"]),double(a["end_seconds"]),double(a["score"]),bool(a["uncertain"])});
    }return validateAnalysis(p);
}
