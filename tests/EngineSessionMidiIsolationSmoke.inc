// Included inside runProductionSmokeTest's try block. This is an actual hosted
// audio graph test: a diagnostic MIDI instrument renders one fixed level per
// active voice so left/right PCM proves routing, rather than echoing state flags.
// It is a test instrument, not an advertised native device or physical-I/O test.
{
    class MidiIsolationProbe final : public te::Plugin {
    public:
        explicit MidiIsolationProbe(te::PluginCreationInfo info) : te::Plugin(info) {}
        ~MidiIsolationProbe() override { notifyListenersOfDeletion(); }
        juce::String getName() const override { return "MIDI isolation probe"; }
        juce::String getPluginType() override { return "em_test_midi_isolation"; }
        juce::String getSelectableDescription() override { return getName(); }
        bool isSynth() override { return true; }
        bool takesMidiInput() override { return true; }
        bool producesAudioWhenNoAudioInput() override { return true; }
        int getNumOutputChannelsGivenInputs(int) override { return 2; }
        void initialise(const te::PluginInitialisationInfo&) override {}
        void deinitialise() override {}
        void reset() override { for (auto& voice : voices) voice = {}; pedals = {}; }
        void midiPanic() override { ++panicCount; reset(); }
        struct Voice { int channel = 0, note = 0; te::MPESourceID source = 0; bool active = false, held = false; };
        std::array<Voice, 64> voices {};
        std::array<bool, 16> pedals {};
        int noteOns = 0, noteOffs = 0, panicCount = 0, channelModeCount = 0, pedalReleases = 0, renderedBlocks = 0;
        void applyToBuffer(const te::PluginRenderContext& c) override {
            ++renderedBlocks;
            if (c.bufferForMidiMessages) for (const auto& m : *c.bufferForMidiMessages) {
                const int ch = m.getChannel();
                if (ch < 1 || ch > 16) continue;
                if (m.isNoteOn()) {
                    ++noteOns;
                    for (auto& v : voices) if (!v.active) { v = { ch, m.getNoteNumber(), m.mpeSourceID, true, true }; break; }
                } else if (m.isNoteOff()) {
                    ++noteOffs;
                    for (auto& v : voices) if (v.active && v.channel == ch && v.note == m.getNoteNumber() && v.source == m.mpeSourceID) {
                        v.held = false; if (!pedals[std::size_t(ch - 1)]) v.active = false;
                    }
                } else if (m.isController() && m.getControllerNumber() == 64) {
                    pedals[std::size_t(ch - 1)] = m.getControllerValue() >= 64;
                    if (!pedals[std::size_t(ch - 1)]) { ++pedalReleases; for (auto& v : voices) if (v.channel == ch && !v.held) v.active = false; }
                } else if (m.isAllNotesOff() || m.isAllSoundOff()) { ++channelModeCount; reset(); }
            }
            if (auto* audio = c.destBuffer) {
                float value = 0; for (const auto& v : voices) if (v.active) value += 0.025f;
                for (int ch = 0; ch < audio->getNumChannels(); ++ch)
                    for (int n = c.bufferStartSample; n < c.bufferStartSample + c.bufferNumSamples; ++n) audio->setSample(ch, n, value);
            }
            if (c.bufferForMidiMessages) c.bufferForMidiMessages->clear();
        }
        int sounding(int note) const { int count = 0; for (const auto& v : voices) if (v.active && v.note == note) ++count; return count; }
    };
    struct MidiIsolationProbeFactory final : te::PluginManager::BuiltInType {
        MidiIsolationProbeFactory() : te::PluginManager::BuiltInType("em_test_midi_isolation") {}
        te::Plugin::Ptr create(te::PluginCreationInfo info) override { return new MidiIsolationProbe(info); }
    };
    okay(directory.createDirectory(), "create MIDI matrix diagnostics directory");
    EngineSession matrix(false);
    auto& matrixEngine = matrix.impl->engine;
    matrixEngine.getPluginManager().registerBuiltInType(std::make_unique<MidiIsolationProbeFactory>());
    struct MatrixHostedScope { te::Engine& e; ~MatrixHostedScope() { e.getDeviceManager().deviceManager.closeAudioDevice(); e.getDeviceManager().removeHostedAudioDeviceInterface(); } } matrixHostedScope { matrixEngine };
    auto& matrixHosted = matrixEngine.getDeviceManager().getHostedAudioDeviceInterface();
    te::HostedAudioDeviceInterface::Parameters matrixParameters;
    matrixParameters.sampleRate = 48000; matrixParameters.blockSize = 256;
    matrixParameters.inputChannels = 0; matrixParameters.outputChannels = 2; matrixParameters.useMidiDevices = false;
    matrixHosted.initialise(matrixParameters); matrixHosted.prepareToPlay(48000, 256); matrixEngine.getDeviceManager().dispatchPendingUpdates();
    command(matrix, "create_track", object({ {"kind", "instrument"}, {"name", "Left MIDI"} }));
    command(matrix, "create_track", object({ {"kind", "instrument"}, {"name", "Right MIDI"} }));
    const auto leftId = matrix.snapshot().tracks[0].id, rightId = matrix.snapshot().tracks[1].id;
    juce::String matrixMidiId;
    for (const auto& d : matrixEngine.getDeviceManager().getMidiInDevices()) if (te::HostedAudioDeviceInterface::isHostedMidiInputDevice(*d)) matrixMidiId = d->getDeviceID();
    check(matrixMidiId.isNotEmpty(), "matrix hosted input exists");
    command(matrix, "set_track_input", object({ {"track_id", leftId}, {"input_device_id", matrixMidiId} }));
    command(matrix, "set_track_input", object({ {"track_id", rightId}, {"input_device_id", matrixMidiId} }));
    command(matrix, "set_track_pan", object({ {"track_id", leftId}, {"pan", -1.0} }));
    command(matrix, "set_track_pan", object({ {"track_id", rightId}, {"pan", 1.0} }));
    command(matrix, "set_recording_preferences", object({ {"count_in_enabled", false}, {"metronome_enabled", false} }));
    auto* matrixEdit = matrix.impl->edit.get();
    auto& matrixRecorder = matrix.impl->recording;
    matrixRecorder.attach(*matrixEdit, directory.getChildFile("midi-isolation-takes"));
    const auto addProbe = [&](const juce::String& id) {
        auto* t = production::graphTrack(*matrixEdit, id);
        auto plugin = matrixEdit->getPluginCache().createNewPlugin("em_test_midi_isolation", {});
        check(plugin != nullptr, "diagnostic instrument created through real Edit plugin cache");
        t->pluginList.insertPlugin(plugin, 0, nullptr);
        check(t->pluginList.contains(plugin.get()), "diagnostic instrument is actually attached to the track graph");
        return plugin;
    };
    auto leftHeld = addProbe(leftId), rightHeld = addProbe(rightId);
    auto* leftProbe = dynamic_cast<MidiIsolationProbe*>(leftHeld.get()); auto* rightProbe = dynamic_cast<MidiIsolationProbe*>(rightHeld.get());
    check(leftProbe && rightProbe, "diagnostic instruments inserted into both real graph chains");
    const auto block = [&](std::initializer_list<juce::MidiMessage> messages = {}) {
        juce::AudioBuffer<float> audio(2, 256); audio.clear(); juce::MidiBuffer midi;
        for (const auto& m : messages) midi.addEvent(m, 0);
        matrixHosted.processBlock(audio, midi);
        return std::array<float, 2> { audio.getMagnitude(0, 0, 256), audio.getMagnitude(1, 0, 256) };
    };
    const auto settle = [&] {
        matrixEdit->dispatchPendingUpdatesSynchronously();
        juce::MessageManager::getInstance()->runDispatchLoopUntil(4);
        matrixEdit->dispatchPendingUpdatesSynchronously();
        for (int i = 0; i < 8; ++i) block();
    };
    const auto monitor = [&](const juce::String& id, bool on) { command(matrix, "set_input_monitor", object({ {"track_id", id}, {"mode", on ? "on" : "off"} })); };
    const auto arm = [&](const juce::String& id, bool on) { command(matrix, "set_track_armed", object({ {"track_id", id}, {"armed", on} })); };
    const auto pcmMatches = [&](std::array<float, 2> pcm, bool left, bool right, const juce::String& label) {
        const bool passed = (left ? pcm[0] > 0.001f : pcm[0] < 0.000001f) && (right ? pcm[1] > 0.001f : pcm[1] < 0.000001f);
        if (!passed) {
            juce::Array<juce::var> inputs;
            auto* lt = production::graphTrack(*matrixEdit, leftId); auto* rt = production::graphTrack(*matrixEdit, rightId);
            for (auto* input : matrixEdit->getAllInputDevices()) inputs.add(object({
                {"device", input->getInputDevice().getDeviceID()}, {"enabled", input->getInputDevice().isEnabled()},
                {"left_target", input->getTargets().contains(lt->itemID)}, {"right_target", input->getTargets().contains(rt->itemID)},
                {"left_eligible", input->isLivePlayEnabled(*lt)}, {"right_eligible", input->isLivePlayEnabled(*rt)},
                {"left_armed", input->isRecordingEnabled(lt->itemID)}, {"right_armed", input->isRecordingEnabled(rt->itemID)} }));
            const auto probe = [&](MidiIsolationProbe& p) { return object({ {"rendered_blocks", p.renderedBlocks}, {"note_ons", p.noteOns}, {"note_offs", p.noteOffs},
                {"panics", p.panicCount}, {"channel_mode_events", p.channelModeCount}, {"pedal_releases", p.pedalReleases} }); };
            directory.getChildFile("midi-isolation-failure.json").replaceWithText(juce::JSON::toString(object({
                {"phase", label}, {"left_peak", pcm[0]}, {"right_peak", pcm[1]}, {"expected_left", left}, {"expected_right", right},
                {"left_probe", probe(*leftProbe)}, {"right_probe", probe(*rightProbe)}, {"inputs", juce::var(inputs)},
                {"recording_state", matrixRecorder.state()}, {"playing", matrixEdit->getTransport().isPlaying()},
                {"left_plugin_attached", lt->pluginList.contains(leftProbe)}, {"right_plugin_attached", rt->pluginList.contains(rightProbe)} }), true));
        }
        check(passed, label + " actual L/R PCM=" + juce::String(pcm[0], 6) + "/" + juce::String(pcm[1], 6)
              + " rendered=" + juce::String(leftProbe->renderedBlocks) + "/" + juce::String(rightProbe->renderedBlocks)
              + " note-ons=" + juce::String(leftProbe->noteOns) + "/" + juce::String(rightProbe->noteOns));
    };
    juce::Array<juce::var> matrixEvidence;
    // Every combination of two track monitors and record arms; channels 1/16.
    for (int bits = 0; bits < 16; ++bits) {
        const bool monL = (bits & 1) != 0, monR = (bits & 2) != 0, armL = (bits & 4) != 0, armR = (bits & 8) != 0;
        monitor(leftId, monL); monitor(rightId, monR); arm(leftId, armL); arm(rightId, armR); settle();
        matrix.selectTrack((bits & 1) ? rightId : leftId); // Selection must never grant monitoring or arm.
        const int channel = (bits & 4) ? 16 : 1;
        block({ juce::MidiMessage::noteOn(channel, 60, juce::uint8(100)) }); const auto pcm = block();
        pcmMatches(pcm, monL, monR, "16-way monitor/arm matrix " + juce::String(bits));
        matrixEvidence.add(object({ {"case", bits}, {"monitor_left", monL}, {"monitor_right", monR}, {"arm_left", armL}, {"arm_right", armR}, {"channel", channel}, {"left_peak", pcm[0]}, {"right_peak", pcm[1]} }));
        block({ juce::MidiMessage::noteOff(channel, 60) }); block();
        pcmMatches(block(), false, false, "note release after matrix case");
    }
    monitor(leftId, true); monitor(rightId, true); arm(leftId, false); arm(rightId, false); settle();
    // A new key arriving immediately after the Off command must not enter the
    // old graph and survive its removal. Deliberately do not pump UI timers
    // between changing the monitor and feeding this audio/MIDI block.
    monitor(leftId, false);
    block({ juce::MidiMessage::noteOn(3, 75, juce::uint8(100)) });
    settle();
    pcmMatches(block(), false, true, "immediate key after Monitor Off cannot hang in the old graph");
    block({ juce::MidiMessage::noteOff(3, 75) }); block();
    monitor(leftId, true); settle();
    const auto beforeReject = matrix.snapshot();
    check(matrix.execute("set_input_monitor", object({ {"input_device_id", matrixMidiId}, {"mode", "off"} }), beforeReject.revision).failed(), "ambiguous device-only monitoring rejects without affecting either track");
    check(matrix.execute("set_input_monitor", object({ {"track_id", leftId}, {"input_device_id", "other-input"}, {"mode", "off"} }), beforeReject.revision).failed(), "mismatched explicit track and input reject");
    check(matrix.snapshot().tracks[0].monitorMode == "on" && matrix.snapshot().tracks[1].monitorMode == "on", "rejected requests preserve both monitor states");
    block({ juce::MidiMessage::noteOn(16, 62, juce::uint8(100)), juce::MidiMessage::controllerEvent(16, 64, 127) }); block();
    monitor(leftId, false); settle();
    pcmMatches(block(), false, true, "turning left off releases only left held voice, right remains audible");
    check(rightProbe->sounding(62) == 1 && leftProbe->sounding(62) == 0, "target cleanup preserves source IDs and channel 16");
    monitor(leftId, true); settle();
    block({ juce::MidiMessage::noteOn(16, 65, juce::uint8(100)) }); block();
    command(matrix, "set_track_input", object({ {"track_id", leftId}, {"input_device_id", ""} })); matrixRecorder.poll(); settle();
    pcmMatches(block(), false, true, "detaching left input never sends note offs to surviving right target");
    check(rightProbe->sounding(62) == 1 && rightProbe->sounding(65) == 1, "input removal preserves both right-held notes");
    monitor(rightId, false); settle(); pcmMatches(block(), false, false, "last monitor off clears its own held notes");
    // Physical key/pedal state is still retained independently until key-up.
    block({ juce::MidiMessage::noteOff(16, 62), juce::MidiMessage::noteOff(16, 65), juce::MidiMessage::controllerEvent(16, 64, 0) });
    command(matrix, "set_track_input", object({ {"track_id", leftId}, {"input_device_id", matrixMidiId} })); matrixRecorder.poll(); settle();
    command(matrix, "set_input_monitor", object({ {"track_id", leftId}, {"mode", "auto"} })); arm(leftId, true); settle();
    check(matrix.snapshot().tracks[0].monitorMode == "off", "legacy Auto is canonical Off even when armed");
    block({ juce::MidiMessage::noteOn(1, 60, juce::uint8(100)) }); pcmMatches(block(), false, false, "legacy Auto armed stays silent");
    block({ juce::MidiMessage::noteOff(1, 60) });
    // Record both directions: Off+Rec records silently; On without Rec sounds
    // but creates no take. Real engine capture and project adoption are used.
    for (int recordSide = 0; recordSide < 2; ++recordSide) {
        const bool recordLeft = recordSide == 0;
        monitor(leftId, !recordLeft); monitor(rightId, recordLeft); arm(leftId, recordLeft); arm(rightId, !recordLeft); settle();
        matrix.seek(recordSide * 2.0); const auto before = matrix.snapshot();
        command(matrix, "start_recording");
        for (int b = 0; b < 110; ++b) {
            std::array<float, 2> pcm;
            if (b == 20) pcm = block({ juce::MidiMessage::noteOn(7, 69, juce::uint8(96)) });
            else if (b == 85) pcm = block({ juce::MidiMessage::noteOff(7, 69) });
            else pcm = block();
            if (b == 45) pcmMatches(pcm, !recordLeft, recordLeft, "recorded silent track and audible unarmed track are independent");
        }
        // Config changes cannot stop a different track's take behind its back.
        check(matrix.execute("set_input_monitor", object({ {"track_id", recordLeft ? rightId : leftId}, {"mode", "off"} }), matrix.snapshot().revision).failed()
              && matrixEdit->getTransport().isRecording(), "active-take configuration guard leaves current recording running");
        command(matrix, "stop_recording"); matrix.impl->finishRecording();
        const auto after = matrix.snapshot();
        check(after.tracks[recordSide].clips.size() == before.tracks[recordSide].clips.size() + 1
              && after.tracks[1 - recordSide].clips.size() == before.tracks[1 - recordSide].clips.size(), "only the armed destination gets recorded notes");
        const auto take = matrix.impl->capture().tracks[recordSide].clips.back();
        check(take.notes.size() == 1 && take.notes.front().pitch == 69 && take.notes.front().channel == 7, "silent monitored-off take retains actual pitch and MIDI channel");
        settle(); command(matrix, "undo"); settle();
        check(matrix.snapshot().tracks[recordSide].clips.size() == before.tracks[recordSide].clips.size(), "one Undo removes only the recorded take");
    }
    arm(leftId, false); arm(rightId, false); monitor(leftId, false); monitor(rightId, false); settle();
    check(matrix.execute("start_recording", object({}), matrix.snapshot().revision).failed(), "no armed tracks means no recording");
    // Sequence playback remains independent of physical input routing.
    command(matrix, "create_midi_clip", object({ {"track_id", leftId}, {"start_beats", 0.0}, {"length_beats", 16.0} }));
    const auto sequenceId = matrix.snapshot().tracks[0].clips.back().id;
    command(matrix, "write_notes", object({ {"clip_id", sequenceId}, {"notes", juce::var(juce::Array<juce::var> { object({ {"pitch", 48}, {"velocity", 100}, {"channel", 1}, {"start_beats", 0.0}, {"length_beats", 15.0} }) })} }));
    matrix.seek(0); matrix.togglePlay(); settle();
    pcmMatches(block(), true, false, "MIDI clip plays with both monitors Off");
    monitor(leftId, true); settle(); block({ juce::MidiMessage::noteOn(1, 72, juce::uint8(100)) }); block();
    check(leftProbe->sounding(48) > 0 && leftProbe->sounding(72) > 0, "clip and keyboard are both present before monitor off");
    const auto panicBefore = leftProbe->panicCount, channelModeBefore = leftProbe->channelModeCount;
    monitor(leftId, false); settle();
    check(leftProbe->sounding(48) > 0 && leftProbe->sounding(72) == 0, "monitor off releases input voice while existing clip voice continues");
    check(leftProbe->panicCount == panicBefore && leftProbe->channelModeCount == channelModeBefore, "monitor off uses no blanket plugin panic or all-notes-off");
    pcmMatches(block(), true, false, "clip PCM remains after live monitor off");
    block({ juce::MidiMessage::noteOff(1, 72) }); matrix.stop(); settle();
    okay(directory.createDirectory(), "create MIDI matrix evidence directory");
    check(directory.getChildFile("midi-isolation-matrix.json").replaceWithText(juce::JSON::toString(object({
        {"sample_rate", 48000}, {"block_size", 256}, {"driver", "HostedAudioDeviceInterface (no physical I/O)"},
        {"instrument", "diagnostic source-aware MIDI voice/PCM probe"}, {"cases", juce::var(matrixEvidence)},
        {"held_note_and_sustain_cleanup", true}, {"immediate_monitor_off_boundary", true}, {"input_detach_isolation", true}, {"recording_both_directions", true}, {"clip_monitor_independence", true}
    }), true)), "write actual MIDI graph matrix evidence");
    // Plugin references must be released before their Edit and cache disappear.
    leftHeld = nullptr; rightHeld = nullptr;
}
