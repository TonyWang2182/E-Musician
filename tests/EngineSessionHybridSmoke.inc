// Runs inside the generation fixture's isolated, device-free session. These
// explicitly synthetic candidates exercise native adoption, not model quality.
{
    const auto& bound=test.impl->bindings.front().clips.front();
    auto a=std::make_shared<Impl::AnalysisEntry>();a->id=uid();a->kind="score";a->execution="cloud";a->modelId="synthetic-score";
    a->original=a->boundOriginal=bound.source;a->sourceFile=bound.info.playbackFile;
    a->directory=directory.getChildFile("score-candidate");okay(a->directory.createDirectory(),"score fixture directory");
    const auto position=bound.clip->getPosition();
    a->source=object({{"project_id",test.snapshot().projectId},{"clip_id",bound.id},{"asset_id",bound.assetId},{"track_id",test.impl->bindings.front().id},
        {"clip_timeline_start",position.time.getStart().inSeconds()},{"clip_source_offset",position.offset.inSeconds()},{"clip_duration",position.time.getLength().inSeconds()},
        {"bpm",test.snapshot().bpm},{"range_start_seconds",.1},{"duration_seconds",.8},{"timeline_start",position.time.getStart().inSeconds()+.1}});
    a->parameters=object({});JobFingerprint sourceHash;okay(fingerprint(a->original,sourceHash,{}),"score original hash");a->originalHash=sourceHash.hash;
    okay(fingerprint(a->sourceFile,sourceHash,{}),"score prepared hash");
    const auto note=[](int pitch,int channel){return object({{"pitch",pitch},{"start_seconds",.1},{"duration_seconds",.2},{"velocity",91},{"channel",channel}});};
    const auto cc=[](double at,int value){return object({{"time_seconds",at},{"controller",64},{"value",value},{"channel",2}});};
    juce::Array<juce::var> midi{
        object({{"id","piano"},{"name","Piano"},{"instrument","acoustic_piano"},{"program",0},{"channel",2},{"is_drum",false},
            {"notes",juce::Array<juce::var>{note(64,2)}},{"controllers",juce::Array<juce::var>{cc(.05,127),cc(.7,0)}}}),
        object({{"id","drums"},{"name","Drums"},{"instrument","drums"},{"program",0},{"channel",10},{"is_drum",true},
            {"notes",juce::Array<juce::var>{note(36,10)}},{"controllers",juce::Array<juce::var>{}}})};
    a->result=object({{"schema_version",1},{"job_id",a->id},{"result_id",a->id},{"kind","score"},{"duration_seconds",.8},
        {"source",object({{"source_sha256",sourceHash.hash}})},{"model",object({{"id",a->modelId},{"version","synthetic-v1"}})},{"parameters",a->parameters},
        {"midi_tracks",midi},{"tempo",juce::var()},
        {"chord_regions",juce::Array<juce::var>{object({{"label","Db:maj9(#11)/Ab"},{"start_seconds",0.0},{"end_seconds",.8},{"score",juce::var()},{"uncertain",true}})}},
        {"beat_events",juce::Array<juce::var>{object({{"time_seconds",.2},{"is_downbeat",true}})}},
        {"structure_regions",juce::Array<juce::var>{object({{"label","Verse A"},{"start_seconds",0.0},{"end_seconds",.8}})}}});
    okay(validateAnalysisResult(a->result,a->id,"score",.8),"validate multi-instrument score with nullable tempo/confidence");
    auto invalid=a->result.clone();invalid["midi_tracks"][0]["controllers"][0].getDynamicObject()->setProperty("value",128);
    check(validateAnalysisResult(invalid,a->id,"score",.8).failed(),"reject out-of-range pedal value");
    invalid=a->result.clone();invalid["structure_regions"][0].getDynamicObject()->setProperty("end_seconds",.9);
    check(validateAnalysisResult(invalid,a->id,"score",.8).failed(),"reject out-of-source section");
    check(!storage::isSupportedChordLabel("C\n7"),"reject multiline chord while preserving extensions");
    a->summary=candidateSummary(a->result);check(int(a->summary["track_count"])==2&&int(a->summary["controller_count"])==2&&int(a->summary["program_change_count"])==2,"summary separates pedals from injected programs");
    check(a->directory.getChildFile("result.json").replaceWithText(juce::JSON::toString(a->result)),"write immutable score candidate");
    JobFingerprint resultHash;okay(fingerprint(a->directory.getChildFile("result.json"),resultHash,{}),"score manifest hash");a->resultHash=resultHash.hash;
    a->job=std::make_shared<Impl::Job>();a->job->status="ready";a->job->kind="analysis.score";a->job->done=true;test.impl->analyses[a->id]=a;
    juce::var page;okay(run("get_analysis_result",object({{"result_id",a->id},{"component","notes"},{"limit",1},{"offset",1}}),&page),"paged score readback");
    check(page["items"].size()==1&&bool(page["items"][0]["is_drum"])&&int(page["total"])==2,"flat note page retains instrument identity");
    const auto before=test.snapshot();okay(run("accept_analysis_result",object({{"result_id",a->id}})),"accept synthetic score");
    const auto until=juce::Time::getMillisecondCounterHiRes()+10000;
    while(a->acceptJob->worker.joinable()&&juce::Time::getMillisecondCounterHiRes()<until){juce::MessageManager::getInstance()->runDispatchLoopUntil(10);test.impl->reapFinishedJobs(true);}
    check(a->acceptJob->status=="applied","score adoption: "+a->acceptJob->error);
    auto acceptedScore=test.impl->capture();check(acceptedScore.schemaVersion==8&&acceptedScore.tracks.size()==3&&acceptedScore.chordRegions.size()==1,"score import adds two MIDI tracks and chord annotation");
    check(test.snapshot().revision==before.revision+1&&test.snapshot().bpm==before.bpm,"one revision without changing project tempo");
    const auto& piano=acceptedScore.tracks[1].clips.front();
    check(piano.midiChannel==2&&piano.notes.front().channel==2&&piano.controllers.size()==3,"channel and pedal plus program retained");
    check(piano.controllers[1].value==(127<<7)&&acceptedScore.tracks[2].clips.front().midiChannel==10,"native controller resolution and drum channel preserved");
    auto controllerOnly=acceptedScore;controllerOnly.tracks[1].clips.front().notes.clear();
    const auto pedalFile=directory.getChildFile("pedal-channel.mid");okay(writeJobMidi(std::make_shared<Impl::Job>(),pedalFile,controllerOnly,{piano.id}),"export controller-only explicit channel");
    juce::FileInputStream midiInput(pedalFile);juce::MidiFile pedalMidi;check(pedalMidi.readFrom(midiInput),"read exported controller MIDI");bool pedalSeen=false;
    for(int t=0;t<pedalMidi.getNumTracks();++t)for(int e=0;e<pedalMidi.getTrack(t)->getNumEvents();++e){const auto& m=pedalMidi.getTrack(t)->getEventPointer(e)->message;if(m.isController()){check(m.getChannel()==2,"controller-only export preserves channel2");pedalSeen=true;}}
    check(pedalSeen,"export includes pedal events");
    check(std::abs(piano.timelineStart-2.1)<1e-9&&acceptedScore.chordRegions.front().label=="Db:maj9(#11)/Ab","frozen range placement and complex chord spelling");
    check(acceptedScore.chordRegions.front().score==-1&&acceptedScore.chordRegions.front().uncertain,"unknown confidence not fabricated");
    juce::var annotations;okay(run("get_analysis_annotations",object({{"analysis_id",a->id},{"component","structure"}}),&annotations),"read accepted sections");
    check(int(annotations["total"])==1&&std::abs(double(annotations["items"][0]["start_seconds"])-2.1)<1e-9,"accepted section uses absolute project timeline");
    okay(test.undo(test.snapshot().revision),"score one Undo");check(test.snapshot().tracks.size()==1&&test.impl->capture().analyses.empty()&&test.impl->capture().chordRegions.empty(),"Undo removes all score components together");
    okay(test.redo(test.snapshot().revision),"score Redo");
    const auto savedScore=directory.getChildFile("hybrid-score.emproj");okay(test.saveProject(savedScore,test.snapshot().revision),"save schema8");
    okay(test.saveProject(savedScore,test.snapshot().revision),"save existing schema8 again");
    okay(test.openProject(savedScore,test.snapshot().revision),"reopen schema8 offline");
    acceptedScore=test.impl->capture();check(acceptedScore.schemaVersion==8&&acceptedScore.tracks[1].clips.front().controllers.size()==3&&acceptedScore.analyses.front().annotationsJson.contains("Verse A"),"offline reopen retains pedals and sections");
    okay(run("get_analysis_annotations",object({{"component","notes"},{"kind","score"}}),&annotations),"saved score note view");check(int(annotations["total"])==2,"saved note view reads authoritative MIDI");
    okay(run("get_analysis_annotations",object({{"component","chords"},{"kind","score"}}),&annotations),"saved score chord view");check(annotations["items"][0]["score"].isVoid(),"public unknown confidence remains null");
    juce::var selected;const auto routes=juce::var(juce::Array<juce::var>{object({{"kind","score"},{"execution","cloud"},{"model_id","sheetsage2"},{"available",true},{"default",true}})});
    check(selectAnalysisRoute(routes,"score",object({{"execution","local"}}),selected).failed(),"explicit local route never silently uses cloud");
    okay(selectAnalysisRoute(routes,"score",object({{"execution","auto"}}),selected),"auto resolves available model");
    okay(test.saveProject(savedScore,test.snapshot().revision),"overwrite reopened schema8");
    auto legacy=acceptedScore;legacy.schemaVersion=7;check(storage::validate(legacy).failed(),"schema8 metadata cannot masquerade as older schema");
    report.setProperty("hybrid_fixture","synthetic multi-instrument score; native import/undo/redo/offline save, no model or network");
}
