namespace {
double number(const juce::var& a,const char* k,double fallback=std::numeric_limits<double>::quiet_NaN())
{auto v=a.getProperty(k,{});return v.isInt()||v.isInt64()||v.isDouble()?double(v):fallback;}
juce::String textArg(const juce::var& a,const char* k){auto v=a.getProperty(k,{});return v.isString()?v.toString():juce::String();}
std::vector<juce::String> idsArg(const juce::var& a,const char* key)
{std::vector<juce::String> out;auto value=a.getProperty(key,{});if(value.isVoid())return out;
 if(!value.isArray())throw std::invalid_argument("Object IDs must be an array of strings.");
 for(const auto& id:*value.getArray()){if(!id.isString())throw std::invalid_argument("Every object ID must be a string.");out.push_back(id.toString());}return out;}
storage::StoredTrack* storedTrack(storage::StoredProject& s,const juce::String& id)
{for(auto& t:s.tracks)if(t.id==id)return &t;return nullptr;}
storage::StoredClip* storedClip(storage::StoredProject& s,const juce::String& id,storage::StoredTrack** parent=nullptr)
{for(auto& t:s.tracks)for(auto& c:t.clips)if(c.id==id){if(parent)*parent=&t;return &c;}return nullptr;}
void pruneAssets(storage::StoredProject& s)
{std::erase_if(s.assets,[&](const auto& a){for(const auto& t:s.tracks)for(const auto& c:t.clips)if(c.assetId==a.id)return false;return true;});}
void syncMidiSeconds(storage::StoredProject& s)
{for(auto& t:s.tracks)for(auto& c:t.clips)if(c.kind=="midi"){c.timelineStart=time::beatsToSeconds(c.startBeats,s.bpm);c.duration=time::beatsToSeconds(c.lengthBeats,s.bpm);c.sourceOffset=0;}}
std::vector<storage::StoredControllerEvent> sliceControllers(const std::vector<storage::StoredControllerEvent>& source,
                                                            double start,double length,bool newIds)
{
    using Event=storage::StoredControllerEvent;using Key=std::pair<int,int>;
    std::vector<Event> result;std::map<Key,Event> preceding;std::set<Key> atBoundary;
    const auto key=[](const Event& e){return Key{e.type,e.type==0x1004?e.metadata:0};};
    const auto stateful=[](const Event& e){return (e.type>=0&&e.type<120)||e.type==0x1001
        ||e.type==0x1004||e.type==0x1005||e.type==0x1007;};
    for(auto event:source){
        if(event.beats<start){
            if(stateful(event)){auto found=preceding.find(key(event));
                if(found==preceding.end()||found->second.beats<=event.beats)preceding[key(event)]=event;}
        }else if(event.beats<=start+length){
            event.beats-=start;if(event.beats==0)atBoundary.insert(key(event));
            if(newIds)event.id=uid();result.push_back(std::move(event));
        }
    }
    // Chase persistent controller state at the new edge. Channel-mode actions
    // (all-sound/all-notes-off etc., CC >= 120) must never be replayed here.
    std::vector<Event> chased;
    for(auto& [type,event]:preceding)if(!atBoundary.contains(type)){event.id=uid();event.beats=0;chased.push_back(std::move(event));}
    // Prior state precedes real boundary events (for example bank-select before
    // a program change), while actual events at the cut retain their ordering.
    result.insert(result.begin(),chased.begin(),chased.end());
    std::stable_sort(result.begin(),result.end(),[](const auto& a,const auto& b){return a.beats<b.beats;});
    return result;
}
}

juce::Result EngineSession::Impl::mutate(storage::StoredProject& s,const juce::String& cmd,const juce::var& a,juce::String& chooseAfter)
{
    if(!a.isObject())return juce::Result::fail("Command arguments must be an object.");
    auto bad=[](const juce::String& x){return juce::Result::fail(x);};
    auto* t=storedTrack(s,textArg(a,"track_id"));
    auto* c=storedClip(s,textArg(a,"clip_id"));
    if(cmd=="batch"){
        auto v=a.getProperty("commands",{});auto* list=v.getArray();
        if(!list||list->isEmpty()||list->size()>100)return bad("Batch needs 1 to 100 editing commands.");
        for(const auto& child:*list){auto name=textArg(child,"command");if(name=="batch")return bad("Nested batches are not supported.");
            if(auto r=mutate(s,name,child.getProperty("args",object({})),chooseAfter);r.failed())return r;}
    }else if(cmd=="create_track"){
        storage::StoredTrack added;added.id=uid();added.kind=textArg(a,"kind");added.name=textArg(a,"name").trim();
        if(added.kind!="audio"&&added.kind!="instrument"&&added.kind!="bus")return bad("Track kind must be audio, instrument or bus.");
        if(added.name.isEmpty())added.name=added.kind=="audio"?"Audio":added.kind=="bus"?"Bus":"MIDI";s.tracks.push_back(std::move(added));
    }else if(cmd=="rename_track"){
        if(!t)return bad("Track no longer exists.");auto name=textArg(a,"name").trim();if(name.isEmpty()||name.length()>200)return bad("Track name must contain 1 to 200 characters.");t->name=name;
    }else if(cmd=="reorder_track"){
        if(!t)return bad("Track no longer exists.");double index=number(a,"index");if(!std::isfinite(index)||index!=std::floor(index)||index<0||index>=s.tracks.size())return bad("Invalid track order.");
        auto copy=*t;std::erase_if(s.tracks,[&](const auto& x){return x.id==copy.id;});s.tracks.insert(s.tracks.begin()+int(index),std::move(copy));
    }else if(cmd=="remove_track"){
        if(!t)return bad("Track no longer exists.");auto id=t->id;std::erase_if(s.tracks,[&](const auto& x){return x.id==id;});
        for(auto& track:s.tracks){if(track.outputTargetId==id)track.outputTargetId="master";
            std::erase_if(track.sends,[&](const auto& send){return send.targetTrackId==id;});}
        pruneAssets(s);
    }else if(cmd=="set_track_gain"||cmd=="set_track_pan"||cmd=="set_track_muted"||cmd=="set_track_solo"){
        if(!t)return bad("Track no longer exists.");
        if(cmd=="set_track_gain")t->gainDb=float(number(a,"gain_db"));
        else if(cmd=="set_track_pan")t->pan=float(number(a,"pan"));
        else{const auto key=cmd=="set_track_muted"?"muted":"solo";auto v=a.getProperty(key,{});if(!v.isBool())return bad("Expected a boolean track setting.");if(cmd=="set_track_muted")t->muted=bool(v);else t->solo=bool(v);}
    }else if(cmd=="set_master_gain")s.masterGainDb=float(number(a,"gain_db"));
    else if(cmd=="set_loop") {auto v=a.getProperty("enabled",{});if(!v.isBool())return bad("Loop enabled must be boolean.");s.looping=bool(v);}
    else if(cmd=="set_tempo"){s.bpm=number(a,"bpm");if(!std::isfinite(s.bpm)||s.bpm<20||s.bpm>300)return bad("Tempo must be 20 to 300 BPM.");syncMidiSeconds(s);}
    else if(cmd=="set_time_signature"){
        auto n=number(a,"numerator"),d=number(a,"denominator");if(!std::isfinite(n)||!std::isfinite(d)||n!=std::floor(n)||d!=std::floor(d)||n<1||n>32||d<1||d>32)return bad("Time signature must use supported integer values.");s.numerator=int(n);s.denominator=int(d);
    }else if(cmd=="set_loop_range"){s.loopStart=number(a,"start_seconds");s.loopEnd=number(a,"end_seconds");}
    else if(cmd=="create_midi_clip"){
        if(!t||t->kind!="instrument")return bad("Choose a MIDI instrument track.");storage::StoredClip added;added.id=uid();added.kind="midi";added.startBeats=number(a,"start_beats");added.lengthBeats=number(a,"length_beats");chooseAfter=added.id;t->clips.push_back(std::move(added));syncMidiSeconds(s);
    }else if(cmd=="write_notes"||cmd=="edit_notes"){
        if(!c||c->kind!="midi")return bad("Choose a MIDI clip.");auto value=a.getProperty(cmd=="write_notes"?"notes":"upsert",juce::var(juce::Array<juce::var>{}));auto* notes=value.getArray();
        const auto maximum=cmd=="write_notes"?storage::maximumNotes:size_t(10000);
        if(!notes||size_t(notes->size())>maximum)return bad("Note command exceeds its supported size.");
        std::vector<storage::StoredNote> result;result.reserve(size_t(notes->size()));
        std::set<juce::String> incoming;
        for(const auto& v:*notes){storage::StoredNote n;n.id=textArg(v,"id");if(n.id.isEmpty())n.id=uid();
            const auto pitch=number(v,"pitch"),velocity=number(v,"velocity"),channel=number(v,"channel",1);
            if(!std::isfinite(pitch)||!std::isfinite(velocity)||!std::isfinite(channel)||pitch!=std::floor(pitch)||velocity!=std::floor(velocity)||channel!=std::floor(channel)||pitch<0||pitch>127||velocity<1||velocity>127||channel<1||channel>16)return bad("MIDI pitch, velocity or channel is outside its integer range.");
            if(!incoming.insert(n.id).second)return bad("A note ID is repeated in the command.");
            n.pitch=int(pitch);n.velocity=int(velocity);n.channel=int(channel);n.startBeats=number(v,"start_beats");n.lengthBeats=number(v,"length_beats");result.push_back(std::move(n));
        }
        if(cmd=="edit_notes"){
            auto deleted=idsArg(a,"delete_ids");if(deleted.size()>10000)return bad("At most 10000 note deletions per command.");
            std::set<juce::String> removals;std::map<juce::String,size_t> existing;
            for(size_t i=0;i<c->notes.size();++i)existing[c->notes[i].id]=i;
            for(const auto& id:deleted)if(!existing.contains(id)||!removals.insert(id).second||incoming.contains(id))return bad("A deleted note is missing, repeated or also upserted.");
            for(auto& note:result){if(auto it=existing.find(note.id);it!=existing.end())c->notes[it->second]=std::move(note);else c->notes.push_back(std::move(note));}
            std::erase_if(c->notes,[&](const auto& note){return removals.contains(note.id);});
        }else c->notes=std::move(result);chooseAfter=c->id;
    }else if(cmd=="set_clip_fades"){
        if(!c||c->kind!="audio")return bad("Choose an audio clip.");c->fadeIn=number(a,"fade_in_seconds");c->fadeOut=number(a,"fade_out_seconds");
    }else if(cmd=="move_clip"){
        if(!c)return bad("Clip no longer exists.");auto at=number(a,"start_seconds");if(!std::isfinite(at)||at<0)return bad("Clip start must be non-negative.");c->timelineStart=at;if(c->kind=="midi")c->startBeats=time::secondsToBeats(at,s.bpm);
    }else if(cmd=="move_clips"){
        auto ids=idsArg(a,"clip_ids");auto delta=number(a,"delta_seconds");auto targetId=textArg(a,"target_track_id");auto* target=targetId.isEmpty()?nullptr:storedTrack(s,targetId);
        if(ids.empty()||!std::isfinite(delta)||(!targetId.isEmpty()&&!target))return bad("Invalid clip movement.");
        std::set<juce::String> unique;std::vector<std::pair<juce::String,storage::StoredClip>> moving;
        for(const auto& id:ids){storage::StoredTrack* parent=nullptr;auto* clip=storedClip(s,id,&parent);if(!clip||!unique.insert(id).second)return bad("A clip is missing or repeated.");if(target&&target->kind!=parent->kind)return bad("Audio and MIDI clips need matching track types.");auto next=*clip;next.timelineStart+=delta;if(next.timelineStart<0)return bad("Clips cannot start before zero.");if(next.kind=="midi")next.startBeats=time::secondsToBeats(next.timelineStart,s.bpm);moving.push_back({target?target->id:parent->id,std::move(next)});}
        for(auto& track:s.tracks)std::erase_if(track.clips,[&](const auto& clip){return unique.contains(clip.id);});
        for(auto& [tid,clip]:moving)storedTrack(s,tid)->clips.push_back(std::move(clip));
    }else if(cmd=="trim_clip"){
        if(!c)return bad("Clip no longer exists.");auto start=number(a,"start_seconds"),end=number(a,"end_seconds");
        if(!std::isfinite(start)||!std::isfinite(end)||start<0||end<=start)return bad("Clip trim needs a positive range.");
        if(c->kind=="audio"){
            c->sourceOffset=number(a,"source_offset",c->sourceOffset+start-c->timelineStart);c->timelineStart=start;c->duration=end-start;
            c->fadeIn=juce::jmin(c->fadeIn,c->duration);c->fadeOut=juce::jmin(c->fadeOut,c->duration-c->fadeIn);
        }else{
            auto delta=time::secondsToBeats(start,s.bpm)-c->startBeats;c->startBeats=time::secondsToBeats(start,s.bpm);c->lengthBeats=time::secondsToBeats(end-start,s.bpm);
            c->controllers=sliceControllers(c->controllers,delta,c->lengthBeats,false);
            for(auto& n:c->notes){auto a0=n.startBeats-delta,a1=a0+n.lengthBeats;n.startBeats=juce::jmax(0.0,a0);n.lengthBeats=juce::jmin(c->lengthBeats,a1)-n.startBeats;}
            std::erase_if(c->notes,[](const auto& n){return n.lengthBeats<=0;});syncMidiSeconds(s);
        }
    }else if(cmd=="split_clip"){
        storage::StoredTrack* parent=nullptr;c=storedClip(s,textArg(a,"clip_id"),&parent);if(!c)return bad("Clip no longer exists.");const auto at=number(a,"at_seconds");
        if(!std::isfinite(at)||at-c->timelineStart<0.001||c->timelineStart+c->duration-at<0.001)return bad("Split must leave at least 1 ms on each side.");
        auto right=*c;right.id=uid();chooseAfter=right.id;double left=at-c->timelineStart;
        right.timelineStart=at;right.duration=c->duration-left;c->duration=left;
        if(c->kind=="audio"){right.sourceOffset+=left;right.fadeIn=0;right.fadeOut=juce::jmin(right.fadeOut,right.duration);c->fadeOut=0;c->fadeIn=juce::jmin(c->fadeIn,c->duration);}
        else{
            double beat=time::secondsToBeats(left,s.bpm);c->lengthBeats=beat;right.startBeats+=beat;right.lengthBeats-=beat;right.notes.clear();std::vector<storage::StoredNote> leftNotes;
            right.controllers=sliceControllers(c->controllers,beat,right.lengthBeats,true);
            std::erase_if(c->controllers,[&](const auto& event){return event.beats>=beat;});
            for(auto n:c->notes){const double end=n.startBeats+n.lengthBeats;if(end>beat){auto r=n;r.id=uid();r.startBeats=juce::jmax(0.0,n.startBeats-beat);r.lengthBeats=end-beat-r.startBeats;right.notes.push_back(std::move(r));}if(n.startBeats<beat){n.lengthBeats=juce::jmin(end,beat)-n.startBeats;leftNotes.push_back(std::move(n));}}
            c->notes=std::move(leftNotes);
        }parent->clips.push_back(std::move(right));
    }else if(cmd=="delete_clips"||cmd=="duplicate_clips"){
        auto ids=idsArg(a,"clip_ids");if(ids.empty())return bad("Select at least one clip.");std::set<juce::String> chosen;double first=storage::maximumTimelineSeconds,last=0;
        for(const auto& id:ids){auto* clip=storedClip(s,id);if(!clip||!chosen.insert(id).second)return bad("A clip is missing or repeated.");first=juce::jmin(first,clip->timelineStart);last=juce::jmax(last,clip->timelineStart+clip->duration);}
        for(auto& track:s.tracks){if(cmd=="delete_clips")std::erase_if(track.clips,[&](const auto& clip){return chosen.contains(clip.id);});
            else{auto originals=track.clips;for(auto copy:originals)if(chosen.contains(copy.id)){copy.id=uid();chooseAfter=copy.id;copy.timelineStart+=last-first;if(copy.kind=="midi"){copy.startBeats=time::secondsToBeats(copy.timelineStart,s.bpm);for(auto& n:copy.notes)n.id=uid();for(auto& event:copy.controllers)event.id=uid();}track.clips.push_back(std::move(copy));}}
        }pruneAssets(s);
    }else if(cmd=="add_plugin"||cmd=="remove_plugin"||cmd=="move_plugin"||cmd=="set_plugin_enabled"){
        auto tid=textArg(a,"track_id");if(tid.isNotEmpty()&&tid!="master"&&!t)return bad("Track no longer exists.");auto& list=t?t->plugins:s.masterPlugins;
        auto& lanes=t?t->automation:s.masterAutomation;
        const auto removeAutomation=[&](const juce::String& pluginId){std::erase_if(lanes,[&](const auto& lane){return lane.target=="plugin_parameter"&&lane.pluginId==pluginId;});};
        auto id=textArg(a,"plugin_id");auto it=std::find_if(list.begin(),list.end(),[&](const auto& p){return p.id==id;});
        if(cmd=="add_plugin"){
            juce::PluginDescription desc;if(!pluginHost.getDescription(textArg(a,"catalog_id"),desc))return bad("Plugin is not available. Scan its folder first.");
            if(desc.isInstrument&&(!t||t->kind!="instrument"))return bad("Instrument plugins need a MIDI track.");
            auto p=plugins::PluginHost::describe(desc);p.id=uid();p.role=desc.isInstrument?"instrument":"effect";
            if(desc.isInstrument){for(const auto& old:list)if(old.role=="instrument")removeAutomation(old.id);
                std::erase_if(list,[](const auto& x){return x.role=="instrument";});list.insert(list.begin(),std::move(p));}else list.push_back(std::move(p));
        }else{
            if(it==list.end())return bad("Plugin slot no longer exists.");
            if(cmd=="remove_plugin"){removeAutomation(it->id);list.erase(it);}
            else if(cmd=="set_plugin_enabled"){auto value=a.getProperty("enabled",{});if(!value.isBool())return bad("Plugin enabled must be boolean.");it->enabled=bool(value);}
            else{const auto n=number(a,"index");if(!std::isfinite(n)||n!=std::floor(n)||n<0||n>=list.size())return bad("Invalid plugin order.");auto copy=*it;list.erase(it);list.insert(list.begin()+int(n),std::move(copy));}
        }
    }else if(cmd=="set_track_input"||cmd=="set_track_output"||cmd=="add_send"||cmd=="update_send"||cmd=="remove_send"
             ||cmd=="set_automation_lane"||cmd=="remove_automation_lane"){
        if(auto r=production::mutateGraph(s,cmd,a);r.failed())return r;
    }else return bad("Unsupported editing command: "+cmd);
    syncMidiSeconds(s);if(auto r=storage::validate(s);r.failed())return r;return production::validateGraph(s);
}

juce::Result EngineSession::Impl::perform(const juce::String& command,const juce::var& args)
{
    if(!args.isObject())return fail("Command arguments must be an object.");
    if(gesture&&command!="set_track_gain"&&command!="set_master_gain"&&command!="set_track_pan")finishGesture();
    if(command=="set_plugin_parameter")return setPluginParameter(args);
    if(command=="scan_plugins"||command=="cancel_job"||command=="import_audio"||command=="import_midi"||command=="save_project"||command=="open_project"||command=="export_wav"||command=="export_midi")return performJob(command,args);
    if(command=="open_plugin"){
        auto* p=livePlugin(*edit,textArg(args,"plugin_id"));if(!p)return fail("Plugin is missing or no longer available.");return plugins::PluginHost::showEditor(*p);
    }
    if(command=="undo"||command=="redo"){
        finishGesture();auto& u=edit->getUndoManager();if(command=="undo"?!u.canUndo():!u.canRedo())return fail("No history available.");
        const auto wasPlaying=edit->getTransport().isPlaying();
        if(command=="undo")edit->undo();else edit->redo();
        if(auto cached=pluginHost.cacheDetachedPluginsForUndo(*edit);cached.failed()){
            // Watchers still own removed instances. Reverse the structural
            // history operation before releasing them if capture was refused.
            const bool restored=command=="undo"?u.redo():u.undo();
            rebuild(*edit,bindings);refreshRange();refreshPluginWatches();choose(selected,selectedClip);
            if(!restored)recordEdit();
            if(wasPlaying&&!edit->getTransport().isPlaying())edit->getTransport().play(false);
            return fail(restored?"Undo/Redo was rolled back because plugin state could not be preserved: "+cached.getErrorMessage()
                :"Undo/Redo changed the project but plugin state capture and rollback failed: "+cached.getErrorMessage());
        }
        rebuild(*edit,bindings);refreshRange();refreshPluginWatches();choose(selected,selectedClip);recordEdit();status=command=="undo"?"Undo":"Redo";
        if(wasPlaying&&!edit->getTransport().isPlaying())edit->getTransport().play(false);
        return juce::Result::ok();
    }
    const bool scalar=command=="set_track_gain"||command=="set_track_pan"||command=="set_track_muted"||command=="set_track_solo"
        ||command=="set_master_gain"||command=="set_loop"||command=="set_loop_range"||command=="set_time_signature"||command=="rename_track";
    if(scalar){
        // Validate the small metadata candidate through the same command rules.
        // None of these commands can change note validity or topology, so they
        // must not copy, rehash, validate, or reapply the project's MIDI notes.
        auto candidate=capture(false,false);auto selectedAfter=selectedClip;const auto before=contentKey(candidate);
        if(auto r=mutate(candidate,command,args,selectedAfter);r.failed())return fail(r.getErrorMessage());
        if(contentKey(candidate)==before)return juce::Result::ok();
        remember(command.replaceCharacter('_',' '));auto* um=&edit->getUndoManager();
        if(command.startsWith("set_track_")||command=="rename_track"){
            const auto id=textArg(args,"track_id");auto* b=find(id);auto* t=storedTrack(candidate,id);
            if(command=="set_track_gain"||command=="set_track_pan")applyMix(*edit,*b->track->getVolumePlugin(),id,t->gainDb,t->pan,false);
            else if(command=="set_track_muted")b->track->setMute(t->muted);
            else if(command=="set_track_solo")b->track->setSolo(t->solo);
            else b->track->setName(t->name);
        }else if(command=="set_master_gain")applyMix(*edit,*edit->getMasterVolumePlugin(),{},candidate.masterGainDb,edit->getMasterVolumePlugin()->getPan(),false);
        else if(command=="set_loop")um->perform(new LoopChange(*edit,edit->getTransport().looping.get(),candidate.looping));
        else if(command=="set_loop_range"){
            auto meta=metadata(*edit);meta.setProperty("loopStart",candidate.loopStart,um);meta.setProperty("loopEnd",candidate.loopEnd,um);
        }else if(command=="set_time_signature"){
            auto* sig=edit->tempoSequence.getTimeSig(0);sig->numerator=candidate.numerator;sig->denominator=candidate.denominator;
        }
        if(command=="set_loop"||command=="set_loop_range")refreshRange();
        recordEdit();status=command.replaceCharacter('_',' ')+" completed.";return juce::Result::ok();
    }
    if(command=="edit_notes"||command=="write_notes"){
        Binding* owner=nullptr;auto* binding=findClip(textArg(args,"clip_id"),&owner);
        auto* midi=binding?dynamic_cast<te::MidiClip*>(binding->clip.get()):nullptr;
        if(!midi)return fail("Choose a MIDI clip.");
        const bool replace=command=="write_notes";
        auto values=args.getProperty(replace?"notes":"upsert",juce::var(juce::Array<juce::var>{}));
        if(!values.isArray()||(!replace&&values.getArray()->size()>10000))return fail("Note command exceeds its supported size.");
        auto deleted=replace?std::vector<juce::String>{}:idsArg(args,"delete_ids");
        if(deleted.size()>10000)return fail("At most 10000 note deletions per command.");
        // Validate just the incoming notes using the shared storage/command
        // rules. Existing notes are already valid; the read-only views below
        // enforce project-wide IDs, total count, and the clip channel invariant.
        auto candidate=capture(false,false);juce::String selectedAfter;
        if(auto r=mutate(candidate,"write_notes",object({{"clip_id",binding->id},{"notes",values}}),selectedAfter);r.failed())return fail(r.getErrorMessage());
        auto& incoming=storedClip(candidate,binding->id)->notes;
        std::map<juce::String,const storage::StoredNote*> updates;std::set<juce::String> removals,foundUpdates;
        for(const auto& n:incoming)updates[n.id]=&n;
        for(const auto& id:deleted)if(!removals.insert(id).second||updates.contains(id))return fail("A deleted note is missing, repeated or also upserted.");
        const auto& priorView=noteView(binding->id,*midi);const auto prior=priorView.notes;
        const auto priorEncoded=priorView.encoded;const auto priorOffsets=priorView.valueOffsets;
        const auto same=[](const auto& a,const auto& b){return a.pitch==b.pitch&&a.startBeats==b.startBeats&&a.lengthBeats==b.lengthBeats&&a.velocity==b.velocity&&a.channel==b.channel;};
        size_t total=prior->size(),removed=0,changed=0;const int channel=incoming.empty()?midi->getMidiChannel().getChannelNumber():incoming.front().channel;
        std::vector<std::pair<size_t,const storage::StoredNote*>> nativeEdits;std::vector<size_t> nativeRemovals;
        for(size_t index=0;index<prior->size();++index){
            const auto& n=(*prior)[index];const auto update=updates.find(n.id);
            const bool removing=replace?update==updates.end():removals.contains(n.id);
            if(removing){++removed;nativeRemovals.push_back(index);if(replace)removals.insert(n.id);continue;}
            if(update!=updates.end()){
                foundUpdates.insert(n.id);if(!same(n,*update->second)){++changed;nativeEdits.push_back({index,update->second});}
            }else if(n.channel!=channel)return fail("All notes in one MIDI clip must use the same MIDI channel.");
        }
        if(!replace&&removed!=deleted.size())return fail("A deleted note is missing, repeated or also upserted.");
        const size_t added=incoming.size()-foundUpdates.size();
        std::set<juce::String> newIds;for(const auto& n:incoming)if(!foundUpdates.contains(n.id))newIds.insert(n.id.toLowerCase());
        for(const auto& track:bindings)for(const auto& clip:track.clips)if(auto* other=dynamic_cast<te::MidiClip*>(clip.clip.get())){
            const auto notes=noteView(clip.id,*other).notes;if(clip.id!=binding->id)total+=notes->size();
            // An update to an existing stable ID cannot introduce an ID
            // collision. Only inserted IDs require this project-wide scan.
            if(!newIds.empty())for(const auto& n:*notes)
                if(newIds.contains(n.id.toLowerCase())&&!(clip.id==binding->id&&removals.contains(n.id)))
                    return fail("Note IDs must be valid and unique across the project.");
        }
        if(total-removed+added>storage::maximumNotes)return fail("A project supports at most 100000 MIDI notes.");
        if(removed+added+changed==0)return juce::Result::ok();
        // Many property edits would each make TE search the full EventList.
        // Replace a dense edit as one sequence; small edits touch only changed
        // notes and keep the live clip and unrelated objects in place.
        std::vector<storage::StoredNote> replacement;
        const bool dense=removed+added+changed>128;
        if(dense){
            replacement.reserve(prior->size()-removed+added);
            for(const auto& n:*prior)if(!removals.contains(n.id)){
                if(auto i=updates.find(n.id);i!=updates.end())replacement.push_back(*i->second);
                else replacement.push_back({n.id,n.pitch,n.startBeats,n.lengthBeats,n.velocity,n.channel});
            }
            for(const auto& n:incoming)if(!foundUpdates.contains(n.id))replacement.push_back(n);
        }
        std::optional<NoteView> patchedView;
        if(!dense&&removed==0&&added==0&&channel==midi->getMidiChannel().getChannelNumber()
            &&std::all_of(nativeEdits.begin(),nativeEdits.end(),[&](const auto& change){return (*prior)[change.first].startBeats==change.second->startBeats;})){
            // Timing/order, IDs and channel stay fixed. Reuse the validated
            // view instead of rereading 100000 native notes after a velocity,
            // pitch or length edit. Never mutate snapshots held by the GUI.
            auto notes=std::make_shared<std::vector<NoteSnapshot>>(*prior);
            auto encoded=std::make_shared<juce::MemoryBlock>(*priorEncoded);
            for(const auto& [index,value]:nativeEdits){
                const auto& n=*value;(*notes)[index]={n.id,n.pitch,n.startBeats,n.lengthBeats,n.velocity,n.channel};
                juce::MemoryOutputStream out(static_cast<char*>(encoded->getData())+(*priorOffsets)[index],28);
                writeNoteValues(out,n);jassert(out.getDataSize()==28);
            }
            patchedView=NoteView{midi->getSequence().state,channel,notes,sessionSha256(encoded->getData(),encoded->getSize()),encoded,priorOffsets};
        }
        remember(command.replaceCharacter('_',' '));auto* um=&edit->getUndoManager();
        if(dense)replaceMidiNotes(*midi,replacement,um);
        else{
            auto& seq=midi->getSequence();std::vector<te::MidiNote*> remove;
            std::vector<std::pair<te::MidiNote*,const storage::StoredNote*>> change;
            // The immutable view was created from this sorted list. Resolve
            // only changed indices before tree mutations, instead of walking
            // every live note and reading all emId properties again.
            const auto& live=seq.getNotes();for(auto index:nativeRemovals)remove.push_back(live[int(index)]);
            for(const auto& [index,value]:nativeEdits){
                auto* n=live[int(index)];jassert(n->state[emId].toString()==value->id);change.push_back({n,value});
            }
            for(const auto& [n,value]:change){
                const auto& v=*value;
                n->setNoteNumber(v.pitch,um);n->setStartAndLength(te::BeatPosition::fromBeats(v.startBeats),te::BeatDuration::fromBeats(v.lengthBeats),um);n->setVelocity(v.velocity,um);
            }
            for(auto* n:remove)seq.removeNote(*n,um);
            for(const auto& n:incoming)if(!foundUpdates.contains(n.id))seq.state.addChild(noteTree(n),-1,um);
            if(!incoming.empty())midi->setMidiChannel(te::MidiChannel(channel));
        }
        if(patchedView)noteViews.insert_or_assign(binding->id,std::move(*patchedView));
        choose(owner->id,binding->id);recordEdit();status=command.replaceCharacter('_',' ')+" completed.";return juce::Result::ok();
    }
    auto s=capture();auto selectedAfter=selectedClip;auto before=contentKey(s);
    const auto pluginTopology=[](const auto& project){juce::StringArray ids;for(const auto& p:project.masterPlugins)ids.add("master:"+p.id);for(const auto& t:project.tracks)for(const auto& p:t.plugins)ids.add(t.id+":"+p.id);return ids;};
    const auto previousTopology=pluginTopology(s);
    try{if(auto r=mutate(s,command,args,selectedAfter);r.failed())return fail(r.getErrorMessage());}
    catch(const std::exception& e){return fail(e.what());}
    if(contentKey(s)==before)return juce::Result::ok();
    // Large third-party instance changes are explicit structural operations.
    if(pluginTopology(s)!=previousTopology)edit->getTransport().stop(false,false);
    remember(command.replaceCharacter('_',' '));
    auto applied=juce::Result::ok();
    try{applied=applyTo(*edit,s,bindings,false);}
    catch(const std::exception& error){applied=juce::Result::fail(error.what());}
    catch(...){applied=juce::Result::fail("The edit could not be applied.");}
    if(applied.failed()){
        edit->getUndoManager().undoCurrentTransactionOnly();rebuild(*edit,bindings);refreshRange();refreshPluginWatches();
        return fail(applied.getErrorMessage());
    }
    refreshRange();refreshPluginWatches();if(auto* c=findClip(selectedAfter)){Binding* parent=nullptr;findClip(c->id,&parent);choose(parent->id,c->id);}else choose(selected);
    if(command=="create_track"&&!bindings.empty())choose(bindings.back().id);
    recordEdit();status=command.replaceCharacter('_',' ')+" completed.";return juce::Result::ok();
}
