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
{
 std::set<juce::String> nativeIds;
 const auto collect=[&](const auto& plugins){for(const auto& plugin:plugins)if(plugin.format=="E-musician"){
     std::vector<juce::String> ids;if(storage::nativePluginAssetIds(plugin,ids).failed())return false;
     nativeIds.insert(ids.begin(),ids.end());}return true;};
 if(!collect(s.masterPlugins))return;
 for(const auto& track:s.tracks)if(!collect(track.plugins))return;
 std::erase_if(s.assets,[&](const auto& a){if(nativeIds.contains(a.id))return false;
     for(const auto& t:s.tracks)for(const auto& c:t.clips)if(c.assetId==a.id||(c.warp.enabled&&c.warp.renderAssetId==a.id))return false;return true;});
}
void syncMidiSeconds(storage::StoredProject& s)
{for(auto& t:s.tracks)for(auto& c:t.clips)if(c.kind=="midi"){c.timelineStart=time::beatsToSeconds(c.startBeats,s.bpm);c.duration=time::beatsToSeconds(c.lengthBeats,s.bpm);c.sourceOffset=0;}}
std::vector<storage::StoredControllerEvent> sliceControllers(const std::vector<storage::StoredControllerEvent>& source,
                                                            double start,double length,bool newIds)
{
    using Event=storage::StoredControllerEvent;using Key=std::pair<int,int>;
    std::vector<Event> result;std::map<Key,Event> preceding;std::set<Key> atBoundary;
    const auto key=[](const Event& e){return Key{e.type,e.type==te::MidiControllerEvent::aftertouchType?e.metadata:0};};
    const auto stateful=[](const Event& e){return e.type==1||e.type==2||e.type==4||e.type==7||e.type==8||e.type==10||e.type==11
        ||(e.type>=64&&e.type<=79)||(e.type>=91&&e.type<=95)||e.type==te::MidiControllerEvent::pitchWheelType
        ||e.type==te::MidiControllerEvent::aftertouchType||e.type==te::MidiControllerEvent::channelPressureType;};
    for(auto event:source){
        if(event.beats<start){
            if(stateful(event)){auto found=preceding.find(key(event));
                if(found==preceding.end()||found->second.beats<=event.beats)preceding[key(event)]=event;}
        }else if(event.beats<=start+length){
            event.beats-=start;if(event.beats==0)atBoundary.insert(key(event));
            if(newIds)event.id=uid();result.push_back(std::move(event));
        }
    }
    // Chase only independent retained state at the edge. Bank/program changes,
    // RPN/NRPN/data-entry sequences and increment/channel-mode actions cannot
    // safely be reconstructed by key sorting, so are not synthesized.
    std::vector<Event> chased;
    for(auto& [type,event]:preceding)if(!atBoundary.contains(type)){event.id=uid();event.beats=0;chased.push_back(std::move(event));}
    // Prior state precedes real boundary events (for example bank-select before
    // a program change), while actual events at the cut retain their ordering.
    result.insert(result.begin(),chased.begin(),chased.end());
    std::stable_sort(result.begin(),result.end(),[](const auto& a,const auto& b){return a.beats<b.beats;});
    return result;
}
}

juce::Result EngineSession::Impl::mutate(storage::StoredProject& s,const juce::String& cmd,const juce::var& a,juce::String& chooseAfter,juce::var* batchResult)
{
    if(!a.isObject())return juce::Result::fail("Command arguments must be an object.");
    auto bad=[](const juce::String& x){return juce::Result::fail(x);};
    auto* t=storedTrack(s,textArg(a,"track_id"));
    auto* c=storedClip(s,textArg(a,"clip_id"));
    juce::var completedBatch;
    if(cmd=="batch"){
        auto v=a.getProperty("commands",{});auto* list=v.getArray();
        if(!list||list->isEmpty()||list->size()>100)return bad("Batch needs 1 to 100 editing commands.");
        struct Reference {juce::String id;int type;}; // 0 clip, 1 track, 2 native effect
        std::map<juce::String,Reference> references;
        const auto validAlias=[](const juce::String& value){
            if(value.isEmpty()||value.length()>40)return false;
            const auto letter=[](juce::juce_wchar ch){return (ch>='A'&&ch<='Z')||(ch>='a'&&ch<='z');};
            if(!letter(value[0]))return false;
            for(int i=1;i<value.length();++i){const auto ch=value[i];if(!letter(ch)&&!(ch>='0'&&ch<='9')&&ch!='_'&&ch!='-')return false;}
            return true;
        };
        const auto resolveId=[&](const juce::var& value,int type,juce::String& resolved){
            if(!value.isString())return bad("Batch object references must be strings.");
            resolved=value.toString();if(!resolved.startsWithChar('@'))return juce::Result::ok();
            const auto alias=resolved.substring(1);const auto found=references.find(alias);
            if(!validAlias(alias)||found==references.end())return bad("Unknown or forward batch reference: "+resolved);
            if(found->second.type!=type)return bad("Batch reference has the wrong object type: "+resolved);
            resolved=found->second.id;return juce::Result::ok();
        };
        for(const auto& child:*list){
            if(!child.isObject())return bad("Each batch child must be an object.");
            for(const auto& field:child.getDynamicObject()->getProperties())
                if(field.name.toString()!="command"&&field.name.toString()!="args"&&field.name.toString()!="as")return bad("Unknown batch child field: "+field.name.toString());
            const auto name=textArg(child,"command");
            if(name.isEmpty()||name=="batch")return bad("A batch child requires a non-nested editing command.");
            auto parameters=child.getProperty("args",object({})).clone();
            if(!parameters.isObject())return bad("Batch child args must be an object.");
            juce::String alias;
            if(child.hasProperty("as")){
                if(!child["as"].isString()||!validAlias(alias=child["as"].toString()))return bad("Batch alias must match [A-Za-z][A-Za-z0-9_-]{0,39}.");
                if(references.contains(alias))return bad("Batch aliases must be unique.");
                if(name!="create_track"&&name!="create_midi_clip"&&name!="duplicate_clips"&&name!="add_native_effect")return bad("This command cannot produce a batch reference.");
            }
            // Only these typed object-ID positions are references. Names, note
            // payloads, plugin IDs and arbitrary nested strings stay literal.
            for(const auto* key:{"track_id","target_track_id","clip_id"})if(parameters.hasProperty(key)){
                juce::String resolved;if(auto r=resolveId(parameters[key],juce::String(key)!="clip_id"?1:0,resolved);r.failed())return r;
                parameters.getDynamicObject()->setProperty(key,resolved);
            }
            if(name=="set_native_effect"&&parameters.hasProperty("device_id")){
                juce::String resolved;if(auto r=resolveId(parameters["device_id"],2,resolved);r.failed())return r;
                parameters.getDynamicObject()->setProperty("device_id",resolved);
            }
            if(parameters.hasProperty("clip_ids")){
                auto* values=parameters["clip_ids"].getArray();if(!values)return bad("clip_ids must be an array.");
                juce::Array<juce::var> resolvedIds;
                for(const auto& value:*values){juce::String resolved;if(auto r=resolveId(value,0,resolved);r.failed())return r;resolvedIds.add(resolved);}
                parameters.getDynamicObject()->setProperty("clip_ids",resolvedIds);
            }
            if(alias.isNotEmpty()&&name=="duplicate_clips"&&idsArg(parameters,"clip_ids").size()!=1)
                return bad("A duplicate_clips alias requires exactly one source clip.");
            // All children still validate the same private candidate. Retain the
            // existing intermediate invariants; nothing reaches the live Edit.
            juce::var childResult;
            if(auto r=mutate(s,name,parameters,chooseAfter,&childResult);r.failed())return r;
            if(alias.isNotEmpty()){
                const int type=name=="create_track"?1:name=="add_native_effect"?2:0;
                const auto id=type==1?s.tracks.back().id:type==2?childResult["device_id"].toString():chooseAfter;
                if(id.isEmpty()||(type==1&&storedTrack(s,id)==nullptr)||(type==0&&storedClip(s,id)==nullptr))return bad("Batch command produced no reference target.");
                references.emplace(alias,Reference{id,type});
            }
        }
        auto refs=object({});
        for(const auto& [alias,reference]:references){
            bool exists=reference.type==1?storedTrack(s,reference.id)!=nullptr:reference.type==0?storedClip(s,reference.id)!=nullptr:false;
            if(reference.type==2){for(const auto& p:s.masterPlugins)if(p.id==reference.id)exists=true;
                for(const auto& t:s.tracks)for(const auto& p:t.plugins)if(p.id==reference.id)exists=true;}
            if(!exists)return bad("A batch reference target was removed before commit.");
            refs.getDynamicObject()->setProperty(alias,reference.id);
        }
        completedBatch=object({{"refs",refs},{"executed_commands",list->size()}});
    }else if(cmd=="create_track"){
        if(a.hasProperty("id")||a.hasProperty("track_id"))return bad("New track IDs are assigned by the engine.");
        storage::StoredTrack added;added.id=uid();added.kind=textArg(a,"kind");added.name=textArg(a,"name").trim();
        if(added.kind!="audio"&&added.kind!="instrument"&&added.kind!="bus")return bad("Track kind must be audio, instrument or bus.");
        if(added.name.isEmpty())added.name=added.kind=="audio"?"Audio":added.kind=="bus"?"Bus":"MIDI";s.tracks.push_back(std::move(added));
    }else if(cmd=="rename_track"){
        if(!t)return bad("Track no longer exists.");auto name=textArg(a,"name").trim();if(name.isEmpty()||name.length()>200)return bad("Track name must contain 1 to 200 characters.");t->name=name;
    }else if(cmd=="set_track_colour"){
        if(!a["track_id"].isString()||a.getDynamicObject()->getProperties().size()!=2)return bad("Track colour needs only track_id and colour.");
        if(!t)return bad("Track no longer exists.");
        if(auto result=storage::canonicalTrackColour(a["colour"],t->colour);result.failed())return result;
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
    else if(cmd=="set_tempo"){
        const double old=s.bpm;s.bpm=number(a,"bpm");if(!std::isfinite(s.bpm)||s.bpm<20||s.bpm>300)return bad("Tempo must be 20 to 300 BPM.");
        for(auto& track:s.tracks)for(auto& clip:track.clips)if(clip.warp.enabled&&clip.warp.followTempo){
            const auto scale=old/s.bpm;clip.timelineStart*=scale;clip.duration*=scale;clip.fadeIn*=scale;clip.fadeOut*=scale;clip.warp.targetBpm=s.bpm;
        }syncMidiSeconds(s);
    }
    else if(cmd=="set_time_signature"){
        auto n=number(a,"numerator"),d=number(a,"denominator");if(!std::isfinite(n)||!std::isfinite(d)||n!=std::floor(n)||d!=std::floor(d)||n<1||n>32||d<1||d>32)return bad("Time signature must use supported integer values.");s.numerator=int(n);s.denominator=int(d);
    }else if(cmd=="set_loop_range"){s.loopStart=number(a,"start_seconds");s.loopEnd=number(a,"end_seconds");}
    else if(cmd=="create_midi_clip"){
        if(a.hasProperty("id")||a.hasProperty("clip_id"))return bad("New clip IDs are assigned by the engine.");
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
    }else if(cmd=="paste_clips"){
        if(clipClipboard.clips.empty()||clipClipboard.projectId!=juce::String(guard.projectId()))return bad("Copy clips from this project before pasting.");
        if(a.hasProperty("clipboard_id")&&(!a["clipboard_id"].isString()||a["clipboard_id"].toString()!=clipClipboard.id))return bad("Clipboard changed. Copy again or read its current identity before pasting.");
        if(a.hasProperty("target_track_id")&&!a["target_track_id"].isString())return bad("target_track_id must be a string.");
        const auto at=number(a,"start_seconds");const auto targetId=textArg(a,"target_track_id");
        if(!std::isfinite(at)||at<0||at>storage::maximumTimelineSeconds)return bad("Paste position is outside the project timeline.");
        int targetRow=-1;for(size_t i=0;i<s.tracks.size();++i)if(s.tracks[i].id==targetId)targetRow=int(i);
        if(targetId.isNotEmpty()&&targetRow<0)return bad("The paste target track no longer exists.");
        // Clipboard holds content, so deleting/changing its source clips does not
        // change a later paste. Never create plugin instances or duplicate media.
        for(const auto& asset:clipClipboard.assets){
            const auto found=std::find_if(s.assets.begin(),s.assets.end(),[&](const auto& x){return x.id==asset.id;});
            if(found==s.assets.end())s.assets.push_back(asset);
            // Save As may relocate a stable asset into its new .assets folder.
            // The current project owns its canonical path; do not restore the old path.
        }
        const bool musicalOnly=std::all_of(clipClipboard.clips.begin(),clipClipboard.clips.end(),[](const auto& entry){return entry.clip.kind=="midi";});
        for(const auto& entry:clipClipboard.clips){
            storage::StoredTrack* destination=nullptr;
            if(targetRow<0)destination=storedTrack(s,entry.trackId);
            else {const int row=targetRow+entry.row-clipClipboard.firstRow;if(row>=0&&row<int(s.tracks.size()))destination=&s.tracks[size_t(row)];}
            if(!destination||destination->kind!=entry.trackKind)return bad("Paste needs matching audio/MIDI tracks in the same relative row positions.");
            auto copy=entry.clip;copy.id=uid();copy.timelineStart=at+(copy.timelineStart-clipClipboard.originSeconds);
            if(copy.kind=="midi"){
                copy.startBeats=musicalOnly?time::secondsToBeats(at,s.bpm)+entry.clip.startBeats-time::secondsToBeats(clipClipboard.originSeconds,clipClipboard.originBpm)
                    :time::secondsToBeats(copy.timelineStart,s.bpm);
                for(auto& n:copy.notes)n.id=uid();for(auto& e:copy.controllers)e.id=uid();
            }
            chooseAfter=copy.id;destination->clips.push_back(std::move(copy));
        }
    }else if(cmd=="trim_clip"){
        if(!c)return bad("Clip no longer exists.");auto start=number(a,"start_seconds"),end=number(a,"end_seconds");
        if(!std::isfinite(start)||!std::isfinite(end)||start<0||end<=start)return bad("Clip trim needs a positive range.");
        if(c->kind=="audio"){
            c->sourceOffset=number(a,"source_offset",c->sourceOffset+(start-c->timelineStart)*c->warp.speedRatio());c->timelineStart=start;c->duration=end-start;
            c->fadeIn=juce::jmin(c->fadeIn,c->duration);c->fadeOut=juce::jmin(c->fadeOut,c->duration-c->fadeIn);
        }else{
            auto delta=time::secondsToBeats(start,s.bpm)-c->startBeats;c->startBeats=time::secondsToBeats(start,s.bpm);c->lengthBeats=time::secondsToBeats(end-start,s.bpm);
            c->controllers=sliceControllers(c->controllers,delta,c->lengthBeats,false);
            for(auto& n:c->notes){auto a0=n.startBeats-delta,a1=a0+n.lengthBeats;n.startBeats=juce::jmax(0.0,a0);n.lengthBeats=juce::jmin(c->lengthBeats,a1)-n.startBeats;}
            std::erase_if(c->notes,[](const auto& n){return n.lengthBeats<=0;});syncMidiSeconds(s);
        }
    }else if(cmd=="split_clip"){
        storage::StoredTrack* parent=nullptr;c=storedClip(s,textArg(a,"clip_id"),&parent);if(!c)return bad("Clip no longer exists.");const auto at=number(a,"at_seconds");
        if(!std::isfinite(at)||at-c->timelineStart<time::minimumEditSpanSeconds||c->timelineStart+c->duration-at<time::minimumEditSpanSeconds)return bad("Split must leave at least 1 microsecond on each side.");
        auto right=*c;right.id=uid();chooseAfter=right.id;double left=at-c->timelineStart;
        right.timelineStart=at;right.duration=c->duration-left;c->duration=left;
        if(c->kind=="audio"){right.sourceOffset+=left*c->warp.speedRatio();right.fadeIn=0;right.fadeOut=juce::jmin(right.fadeOut,right.duration);c->fadeOut=0;c->fadeIn=juce::jmin(c->fadeIn,c->duration);}
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
    }else if(cmd=="add_native_effect"||cmd=="set_native_effect"){
        if(auto r=native_effects::mutate(s,cmd,a,batchResult);r.failed())return r;
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
    syncMidiSeconds(s);if(auto r=storage::validate(s);r.failed())return r;
    if(auto r=production::validateGraph(s);r.failed())return r;
    if(batchResult&&cmd=="batch")*batchResult=std::move(completedBatch);
    return juce::Result::ok();
}

juce::Result EngineSession::Impl::perform(const juce::String& command,const juce::var& args,juce::var* commandResult)
{
    if(!args.isObject())return fail("Command arguments must be an object.");
    if(command=="copy_clips"||command=="cut_clips"){
        ClipClipboard next;next.projectId=juce::String(guard.projectId());next.id=uid();next.originSeconds=storage::maximumTimelineSeconds;next.firstRow=int(storage::maximumTracks);
        try{
            const auto ids=idsArg(args,"clip_ids");std::set<juce::String> chosen(ids.begin(),ids.end());
            if(ids.empty()||chosen.size()!=ids.size())return fail("Select clips to copy; repeated IDs are not allowed.");
            auto source=capture();next.originBpm=source.bpm;
            std::set<juce::String> assets;
            for(size_t row=0;row<source.tracks.size();++row)for(const auto& clip:source.tracks[row].clips)if(chosen.erase(clip.id)){
                next.clips.push_back({source.tracks[row].id,source.tracks[row].kind,int(row),clip});
                next.firstRow=std::min(next.firstRow,int(row));next.originSeconds=std::min(next.originSeconds,clip.timelineStart);
                if(clip.assetId.isNotEmpty())assets.insert(clip.assetId);
                if(clip.warp.enabled)assets.insert(clip.warp.renderAssetId);
            }
            if(!chosen.empty())return fail("A selected clip no longer exists. Select it again.");
            for(const auto& asset:source.assets)if(assets.contains(asset.id))next.assets.push_back(asset);
        }catch(const std::exception& error){return fail(error.what());}
        if(command=="cut_clips")if(auto result=perform("delete_clips",args);result.failed())return result;
        clipClipboard=std::move(next);publish("clipboard_changed",object({{"clip_count",int(clipClipboard.clips.size())}}));
        status=command=="cut_clips"?"Clips cut. Paste at the playhead; Undo restores the cut.":"Clips copied. Select a destination track and paste at the playhead.";
        return juce::Result::ok();
    }
    if(gesture&&command!="open_plugin"&&command!="batch"&&command!="set_track_gain"&&command!="set_master_gain"&&command!="set_track_pan")finishGesture();
    if(command=="set_plugin_parameter")return setPluginParameter(args);
    if(command=="set_native_effect")return setNativeEffect(args);
    if(command=="set_audio_warp")return beginAudioWarp(args,commandResult);
    if(command=="scan_plugins"||command=="cancel_job"||command=="import_audio"||command=="import_midi"||command=="save_project"||command=="open_project"||command=="export_wav"||command=="export_midi")return performJob(command,args);
    if(command=="open_plugin"){
        const auto id=textArg(args,"plugin_id");
        if(args.hasProperty("track_id")){
            if(!args["track_id"].isString()||textArg(args,"track_id").isEmpty())return fail("A valid track ID is required.");
            const auto trackId=textArg(args,"track_id");juce::ValueTree owner;
            if(trackId=="master")owner=metadata(*edit);
            else if(auto* binding=find(trackId))owner=binding->track->state;
            else return fail("Track not found.");
            bool belongs=false;
            for(const auto& slot:owner.getChildWithName("EM_PLUGINS"))if(slot["id"].toString()==id){belongs=true;break;}
            if(!belongs)return fail("Plugin does not belong to the specified track.");
        }
        auto* p=livePlugin(*edit,id);if(!p)return fail("Plugin is missing or no longer available.");return plugins::PluginHost::showEditor(*p);
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
    const auto* batchCommands=args["commands"].getArray();
    const bool colourBatch=command=="batch"&&batchCommands&&!batchCommands->isEmpty()
        &&std::all_of(batchCommands->begin(),batchCommands->end(),[](const auto& child){return child["command"].toString()=="set_track_colour";});
    const bool scalar=colourBatch||command=="set_track_colour"||command=="set_track_gain"||command=="set_track_pan"||command=="set_track_muted"||command=="set_track_solo"
        ||command=="set_master_gain"||command=="set_loop"||command=="set_loop_range"||command=="set_time_signature"||command=="rename_track";
    if(scalar){
        // Validate the small metadata candidate through the same command rules.
        // None of these commands can change note validity or topology, so they
        // must not copy, rehash, validate, or reapply the project's MIDI notes.
        auto candidate=capture(false,false);auto selectedAfter=selectedClip;const auto before=contentKey(candidate);
        juce::var metadataResult;
        if(auto r=mutate(candidate,command,args,selectedAfter,&metadataResult);r.failed())return fail(r.getErrorMessage());
        if(contentKey(candidate)==before){if(commandResult)*commandResult=metadataResult;return juce::Result::ok();}
        if(colourBatch)finishGesture();
        remember(command.replaceCharacter('_',' '));auto* um=&edit->getUndoManager();
        if(colourBatch){
            for(const auto& track:candidate.tracks)if(auto* binding=find(track.id))binding->track->state.setProperty(emColour,track.colour,um);
        }else if(command.startsWith("set_track_")||command=="rename_track"){
            const auto id=textArg(args,"track_id");auto* b=find(id);auto* t=storedTrack(candidate,id);
            if(command=="set_track_gain"||command=="set_track_pan")applyMix(*edit,*b->track->getVolumePlugin(),id,t->gainDb,t->pan,false);
            else if(command=="set_track_muted")b->track->setMute(t->muted);
            else if(command=="set_track_solo")b->track->setSolo(t->solo);
            else if(command=="set_track_colour")b->track->state.setProperty(emColour,t->colour,um);
            else b->track->setName(t->name);
        }else if(command=="set_master_gain")applyMix(*edit,*edit->getMasterVolumePlugin(),{},candidate.masterGainDb,edit->getMasterVolumePlugin()->getPan(),false);
        else if(command=="set_loop")um->perform(new LoopChange(*edit,edit->getTransport().looping.get(),candidate.looping));
        else if(command=="set_loop_range"){
            auto meta=metadata(*edit);meta.setProperty("loopStart",candidate.loopStart,um);meta.setProperty("loopEnd",candidate.loopEnd,um);
        }else if(command=="set_time_signature"){
            auto* sig=edit->tempoSequence.getTimeSig(0);sig->numerator=candidate.numerator;sig->denominator=candidate.denominator;
        }
        if(command=="set_loop"||command=="set_loop_range")refreshRange();
        recordEdit(!colourBatch);status=command.replaceCharacter('_',' ')+" completed.";if(commandResult)*commandResult=metadataResult;return juce::Result::ok();
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
    std::map<juce::String,double> oldWarpRatios;
    for(const auto& track:s.tracks)for(const auto& clip:track.clips)if(clip.warp.enabled)oldWarpRatios.emplace(clip.id,clip.warp.speedRatio());
    const auto pluginTopology=[](const auto& project){juce::StringArray ids;for(const auto& p:project.masterPlugins)ids.add("master:"+p.id);for(const auto& t:project.tracks)for(const auto& p:t.plugins)ids.add(t.id+":"+p.id);return ids;};
    const auto previousTopology=pluginTopology(s);
    juce::var candidateResult;
    try{if(auto r=mutate(s,command,args,selectedAfter,&candidateResult);r.failed())return fail(r.getErrorMessage());}
    catch(const std::exception& e){return fail(e.what());}
    if(contentKey(s)==before){if(commandResult)*commandResult=std::move(candidateResult);return juce::Result::ok();}
    // A tempo edit with following audio must publish tempo, lengths and ready
    // PCM in one transaction. Playback keeps the old complete graph meanwhile.
    bool needsWarp=false;
    for(const auto& track:s.tracks)for(const auto& clip:track.clips)if(clip.warp.enabled)
        if(auto old=oldWarpRatios.find(clip.id);old!=oldWarpRatios.end()&&old->second!=clip.warp.speedRatio())needsWarp=true;
    if(needsWarp)return beginWarpCandidate(std::move(s),selectedAfter,std::move(candidateResult),commandResult);
    // Large third-party instance changes are explicit structural operations.
    if(pluginTopology(s)!=previousTopology)edit->getTransport().stop(false,false);
    // A confirmed batch must not merge into an in-progress GUI gesture. Do this
    // only after candidate validation, so a rejected batch leaves Undo untouched.
    if(command=="batch")finishGesture();
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
    // Tracktion can finish new clip/track properties on a later message turn.
    // Keep those derived writes inside this atomic batch, as recording does;
    // opening an empty transaction here makes one Undo consume only that tail.
    // The next explicit edit, gesture, save or Undo still closes this boundary.
    recordEdit(command!="batch");status=command.replaceCharacter('_',' ')+" completed.";
    if(commandResult)*commandResult=std::move(candidateResult);
    return juce::Result::ok();
}
