// Selection is a disposable control-thread projection, never musical state.
namespace {
// Rebuilt only for this validation pass. Positions refer to the current bindings
// and cannot outlive a failed edit/rollback or vector reallocation.
struct SelectionObjectIndex {
    std::map<juce::String,size_t> tracks;
    std::map<juce::String,std::pair<size_t,size_t>> clips;
    template<class Bindings> void rebuild(const Bindings& bindings,bool includeClips=true) {
        tracks.clear();clips.clear();
        for(size_t t=0;t<bindings.size();++t){
            tracks.emplace(bindings[t].id,t);
            if(includeClips)for(size_t c=0;c<bindings[t].clips.size();++c)
                clips.emplace(bindings[t].clips[c].id,std::make_pair(t,c));
        }
    }
};
template<class Notes> SelectionNoteIdSet selectionNoteIdIndex(const Notes& notes) {
    SelectionNoteIdSet index;
    // Membership only: canonical selection is independently sorted below.
    // Reserve once so a dense snapshot does not repeatedly rehash on rebuild.
    index.max_load_factor(0.7f);index.reserve(notes.size());
    for(const auto& note:notes)index.insert(note.id);
    return index;
}
}

void EngineSession::Impl::refreshSelectionContext(const juce::var* proposed)
{
    const auto project=juce::String(guard.projectId());
    if(!proposed && selectionMusicRevision==guard.revision() && selectionState["project_id"].toString()==project)return;
    auto input=proposed?proposed->clone():selectionState.clone();
    const bool wrongProject=input.hasProperty("project_id")&&input["project_id"].toString()!=project;
    if(!input.isObject()||wrongProject)input=object({});
    const auto hasIds=[&](const char* key){const auto* values=input[key].getArray();return values&&values->size()>0;};
    const bool needClips=hasIds("clip_ids")||input["active_clip_id"].toString().isNotEmpty()||input["note_clip_id"].toString().isNotEmpty();
    SelectionObjectIndex objectIndex;
    if(needClips||hasIds("track_ids")||input["active_track_id"].toString().isNotEmpty())objectIndex.rebuild(bindings,needClips);
    const auto clipBinding=[&](const juce::String& id,Binding** parent=nullptr)->ClipBinding*{
        if(id.isEmpty())return nullptr;
        const auto found=objectIndex.clips.find(id);if(found==objectIndex.clips.end())return nullptr;
        auto& track=bindings[found->second.first];if(parent)*parent=&track;
        return &track.clips[found->second.second];
    };
    bool available=true;
    auto validIds=[&](const char* key,bool clipIds){
        juce::StringArray result;
        std::set<juce::String> unique;
        if(auto* array=input[key].getArray()){
            const int maximum=clipIds?4096:64;
            if(array->size()>maximum){available=false;return result;}
            for(const auto& value:*array){if(!value.isString()){available=false;continue;}
                const auto id=value.toString();if((clipIds?objectIndex.clips.contains(id):objectIndex.tracks.contains(id))&&unique.insert(id).second)result.add(id);}
            result.sort(false);
        }else if(input.hasProperty(key))available=false;
        return result;
    };
    auto trackIds=validIds("track_ids",false),clipIds=validIds("clip_ids",true);
    auto activeTrack=input["active_track_id"].toString(),activeClip=input["active_clip_id"].toString();
    if(!objectIndex.tracks.contains(activeTrack))activeTrack.clear();
    Binding* activeParent=nullptr;if(!clipBinding(activeClip,&activeParent))activeClip.clear();
    if(activeParent)activeTrack=activeParent->id;
    auto focus=input["focus"].toString();
    if(focus!="arrangement"&&focus!="piano_roll"&&focus!="track")focus="none";
    auto noteClip=input["note_clip_id"].toString();auto* binding=clipBinding(noteClip);
    auto* midi=binding?dynamic_cast<te::MidiClip*>(binding->clip.get()):nullptr;
    juce::StringArray noteIds;int requestedCount=0;bool truncated=false;
    if(auto* values=input["note_ids"].getArray())requestedCount=values->size();
    else if(input.hasProperty("note_ids"))available=false;
    const auto countValue=input["note_count"];
    if(countValue.isInt()||countValue.isInt64()){
        if(juce::int64(countValue)<0||juce::int64(countValue)>100000)available=false;
        else{if(int(countValue)!=requestedCount)available=false;requestedCount=juce::jmax(requestedCount,int(countValue));}
    }
    truncated=requestedCount>2000||bool(input.getProperty("notes_truncated",false));
    if(truncated)available=false;
    if(midi&&!truncated&&requestedCount>0){
        const auto& view=noteView(noteClip,*midi);
        if(selectionNoteSource!=view.notes){
            selectionNoteIndex=selectionNoteIdIndex(*view.notes);selectionNoteSource=view.notes;
        }
        std::set<juce::String> unique;
        if(auto* values=input["note_ids"].getArray())for(const auto& value:*values){
            if(!value.isString()){available=false;continue;}
            const auto id=value.toString();if(selectionNoteIndex.contains(id)&&unique.insert(id).second)noteIds.add(id);
        }
        noteIds.sort(false);
    }else if(!midi){noteClip.clear();requestedCount=0;truncated=false;selectionNoteSource.reset();selectionNoteIndex.clear();}
    if(!truncated)requestedCount=noteIds.size();
    auto range=input["time_range"];bool rangeActive=bool(range.getProperty("active",false));
    double start=0,end=0;
    if(rangeActive){
        auto a=range["start_seconds"],b=range["end_seconds"];
        const auto numeric=[](const juce::var& v){return v.isInt()||v.isInt64()||v.isDouble();};
        if(!numeric(a)||!numeric(b)||!std::isfinite(double(a))||!std::isfinite(double(b))||double(a)<0||double(b)<=double(a)||double(b)>172800){available=false;rangeActive=false;}
        else{start=double(a);end=double(b);}
    }
    // If the selected object disappeared, never silently fall back to another.
    if(focus=="piano_roll"&&noteClip.isEmpty())focus="none";
    if(focus=="track"&&activeTrack.isEmpty())focus="none";
    auto canonical=object({{"project_id",project},{"active_track_id",activeTrack},{"active_clip_id",activeClip},
        {"track_ids",juce::var(trackIds)},{"clip_ids",juce::var(clipIds)},
        {"note_clip_id",noteClip},{"note_ids",juce::var(noteIds)},{"note_count",requestedCount},{"notes_truncated",truncated},
        {"time_range",object({{"active",rangeActive},{"start_seconds",start},{"end_seconds",end}})},
        {"focus",focus},{"available",available}});
    const auto signature=juce::JSON::toString(canonical,true);
    if(signature!=selectionSignature){selectionSignature=signature;++selectionRevision;}
    canonical.getDynamicObject()->setProperty("selection_revision",juce::int64(selectionRevision));
    canonical.getDynamicObject()->setProperty("project_revision",juce::int64(guard.revision()));
    selectionState=std::move(canonical);selectionMusicRevision=guard.revision();
}

void EngineSession::setSelectionContext(const juce::var& context)
{ requireControlThread();impl->refreshSelectionContext(&context); }
juce::var EngineSession::selectionContext() const
{ requireControlThread();impl->refreshSelectionContext();return impl->selectionState.clone(); }

juce::Result EngineSession::runSelectionContextSmokeTest(juce::DynamicObject& report)
{
    requireControlThread();EngineSession test(false);
    const auto run=[&](const char* cmd,juce::var args){return test.execute(cmd,args,test.snapshot().revision);};
    if(auto result=run("create_track",object({{"kind","instrument"},{"name","Selection fixture"}}));result.failed())return result;
    auto state=test.snapshot();const auto track=state.tracks[0].id;
    if(auto result=run("create_midi_clip",object({{"track_id",track},{"start_beats",0.0},{"length_beats",4.0}}));result.failed())return result;
    const auto clip=test.snapshot().tracks[0].clips[0].id;
    juce::Array<juce::var> notes;notes.add(object({{"id","selection-note"},{"pitch",60},{"start_beats",0.0},{"length_beats",1.0},{"velocity",80},{"channel",1}}));
    if(auto result=run("write_notes",object({{"clip_id",clip},{"notes",notes}}));result.failed())return result;
    auto before=test.snapshot();auto input=object({{"project_id",before.projectId},{"active_track_id",track},{"active_clip_id",clip},
        {"track_ids",juce::var(juce::StringArray{track})},{"clip_ids",juce::var(juce::StringArray{clip})},
        {"note_clip_id",clip},{"note_ids",juce::var(juce::StringArray{"selection-note"})},{"focus","piano_roll"}});
    auto emptyNotes=input.clone();emptyNotes.getDynamicObject()->setProperty("note_ids",juce::Array<juce::var>{});
    const auto noteSourceBefore=test.impl->selectionNoteSource;
    const auto noteIndexSizeBefore=test.impl->selectionNoteIndex.size();
    test.setSelectionContext(emptyNotes);
    if(test.impl->selectionNoteSource!=noteSourceBefore||test.impl->selectionNoteIndex.size()!=noteIndexSizeBefore)
        return juce::Result::fail("Empty note selection rebuilt the full note membership index.");
    test.setSelectionContext(input);const auto first=test.selectionContext();const auto selectedRevision=juce::int64(first["selection_revision"]);
    test.setSelectionContext(input);auto second=test.selectionContext();
    if(juce::int64(second["selection_revision"])!=selectedRevision||test.snapshot().revision!=before.revision||test.snapshot().dirty!=before.dirty)
        return juce::Result::fail("Selection polling changed music/selection revision or dirty state.");
    auto changed=input.clone();changed.getDynamicObject()->setProperty("focus","arrangement");test.setSelectionContext(changed);
    auto response=test.executeRequest(object({{"request_id","selection-stale"},{"project_id",before.projectId},{"expected_revision",juce::int64(before.revision)},
        {"expected_selection_revision",selectedRevision},{"command","set_tempo"},{"args",object({{"bpm",100.0}})}}));
    if(response["status"].toString()!="selection_conflict"||test.snapshot().bpm!=120)return juce::Result::fail("Stale selection allowed an edit.");
    if(auto result=run("write_notes",object({{"clip_id",clip},{"notes",juce::Array<juce::var>{}}}));result.failed())return result;
    if(test.selectionContext()["note_ids"].size()!=0)return juce::Result::fail("Removed notes remained selected.");
    auto oversized=input.clone();oversized.getDynamicObject()->setProperty("note_count",100000);test.setSelectionContext(oversized);
    if(bool(test.selectionContext()["available"])||!bool(test.selectionContext()["notes_truncated"]))return juce::Result::fail("Large selection was silently widened.");
    if(auto result=test.newProject(test.snapshot().revision);result.failed())return result;
    const auto cleared=test.selectionContext();
    if(cleared["active_track_id"].toString().isNotEmpty()||cleared["note_ids"].size()!=0)return juce::Result::fail("New project retained old selection.");
    // These exercise the production ID-index algorithms with synthetic IDs.
    // They intentionally do not allocate 4096 real clips, build a playback graph,
    // render JSON/UI, or claim an audio-device/whole-refresh latency measurement.
    struct IdOnly {juce::String id;};
    struct TrackOnly {juce::String id;std::vector<IdOnly> clips;};
    std::vector<TrackOnly> denseTracks;denseTracks.reserve(64);
    std::vector<juce::String> denseClipIds;denseClipIds.reserve(4096);
    for(int t=0;t<64;++t){
        TrackOnly row{"selection-track-"+juce::String(t),{}};row.clips.reserve(64);
        for(int c=0;c<64;++c){
            auto id="00000000-0000-0000-0000-"+juce::String(t*64+c).paddedLeft('0',12);
            denseClipIds.push_back(id);row.clips.push_back({id});
        }
        denseTracks.push_back(std::move(row));
    }
    const auto timings=[](std::vector<double> values){
        std::sort(values.begin(),values.end());
        return object({{"iterations",int(values.size())},{"p50_ms",values[values.size()/2]},
            {"p95_ms",values[size_t(std::ceil(double(values.size())*.95))-1]},{"max_ms",values.back()}});
    };
    SelectionObjectIndex index;std::vector<double> clipSamples;clipSamples.reserve(64);
    for(int round=0;round<64;++round){
        const auto started=juce::Time::getMillisecondCounterHiRes();index.rebuild(denseTracks);
        size_t matched=0;for(const auto& id:denseClipIds)matched+=index.clips.contains(id)?1:0;
        clipSamples.push_back(juce::Time::getMillisecondCounterHiRes()-started);
        if(matched!=4096||index.tracks.size()!=64||index.clips.size()!=4096||index.clips.contains("missing-clip"))
            return juce::Result::fail("Dense selection index lost or invented an object ID.");
    }
    const auto last=denseClipIds.back();const auto found=index.clips.at(last);
    if(found.first!=63||found.second!=63)return juce::Result::fail("Clip index returned the wrong parent.");
    denseTracks.back().clips.pop_back();index.rebuild(denseTracks);
    if(index.clips.contains(last)||index.clips.size()!=4095)return juce::Result::fail("Rebuilt selection index retained a removed clip.");
    index.rebuild(denseTracks,false);
    if(index.tracks.size()!=64||!index.clips.empty())return juce::Result::fail("Track-only selection built a clip index.");
    std::vector<IdOnly> denseNotes;denseNotes.reserve(100000);
    for(int n=0;n<100000;++n)denseNotes.push_back({"10000000-0000-0000-0000-"+juce::String(n).paddedLeft('0',12)});
    const auto noteStarted=juce::Time::getMillisecondCounterHiRes();
    const auto denseNoteIndex=selectionNoteIdIndex(denseNotes);
    const auto noteBuildMs=juce::Time::getMillisecondCounterHiRes()-noteStarted;
    if(denseNoteIndex.size()!=100000||denseNoteIndex.contains("missing-note"))return juce::Result::fail("Dense note membership index changed IDs.");
    std::vector<double> noteSamples;noteSamples.reserve(64);
    for(int round=0;round<64;++round){
        const auto started=juce::Time::getMillisecondCounterHiRes();int matched=0;
        for(int n=0;n<2000;++n)matched+=denseNoteIndex.contains(denseNotes[size_t(n*50)].id)?1:0;
        noteSamples.push_back(juce::Time::getMillisecondCounterHiRes()-started);
        if(matched!=2000)return juce::Result::fail("Cached note selection lost valid IDs.");
    }
    report.setProperty("selection_scope_revision_and_pruning",true);
    report.setProperty("selection_empty_notes_skips_full_index",true);
#if defined(JUCE_DEBUG) && JUCE_DEBUG
    constexpr const char* selectionBuild="Debug";
#else
    constexpr const char* selectionBuild="Release";
#endif
    report.setProperty("selection_index_measurement",object({
        {"scope","Synthetic ID-index CPU time only; excludes real Edit, snapshot/JSON, GUI, plugins and audio"},
        {"operating_system",juce::SystemStats::getOperatingSystemName()},{"cpu_model",juce::SystemStats::getCpuModel()},
        {"build_config",selectionBuild},{"offline",true},{"physical_audio_device",false},
        {"sample_rate_hz",juce::var()},{"buffer_size_samples",juce::var()},
        {"tracks",64},{"clips",4096},{"clip_index_rebuild_and_lookup",timings(clipSamples)},
        {"notes",100000},{"note_index","reserved unordered_set / JUCE hashCode64 / max_load_factor 0.7"},
        {"note_index_cold_build_ms",noteBuildMs},{"selected_notes",2000},
        {"cached_note_membership_lookup",timings(noteSamples)},{"timing_budget_asserted",false}}));
    return juce::Result::ok();
}
