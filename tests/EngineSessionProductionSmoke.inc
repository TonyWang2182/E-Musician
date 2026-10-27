// Included after the other EngineSession smoke tests, inside emusician.
// All captured input is generated here and fed through HostedAudioDeviceInterface.
// No physical audio or MIDI input is opened by this suite.
juce::Result runVst3InactiveBusSmoke();
juce::Result EngineSession::runProductionSmokeTest(const juce::File& directory)
{
    requireControlThread(); int checks = 0;
    auto check = [&](bool ok, const juce::String& message) { if (!ok) throw std::runtime_error(("Production smoke: " + message).toStdString()); ++checks; };
    auto okay = [&](const juce::Result& r, const juce::String& context) { check(r.wasOk(), context + ": " + r.getErrorMessage()); };
    auto command = [&](EngineSession& target, const juce::String& name, juce::var args = object({})) { okay(target.execute(name, args, target.snapshot().revision), name); };
    try {
        okay(runVst3InactiveBusSmoke(), "VST3 inactive-bus compatibility buffers");
        const auto workspace = directory.getChildFile("production-" + uid()); okay(workspace.createDirectory(), "owned test workspace");
        storage::StoredProject graph; graph.projectId = uid();
        storage::StoredTrack source, busA, busB; source.id = "source"; source.name = "Source";
        busA.id = "bus-a"; busA.name = "A"; busA.kind = "bus"; busB.id = "bus-b"; busB.name = "B"; busB.kind = "bus";
        source.outputTargetId = busA.id; busA.outputTargetId = busB.id; graph.tracks = { source, busA, busB };
        okay(production::validateGraph(graph), "acyclic bus chain accepted");
        graph.tracks[2].sends.push_back({ "feedback", "bus-a", -12, false, false });
        check(production::validateGraph(graph).failed(), "disabled send still rejects indirect feedback cycle");
        graph.tracks[2].sends.clear(); graph.tracks[0].outputTargetId = "missing";
        check(production::validateGraph(graph).failed(), "missing output rejected"); graph.tracks[0].outputTargetId = "bus-a";
        storage::StoredAutomationLane lane; lane.id = "gain-lane"; lane.target = "track_gain";
        lane.points = { { "gain-a", 0, 0.5f, 0 }, { "gain-b", 1, 0.8f, 0.5f } };
        graph.tracks[0].automation = { lane }; okay(production::validateGraph(graph), "finite automation accepted");
        graph.tracks[0].automation[0].points[1].timeSeconds = 0;
        check(production::validateGraph(graph).failed(), "duplicate automation time rejected"); graph.tracks[0].automation = { lane };

        const auto preferencesFile = juce::File::getSpecialLocation(juce::File::userApplicationDataDirectory).getChildFile("E-musician/Settings.xml");
        const bool preferencesExisted = preferencesFile.existsAsFile();
        juce::MemoryBlock preferencesBefore;
        check(!preferencesExisted || preferencesFile.loadFileAsData(preferencesBefore), "read user settings without modifying them");
        {
            EngineSession first(false); auto& firstProperties = first.impl->engine.getPropertyStorage();
            check(firstProperties.getPropertiesFile().getFile() == juce::File(), "offline settings have no disk backing file");
            juce::XmlElement setup("DEVICESETUP"); setup.setAttribute("deviceType", "Offline isolation sentinel");
            firstProperties.setXmlProperty(te::SettingID::audio_device_setup, setup);
            check(firstProperties.getPropertiesFile().needsToBeSaved() && !firstProperties.getPropertiesFile().saveIfNeeded(), "explicit offline settings flush cannot write to disk");
            EngineSession second(false);
            check(second.impl->engine.getPropertyStorage().getXmlProperty(te::SettingID::audio_device_setup) == nullptr, "offline engines do not share device settings");
            check(firstProperties.getAppCacheFolder() != second.impl->engine.getPropertyStorage().getAppCacheFolder(), "offline engine caches have separate owners");
        }
        {
        EngineSession isolated(false); auto& engine = isolated.impl->engine;
        auto edit = te::createEmptyEdit(engine, {}); auto inhibit = std::make_unique<te::Edit::UndoTransactionInhibitor>(*edit);
        edit->ensureNumberOfAudioTracks(3); auto tracks = te::getAudioTracks(*edit);
        for (int i = 0; i < 3; ++i) { tracks[i]->state.setProperty("emId", graph.tracks[size_t(i)].id, nullptr); tracks[i]->state.setProperty("emKind", graph.tracks[size_t(i)].kind, nullptr); }
        okay(production::applyGraph(*edit, graph, true), "create native buses and curve");
        auto& curve = tracks[0]->getVolumePlugin()->volParam->getCurve();
        check(curve.getNumPoints() == 2 && std::abs(curve.getValueAt(te::TimePosition::fromSeconds(0)) - 0.5f) < 1.0e-6f, "native automation curve values");
        check(tracks[0]->getVolumePlugin()->volParam->isAutomationActive(), "native curve stream is active immediately without pumping message timers");
        check(tracks[0]->getOutput().getDestinationTrack() == tracks[1] && tracks[1]->getOutput().getDestinationTrack() == tracks[2], "native output DAG points to buses");
        check(tracks[1]->pluginList.findFirstPluginOfType<te::AuxReturnPlugin>() != nullptr, "native bus return exists");
        edit->getUndoManager().clearUndoHistory(); edit->getUndoManager().beginNewTransaction("Edit automation");
        graph.tracks[0].automation[0].points[1].value = 0.6f;
        okay(production::applyGraph(*edit, graph, false), "change native curve");
        check(std::abs(curve.getPointValue(1) - 0.6f) < 1.0e-6f, "automation edit applied");
        check(edit->getUndoManager().undo(), "automation edit Undo");
        check(std::abs(curve.getPointValue(1) - 0.8f) < 1.0e-6f, "automation Undo restores native value");
        check(edit->getUndoManager().redo(), "automation edit Redo");
        storage::StoredProject captured = graph; production::captureGraph(*edit, captured);
        check(captured.tracks[0].automation.size() == 1 && captured.tracks[0].automation[0].points[1].id == "gain-b", "curve point IDs survive capture");
        const auto explicitGain = captured.tracks[0].gainDb;
        tracks[0]->getVolumePlugin()->volParam->updateFromAutomationSources(te::TimePosition::fromSeconds(0.75));
        production::captureGraph(*edit, captured);
        check(std::abs(captured.tracks[0].gainDb - explicitGain) < 1.0e-5, "automation read does not replace saved manual fader value");

        // Compare rendered energy through real AuxSend/AuxReturn nodes, then
        // verify the read curve changes the exported audio, not merely the UI.
        const auto tone = workspace.getChildFile("tone.wav"); okay(writeDawTestTone(tone, 2, 0.15f), "synthetic routing tone");
        auto clip = tracks[0]->insertWaveClip("Tone", tone, { { te::TimePosition::fromSeconds(0), te::TimeDuration::fromSeconds(2) }, {} }, false);
        check(clip != nullptr, "insert synthetic audio"); clip->setUsesProxy(false);
        graph.tracks[0].automation.clear(); graph.tracks[0].outputTargetId = "master"; graph.tracks[1].outputTargetId = "master";
        juce::Array<juce::var> renderReports;
        auto render = [&](const juce::String& name) {
            auto output = workspace.getChildFile(name + ".wav"); juce::WavAudioFormat format;
            auto* parameter = tracks[0]->getVolumePlugin()->volParam.get(); auto& nativeCurve = parameter->getCurve();
            juce::Array<juce::var> nativePoints;
            for (int i = 0; i < nativeCurve.getNumPoints(); ++i) { auto point = nativeCurve.getPoint(i); nativePoints.add(object({ {"time_seconds", point.time.inSeconds()}, {"native_value", point.value}, {"curve", point.curve} })); }
            auto diagnostics = object({ {"name", name}, {"file", output.getFullPathName()}, {"sample_rate", 48000}, {"block_size", 256},
                {"reading_automation", edit->getAutomationRecordManager().isReadingAutomation()}, {"writing_automation", edit->getAutomationRecordManager().isWritingAutomation()},
                {"automation_active_before_render", parameter->isAutomationActive()}, {"bypass", bool(nativeCurve.bypass.get())}, {"explicit_native_value", parameter->getCurrentExplicitValue()},
                {"parameter_range_start", parameter->valueRange.start}, {"parameter_range_end", parameter->valueRange.end}, {"points", nativePoints} });
            renderReports.add(diagnostics);
            check(workspace.getChildFile("render-diagnostics.json").replaceWithText(juce::JSON::toString(object({ {"renders", renderReports} }), true)), "write pre-render curve diagnostics");
            te::Renderer::Parameters parameters(*edit); parameters.destFile = output; parameters.audioFormat = &format;
            parameters.sampleRateForAudio = 48000; parameters.blockSizeForAudio = 256; parameters.bitDepth = 24; parameters.canRenderInMono = false;
            parameters.useMasterPlugins = true; parameters.time = { te::TimePosition::fromSeconds(0), te::TimePosition::fromSeconds(2) }; parameters.tracksToDo = te::toBitSet(te::getAllTracks(*edit));
            { te::Edit::ScopedRenderStatus rendering(*edit, true); te::Renderer::RenderTask task("Production graph verification", parameters, nullptr, nullptr);
              while (task.runJob() == juce::ThreadPoolJob::jobNeedsRunningAgain) {} check(task.errorMessage.isEmpty(), "render " + name + ": " + task.errorMessage); }
            std::unique_ptr<juce::AudioFormatReader> reader(format.createReaderFor(output.createInputStream().release(), true)); check(reader != nullptr, "read rendered waveform");
            juce::AudioBuffer<float> samples(int(reader->numChannels), int(reader->lengthInSamples)); check(reader->read(&samples, 0, samples.getNumSamples(), 0, true, true), "decode rendered waveform");
            juce::Array<juce::var> rms; for (int start = 0; start < samples.getNumSamples(); start += 12000) rms.add(samples.getRMSLevel(0, start, std::min(12000, samples.getNumSamples() - start)));
            diagnostics.getDynamicObject()->setProperty("rms_quarter_seconds", rms); diagnostics.getDynamicObject()->setProperty("frames", samples.getNumSamples());
            if (samples.getNumSamples() >= 84000) diagnostics.getDynamicObject()->setProperty("late_early_rms_ratio", samples.getRMSLevel(0, 72000, 12000) / juce::jmax(1.0e-12f, samples.getRMSLevel(0, 0, 12000)));
            check(workspace.getChildFile("render-diagnostics.json").replaceWithText(juce::JSON::toString(object({ {"renders", renderReports} }), true)), "write rendered RMS diagnostics before checking expected effect");
            return samples;
        };
        okay(production::applyGraph(*edit, graph, true), "direct output graph");
        auto direct = render("direct"); const auto directRms = direct.getRMSLevel(0, 12000, 48000); check(directRms > 0.01f, "direct graph renders non-silent audio");
        graph.tracks[0].sends = { { "send-a", "bus-a", 0.0f, false, true } }; okay(production::applyGraph(*edit, graph, false), "add post-fader send");
        auto sent = render("send"); const auto ratio = sent.getRMSLevel(0, 12000, 48000) / directRms;
        check(ratio > 1.8f && ratio < 2.2f, "send and bus return add audible parallel audio");
        graph.tracks[0].sends.clear(); lane.points = { { "gain-a", 0, te::decibelsToVolumeFaderPosition(-24), 0 }, { "gain-b", 1.5, te::decibelsToVolumeFaderPosition(0), 0 } }; graph.tracks[0].automation = { lane };
        okay(production::applyGraph(*edit, graph, false), "render automation graph"); auto automated = render("automated");
        check(automated.getRMSLevel(0, 72000, 12000) > automated.getRMSLevel(0, 0, 12000) * 3, "automation curve changes exported audio over time");
        // Clip::~Clip accesses its Edit's clip cache. Release this retained
        // native clip before destroying the temporary render Edit.
        clip = nullptr;
        inhibit.reset(); edit.reset();

        // Independent hosted input test. No actual driver, microphone or MIDI
        // keyboard is touched; the same record/stop/adoption code is exercised.
        struct HostedScope { te::Engine& engine; ~HostedScope() { engine.getDeviceManager().deviceManager.closeAudioDevice(); engine.getDeviceManager().removeHostedAudioDeviceInterface(); } } hostedScope{ engine };
        auto& hosted = engine.getDeviceManager().getHostedAudioDeviceInterface();
        te::HostedAudioDeviceInterface::Parameters parameters; parameters.sampleRate = 48000; parameters.blockSize = 256; parameters.inputChannels = 2; parameters.outputChannels = 2; parameters.useMidiDevices = false;
        hosted.initialise(parameters); hosted.prepareToPlay(48000, 256); engine.getDeviceManager().dispatchPendingUpdates();
        command(isolated, "create_track", object({ {"kind", "audio"}, {"name", "Record audio"} }));
        command(isolated, "create_track", object({ {"kind", "instrument"}, {"name", "Record MIDI"} }));
        auto* recordingEdit = isolated.impl->edit.get(); auto recordingTracks = te::getAudioTracks(*recordingEdit);
        const auto audioTrackId = isolated.snapshot().tracks[0].id, midiTrackId = isolated.snapshot().tracks[1].id;
        auto waveInputs = engine.getDeviceManager().getWaveInputDevices(); check(!waveInputs.empty(), "hosted audio input available");
        juce::String midiId; for (const auto& midi : engine.getDeviceManager().getMidiInDevices()) if (te::HostedAudioDeviceInterface::isHostedMidiInputDevice(*midi)) midiId = midi->getDeviceID();
        check(midiId.isNotEmpty(), "hosted MIDI input available");
        command(isolated, "set_track_input", object({ {"track_id", audioTrackId}, {"input_device_id", waveInputs.front()->getDeviceID()} }));
        command(isolated, "set_track_input", object({ {"track_id", midiTrackId}, {"input_device_id", midiId} }));
        auto& recorder = isolated.impl->recording; recorder.attach(*recordingEdit, workspace.getChildFile("takes"));
        {
            const auto inputs = recorder.inputs(); const auto* list = inputs["inputs"].getArray();
            check(list != nullptr && list->size() >= 3, "hosted audio and MIDI owners are enumerated before recording");
            for (const auto& input : *list) check(input["monitor"].toString() == "off", "attach resets every engine input owner, including unassigned inputs, to monitor off");
        }
        command(isolated, "set_track_armed", object({ {"track_id", audioTrackId}, {"armed", true} }));
        command(isolated, "set_track_armed", object({ {"track_id", midiTrackId}, {"armed", true} }));
        recordingEdit->dispatchPendingUpdatesSynchronously(); recordingEdit->getUndoManager().clearUndoHistory();
        const auto beforeTakeRevision = isolated.snapshot().revision;
        command(isolated, "start_recording");
        check(isolated.snapshot().recording && isolated.snapshot().duration == 0, "public record starts in an empty arrangement");
        for (int block = 0; block < 256; ++block) {
            juce::AudioBuffer<float> input(2, 256); for (int ch = 0; ch < 2; ++ch) for (int i = 0; i < 256; ++i) input.setSample(ch, i, 0.2f * float(std::sin((block * 256 + i) * 0.035)));
            juce::MidiBuffer midi; if (block == 4) midi.addEvent(juce::MidiMessage::noteOn(1, 60, juce::uint8(100)), 0);
            if (block == 12) midi.addEvent(juce::MidiMessage::controllerEvent(1, 64, 127), 0);
            if (block == 90) { midi.addEvent(juce::MidiMessage::noteOff(1, 60), 0); midi.addEvent(juce::MidiMessage::controllerEvent(1, 64, 0), 1); }
            hosted.processBlock(input, midi);
            if (block == 64) { isolated.impl->timerCallback(); check(isolated.snapshot().recording, "empty arrangement timer does not stop recording at duration zero"); }
        }
        command(isolated, "stop_recording");
        check(isolated.snapshot().recordingFinalizing, "public Stop retains finalizing state until bindings are adopted");
        check(isolated.saveProject(workspace.getChildFile("premature.emproj"), isolated.snapshot().revision).failed(), "save cannot omit a just-stopped take before finalization");
        isolated.impl->finishRecording();
        check(isolated.snapshot().revision == beforeTakeRevision + 1 && !isolated.snapshot().recordingFinalizing, "whole take commits one project revision");
        check(!recorder.poll(), "completed take notification is not repeated");
        check(recordingTracks[0]->getClips().size() == 1 && recordingTracks[1]->getClips().size() == 1, "audio and MIDI recording create one clip each");
        auto* recordedAudio = dynamic_cast<te::WaveAudioClip*>(recordingTracks[0]->getClips()[0]); auto* recordedMidi = dynamic_cast<te::MidiClip*>(recordingTracks[1]->getClips()[0]);
        check(recordedAudio && recordedAudio->getOriginalFile().existsAsFile() && recordedAudio->state["emAsset"].toString().isNotEmpty(), "audio recording owns a persistent source and asset ID");
        {
            juce::WavAudioFormat format;
            std::unique_ptr<juce::AudioFormatReader> reader(format.createReaderFor(recordedAudio->getOriginalFile().createInputStream().release(), true));
            check(reader != nullptr && reader->sampleRate == 48000 && reader->numChannels == 1, "recorded mono input retains 48 kHz format");
            check(std::abs(reader->lengthInSamples - juce::int64(256 * 256)) <= 256, "recorded WAV length matches supplied samples within one input block");
            juce::AudioBuffer<float> capturedAudio(1, int(reader->lengthInSamples));
            check(reader->read(&capturedAudio, 0, capturedAudio.getNumSamples(), 0, true, false), "decode recorded WAV samples");
            const auto rms = capturedAudio.getRMSLevel(0, 0, capturedAudio.getNumSamples());
            check(rms > 0.08f && rms < 0.20f, "recorded audio contains the generated signal rather than silence");
        }
        check(recordedMidi && recordedMidi->getSequence().getNumNotes() >= 1 && recordedMidi->getSequence().getNumControllerEvents() >= 2, "MIDI recording preserves notes and sustain controller");
        check(recordedMidi->getSequence().getNotes()[0]->state["emId"].toString().isNotEmpty(), "recorded MIDI note has stable ID");
        const auto recordedFile = recordedAudio->getOriginalFile();
        command(isolated, "undo"); check(recordingTracks[0]->getClips().isEmpty() && recordingTracks[1]->getClips().isEmpty(), "one public Undo removes the whole simultaneous take");
        check(recordedFile.existsAsFile(), "Undo retains the recorded source for Redo"); command(isolated, "redo");
        check(recordingTracks[0]->getClips().size() == 1 && recordingTracks[1]->getClips().size() == 1, "one Redo restores both take clips");
        check(isolated.snapshot().tracks[0].clips.size() == 1 && isolated.snapshot().tracks[1].clips.size() == 1, "recorded clips reach public snapshots");
        command(isolated, "create_track", object({ {"kind", "bus"}, {"name", "Recorded bus"} })); const auto busId = isolated.snapshot().tracks.back().id;
        command(isolated, "set_track_output", object({ {"track_id", audioTrackId}, {"target_track_id", busId} }));
        command(isolated, "set_automation_lane", object({ {"track_id", audioTrackId}, {"lane_id", "public-gain"}, {"target", "track_gain"}, {"points", juce::var(juce::Array<juce::var>{ object({ {"id", "public-a"}, {"time_seconds", 0.0}, {"value", 0.5}, {"curve", 0.0} }), object({ {"id", "public-b"}, {"time_seconds", 1.0}, {"value", 0.8}, {"curve", 0.0} }) })} }));
        const auto beforeSave = isolated.impl->capture(); const auto projectFile = workspace.getChildFile("recorded.emproj");
        okay(isolated.saveProject(projectFile, isolated.snapshot().revision), "save captured audio, MIDI controllers, routing and curve");
        command(isolated, "set_input_monitor", object({ {"input_device_id", beforeSave.tracks[0].inputDeviceId}, {"mode", "on"} }));
        command(isolated, "set_input_monitor", object({ {"input_device_id", midiId}, {"mode", "auto"} }));
        check(isolated.snapshot().tracks[0].monitorMode == "on" && isolated.snapshot().tracks[1].monitorMode == "auto", "test explicitly sets non-off monitor modes before reopening");
        okay(isolated.openProject(projectFile, isolated.snapshot().revision), "reopen recorded project"); const auto afterOpen = isolated.impl->capture();
        check(afterOpen.tracks[0].outputTargetId == busId && afterOpen.tracks[0].automation.size() == 1 && afterOpen.tracks[0].automation[0].points.size() == 2, "schema4 restores public routing and curve");
        check(afterOpen.tracks[1].clips[0].controllers.size() == beforeSave.tracks[1].clips[0].controllers.size() && afterOpen.tracks[1].clips[0].notes.size() == beforeSave.tracks[1].clips[0].notes.size(), "schema4 restores recorded notes and pedal events");
        for (const auto& track : isolated.snapshot().tracks) check(!track.armed && track.monitorMode == "off", "reopening leaves recording disarmed and monitor off");
        {
            const auto inputs = isolated.impl->recording.inputs(); const auto* list = inputs["inputs"].getArray();
            check(list != nullptr, "reopened engine input list is available");
            for (const auto& input : *list) check(input["monitor"].toString() == "off", "reopening resets all input owners, not just current Edit destinations");
        }
        {
            EngineSession chase(false); command(chase, "create_track", object({ {"kind", "instrument"}, {"name", "Controller boundary test"} }));
            const auto tid = chase.snapshot().tracks.front().id;
            command(chase, "create_midi_clip", object({ {"track_id", tid}, {"start_beats", 0.0}, {"length_beats", 8.0} }));
            auto fixture = chase.impl->capture(); const auto cid = fixture.tracks[0].clips[0].id;
            fixture.tracks[0].clips[0].controllers = { { "pedal-on", 1, 64, 127 << 7, 0 }, { "bend", 2, 0x1005, 10000, 0 }, { "all-notes-off", 2, 123, 0, 0 }, { "pedal-off", 6, 64, 0, 0 } };
            okay(chase.impl->applyTo(*chase.impl->edit, fixture, chase.impl->bindings, false), "prepare native controller fixture"); chase.impl->recordEdit(); chase.impl->edit->getUndoManager().clearUndoHistory();
            auto boundary = [&](const storage::StoredClip& clip) {
                bool pedal = false, bend = false, off = false, replayedAction = false;
                for (const auto& event : clip.controllers) { pedal |= event.type == 64 && event.value == (127 << 7) && event.beats == 0; bend |= event.type == 0x1005 && event.value == 10000 && event.beats == 0; off |= event.type == 64 && event.value == 0 && event.beats == 2; replayedAction |= event.type == 123; }
                check(pedal && bend && off && !replayedAction, "boundary chases pedal/bend, preserves later off and does not replay channel-mode actions");
            };
            command(chase, "split_clip", object({ {"clip_id", cid}, {"at_seconds", 2.0} })); auto split = chase.impl->capture();
            check(split.tracks[0].clips.size() == 2, "public MIDI split creates two clips");
            for (const auto& piece : split.tracks[0].clips) if (piece.id != cid) boundary(piece);
            command(chase, "undo"); check(chase.impl->capture().tracks[0].clips[0].controllers.size() == 4, "split Undo preserves original controller events"); command(chase, "redo");
            for (const auto& piece : chase.impl->capture().tracks[0].clips) if (piece.id != cid) boundary(piece);
            command(chase, "undo"); command(chase, "trim_clip", object({ {"clip_id", cid}, {"start_seconds", 2.0}, {"end_seconds", 4.0} })); boundary(chase.impl->capture().tracks[0].clips[0]);
            command(chase, "undo"); command(chase, "duplicate_clips", object({ {"clip_ids", juce::var(juce::Array<juce::var>{ cid })} }));
            std::set<juce::String> eventIds; auto duplicated = chase.impl->capture();
            check(duplicated.tracks[0].clips.size() == 2, "public MIDI duplicate creates a second clip");
            for (const auto& copy : duplicated.tracks[0].clips) for (const auto& event : copy.controllers) check(eventIds.insert(event.id).second, "duplicated controller IDs are globally unique");
        }
        } // Destroy the hosted engine before checking its settings side effects.
        juce::MemoryBlock preferencesAfter;
        check(preferencesFile.existsAsFile() == preferencesExisted && (!preferencesExisted || preferencesFile.loadFileAsData(preferencesAfter)), "offline teardown preserves user settings presence");
        check(preferencesAfter == preferencesBefore, "hosted capture, device changes and engine teardown preserve user settings bytes");
        auto report = object({ {"ok", true}, {"checks", checks}, {"input_source", "generated hosted buffers; no physical inputs"}, {"sample_rate", 48000}, {"block_size", 256}, {"workspace", workspace.getFullPathName()} });
        check(directory.getChildFile("production-smoke.json").replaceWithText(juce::JSON::toString(report, true)), "write production evidence");
        return juce::Result::ok();
    } catch (const std::exception& e) { return juce::Result::fail(e.what()); }
}
