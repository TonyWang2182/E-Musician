// Control-thread recording lifecycle. The pinned engine owns device callbacks,
// MIDI capture and its audio writer thread; recorded files outlive Undo entries.
namespace production {
// Recorded event timestamps may coincide even though both MIDI edges are valid.
// Normalise the authoritative take before snapshots/Undo/persistence see it.
// Keep every onset and event; extend the clip rather than discard a late tail.
static void normaliseRecordedMidiTiming(te::MidiClip& clip)
{
    constexpr double minimumNoteBeats = 1.0 / 960.0; // SMF export resolution.
    auto* undo = &clip.edit.getUndoManager();
    double lastEventBeat = 0;
    for (auto* note : clip.getSequence().getNotes()) {
        const double start = double(note->state[te::IDs::b]), length = double(note->state[te::IDs::l]);
        const int pitch = int(note->state[te::IDs::p]), velocity = int(note->state[te::IDs::v]);
        // Do not disguise corrupted state as a legitimate short captured note.
        if (!std::isfinite(start) || !std::isfinite(length) || start < 0 || length < 0
            || pitch < 0 || pitch > 127 || velocity < 1 || velocity > 127) continue;
        const auto duration = std::max(length, minimumNoteBeats);
        const auto end = start + duration;
        if (!std::isfinite(end)) continue;
        if (duration != length) note->setStartAndLength(te::BeatPosition::fromBeats(start), te::BeatDuration::fromBeats(duration), undo);
        lastEventBeat = std::max(lastEventBeat, end);
    }
    for (auto* event : clip.getSequence().getControllerEvents()) {
        const auto beat = event->getBeatPosition().inBeats();
        if (std::isfinite(beat) && beat >= 0) lastEventBeat = std::max(lastEventBeat, beat);
    }
    // Content beats are source-relative: this handles a nonzero timeline start
    // without adding that start twice, and does not alter the source offset.
    const auto end = clip.getTimeOfContentBeat(te::BeatPosition::fromBeats(lastEventBeat));
    const auto position = clip.getPosition();
    if (!std::isfinite(end.inSeconds()) || end.inSeconds() > storage::maximumTimelineSeconds) return;
    double endSeconds = std::max(end.inSeconds(), position.time.getEnd().inSeconds());
    if (position.offset.inSeconds() == 0) {
        // Persistence derives clip beats from its duration in seconds. At a
        // nonzero origin, subtraction can round below a controller's exact end.
        const auto bpm = clip.edit.tempoSequence.getTempo(0)->getBpm();
        for (int i = 0; i < 8 && time::secondsToBeats(endSeconds - position.time.getStart().inSeconds(), bpm) < lastEventBeat; ++i)
            endSeconds = std::nextafter(endSeconds, std::numeric_limits<double>::infinity());
    }
    if (endSeconds <= storage::maximumTimelineSeconds && endSeconds > position.time.getEnd().inSeconds())
        clip.setEnd(te::TimePosition::fromSeconds(endSeconds), true);
}

struct RecordingController::State final : te::TransportControl::Listener {
    te::Engine& engine;
    te::Edit* edit = nullptr;
    juce::File directory;
    juce::String error;
    bool activeTake = false, transactionStarted = false, adopted = false;
    int finishingInputs = 0;
    bool metronomeEnabled=false, recordOnly=false, countEnabled=false, cancelled=false;
    std::map<juce::String, juce::String> monitorRebindAttempts;
    int countBars=1;
    float gainDb=-12;
    double punchTime=0;
    explicit State(te::Engine& e) : engine(e) {
        auto& p=engine.getPropertyStorage().getPropertiesFile();
        metronomeEnabled=p.getBoolValue("emMetronomeEnabled",false);
        recordOnly=p.getBoolValue("emMetronomeRecordOnly",false);
        countEnabled=p.getBoolValue("emCountInEnabled",false);
        countBars=p.getIntValue("emCountInBars",1);if(countBars!=1&&countBars!=2&&countBars!=4)countBars=1;
        gainDb=float(p.getDoubleValue("emMetronomeGainDb",-12));if(!std::isfinite(gainDb))gainDb=-12;gainDb=juce::jlimit(-36.0f,0.0f,gainDb);
    }
    void applyPreferences() {
        if(!edit)return;
        edit->clickTrackEnabled=metronomeEnabled;edit->clickTrackRecordingOnly=recordOnly;
        edit->clickTrackEmphasiseBars=true;edit->setClickTrackVolume(juce::Decibels::decibelsToGain(gainDb));
        edit->setCountInMode(!countEnabled?te::Edit::CountIn::none:countBars==1?te::Edit::CountIn::oneBar:countBars==2?te::Edit::CountIn::twoBar:te::Edit::CountIn::fourBar);
    }
    double position() const {
        if(!edit)return 0;
        auto& transport=edit->getTransport();
        if(auto* context=transport.getCurrentPlaybackContext()){
            // postPlay/postPosition take effect at the next audio block. Before
            // that block, the old playhead may already equal the punch-in point.
            // Use the native queued transport position only while play is pending;
            // after dispatch, count-down is exclusively the audio-clock position.
            if(context->isPlayPending())return transport.getPosition().inSeconds();
            return context->getPosition().inSeconds();
        }
        return transport.getPosition().inSeconds();
    }
    bool countingIn() const {return edit&&edit->getTransport().isRecording()&&position()<punchTime-1.0e-8;}
    juce::Result setPreferences(const juce::var& args) {
        for(const auto& field:args.getDynamicObject()->getProperties()){
            const auto name=field.name.toString();
            if(name!="metronome_enabled"&&name!="metronome_gain_db"&&name!="metronome_record_only"&&name!="count_in_enabled"&&name!="count_in_bars")return graphError("Unknown recording preference: "+name);
        }
        for(const auto* field:{"metronome_enabled","metronome_record_only","count_in_enabled"})if(args.hasProperty(field)&&!args[field].isBool())return graphError(juce::String(field)+" must be boolean.");
        if(args.hasProperty("metronome_gain_db")){
            auto v=args["metronome_gain_db"];double gain=double(v);
            if((!v.isInt()&&!v.isInt64()&&!v.isDouble())||!std::isfinite(gain)||gain < -36||gain>0)return graphError("Metronome gain must be -36 to 0 dB.");
        }
        if(args.hasProperty("count_in_bars")){
            auto v=args["count_in_bars"];double bars=double(v);
            if((!v.isInt()&&!v.isInt64()&&!v.isDouble())||(bars!=1&&bars!=2&&bars!=4))return graphError("Count-in must be 1, 2, or 4 bars; use count_in_enabled to disable it.");
        }
        metronomeEnabled=bool(args.getProperty("metronome_enabled",metronomeEnabled));recordOnly=bool(args.getProperty("metronome_record_only",recordOnly));
        countEnabled=bool(args.getProperty("count_in_enabled",countEnabled));countBars=int(args.getProperty("count_in_bars",countBars));gainDb=float(args.getProperty("metronome_gain_db",gainDb));
        auto& p=engine.getPropertyStorage().getPropertiesFile();
        p.setValue("emMetronomeEnabled",metronomeEnabled);p.setValue("emMetronomeRecordOnly",recordOnly);p.setValue("emMetronomeGainDb",gainDb);p.setValue("emCountInEnabled",countEnabled);p.setValue("emCountInBars",countBars);
        applyPreferences();return juce::Result::ok();
    }

    te::InputDevice* device(const juce::String& id) const {
        for (auto* d : engine.getDeviceManager().getWaveInputDevices()) if (d->getDeviceID() == id) return d;
        for (const auto& d : engine.getDeviceManager().getMidiInDevices()) if (d->getDeviceID() == id) return d.get();
        return nullptr;
    }
    static juce::String monitor(te::InputDevice& d) {
        switch (d.getMonitorMode()) { case te::InputDevice::MonitorMode::on: return "on"; case te::InputDevice::MonitorMode::automatic: return "auto"; default: return "off"; }
    }
    using MonitorModes = std::map<juce::String, te::InputDevice::MonitorMode>;
    MonitorModes monitorModes() const {
        MonitorModes modes;
        for (auto* input : engine.getDeviceManager().getWaveInputDevices()) modes[input->getDeviceID()] = input->getMonitorMode();
        for (const auto& input : engine.getDeviceManager().getMidiInDevices()) modes[input->getDeviceID()] = input->getMonitorMode();
        return modes;
    }
    void restoreMonitorsOrDefaultOff(const MonitorModes& previous) {
        const auto restore = [&](te::InputDevice& input) {
            const auto found = previous.find(input.getDeviceID());
            input.setMonitorMode(found == previous.end() ? te::InputDevice::MonitorMode::off : found->second);
        };
        // Owners exist even when this Edit has no playback context/instances.
        // Enumerate the engine's existing inputs without opening new devices.
        for (auto* input : engine.getDeviceManager().getWaveInputDevices()) restore(*input);
        for (const auto& input : engine.getDeviceManager().getMidiInDevices()) restore(*input);
    }
    juce::String selectedInput(te::AudioTrack& track) const { return track.state.getChildWithName("EM_PRODUCTION")["inputDeviceId"].toString(); }
    te::InputDeviceInstance* instance(const juce::String& id) const {
        if (edit) for (auto* i : edit->getAllInputDevices()) if (i->getInputDevice().getDeviceID() == id) return i;
        return nullptr;
    }
    // A device change may destroy and replace input instances. Never retain a
    // device/instance pointer across setEnabled/dispatchPendingUpdates.
    juce::Result bind(te::AudioTrack& track, bool armed) {
        const auto id = selectedInput(track); auto* input = device(id);
        if (!input) return graphError("Selected recording input is unavailable. Select an input again.");
        if (input->isMidi() != (track.state["emKind"].toString() == "instrument")) return graphError("Audio tracks need an audio input; MIDI tracks need a MIDI input.");
        if (!input->isEnabled()) { input->setEnabled(true); engine.getDeviceManager().dispatchPendingUpdates(); }
        input = device(id); if (!input || !input->isEnabled()) return graphError("Could not enable the selected recording input.");
        edit->getTransport().ensureContextAllocated();
        auto* destination = instance(id); if (!destination) return graphError("The input has no active playback instance. Check the audio device configuration.");
        for (auto* old : edit->getAllInputDevices()) if (old != destination && old->getTargets().contains(track.itemID)) {
            old->setRecordingEnabled(track.itemID, false); auto ignored = old->removeTarget(track.itemID, nullptr); juce::ignoreUnused(ignored);
        }
        if (!destination->getTargets().contains(track.itemID)) {
            auto result = destination->setTarget(track.itemID, false, nullptr, 0);
            if (!result) return graphError(result.error());
        }
        destination->setRecordingEnabled(track.itemID, armed);
        return juce::Result::ok();
    }
    void reconcile() {
        if (!edit || edit->getTransport().isRecording() || edit->getTransport().isRecordingStopping()) return;
        std::map<juce::String, bool> previousArms;
        for (auto* input : edit->getAllInputDevices()) for (auto target : input->getTargets()) {
            auto* track = dynamic_cast<te::AudioTrack*>(te::findTrackForID(*edit, target));
            if (!track || selectedInput(*track) != input->getInputDevice().getDeviceID()) {
                if (track) previousArms[track->state["emId"].toString()] |= input->isRecordingEnabled(target);
                input->setRecordingEnabled(target, false); auto ignored = input->removeTarget(target, nullptr); juce::ignoreUnused(ignored);
            }
        }
        for (auto* track : te::getAudioTracks(*edit)) {
            const auto trackId = track->state["emId"].toString(), id = selectedInput(*track);
            const bool wasArmed = previousArms[trackId];
            const bool wantsLive = track->state["emMonitorMode"].toString() == "on";
            if (id.isEmpty() || (!wasArmed && !wantsLive)) { monitorRebindAttempts.erase(trackId); continue; }
            auto* input = instance(id);
            if (input && input->getTargets().contains(track->itemID)) { monitorRebindAttempts.erase(trackId); continue; }
            if (!device(id) || monitorRebindAttempts[trackId] == id) continue;
            // Try once for this selection; explicit arm/monitor changes retry.
            // Avoid repeatedly restarting the graph if a driver cannot open.
            monitorRebindAttempts[trackId] = id;
            if (auto result = bind(*track, wasArmed); result.failed()) error = result.getErrorMessage();
            else monitorRebindAttempts.erase(trackId);
        }
    }
    void recordingStarted(te::SyncPoint start, std::optional<te::TimeRange>) override {
        punchTime=start.time.inSeconds();cancelled=false;
        activeTake = true; adopted = false; transactionStarted = false; finishingInputs = 0; error.clear();
    }
    void recordingAboutToStop(te::InputDeviceInstance&, te::EditItemID) override {
        if (edit && !cancelled && !transactionStarted) { edit->getUndoManager().beginNewTransaction("Record take"); transactionStarted = true; }
        ++finishingInputs;
    }
    void recordingFinished(te::InputDeviceInstance&, te::EditItemID, const juce::ReferenceCountedArray<te::Clip>& clips) override {
        if (!edit || cancelled) { finishingInputs=std::max(0,finishingInputs-1);return; } auto* um = &edit->getUndoManager();
        for (auto* clip : clips) {
            if (clip->state["emId"].toString().isEmpty()) clip->state.setProperty("emId", freshId(), um);
            if (auto* audio = dynamic_cast<te::WaveAudioClip*>(clip)) {
                const auto file = audio->getOriginalFile();
                if (!file.existsAsFile()) { error = "Recording ended without a readable audio file."; continue; }
                clip->state.setProperty("emKind", "audio", um);
                clip->state.setProperty("emAsset", freshId(), um);
                clip->state.setProperty("emSource", file.getFullPathName(), um);
                adopted = true;
            } else if (auto* midi = dynamic_cast<te::MidiClip*>(clip)) {
                clip->state.setProperty("emKind", "midi", um); midi->setUsesProxy(false); midi->setSyncType(te::Clip::syncBarsBeats);
                normaliseRecordedMidiTiming(*midi);
                for (auto* note : midi->getSequence().getNotes()) if (note->state["emId"].toString().isEmpty()) note->state.setProperty("emId", freshId(), um);
                for (auto* controller : midi->getSequence().getControllerEvents()) if (controller->state["emId"].toString().isEmpty()) controller->state.setProperty("emId", freshId(), um);
                adopted = true;
            }
        }
        finishingInputs = std::max(0, finishingInputs - 1);
    }
    juce::Result configureDevice(const juce::var& args) {
        if (edit && edit->getTransport().isPlaying()) return graphError("Stop playback before changing the audio device.");
        auto& manager = engine.getDeviceManager().deviceManager;
        const auto beforeType = manager.getCurrentAudioDeviceType(); const auto before = manager.getAudioDeviceSetup();
        const auto previousMonitorModes = monitorModes();
        const auto wantedType = args.getProperty("driver_type", beforeType).toString();
        auto rollback = [&](const juce::String& failure) {
            manager.setCurrentAudioDeviceType(beforeType, true);
            const auto restore = manager.setAudioDeviceSetup(before, true);
            engine.getDeviceManager().dispatchPendingUpdates();
            restoreMonitorsOrDefaultOff(previousMonitorModes);
            return graphError(failure + (restore.isEmpty() ? " Previous device configuration restored." : " Restore failed: " + restore));
        };
        bool found = false; for (auto* type : manager.getAvailableDeviceTypes()) if (type->getTypeName() == wantedType) found = true;
        if (!found) return graphError("Audio driver type is unavailable in this build: " + wantedType);
        manager.setCurrentAudioDeviceType(wantedType, true);
        auto setup = manager.getAudioDeviceSetup();
        if (args.hasProperty("device_name")) setup.inputDeviceName = setup.outputDeviceName = args["device_name"].toString();
        if (args.hasProperty("input_device_name")) setup.inputDeviceName = args["input_device_name"].toString();
        if (args.hasProperty("output_device_name")) setup.outputDeviceName = args["output_device_name"].toString();
        if (args.hasProperty("sample_rate")) setup.sampleRate = double(args["sample_rate"]);
        if (args.hasProperty("buffer_size")) setup.bufferSize = int(args["buffer_size"]);
        if (!std::isfinite(setup.sampleRate) || setup.sampleRate < 8000 || setup.sampleRate > 384000 || setup.bufferSize < 16 || setup.bufferSize > 8192) return rollback("Invalid sample rate or buffer size.");
        setup.useDefaultInputChannels = true; setup.useDefaultOutputChannels = true;
        if (args.hasProperty("input_channels")) {
            auto* channels = args["input_channels"].getArray(); if (!channels) return rollback("input_channels must be an array.");
            setup.inputChannels.clear(); setup.useDefaultInputChannels = false;
            for (const auto& channel : *channels) { int index = int(channel); if (index < 0 || index > 63) return rollback("Input channel index is out of range."); setup.inputChannels.setBit(index); }
        }
        auto failure = manager.setAudioDeviceSetup(setup, true); if (failure.isNotEmpty()) return rollback(failure);
        auto* opened = manager.getCurrentAudioDevice(); if (!opened || !opened->isOpen()) return rollback("Audio driver did not open a device.");
        if (args.hasProperty("sample_rate") && std::abs(opened->getCurrentSampleRate() - setup.sampleRate) > 0.01) return rollback("The audio driver did not accept the requested sample rate.");
        if (args.hasProperty("buffer_size") && opened->getCurrentBufferSizeSamples() != setup.bufferSize) return rollback("The audio driver did not accept the requested buffer size.");
        engine.getDeviceManager().dispatchPendingUpdates();
        // Preserve user choices for surviving IDs. Newly created driver inputs
        // must not inherit a native on/auto default and begin monitoring.
        restoreMonitorsOrDefaultOff(previousMonitorModes);
        reconcile(); error.clear(); return juce::Result::ok();
    }
};

RecordingController::RecordingController(te::Engine& e) : data(std::make_unique<State>(e)) {}
RecordingController::~RecordingController() { detach(); }
void RecordingController::detach() {
    if (data->edit) { data->edit->getTransport().removeListener(data.get()); data->edit = nullptr; }
    data->activeTake = false; data->finishingInputs = 0; data->transactionStarted = false;
    data->monitorRebindAttempts.clear();
}
void RecordingController::attach(te::Edit& edit, const juce::File& directory) {
    detach(); data->edit = &edit; data->directory = directory; data->error.clear();
    edit.getTransport().addListener(data.get());
    // A project never starts recording/monitoring simply because it was opened.
    for (auto* i : edit.getAllInputDevices()) for (auto t : i->getTargets()) i->setRecordingEnabled(t, false);
    for (auto* track : te::getAudioTracks(edit)) track->state.setProperty("emMonitorMode", "off", nullptr);
    data->restoreMonitorsOrDefaultOff({});
    data->applyPreferences();
}
juce::Result RecordingController::execute(const juce::String& command, const juce::var& args) {
    auto& s = *data; if (!s.edit) return graphError("No project is attached to the recorder.");
    if (!args.isObject()) return graphError("Recording arguments must be an object.");
    for (const auto* key : { "track_id", "input_device_id", "mode", "driver_type", "device_name", "input_device_name", "output_device_name" })
        if (args.hasProperty(key) && !args[key].isString()) return graphError(juce::String(key) + " must be a string.");
    if (command == "set_track_armed" && !args["armed"].isBool()) return graphError("armed must be a boolean.");
    for (const auto* key : { "sample_rate", "buffer_size" }) if (args.hasProperty(key) && (!args[key].isInt() && !args[key].isInt64() && !args[key].isDouble())) return graphError(juce::String(key) + " must be numeric.");
    if (args.hasProperty("buffer_size") && (!std::isfinite(double(args["buffer_size"])) || double(args["buffer_size"]) != std::floor(double(args["buffer_size"])))) return graphError("buffer_size must be an integer.");
    auto& transport = s.edit->getTransport();
    if (command == "stop_recording") {
        s.cancelled=s.countingIn();transport.stop(s.cancelled, false);
        s.edit->setClickTrackRange({});
        if(s.cancelled){s.activeTake=false;s.adopted=false;s.finishingInputs=0;s.error.clear();transport.setPosition(te::TimePosition::fromSeconds(s.punchTime));}
        return juce::Result::ok();
    }
    if (transport.isRecording() || transport.isRecordingStopping() || s.finishingInputs > 0 || s.activeTake) return graphError("Finish the current recording before changing inputs or the device.");
    if(command=="set_recording_preferences")return s.setPreferences(args);
    s.reconcile();
    if (command == "configure_audio_device") return s.configureDevice(args);
    if (command == "set_track_armed") {
        auto* track = graphTrack(*s.edit, args["track_id"].toString()); if (!track || track->state["emKind"].toString() == "bus") return graphError("Only audio and MIDI tracks can be armed.");
        if (!bool(args["armed"])) { for (auto* i : s.edit->getAllInputDevices()) i->setRecordingEnabled(track->itemID, false); return juce::Result::ok(); }
        return s.bind(*track, true);
    }
    if (command == "set_input_monitor") {
        const auto id = args["input_device_id"].toString(), mode = args["mode"].toString();
        if (mode != "off" && mode != "auto" && mode != "on") return graphError("Input monitor must be off, auto, or on.");
        if (args.hasProperty("track_id")) {
            auto* track = graphTrack(*s.edit, args["track_id"].toString());
            if (!track || track->state["emKind"].toString() == "bus") return graphError("Select an audio or MIDI track for monitoring.");
            const auto selected = s.selectedInput(*track);
            if (!s.device(selected)) return graphError("Selected recording input is unavailable.");
            if (mode != "off") {
                auto* input = s.instance(selected);
                const bool armed = input && input->isRecordingEnabled(track->itemID);
                if (auto r = s.bind(*track, armed); r.failed()) return r;
            }
            track->state.setProperty("emMonitorMode", mode, nullptr);
            te::TransportControl::restartAllTransports(s.engine, false);
            return juce::Result::ok();
        }
        if (mode != "off") for (auto* track : te::getAudioTracks(*s.edit)) if (s.selectedInput(*track) == id) {
            auto* i = s.instance(id); const bool armed = i && i->isRecordingEnabled(track->itemID);
            if (auto r = s.bind(*track, armed); r.failed()) return r;
        }
        auto* device = s.device(id); if (!device) return graphError("Input device not found.");
        for (auto* track : te::getAudioTracks(*s.edit)) if (s.selectedInput(*track) == id) track->state.setProperty("emMonitorMode", mode, nullptr);
        const auto previousMode = device->getMonitorMode();
        device->setMonitorMode(mode == "on" ? te::InputDevice::MonitorMode::on : mode == "auto" ? te::InputDevice::MonitorMode::automatic : te::InputDevice::MonitorMode::off);
        if (previousMode == device->getMonitorMode()) te::TransportControl::restartAllTransports(s.engine, false);
        return juce::Result::ok();
    }
    if (command == "start_recording") {
        bool armed = false; for (auto* input : s.edit->getAllInputDevices()) for (auto id : input->getTargets()) armed |= input->isRecordingEnabled(id);
        if (!armed) return graphError("Arm a track and choose its recording input first.");
        if (transport.looping) return graphError("Turn loop off before recording. This version records a linear take.");
        if (auto result = s.directory.createDirectory(); result.failed()) return graphError("Cannot create the recording directory: " + result.getErrorMessage());
        const auto takeName = "take-" + freshId() + "-%track%-%take%";
        for (auto* input : s.engine.getDeviceManager().getWaveInputDevices()) {
            bool used = false; if (auto* i = s.instance(input->getDeviceID())) for (auto id : i->getTargets()) used |= i->isRecordingEnabled(id);
            if (used) { input->setOutputFormat("WAV"); input->setBitDepth(24); input->setMergeMode(te::WaveInputDevice::getMergeModes()[0]); input->setFilenameMask(s.directory.getChildFile(takeName).getFullPathName()); }
        }
        for (const auto& input : s.engine.getDeviceManager().getMidiInDevices()) {
            bool used = false; if (auto* i = s.instance(input->getDeviceID())) for (auto id : i->getTargets()) used |= i->isRecordingEnabled(id);
            if (used) { input->mergeRecordings = false; input->replaceExistingClips = false; input->recordingEnabled = true; input->recordToNoteAutomation = false; }
        }
        s.error.clear();s.cancelled=false;s.punchTime=transport.getPosition().inSeconds();transport.record(false, false);
        if (!transport.isRecording()) return graphError("Recording could not start. Check the selected input and driver.");
        return juce::Result::ok();
    }
    return graphError("Unsupported recording command.");
}
juce::var RecordingController::state() const {
    const auto& s = *data; juce::Array<juce::var> tracks;
    if (s.edit) for (auto* track : te::getAudioTracks(*s.edit)) {
        const auto inputId = s.selectedInput(*track); auto* input = s.instance(inputId); auto* device = s.device(inputId);
        const auto overrideMode = track->state["emMonitorMode"].toString();
        tracks.add(graphObject({ {"track_id", track->state["emId"].toString()}, {"input_device_id", inputId}, {"armed", input && input->isRecordingEnabled(track->itemID)}, {"monitor", overrideMode.isNotEmpty() ? overrideMode : "off"}, {"input_available", device != nullptr} }));
    }
    const auto remaining=s.countingIn()?juce::jlimit(0.0,double(s.countBars*s.edit->tempoSequence.getTimeSig(0)->numerator),(s.punchTime-s.position())*s.edit->tempoSequence.getTempo(0)->getBpm()/60.0*s.edit->tempoSequence.getTimeSig(0)->denominator/4.0):0.0;
    return graphObject({ {"counting_in",s.countingIn()},{"count_in_beats_remaining",remaining},{"recording_start_seconds",s.punchTime}, {"recording", s.edit && s.edit->getTransport().isRecording()}, {"finalizing", s.edit && (s.edit->getTransport().isRecordingStopping() || s.finishingInputs > 0 || (s.activeTake && !s.edit->getTransport().isRecording()))}, {"error", s.error}, {"tracks", tracks}, {"recording_directory", s.directory.getFullPathName()}, {"monitor_scope", "track_and_input_device"} });
}
juce::var RecordingController::preferences() const {
    const auto& s=*data;
    return graphObject({{"metronome_enabled",s.metronomeEnabled},{"metronome_gain_db",s.gainDb},{"metronome_record_only",s.recordOnly},{"count_in_enabled",s.countEnabled},{"count_in_bars",s.countBars},{"scope","application"}});
}
juce::var RecordingController::inputs() const {
    juce::Array<juce::var> inputs;
    auto append = [&](te::InputDevice& d) { if (!d.isTrackDevice()) inputs.add(graphObject({ {"id", d.getDeviceID()}, {"name", d.getName()}, {"type", d.getType()}, {"midi", d.isMidi()}, {"enabled", d.isEnabled()}, {"monitor", State::monitor(d)} })); };
    for (auto* input : data->engine.getDeviceManager().getWaveInputDevices()) append(*input);
    for (const auto& input : data->engine.getDeviceManager().getMidiInDevices()) append(*input);
    return graphObject({ {"inputs", inputs} });
}
juce::var RecordingController::audioDevices(bool scan) const {
    auto& manager = data->engine.getDeviceManager().deviceManager; juce::Array<juce::var> drivers;
    for (auto* type : manager.getAvailableDeviceTypes()) {
        if (scan) type->scanForDevices();
        juce::Array<juce::var> inputNames, outputNames;
        for (const auto& name : type->getDeviceNames(true)) inputNames.add(name);
        for (const auto& name : type->getDeviceNames(false)) outputNames.add(name);
        drivers.add(graphObject({ {"driver_type", type->getTypeName()}, {"inputs", inputNames}, {"outputs", outputNames}, {"separate_inputs_and_outputs", type->hasSeparateInputsAndOutputs()} }));
    }
    juce::Array<juce::var> rates, sizes, inputChannels, outputChannels;
    auto* device = manager.getCurrentAudioDevice();
    if (device) {
        for (auto rate : device->getAvailableSampleRates()) rates.add(rate);
        for (auto size : device->getAvailableBufferSizes()) sizes.add(size);
        auto channels = device->getInputChannelNames(); for (int i = 0; i < channels.size(); ++i) inputChannels.add(graphObject({ {"index", i}, {"name", channels[i]}, {"active", device->getActiveInputChannels()[i]} }));
        channels = device->getOutputChannelNames(); for (int i = 0; i < channels.size(); ++i) outputChannels.add(graphObject({ {"index", i}, {"name", channels[i]}, {"active", device->getActiveOutputChannels()[i]} }));
    }
    const auto setup = manager.getAudioDeviceSetup();
    return graphObject({ {"drivers", drivers}, {"driver_type", manager.getCurrentAudioDeviceType()}, {"device_name", device ? device->getName() : juce::String()},
        {"input_device_name", setup.inputDeviceName}, {"output_device_name", setup.outputDeviceName},
        {"sample_rate", device ? device->getCurrentSampleRate() : 0.0}, {"buffer_size", device ? device->getCurrentBufferSizeSamples() : 0}, {"sample_rates", rates}, {"buffer_sizes", sizes},
        {"input_channels", inputChannels}, {"output_channels", outputChannels}, {"input_latency_samples", device ? device->getInputLatencyInSamples() : 0}, {"output_latency_samples", device ? device->getOutputLatencyInSamples() : 0} });
}
bool RecordingController::poll() {
    auto& s = *data; if (!s.edit) return false; s.reconcile();
    if (!s.activeTake || s.edit->getTransport().isRecording() || s.edit->getTransport().isRecordingStopping() || s.finishingInputs > 0) return false;
    s.activeTake = false; s.transactionStarted = false;
    const bool completed = s.adopted; s.adopted = false;
    if (!completed && s.error.isEmpty()) s.error = "Recording ended without any captured audio or MIDI.";
    return completed;
}
} // namespace production
