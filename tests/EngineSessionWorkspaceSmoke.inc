// Synthetic/offline contract tests. The output directory belongs to the harness.
juce::Result EngineSession::runWorkspaceEngineSmokeTest(juce::DynamicObject& report,const juce::File& outputDirectory)
{
    requireControlThread();EngineSession test(false);int checks=0;
    const auto check=[&](bool ok,const juce::String& label){if(!ok)throw std::runtime_error(label.toStdString());++checks;};
    const auto okay=[&](const juce::Result& result,const juce::String& label){check(result.wasOk(),label+": "+result.getErrorMessage());};
    const auto run=[&](const juce::String& command,const juce::var& args,juce::var* result=nullptr){return test.execute(command,args,test.snapshot().revision,result);};
    const auto child=[](const char* command,juce::var args){return object({{"command",command},{"args",args}});};
    try{
        okay(outputDirectory.createDirectory(),"fixture output directory");
        okay(runGenerationEngineSmokeTest(report,outputDirectory.getChildFile("generation")),"generation contracts");
        okay(run("create_track",object({{"kind","instrument"},{"name","Colour fixture"}})),"create fixture track");
        const auto id=test.snapshot().tracks.front().id;
        okay(run("create_midi_clip",object({{"track_id",id},{"start_beats",0.0},{"length_beats",4.0}})),"create fixture clip");
        const auto clipId=test.snapshot().tracks.front().clips.front().id;
        okay(run("write_notes",object({{"clip_id",clipId},{"notes",juce::Array<juce::var>{object({{"id","colour-note"},{"pitch",60},{"start_beats",0.0},{"length_beats",1.0},{"velocity",90},{"channel",1}})}}})),"write fixture note");
        juce::MessageManager::getInstance()->runDispatchLoopUntil(20);
        auto* edit=test.impl->edit.get();auto* track=test.impl->find(id)->track;
        auto* clip=test.impl->findClip(clipId)->clip.get();
        const auto notes=test.snapshot().tracks.front().clips.front().notes;
        const auto colour=[&]{return test.snapshot().tracks.front().colour;};
        const auto setColour=[&](juce::var value){return run("set_track_colour",object({{"track_id",id},{"colour",value}}));};
        check(colour().isEmpty(),"old/new track defaults to automatic colour");
        auto rev=test.snapshot().revision;
        okay(setColour("#1a2b3c"),"canonical colour input");
        check(colour()=="#1A2B3C"&&test.snapshot().revision==rev+1,"colour normalizes and advances one revision");
        check(test.snapshotJson()["tracks"][0]["colour"].toString()==colour(),"colour appears in public snapshot");
        check(test.impl->edit.get()==edit&&test.impl->find(id)->track==track&&test.impl->findClip(clipId)->clip.get()==clip
            &&test.snapshot().tracks.front().clips.front().notes==notes,"colour retains Edit, track, clip and immutable MIDI view");
        rev=test.snapshot().revision;okay(setColour("#1A2B3C"),"same colour is a no-op");check(test.snapshot().revision==rev,"same colour has no revision");
        for(const auto& invalid:juce::Array<juce::var>{juce::var(),true,123,"#ABC","#11223344","112233","#GG1234"," #123456","#123456 "}){
            check(setColour(invalid).failed(),"reject malformed colour");check(colour()=="#1A2B3C"&&test.snapshot().revision==rev,"invalid colour leaves state and history unchanged");
        }
        check(run("set_track_colour",object({{"track_id",id},{"colour","#FFFFFF"},{"extra",1}})).failed(),"reject unknown colour field");
        okay(test.undo(rev),"colour Undo");check(colour().isEmpty(),"Undo returns automatic colour");
        okay(test.redo(test.snapshot().revision),"colour Redo");check(colour()=="#1A2B3C","Redo restores canonical colour");
        rev=test.snapshot().revision;juce::var batchResult;
        okay(run("batch",object({{"commands",juce::Array<juce::var>{child("set_track_colour",object({{"track_id",id},{"colour","#FFAA00"}})),child("set_track_colour",object({{"track_id",id},{"colour","#224466"}}))}}}),&batchResult),"colour-only atomic batch");
        check(colour()=="#224466"&&test.snapshot().revision==rev+1&&int(batchResult["executed_commands"])==2,"batch final colour and one revision");
        check(test.snapshot().tracks.front().clips.front().notes==notes,"colour batch does not reconstruct MIDI notes");
        okay(test.undo(test.snapshot().revision),"colour batch single Undo");check(colour()=="#1A2B3C","batch Undo restores first colour");
        const auto before=test.impl->currentKey;rev=test.snapshot().revision;
        check(run("batch",object({{"commands",juce::Array<juce::var>{child("set_track_colour",object({{"track_id",id},{"colour","#FF0000"}})),child("set_track_colour",object({{"track_id","missing"},{"colour","#FFFFFF"}}))}}})).failed(),"invalid later colour rejects batch");
        check(test.impl->currentKey==before&&test.snapshot().revision==rev,"failed colour batch is atomic");
        okay(setColour(""),"reset colour");check(colour().isEmpty(),"empty resets automatic colour");okay(setColour("#8844CC"),"set persisted colour");
        const auto file=outputDirectory.getChildFile("colour-and-effect.emproj");
        okay(test.saveProject(file,test.snapshot().revision),"save coloured project");
        storage::StoredProject saved;okay(storage::load(file,saved),"read saved colour");check(saved.tracks.front().colour=="#8844CC","storage preserves colour");
        auto legacy=juce::JSON::parse(file);legacy["tracks"][0].getDynamicObject()->removeProperty("colour");
        const auto legacyFile=outputDirectory.getChildFile("legacy-no-colour.emproj");
        check(legacyFile.replaceWithText(juce::JSON::toString(legacy)),"write legacy synthetic manifest");
        storage::StoredProject old;okay(storage::load(legacyFile,old),"load old manifest without colour");check(old.tracks.front().colour.isEmpty(),"old manifest defaults to automatic");
        legacy["tracks"][0].getDynamicObject()->setProperty("colour",false);
        check(legacyFile.replaceWithText(juce::JSON::toString(legacy)),"write invalid synthetic colour");
        check(storage::load(legacyFile,old).failed(),"invalid saved colour is refused");
        okay(test.openProject(file,test.snapshot().revision),"reopen coloured project");check(colour()=="#8844CC","reopen restores colour in Edit");

        juce::var added;okay(run("add_native_effect",object({{"track_id",id},{"type","compressor"}}),&added),"add native effect fixture");
        const auto device=added["device_id"].toString();check(device.isNotEmpty(),"native effect ID returned");
        const auto effectState=[&]{juce::var value;okay(test.impl->describeNativeEffect(id,device,value),"read committed effect");return value["state"].clone();};
        auto initial=effectState();initial.getDynamicObject()->setProperty("threshold_db",0.0);initial.getDynamicObject()->setProperty("ratio",1.0);initial.getDynamicObject()->setProperty("makeup_db",0.0);
        const auto effectArgs=[&](const juce::var& state){return object({{"track_id",id},{"device_id",device},{"state",state}});};
        okay(run("set_native_effect",effectArgs(initial)),"set neutral compressor");
        auto* effect=dynamic_cast<native_effects::Effect*>(test.impl->livePlugin(*test.impl->edit,device));check(effect!=nullptr,"native effect remains live");
        auto* nativeEdit=test.impl->edit.get();auto* nativeTrack=test.impl->find(id)->track;
        effect->initialise({te::TimePosition::fromSeconds(0),48000.0,128});
        juce::AudioBuffer<float> audio(2,128);te::MidiMessageArray midi;
        const auto renderedLevel=[&]{
            for(int block=0;block<32;++block){for(int c=0;c<2;++c)for(int i=0;i<128;++i)audio.setSample(c,i,.2f);
                te::PluginRenderContext context(&audio,juce::AudioChannelSet::stereo(),0,128,&midi,0,
                    te::TimeRange{te::TimePosition::fromSeconds(0),te::TimeDuration::fromSeconds(128.0/48000)},true,false,false,false);
                effect->applyToBuffer(context);}
            return audio.getMagnitude(0,0,128);
        };
        const auto level=renderedLevel();
        const auto begin=[&]{juce::var reply;okay(run("begin_native_effect_gesture",object({{"track_id",id},{"device_id",device}}),&reply),"begin native gesture");return reply["gesture_id"].toString();};
        const auto finish=[&](const char* command,const juce::String& token){return run(command,object({{"gesture_id",token}}));};
        const auto update=[&](const juce::String& token,double gain){auto value=initial.clone();value.getDynamicObject()->setProperty("makeup_db",gain);return run("update_native_effect_gesture",object({{"gesture_id",token},{"state",value}}));};
        okay(test.saveProject(file,test.snapshot().revision),"save effect baseline");
        test.impl->edit->getUndoManager().clearUndoHistory();rev=test.snapshot().revision;const auto cleanKey=test.impl->currentKey;
        auto token=begin();okay(finish("end_native_effect_gesture",token),"unchanged gesture ends");
        check(test.snapshot().revision==rev&&!test.snapshot().canUndo&&!test.snapshot().dirty,"unchanged gesture does not create history");
        token=begin();
        auto invalidState=initial.clone();invalidState.getDynamicObject()->setProperty("makeup_db",true);
        check(run("update_native_effect_gesture",object({{"gesture_id",token},{"state",invalidState}})).failed(),"gesture rejects boolean numeric parameter");
        check(test.snapshot().revision==rev&&double(effectState()["makeup_db"])==0.0,"invalid preview cannot change committed value");
        for(int step=0;step<30;++step)okay(update(token,double(step+1)/5.0),"preview continuous change");
        check(test.snapshot().revision==rev&&!test.snapshot().dirty&&test.impl->currentKey==cleanKey,"preview does not dirty or revise project");
        check(double(effectState()["makeup_db"])==0.0&&!test.snapshot().canUndo,"preview leaves committed parameters and Undo untouched");
        check(renderedLevel()>level*1.9f,"preview is audible in offline native DSP output");
        check(finish("cancel_native_effect_gesture","wrong-token").failed()&&test.impl->effectGesture.has_value(),"wrong token cannot cancel active draft");
        okay(finish("end_native_effect_gesture",token),"commit continuous gesture");
        check(test.snapshot().revision==rev+1&&double(effectState()["makeup_db"])==6.0,"gesture commits one revision and final value");
        check(test.impl->edit.get()==nativeEdit&&test.impl->find(id)->track==nativeTrack&&test.impl->livePlugin(*nativeEdit,device)==effect,"gesture keeps Edit, track and DSP instance");
        okay(test.undo(test.snapshot().revision),"one Undo for entire drag");check(double(effectState()["makeup_db"])==0.0&&!test.snapshot().canUndo,"single Undo restores gesture start");
        check(std::abs(renderedLevel()-level)<.01f,"Undo restores native DSP parameters");
        okay(test.redo(test.snapshot().revision),"gesture Redo");check(double(effectState()["makeup_db"])==6.0,"Redo restores final drag value");
        token=begin();okay(update(token,2.0),"preview before cancel");rev=test.snapshot().revision;const auto undoName=test.impl->edit->getUndoManager().getUndoDescription();
        okay(finish("cancel_native_effect_gesture",token),"cancel gesture");check(test.snapshot().revision==rev&&double(effectState()["makeup_db"])==6.0&&test.impl->edit->getUndoManager().getUndoDescription()==undoName,"cancel preserves committed value and Undo");
        check(renderedLevel()>level*1.9f,"cancel restores committed DSP output");
        token=begin();okay(update(token,3.0),"preview before external edit");okay(run("rename_track",object({{"track_id",id},{"name","External rename"}})),"external edit cancels preview");
        check(finish("end_native_effect_gesture",token).failed()&&test.snapshot().tracks.front().name=="External rename"&&double(effectState()["makeup_db"])==6.0,"stale finish never overwrites external edit");
        token=begin();okay(update(token,4.0),"preview before save");okay(test.saveProject(file,test.snapshot().revision),"save cancels pending preview");
        check(!test.impl->effectGesture&&double(effectState()["makeup_db"])==6.0,"save keeps committed effect and stops preview");
        token=begin();okay(update(token,1.0),"preview before asynchronous save");
        const auto asyncFile=outputDirectory.getChildFile("async-colour-and-effect.emproj");
        const auto accepted=test.executeRequest(object({{"request_id","workspace-save"},{"project_id",test.snapshot().projectId},
            {"expected_revision",juce::int64(test.snapshot().revision)},{"command","save_project"},{"args",object({{"path",asyncFile.getFullPathName()}})}}));
        check(accepted["status"].toString()=="accepted"&&!test.impl->effectGesture,"interactive save accepts job and cancels preview");
        const auto jobId=accepted["result"]["job_id"].toString();
        const auto deadline=juce::Time::getMillisecondCounterHiRes()+10000;juce::var savedJob;
        do{
            juce::MessageManager::getInstance()->runDispatchLoopUntil(10);test.impl->reapFinishedJobs(true);
            savedJob=test.executeRequest(object({{"command","get_job"},{"args",object({{"job_id",jobId}})}}))["result"];
        }while(savedJob["status"].toString()!="completed"&&savedJob["status"].toString()!="failed"&&juce::Time::getMillisecondCounterHiRes()<deadline);
        check(savedJob["status"].toString()=="completed","interactive save finishes: "+savedJob["error"].toString());
        storage::StoredProject asyncSaved;okay(storage::load(asyncFile,asyncSaved),"load asynchronous saved manifest");
        native_effects::Settings asyncEffect;okay(native_effects::decode(asyncSaved.tracks.front().plugins.front(),asyncEffect),"decode asynchronously saved effect");
        check(asyncSaved.tracks.front().colour=="#8844CC"&&asyncEffect.compressor.makeupDb==6.0f,"interactive save writes committed colour and effect");
        okay(test.openProject(file,test.snapshot().revision),"reopen effect and colour");check(colour()=="#8844CC"&&double(effectState()["makeup_db"])==6.0,"reopen keeps colour and committed effect");
        report.setProperty("checks",checks);report.setProperty("status","passed");report.setProperty("offline",true);report.setProperty("physical_audio",false);
        report.setProperty("dsp_fixture",object({{"sample_rate",48000},{"block_size",128},{"blocks_per_observation",32},{"input","synthetic constant 0.2 stereo"}}));
        return juce::Result::ok();
    }catch(const std::exception& e){report.setProperty("checks",checks);report.setProperty("status","failed");report.setProperty("error",e.what());return juce::Result::fail(e.what());}
}
