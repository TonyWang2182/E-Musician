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
    bool changingDevice = false;
    int finishingInputs = 0;
    bool metronomeEnabled=false, recordOnly=false, countEnabled=false, cancelled=false;
    std::map<juce::String, juce::String> monitorRebindAttempts;
    int countBars=1;
    float gainDb=-12;
    double punchTime=0;
    struct LivePreview {
        EngineSession::RecordingPreviewSnapshot view;
        juce::File file;
        te::RecordingThumbnailManager::Thumbnail::Ptr thumbnail;
    };
    // Only accessed/released on the message thread. The engine's writer owns
    // the other reference and publishes peak data through AudioThumbnail.
    std::vector<LivePreview> livePreviews;
    std::uint64_t takeSequence = 0;
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

    juce::String audioIdentity() const {
        auto& manager = engine.getDeviceManager().deviceManager;
        const auto setup = manager.getAudioDeviceSetup();
        return juce::JSON::toString(graphObject({{"driver", manager.getCurrentAudioDeviceType()}, {"input", setup.inputDeviceName}}), true);
    }
    juce::String publicId(te::InputDevice& input) const {
        auto* wave = dynamic_cast<te::WaveInputDevice*>(&input);
        if (!wave || wave->isTrackDevice()) return input.getDeviceID();
        juce::Array<juce::var> channels;
        auto* current = engine.getDeviceManager().deviceManager.getCurrentAudioDevice();
        const auto names = current ? current->getInputChannelNames() : juce::StringArray();
        for (const auto& channel : wave->getChannels())
            channels.add(graphObject({{"index", channel.indexInDevice}, {"name", names[channel.indexInDevice]}}));
        const auto identity = audioIdentity() + juce::JSON::toString(channels, true);
        return "audioin_" + juce::SHA256(identity.toRawUTF8(), identity.getNumBytesAsUTF8()).toHexString();
    }
    bool matches(const juce::String& id, te::InputDevice& input) const {
        if (id == publicId(input)) return true;
        // Old projects have only TE's hash("Input 1"), which cannot identify a
        // physical interface. Require re-selection instead of guessing a card.
        // Hosted regression fixtures are explicitly isolated from user hardware.
        return !input.isMidi() && engine.getDeviceManager().isHostedAudioDeviceInterfaceInUse()
            && id == input.getDeviceID();
    }
    bool physicalActive(te::InputDevice& input) const {
        auto* wave = dynamic_cast<te::WaveInputDevice*>(&input);
        if (!wave || wave->isTrackDevice()) return true;
        auto* current = engine.getDeviceManager().deviceManager.getCurrentAudioDevice();
        if (!current || !current->isOpen()) return false;
        const auto active = current->getActiveInputChannels();
        for (const auto& channel : wave->getChannels()) if (!active[channel.indexInDevice]) return false;
        return !wave->getChannels().empty();
    }
    te::InputDevice* device(const juce::String& id) const {
        for (auto* d : engine.getDeviceManager().getWaveInputDevices()) if (matches(id, *d)) return d;
        for (const auto& d : engine.getDeviceManager().getMidiInDevices()) if (d->getDeviceID() == id) return d.get();
        return nullptr;
    }
    static juce::String monitor(te::InputDevice& d) {
        switch (d.getMonitorMode()) { case te::InputDevice::MonitorMode::on: return "on"; case te::InputDevice::MonitorMode::automatic: return "auto"; default: return "off"; }
    }
    using MonitorModes = std::map<juce::String, te::InputDevice::MonitorMode>;
    MonitorModes monitorModes() const {
        MonitorModes modes;
        for (auto* input : engine.getDeviceManager().getWaveInputDevices()) modes[publicId(*input)] = input->getMonitorMode();
        for (const auto& input : engine.getDeviceManager().getMidiInDevices()) modes[input->getDeviceID()] = input->getMonitorMode();
        return modes;
    }
    void restoreMonitorsOrDefaultOff(const MonitorModes& previous) {
        const auto restore = [&](te::InputDevice& input) {
            const auto found = previous.find(publicId(input));
            input.setMonitorMode(found == previous.end() ? te::InputDevice::MonitorMode::off : found->second);
        };
        // Owners exist even when this Edit has no playback context/instances.
        // Enumerate the engine's existing inputs without opening new devices.
        for (auto* input : engine.getDeviceManager().getWaveInputDevices()) restore(*input);
        for (const auto& input : engine.getDeviceManager().getMidiInDevices()) restore(*input);
    }
    juce::String selectedInput(te::AudioTrack& track) const { return track.state.getChildWithName("EM_PRODUCTION")["inputDeviceId"].toString(); }
    te::InputDeviceInstance* instance(const juce::String& id) const {
        if (edit) for (auto* i : edit->getAllInputDevices()) if (matches(id, i->getInputDevice())) return i;
        return nullptr;
    }
    // A device change may destroy and replace input instances. Never retain a
    // device/instance pointer across setEnabled/dispatchPendingUpdates.
    juce::Result bind(te::AudioTrack& track, bool armed) {
        const auto id = selectedInput(track); auto* input = device(id);
        if (!input) return graphError("Selected recording input is unavailable or belongs to another audio device. Select an input again.");
        if (input->isMidi() != (track.state["emKind"].toString() == "instrument")) return graphError("Audio tracks need an audio input; MIDI tracks need a MIDI input.");
        if (!physicalActive(*input)) return graphError("Selected audio input is disabled in Audio Settings. Enable its physical input channels before monitoring or recording.");
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
        if (changingDevice || !edit || edit->getTransport().isRecording() || edit->getTransport().isRecordingStopping()) return;
        std::map<juce::String, bool> previousArms;
        for (auto* input : edit->getAllInputDevices()) for (auto target : input->getTargets()) {
            auto* track = dynamic_cast<te::AudioTrack*>(te::findTrackForID(*edit, target));
            if (!track || !matches(selectedInput(*track), input->getInputDevice()) || !physicalActive(input->getInputDevice())) {
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
            auto* selected = device(id);
            if (!selected || !physicalActive(*selected) || monitorRebindAttempts[trackId] == id) continue;
            // Try once for this selection; explicit arm/monitor changes retry.
            // Avoid repeatedly restarting the graph if a driver cannot open.
            monitorRebindAttempts[trackId] = id;
            if (auto result = bind(*track, wasArmed); result.failed()) error = result.getErrorMessage();
            else monitorRebindAttempts.erase(trackId);
        }
    }
    void refreshPreviews() {
        if (!edit || cancelled) { livePreviews.clear(); return; }
        auto& transport = edit->getTransport();
        if (activeTake && transport.isRecording() && !countingIn()) {
            const double end = position();
            for (auto* input : edit->getAllInputDevices()) {
                if (input->getInputDevice().isMidi() || input->getInputDevice().isTrackDevice()) continue;
                for (auto target : input->getTargets()) {
                    if (!input->isRecordingEnabled(target)) continue;
                    const auto file = input->getRecordingFile(target);
                    if (file == juce::File()) continue; // No filesystem stat/read here.
                    auto* track = dynamic_cast<te::AudioTrack*>(te::findTrackForID(*edit, target));
                    if (!track) continue;
                    const auto trackId = track->state["emId"].toString();
                    auto found = std::find_if(livePreviews.begin(), livePreviews.end(), [&](const auto& item) {
                        return item.file == file && item.view.trackId == trackId;
                    });
                    if (found == livePreviews.end()) {
                        LivePreview item;
                        item.view.id = juce::String(takeSequence) + ":" + trackId;
                        item.view.trackId = trackId;
                        item.file = file;
                        item.thumbnail = engine.getRecordingThumbnailManager().getThumbnailFor(file);
                        livePreviews.push_back(std::move(item));
                        found = std::prev(livePreviews.end());
                    }
                    auto& view = found->view;
                    view.timelineStart = input->getPunchInTime(target).inSeconds();
                    view.duration = std::max(0.0, end - view.timelineStart);
                    view.finalizing = false;
                    if (found->thumbnail) {
                        view.channels = found->thumbnail->thumb->getNumChannels();
                        // The thumbnail rounds up to 1024-sample peak cells. It
                        // is display coverage, never the take's exact duration.
                        view.availableDuration = std::min(view.duration, found->thumbnail->thumb->getTotalLength());
                    }
                }
            }
        }
        for (auto& preview : livePreviews) {
            auto& view = preview.view;
            view.finalizing = view.clipId.isEmpty() && (!transport.isRecording() || transport.isRecordingStopping());
            if (view.clipId.isNotEmpty()) {
                te::WaveAudioClip* completed = nullptr;
                for (auto* track : te::getAudioTracks(*edit)) {
                    if (track->state["emId"].toString() != view.trackId) continue;
                    for (auto* clip : track->getClips())
                        if (clip->state["emId"].toString() == view.clipId)
                            completed = dynamic_cast<te::WaveAudioClip*>(clip);
                }
                if (!completed || completed->getOriginalFile() != preview.file) {
                    preview.thumbnail = nullptr; // Undo/remove/replace invalidated this take.
                    continue;
                }
                const auto position = completed->getPosition();
                view.timelineStart = position.time.getStart().inSeconds();
                view.duration = position.time.getLength().inSeconds();
                view.sourceOffset = position.offset.inSeconds();
            }
            if (preview.thumbnail)
                view.availableDuration = std::min(view.sourceOffset + view.duration,
                                                  preview.thumbnail->thumb->getTotalLength());
        }
        std::erase_if(livePreviews, [](const auto& preview) { return preview.thumbnail == nullptr; });
    }
    void recordingStarted(te::SyncPoint start, std::optional<te::TimeRange>) override {
        punchTime=start.time.inSeconds();cancelled=false;
        livePreviews.clear(); ++takeSequence;
        activeTake = true; adopted = false; transactionStarted = false; finishingInputs = 0; error.clear();
    }
    void recordingAboutToStop(te::InputDeviceInstance&, te::EditItemID) override {
        refreshPreviews();
        if (edit && !cancelled && !transactionStarted) { edit->getUndoManager().beginNewTransaction("Record take"); transactionStarted = true; }
        ++finishingInputs;
    }
    void recordingFinished(te::InputDeviceInstance&, te::EditItemID target, const juce::ReferenceCountedArray<te::Clip>& clips) override {
        if (!edit || cancelled) { finishingInputs=std::max(0,finishingInputs-1);return; } auto* um = &edit->getUndoManager();
        for (auto* clip : clips) {
            if (clip->state["emId"].toString().isEmpty()) clip->state.setProperty("emId", freshId(), um);
            if (auto* audio = dynamic_cast<te::WaveAudioClip*>(clip)) {
                const auto file = audio->getOriginalFile();
                if (!file.existsAsFile()) { error = "Recording ended without a readable audio file."; continue; }
                clip->state.setProperty("emKind", "audio", um);
                clip->state.setProperty("emAsset", freshId(), um);
                clip->state.setProperty("emSource", file.getFullPathName(), um);
                auto* targetTrack = te::findTrackForID(*edit, target);
                const auto targetTrackId = targetTrack ? targetTrack->state["emId"].toString() : juce::String();
                for (auto& preview : livePreviews) if (preview.file == file && preview.view.trackId == targetTrackId) {
                    const auto position = clip->getPosition();
                    preview.view.clipId = clip->state["emId"].toString();
                    preview.view.timelineStart = position.time.getStart().inSeconds();
                    preview.view.duration = position.time.getLength().inSeconds();
                    preview.view.sourceOffset = position.offset.inSeconds();
                    preview.view.finalizing = false;
                }
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
    juce::BigInteger stereoPairs() const {
        juce::BigInteger result;
        auto& manager = engine.getDeviceManager();
        if (auto* current = manager.deviceManager.getCurrentAudioDevice())
            for (int i = 0; i + 1 < current->getInputChannelNames().size(); i += 2)
                if (manager.isDeviceInChannelStereo(i)) result.setBit(i);
        return result;
    }
    void applyStereoPairs(const juce::BigInteger& pairs) {
        auto& manager = engine.getDeviceManager();
        if (auto* current = manager.deviceManager.getCurrentAudioDevice()) {
            const auto count = current->getInputChannelNames().size();
            for (int i = 0; i < count; i += 2) manager.setDeviceInChannelStereo(i, pairs[i]);
        }
        manager.rescanWaveDeviceList();
        manager.dispatchPendingUpdates();
    }
    void refreshInputs(const MonitorModes& previous) {
        auto& manager = engine.getDeviceManager();
        manager.rescanWaveDeviceList();
        manager.dispatchPendingUpdates();
        restoreMonitorsOrDefaultOff(previous);
        monitorRebindAttempts.clear();
        if (edit) edit->dispatchPendingUpdatesSynchronously();
    }
    struct AudioBinding { juce::String trackId, inputId; bool armed = false; };
    using AudioBindings = std::vector<AudioBinding>;
    AudioBindings suspendAudioBindings() {
        AudioBindings bindings;
        if (!edit) return bindings;
        for (auto* input : edit->getAllInputDevices()) {
            if (input->getInputDevice().isMidi() || input->getInputDevice().isTrackDevice()) continue;
            for (auto target : input->getTargets()) {
                if (auto* track = dynamic_cast<te::AudioTrack*>(te::findTrackForID(*edit, target)))
                    bindings.push_back({track->state["emId"].toString(), selectedInput(*track), input->isRecordingEnabled(target)});
                input->setRecordingEnabled(target, false);
                auto ignored = input->removeTarget(target, nullptr); juce::ignoreUnused(ignored);
            }
        }
        // Publish the disconnected graph before a native driver can start its
        // callback or nested message loop. Name-hashed TE IDs must never route
        // a replacement card through a previous card's live/armed targets.
        edit->restartPlayback();
        edit->dispatchPendingUpdatesSynchronously();
        return bindings;
    }
    void restoreAudioBindings(const AudioBindings& bindings) {
        if (!edit) return;
        for (const auto& previous : bindings) {
            auto* track = graphTrack(*edit, previous.trackId);
            if (!track || selectedInput(*track) != previous.inputId) continue;
            auto* current = device(previous.inputId);
            if (!current || !physicalActive(*current)) continue;
            if (previous.armed || track->state["emMonitorMode"].toString() == "on")
                if (auto result = bind(*track, previous.armed); result.failed()) error = result.getErrorMessage();
        }
        edit->dispatchPendingUpdatesSynchronously();
    }
    juce::Result configureDevice(const juce::var& args) {
        if (edit && edit->getTransport().isPlaying()) return graphError("Stop playback before changing the audio device.");
        juce::BigInteger requestedChannels, requestedPairs;
        if (args.hasProperty("input_channels"))
            if (auto r = audio_config::parseIndices(args["input_channels"], "input_channels", requestedChannels); r.failed()) return r;
        if (args.hasProperty("input_stereo_pairs"))
            if (auto r = audio_config::parseIndices(args["input_stereo_pairs"], "input_stereo_pairs", requestedPairs, true); r.failed()) return r;
        if ((args.hasProperty("sample_rate") && (!std::isfinite(double(args["sample_rate"])) || double(args["sample_rate"]) < 8000 || double(args["sample_rate"]) > 384000))
            || (args.hasProperty("buffer_size") && (double(args["buffer_size"]) < 16 || double(args["buffer_size"]) > 8192)))
            return graphError("Invalid sample rate or buffer size.");
        auto& manager = engine.getDeviceManager().deviceManager;
        const auto beforeType = manager.getCurrentAudioDeviceType();
        const auto before = manager.getAudioDeviceSetup();
        const auto beforePairs = stereoPairs();
        const auto previousMonitorModes = monitorModes();
        const auto wantedType = args.getProperty("driver_type", beforeType).toString();
        juce::AudioIODeviceType* wantedDriver = nullptr;
        for (auto* type : manager.getAvailableDeviceTypes()) if (type->getTypeName() == wantedType) wantedDriver = type;
        if (!wantedDriver) return graphError("Audio driver type is unavailable in this build: " + wantedType);
        // Prevent a native driver's nested message loop from reconciling the
        // Edit while its input objects are being destroyed/replaced.
        juce::Result result = juce::Result::ok();
        AudioBindings previousBindings;
        {
            const juce::ScopedValueSetter<bool> guard(changingDevice, true);
            previousBindings = suspendAudioBindings();
            auto rollback = [&](const juce::String& failure) {
                manager.setCurrentAudioDeviceType(beforeType, true);
                auto restoreSetup = before;
                // Candidate masks update JUCE's mutable default channel counts.
                // Restoring useDefault=true could therefore reopen a different
                // mask even when the saved setup previously represented zero.
                restoreSetup.useDefaultInputChannels = false;
                restoreSetup.useDefaultOutputChannels = false;
                auto restore = manager.setAudioDeviceSetup(restoreSetup, true);
                if (restore.isEmpty()) {
                    auto* restored = manager.getCurrentAudioDevice();
                    if (!restored || !restored->isOpen() || manager.getCurrentAudioDeviceType() != beforeType
                        || manager.getAudioDeviceSetup().inputDeviceName != before.inputDeviceName
                        || manager.getAudioDeviceSetup().outputDeviceName != before.outputDeviceName
                        || restored->getActiveInputChannels() != before.inputChannels
                        || restored->getActiveOutputChannels() != before.outputChannels
                        || std::abs(restored->getCurrentSampleRate() - before.sampleRate) > 0.01
                        || restored->getCurrentBufferSizeSamples() != before.bufferSize)
                        restore = "The driver did not restore the previous device configuration.";
                }
                applyStereoPairs(beforePairs);
                refreshInputs(previousMonitorModes);
                return graphError(failure + (restore.isEmpty() ? " Previous device configuration restored." : " Restore failed: " + restore));
            };
            result = [&]() -> juce::Result {
                manager.setCurrentAudioDeviceType(wantedType, true);
                auto setup = manager.getAudioDeviceSetup();
                if (args.hasProperty("device_name")) setup.inputDeviceName = setup.outputDeviceName = args["device_name"].toString();
                if (args.hasProperty("input_device_name")) setup.inputDeviceName = args["input_device_name"].toString();
                if (args.hasProperty("output_device_name")) setup.outputDeviceName = args["output_device_name"].toString();
                if (!wantedDriver->hasSeparateInputsAndOutputs() && setup.inputDeviceName.isNotEmpty()
                    && setup.outputDeviceName.isNotEmpty() && setup.inputDeviceName != setup.outputDeviceName)
                    return rollback("This audio driver uses one device for input and output. Set device_name or choose matching input and output device names.");
                const bool newInput = wantedType != beforeType || setup.inputDeviceName != before.inputDeviceName;
                const bool newOutput = wantedType != beforeType || setup.outputDeviceName != before.outputDeviceName;
                const bool newDevice = newInput || newOutput;
                if (newDevice) { setup.sampleRate = 0; setup.bufferSize = 0; }
                if (args.hasProperty("sample_rate")) setup.sampleRate = double(args["sample_rate"]);
                if (args.hasProperty("buffer_size")) setup.bufferSize = int(args["buffer_size"]);
                // JUCE's "default" count is mutable and can stay zero after
                // output-only startup. Always submit a deliberate physical mask.
                setup.useDefaultInputChannels = false;
                setup.useDefaultOutputChannels = false;
                setup.inputChannels = args.hasProperty("input_channels") ? requestedChannels
                    : newInput ? audio_config::defaultInputs(2) : before.inputChannels;
                setup.outputChannels = newOutput ? audio_config::defaultInputs(2) : before.outputChannels;
                if (setup.inputDeviceName.isEmpty()) setup.inputChannels.clear();
                if (setup.outputDeviceName.isEmpty()) setup.outputChannels.clear();
                auto failure = manager.setAudioDeviceSetup(setup, true);
                if (failure.isNotEmpty()) return rollback(failure);
                auto* opened = manager.getCurrentAudioDevice();
                if (!opened || !opened->isOpen()) return rollback("Audio driver did not open a device.");
                const auto count = opened->getInputChannelNames().size();
                const auto desired = args.hasProperty("input_channels") ? requestedChannels
                    : newInput ? audio_config::defaultInputs(setup.inputDeviceName.isEmpty() ? 0 : count) : before.inputChannels;
                if (auto r = audio_config::validateAvailable(desired, count); r.failed()) return rollback(r.getErrorMessage());
                if (opened->getActiveInputChannels() != desired) {
                    // Some drivers clamp the provisional two-channel default.
                    // Retry the exact device-bounded mask, then require readback.
                    auto exact = manager.getAudioDeviceSetup();
                    exact.useDefaultInputChannels = false; exact.inputChannels = desired;
                    failure = manager.setAudioDeviceSetup(exact, true);
                    if (failure.isNotEmpty()) return rollback(failure);
                    opened = manager.getCurrentAudioDevice();
                }
                if (!opened || !opened->isOpen() || opened->getActiveInputChannels() != desired)
                    return rollback("The audio driver did not accept the requested input channels.");
                if (args.hasProperty("sample_rate") && std::abs(opened->getCurrentSampleRate() - double(args["sample_rate"])) > 0.01)
                    return rollback("The audio driver did not accept the requested sample rate.");
                if (args.hasProperty("buffer_size") && opened->getCurrentBufferSizeSamples() != int(args["buffer_size"]))
                    return rollback("The audio driver did not accept the requested buffer size.");
                auto pairs = args.hasProperty("input_stereo_pairs") ? requestedPairs : newInput ? juce::BigInteger() : beforePairs;
                for (int i = pairs.findNextSetBit(0); i >= 0; i = pairs.findNextSetBit(i + 1)) {
                    if (i + 1 < count && desired[i] && desired[i + 1]) continue;
                    if (args.hasProperty("input_stereo_pairs")) return rollback("A stereo input pair requires both physical channels to be available and enabled.");
                    pairs.clearBit(i); // Disabling one channel restores this pair's mono inputs.
                }
                applyStereoPairs(pairs);
                refreshInputs(previousMonitorModes);
                return juce::Result::ok();
            }();
        }
        if (result.wasOk()) error.clear();
        restoreAudioBindings(previousBindings);
        reconcile();
        return result;
    }
    juce::Result showDriverPanel() {
        if (edit && edit->getTransport().isPlaying()) return graphError("Stop playback before opening the audio driver control panel.");
        auto& manager = engine.getDeviceManager().deviceManager;
        {
            auto* current = manager.getCurrentAudioDevice();
            if (!current || !current->isOpen()) return graphError("Open an audio device before opening its control panel.");
            if (!current->hasControlPanel()) return graphError("This audio driver does not provide a control panel.");
        }
        const auto previousMonitorModes = monitorModes();
        AudioBindings previousBindings;
        {
            const juce::ScopedValueSetter<bool> guard(changingDevice, true);
            previousBindings = suspendAudioBindings();
            // A panel can run a nested native message loop. Never retain its
            // device pointer after the call, including for restart/readback.
            const bool needsRestart = [&] {
                auto* current = manager.getCurrentAudioDevice();
                return current && current->isOpen() && current->hasControlPanel() && current->showControlPanel();
            }();
            if (needsRestart && manager.getCurrentAudioDevice()) {
                manager.closeAudioDevice();
                manager.restartLastAudioDevice();
            }
            refreshInputs(previousMonitorModes);
        }
        error.clear();
        restoreAudioBindings(previousBindings);
        reconcile();
        auto* current = manager.getCurrentAudioDevice();
        if (!current || !current->isOpen()) return graphError("The audio device is unavailable after closing its driver control panel. Reopen it in Audio Settings.");
        return juce::Result::ok();
    }
};

RecordingController::RecordingController(te::Engine& e) : data(std::make_unique<State>(e)) {}
RecordingController::~RecordingController() { detach(); }
void RecordingController::detach() {
    data->livePreviews.clear();
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
    if (s.changingDevice) return graphError("The audio driver is busy changing its device configuration.");
    if (!args.isObject()) return graphError("Recording arguments must be an object.");
    for (const auto* key : { "track_id", "input_device_id", "mode", "driver_type", "device_name", "input_device_name", "output_device_name" })
        if (args.hasProperty(key) && !args[key].isString()) return graphError(juce::String(key) + " must be a string.");
    if (command == "set_track_armed" && !args["armed"].isBool()) return graphError("armed must be a boolean.");
    for (const auto* key : { "sample_rate", "buffer_size" }) if (args.hasProperty(key) && (!args[key].isInt() && !args[key].isInt64() && !args[key].isDouble())) return graphError(juce::String(key) + " must be numeric.");
    if (args.hasProperty("buffer_size") && (!std::isfinite(double(args["buffer_size"])) || double(args["buffer_size"]) != std::floor(double(args["buffer_size"])))) return graphError("buffer_size must be an integer.");
    auto& transport = s.edit->getTransport();
    if (command == "stop_recording") {
        s.refreshPreviews();
        s.cancelled=s.countingIn();transport.stop(s.cancelled, false);
        s.edit->setClickTrackRange({});
        if(s.cancelled){s.livePreviews.clear();s.activeTake=false;s.adopted=false;s.finishingInputs=0;s.error.clear();transport.setPosition(te::TimePosition::fromSeconds(s.punchTime));}
        return juce::Result::ok();
    }
    if (transport.isRecording() || transport.isRecordingStopping() || s.finishingInputs > 0 || s.activeTake) return graphError("Finish the current recording before changing inputs or the device.");
    if(command=="set_recording_preferences")return s.setPreferences(args);
    s.reconcile();
    if (command == "configure_audio_device") return s.configureDevice(args);
    if (command == "show_audio_driver_panel") return s.showDriverPanel();
    if (command == "set_track_armed") {
        auto* track = graphTrack(*s.edit, args["track_id"].toString()); if (!track || track->state["emKind"].toString() == "bus") return graphError("Only audio and MIDI tracks can be armed.");
        if (!bool(args["armed"])) { for (auto* i : s.edit->getAllInputDevices()) i->setRecordingEnabled(track->itemID, false); return juce::Result::ok(); }
        return s.bind(*track, true);
    }
    if (command == "set_input_monitor") {
        const auto id = args["input_device_id"].toString(), requestedMode = args["mode"].toString();
        if (requestedMode != "off" && requestedMode != "auto" && requestedMode != "on") return graphError("Input monitor must be off or on.");
        // Legacy Auto requests resolve safely to Off. Record-arm no longer
        // grants live monitoring; the user must explicitly choose On.
        const juce::String mode = requestedMode == "on" ? "on" : "off";
        te::AudioTrack* track = nullptr;
        if (args.hasProperty("track_id")) {
            track = graphTrack(*s.edit, args["track_id"].toString());
            if (!track || track->state["emKind"].toString() == "bus") return graphError("Select an audio or MIDI track for monitoring.");
            if (args.hasProperty("input_device_id") && id != s.selectedInput(*track))
                return graphError("The input device does not belong to the selected track.");
        } else {
            // Compatibility with old clients is deliberately unambiguous:
            // device identity may resolve one track, never a device-wide toggle.
            for (auto* candidate : te::getAudioTracks(*s.edit)) if (s.selectedInput(*candidate) == id) {
                if (track) return graphError("This input is shared by multiple tracks. Specify track_id to change monitoring.");
                track = candidate;
            }
            if (!track) return graphError("Select a track assigned to this recording input first.");
        }
        const auto selected = s.selectedInput(*track);
        if (mode == "on") {
            if (!s.device(selected)) return graphError("Selected recording input is unavailable.");
            auto* input = s.instance(selected);
            const bool armed = input && input->isRecordingEnabled(track->itemID);
            if (auto r = s.bind(*track, armed); r.failed()) return r;
        }
        if (mode != "on" && track->state["emMonitorMode"].toString() == "on")
            if (auto* input = s.instance(selected)) input->releaseLiveMidiForTarget(track->itemID);
        if (track->state["emMonitorMode"].toString() != mode) {
            track->state.setProperty("emMonitorMode", mode, nullptr);
            // Rebuild this Edit only; never change the shared physical input's
            // monitor mode or touch another Edit's transport/recording state.
            s.edit->restartPlayback();
            // Publish the new graph before this command returns. Deferring to
            // Edit's timer lets a subsequent MIDI block enter the old On graph
            // after its held-note cleanup, leaving an unpaired voice at Off.
            s.edit->dispatchPendingUpdatesSynchronously();
        }
        return juce::Result::ok();
    }
    if (command == "start_recording") {
        bool armed = false;
        for (auto* input : s.edit->getAllInputDevices()) for (auto id : input->getTargets()) if (input->isRecordingEnabled(id)) {
            if (!s.physicalActive(input->getInputDevice())) return graphError("An armed audio input is disabled in Audio Settings.");
            auto* track = dynamic_cast<te::AudioTrack*>(te::findTrackForID(*s.edit, id));
            if (!track || !s.matches(s.selectedInput(*track), input->getInputDevice())) return graphError("An armed input belongs to another audio device. Select its recording input again.");
            armed = true;
        }
        if (!armed) return graphError("Arm a track and choose its recording input first.");
        if (transport.looping) return graphError("Turn loop off before recording. This version records a linear take.");
        if (auto result = s.directory.createDirectory(); result.failed()) return graphError("Cannot create the recording directory: " + result.getErrorMessage());
        const auto takeName = "take-" + freshId() + "-%track%-%take%";
        for (auto* input : s.engine.getDeviceManager().getWaveInputDevices()) {
            bool used = false; if (auto* i = s.instance(s.publicId(*input))) for (auto id : i->getTargets()) used |= i->isRecordingEnabled(id);
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
        tracks.add(graphObject({ {"track_id", track->state["emId"].toString()}, {"input_device_id", inputId}, {"armed", input && input->isRecordingEnabled(track->itemID)}, {"monitor", overrideMode.isNotEmpty() ? overrideMode : "off"}, {"input_available", device != nullptr}, {"physical_active", device && s.physicalActive(*device)} }));
    }
    const auto remaining=s.countingIn()?juce::jlimit(0.0,double(s.countBars*s.edit->tempoSequence.getTimeSig(0)->numerator),(s.punchTime-s.position())*s.edit->tempoSequence.getTempo(0)->getBpm()/60.0*s.edit->tempoSequence.getTimeSig(0)->denominator/4.0):0.0;
    return graphObject({ {"counting_in",s.countingIn()},{"count_in_beats_remaining",remaining},{"recording_start_seconds",s.punchTime}, {"recording", s.edit && s.edit->getTransport().isRecording()}, {"finalizing", s.edit && (s.edit->getTransport().isRecordingStopping() || s.finishingInputs > 0 || (s.activeTake && !s.edit->getTransport().isRecording()))}, {"error", s.error}, {"tracks", tracks}, {"recording_directory", s.directory.getFullPathName()}, {"monitor_scope", "track"} });
}
juce::var RecordingController::preferences() const {
    const auto& s=*data;
    return graphObject({{"metronome_enabled",s.metronomeEnabled},{"metronome_gain_db",s.gainDb},{"metronome_record_only",s.recordOnly},{"count_in_enabled",s.countEnabled},{"count_in_bars",s.countBars},{"scope","application"}});
}
juce::var RecordingController::inputs() const {
    juce::Array<juce::var> inputs;
    auto append = [&](te::InputDevice& d) {
        if (d.isTrackDevice()) return;
        juce::Array<juce::var> channels;
        if (auto* wave = dynamic_cast<te::WaveInputDevice*>(&d))
            for (const auto& channel : wave->getChannels()) channels.add(channel.indexInDevice);
        inputs.add(graphObject({ {"id", data->publicId(d)}, {"engine_id", d.getDeviceID()}, {"name", d.getName()}, {"type", d.getType()},
            {"midi", d.isMidi()}, {"enabled", d.isEnabled()}, {"monitor", State::monitor(d)}, {"physical_active", data->physicalActive(d)},
            {"available", data->physicalActive(d)}, {"channels", channels}, {"stereo", channels.size() == 2} }));
    };
    for (auto* input : data->engine.getDeviceManager().getWaveInputDevices()) append(*input);
    for (const auto& input : data->engine.getDeviceManager().getMidiInDevices()) append(*input);
    return graphObject({ {"inputs", inputs} });
}
te::InputDevice* RecordingController::inputForId(const juce::String& id) const { return data->device(id); }
std::vector<EngineSession::RecordingPreviewSnapshot> RecordingController::previews() {
    data->refreshPreviews();
    std::vector<EngineSession::RecordingPreviewSnapshot> result;
    result.reserve(data->livePreviews.size());
    for (const auto& preview : data->livePreviews) result.push_back(preview.view);
    return result;
}
bool RecordingController::drawPreview(const juce::String& id, juce::Graphics& graphics,
                                       juce::Rectangle<int> area, double start, double end, float zoom) const {
    if (area.isEmpty() || !std::isfinite(start) || !std::isfinite(end) || end <= start || start < 0
        || !std::isfinite(zoom) || zoom <= 0) return false;
    for (const auto& preview : data->livePreviews) {
        if (preview.view.id != id || !preview.thumbnail) continue;
        const double available = std::min(preview.view.sourceOffset + preview.view.duration,
                                          preview.thumbnail->thumb->getTotalLength());
        if (start >= available) return false;
        const auto clippedEnd = std::min(end, available);
        if (clippedEnd < end)
            area.setWidth(juce::jmax(1, juce::roundToInt(area.getWidth() * (clippedEnd - start) / (end - start))));
        juce::Graphics::ScopedSaveState clip(graphics);
        graphics.reduceClipRegion(area);
        const auto visible = graphics.getClipBounds().getIntersection(area);
        const auto channels = preview.thumbnail->thumb->getNumChannels();
        // Read only the writer-published peak store. AudioThumbnail's generic
        // drawing path may choose a source reader at high zoom; a live take's
        // WAV header is not final yet, and painting must never depend on it.
        // Restrict work to visible pixels and keep constant/silent PCM visible
        // as a thin line rather than treating a zero-height range as no data.
        for (int channel = 0; channel < channels; ++channel) {
            const float top = float(area.getY()) + float(channel * area.getHeight()) / float(channels);
            const float bottom = float(area.getY()) + float((channel + 1) * area.getHeight()) / float(channels);
            const float centre = (top + bottom) * 0.5f;
            const float scale = zoom * (bottom - top) * 0.5f;
            for (int x = visible.getX(); x < visible.getRight(); ++x) {
                const double from = start + (clippedEnd - start) * double(x - area.getX()) / double(area.getWidth());
                const double to = start + (clippedEnd - start) * double(x + 1 - area.getX()) / double(area.getWidth());
                float low = 0, high = 0;
                preview.thumbnail->thumb->getApproximateMinMax(from, to, channel, low, high);
                if (!std::isfinite(low) || !std::isfinite(high) || high < low) continue;
                const float y1 = juce::jlimit(top, bottom, centre - high * scale - 0.5f);
                const float y2 = juce::jlimit(top, bottom, centre - low * scale + 0.5f);
                graphics.fillRect(float(x), y1, 1.0f, std::max(0.0f, y2 - y1));
            }
        }
        return true;
    }
    return false;
}
void RecordingController::releasePreview(const juce::String& id) {
    std::erase_if(data->livePreviews, [&](const auto& preview) {
        return preview.view.id == id && preview.view.clipId.isNotEmpty();
    });
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
        {"input_channels", inputChannels}, {"output_channels", outputChannels},
        {"active_input_channels", device ? audio_config::indices(device->getActiveInputChannels()) : juce::Array<juce::var>()},
        {"input_stereo_pairs", audio_config::indices(data->stereoPairs())}, {"device_open", device && device->isOpen()}, {"has_control_panel", device && device->isOpen() && device->hasControlPanel()},
        {"input_latency_samples", device ? device->getInputLatencyInSamples() : 0}, {"output_latency_samples", device ? device->getOutputLatencyInSamples() : 0} });
}
bool RecordingController::poll() {
    auto& s = *data; if (!s.edit || s.changingDevice) return false; s.reconcile();
    if (!s.activeTake || s.edit->getTransport().isRecording() || s.edit->getTransport().isRecordingStopping() || s.finishingInputs > 0) return false;
    s.activeTake = false; s.transactionStarted = false;
    const bool completed = s.adopted; s.adopted = false;
    // A failed/cancelled input must not leave a finalising rectangle behind
    // merely because a different input in the same take succeeded.
    std::erase_if(s.livePreviews, [](const auto& preview) { return preview.view.clipId.isEmpty(); });
    if (!completed && s.error.isEmpty()) s.error = "Recording ended without any captured audio or MIDI.";
    return completed;
}
} // namespace production
