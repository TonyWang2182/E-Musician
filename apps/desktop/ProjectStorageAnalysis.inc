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
    if(!p.generations.empty()&&p.schemaVersion<7)return Result::fail("Generated audio requires project schema 7.");
    if(p.generations.size()>maximumAnalyses)return Result::fail("Generation metadata limit exceeded.");
    std::set<juce::String> generationIds;
    for(const auto& g:p.generations){
        if(!validIdentifier(g.id)||!generationIds.insert(g.id).second||!validIdentifier(g.assetId)||!validIdentifier(g.clipId)
           ||g.modelId.isEmpty()||g.modelId.length()>256||g.modelRevision.length()>128
           ||g.audioSha256.length()!=64||!g.audioSha256.containsOnly("0123456789abcdef")||g.resultSha256.length()!=64||!g.resultSha256.containsOnly("0123456789abcdef")
           ||g.parametersJson.getNumBytesAsUTF8()>32768||!juce::JSON::parse(g.parametersJson).isObject()
           ||!validTime(g.startSeconds)||!std::isfinite(g.durationSeconds)||g.durationSeconds<=0||!validTime(g.startSeconds+g.durationSeconds))return Result::fail("Invalid generation provenance.");
    }
    if((!p.analyses.empty()||!p.chordRegions.empty())&&p.schemaVersion<5)return Result::fail("Analysis data requires project schema 5 or later.");
    if(p.analyses.size()>maximumAnalyses||p.chordRegions.size()>maximumChordRegions)return Result::fail("Analysis metadata limit exceeded.");
    std::set<juce::String> ids,chords;
    for(const auto& a:p.analyses){
        if(!validIdentifier(a.id)||!ids.insert(a.id).second||!validIdentifier(a.sourceClipId)||!validIdentifier(a.sourceAssetId)
           ||(a.kind!="separate"&&a.kind!="transcribe"&&a.kind!="chords"&&a.kind!="beats")||(a.kind=="beats"&&p.schemaVersion<6)||a.modelId.isEmpty()||a.modelId.length()>256||a.modelVersion.length()>128
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
    if(p.schemaVersion>=7){
        const auto records=object["generations"];if(!records.isArray()||records.size()>int(maximumAnalyses))return Result::fail("Invalid generation records.");
        for(const auto& g:*records.getArray()){
            if(!g.isObject())return Result::fail("Invalid generation record.");
            for(const auto* key:{"id","asset_id","clip_id","model_id","model_revision","audio_sha256","result_sha256","parameters_json"})if(!g[key].isString())return Result::fail("Invalid generation string.");
            if(!number(g["start_seconds"])||!number(g["duration_seconds"]))return Result::fail("Invalid generation time.");
            p.generations.push_back({g["id"].toString(),g["asset_id"].toString(),g["clip_id"].toString(),g["model_id"].toString(),g["model_revision"].toString(),g["audio_sha256"].toString(),g["result_sha256"].toString(),g["parameters_json"].toString(),double(g["start_seconds"]),double(g["duration_seconds"])});
        }
    }
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
