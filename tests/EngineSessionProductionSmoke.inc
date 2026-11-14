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
#include "EngineSessionMidiIsolationSmoke.inc"
        {
            EngineSession fixture(false);
            auto analysis=std::make_shared<Impl::Job>();analysis->kind="analysis.separate";analysis->status="running";
            std::atomic<bool> release{false};bool committed=false;
            analysis->commit=[&]{committed=true;jobStatus(analysis,"ready");};
            analysis->worker=std::thread([&]{while(!release.load())std::this_thread::sleep_for(std::chrono::milliseconds(1));analysis->done=true;});
            fixture.impl->jobs.push_back(analysis);
            for(int i=0;i<63;++i){auto retired=std::make_shared<Impl::Job>();retired->kind="save_project";retired->status="completed";fixture.impl->jobs.push_back(retired);}
            auto next=fixture.impl->startJob("save_project",[](const auto&){});
            const bool retained=std::find(fixture.impl->jobs.begin(),fixture.impl->jobs.end(),analysis)!=fixture.impl->jobs.end();
            release=true;
            while(!analysis->done.load()||(next&&!next->done.load()))std::this_thread::sleep_for(std::chrono::milliseconds(1));
            fixture.impl->reapFinishedJobs(true);
            check(next&&retained&&committed,"concurrent analysis remains pumpable when completed job history is pruned");
        }
        okay(runNativeLoadQueueTests(), "native sample loader queue");
        {
            storage::StoredPlugin old;old.format="E-musician";old.role="effect";old.identifier="native.compressor";
            const juce::String json=R"({"version":1,"type":"compressor","threshold_db":-30,"ratio":10,"attack_ms":0.1,"release_ms":100,"makeup_db":0})";
            old.state=juce::MemoryBlock(json.toRawUTF8(),json.getNumBytesAsUTF8());
            native_effects::Settings parsed;okay(native_effects::decode(old,parsed),"legacy compressor state");
            check(parsed.compressor.dryWet==1.0f&&double(native_effects::encode(parsed)["dry_wet"])==1.0,"legacy compressor defaults to fully wet");
            EngineSession fixture(false);
            auto tree=juce::ValueTree(te::IDs::PLUGIN);tree.setProperty(te::IDs::type,native_effects::Effect::xmlTypeName,nullptr);
            tree.setProperty("emEffectType",old.identifier,nullptr);tree.setProperty("emEffectData",juce::var(old.state),nullptr);
            te::Plugin::Ptr held=new native_effects::Effect(te::PluginCreationInfo(*fixture.impl->edit,tree,true));
            auto* effect=dynamic_cast<native_effects::Effect*>(held.get());check(effect!=nullptr,"create compressor wrapper fixture");
            effect->initialise({te::TimePosition::fromSeconds(0),48000.0,128});
            juce::AudioBuffer<float> audio(2,128);audio.clear();
            for(int ch=0;ch<2;++ch)for(int i=0;i<128;++i)audio.setSample(ch,i,.5f);
            te::MidiMessageArray midi;
            te::PluginRenderContext context(&audio,juce::AudioChannelSet::stereo(),0,128,&midi,0,
                te::TimeRange{te::TimePosition::fromSeconds(0),te::TimeDuration::fromSeconds(128.0/48000)},true,false,false,false);
            check(effect->meterSequence()==0,"meter starts unavailable before real processing");
            effect->applyToBuffer(context);
            check(effect->meterSequence()==1&&effect->gainReductionDb()>5,"meter reflects real rendered compressor gain reduction");
            held=nullptr;
        }
        {
            EngineSession fixture(false);
            auto tree=juce::ValueTree(te::IDs::PLUGIN);tree.setProperty(te::IDs::type,native::Instrument::xmlTypeName,nullptr);
            te::Plugin::Ptr held=new native::Instrument(te::PluginCreationInfo(*fixture.impl->edit,tree,true));
            auto* instrument=dynamic_cast<native::Instrument*>(held.get());check(instrument!=nullptr,"create native wrapper fixture");
            instrument->initialise({te::TimePosition::fromSeconds(0),48000.0,128});
            auto data=std::make_shared<native::SampleData>();data->sampleRate=48000;data->left.assign(4096,0.5f);
            auto bank=std::make_unique<native::PreparedBank>();bank->bank.generation=1;bank->samples[0]=data;bank->sampleHashes[0]="fixture-hash";
            auto& slot=bank->bank.slots[0];slot.left=data->left.data();slot.frames=data->left.size();slot.endFrame=data->left.size();
            slot.sampleRate=48000;slot.rootNote=60;slot.minNote=0;slot.maxNote=127;slot.attackSeconds=0;slot.oneShot=true;
            instrument->publish(std::move(bank));
            check(instrument->sampleForDisplay(0,"fixture-hash")==data,"published pad PCM is available for display");
            check(!instrument->sampleForDisplay(0,"other-hash")&&!instrument->sampleForDisplay(1,"fixture-hash")
                && !instrument->sampleForDisplay(-1,"fixture-hash"),"waveform PCM rejects wrong hash and pad");
            juce::AudioBuffer<float> audio(2,128);te::MidiMessageArray midi;
            const auto process=[&]{te::PluginRenderContext context(&audio,juce::AudioChannelSet::stereo(),0,128,&midi,0,
                te::TimeRange{te::TimePosition::fromSeconds(0),te::TimeDuration::fromSeconds(128.0/48000)},true,false,false,false);
                instrument->applyToBuffer(context);};
            midi.addMidiMessage(juce::MidiMessage::noteOn(1,60,juce::uint8(127)),0.0,te::MPESourceID(0));audio.clear();process();
            check(audio.getMagnitude(0,0,128)>0.1f,"native wrapper produces held voice");
            midi.clear();audio.clear();instrument->reset();process();
            check(audio.getMagnitude(0,0,128)==0.0f,"native wrapper reset stops sounding voices");
            midi.addMidiMessage(juce::MidiMessage::noteOn(2,60,juce::uint8(127)),0.0,te::MPESourceID(0));audio.clear();process();
            check(audio.getMagnitude(0,0,128)>0.1f,"native wrapper produces second-channel voice");
            midi.clear();audio.clear();instrument->midiPanic();process();
            check(audio.getMagnitude(0,0,128)==0.0f,"native wrapper panic clears all channels");
            check(!instrument->previewSample(-1)&&!instrument->previewSample(1),"preview rejects invalid and empty pads");
            check(instrument->previewSample(0),"ready sample accepts independent preview");
            audio.clear();process();check(audio.getMagnitude(0,0,128)>0.1f,"preview renders without timeline MIDI");
            instrument->stopPreview();audio.clear();process();check(audio.getMagnitude(0,0,128)==0.0f,"preview stop silences one-shot preview");
            midi.addMidiMessage(juce::MidiMessage::noteOn(2,60,juce::uint8(127)),0.0,te::MPESourceID(0));audio.clear();process();
            midi.clear();check(instrument->previewSample(0),"preview can coexist with MIDI playback");audio.clear();process();
            instrument->stopPreview();audio.clear();process();check(audio.getMagnitude(0,0,128)>0.1f,"preview stop does not silence timeline voices");
            held=nullptr;
        }
        okay(runVst3InactiveBusSmoke(), "VST3 inactive-bus compatibility buffers");
        {
            // A native effect is deliberately not a third-party editor, so an
            // accepted target reaches showEditor and fails harmlessly there.
            // This verifies routing without opening any real plugin window.
            EngineSession fixture(false);
            command(fixture,"create_track",object({{"kind","audio"},{"name","Owner"}}));
            const auto owner=fixture.snapshot().tracks.back().id;
            command(fixture,"create_track",object({{"kind","audio"},{"name","Other"}}));
            const auto other=fixture.snapshot().tracks.back().id;
            juce::var added;
            okay(fixture.execute("add_native_effect",object({{"track_id",owner},{"type","eq8"}}),fixture.snapshot().revision,&added),"add harmless target fixture");
            const auto id=added["device_id"].toString();check(id.isNotEmpty(),"fixture has a stable device ID");
            const auto open=[&](juce::var args){return fixture.execute("open_plugin",args,fixture.snapshot().revision);};
            const auto wrong=open(object({{"track_id",other},{"plugin_id",id}}));
            check(wrong.failed()&&wrong.getErrorMessage().contains("does not belong"),"wrong track cannot open another track's device");
            const auto correct=open(object({{"track_id",owner},{"plugin_id",id}}));
            check(correct.failed()&&correct.getErrorMessage().contains("not loaded"),"correct track reaches editor host");
            const auto legacy=open(object({{"plugin_id",id}}));
            check(legacy.failed()&&legacy.getErrorMessage().contains("not loaded"),"legacy ID-only open reaches editor host");
            const auto master=open(object({{"track_id","master"},{"plugin_id",id}}));
            check(master.failed()&&master.getErrorMessage().contains("does not belong"),"master cannot open a track device");
            juce::var masterAdded;
            okay(fixture.execute("add_native_effect",object({{"track_id","master"},{"type","compressor"}}),fixture.snapshot().revision,&masterAdded),"add master target fixture");
            const auto masterId=masterAdded["device_id"].toString();check(masterId.isNotEmpty(),"master fixture has a stable device ID");
            const auto rightMaster=open(object({{"track_id","master"},{"plugin_id",masterId}}));
            check(rightMaster.failed()&&rightMaster.getErrorMessage().contains("not loaded"),"correct master reaches editor host");
            const auto wrongMaster=open(object({{"track_id",owner},{"plugin_id",masterId}}));
            check(wrongMaster.failed()&&wrongMaster.getErrorMessage().contains("does not belong"),"track cannot open master device");
            const auto malformed=open(object({{"track_id",42},{"plugin_id",id}}));
            check(malformed.failed()&&malformed.getErrorMessage().contains("valid track ID"),"invalid track identity rejected");
        }
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
            EngineSession preferences(false);const auto initial=preferences.snapshot();
            command(preferences,"set_recording_preferences",object({{"metronome_enabled",true},{"metronome_gain_db",-30.0},{"metronome_record_only",true},{"count_in_enabled",true},{"count_in_bars",4}}));
            auto changed=preferences.snapshot();
            check(changed.revision==initial.revision&&changed.dirty==initial.dirty&&!changed.canUndo,"recording preferences do not mutate project revision/dirty/Undo");
            check(changed.metronomeEnabled&&changed.metronomeRecordOnly&&changed.countInEnabled&&changed.countInBars==4&&std::abs(changed.metronomeGainDb+30)<1.0e-6,"all recording preferences round trip");
            check(std::abs(preferences.impl->edit->getClickTrackVolume()-juce::Decibels::decibelsToGain(-30.0f))<1.0e-6,"quiet metronome gain is not clamped to native 0.2 floor");
            check(preferences.execute("set_recording_preferences",object({{"metronome_enabled",false},{"count_in_bars",3}}),changed.revision).failed()&&preferences.snapshot().metronomeEnabled,"invalid preference patch is atomic");
            check(preferences.execute("set_recording_preferences",object({{"metronome_gain_db",std::numeric_limits<double>::quiet_NaN()}}),changed.revision).failed(),"nonfinite metronome gain rejected");
            check(changed.memoryWorkingSetBytes>0&&changed.memoryPrivateBytes>0,"Windows RAM observations are real positive byte counts");
            const auto readAt=preferences.impl->memoryReadAt;preferences.snapshot();check(preferences.impl->memoryReadAt==readAt,"repeated snapshots reuse RAM sample");
            {
                te::LevelMeasurer disconnected;auto probe=preferences.snapshot();TrackSnapshot track;track.inputDeviceId="disconnected-device";probe.tracks.push_back(track);
                auto tap=std::make_unique<Impl::MeterTap>();tap->bind(&disconnected);tap->left=tap->right=-3.0f;
                preferences.impl->inputMeters.emplace(track.inputDeviceId,std::move(tap));preferences.impl->metersReadAt=-1000000;
                preferences.impl->updateTelemetry(probe);
                check(!preferences.impl->inputMeters.contains(track.inputDeviceId)&&probe.tracks.back().inputPeakDb==-100.0f,"missing enumerated input is detached and stale peak disappears even while track binding remains");
            }
            command(preferences,"reset_meters");check(!preferences.snapshot().masterOverloaded,"meter reset available without project mutation");
            for(const auto signature:std::array<std::pair<int,int>,4>{{{4,4},{3,4},{6,8},{3,8}}}){
                command(preferences,"set_time_signature",object({{"numerator",signature.first},{"denominator",signature.second}}));
                preferences.impl->edit->tempoSequence.updateTempoData();
                check(std::abs(preferences.impl->edit->getNumCountInBeats()-signature.first*4.0/signature.second*4)<1.0e-8,"four-bar preroll matches meter denominator");
                check(std::abs(preferences.impl->edit->tempoSequence.toTime(te::BeatPosition::fromBeats(4)).inSeconds()-2.0)<1.0e-8,"native MIDI quarter-beat clock remains consistent across signatures");
            }
        }
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
        auto direct = render("direct");
        edit->clickTrackEnabled=true;edit->clickTrackEmphasiseBars=true;
        auto withClick = render("click-excluded");double clickDifference=0;
        for(int ch=0;ch<direct.getNumChannels();++ch)for(int i=0;i<direct.getNumSamples();++i)clickDifference=std::max(clickDifference,double(std::abs(direct.getSample(ch,i)-withClick.getSample(ch,i))));
        check(clickDifference<1.0e-7,"enabled metronome never enters offline render");edit->clickTrackEnabled=false;
        const auto directRms = direct.getRMSLevel(0, 12000, 48000); check(directRms > 0.01f, "direct graph renders non-silent audio");
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
        juce::Array<juce::var> countInReports;
        const auto reportCountIn=[&](const juce::String& phase){
            auto& native=isolated.impl->edit->getTransport();auto* context=native.getCurrentPlaybackContext();
            countInReports.add(object({{"phase",phase},{"state",isolated.impl->recording.state()},
                {"transport_position",native.getPosition().inSeconds()},
                {"audio_position",context?context->getPosition().inSeconds():0.0},
                {"play_pending",context&&context->isPlayPending()},
                {"native_count_beats",isolated.impl->edit->getNumCountInBeats()}}));
            check(directory.getChildFile("recording-countin-diagnostics.json").replaceWithText(juce::JSON::toString(object({{"stages",countInReports}}),true)),"write count-in clock diagnostics");
        };
        // Cancellation during native preroll must never create a partial take.
        command(isolated,"set_recording_preferences",object({{"count_in_enabled",true},{"count_in_bars",4},{"metronome_enabled",false}}));
        const auto beforeCancel=isolated.snapshot();
        command(isolated,"start_recording");
        reportCountIn("four-bars-before-first-audio-block");
        check(isolated.snapshot().countingIn&&isolated.snapshot().countInBeatsRemaining>15,"native four-bar prerecord state is visible while click switch is off");
        double countClickPeak=0;
        for(int b=0;b<100;++b){juce::AudioBuffer<float> input(2,256);input.clear();juce::MidiBuffer midi;hosted.processBlock(input,midi);countClickPeak=std::max(countClickPeak,double(input.getMagnitude(0,input.getNumSamples())));}
        reportCountIn("four-bars-after-100-blocks");
        check(countClickPeak>0.001,"count-in produces click independently of metronome play switch");
        command(isolated,"stop_recording");isolated.impl->finishRecording();
        reportCountIn("four-bars-cancelled");
        check(!isolated.snapshot().recording&&!isolated.snapshot().recordingFinalizing&&isolated.snapshot().recordingError.isEmpty(),"cancelled count-in returns cleanly to idle");
        check(isolated.snapshot().revision==beforeCancel.revision&&recordingTracks[0]->getClips().isEmpty()&&recordingTracks[1]->getClips().isEmpty(),"cancelled count-in creates no clips or revision");
        command(isolated,"set_recording_preferences",object({{"count_in_enabled",false}}));
        recordingEdit->getUndoManager().clearUndoHistory();
        const auto beforeTakeRevision = isolated.snapshot().revision;
        command(isolated, "start_recording");
        check(isolated.snapshot().recording && isolated.snapshot().duration == 0, "public record starts in an empty arrangement");
        for (int block = 0; block < 256; ++block) {
            juce::AudioBuffer<float> input(2, 256); for (int ch = 0; ch < 2; ++ch) for (int i = 0; i < 256; ++i) input.setSample(ch, i, 0.2f * float(std::sin((block * 256 + i) * 0.035)));
            juce::MidiBuffer midi; if (block == 4) midi.addEvent(juce::MidiMessage::noteOn(1, 60, juce::uint8(100)), 0);
            if (block == 12) midi.addEvent(juce::MidiMessage::controllerEvent(1, 64, 127), 0);
            // Real keyboards can deliver matching note edges with the same timestamp.
            if (block == 20) { midi.addEvent(juce::MidiMessage::noteOn(1, 62, juce::uint8(75)), 10); midi.addEvent(juce::MidiMessage::noteOff(1, 62), 10); }
            if (block == 240) midi.addEvent(juce::MidiMessage::noteOn(1, 64, juce::uint8(85)), 1); // Held across Stop.

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
        const auto capturedTake = isolated.impl->capture();
        juce::Array<juce::var> noteEdges;
        for (const auto& t : capturedTake.tracks) for (const auto& c : t.clips) for (const auto& n : c.notes)
            noteEdges.add(object({ {"pitch", n.pitch}, {"start", n.startBeats}, {"length", n.lengthBeats}, {"clip_length", c.lengthBeats} }));
        check(directory.getChildFile("recording-note-boundaries.json").replaceWithText(juce::JSON::toString(object({ {"notes", noteEdges}, {"validation", storage::validate(capturedTake).getErrorMessage()} }), true)), "write synthetic recording boundary evidence");
        bool instant = false, held = false;
        for (auto* n : recordedMidi->getSequence().getNotes()) {
            if (n->getNoteNumber() == 62) { instant = true; check(n->getLengthBeats().inBeats() >= 1.0 / 960.0 - 1.0e-12, "same-sample note edges retain an exportable positive duration"); }
            if (n->getNoteNumber() == 64) { held = true; check(n->getLengthBeats().inBeats() > 0, "held note ends safely when recording stops"); }
        }
        check(instant && held, "short and held recording notes are preserved");
        okay(storage::validate(capturedTake), "recorded notes satisfy persistence boundaries");
        const auto takeUndoBeforePump = recordingEdit->getUndoManager().getUndoDescriptions().joinIntoString(" | ");
        {
            // A late native event must not be lost when the engine resets take
            // length to the Stop boundary. Use a nonzero timeline origin too.
            EngineSession boundary(false);
            command(boundary, "create_track", object({ {"kind", "instrument"} }));
            command(boundary, "create_midi_clip", object({ {"track_id", boundary.snapshot().tracks[0].id}, {"start_beats", 4.0}, {"length_beats", 1.0} }));
            auto* native = dynamic_cast<te::MidiClip*>(te::getAudioTracks(*boundary.impl->edit)[0]->getClips()[0]);
            auto& sequence = native->getSequence(); auto* um = &boundary.impl->edit->getUndoManager();
            auto* late = sequence.addNote(67, te::BeatPosition::fromBeats(1.2), te::BeatDuration::fromBeats(0.3), 90, 0, um);
            late->state.setProperty("emId", "late-native-note", um);
            auto* tiny = sequence.addNote(69, te::BeatPosition::fromBeats(0.2506), te::BeatDuration::fromBeats(0), 80, 0, um);
            tiny->state.setProperty("emId", "short-native-note", um);
            auto* pedal = sequence.addControllerEvent(te::BeatPosition::fromBeats(1.6), 64, 0, um);
            pedal->state.setProperty("emId", "late-pedal", um);
            check(storage::validate(boundary.impl->capture()).failed(), "native late/zero fixture reproduces strict persistence rejection");
            production::normaliseRecordedMidiTiming(*native);
            boundary.impl->recordEdit();
            const auto repaired = boundary.impl->capture(); const auto& fixed = repaired.tracks[0].clips[0];
            okay(storage::validate(repaired), "normalised native take satisfies strict persistence");
            check(fixed.startBeats == 4 && std::abs(fixed.lengthBeats - 1.6) < 1.0e-9 && fixed.sourceOffset == 0, "late event extends only the end at a nonzero timeline origin");
            check(fixed.notes.size() == 2 && fixed.controllers.size() == 1 && late->getStartBeat().inBeats() == 1.2 && late->getVelocity() == 90, "normalisation retains every note/controller, onset and velocity");
            const auto eventKey = contentKey(repaired); production::normaliseRecordedMidiTiming(*native);
            check(contentKey(boundary.impl->capture()) == eventKey, "recording normalisation is idempotent");
            // The user's recovered take contains positive 0.001-beat notes.
            // Those remain valid in projects even if both SMF edges round alike.
            tiny->setStartAndLength(te::BeatPosition::fromBeats(0.2506), te::BeatDuration::fromBeats(0.0001), um);
            boundary.impl->recordEdit();
            const auto midiFile = workspace.getChildFile("short-positive.mid");
            command(boundary, "export_midi", object({ {"path", midiFile.getFullPathName()} }));
            const auto deadline = juce::Time::getMillisecondCounterHiRes() + 5000;
            while (boundary.hasActiveJobs() && juce::Time::getMillisecondCounterHiRes() < deadline) { juce::MessageManager::getInstance()->runDispatchLoopUntil(5); boundary.impl->timerCallback(); }
            auto exported = boundary.snapshot(); check(!exported.jobs.empty() && exported.jobs.back().status == "completed" && midiFile.existsAsFile(), "positive sub-tick MIDI note exports successfully");
            juce::FileInputStream input(midiFile); juce::MidiFile file; check(file.readFrom(input), "read generated short-note MIDI");
            bool shortRoundTrip = false;
            for (int track = 0; track < file.getNumTracks(); ++track) { auto seq = *file.getTrack(track); seq.updateMatchedPairs(); for (int index = 0; index < seq.getNumEvents(); ++index) { auto* event = seq.getEventPointer(index); if (event->message.isNoteOn() && event->message.getNoteNumber() == 69) { check(event->noteOffObject != nullptr && event->noteOffObject->message.getTimeStamp() - event->message.getTimeStamp() == 1, "sub-tick note survives as exactly one MIDI tick"); shortRoundTrip = true; } } }
            check(shortRoundTrip, "short exported note was not dropped");
            auto invalidExport = boundary.impl->capture(); invalidExport.tracks[0].clips[0].notes[0].lengthBeats = std::numeric_limits<double>::max();
            auto exportProbe = std::make_shared<Impl::Job>();
            check(writeJobMidi(exportProbe, workspace.getChildFile("overflow.mid"), invalidExport, {}).failed(), "unrepresentable MIDI duration is rejected before integer conversion");
            invalidExport.tracks[0].clips[0].notes[0].lengthBeats = 0;
            check(writeJobMidi(exportProbe, workspace.getChildFile("zero.mid"), invalidExport, {}).failed(), "zero-length stored data is not silently accepted by MIDI export");

            tiny->state.setProperty(te::IDs::l, -1.0, um); production::normaliseRecordedMidiTiming(*native);
            check(double(tiny->state[te::IDs::l]) == -1.0 && storage::validate(boundary.impl->capture()).failed(), "negative native duration is not repaired into a valid note");
        }
        const auto recordedFile = recordedAudio->getOriginalFile();
        const auto takeUndoAfterPump = recordingEdit->getUndoManager().getUndoDescriptions().joinIntoString(" | ");
        command(isolated, "undo");
        check(directory.getChildFile("recording-undo-after-dispatch.json").replaceWithText(juce::JSON::toString(object({
            {"before_dispatch", takeUndoBeforePump}, {"after_dispatch", takeUndoAfterPump},
            {"after_undo", recordingEdit->getUndoManager().getUndoDescriptions().joinIntoString(" | ")},
            {"audio_clips_after_undo", recordingTracks[0]->getClips().size()}, {"midi_clips_after_undo", recordingTracks[1]->getClips().size()}
        }), true)), "write delayed recording Undo evidence");
        check(recordingTracks[0]->getClips().isEmpty() && recordingTracks[1]->getClips().isEmpty(), "one public Undo after asynchronous dispatch removes the whole simultaneous take");
        check(recordedFile.existsAsFile(), "Undo retains the recorded source for Redo"); command(isolated, "redo");
        check(recordingTracks[0]->getClips().size() == 1 && recordingTracks[1]->getClips().size() == 1, "one Redo restores both take clips");
        check(isolated.snapshot().tracks[0].clips.size() == 1 && isolated.snapshot().tracks[1].clips.size() == 1, "recorded clips reach public snapshots");
        // Two destinations share one hosted MIDI input. Monitor choices must
        // change live routing independently of the record-arm flags.
        command(isolated, "create_track", object({ {"kind", "instrument"}, {"name", "Monitor isolation"} }));
        const auto monitorTrackId = isolated.snapshot().tracks.back().id;
        command(isolated, "set_track_input", object({ {"track_id", monitorTrackId}, {"input_device_id", midiId} }));
        command(isolated, "set_track_armed", object({ {"track_id", monitorTrackId}, {"armed", true} }));
        const auto beforeMonitorRevision = isolated.snapshot().revision;
        const auto beforeMonitorUndo = recordingEdit->getUndoManager().getUndoDescriptions();
        command(isolated, "set_input_monitor", object({ {"track_id", midiTrackId}, {"mode", "on"} }));
        command(isolated, "set_input_monitor", object({ {"track_id", monitorTrackId}, {"mode", "off"} }));
        check(isolated.snapshot().revision == beforeMonitorRevision && recordingEdit->getUndoManager().getUndoDescriptions() == beforeMonitorUndo, "monitor changes do not edit the project or pollute undo history");
        recordingEdit->dispatchPendingUpdatesSynchronously();
        te::InputDeviceInstance* monitoredInput = nullptr;
        for (auto* input : recordingEdit->getAllInputDevices()) if (input->getInputDevice().getDeviceID() == midiId) monitoredInput = input;
        auto* firstMonitorTrack = production::graphTrack(*recordingEdit, midiTrackId);
        auto* secondMonitorTrack = production::graphTrack(*recordingEdit, monitorTrackId);
        check(monitoredInput && firstMonitorTrack && secondMonitorTrack, "find shared input and both track targets");
        check(monitoredInput->isRecordingEnabled(firstMonitorTrack->itemID) && monitoredInput->isRecordingEnabled(secondMonitorTrack->itemID), "monitor changes preserve independent recording arms");
        check(monitoredInput->isLivePlayEnabled(*firstMonitorTrack) && !monitoredInput->isLivePlayEnabled(*secondMonitorTrack), "on and off isolate two armed tracks sharing one MIDI device");
        command(isolated, "set_input_monitor", object({ {"track_id", monitorTrackId}, {"mode", "auto"} }));
        check(!monitoredInput->isLivePlayEnabled(*secondMonitorTrack) && isolated.snapshot().tracks[2].monitorMode == "off", "legacy auto resolves to off even when the second track is armed");
        command(isolated, "set_track_armed", object({ {"track_id", monitorTrackId}, {"armed", false} }));
        check(!monitoredInput->isLivePlayEnabled(*secondMonitorTrack) && monitoredInput->isLivePlayEnabled(*firstMonitorTrack), "disarm preserves explicit monitor off without affecting the other track");
        command(isolated, "set_input_monitor", object({ {"track_id", monitorTrackId}, {"mode", "on"} }));
        check(monitoredInput->isLivePlayEnabled(*secondMonitorTrack) && !monitoredInput->isRecordingEnabled(secondMonitorTrack->itemID), "on monitors without arming or recording the track");
        command(isolated, "set_track_input", object({ {"track_id", monitorTrackId}, {"input_device_id", ""} }));
        recorder.poll();
        check(!monitoredInput->getTargets().contains(secondMonitorTrack->itemID) && monitoredInput->isLivePlayEnabled(*firstMonitorTrack), "clearing one input detaches only its own monitor target");
        command(isolated, "set_track_input", object({ {"track_id", monitorTrackId}, {"input_device_id", midiId} }));
        recorder.poll();
        monitoredInput = nullptr;
        for (auto* input : recordingEdit->getAllInputDevices()) if (input->getInputDevice().getDeviceID() == midiId) monitoredInput = input;
        check(monitoredInput && monitoredInput->isLivePlayEnabled(*secondMonitorTrack) && !monitoredInput->isRecordingEnabled(secondMonitorTrack->itemID), "monitor on automatically binds a newly selected input without arming");
        command(isolated, "create_track", object({ {"kind", "bus"}, {"name", "Recorded bus"} })); const auto busId = isolated.snapshot().tracks.back().id;
        command(isolated, "set_track_output", object({ {"track_id", audioTrackId}, {"target_track_id", busId} }));
        command(isolated, "set_automation_lane", object({ {"track_id", audioTrackId}, {"lane_id", "public-gain"}, {"target", "track_gain"}, {"points", juce::var(juce::Array<juce::var>{ object({ {"id", "public-a"}, {"time_seconds", 0.0}, {"value", 0.5}, {"curve", 0.0} }), object({ {"id", "public-b"}, {"time_seconds", 1.0}, {"value", 0.8}, {"curve", 0.0} }) })} }));
        const auto beforeSave = isolated.impl->capture(); const auto projectFile = workspace.getChildFile("recorded.emproj");
        okay(isolated.saveProject(projectFile, isolated.snapshot().revision), "save captured audio, MIDI controllers, routing and curve");
        command(isolated, "set_input_monitor", object({ {"input_device_id", beforeSave.tracks[0].inputDeviceId}, {"mode", "on"} }));
        command(isolated, "set_input_monitor", object({ {"track_id", midiTrackId}, {"mode", "auto"} }));
        check(isolated.snapshot().tracks[0].monitorMode == "on" && isolated.snapshot().tracks[1].monitorMode == "off", "legacy auto is canonical off before reopening");
        command(isolated, "set_input_monitor", object({ {"track_id", midiTrackId}, {"mode", "on"} }));
        command(isolated, "create_track", object({ {"kind", "instrument"}, {"name", "New track defaults off"} }));
        const auto newTrackId = isolated.snapshot().tracks.back().id;
        command(isolated, "set_track_input", object({ {"track_id", newTrackId}, {"input_device_id", midiId} }));
        command(isolated, "set_track_armed", object({ {"track_id", newTrackId}, {"armed", true} }));
        auto* newTrack = production::graphTrack(*recordingEdit, newTrackId);
        te::InputDeviceInstance* newTrackInput = nullptr;
        for (auto* input : recordingEdit->getAllInputDevices()) if (input->getInputDevice().getDeviceID() == midiId) newTrackInput = input;
        check(newTrack && newTrackInput && !newTrackInput->isLivePlayEnabled(*newTrack), "new armed track defaults monitor off while another track sharing the input monitors on");
        okay(isolated.openProject(projectFile, isolated.snapshot().revision), "reopen recorded project"); const auto afterOpen = isolated.impl->capture();
        check(afterOpen.tracks[0].outputTargetId == busId && afterOpen.tracks[0].automation.size() == 1 && afterOpen.tracks[0].automation[0].points.size() == 2, "schema4 restores public routing and curve");
        check(afterOpen.tracks[1].clips[0].controllers.size() == beforeSave.tracks[1].clips[0].controllers.size() && afterOpen.tracks[1].clips[0].notes.size() == beforeSave.tracks[1].clips[0].notes.size(), "schema4 restores recorded notes and pedal events");
        for (const auto& track : isolated.snapshot().tracks) check(!track.armed && track.monitorMode == "off", "reopening leaves recording disarmed and monitor off");
        {
            const auto inputs = isolated.impl->recording.inputs(); const auto* list = inputs["inputs"].getArray();
            check(list != nullptr, "reopened engine input list is available");
            for (const auto& input : *list) check(input["monitor"].toString() == "off", "reopening resets all input owners, not just current Edit destinations");
        }
        // A completed count-in at a nonzero mid-bar position captures only the
        // punch-in region, retaining a held note and pre-roll sustain state.
        command(isolated,"set_time_signature",object({{"numerator",3},{"denominator",8}}));
        command(isolated,"set_recording_preferences",object({{"count_in_enabled",true},{"count_in_bars",1},{"metronome_enabled",false}}));
        command(isolated,"set_track_armed",object({{"track_id",audioTrackId},{"armed",true}}));
        command(isolated,"set_track_armed",object({{"track_id",midiTrackId},{"armed",true}}));
        auto* takeEdit=isolated.impl->edit.get();takeEdit->dispatchPendingUpdatesSynchronously();
        isolated.seek(5.375);const auto beforeCountTake=isolated.snapshot().revision;
        command(isolated,"start_recording");
        reportCountIn("mid-bar-before-first-audio-block");
        check(isolated.snapshot().countingIn,"mid-bar count-in is active");
        bool sentHeld=false,sentRelease=false;double audibleCountPeak=0;
        for(int block=0;block<300;++block){
            auto* playback=takeEdit->getTransport().getCurrentPlaybackContext();const auto position=playback->getPosition().inSeconds();
            juce::AudioBuffer<float> input(2,256);input.clear();juce::MidiBuffer midi;
            if(!sentHeld&&position<5.375){midi.addEvent(juce::MidiMessage::noteOn(1,72,juce::uint8(90)),0);midi.addEvent(juce::MidiMessage::controllerEvent(1,64,127),0);
                for(int cc:{0,6,32,38,84,88,96,97,98,99,100,101,123})midi.addEvent(juce::MidiMessage::controllerEvent(1,cc,1),1);
                sentHeld=true;}
            if(!sentRelease&&position>5.625){midi.addEvent(juce::MidiMessage::noteOff(1,72),0);midi.addEvent(juce::MidiMessage::controllerEvent(1,64,0),1);sentRelease=true;}
            hosted.processBlock(input,midi);if(position<5.375)audibleCountPeak=std::max(audibleCountPeak,double(input.getMagnitude(0,input.getNumSamples())));
        }
        reportCountIn("mid-bar-after-300-blocks");
        check(sentHeld&&sentRelease&&!isolated.snapshot().countingIn&&audibleCountPeak>0.001,"native sample clock finishes 3/8 count-in and keeps click audible");
        command(isolated,"stop_recording");isolated.impl->finishRecording();
        check(isolated.snapshot().revision==beforeCountTake+1,"completed count-in take commits one revision");
        const auto countTake=isolated.impl->capture();bool foundHeld=false,foundPedal=false,foundAudio=false;
        for(const auto& t:countTake.tracks)for(const auto& c:t.clips)if(std::abs(c.timelineStart-5.375)<0.011){
            if(c.kind=="audio"){
                foundAudio=true;juce::WavAudioFormat format;auto* native=isolated.impl->findClip(c.id);std::unique_ptr<juce::AudioFormatReader> r(format.createReaderFor(native->source.createInputStream().release(),true));
                check(r!=nullptr,"read count-in silent input take");juce::AudioBuffer<float> data(1,int(r->lengthInSamples));r->read(&data,0,data.getNumSamples(),0,true,false);
                check(data.getMagnitude(0,data.getNumSamples())<1.0e-6,"metronome does not leak into input recording");
            }
            for(const auto& n:c.notes)if(n.pitch==72){foundHeld=true;check(std::abs(n.startBeats)<0.025&&n.lengthBeats>0,"held note enters at recording boundary without negative offset");}
            for(const auto& event:c.controllers){
                if(event.type==64&&event.value==(127<<7)&&std::abs(event.beats)<1.0e-8)foundPedal=true;
                check(event.type!=0&&event.type!=6&&event.type!=32&&event.type!=38&&event.type!=84&&event.type!=88
                    &&(event.type<96||event.type>101)&&event.type!=123,"pre-count bank/RPN/increment/channel-mode events are not synthesized at recording start");
            }
        }
        check(foundHeld&&foundPedal&&foundAudio,"count-in retains held note, sustain-at-start and audio take");
        okay(storage::validate(countTake),"count-in take is saveable");
        command(isolated,"undo");command(isolated,"set_recording_preferences",object({{"count_in_enabled",false}}));
        command(isolated,"set_time_signature",object({{"numerator",4},{"denominator",4}}));
        {
            EngineSession chase(false); command(chase, "create_track", object({ {"kind", "instrument"}, {"name", "Controller boundary test"} }));
            const auto tid = chase.snapshot().tracks.front().id;
            command(chase, "create_midi_clip", object({ {"track_id", tid}, {"start_beats", 0.0}, {"length_beats", 8.0} }));
            auto fixture = chase.impl->capture(); const auto cid = fixture.tracks[0].clips[0].id;
            fixture.tracks[0].clips[0].controllers = {
                { "pedal-on", 1, 64, 127 << 7, 0 },
                { "bend", 2, te::MidiControllerEvent::pitchWheelType, 10000, 0 },
                { "all-notes-off", 2, 123, 0, 0 }, { "pedal-off", 6, 64, 0, 0 },
                { "program", 2, te::MidiControllerEvent::programChangeType, 7 << 7, 0 }
            };
            for(int cc:{0,6,32,38,96,97,98,99,100,101})
                fixture.tracks[0].clips[0].controllers.push_back({"unsupported-"+juce::String(cc),2,cc,1<<7,0});
            okay(chase.impl->applyTo(*chase.impl->edit, fixture, chase.impl->bindings, false), "prepare native controller fixture"); chase.impl->recordEdit(); chase.impl->edit->getUndoManager().clearUndoHistory();
            auto boundary = [&](const storage::StoredClip& clip) {
                bool pedal = false, bend = false, off = false, replayedAction = false;
                for (const auto& event : clip.controllers) {
                    pedal |= event.type == 64 && event.value == (127 << 7) && event.beats == 0;
                    bend |= event.type == te::MidiControllerEvent::pitchWheelType && event.value == 10000 && event.beats == 0;
                    off |= event.type == 64 && event.value == 0 && event.beats == 2;
                    replayedAction |= event.type == te::MidiControllerEvent::programChangeType || event.type == 123
                        || event.type == 0 || event.type == 6 || event.type == 32 || event.type == 38
                        || (event.type >= 96 && event.type <= 101);
                }
                check(pedal && bend && off && !replayedAction, "boundary chases pedal/bend, preserves later off and does not replay program/bank/RPN/increment/channel-mode actions");
            };
            command(chase, "split_clip", object({ {"clip_id", cid}, {"at_seconds", 2.0} })); auto split = chase.impl->capture();
            check(split.tracks[0].clips.size() == 2, "public MIDI split creates two clips");
            for (const auto& piece : split.tracks[0].clips) if (piece.id != cid) boundary(piece);
            command(chase, "undo"); check(chase.impl->capture().tracks[0].clips[0].controllers.size() == 15, "split Undo preserves original controller events"); command(chase, "redo");
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
