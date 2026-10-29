void EngineSession::setOfflineTestMode(bool enabled){requireControlThread();offlineTestMode=enabled;}
EngineSession::EngineSession(bool enable):impl(std::make_unique<Impl>(enable&&!offlineTestMode)){}
EngineSession::~EngineSession()=default;
bool EngineSession::isSupportedAudioFile(const juce::File& f){return f.hasFileExtension("wav;mp3");}

namespace {
juce::var jobSnapshotJson(const EngineSession::JobSnapshot& j)
{
    return object({{"id",j.id},{"kind",j.kind},{"status",j.status},{"progress",j.progress},{"error",j.error},
        {"phase",j.phase},{"detail",j.detail},{"capture_ms",j.captureMs},{"max_plugin_capture_ms",j.maxPluginCaptureMs},
        {"bytes_written",j.bytesWritten},{"bytes_reused",j.bytesReused},{"plugins_captured",j.pluginsCaptured}});
}
}

EngineSession::Snapshot EngineSession::snapshot()const
{
    requireControlThread();auto& p=*impl;
    if(p.cachedRevision!=p.guard.revision()){
        Snapshot s;auto state=p.capture(false,false);s.projectId=p.guard.projectId();s.revision=p.guard.revision();s.bpm=state.bpm;s.numerator=state.numerator;s.denominator=state.denominator;
        s.loopStart=state.loopStart;s.loopEnd=state.loopEnd;s.duration=p.duration;
        auto slots=[&](const auto& list){std::vector<PluginSlotSnapshot> out;for(const auto& x:list)out.push_back({x.id,x.name,x.format,x.enabled,p.loadedPlugin(*p.edit,x.id)==nullptr,x.role=="instrument"});return out;};
        s.masterPlugins=slots(state.masterPlugins);
        auto lanes=[](const auto& list){std::vector<AutomationLaneSnapshot> out;for(const auto& lane:list){auto points=std::make_shared<std::vector<AutomationPointSnapshot>>();points->reserve(lane.points.size());for(const auto& point:lane.points)points->push_back({point.id,point.timeSeconds,point.value,point.curve});out.push_back({lane.id,lane.target,lane.pluginId,lane.parameterId,lane.enabled,points});}return out;};
        s.masterAutomation=lanes(state.masterAutomation);
        for(const auto& t:state.tracks){
            TrackSnapshot track;track.id=t.id;track.name=t.name;track.kind=t.kind;track.pan=t.pan;track.gainDb=t.gainDb;track.muted=t.muted;track.solo=t.solo;track.plugins=slots(t.plugins);
            track.inputDeviceId=t.inputDeviceId;track.outputTargetId=t.outputTargetId;track.automation=lanes(t.automation);
            for(const auto& send:t.sends)track.sends.push_back({send.id,send.targetTrackId,send.gainDb,send.preFader,send.enabled});
            for(const auto& c:t.clips){
                ClipSnapshot clip;clip.id=c.id;clip.assetId=c.assetId;clip.kind=c.kind;clip.timelineStart=c.timelineStart;clip.sourceOffset=c.sourceOffset;clip.duration=c.duration;
                clip.startBeats=c.startBeats;clip.lengthBeats=c.lengthBeats;clip.fadeIn=c.fadeIn;clip.fadeOut=c.fadeOut;
                if(auto* binding=p.findClip(c.id)){clip.source=binding->source;clip.waveformSource=binding->info.playbackFile;clip.sourceDuration=binding->info.duration;clip.sampleRate=binding->info.rate;clip.channels=binding->info.channels;clip.format=binding->info.format;}
                if(c.kind=="midi"){
                    if(auto* binding=p.findClip(c.id))if(auto* midi=dynamic_cast<te::MidiClip*>(binding->clip.get())){clip.notes=p.noteView(c.id,*midi).notes;clip.controllerCount=midi->getSequence().getNumControllerEvents();}
                    clip.format="MIDI";
                }
                track.duration=juce::jmax(track.duration,c.timelineStart+c.duration);
                if(track.clips.empty()){track.source=clip.source;track.waveformSource=clip.waveformSource;track.format=clip.format;track.sampleRate=clip.sampleRate;track.channels=clip.channels;}
                track.clips.push_back(std::move(clip));
            }s.tracks.push_back(std::move(track));
        }p.cached=std::move(s);p.cachedRevision=p.guard.revision();
    }
    auto s=p.cached;
    const auto preferences=p.recording.preferences();
    s.metronomeEnabled=bool(preferences["metronome_enabled"]);s.metronomeGainDb=float(preferences["metronome_gain_db"]);
    s.metronomeRecordOnly=bool(preferences["metronome_record_only"]);s.countInEnabled=bool(preferences["count_in_enabled"]);s.countInBars=int(preferences["count_in_bars"]);
    s.status=p.status;s.selectedTrackId=p.selected;s.selectedClipId=p.selectedClip;s.projectFile=p.projectFile;
    s.recordingState=p.recording.state();s.recording=bool(s.recordingState["recording"]);s.recordingFinalizing=bool(s.recordingState["finalizing"]);s.recordingError=s.recordingState["error"].toString();s.countingIn=bool(s.recordingState["counting_in"]);s.countInBeatsRemaining=double(s.recordingState["count_in_beats_remaining"]);
    if(auto* list=s.recordingState["tracks"].getArray())for(const auto& item:*list)for(auto& track:s.tracks)if(track.id==item["track_id"].toString()){track.armed=bool(item["armed"]);track.monitorMode=item["monitor"].toString();}
    s.projectName=p.projectFile==juce::File()?"Untitled":p.projectFile.getFileNameWithoutExtension();s.dirty=p.currentKey!=p.savedKey||p.pluginDirty||p.pluginHost.hasPendingChanges();
    auto& um=p.edit->getUndoManager();s.canUndo=um.canUndo();s.canRedo=um.canRedo();s.undoDescription=um.getUndoDescription();s.redoDescription=um.getRedoDescription();
    auto& tr=p.edit->getTransport();s.position=juce::jmax(0.0,tr.getPosition().inSeconds());s.playing=tr.isPlaying();s.looping=tr.looping.get();s.gainDb=p.edit->getMasterVolumePlugin()->getVolumeDb();
    for(const auto& t:s.tracks)for(const auto& c:t.clips)if(c.id==p.selectedClip){s.source=c.source;s.waveformSource=c.waveformSource;s.sourceDuration=c.sourceDuration;s.sourceSampleRate=c.sampleRate;s.sourceFormat=c.format;s.channels=c.channels;}
    auto& dm=p.engine.getDeviceManager().deviceManager;s.cpuUsage=dm.getCpuUsage();s.xruns=dm.getXRunCount();
    if(auto* d=dm.getCurrentAudioDevice()){s.deviceAvailable=d->isOpen()&&!d->getActiveOutputChannels().isZero();s.deviceName=d->getName();s.sampleRate=d->getCurrentSampleRate();s.bufferSize=d->getCurrentBufferSizeSamples();}
    for(const auto& j:p.jobs){
        std::lock_guard lock(j->mutex);
        JobSnapshot job{j->id,j->kind,j->status,j->error,j->progress};
        job.phase=j->phase;job.detail=j->detail;job.captureMs=j->captureMs;job.maxPluginCaptureMs=j->maxPluginCaptureMs;
        job.bytesWritten=j->bytesWritten;job.bytesReused=j->bytesReused;job.pluginsCaptured=j->pluginsCaptured;
        s.jobs.push_back(std::move(job));
    }
    auto scan=p.pluginHost.scanSnapshot();s.pluginScanning=scan.running;
    if(scan.running||scan.completed>0||scan.cancelled)s.jobs.push_back({"plugin-scan","scan_plugins",scan.running?"running":scan.cancelled?"cancelled":"completed",scan.status,scan.total>0?double(scan.completed)/scan.total:-1});
    const auto now=juce::Time::getMillisecondCounterHiRes();
    if(p.catalogReadAt<0||(scan.running&&now-p.catalogReadAt>500)||p.catalogWasScanning!=scan.running){
        p.catalogCache.clear();for(const auto& c:p.pluginHost.catalog())if(c.available)p.catalogCache.push_back({c.id,c.description.name,c.description.manufacturerName,c.description.pluginFormatName,c.description.isInstrument});
        p.catalogReadAt=now;p.catalogWasScanning=scan.running;
    }s.pluginCatalog=p.catalogCache;
    p.updateTelemetry(s);
    return s;
}

juce::Result EngineSession::execute(const juce::String& command,const juce::var& args,std::uint64_t expected,juce::var* commandResult)
{
    requireControlThread();
    if(commandResult)*commandResult=juce::var();
    if(command=="stop_recording")return impl->recording.execute(command,args);
    if(command=="reset_meters"){impl->resetMeters();return juce::Result::ok();}
    if(impl->recordingBusy()&&command!="cancel_job")return impl->fail("Stop recording and wait for the take to finish before editing.");
    if(command!="cancel_job"&&command!="scan_plugins"&&command!="open_plugin")if(auto r=impl->preflight(expected);r.failed())return r;
    if(command=="start_recording"||command=="set_track_armed"||command=="set_input_monitor"||command=="configure_audio_device"||command=="set_recording_preferences"){
        if(!args.isObject())return impl->fail("Command arguments must be an object.");
        if(command=="set_track_armed"&&(!args["track_id"].isString()||!args["armed"].isBool()))return impl->fail("Arming requires a track_id and boolean armed.");
        if(command=="set_input_monitor"&&(!args["input_device_id"].isString()||!args["mode"].isString()))return impl->fail("Monitoring requires an input_device_id and mode.");
        if(command=="start_recording"){
            if(hasActiveJobs())return impl->fail("Wait for background tasks before recording.");
            impl->finishGesture();
        }
        auto result=impl->recording.execute(command,args);if(result.failed())return impl->fail(result.getErrorMessage());
        impl->status=command=="set_recording_preferences"?"Recording preferences updated.":command=="start_recording"?"Recording...":command=="configure_audio_device"?"Audio device ready.":"Recording input updated.";
        impl->publish("recording_state_changed",impl->recording.state());return result;
    }
    try{return impl->perform(command,args,commandResult);}catch(const std::exception& e){return impl->fail(e.what());}
}
juce::Result EngineSession::importFile(const juce::File& f,std::uint64_t r){return importFiles({f},r);}
juce::Result EngineSession::importFiles(const juce::Array<juce::File>& files,std::uint64_t revision)
{
    // Synchronous compatibility entry for controlled tests. Interactive import uses jobs.
    if(impl->recordingBusy())return impl->fail("Stop recording before importing audio.");
    requireControlThread();if(auto r=impl->preflight(revision);r.failed())return r;
    if(files.isEmpty())return impl->fail("Choose an audio file.");auto state=impl->capture();
    if(state.tracks.size()+size_t(files.size())>storage::maximumTracks)return impl->fail("Track limit exceeded.");
    for(const auto& file:files){AudioInfo info;if(auto r=inspectAudio(file,info);r.failed())return impl->fail(r.getErrorMessage());
        impl->prepared[file.getFullPathName()]=info;storage::StoredAsset asset{uid(),file};storage::StoredTrack track;track.id=uid();track.name=file.getFileNameWithoutExtension();
        track.clips.push_back({uid(),asset.id,0,0,info.duration});state.assets.push_back(asset);state.tracks.push_back(std::move(track));}
    if(auto r=storage::validate(state);r.failed())return impl->fail(r.getErrorMessage());
    impl->finishGesture();impl->remember("Import audio");
    if(auto r=impl->applyTo(*impl->edit,state,impl->bindings,false);r.failed())return r;
    impl->refreshRange();impl->choose(state.tracks.back().id);impl->recordEdit();impl->status="Audio imported.";return juce::Result::ok();
}
juce::Result EngineSession::newProject(std::uint64_t expected)
{
    if(impl->recordingBusy())return impl->fail("Stop recording before creating a project.");
    requireControlThread();if(auto r=impl->preflight(expected);r.failed())return r;
    storage::StoredProject state;state.projectId=uid();std::unique_ptr<te::Edit> next;std::vector<Impl::Binding> bs;
    if(auto r=impl->build(state,next,bs);r.failed())return r;auto rev=impl->guard.revision()+1;
    impl->guard=commands::RevisionGuard(state.projectId.toStdString(),rev);impl->adopt(std::move(next),std::move(bs),{});impl->projectFile={};
    impl->savedKey=impl->currentKey=contentKey(impl->capture());impl->pluginDirty=false;impl->publish("project_opened");impl->status="New project. 120 BPM.";return juce::Result::ok();
}
juce::Result EngineSession::saveProject(const juce::File& file,std::uint64_t expected)
{
    // Test/legacy compatibility only. GUI and Agent use the asynchronous save_project job.
    if(impl->recordingBusy())return impl->fail("Stop recording before saving a project.");
    requireControlThread();if(auto r=impl->preflight(expected);r.failed())return r;impl->finishGesture();auto state=impl->capture();
    if(auto r=impl->capturePluginStates(state);r.failed())return impl->fail(r.getErrorMessage());storage::StoredProject archived;
    if(auto r=storage::save(file,state,archived);r.failed())return impl->fail(r.getErrorMessage());
    impl->projectFile=file;impl->savedKey=contentKey(state);impl->pluginDirty=false;impl->status="Project saved.";return juce::Result::ok();
}
juce::Result EngineSession::openProject(const juce::File& file,std::uint64_t expected)
{
    if(impl->recordingBusy())return impl->fail("Stop recording before opening a project.");
    requireControlThread();if(auto r=impl->preflight(expected);r.failed())return r;storage::StoredProject state;
    if(auto r=storage::load(file,state);r.failed())return impl->fail(r.getErrorMessage());
    if(state.revision>=std::uint64_t(std::numeric_limits<juce::int64>::max())-1)return impl->fail("Project revision is too large.");
    std::unique_ptr<te::Edit> next;std::vector<Impl::Binding> bs;if(auto r=impl->build(state,next,bs);r.failed())return r;
    auto rev=juce::jmax(impl->guard.revision(),state.revision)+1;impl->guard=commands::RevisionGuard(state.projectId.toStdString(),rev);
    impl->adopt(std::move(next),std::move(bs),{});impl->projectFile=file;impl->savedKey=impl->currentKey=contentKey(impl->capture());impl->pluginDirty=false;
    impl->publish("project_opened");impl->status="Project opened.";return juce::Result::ok();
}
void EngineSession::selectTrack(const juce::String& id){requireControlThread();if(impl->find(id))impl->choose(id);}
void EngineSession::selectClip(const juce::String& id){requireControlThread();Impl::Binding* parent=nullptr;if(impl->findClip(id,&parent))impl->choose(parent->id,id);}
juce::Result EngineSession::moveClip(const juce::String& id,double start,std::uint64_t rev){return execute("move_clip",object({{"clip_id",id},{"start_seconds",start}}),rev);}
juce::Result EngineSession::setTrackGain(const juce::String& id,float db,std::uint64_t rev){return execute("set_track_gain",object({{"track_id",id},{"gain_db",std::isfinite(db)?stableGain(db):db}}),rev);}
juce::Result EngineSession::setTrackMuted(const juce::String& id,bool v,std::uint64_t rev){return execute("set_track_muted",object({{"track_id",id},{"muted",v}}),rev);}
juce::Result EngineSession::setTrackSolo(const juce::String& id,bool v,std::uint64_t rev){return execute("set_track_solo",object({{"track_id",id},{"solo",v}}),rev);}
juce::Result EngineSession::removeTrack(const juce::String& id,std::uint64_t rev){return execute("remove_track",object({{"track_id",id}}),rev);}
juce::Result EngineSession::undo(std::uint64_t rev){return execute("undo",object({}),rev);}
juce::Result EngineSession::redo(std::uint64_t rev){return execute("redo",object({}),rev);}
void EngineSession::beginEditGesture(){requireControlThread();impl->finishGesture();impl->edit->getUndoManager().beginNewTransaction("Adjust gain");impl->gesture=true;}
void EngineSession::endEditGesture(){requireControlThread();impl->finishGesture();}
void EngineSession::togglePlay(){
    if(impl->recordingBusy()){stop();return;}
    requireControlThread();if(impl->duration<=0&&!impl->edit->clickTrackEnabled.get())return;auto& t=impl->edit->getTransport();if(t.isPlaying()){t.stop(false,false);impl->status="Paused.";return;}
    if(!snapshot().deviceAvailable){impl->status="Choose an output in audio settings.";return;}t.play(false);impl->status="Playing.";
}
void EngineSession::stop(){requireControlThread();const bool recording=impl->recordingBusy();if(recording)impl->recording.execute("stop_recording",object({}));else impl->edit->getTransport().stop(false,false);if(!recording)impl->edit->getTransport().setPosition(te::TimePosition::fromSeconds(0));impl->finishRecording();impl->status=impl->recordingBusy()?"Finishing recording...":"Stopped.";}
void EngineSession::seek(double seconds){requireControlThread();if(impl->recordingBusy())return;if(std::isfinite(seconds))impl->edit->getTransport().setPosition(te::TimePosition::fromSeconds(juce::jlimit(0.0,storage::maximumTimelineSeconds,seconds)));}
void EngineSession::setLoop(bool enabled){execute("set_loop",object({{"enabled",enabled}}),impl->guard.revision());}
void EngineSession::setGain(float db){execute("set_master_gain",object({{"gain_db",std::isfinite(db)?stableGain(db):db}}),impl->guard.revision());}
juce::AudioDeviceManager& EngineSession::deviceManager(){requireControlThread();return impl->engine.getDeviceManager().deviceManager;}
bool EngineSession::hasActiveJobs()const{for(const auto& j:impl->jobs)if(j->worker.joinable())return true;return impl->pluginHost.scanSnapshot().running;}
void EngineSession::cancelAllJobs(){for(auto& j:impl->jobs)j->cancel=true;impl->pluginHost.cancelScan();}

juce::var EngineSession::capabilities()const
{
    // Selection revision is independent from musical project revision.
    juce::Array<juce::var> commands;
    commands.add("get_selection_context");
    for(const auto* name:{"get_capabilities","get_snapshot","get_project_state","get_jobs","get_job","get_events","get_clip_notes","create_track","rename_track","reorder_track","remove_track","set_track_gain","set_track_pan","set_track_muted","set_track_solo","set_master_gain","set_loop","set_loop_range","set_tempo","set_time_signature","move_clip","move_clips","trim_clip","split_clip","duplicate_clips","delete_clips","set_clip_fades","create_midi_clip","write_notes","batch","undo","redo","import_audio","import_midi","save_project","open_project","export_wav","export_midi","scan_plugins","cancel_job","add_plugin","remove_plugin","move_plugin","set_plugin_enabled","open_plugin","new_project","play","pause","stop","seek"})commands.add(name);
    for(const auto* command:{"get_recording_preferences","set_recording_preferences","reset_meters","get_clipboard_state","copy_clips","cut_clips","paste_clips"})commands.add(command);
    commands.add("get_track_clips");commands.add("get_plugin_catalog");commands.add("get_plugin_parameters");commands.add("set_plugin_parameter");commands.add("edit_notes");commands.add("get_save_diagnostics");
    for(const auto* command:{"get_recording_state","get_recording_inputs","get_audio_devices","configure_audio_device","set_track_input","set_track_armed","set_input_monitor","start_recording","stop_recording","set_track_output","add_send","update_send","remove_send","get_automation_targets","get_automation_points","set_automation_lane","remove_automation_lane","get_clip_controllers"})commands.add(command);
    return object({{"protocol_version",1},{"batch_result_refs",true},{"batch_result_refs_version",1},{"project_schema_version",4},{"max_controller_events",100000},{"max_automation_points",100000},{"max_automation_page",1000},{"max_sends_per_track",32},{"max_sends",512},{"recording_mode","linear_take"},{"monitor_scope","input_device"},{"commands",commands},{"default_bpm",120},{"tempo_min",20},{"tempo_max",300},{"max_tracks",64},{"max_clips",4096},{"max_notes",100000},{"max_note_page",1000},{"max_clip_page",256},{"max_catalog_page",256},{"snapshot_clips_per_track",64},{"snapshot_clips_total",256},{"snapshot_includes_note_content",false},{"plugin_formats",juce::var(juce::Array<juce::var>{"VST","VST3"})},{"network_control",false},{"event_sequence",juce::int64(impl->eventSequence)}});
}
namespace {
juce::var controlClipJson(const EngineSession::ClipSnapshot& c)
{return object({{"id",c.id},{"asset_id",c.assetId},{"kind",c.kind},{"start_seconds",c.timelineStart},{"source_offset",c.sourceOffset},{"duration_seconds",c.duration},{"start_beats",c.startBeats},{"length_beats",c.lengthBeats},{"fade_in_seconds",c.fadeIn},{"fade_out_seconds",c.fadeOut},{"note_count",int(c.notes?c.notes->size():0)},{"controller_count",c.controllerCount}});}
juce::var controlCatalogJson(const EngineSession::PluginDescriptorSnapshot& c)
{return object({{"id",c.id},{"name",c.name},{"format",c.format},{"manufacturer",c.manufacturer},{"is_instrument",c.isInstrument}});}
juce::var controlLanesJson(const std::vector<EngineSession::AutomationLaneSnapshot>& lanes)
{juce::Array<juce::var> out;for(const auto& lane:lanes)out.add(object({{"id",lane.id},{"target",lane.target},{"plugin_id",lane.pluginId},{"parameter_id",lane.parameterId},{"enabled",lane.enabled},{"point_count",int(lane.points?lane.points->size():0)}}));return out;}
}
juce::var EngineSession::snapshotJson()const
{
    auto s=snapshot();juce::Array<juce::var> tracks,jobs,catalog;int remainingClips=256;
    auto plugins=[](const auto& ps){juce::Array<juce::var> out;for(const auto& p:ps)out.add(object({{"id",p.id},{"name",p.name},{"format",p.format},{"enabled",p.enabled},{"missing",p.missing},{"is_instrument",p.isInstrument}}));return juce::var(out);};
    for(const auto& t:s.tracks){juce::Array<juce::var> clips;for(const auto& c:t.clips){
        if(clips.size()>=64||remainingClips<=0)break;clips.add(controlClipJson(c));--remainingClips;}
        juce::Array<juce::var> sends;for(const auto& send:t.sends)sends.add(object({{"id",send.id},{"target_track_id",send.targetTrackId},{"gain_db",send.gainDb},{"pre_fader",send.preFader},{"enabled",send.enabled}}));
        tracks.add(object({{"id",t.id},{"name",t.name},{"kind",t.kind},{"gain_db",t.gainDb},{"pan",t.pan},{"muted",t.muted},{"solo",t.solo},{"clips",clips},{"clip_count",int(t.clips.size())},{"clips_truncated",clips.size()<int(t.clips.size())},{"plugins",plugins(t.plugins)},{"input_device_id",t.inputDeviceId},{"output_target_id",t.outputTargetId},{"armed",t.armed},{"monitor",t.monitorMode},{"peak_left_db",t.peakLeftDb},{"peak_right_db",t.peakRightDb},{"input_peak_db",t.inputPeakDb},{"overloaded",t.overloaded},{"sends",sends},{"automation",controlLanesJson(t.automation)}}));}
    for(const auto& j:s.jobs)jobs.add(jobSnapshotJson(j));
    for(const auto& c:s.pluginCatalog){if(catalog.size()>=256)break;catalog.add(controlCatalogJson(c));}
    return object({{"project_id",s.projectId},{"revision",juce::int64(s.revision)},{"name",s.projectName},{"dirty",s.dirty},{"bpm",s.bpm},{"numerator",s.numerator},{"denominator",s.denominator},{"duration_seconds",s.duration},{"position_seconds",s.position},{"playing",s.playing},{"looping",s.looping},{"loop_start_seconds",s.loopStart},{"loop_end_seconds",s.loopEnd},{"master_gain_db",s.gainDb},{"selection_context",selectionContext()},{"selected_track_id",s.selectedTrackId},{"selected_clip_id",s.selectedClipId},{"can_undo",s.canUndo},{"can_redo",s.canRedo},{"tracks",tracks},{"jobs",jobs},{"plugin_catalog",catalog},{"plugin_catalog_total",int(s.pluginCatalog.size())},{"plugin_catalog_truncated",catalog.size()<int(s.pluginCatalog.size())},{"master_plugins",plugins(s.masterPlugins)},{"master_automation",controlLanesJson(s.masterAutomation)},{"recording",s.recording},{"recording_finalizing",s.recordingFinalizing},{"recording_error",s.recordingError},{"recording_preferences",impl->recording.preferences()},{"counting_in",s.countingIn},{"count_in_beats_remaining",s.countInBeatsRemaining},{"memory_working_set_bytes",s.memoryWorkingSetBytes},{"memory_private_bytes",s.memoryPrivateBytes},{"master_peak_left_db",s.masterPeakLeftDb},{"master_peak_right_db",s.masterPeakRightDb},{"master_overloaded",s.masterOverloaded},{"cpu_usage",s.cpuUsage},{"xruns",s.xruns},{"sample_rate",s.sampleRate},{"buffer_size",s.bufferSize},{"event_sequence",juce::int64(impl->eventSequence)}});
}
juce::var EngineSession::eventsSince(std::uint64_t seq)const
{juce::Array<juce::var> out;for(const auto& e:impl->events)if(std::uint64_t(juce::int64(e.getProperty("sequence",0)))>seq)out.add(e);bool lost=!impl->events.isEmpty()&&seq+1<std::uint64_t(juce::int64(impl->events[0].getProperty("sequence",0)));return object({{"events",out},{"resync_required",lost},{"sequence",juce::int64(impl->eventSequence)}});}

juce::var EngineSession::executeRequest(const juce::var& envelope)
{
    requireControlThread();auto command=textArg(envelope,"command"),request=textArg(envelope,"request_id");
    auto reply=[&](const juce::String& status,juce::var result,juce::String error={}){return object({{"request_id",request},{"status",status},{"project_id",juce::String(impl->guard.projectId())},{"revision",juce::int64(impl->guard.revision())},{"result",result},{"error",error}});};
    if(!envelope.isObject())return reply("invalid",{},"Request must be an object.");
    auto args=envelope.getProperty("args",object({}));
    if(!args.isObject())return reply("invalid",{},"Request args must be an object.");
    if(command=="get_capabilities")return reply("completed",capabilities());
    if(command=="get_selection_context")return reply("completed",selectionContext());
    if(command=="get_project_state"||command=="get_snapshot")return reply("completed",snapshotJson());
    if(command=="get_save_diagnostics"){
        // Explicit troubleshooting only: never hash full musical content in
        // the normal transport/snapshot poll, or mutate the saved baseline.
        const auto fresh=impl->calculateCurrentKey();
        return reply("completed",object({{"current_key",impl->currentKey},{"saved_key",impl->savedKey},
            {"fresh_content_key",fresh},{"plugin_dirty",impl->pluginDirty},
            {"pending_plugin_changes",impl->pluginHost.hasPendingChanges()},{"revision",juce::int64(impl->guard.revision())}}));
    }
    if(command=="get_recording_preferences")return reply("completed",impl->recording.preferences());
    if(command=="get_clipboard_state")return reply("completed",object({{"clipboard_id",impl->clipClipboard.id},{"project_id",impl->clipClipboard.projectId},{"clip_count",int(impl->clipClipboard.clips.size())}}));
    if(command=="get_recording_state")return reply("completed",impl->recording.state());
    if(command=="get_recording_inputs")return reply("completed",impl->recording.inputs());
    if(command=="get_audio_devices"){
        if(impl->recordingBusy()&&bool(args.getProperty("scan",false)))return reply("busy",{},"Device scans are unavailable during recording.");
        return reply("completed",impl->recording.audioDevices(bool(args.getProperty("scan",false))));
    }
    if(command=="get_automation_targets")return reply("completed",production::automationTargets(*impl->edit,textArg(args,"track_id")));
    if(command=="get_automation_points"||command=="get_clip_controllers"){
        auto offset=args.getProperty("offset",0),limit=args.getProperty("limit",256);
        if((!offset.isInt()&&!offset.isInt64())||(!limit.isInt()&&!limit.isInt64())||juce::int64(offset)<0||juce::int64(offset)>1000000||juce::int64(limit)<1||juce::int64(limit)>1000)return reply("invalid",{},"Page requires non-negative offset and limit 1 to 1000.");
        juce::Array<juce::var> values;const int begin=int(offset),count=int(limit);int total=0;
        if(command=="get_automation_points"){
            auto state=snapshot();const auto tid=textArg(args,"track_id"),id=textArg(args,"lane_id");const auto* lanes=&state.masterAutomation;
            if(tid!="master"){auto it=std::find_if(state.tracks.begin(),state.tracks.end(),[&](const auto& t){return t.id==tid;});if(it==state.tracks.end())return reply("failed",{},"Track not found.");lanes=&it->automation;}
            auto it=std::find_if(lanes->begin(),lanes->end(),[&](const auto& l){return l.id==id;});if(it==lanes->end())return reply("failed",{},"Automation lane not found.");
            total=int(it->points?it->points->size():0);for(int i=begin;i<std::min(total,begin+count);++i){const auto& p=(*it->points)[size_t(i)];values.add(object({{"id",p.id},{"time_seconds",p.timeSeconds},{"value",p.value},{"curve",p.curve}}));}
        }else{
            auto* binding=impl->findClip(textArg(args,"clip_id"));auto* midi=binding?dynamic_cast<te::MidiClip*>(binding->clip.get()):nullptr;if(!midi)return reply("failed",{},"MIDI clip not found.");
            const auto& events=midi->getSequence().getControllerEvents();total=events.size();for(int i=begin;i<std::min(total,begin+count);++i){auto* e=events[i];values.add(object({{"id",e->state[emId].toString()},{"beats",e->getBeatPosition().inBeats()},{"type",e->getType()},{"value",e->getControllerValue()},{"metadata",e->getMetadata()}}));}
        }
        return reply("completed",object({{command=="get_automation_points"?"points":"events",values},{"total",total},{"offset",begin},{"has_more",begin+values.size()<total}}));
    }
    if(command=="get_plugin_parameters"){
        auto data=impl->getPluginParameters(args);
        if(data.hasProperty("error"))return reply("failed",{},data.getProperty("error",{}).toString());
        return reply("completed",data);
    }
    if(command=="get_jobs"||command=="get_job"){
        juce::Array<juce::var> list;for(const auto& j:snapshot().jobs){auto v=jobSnapshotJson(j);
            if(command=="get_job"&&j.id==textArg(args,"job_id"))return reply("completed",v);list.add(v);}
        return command=="get_job"?reply("failed",{},"Task not found."):reply("completed",object({{"jobs",list}}));
    }
    if(command=="get_track_clips"||command=="get_plugin_catalog"){
        auto offset=args.getProperty("offset",0),limit=args.getProperty("limit",64);
        if((!offset.isInt()&&!offset.isInt64())||(!limit.isInt()&&!limit.isInt64())||juce::int64(offset)<0
            ||juce::int64(offset)>1000000||juce::int64(limit)<1||juce::int64(limit)>256)return reply("invalid",{},"Invalid page: non-negative offset and limit 1 to 256 required.");
        const auto start=size_t(juce::int64(offset)),end=start+size_t(juce::int64(limit));auto state=snapshot();juce::Array<juce::var> page;
        if(command=="get_plugin_catalog"){
            for(size_t i=start;i<state.pluginCatalog.size()&&i<end;++i)page.add(controlCatalogJson(state.pluginCatalog[i]));
            return reply("completed",object({{"total",int(state.pluginCatalog.size())},{"offset",int(start)},{"plugins",page}}));
        }
        const auto id=textArg(args,"track_id");for(const auto& track:state.tracks)if(track.id==id){
            for(size_t i=start;i<track.clips.size()&&i<end;++i)page.add(controlClipJson(track.clips[i]));
            return reply("completed",object({{"track_id",id},{"total",int(track.clips.size())},{"offset",int(start)},{"clips",page}}));
        }return reply("failed",{},"Track not found.");
    }
    if(command=="get_clip_notes"){
        auto offset=number(args,"offset",0),limit=number(args,"limit",256);
        if(!std::isfinite(offset)||!std::isfinite(limit)||offset<0||limit<1||limit>1000||offset!=std::floor(offset)||limit!=std::floor(limit)||offset>100000)return reply("invalid",{},"Invalid note page.");
        auto id=textArg(args,"clip_id");for(const auto& t:snapshot().tracks)for(const auto& c:t.clips)if(c.id==id&&c.notes){
            juce::Array<juce::var> page;for(size_t i=size_t(offset);i<c.notes->size()&&i<size_t(offset+limit);++i){const auto& n=(*c.notes)[i];page.add(object({{"id",n.id},{"pitch",n.pitch},{"start_beats",n.startBeats},{"length_beats",n.lengthBeats},{"velocity",n.velocity},{"channel",n.channel}}));}
            return reply("completed",object({{"clip_id",id},{"total",int(c.notes->size())},{"offset",int(offset)},{"notes",page}}));
        }return reply("failed",{},"MIDI clip not found.");
    }
    if(command=="get_events"){
        auto after=args.getProperty("after_sequence",juce::int64(0));
        if((!after.isInt()&&!after.isInt64())||juce::int64(after)<0)return reply("invalid",{},"after_sequence must be a non-negative integer.");
        return reply("completed",eventsSince(std::uint64_t(juce::int64(after))));
    }
    if(request.isEmpty()||request.length()>128)return reply("invalid",{},"A request_id of 1 to 128 characters is required.");
    const auto serialized=juce::JSON::toString(envelope,true);auto digest=juce::SHA256(serialized.toRawUTF8(),size_t(serialized.getNumBytesAsUTF8())).toHexString();
    if(auto found=impl->replies.find(request);found!=impl->replies.end())return found->second.digest==digest?found->second.value:reply("invalid",{},"request_id was reused with different content.");
    auto expected=envelope.getProperty("expected_revision",{});if((!expected.isInt()&&!expected.isInt64())||juce::int64(expected)<0)return reply("invalid",{},"expected_revision must be a non-negative integer.");
    if(textArg(envelope,"project_id")!=juce::String(impl->guard.projectId()))return reply("wrong_project",{},"Project identity changed.");
    auto revision=std::uint64_t(juce::int64(expected));if(revision!=impl->guard.revision())return reply("conflict",{},"Project revision changed.");
    if(envelope.hasProperty("expected_selection_revision")){
        auto expectedSelection=envelope["expected_selection_revision"];
        if((!expectedSelection.isInt()&&!expectedSelection.isInt64())||juce::int64(expectedSelection)<0)return reply("invalid",{},"expected_selection_revision must be a non-negative integer.");
        if(juce::int64(selectionContext()["selection_revision"])!=juce::int64(expectedSelection))return reply("selection_conflict",{},"Music selection changed; review a new plan.");
    }
    if(impl->replies.size()>=10000)return reply("busy",{},"Request history is full; restart the control session.");
    const auto missingClipboardToken=[](const juce::String& name,const juce::var& parameters){return name=="paste_clips"&&!parameters["clipboard_id"].isString();};
    bool missingToken=missingClipboardToken(command,args);
    if(command=="batch")if(auto* children=args["commands"].getArray())
        for(const auto& child:*children)missingToken=missingToken||missingClipboardToken(textArg(child,"command"),child["args"]);
    const auto priorJob=impl->jobs.empty()?juce::String():impl->jobs.back()->id;juce::Result result=juce::Result::ok();juce::var data;
    if(impl->recordingBusy()&&(command=="play"||command=="pause"||command=="seek"))result=juce::Result::fail("Stop recording and finish the take before changing transport position or playback.");
    else if(command=="new_project")result=newProject(revision);
    else if(command=="play"){if(!snapshot().playing)togglePlay();if(!snapshot().playing)result=juce::Result::fail("Playback could not start.");}
    else if(command=="pause"){if(snapshot().playing)togglePlay();}
    else if(command=="stop")stop();
    else if(command=="seek"){auto at=number(args,"seconds");if(!std::isfinite(at)||at<0)result=juce::Result::fail("Invalid seek position.");else seek(at);}
    else if(missingToken)result=juce::Result::fail("Agent paste_clips, including batch children, requires clipboard_id returned by copy_clips/cut_clips.");
    else result=execute(command,args,revision,&data);
    bool accepted=false;
    if(result.wasOk()&&!impl->jobs.empty()&&impl->jobs.back()->id!=priorJob){data=object({{"job_id",impl->jobs.back()->id}});accepted=true;}
    if(result.wasOk()&&command=="scan_plugins"){data=object({{"job_id","plugin-scan"}});accepted=true;}
    if(result.wasOk()&&(command=="copy_clips"||command=="cut_clips"))data=object({{"clipboard_id",impl->clipClipboard.id},{"clip_count",int(impl->clipClipboard.clips.size())}});
    auto response=reply(result.failed()?"failed":accepted?"accepted":"completed",data,result.getErrorMessage());impl->replies.emplace(request,Impl::Reply{digest,response});return response;
}
