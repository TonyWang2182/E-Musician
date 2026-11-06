// Helpers in storage's public namespace (not the local validation namespace).
juce::var audioWarpToVar(const StoredAudioWarp& w)
{
    auto* v=new juce::DynamicObject();v->setProperty("enabled",w.enabled);v->setProperty("follow_tempo",w.followTempo);
    v->setProperty("source_bpm",w.sourceBpm);v->setProperty("target_bpm",w.targetBpm);v->setProperty("mode",w.mode);
    v->setProperty("render_asset_id",w.renderAssetId);v->setProperty("source_sha256",w.sourceHash);v->setProperty("render_sha256",w.renderHash);return v;
}
juce::Result audioWarpFromVar(const juce::var& v,StoredAudioWarp& w)
{
    if(!v.isObject()||!v["enabled"].isBool()||!v["follow_tempo"].isBool()||!v["mode"].isString()
       ||!v["render_asset_id"].isString()||!v["source_sha256"].isString()||!v["render_sha256"].isString())
        return juce::Result::fail("Invalid audio Warp fields.");
    const auto numeric=[](const juce::var& x){return x.isDouble()||x.isInt()||x.isInt64();};
    if(!numeric(v["source_bpm"])||!numeric(v["target_bpm"]))return juce::Result::fail("Invalid Warp BPM.");
    w={bool(v["enabled"]),bool(v["follow_tempo"]),double(v["source_bpm"]),double(v["target_bpm"]),v["mode"].toString(),
        v["render_asset_id"].toString(),v["source_sha256"].toString(),v["render_sha256"].toString()};
    return juce::Result::ok();
}
int requiredSchema(const StoredProject& p)
{
    if(!p.generations.empty())return 7;
    for(const auto& t:p.tracks)for(const auto& c:t.clips)if(c.warp.enabled)return 6;
    for(const auto& a:p.analyses)if(a.kind=="beats")return 6;
    return p.analyses.empty()&&p.chordRegions.empty()?4:5;
}
