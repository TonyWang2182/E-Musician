// Control-thread-only effect draft. The committed Edit remains authoritative;
// the audio callback consumes the existing bounded atomic parameter publication.
namespace {
bool isEffectGestureCommand(const juce::String& command)
{
    return command=="begin_native_effect_gesture"||command=="update_native_effect_gesture"
        ||command=="end_native_effect_gesture"||command=="cancel_native_effect_gesture";
}
bool exactEffectKeys(const juce::var& args,std::initializer_list<const char*> names)
{
    auto* object=args.getDynamicObject();if(!object||object->getProperties().size()!=int(names.size()))return false;
    for(const auto* name:names)if(!object->hasProperty(name))return false;
    return true;
}
struct EffectDataChange final:juce::UndoableAction {
    juce::ValueTree slot,live;
    juce::MemoryBlock before,after;
    EffectDataChange(juce::ValueTree a,juce::ValueTree b,juce::MemoryBlock from,juce::MemoryBlock to)
        :slot(std::move(a)),live(std::move(b)),before(std::move(from)),after(std::move(to)){}
    bool write(const juce::MemoryBlock& bytes){
        if(!slot.getParent().isValid()||!live.getParent().isValid())return false;
        slot.setProperty("data",juce::var(bytes),nullptr);
        live.setProperty("emEffectData",juce::var(bytes),nullptr);
        return true;
    }
    bool perform()override{return write(after);}
    bool undo()override{return write(before);}
    int getSizeInUnits()override{return int(sizeof(*this)+before.getSize()+after.getSize());}
};
}

juce::Result EngineSession::Impl::effectTarget(const juce::String& trackId,const juce::String& deviceId,
                                             juce::ValueTree& slot,native_effects::Effect*& effect)
{
    juce::ValueTree owner;
    if(trackId=="master")owner=metadata(*edit);
    else if(auto* binding=find(trackId))owner=binding->track->state;
    else return fail("Track not found.");
    slot=owner.getChildWithName("EM_PLUGINS").getChildWithProperty("id",deviceId);
    if(!slot.isValid()||slot["format"].toString()!="E-musician"||slot["role"].toString()!="effect")
        return fail("Native effect does not belong to this track.");
    effect=dynamic_cast<native_effects::Effect*>(livePlugin(*edit,deviceId));
    if(!effect)return fail("Native effect is not available.");
    return juce::Result::ok();
}

juce::Result EngineSession::Impl::prepareEffectState(const juce::var& args,storage::StoredPlugin& proposed,
                                                   juce::ValueTree& slot,native_effects::Effect*& effect)
{
    if(!exactEffectKeys(args,{"track_id","device_id","state"})||!args["track_id"].isString()
        ||!args["device_id"].isString()||!args["state"].isObject())return fail("Native effect needs track_id, device_id and state.");
    const auto trackId=args["track_id"].toString();
    if(auto r=effectTarget(trackId,args["device_id"].toString(),slot,effect);r.failed())return r;
    storage::StoredProject candidate;
    if(trackId=="master")candidate.masterPlugins.push_back(readSlot(slot,true));
    else {storage::StoredTrack track;track.id=trackId;track.plugins.push_back(readSlot(slot,true));candidate.tracks.push_back(std::move(track));}
    if(auto r=native_effects::mutate(candidate,"set_native_effect",args);r.failed())return fail(r.getErrorMessage());
    proposed=trackId=="master"?candidate.masterPlugins.front():candidate.tracks.front().plugins.front();
    return juce::Result::ok();
}

juce::Result EngineSession::Impl::setNativeEffect(const juce::var& args)
{
    storage::StoredPlugin proposed;juce::ValueTree slot;native_effects::Effect* effect=nullptr;
    if(auto r=prepareEffectState(args,proposed,slot,effect);r.failed())return r;
    const auto before=readSlot(slot,true).state;
    if(before==proposed.state){effect->restorePublishedSettings();return juce::Result::ok();}
    remember("Adjust native effect");
    if(!edit->getUndoManager().perform(new EffectDataChange(slot,effect->state,before,proposed.state)))
        return fail("Could not update native effect.");
    recordEdit(false);status="Native effect updated.";return juce::Result::ok();
}

void EngineSession::Impl::cancelEffectGesture()
{
    if(!effectGesture)return;
    // Restore the current committed tree, not a stale before-image. An external
    // edit may legitimately have changed the effect while this draft was open.
    juce::ValueTree slot;native_effects::Effect* effect=nullptr;
    if(effectGesture->projectId==juce::String(guard.projectId())
        &&effectTarget(effectGesture->trackId,effectGesture->deviceId,slot,effect).wasOk())effect->restorePublishedSettings();
    effectGesture.reset();
}

juce::Result EngineSession::Impl::handleEffectGesture(const juce::String& command,const juce::var& args,juce::var* result)
{
    if(command=="begin_native_effect_gesture"){
        if(!exactEffectKeys(args,{"track_id","device_id"})||!args["track_id"].isString()||!args["device_id"].isString())
            return fail("An effect gesture needs track_id and device_id.");
        if(effectGesture)return fail("Finish the current native effect gesture first.");
        if(nativePending||std::any_of(jobs.begin(),jobs.end(),[](const auto& job){return !job->done.load(std::memory_order_acquire);}))
            return fail("Wait for pending project work before adjusting an effect.");
        juce::ValueTree slot;native_effects::Effect* effect=nullptr;
        const auto trackId=args["track_id"].toString(),deviceId=args["device_id"].toString();
        if(auto r=effectTarget(trackId,deviceId,slot,effect);r.failed())return r;
        native_effects::Settings checked;auto proposed=readSlot(slot,true);
        if(auto r=native_effects::decode(proposed,checked);r.failed())return fail(r.getErrorMessage());
        finishGesture();effectGesture=EffectGesture{uid(),juce::String(guard.projectId()),trackId,deviceId,guard.revision(),std::move(proposed)};
        if(result)*result=object({{"gesture_id",effectGesture->id}});
        return juce::Result::ok();
    }
    const bool update=command=="update_native_effect_gesture";
    if(!(update?exactEffectKeys(args,{"gesture_id","state"}):exactEffectKeys(args,{"gesture_id"}))||!args["gesture_id"].isString())
        return fail("Invalid native effect gesture arguments.");
    if(!effectGesture||args["gesture_id"].toString()!=effectGesture->id)return fail("Native effect gesture is no longer active.");
    if(command=="cancel_native_effect_gesture"){cancelEffectGesture();return juce::Result::ok();}
    if(effectGesture->projectId!=juce::String(guard.projectId())||effectGesture->revision!=guard.revision()){
        cancelEffectGesture();return fail("The project changed; native effect preview was cancelled.");
    }
    if(update){
        auto state=object({{"track_id",effectGesture->trackId},{"device_id",effectGesture->deviceId},{"state",args["state"]}});
        storage::StoredPlugin proposed;juce::ValueTree slot;native_effects::Effect* effect=nullptr;
        if(auto r=prepareEffectState(state,proposed,slot,effect);r.failed())return r;
        native_effects::Settings settings;if(auto r=native_effects::decode(proposed,settings);r.failed())return fail(r.getErrorMessage());
        effectGesture->proposed=std::move(proposed);effect->previewSettings(settings);return juce::Result::ok();
    }
    native_effects::Settings settings;
    if(auto r=native_effects::decode(effectGesture->proposed,settings);r.failed()){cancelEffectGesture();return fail(r.getErrorMessage());}
    const auto final=object({{"track_id",effectGesture->trackId},{"device_id",effectGesture->deviceId},{"state",native_effects::encode(settings)}});
    // Keep the preview published across commit; a no-op or failed commit must
    // restore the actual committed value. No graph or plugin instance rebuild.
    auto committed=setNativeEffect(final);cancelEffectGesture();return committed;
}
