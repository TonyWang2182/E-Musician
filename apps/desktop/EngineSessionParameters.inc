// Native plugin parameters are changed on the control thread. Undo stores two
// scalar values and stable identities, never a plugin pointer or a whole preset.
namespace {
te::AutomatableParameter* exposedParameter(te::Plugin* plugin,const juce::String& id)
{
    auto* external=dynamic_cast<te::ExternalPlugin*>(plugin);
    if(!external||!external->getAudioPluginInstance())return nullptr;
    auto* parameter=external->getAutomatableParameterByID(id).get();
    if(parameter==external->dryGain.get()||parameter==external->wetGain.get())return nullptr;
    return parameter;
}
}

juce::var EngineSession::Impl::getPluginParameters(const juce::var& args)const
{
    const auto id=args.getProperty("plugin_id",{}).toString();
    auto* external=loadedPlugin(*edit,id);
    if(!external)return object({{"error","Plugin is missing or no longer available."}});
    const auto offset=args.getProperty("offset",0),limit=args.getProperty("limit",128);
    if((!offset.isInt()&&!offset.isInt64())||(!limit.isInt()&&!limit.isInt64())
        ||juce::int64(offset)<0||juce::int64(offset)>100000||juce::int64(limit)<1||juce::int64(limit)>256)
        return object({{"error","Invalid parameter page (limit 1 to 256)."}});
    juce::Array<juce::var> page;int count=0;
    for(auto* parameter:external->getAutomatableParameters()){
        if(parameter==external->dryGain.get()||parameter==external->wetGain.get())continue;
        if(count>=int(offset)&&count<int(offset)+int(limit))page.add(object({
            {"id",parameter->paramID},{"name",parameter->getParameterName()},
            {"value",double(parameter->getCurrentNormalisedValue())},
            {"text",parameter->getCurrentValueAsStringWithLabel()},{"active",parameter->isParameterActive()}}));
        ++count;
    }
    return object({{"plugin_id",id},{"total",count},{"offset",offset},{"parameters",page}});
}

juce::Result EngineSession::Impl::setPluginParameter(const juce::var& args)
{
    const auto pluginId=args.getProperty("plugin_id",{}).toString();
    const auto parameterId=args.getProperty("parameter_id",{}).toString();
    const auto raw=args.getProperty("value",{});
    if((!raw.isInt()&&!raw.isInt64()&&!raw.isDouble())||!std::isfinite(double(raw))||double(raw)<0||double(raw)>1)
        return fail("Parameter value must be a finite number between 0 and 1.");
    auto* parameter=exposedParameter(livePlugin(*edit,pluginId),parameterId);
    if(!parameter||!parameter->isParameterActive())return fail("Plugin parameter is missing or inactive.");
    const float before=parameter->valueRange.convertTo0to1(parameter->getCurrentExplicitValue()),after=float(double(raw));
    if(before==after)return juce::Result::ok();
    struct Change final:juce::UndoableAction {
        Impl& owner;juce::String pluginId,parameterId;float before,after;
        Change(Impl& p,juce::String plugin,juce::String parameter,float oldValue,float newValue)
            :owner(p),pluginId(std::move(plugin)),parameterId(std::move(parameter)),before(oldValue),after(newValue){}
        bool write(float value){
            auto* p=exposedParameter(owner.livePlugin(*owner.edit,pluginId),parameterId);
            if(!p)return false;
            p->parameterChangeGestureBegin();p->setNormalisedParameter(value,juce::sendNotification);p->parameterChangeGestureEnd();
            owner.pluginDirty=true;return true;
        }
        bool perform()override{return write(after);}
        bool undo()override{return write(before);}
        int getSizeInUnits()override{return 32;}
    };
    finishGesture();remember("Change plugin parameter");
    if(!edit->getUndoManager().perform(new Change(*this,pluginId,parameterId,before,after)))return fail("Could not change plugin parameter.");
    // Synchronous native notifications describe the same change. Consume their
    // flags before publishing one command revision; later external changes are
    // still observed by the normal timer.
    (void)pluginHost.takeChangedPluginIds();recordEdit();status="Plugin parameter changed.";
    return juce::Result::ok();
}
