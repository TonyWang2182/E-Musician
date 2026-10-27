#include "EngineSession.h"
#include "ProjectStorage.h"
#include "AudioSource.h"
#include "PluginHost.h"
#include "EngineSessionProduction.h"
#include "core/commands/RevisionGuard.hpp"
#include "core/time/Time.hpp"
#include <tracktion_engine/tracktion_engine.h>
#include <juce_cryptography/juce_cryptography.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <functional>
#include <limits>
#include <map>
#include <mutex>
#include <optional>
#include <set>
#include <stdexcept>
#include <thread>
#if JUCE_WINDOWS
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <psapi.h>
#include <bcrypt.h>
#endif

namespace emusician {
namespace te = tracktion;
namespace {
// Offline renders and hosted-input tests must never replace the user's device
// configuration when their Engine flushes settings during destruction.
struct TransientPropertyStorage final : te::PropertyStorage {
    TransientPropertyStorage()
        : te::PropertyStorage("E-musician"),
          directory(juce::File::getSpecialLocation(juce::File::tempDirectory)
              .getChildFile("E-musician-offline").getChildFile(juce::Uuid().toString())),
          properties(juce::File(), options()) {}
    static juce::PropertiesFile::Options options() {
        juce::PropertiesFile::Options value;
        value.doNotSave = true;
        value.millisecondsBeforeSaving = -1;
        return value;
    }
    juce::PropertiesFile& getPropertiesFile() override { return properties; }
    juce::File getAppPrefsFolder() override { return directory; }
    juce::File getAppCacheFolder() override { return directory; }
    const juce::File directory;
    juce::PropertiesFile properties;
};
std::unique_ptr<te::PropertyStorage> sessionProperties(bool interactive) {
    if (interactive) return std::make_unique<te::PropertyStorage>("E-musician");
    return std::make_unique<TransientPropertyStorage>();
}
struct OutputOnlyBehaviour : te::EngineBehaviour {
    explicit OutputOnlyBehaviour(bool enable=true):enabled(enable){}
    bool enabled;
    bool shouldOpenAudioInputByDefault() override { return false; }
    bool autoInitialiseDeviceManager() override { return enabled; }
    te::EditLimits getEditLimits() override {
        te::EditLimits limits;limits.maxNumTracks=int(storage::maximumTracks)+8;
        limits.maxClipsInTrack=int(storage::maximumClips);
        limits.maxPluginsOnTrack=limits.maxNumMasterPlugins=int(storage::maximumPlugins)+8;
        return limits;
    }
    bool shouldLoadPlugin(te::ExternalPlugin& plugin) override {
        return te::EngineBehaviour::shouldLoadPlugin(plugin)&&plugins::PluginHost::matchesCachedIdentity(plugin);
    }
    void doAdditionalInitialisation(te::ExternalPlugin& plugin) override {
        if(auto result=plugins::PluginHost::restoreCachedProgramIfNeeded(plugin);result.failed())throw std::runtime_error(result.getErrorMessage().toStdString());
    }
};
void requireControlThread() { jassert(juce::MessageManager::getInstance()->isThisTheMessageThread()); }
float stableGain(float v) { return juce::jlimit(-60.0f,6.0f,float(std::round(double(v)*1000.0)/1000.0)); }
juce::String uid() { return juce::Uuid().toString(); }
juce::var object(std::initializer_list<std::pair<juce::Identifier,juce::var>> fields)
{ auto* o=new juce::DynamicObject();for(const auto& [k,v]:fields)o->setProperty(k,v);return o; }
juce::String sessionSha256(const void* data,size_t size,bool* usedNative=nullptr)
{
    if(usedNative)*usedNative=false;
#if JUCE_WINDOWS && defined(BCRYPT_SHA256_ALG_HANDLE)
    // Windows 10's CNG implementation selects its platform implementation.
    // Preserve exactly the same SHA256 bytes as JUCE; this is not a new key
    // algorithm. Hashing remains on the control/worker side, never audio IO.
    if(size<=std::numeric_limits<ULONG>::max()){
        std::array<unsigned char,32> digest{};unsigned char empty=0;
        auto* input=size?const_cast<unsigned char*>(static_cast<const unsigned char*>(data)):&empty;
        if(BCryptHash(BCRYPT_SHA256_ALG_HANDLE,nullptr,0,input,ULONG(size),digest.data(),ULONG(digest.size()))>=0){
            if(usedNative)*usedNative=true;return juce::String::toHexString(digest.data(),int(digest.size()),0);
        }
    }
#endif
    return juce::SHA256(data,size).toHexString();
}
template<class Notes> juce::String noteContentKey(const Notes& notes)
{
    juce::MemoryOutputStream o;
    for(const auto& n:notes){o.writeString(n.id);o.writeInt(n.pitch);o.writeInt64(juce::int64(std::llround(n.startBeats*1.0e9)));o.writeInt64(juce::int64(std::llround(n.lengthBeats*1.0e9)));o.writeInt(n.velocity);o.writeInt(n.channel);}
    return sessionSha256(o.getData(),o.getDataSize());
}
juce::String contentKey(const storage::StoredProject& s,const std::function<juce::String(const juce::String&)>& noteKey={})
{
    // Computed at edit/save boundaries, never during the transport poll.
    juce::MemoryOutputStream o;
    auto time=[&](double v){o.writeInt64(juce::int64(std::llround(v*1.0e9)));};
    auto plugin=[&](const auto& p){o.writeString(p.id);o.writeString(p.format);o.writeString(p.identifier);o.writeInt(p.uniqueId);o.writeBool(p.enabled);o.writeString(p.role);};
    auto lanes=[&](const auto& list){for(const auto& lane:list){o.writeString(lane.id);o.writeString(lane.target);o.writeString(lane.pluginId);o.writeString(lane.parameterId);o.writeBool(lane.enabled);for(const auto& point:lane.points){o.writeString(point.id);time(point.timeSeconds);o.writeFloat(point.value);o.writeFloat(point.curve);}}};
    o.writeString(s.projectId);o.writeInt(int(std::round(s.masterGainDb*1000)));o.writeBool(s.looping);
    time(s.bpm);o.writeInt(s.numerator);o.writeInt(s.denominator);time(s.loopStart);time(s.loopEnd);
    for(const auto& p:s.masterPlugins)plugin(p);
    lanes(s.masterAutomation);
    for(const auto& t:s.tracks){
        o.writeString(t.id);o.writeString(t.name);o.writeString(t.kind);o.writeInt(int(std::round(t.gainDb*1000)));o.writeInt(int(std::round(t.pan*100000)));
        o.writeBool(t.muted);o.writeBool(t.solo);for(const auto& p:t.plugins)plugin(p);
        o.writeString(t.inputDeviceId);o.writeString(t.outputTargetId);lanes(t.automation);
        for(const auto& send:t.sends){o.writeString(send.id);o.writeString(send.targetTrackId);o.writeFloat(send.gainDb);o.writeBool(send.preFader);o.writeBool(send.enabled);}
        for(const auto& c:t.clips){o.writeString(c.id);o.writeString(c.kind);o.writeString(c.assetId);time(c.timelineStart);time(c.sourceOffset);time(c.duration);time(c.fadeIn);time(c.fadeOut);
            if(c.kind=="midi"){time(c.startBeats);time(c.lengthBeats);o.writeString(noteKey?noteKey(c.id):noteContentKey(c.notes));for(const auto& event:c.controllers){o.writeString(event.id);time(event.beats);o.writeInt(event.type);o.writeInt(event.value);o.writeInt(event.metadata);}}
        }
    }return sessionSha256(o.getData(),o.getDataSize());
}
struct AudioInfo{double duration=0,rate=0;int channels=0;juce::String format;juce::File playbackFile;};
juce::Result inspectAudio(const juce::File& f,AudioInfo& info){audio::PreparedSource p;auto r=audio::prepareSource(f,p);if(r.wasOk())info={p.duration,p.sampleRate,p.channels,p.format,p.playbackFile};return r;}
const juce::Identifier emId("emId"),emKind("emKind"),emAsset("emAsset"),emSource("emSource"),emChannel("emChannel");
juce::ValueTree slotTree(const storage::StoredPlugin& p)
{
    juce::ValueTree v("EM_PLUGIN");
    for(const auto& [k,x]:std::initializer_list<std::pair<juce::Identifier,juce::var>>{{"id",p.id},{"format",p.format},{"identifier",p.identifier},{"uniqueId",p.uniqueId},{"deprecatedUniqueId",p.deprecatedUniqueId},{"name",p.name},{"manufacturer",p.manufacturer},{"version",p.version},{"enabled",p.enabled},{"role",p.role}})v.setProperty(k,x,nullptr);
    if(p.state.getSize())v.setProperty("data",juce::var(p.state),nullptr);return v;
}
storage::StoredPlugin readSlot(const juce::ValueTree& v,bool includeState=true)
{
    storage::StoredPlugin p;p.id=v["id"].toString();p.format=v["format"].toString();p.identifier=v["identifier"].toString();p.uniqueId=int(v["uniqueId"]);p.deprecatedUniqueId=int(v["deprecatedUniqueId"]);
    p.name=v["name"].toString();p.manufacturer=v["manufacturer"].toString();p.version=v["version"].toString();p.enabled=bool(v["enabled"]);p.role=v["role"].toString();if(includeState)if(auto* b=v["data"].getBinaryData())p.state=*b;return p;
}
}

struct EngineSession::Impl : private juce::Timer,private juce::ValueTree::Listener {
    struct ClipBinding{juce::String id,assetId;juce::File source;AudioInfo info;te::Clip::Ptr clip;};
    struct Binding{juce::String id;te::AudioTrack* track=nullptr;std::vector<ClipBinding> clips;};
    struct Job{
        juce::String id=uid(),kind,status="queued",error,projectId;std::uint64_t revision=0;double progress=-1;
        juce::String phase="queued",detail;
        double captureMs=0,maxPluginCaptureMs=0;
        juce::int64 bytesWritten=0,bytesReused=0;
        int pluginsCaptured=0;
        std::atomic<bool> cancel{false},done{false};std::mutex mutex;std::thread worker;std::function<void()> commit;
        std::function<void()> preparation;
        std::condition_variable preparationReady;
        std::atomic<bool> prepared{false};
        ~Job(){cancel=true;if(worker.joinable())worker.join();}
    };
    te::Engine engine;
    plugins::PluginHost pluginHost{engine};commands::RevisionGuard guard{uid().toStdString()};
    production::RecordingController recording{engine};
    std::unique_ptr<te::Edit> edit=te::createEmptyEdit(engine,{});
    std::unique_ptr<te::Edit::UndoTransactionInhibitor> transactionControl;
    std::vector<Binding> bindings;std::map<juce::String,AudioInfo> prepared;
    // Derived, immutable views only. The Edit remains the sole writable music
    // state; note-tree notifications invalidate these views, including on Undo.
    struct NoteView {
        juce::ValueTree sequence;int channel=1;
        std::shared_ptr<const std::vector<NoteSnapshot>> notes;juce::String key;
        // Same exact byte encoding as noteContentKey. Offsets point after each
        // stable ID to its fixed-size values, enabling sparse copy-on-write.
        std::shared_ptr<const juce::MemoryBlock> encoded;
        std::shared_ptr<const std::vector<size_t>> valueOffsets;
    };
    mutable std::map<juce::String,NoteView> noteViews;
    juce::String selected,selectedClip,status="Import audio or create a MIDI track.",savedKey,currentKey;juce::File projectFile;
    double duration=0;bool gesture=false,shuttingDown=false,pluginDirty=false;
    std::uint64_t cachedRevision=std::numeric_limits<std::uint64_t>::max(),eventSequence=0;Snapshot cached;
    std::vector<std::shared_ptr<Job>> jobs;juce::Array<juce::var> events;
    std::shared_ptr<bool> alive=std::make_shared<bool>(true);
    std::set<juce::String> watchedPlugins;
    std::vector<PluginDescriptorSnapshot> catalogCache;
    double catalogReadAt=-100000.0;
    bool catalogWasScanning=false;
    struct Reply{juce::String digest;juce::var value;};std::map<juce::String,Reply> replies;

    explicit Impl(bool enable=true):engine(sessionProperties(enable),plugins::createUIBehaviour(),std::make_unique<OutputOnlyBehaviour>(enable)){
        if(!edit)throw std::runtime_error("Unable to create audio session");
        edit->tempoSequence.getTempo(0)->set(te::BeatPosition::fromBeats(0),120,0,false);edit->getMasterVolumePlugin()->setVolumeDb(-6);
        transactionControl=std::make_unique<te::Edit::UndoTransactionInhibitor>(*edit);
        edit->state.addListener(this);
        recording.attach(*edit,recordingDirectory());
        edit->getUndoManager().setMaxNumberOfStoredUnits(1000000,64);edit->getUndoManager().clearUndoHistory();savedKey=currentKey=calculateCurrentKey();startTimerHz(30);
    }
    ~Impl() override{
        *alive=false;shuttingDown=true;stopTimer();for(auto& j:jobs)j->cancel=true;
        for(auto& j:jobs)if(j->worker.joinable())j->worker.join();
        for(auto& j:jobs)j->commit={};jobs.clear();pluginHost.cancelScan();plugins::PluginHost::closeAllEditors(*edit);
        edit->getTransport().stop(false,false);recording.detach();pluginHost.detachEdit(*edit);edit->state.removeListener(this);noteViews.clear();transactionControl.reset();bindings.clear();edit.reset();
    }
    juce::File recordingDirectory()const{return juce::File::getSpecialLocation(juce::File::userApplicationDataDirectory).getChildFile("E-musician/recordings").getChildFile(guard.projectId());}
    bool recordingBusy()const{return edit->getTransport().isRecording()||edit->getTransport().isRecordingStopping()||bool(recording.state()["finalizing"]);}
    void finishRecording(){
        if(!recording.poll())return;
        juce::String preparationError;
        for(auto* track:te::getAudioTracks(*edit))for(auto* clip:track->getClips())if(auto* wave=dynamic_cast<te::WaveAudioClip*>(clip)){
            const auto source=wave->state[emSource].toString();if(source.isEmpty()||prepared.contains(source))continue;
            AudioInfo info;if(auto r=inspectAudio(juce::File(source),info);r.wasOk())prepared[source]=info;else preparationError=r.getErrorMessage();
        }
        rebuild(*edit,bindings);refreshRange();choose(selected);recordEdit();status=preparationError.isEmpty()?"Recording added. Undo removes the complete take.":"Recorded file needs attention: "+preparationError;
        publish("recording_completed",recording.state());
    }
    juce::ValueTree metadata(te::Edit& t)const{return t.state.getOrCreateChildWithName("EM_PROJECT",nullptr);}
    te::Plugin* livePlugin(te::Edit& t,const juce::String& id)const{
        for(auto* p:t.getMasterPluginList())if(p->state[emId].toString()==id)return p;
        for(auto* track:te::getAudioTracks(t))for(auto* p:track->pluginList)if(p->state[emId].toString()==id)return p;return nullptr;
    }
    te::ExternalPlugin* loadedPlugin(te::Edit& t,const juce::String& id)const{
        auto* plugin=dynamic_cast<te::ExternalPlugin*>(livePlugin(t,id));
        return plugin&&plugin->getAudioPluginInstance()?plugin:nullptr;
    }
    std::vector<storage::StoredPlugin> captureSlots(juce::ValueTree owner)const{
        std::vector<storage::StoredPlugin> out;for(auto v:owner.getChildWithName("EM_PLUGINS")){auto p=readSlot(v,false);if(auto* live=loadedPlugin(*edit,p.id))plugins::PluginHost::capture(*live,p,false);out.push_back(std::move(p));}return out;
    }
    const NoteView& noteView(const juce::String& id,te::MidiClip& midi)const{
        auto& sequence=midi.getSequence();const int channel=midi.getMidiChannel().getChannelNumber();
        if(auto i=noteViews.find(id);i!=noteViews.end()&&i->second.sequence==sequence.state&&i->second.channel==channel)return i->second;
        auto notes=std::make_shared<std::vector<NoteSnapshot>>();notes->reserve(size_t(sequence.getNumNotes()));
        auto encoded=std::make_shared<juce::MemoryBlock>();auto offsets=std::make_shared<std::vector<size_t>>();offsets->reserve(size_t(sequence.getNumNotes()));
        {
            juce::MemoryOutputStream out(*encoded,false);out.preallocate(size_t(sequence.getNumNotes())*80);
            for(auto* n:sequence.getNotes()){
                notes->push_back({n->state[emId].toString(),n->getNoteNumber(),n->getStartBeat().inBeats(),n->getLengthBeats().inBeats(),n->getVelocity(),channel});
                const auto& value=notes->back();out.writeString(value.id);offsets->push_back(out.getDataSize());writeNoteValues(out,value);
            }
        }
        NoteView view{sequence.state,channel,notes,sessionSha256(encoded->getData(),encoded->getSize()),encoded,offsets};
        return noteViews.insert_or_assign(id,std::move(view)).first->second;
    }
    template<class Note> static void writeNoteValues(juce::OutputStream& out,const Note& n){
        out.writeInt(n.pitch);out.writeInt64(juce::int64(std::llround(n.startBeats*1.0e9)));out.writeInt64(juce::int64(std::llround(n.lengthBeats*1.0e9)));out.writeInt(n.velocity);out.writeInt(n.channel);
    }
    void invalidateNotes(juce::ValueTree tree){
        for(auto v=tree;v.isValid();v=v.getParent())if(v.hasType(te::IDs::MIDICLIP)){
            noteViews.erase(v[emId].toString());cachedRevision=std::numeric_limits<std::uint64_t>::max();return;
        }
    }
    void valueTreePropertyChanged(juce::ValueTree& tree,const juce::Identifier&)override{
        if(tree.hasType(te::IDs::NOTE)||tree.hasType(te::IDs::SEQUENCE))invalidateNotes(tree);
    }
    void valueTreeChildAdded(juce::ValueTree& parent,juce::ValueTree& child)override{
        if(child.hasType(te::IDs::NOTE)||child.hasType(te::IDs::SEQUENCE))invalidateNotes(parent);
    }
    void valueTreeChildRemoved(juce::ValueTree& parent,juce::ValueTree& child,int)override{
        if(child.hasType(te::IDs::NOTE)||child.hasType(te::IDs::SEQUENCE))invalidateNotes(parent);
    }
    void valueTreeChildOrderChanged(juce::ValueTree& parent,int,int)override{
        if(parent.hasType(te::IDs::SEQUENCE))invalidateNotes(parent);
    }
    juce::String calculateCurrentKey()const{
        return contentKey(capture(false),[&](const juce::String& id){
            for(const auto& b:bindings)for(const auto& c:b.clips)if(c.id==id)if(auto* midi=dynamic_cast<te::MidiClip*>(c.clip.get()))return noteView(id,*midi).key;
            return juce::String();
        });
    }
    storage::StoredProject capture(bool includeNotes=true,bool includeControllers=true)const{
        storage::StoredProject s;s.projectId=guard.projectId();s.revision=guard.revision();s.masterGainDb=stableGain(edit->getMasterVolumePlugin()->getVolumeDb());s.looping=edit->getTransport().looping.get();
        s.bpm=edit->tempoSequence.getTempo(0)->getBpm();auto* sig=edit->tempoSequence.getTimeSig(0);s.numerator=sig->numerator;s.denominator=sig->denominator;
        auto m=metadata(*edit);s.loopStart=double(m.getProperty("loopStart",0.0));s.loopEnd=double(m.getProperty("loopEnd",0.0));s.masterPlugins=captureSlots(m);
        for(const auto& b:bindings){storage::StoredTrack t;t.id=b.id;t.name=b.track->getName();t.kind=b.track->state.getProperty(emKind,"audio").toString();t.gainDb=stableGain(b.track->getVolumePlugin()->getVolumeDb());t.pan=b.track->getVolumePlugin()->getPan();t.muted=b.track->isMuted(false);t.solo=b.track->isSolo(false);t.plugins=captureSlots(b.track->state);
            for(const auto& c:b.clips){storage::StoredClip a;a.id=c.id;a.assetId=c.assetId;auto pos=c.clip->getPosition();a.timelineStart=pos.time.getStart().inSeconds();a.sourceOffset=pos.offset.inSeconds();a.duration=pos.time.getLength().inSeconds();
                if(auto* midi=dynamic_cast<te::MidiClip*>(c.clip.get())){a.kind="midi";a.startBeats=time::secondsToBeats(a.timelineStart,s.bpm);a.lengthBeats=time::secondsToBeats(a.duration,s.bpm);
                    if(includeNotes){const auto& notes=*noteView(c.id,*midi).notes;a.notes.reserve(notes.size());for(const auto& n:notes)a.notes.push_back({n.id,n.pitch,n.startBeats,n.lengthBeats,n.velocity,n.channel});}
                }else if(auto* audio=dynamic_cast<te::WaveAudioClip*>(c.clip.get())){a.fadeIn=audio->getFadeIn().inSeconds();a.fadeOut=audio->getFadeOut().inSeconds();if(std::none_of(s.assets.begin(),s.assets.end(),[&](const auto& x){return x.id==c.assetId;}))s.assets.push_back({c.assetId,c.source});}
                t.clips.push_back(std::move(a));
            }s.tracks.push_back(std::move(t));
        }production::captureGraph(*edit,s,includeControllers);return s;
    }
    juce::Result capturePluginStates(storage::StoredProject& s){
        auto flush=[&](auto& list,juce::ValueTree owner){for(auto& p:list){
            auto slot=owner.getChildWithName("EM_PLUGINS").getChildWithProperty("id",p.id);
            if(auto* live=loadedPlugin(*edit,p.id)){auto r=plugins::PluginHost::capture(*live,p,true);if(r.failed())return r;
                slot.setProperty("data",juce::var(p.state),nullptr);
            }else if(slot.isValid())p.state=readSlot(slot).state;
        }return juce::Result::ok();};
        if(auto r=flush(s.masterPlugins,metadata(*edit));r.failed())return r;
        for(auto& t:s.tracks)if(auto* b=find(t.id))if(auto r=flush(t.plugins,b->track->state);r.failed())return r;
        return juce::Result::ok();
    }
    juce::Result fail(const juce::String& m){status=m;return juce::Result::fail(m);}
    juce::Result preflight(std::uint64_t expected){if(expected!=guard.revision())return fail("The project changed. Refresh and try again.");if(guard.revision()>=std::uint64_t(std::numeric_limits<juce::int64>::max())-1)return fail("Project revision limit reached.");return juce::Result::ok();}
    void publish(const juce::String& type,juce::var data={}){events.add(object({{"sequence",juce::int64(++eventSequence)},{"type",type},{"project_id",juce::String(guard.projectId())},{"revision",juce::int64(guard.revision())},{"data",data}}));if(events.size()>1024)events.removeRange(0,events.size()-1024);}
    void advanceRevision(){guard=commands::RevisionGuard(guard.projectId(),guard.revision()+1);}
    void recordEdit(){advanceRevision();currentKey=calculateCurrentKey();cachedRevision=std::numeric_limits<std::uint64_t>::max();publish("project_changed");if(!gesture)edit->getUndoManager().beginNewTransaction();}
    Binding* find(const juce::String& id){auto i=std::find_if(bindings.begin(),bindings.end(),[&](const auto& t){return t.id==id;});return i==bindings.end()?nullptr:&*i;}
    ClipBinding* findClip(const juce::String& id,Binding** parent=nullptr){for(auto& t:bindings)for(auto& c:t.clips)if(c.id==id){if(parent)*parent=&t;return &c;}return nullptr;}
    void choose(const juce::String& tid,const juce::String& cid={}){auto* t=find(tid);if(!t&&!bindings.empty())t=&bindings.front();selected=t?t->id:juce::String();selectedClip={};if(t&&!t->clips.empty()){auto i=std::find_if(t->clips.begin(),t->clips.end(),[&](const auto& c){return c.id==cid;});selectedClip=i==t->clips.end()?t->clips.front().id:i->id;}}
    void rebuild(te::Edit& target,std::vector<Binding>& out){
        out.clear();for(auto* t:te::getAudioTracks(target)){auto id=t->state[emId].toString();if(id.isEmpty())continue;Binding b{id,t,{}};
            for(auto* clip:t->getClips()){auto cid=clip->state[emId].toString();if(cid.isEmpty())continue;const auto source=clip->state[emSource].toString();AudioInfo info;if(auto i=prepared.find(source);i!=prepared.end())info=i->second;b.clips.push_back({cid,clip->state[emAsset].toString(),source.isEmpty()?juce::File():juce::File(source),info,clip});}out.push_back(std::move(b));}
        if(&target==edit.get())std::erase_if(noteViews,[&](const auto& entry){for(const auto& b:out)for(const auto& c:b.clips)if(c.id==entry.first)return false;return true;});
    }
    void refreshRange(){
        duration=0;for(const auto& t:bindings)for(const auto& c:t.clips)duration=juce::jmax(duration,c.clip->getPosition().time.getEnd().inSeconds());
        auto m=metadata(*edit);double a=double(m.getProperty("loopStart",0.0)),b=double(m.getProperty("loopEnd",0.0));if(b<=a){a=0;b=duration;}
        auto& tr=edit->getTransport();tr.setLoopRange({te::TimePosition::fromSeconds(a),te::TimePosition::fromSeconds(b)});if(b-a<0.010)tr.looping=false;if(tr.getPosition().inSeconds()>juce::jmax(duration,b))tr.setPosition(te::TimePosition::fromSeconds(duration));
    }
    void remember(const juce::String& name){if(!gesture)edit->getUndoManager().beginNewTransaction(name);}
    void finishGesture(){gesture=false;edit->getUndoManager().beginNewTransaction();}
    void refreshPluginWatches(){
        std::set<juce::String> present;
        auto visit=[&](te::PluginList& list){for(auto* p:list){auto id=p->state[emId].toString();if(id.isNotEmpty()){present.insert(id);pluginHost.watchPlugin(p,id);}}};
        visit(edit->getMasterPluginList());for(auto* t:te::getAudioTracks(*edit))visit(t->pluginList);
        for(const auto& id:watchedPlugins)if(!present.contains(id))pluginHost.unwatchPlugin(id);watchedPlugins=std::move(present);
    }
    juce::Result prepare(const storage::StoredProject& s){for(const auto& a:s.assets)if(!prepared.contains(a.source.getFullPathName())){AudioInfo info;if(auto r=inspectAudio(a.source,info);r.failed())return fail(r.getErrorMessage());prepared[a.source.getFullPathName()]=info;}return juce::Result::ok();}
    juce::Result applyTo(te::Edit&,storage::StoredProject,std::vector<Binding>&,bool loading);
    juce::Result build(const storage::StoredProject& s,std::unique_ptr<te::Edit>& candidate,std::vector<Binding>& next){
        if(s.tracks.size()>storage::maximumTracks||s.assets.size()>storage::maximumAssets)return fail("Project object limit exceeded.");size_t n=0;for(const auto& t:s.tracks)n+=t.clips.size();if(n>storage::maximumClips)return fail("Clip limit exceeded.");
        if(auto r=prepare(s);r.failed())return r;candidate=te::createEmptyEdit(engine,{});if(!candidate)return fail("Could not create project.");auto r=applyTo(*candidate,s,next,true);if(r.wasOk())candidate->getUndoManager().clearUndoHistory();return r;
    }
    void adopt(std::unique_ptr<te::Edit> next,std::vector<Binding> bs,const juce::String& tid,const juce::String& cid={}){
        plugins::PluginHost::closeAllEditors(*edit);edit->getTransport().stop(false,false);recording.detach();pluginHost.detachEdit(*edit);edit->state.removeListener(this);noteViews.clear();transactionControl.reset();bindings.clear();edit=std::move(next);bindings=std::move(bs);transactionControl=std::make_unique<te::Edit::UndoTransactionInhibitor>(*edit);edit->state.addListener(this);recording.attach(*edit,recordingDirectory());
        edit->getUndoManager().setMaxNumberOfStoredUnits(1000000,64);refreshRange();choose(tid,cid);gesture=false;watchedPlugins.clear();refreshPluginWatches();currentKey=calculateCurrentKey();cachedRevision=std::numeric_limits<std::uint64_t>::max();
    }
    void timerCallback() override;
    void reapFinishedJobs(bool applyCommits);
    std::shared_ptr<Job> startJob(const juce::String&,std::function<void(const std::shared_ptr<Job>&)>);
    juce::Result mutate(storage::StoredProject&,const juce::String&,const juce::var&,juce::String& selectedAfter);
    juce::Result perform(const juce::String&,const juce::var&);
    juce::Result performJob(const juce::String&,const juce::var&);
    juce::Result beginSave(const juce::File&);
    juce::Result setPluginParameter(const juce::var&);
    juce::var getPluginParameters(const juce::var&)const;
};

#include "EngineSessionAutomationRouting.inc"
#include "EngineSessionRecording.inc"
#include "EngineSessionParameters.inc"
#include "EngineSessionModel.inc"
#include "EngineSessionCommands.inc"
#include "EngineSessionJobs.inc"
#include "EngineSessionPublic.inc"
#include "../../tests/EngineSessionSmoke.inc"
#include "../../tests/EngineSessionProjectSmoke.inc"
#include "../../tests/EngineSessionClipSmoke.inc"
#include "../../tests/EngineSessionDawSmoke.inc"
#include "../../tests/EngineSessionProductionSmoke.inc"
#include "../../tests/EngineSessionPluginNotificationSmoke.inc"
}
