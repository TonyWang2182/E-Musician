#include "NativeEffects.h"
#include <algorithm>
#include <cmath>

namespace emusician::native_effects {
namespace {
bool numeric(const juce::var& v){return v.isInt()||v.isInt64()||v.isDouble();}
juce::var make(std::initializer_list<std::pair<juce::Identifier,juce::var>> props){auto* o=new juce::DynamicObject;for(const auto& p:props)o->setProperty(p.first,p.second);return juce::var(o);}
void setState(storage::StoredPlugin& p,const juce::var& v){const auto j=juce::JSON::toString(v,true);p.state=juce::MemoryBlock(j.toRawUTF8(),j.getNumBytesAsUTF8());}
}
juce::var encode(const Settings& s){
    if(s.autoFilter)return make({{"version",1},{"type","auto_filter"},{"mode",s.filterSettings.mode==autofilter::Mode::lowPass?"low_pass":"high_pass"},{"frequency_hz",s.filterSettings.frequencyHz},{"resonance_q",s.filterSettings.resonanceQ},{"lfo_enabled",s.filterSettings.lfoEnabled},{"lfo_hz",s.filterSettings.lfoHz},{"lfo_depth",s.filterSettings.lfoDepth},{"dry_wet",s.filterSettings.dryWet}});
    if(s.reverb)return make({{"version",1},{"type","reverb"},{"decay_seconds",s.reverbSettings.decaySeconds},{"damping",s.reverbSettings.damping},{"dry_wet",s.reverbSettings.dryWet}});
    if(s.delay)return make({{"version",1},{"type","delay"},{"delay_ms",s.delaySettings.delayMs},{"feedback",s.delaySettings.feedback},{"dry_wet",s.delaySettings.dryWet}});
    if(!s.eq)return make({{"version",1},{"type","compressor"},{"threshold_db",s.compressor.thresholdDb},{"ratio",s.compressor.ratio},{"attack_ms",s.compressor.attackMs},{"release_ms",s.compressor.releaseMs},{"makeup_db",s.compressor.makeupDb},{"dry_wet",s.compressor.dryWet}});
    juce::Array<juce::var> bands;for(std::size_t i=0;i<s.equalizer.bands.size();++i){const auto& b=s.equalizer.bands[i];bands.add(make({{"enabled",b.enabled},{"frequency",b.frequency},{"gain_db",b.gainDb},{"q",b.q},{"shape",effects::shapeName(b.shape,i)}}));}
    bool needsShapes=false;for(std::size_t i=0;i<s.equalizer.bands.size();++i)
        needsShapes|=effects::effectiveShape(s.equalizer.bands[i].shape,i)!=effects::effectiveShape(effects::FilterShape::legacy,i);
    return make({{"version",needsShapes?2:1},{"type","eq8"},{"bands",bands}});
}
juce::Result decode(const storage::StoredPlugin& p,Settings& s){
    if(p.format!="E-musician"||p.role!="effect"||(p.identifier!="native.eq8"&&p.identifier!="native.compressor"&&p.identifier!="native.delay"&&p.identifier!="native.reverb"&&p.identifier!="native.auto_filter"))return juce::Result::fail("Unsupported native effect identity.");
    if(!p.state.getSize()||p.state.getSize()>16384)return juce::Result::fail("Native effect state size is invalid.");
    const auto v=juce::JSON::parse(juce::String::fromUTF8(static_cast<const char*>(p.state.getData()),int(p.state.getSize())));
    if(!v.isObject()||(!v["version"].isInt()&&!v["version"].isInt64())||(juce::int64(v["version"])!=1&&(p.identifier!="native.eq8"||juce::int64(v["version"])!=2))||!v["type"].isString()||"native."+v["type"].toString()!=p.identifier)return juce::Result::fail("Invalid native effect version or type.");
    s.eq=p.identifier=="native.eq8";s.delay=p.identifier=="native.delay";s.reverb=p.identifier=="native.reverb";s.autoFilter=p.identifier=="native.auto_filter";
    if(s.autoFilter){const auto mode=v["mode"].toString();if(!v["mode"].isString()||(mode!="low_pass"&&mode!="high_pass")||!v["lfo_enabled"].isBool())return juce::Result::fail("Invalid auto filter mode or LFO switch.");
        for(const auto* k:{"frequency_hz","resonance_q","lfo_hz","lfo_depth","dry_wet"})if(!numeric(v[k]))return juce::Result::fail("Invalid auto filter value.");
        s.filterSettings={mode=="low_pass"?autofilter::Mode::lowPass:autofilter::Mode::highPass,float(v["frequency_hz"]),float(v["resonance_q"]),bool(v["lfo_enabled"]),float(v["lfo_hz"]),float(v["lfo_depth"]),float(v["dry_wet"])};
        if(!autofilter::valid(s.filterSettings))return juce::Result::fail("Auto filter values are outside their supported ranges.");
    }else if(s.reverb){for(const auto* k:{"decay_seconds","damping","dry_wet"})if(!numeric(v[k]))return juce::Result::fail("Invalid reverb value.");
        s.reverbSettings={float(v["decay_seconds"]),float(v["damping"]),float(v["dry_wet"])};
        if(!effects::valid(s.reverbSettings))return juce::Result::fail("Reverb values are outside their supported ranges.");
    }else if(s.delay){for(const auto* k:{"delay_ms","feedback","dry_wet"})if(!numeric(v[k]))return juce::Result::fail("Invalid delay value.");
        s.delaySettings={float(v["delay_ms"]),float(v["feedback"]),float(v["dry_wet"])};
        if(!effects::valid(s.delaySettings))return juce::Result::fail("Delay values are outside their supported ranges.");
    }else if(s.eq){auto* bs=v["bands"].getArray();if(!bs||bs->size()!=int(effects::eqBandCount))return juce::Result::fail("EQ needs exactly eight bands.");
        for(int i=0;i<bs->size();++i){const auto& b=bs->getReference(i);if(!b.isObject()||!b["enabled"].isBool()||!numeric(b["frequency"])||!numeric(b["gain_db"])||!numeric(b["q"]))return juce::Result::fail("Invalid EQ band.");
            auto bandShape=effects::FilterShape::legacy;
            if(b.hasProperty("shape")&&(!b["shape"].isString()||!effects::parseShape(b["shape"].toString().toStdString(),bandShape)))return juce::Result::fail("Unsupported EQ filter shape.");
            s.equalizer.bands[std::size_t(i)]={bool(b["enabled"]),float(b["frequency"]),float(b["gain_db"]),float(b["q"]),bandShape};}
        if(!effects::valid(s.equalizer))return juce::Result::fail("EQ values are outside their supported ranges.");
    }else {for(const auto* k:{"threshold_db","ratio","attack_ms","release_ms","makeup_db"})if(!numeric(v[k]))return juce::Result::fail("Invalid compressor value.");
        if(v.hasProperty("dry_wet")&&!numeric(v["dry_wet"]))return juce::Result::fail("Invalid compressor dry/wet value.");
        s.compressor={float(v["threshold_db"]),float(v["ratio"]),float(v["attack_ms"]),float(v["release_ms"]),float(v["makeup_db"]),v.hasProperty("dry_wet")?float(v["dry_wet"]):1.0f};
        if(!effects::valid(s.compressor))return juce::Result::fail("Compressor values are outside their supported ranges.");}
    return juce::Result::ok();
}
juce::Result mutate(storage::StoredProject& project,const juce::String& command,const juce::var& args,juce::var* result){
    if(!args.isObject()||!args["track_id"].isString())return juce::Result::fail("A track ID is required.");
    std::vector<storage::StoredPlugin>* plugins=nullptr;const auto id=args["track_id"].toString();
    if(id=="master")plugins=&project.masterPlugins;else for(auto& t:project.tracks)if(t.id==id){plugins=&t.plugins;break;}
    if(!plugins)return juce::Result::fail("Track not found.");
    if(command=="add_native_effect"){
        const auto type=args["type"].toString();if(std::none_of(supportedTypes.begin(),supportedTypes.end(),[&](const char* item){return type==item;}))return juce::Result::fail("Unknown native effect.");
        storage::StoredPlugin p;p.id=juce::Uuid().toString();p.format="E-musician";p.identifier="native."+type;p.name=type=="eq8"?"EQ Eight":type=="delay"?"Stereo Delay":type=="reverb"?"Reverb":type=="auto_filter"?"Auto Filter":"Compressor";p.manufacturer="E-musician";p.version="1";p.role="effect";
        Settings initial;initial.eq=type=="eq8";initial.delay=type=="delay";initial.reverb=type=="reverb";initial.autoFilter=type=="auto_filter";setState(p,encode(initial));if(result)*result=make({{"device_id",p.id}});plugins->push_back(std::move(p));return juce::Result::ok();
    }
    if(command!="set_native_effect"||!args["device_id"].isString()||!args["state"].isObject())return juce::Result::fail("Device ID and state required.");
    for(auto& p:*plugins)if(p.id==args["device_id"].toString()){
        auto candidate=p;setState(candidate,args["state"]);Settings parsed;if(auto r=decode(candidate,parsed);r.failed())return r;
        setState(p,encode(parsed));return juce::Result::ok();}
    return juce::Result::fail("Native effect not found.");
}
juce::Result describe(const storage::StoredProject& p,const juce::String& trackId,const juce::String& deviceId,juce::var& result){
    const std::vector<storage::StoredPlugin>* list=nullptr;if(trackId=="master")list=&p.masterPlugins;else for(const auto& t:p.tracks)if(t.id==trackId){list=&t.plugins;break;}
    if(!list)return juce::Result::fail("Track not found.");for(const auto& plugin:*list)if(plugin.id==deviceId){Settings s;if(auto r=decode(plugin,s);r.failed())return r;result=make({{"device_id",plugin.id},{"state",encode(s)}});return juce::Result::ok();}return juce::Result::fail("Native effect not found.");
}
Effect::Effect(tracktion::PluginCreationInfo i):Plugin(i){if(state["emEffectType"].toString()=="native.delay")delay=std::make_unique<effects::StereoDelay>();else if(state["emEffectType"].toString()=="native.reverb")reverb=std::make_unique<effects::StereoReverb>();publish();}
Effect::~Effect(){notifyListenersOfDeletion();}
void Effect::prepareDelay(){jassert(juce::MessageManager::getInstance()->isThisTheMessageThread());if(!delay)delay=std::make_unique<effects::StereoDelay>();}
void Effect::prepareReverb(){jassert(juce::MessageManager::getInstance()->isThisTheMessageThread());if(!reverb)reverb=std::make_unique<effects::StereoReverb>();}
void Effect::initialise(const tracktion::PluginInitialisationInfo& i){rate.store(i.sampleRate);resetPending.store(true);}
double Effect::getTailLength() const {
    if(isReverb.load(std::memory_order_relaxed))return double(reverbDecay.load(std::memory_order_relaxed)) + .1;
    if(!isDelay.load(std::memory_order_relaxed))return 0;
    const auto repeat=juce::jlimit(0.0,.95,double(feedback.load(std::memory_order_relaxed)));
    const auto count=repeat>0?std::ceil(std::log(1.0e-4)/std::log(repeat)):1.0;
    return double(delayMs.load(std::memory_order_relaxed))*.001*std::max(1.0,count);
}
void Effect::valueTreePropertyChanged(juce::ValueTree& tree,const juce::Identifier& id){Plugin::valueTreePropertyChanged(tree,id);if(tree==state&&(id==juce::Identifier("emEffectData")||id==juce::Identifier("emEffectType")))publish();}
void Effect::publish(){
    storage::StoredPlugin p;p.format="E-musician";p.role="effect";p.identifier=state["emEffectType"].toString();
    const auto data=state["emEffectData"];if(const auto* bytes=data.getBinaryData())p.state=*bytes;Settings s;if(decode(p,s).failed())return;
    previewSettings(s);
}
void Effect::previewSettings(const Settings& s) noexcept {
    settingsVersion.fetch_add(1);
    for(std::size_t i=0;i<effects::eqBandCount;++i){const auto& b=s.equalizer.bands[i];enabled[i].store(b.enabled);freq[i].store(b.frequency);gain[i].store(b.gainDb);q[i].store(b.q);shape[i].store(b.shape);}
    threshold.store(s.compressor.thresholdDb);ratio.store(s.compressor.ratio);attack.store(s.compressor.attackMs);release.store(s.compressor.releaseMs);makeup.store(s.compressor.makeupDb);dryWet.store(s.compressor.dryWet);
    delayMs.store(s.delaySettings.delayMs);feedback.store(s.delaySettings.feedback);delayMix.store(s.delaySettings.dryWet);
    reverbDecay.store(s.reverbSettings.decaySeconds);reverbDamping.store(s.reverbSettings.damping);reverbMix.store(s.reverbSettings.dryWet);
    filterFreq.store(s.filterSettings.frequencyHz);filterQ.store(s.filterSettings.resonanceQ);filterLfoHz.store(s.filterSettings.lfoHz);filterLfoDepth.store(s.filterSettings.lfoDepth);filterMix.store(s.filterSettings.dryWet);
    filterHigh.store(s.filterSettings.mode==autofilter::Mode::highPass);filterLfoOn.store(s.filterSettings.lfoEnabled);
    isEq.store(s.eq);isDelay.store(s.delay);isReverb.store(s.reverb);isFilter.store(s.autoFilter);settingsVersion.fetch_add(1);
}
bool Effect::readSpectrum(std::array<float,2048>& samples,std::uint64_t& sequence) const noexcept {
    static_assert(std::atomic<float>::is_always_lock_free);
    spectrumLease.store(48,std::memory_order_relaxed);
    const auto before=spectrumVersion.load(std::memory_order_acquire);if(!before||(before&1))return false;
    for(std::size_t i=0;i<samples.size();++i)samples[i]=spectrumFrame[i].load(std::memory_order_relaxed);
    if(spectrumVersion.load(std::memory_order_acquire)!=before)return false;
    sequence=before;return true;
}
void Effect::applyToBuffer(const tracktion::PluginRenderContext& c){
    if(!c.destBuffer||c.destBuffer->getNumChannels()<1||c.bufferNumSamples<=0)return;
    if(rendering.test_and_set(std::memory_order_acquire))return;
    if(resetPending.exchange(false)){equalizer.reset();compressor.reset();autoFilter.reset();if(delay)delay->reset();if(reverb)reverb->reset();}
    auto* l=c.destBuffer->getWritePointer(0,c.bufferStartSample);auto* r=c.destBuffer->getNumChannels()>1?c.destBuffer->getWritePointer(1,c.bufferStartSample):nullptr;
    const auto before=settingsVersion.load();
    if(before && !(before&1)) {
        Settings candidate;candidate.eq=isEq.load();candidate.delay=isDelay.load();candidate.reverb=isReverb.load();candidate.autoFilter=isFilter.load();
        for(std::size_t i=0;i<effects::eqBandCount;++i)candidate.equalizer.bands[i]={enabled[i].load(),freq[i].load(),gain[i].load(),q[i].load(),shape[i].load()};
        candidate.compressor={threshold.load(),ratio.load(),attack.load(),release.load(),makeup.load(),dryWet.load()};
        candidate.delaySettings={delayMs.load(),feedback.load(),delayMix.load()};
        candidate.reverbSettings={reverbDecay.load(),reverbDamping.load(),reverbMix.load()};
        candidate.filterSettings={filterHigh.load()?autofilter::Mode::highPass:autofilter::Mode::lowPass,filterFreq.load(),filterQ.load(),filterLfoOn.load(),filterLfoHz.load(),filterLfoDepth.load(),filterMix.load()};
        if(settingsVersion.load()==before)currentSettings=candidate;
    }
    if(currentSettings.autoFilter)autoFilter.process(l,r,c.bufferNumSamples,rate.load(),currentSettings.filterSettings);
    else if(currentSettings.reverb){if(reverb)reverb->process(l,r,c.bufferNumSamples,rate.load(),currentSettings.reverbSettings);}
    else if(currentSettings.delay){if(delay)delay->process(l,r,c.bufferNumSamples,rate.load(),currentSettings.delaySettings);}
    else if(currentSettings.eq)equalizer.process(l,r,c.bufferNumSamples,rate.load(),currentSettings.equalizer);
    else {compressor.process(l,r,c.bufferNumSamples,rate.load(),currentSettings.compressor);
        reductionDb.store(compressor.lastReductionDb(),std::memory_order_relaxed);meterBlocks.fetch_add(1,std::memory_order_release);}
    // At most one published 2048-sample frame per block; no FFT, allocation,
    // lock or callback to the UI. Stops after the display polling lease expires.
    const auto lease=spectrumLease.load(std::memory_order_relaxed);
    if(lease>0){
        spectrumLease.fetch_sub(1,std::memory_order_relaxed);
        for(int i=0;i<c.bufferNumSamples;++i){const float value=r?(l[i]+r[i])*.5f:l[i];spectrumPending[spectrumPosition++]=std::isfinite(value)?value:0;
            if(spectrumPosition==spectrumPending.size()){
                spectrumVersion.fetch_add(1,std::memory_order_acq_rel);
                for(std::size_t j=0;j<spectrumFrame.size();++j)spectrumFrame[j].store(spectrumPending[j],std::memory_order_relaxed);
                spectrumVersion.fetch_add(1,std::memory_order_release);spectrumPosition=0;break;
            }
        }
    }else spectrumPosition=0;
    rendering.clear(std::memory_order_release);
}
}
