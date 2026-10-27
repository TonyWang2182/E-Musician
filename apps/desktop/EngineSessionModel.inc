// Included after Impl. Music is authoritative in Tracktion ValueTrees; these
// DTOs are transient command candidates and persistence snapshots, not a mirror.
namespace {
juce::ValueTree noteTree(const storage::StoredNote& n)
{
    // Keep this schema in step with the pinned MidiList::createNoteValueTree.
    juce::ValueTree tree(te::IDs::NOTE);
    tree.setProperty(te::IDs::p,n.pitch,nullptr);tree.setProperty(te::IDs::b,n.startBeats,nullptr);
    tree.setProperty(te::IDs::l,n.lengthBeats,nullptr);tree.setProperty(te::IDs::v,n.velocity,nullptr);
    tree.setProperty(te::IDs::c,0,nullptr);tree.setProperty(emId,n.id,nullptr);return tree;
}
struct SequenceChange final:juce::UndoableAction {
    juce::ValueTree parent,before,after;
    SequenceChange(juce::ValueTree a,juce::ValueTree b):parent(a.getParent()),before(std::move(a)),after(std::move(b)){}
    bool write(juce::ValueTree from,juce::ValueTree to){
        if(from.getParent()!=parent||to.getParent().isValid())return false;
        const auto index=parent.indexOf(from);parent.removeChild(index,nullptr);parent.addChild(to,index,nullptr);
        // MidiClip and Edit::TreeWatcher do not invalidate the loop cache or
        // playback graph for a whole SEQUENCE attachment. Notify through their
        // existing property path after the swap, also on Undo/Redo. This runs
        // outside tree listeners and does not alter a musical property.
        to.sendPropertyChangeMessage(te::IDs::channelNumber);return true;
    }
    bool perform()override{return write(before,after);}bool undo()override{return write(after,before);}
    int getSizeInUnits()override{return int(sizeof(*this))+(before.getNumChildren()+after.getNumChildren())*64;}
};
void replaceMidiNotes(te::MidiClip& midi,const std::vector<storage::StoredNote>& notes,juce::UndoManager* um)
{
    // Build large sequences detached. Live EventList child insertion performs a
    // linear indexOf even for append; attaching each of 100000 notes is O(N²).
    // The single sequence swap leaves the Edit, track, clip and plugins alive.
    const auto old=midi.getSequence().state;juce::ValueTree next(old.getType());next.copyPropertiesFrom(old,nullptr);
    if(!notes.empty())next.setProperty(te::IDs::channelNumber,notes.front().channel,nullptr);
    for(const auto child:old)if(!child.hasType(te::IDs::NOTE))next.addChild(child.createCopy(),-1,nullptr);
    for(const auto& n:notes)next.addChild(noteTree(n),-1,nullptr);
    if(um){if(!um->perform(new SequenceChange(old,next)))throw std::runtime_error("Could not replace MIDI sequence.");}
    else{SequenceChange change(old,next);if(!change.perform())throw std::runtime_error("Could not replace MIDI sequence.");}
}
struct MixChange final:juce::UndoableAction {
    te::Edit& edit;juce::String trackId;bool pan;float before,after;
    MixChange(te::Edit& e,juce::String id,bool isPan,float a,float b):edit(e),trackId(std::move(id)),pan(isPan),before(a),after(b){}
    bool write(float value){
        te::VolumeAndPanPlugin* plugin=nullptr;
        if(trackId.isEmpty())plugin=edit.getMasterVolumePlugin();
        else for(auto* track:te::getAudioTracks(edit))if(track->state[emId].toString()==trackId){plugin=track->getVolumePlugin();break;}
        if(!plugin)return false;if(pan)plugin->setPan(value);else plugin->setVolumeDb(value);return true;
    }
    bool perform()override{return write(after);}bool undo()override{return write(before);}
    int getSizeInUnits()override{return 24;}
};
struct LoopChange final:juce::UndoableAction {
    te::Edit& edit;bool before,after;
    LoopChange(te::Edit& e,bool a,bool b):edit(e),before(a),after(b){}
    bool perform()override{edit.getTransport().looping=after;return true;}
    bool undo()override{edit.getTransport().looping=before;return true;}
};
void applyMix(te::Edit& edit,te::VolumeAndPanPlugin& plugin,const juce::String& trackId,float gain,float pan,bool loading)
{
    // Automation playback changes the current value; Undo and ordinary fader
    // edits operate on the user's explicit base value instead.
    const float oldGain=stableGain(te::volumeFaderPositionToDB(plugin.volParam->getCurrentExplicitValue()));
    const float oldPan=plugin.panParam->getCurrentExplicitValue();
    if(oldGain!=gain){if(loading)plugin.setVolumeDb(gain);else edit.getUndoManager().perform(new MixChange(edit,trackId,false,oldGain,gain));}
    if(oldPan!=pan){if(loading)plugin.setPan(pan);else edit.getUndoManager().perform(new MixChange(edit,trackId,true,oldPan,pan));}
}
}
juce::Result EngineSession::Impl::applyTo(te::Edit& target,storage::StoredProject s,std::vector<Binding>& out,bool loading)
{
    auto* um=&target.getUndoManager();
    std::map<juce::String,storage::StoredAsset> assets;
    for(const auto& a:s.assets)assets.emplace(a.id,a);
    for(auto& t:s.tracks)for(auto& c:t.clips){
        if(c.kind=="midi"){
            c.timelineStart=time::beatsToSeconds(c.startBeats,s.bpm);c.duration=time::beatsToSeconds(c.lengthBeats,s.bpm);c.sourceOffset=0;
        }else{
            auto a=assets.find(c.assetId);if(a==assets.end())return fail("Audio clip has no source asset.");
            auto p=prepared.find(a->second.source.getFullPathName());if(p==prepared.end())return fail("Audio source is not prepared.");
            if(s.schemaVersion==1)c.duration=p->second.duration;
            if(c.sourceOffset+c.duration>p->second.duration+1.0e-9)return fail("Clip exceeds its source audio.");
        }
    }
    s.schemaVersion=4;
    if(auto r=storage::validate(s);r.failed())return fail(r.getErrorMessage());
    if(auto r=production::validateGraph(s);r.failed())return fail(r.getErrorMessage());
    std::map<juce::String,te::AudioTrack*> tracks;
    std::map<juce::String,te::Clip::Ptr> clips;
    for(auto* t:te::getAudioTracks(target)){
        tracks[t->state[emId].toString()]=t;
        for(auto* c:t->getClips())clips[c->state[emId].toString()]=c;
    }
    // Cache native preset bytes outside Undo before removing an instance. The
    // removed ValueTree then contains the latest patch even after cache eviction.
    if(!loading){
        std::set<juce::String> surviving;
        for(const auto& p:s.masterPlugins)surviving.insert(p.id);
        for(const auto& t:s.tracks)for(const auto& p:t.plugins)surviving.insert(p.id);
        const auto preserve=[&](juce::ValueTree owner,te::PluginList& list){
            for(auto* plugin:list){auto id=plugin->state[emId].toString();if(id.isNotEmpty()&&!surviving.contains(id)){
                auto* external=dynamic_cast<te::ExternalPlugin*>(plugin);
                if(!external||!external->getAudioPluginInstance())continue;
                auto slot=owner.getChildWithName("EM_PLUGINS").getChildWithProperty("id",id);
                if(auto result=plugins::PluginHost::cacheStateForUndo(*plugin,slot);result.failed())return result;
            }}return juce::Result::ok();
        };
        if(auto result=preserve(metadata(target),target.getMasterPluginList());result.failed())return fail(result.getErrorMessage());
        for(auto* track:te::getAudioTracks(target))if(auto result=preserve(track->state,track->pluginList);result.failed())return fail(result.getErrorMessage());
    }
    // Stage new plugin instances before touching the live musical state.
    std::map<juce::String,te::Plugin::Ptr> newPlugins;
    auto preparePlugins=[&](const auto& ps,juce::ValueTree owner){
        auto slots=owner.getChildWithName("EM_PLUGINS");
        for(const auto& p:ps)if(!livePlugin(target,p.id)&&!slots.getChildWithProperty("id",p.id).isValid()){
            auto result=juce::Result::ok();auto instance=pluginHost.instantiate(target,p,result);
            if(!instance&&!loading)return result.failed()?result:juce::Result::fail("Could not instantiate plugin.");
            newPlugins[p.id]=instance;
        }return juce::Result::ok();
    };
    auto meta=metadata(target);
    if(auto r=preparePlugins(s.masterPlugins,meta);r.failed())return fail(r.getErrorMessage());
    for(const auto& t:s.tracks)if(auto r=preparePlugins(t.plugins,tracks.contains(t.id)?tracks[t.id]->state:juce::ValueTree());r.failed())return fail(r.getErrorMessage());

    target.tempoSequence.getTempo(0)->set(te::BeatPosition::fromBeats(0),s.bpm,0,false);
    auto* sig=target.tempoSequence.getTimeSig(0);sig->numerator=s.numerator;sig->denominator=s.denominator;
    meta.setProperty("loopStart",s.loopStart,um);meta.setProperty("loopEnd",s.loopEnd,um);
    auto syncPlugins=[&](const auto& wanted,juce::ValueTree owner,te::PluginList& list)->juce::Result{
        auto slots=owner.getOrCreateChildWithName("EM_PLUGINS",um);
        for(int i=slots.getNumChildren();--i>=0;){auto old=slots.getChild(i);auto id=old["id"].toString();
            if(std::none_of(wanted.begin(),wanted.end(),[&](const auto& p){return p.id==id;})){
                if(auto* p=livePlugin(target,id)){pluginHost.unwatchPlugin(id);plugins::PluginHost::closeEditor(*p);p->deleteFromParent();}slots.removeChild(i,um);
            }
        }
        int index=0;
        for(const auto& p:wanted){
            auto slot=slots.getChildWithProperty("id",p.id);
            if(!slot.isValid()){slot=slotTree(p);slots.addChild(slot,index,um);}else{
                slot.setProperty("enabled",p.enabled,um);slot.setProperty("role",p.role,um);
                slots.moveChild(slots.indexOf(slot),index,um);
            }
            te::Plugin::Ptr live=livePlugin(target,p.id);
            if(!live&&newPlugins.contains(p.id)){live=newPlugins[p.id];if(live){live->state.setProperty(emId,p.id,um);list.insertPlugin(live,index,nullptr);if(!list.contains(live.get()))return fail("Could not insert plugin into the audio chain.");}}
            if(live){
                live->setEnabled(p.enabled);
                auto parent=live->state.getParent();int first=-1;
                for(auto* item:list)if(item->state[emId].toString().isNotEmpty()){first=parent.indexOf(item->state);break;}
                if(first>=0&&list.indexOf(live.get())!=index)parent.moveChild(parent.indexOf(live->state),first+index,um);
                if(&target==edit.get())pluginHost.watchPlugin(live,p.id);
            }++index;
        }return juce::Result::ok();
    };
    if(auto r=syncPlugins(s.masterPlugins,meta,target.getMasterPluginList());r.failed())return r;
    std::set<juce::String> wantedClips,wantedTracks;
    for(const auto& t:s.tracks){
        wantedTracks.insert(t.id);te::AudioTrack* track=nullptr;
        if(auto it=tracks.find(t.id);it!=tracks.end())track=it->second;
        else{
            target.ensureNumberOfAudioTracks(te::getAudioTracks(target).size()+1);
            track=te::getAudioTracks(target).getLast();track->state.setProperty(emId,t.id,um);tracks[t.id]=track;
        }
        track->state.setProperty(emKind,t.kind,um);track->setName(t.name);applyMix(target,*track->getVolumePlugin(),t.id,t.gainDb,t.pan,loading);
        track->setMute(t.muted);track->setSolo(t.solo);
        if(auto r=syncPlugins(t.plugins,track->state,track->pluginList);r.failed())return r;
        for(const auto& c:t.clips){
            wantedClips.insert(c.id);te::Clip::Ptr clip;
            if(auto it=clips.find(c.id);it!=clips.end())clip=it->second;
            auto range=te::TimeRange{te::TimePosition::fromSeconds(c.timelineStart),te::TimeDuration::fromSeconds(c.duration)};
            if(!clip){
                if(c.kind=="midi")clip=track->insertMIDIClip(t.name,range,nullptr);
                else{
                    const auto& a=assets.at(c.assetId);const auto& info=prepared.at(a.source.getFullPathName());
                    clip=track->insertWaveClip(t.name,info.playbackFile,{range,te::TimeDuration::fromSeconds(c.sourceOffset)},false);
                }
                if(!clip)return fail("Could not insert clip.");
                clip->state.setProperty(emId,c.id,um);
            }else if(clip->getTrack()!=track)clip->moveTo(*track);
            clip->state.setProperty(emKind,c.kind,um);
            clip->setPosition({range,te::TimeDuration::fromSeconds(c.sourceOffset)});
            if(auto* midi=dynamic_cast<te::MidiClip*>(clip.get())){
                midi->setSyncType(te::Clip::syncBarsBeats);midi->setUsesProxy(false);
                if(!c.notes.empty())midi->setMidiChannel(te::MidiChannel(c.notes.front().channel));
                if(c.notes.size()>512&&midi->getSequence().getNumNotes()==0){replaceMidiNotes(*midi,c.notes,um);continue;}
                auto& seq=midi->getSequence();std::map<juce::String,te::MidiNote*> existing;
                for(auto* n:seq.getNotes())existing[n->state[emId].toString()]=n;
                std::set<juce::String> wanted;
                for(const auto& n:c.notes){
                    wanted.insert(n.id);te::MidiNote* note=nullptr;
                    if(auto i=existing.find(n.id);i!=existing.end())note=i->second;
                    else{
                        // Pinned MidiList::createNoteValueTree fields, populated
                        // before attachment. addNote/getEventFor and a subsequent
                        // emId property change both scan every existing note.
                        seq.state.addChild(noteTree(n),-1,um);continue;
                    }
                    note->setNoteNumber(n.pitch,um);note->setStartAndLength(te::BeatPosition::fromBeats(n.startBeats),te::BeatDuration::fromBeats(n.lengthBeats),um);note->setVelocity(n.velocity,um);
                }
                for(const auto& [id,n]:existing)if(!wanted.contains(id))seq.removeNote(*n,um);
            }else if(auto* audio=dynamic_cast<te::WaveAudioClip*>(clip.get())){
                audio->setSyncType(te::Clip::syncAbsolute);audio->setAutoTempo(false);audio->setAutoPitch(false);audio->setUsesProxy(false);
                audio->setResamplingQuality(te::ResamplingQuality::sincMedium);
                audio->setFadeInType(te::AudioFadeCurve::linear);audio->setFadeOutType(te::AudioFadeCurve::linear);
                audio->setFadeIn(te::TimeDuration::fromSeconds(c.fadeIn));audio->setFadeOut(te::TimeDuration::fromSeconds(c.fadeOut));
                clip->state.setProperty(emAsset,c.assetId,um);clip->state.setProperty(emSource,assets.at(c.assetId).source.getFullPathName(),um);
            }
        }
    }
    for(const auto& [id,c]:clips)if(id.isNotEmpty()&&!wantedClips.contains(id))c->removeFromParent();
    for(const auto& [id,t]:tracks)if(!wantedTracks.contains(id)){
        for(auto* p:t->pluginList){auto pid=p->state[emId].toString();if(pid.isNotEmpty()){pluginHost.unwatchPlugin(pid);plugins::PluginHost::closeEditor(*p);}}
        target.deleteTrack(t);
    }
    auto ordered=te::getAudioTracks(target);
    if(!ordered.isEmpty()){
        auto parent=ordered[0]->state.getParent();int base=parent.indexOf(ordered[0]->state);
        for(size_t i=0;i<s.tracks.size();++i){auto* t=tracks.at(s.tracks[i].id);parent.moveChild(parent.indexOf(t->state),base+int(i),um);}
    }
    applyMix(target,*target.getMasterVolumePlugin(),{},s.masterGainDb,0,loading);
    if(target.getTransport().looping.get()!=s.looping){if(loading)target.getTransport().looping=s.looping;
        else target.getUndoManager().perform(new LoopChange(target,target.getTransport().looping.get(),s.looping));}
    // All external plugin instances and clip identities exist now. Graph
    // helpers preserve native curves/controllers and join this Undo transaction.
    if(auto r=production::applyGraph(target,s,loading);r.failed())return fail(r.getErrorMessage());
    rebuild(target,out);return juce::Result::ok();
}
