// Offline contract checks. No user project, plugin, model or physical device.
juce::Result EngineSession::runBatchRefsSmokeTest(juce::DynamicObject& report)
{
    requireControlThread();EngineSession test(false);int checks=0;
    const auto check=[&](bool value,const juce::String& label){
        if(!value)throw std::runtime_error(("Batch refs smoke: "+label).toStdString());++checks;
    };
    const auto okay=[&](const juce::Result& result,const juce::String& label){check(result.wasOk(),label+": "+result.getErrorMessage());};
    const auto command=[](const char* name,juce::var args,const juce::String& alias=juce::String()){
        auto value=object({{"command",name},{"args",args}});
        if(alias.isNotEmpty())value.getDynamicObject()->setProperty("as",alias);return value;
    };
    const auto batch=[](std::initializer_list<juce::var> children){
        juce::Array<juce::var> values;for(const auto& child:children)values.add(child);return object({{"commands",values}});
    };
    const auto note=[](const char* id,int pitch){return object({{"id",id},{"pitch",pitch},{"start_beats",0.0},
        {"length_beats",1.0},{"velocity",80},{"channel",1}});};
    const auto request=[&](const juce::var& args,const juce::String& id){
        const auto state=test.snapshot();return object({{"request_id",id},{"project_id",state.projectId},
            {"expected_revision",juce::int64(state.revision)},{"command","batch"},{"args",args}});
    };
    try{
        check(bool(test.capabilities()["batch_result_refs"])&&int(test.capabilities()["batch_result_refs_version"])==1,"versioned capability advertised");
        // Existing GUI/public three-argument callers remain valid.
        okay(test.execute("set_tempo",object({{"bpm",120.0}}),test.snapshot().revision),"legacy execute signature");
        const auto initial=test.snapshot();
        check(test.impl->edit->state.getChildWithName(te::IDs::SCENES).isValid(),"native scene container initialized before user edits");
        auto canonicalRoot=test.impl->edit->state.createCopy();te::TrackList::sortTracksByType(canonicalRoot,nullptr);
        check(canonicalRoot.isEquivalentTo(test.impl->edit->state),"initial host metadata respects native root ordering");
        const auto create=batch({
            command("create_track",object({{"kind","instrument"},{"name","Batch fixture"}}),"track"),
            command("create_midi_clip",object({{"track_id","@track"},{"start_beats",0.0},{"length_beats",4.0}}),"clip"),
            command("write_notes",object({{"clip_id","@clip"},{"notes",juce::Array<juce::var>{note("batch-source-note",60)}}}))});
        const auto envelope=request(create,"batch-create-chain");const auto created=test.executeRequest(envelope);
        check(created["status"].toString()=="completed","create track / clip / notes commits");
        const auto refs=created["result"]["refs"];const auto trackId=refs["track"].toString(),clipId=refs["clip"].toString();
        check(trackId.isNotEmpty()&&clipId.isNotEmpty()&&trackId!=clipId&&!trackId.startsWithChar('@')&&!clipId.startsWithChar('@'),"engine generated distinct actual IDs");
        check(int(created["result"]["executed_commands"])==3,"executed child count");
        auto state=test.snapshot();
        check(state.revision==initial.revision+1&&state.tracks.size()==1&&state.tracks[0].id==trackId,"one revision and actual track ref");
        check(state.tracks[0].clips.size()==1&&state.tracks[0].clips[0].id==clipId&&state.tracks[0].clips[0].notes->size()==1
            &&state.tracks[0].clips[0].notes->front().pitch==60,"clip ref and written notes match");
        // JSONL and sidebar requests return to the message loop between apply
        // and Undo. Immediate same-stack checks miss deferred native writes that
        // can otherwise create a second, musically empty Undo transaction.
        struct DeferredProperties final:juce::ValueTree::Listener{
            juce::StringArray fields;
            void valueTreePropertyChanged(juce::ValueTree& tree,const juce::Identifier& field)override{
                fields.addIfNotAlreadyThere(tree.getType().toString()+"."+field.toString());
            }
            void valueTreeChildAdded(juce::ValueTree& parent,juce::ValueTree& child)override{
                fields.addIfNotAlreadyThere(parent.getType().toString()+" + "+child.getType().toString());
            }
            void valueTreeChildRemoved(juce::ValueTree& parent,juce::ValueTree& child,int)override{
                fields.addIfNotAlreadyThere(parent.getType().toString()+" - "+child.getType().toString());
            }
            void valueTreeChildOrderChanged(juce::ValueTree& parent,int from,int to)override{
                fields.addIfNotAlreadyThere(parent.getType().toString()+" order "+juce::String(from)+" -> "+juce::String(to)+" ("+parent.getChild(to).getType().toString()+")");
            }
        } deferred;
        test.impl->edit->state.addListener(&deferred);
        juce::MessageManager::getInstance()->runDispatchLoopUntil(150);
        test.impl->edit->state.removeListener(&deferred);
        report.setProperty("deferred_native_properties",deferred.fields.joinIntoString(", "));
        check(test.impl->edit->getUndoManager().getUndoDescription()=="batch","deferred native updates remain in batch transaction");
        // Keep only ValueTree handles, not Clip/Track objects, so listeners can
        // also observe native updates to nodes detached by Undo.
        std::vector<juce::ValueTree> observedNodes;
        const auto retainNodes=[&](auto&& self,juce::ValueTree node)->void{
            observedNodes.push_back(node);for(auto child:node)self(self,child);
        };
        retainNodes(retainNodes,test.impl->edit->state);
        okay(test.undo(state.revision),"one batch Undo");check(test.snapshot().tracks.empty(),"one Undo removes entire dependency chain");
        report.setProperty("redo_available_immediately_after_undo",test.impl->edit->getUndoManager().canRedo());
        deferred.fields.clear();for(auto& node:observedNodes)node.addListener(&deferred);
        juce::MessageManager::getInstance()->runDispatchLoopUntil(150);
        for(auto& node:observedNodes)node.removeListener(&deferred);
        report.setProperty("deferred_after_undo_properties",deferred.fields.joinIntoString(", "));
        report.setProperty("redo_available_after_dispatch",test.impl->edit->getUndoManager().canRedo());
        juce::Array<const juce::UndoableAction*> afterUndoActions;
        test.impl->edit->getUndoManager().getActionsInCurrentTransaction(afterUndoActions);
        juce::StringArray afterUndoActionTypes;
        for(const auto* action:afterUndoActions)afterUndoActionTypes.addIfNotAlreadyThere(typeid(*action).name());
        report.setProperty("deferred_after_undo_action_count",afterUndoActions.size());
        report.setProperty("deferred_after_undo_action_types",afterUndoActionTypes.joinIntoString(", "));
        check(test.impl->edit->getUndoManager().canRedo(),"Redo survives deferred updates after Undo");
        okay(test.redo(test.snapshot().revision),"one batch Redo");
        juce::MessageManager::getInstance()->runDispatchLoopUntil(150);
        check(test.snapshot().tracks[0].clips[0].id==clipId,"Redo preserves generated IDs");
        okay(test.undo(test.snapshot().revision),"one Undo after deferred Redo updates");
        check(test.snapshot().tracks.empty(),"Redo does not introduce a trailing phantom Undo");
        okay(test.redo(test.snapshot().revision),"restore dependency chain after asynchronous Undo check");
        const auto replayRevision=test.snapshot().revision;const auto replay=test.executeRequest(envelope);
        check(replay["status"].toString()=="completed"&&replay["result"]["refs"]["clip"].toString()==clipId
            &&test.snapshot().revision==replayRevision,"idempotent request returns original refs without replay");

        // Controller injection belongs only to this isolated fixture. Production
        // duplicate/write/edit paths must preserve the controller data below.
        auto* native=dynamic_cast<te::MidiClip*>(test.impl->findClip(clipId)->clip.get());
        auto* pedal=native->getSequence().addControllerEvent(te::BeatPosition::fromBeats(0.5),64,127,nullptr);
        pedal->state.setProperty(emId,"batch-pedal",nullptr);test.impl->recordEdit();
        test.impl->edit->getUndoManager().clearUndoHistory();
        juce::var duplicateResult;
        okay(test.execute("batch",batch({command("duplicate_clips",object({{"clip_ids",juce::Array<juce::var>{clipId}}}),"copy")}),
            test.snapshot().revision,&duplicateResult),"duplicate one clip with result alias");
        const auto copyId=duplicateResult["refs"]["copy"].toString();auto copied=test.impl->capture();
        const auto* copy=storedClip(copied,copyId);const auto* original=storedClip(copied,clipId);
        check(copy&&original&&copyId!=clipId&&copy->notes.size()==1&&copy->notes[0].id!=original->notes[0].id,"duplicate rekeys note IDs");
        check(copy->controllers.size()==1&&copy->controllers[0].id!=original->controllers[0].id
            &&copy->controllers[0].type==64&&copy->controllers[0].value==127,"duplicate rekeys and preserves controllers");
        okay(test.undo(test.snapshot().revision),"Undo duplicate fixture");

        const auto rewrite=batch({
            command("duplicate_clips",object({{"clip_ids",juce::Array<juce::var>{clipId}}}),"clone"),
            command("write_notes",object({{"clip_id","@clone"},{"notes",juce::Array<juce::var>{note("batch-clone-note",67)}}}))});
        juce::var rewriteResult;const auto rewriteBefore=test.snapshot();
        okay(test.execute("batch",rewrite,rewriteBefore.revision,&rewriteResult),"duplicate then replace cloned notes");
        const auto cloneId=rewriteResult["refs"]["clone"].toString();auto rewritten=test.impl->capture();
        const auto* clone=storedClip(rewritten,cloneId);original=storedClip(rewritten,clipId);
        check(clone&&clone->notes.size()==1&&clone->notes[0].pitch==67&&original->notes[0].pitch==60,"only cloned notes modified");
        check(clone->controllers.size()==1&&clone->controllers[0].value==127&&clone->controllers[0].beats==0.5,"write_notes preserves cloned controllers");
        const auto controllerId=clone->controllers[0].id;
        okay(test.execute("edit_notes",object({{"clip_id",cloneId},{"upsert",juce::Array<juce::var>{note("batch-clone-note",69)}}}),
            test.snapshot().revision),"edit_notes on cloned notes");
        rewritten=test.impl->capture();clone=storedClip(rewritten,cloneId);
        check(clone->notes[0].pitch==69&&clone->controllers.size()==1&&clone->controllers[0].id==controllerId,"edit_notes preserves controller identity");
        okay(test.undo(test.snapshot().revision),"Undo standalone note edit");
        okay(test.undo(test.snapshot().revision),"Undo duplicate and rewrite together");
        check(test.snapshot().tracks[0].clips.size()==1&&test.snapshot().tracks[0].clips[0].notes->front().pitch==60,"one Undo removes duplicate and all dependent changes");

        const auto destinationAlias=juce::String("D_9-")+juce::String::repeatedString("x",36);
        juce::var moveResult;
        okay(test.execute("batch",batch({
            command("duplicate_clips",object({{"clip_ids",juce::Array<juce::var>{clipId}}}),"copy_1"),
            command("create_track",object({{"kind","instrument"},{"name","Moved clone"}}),destinationAlias),
            command("move_clips",object({{"clip_ids",juce::Array<juce::var>{"@copy_1"}},
                {"target_track_id","@"+destinationAlias},{"delta_seconds",0.0}}))}),test.snapshot().revision,&moveResult),
            "array and target-track refs with 40-character alias");
        auto moved=test.impl->capture();storage::StoredTrack* movedParent=nullptr;
        const auto* movedClip=storedClip(moved,moveResult["refs"]["copy_1"].toString(),&movedParent);
        check(movedClip&&movedParent&&movedParent->id==moveResult["refs"][juce::Identifier(destinationAlias)].toString(),"typed refs resolve exact new parent");
        okay(test.undo(test.snapshot().revision),"Undo referenced cross-track move");
        check(test.snapshot().tracks.size()==1&&test.snapshot().tracks[0].clips.size()==1,"one Undo removes referenced move and new track");

        const auto rejected=[&](const juce::var& args,const juce::String& label){
            const auto before=test.snapshot();const auto contents=contentKey(test.impl->capture());
            const auto gestureBefore=test.impl->gesture;
            juce::var output=object({{"refs",object({{"old","must-not-leak"}})}});
            const auto result=test.execute("batch",args,before.revision,&output);const auto after=test.snapshot();
            check(result.failed(),label+" rejected");check(output.isVoid(),label+" returns no stale refs");
            check(after.revision==before.revision&&after.dirty==before.dirty&&after.canUndo==before.canUndo&&after.canRedo==before.canRedo
                &&after.undoDescription==before.undoDescription&&after.redoDescription==before.redoDescription
                &&test.impl->gesture==gestureBefore&&contentKey(test.impl->capture())==contents,label+" leaves music, gesture and Undo unchanged");
        };
        const auto newTrack=[&](const juce::String& alias){return command("create_track",object({{"kind","instrument"},{"name","Temporary"}}),alias);};
        rejected(batch({newTrack("temp"),command("create_midi_clip",object({{"track_id","@temp"},{"start_beats",0.0},{"length_beats",4.0}}),"later"),
            command("write_notes",object({{"clip_id","@later"},{"notes",juce::Array<juce::var>{note("bad-note",128)}}}))}),"invalid final command");
        rejected(batch({command("create_midi_clip",object({{"track_id","@later"},{"start_beats",0.0},{"length_beats",4.0}})),newTrack("later")}),"forward reference");
        rejected(batch({newTrack("same"),newTrack("same")}),"reused alias");
        rejected(batch({newTrack("track"),command("move_clip",object({{"clip_id","@track"},{"start_seconds",4.0}}))}),"track reference in clip field");
        rejected(batch({command("create_midi_clip",object({{"track_id",trackId},{"start_beats",4.0},{"length_beats",4.0}}),"clip"),
            command("move_clips",object({{"clip_ids",juce::Array<juce::var>{clipId}},{"target_track_id","@clip"},{"delta_seconds",0.0}}))}),"clip reference in track field");
        rejected(batch({command("rename_track",object({{"track_id","@track"},{"name","Not a prior-batch ref"}}))}),"cross-batch reference");
        rejected(batch({command("duplicate_clips",object({{"clip_ids",juce::Array<juce::var>{"@unknown"}}}),"copy")}),"unknown array reference");
        rejected(batch({command("duplicate_clips",object({{"clip_ids",juce::Array<juce::var>{clipId,clipId}}}),"copy")}),"ambiguous duplicate result");
        rejected(batch({command("rename_track",object({{"track_id",trackId},{"name","No result"}}),"unsupported")}),"alias on unsupported result");
        rejected(batch({newTrack("gone"),command("remove_track",object({{"track_id","@gone"}}))}),"removed reference target");
        rejected(batch({command("create_track",object({{"kind","instrument"},{"name","Injected"},{"id","caller-track"}}),"x")}),"caller-assigned track ID");
        rejected(batch({command("create_midi_clip",object({{"track_id",trackId},{"start_beats",4.0},{"length_beats",4.0},{"clip_id","caller-clip"}}),"x")}),"caller-assigned clip ID");
        rejected(batch({command("rename_track",object({{"track_id",true},{"name","Invalid type"}}))}),"boolean ID");
        rejected(batch({command("duplicate_clips",object({{"clip_ids",juce::Array<juce::var>{3}}}))}),"numeric array ID");
        rejected(batch({command("batch",batch({newTrack("nested")}))}),"nested batch");
        for(const auto& alias:juce::StringArray{"@injected","_hidden","bad.name","bad/path","bad name","1first",juce::String::repeatedString("a",41)})
            rejected(batch({newTrack(alias)}),"invalid alias "+alias);
        auto badAlias=newTrack("valid");badAlias.getDynamicObject()->setProperty("as",7);rejected(batch({badAlias}),"non-string alias");
        badAlias.getDynamicObject()->setProperty("as","");rejected(batch({badAlias}),"empty alias");
        auto badField=newTrack("valid");badField.getDynamicObject()->setProperty("result_id","injected");rejected(batch({badField}),"unknown child field");
        juce::var literalResult;
        okay(test.execute("batch",batch({command("rename_track",object({{"track_id",trackId},{"name","@literal-name"}}))}),
            test.snapshot().revision,&literalResult),"non-ID string remains literal");
        check(test.snapshot().tracks[0].name=="@literal-name"&&literalResult["refs"].getDynamicObject()->getProperties().size()==0
            &&int(literalResult["executed_commands"])==1,"non-ID strings are never interpolated");
        const auto failedResponse=test.executeRequest(request(batch({command("move_clip",object({{"clip_id","@previous"},{"start_seconds",1.0}}))}),"batch-failed-result"));
        check(failedResponse["status"].toString()=="failed"&&failedResponse["result"].isVoid(),"protocol failure has no refs");
        const auto gainBefore=test.snapshot().tracks[0].gainDb;const auto bpmBefore=test.snapshot().bpm;
        test.beginEditGesture();
        okay(test.setTrackGain(trackId,-1.0f,test.snapshot().revision),"start gesture before rejected batch");
        rejected(batch({newTrack("failedGesture"),command("set_tempo",object({{"bpm",999.0}}))}),"invalid batch during active gesture");
        okay(test.setTrackGain(trackId,-2.0f,test.snapshot().revision),"continue original gesture after rejected batch");
        test.endEditGesture();okay(test.undo(test.snapshot().revision),"Undo original uninterrupted gesture");
        check(test.snapshot().tracks[0].gainDb==gainBefore,"failed batch does not split an active gesture Undo");
        test.beginEditGesture();
        okay(test.setTrackGain(trackId,-3.0f,test.snapshot().revision),"preceding GUI gesture edit");
        okay(test.execute("batch",batch({command("set_tempo",object({{"bpm",100.0}}))}),test.snapshot().revision),"batch during GUI gesture");
        okay(test.undo(test.snapshot().revision),"Undo batch separate from gesture");
        check(test.snapshot().bpm==bpmBefore&&test.snapshot().tracks[0].gainDb==-3.0f,"batch Undo leaves preceding gesture intact");
        okay(test.undo(test.snapshot().revision),"Undo prior gesture separately");
        check(test.snapshot().tracks[0].gainDb==gainBefore,"prior gesture remains independently undoable");
        report.setProperty("status","passed");report.setProperty("checks",checks);
        report.setProperty("offline",true);report.setProperty("physical_devices",false);return juce::Result::ok();
    }catch(const std::exception& error){
        report.setProperty("status","failed");report.setProperty("checks",checks);report.setProperty("error",error.what());
        return juce::Result::fail(error.what());
    }
}
