// Dedicated CLI test. Use an exact pre-scanned catalog ID and a fresh directory.
// No playback, editor, secondary EngineSession or physical input is opened.
juce::Result EngineSession::runPluginNotificationSmoke(const juce::File& directory,const juce::String& catalogId)
{
    requireControlThread();
    if(directory==juce::File()||directory.exists()||!directory.getParentDirectory().isDirectory())
        return juce::Result::fail("Plugin notification test requires a fresh directory in an existing parent.");
    if(auto result=directory.createDirectory();result.failed())return result;
    auto report=object({{"status","running"},{"catalog_id",catalogId},{"workspace",directory.getFullPathName()},
        {"scope","Real raw parameter notifications and forced automation echo; no native editor or playback coverage."}});
    juce::Array<juce::var> observations,checks;juce::StringArray failures;juce::String stage="setup";
    const auto require=[](bool condition,const juce::String& message){if(!condition)throw std::runtime_error(message.toStdString());};
    const auto verify=[&](bool condition,const juce::String& message){checks.add(object({{"check",message},{"passed",condition}}));if(!condition)failures.add(message);};
    const auto pump=[](int milliseconds){
        const auto deadline=juce::Time::getMillisecondCounterHiRes()+milliseconds;
        while(juce::Time::getMillisecondCounterHiRes()<deadline)
            juce::MessageManager::getInstance()->runDispatchLoopUntil(10);
    };
    const auto command=[&](const juce::String& name,juce::var arguments){
        auto result=execute(name,arguments,snapshot().revision);require(result.wasOk(),name+": "+result.getErrorMessage());
    };
    try{
        require(!impl->edit->getTransport().isPlaying(),"Test session must start stopped.");
        juce::PluginDescription description;
        require(impl->pluginHost.getDescription(catalogId,description),"Exact catalog ID is unavailable; explicitly scan the module first.");
        report.getDynamicObject()->setProperty("plugin",object({{"name",description.name},{"format",description.pluginFormatName},
            {"module",description.fileOrIdentifier},{"version",description.version},{"unique_id",description.uniqueId}}));
        auto fresh=newProject(snapshot().revision);require(fresh.wasOk(),fresh.getErrorMessage());
        command("create_track",object({{"kind",description.isInstrument?"instrument":"audio"},{"name","Notification regression"}}));
        const auto trackId=snapshot().tracks.back().id;
        command("add_plugin",object({{"track_id",trackId},{"catalog_id",catalogId}}));pump(300);
        const auto pluginId=snapshot().tracks.back().plugins.front().id;
        auto* external=impl->loadedPlugin(*impl->edit,pluginId);require(external!=nullptr,"Native plugin failed to load.");
        auto* processor=external->getAudioPluginInstance();require(processor!=nullptr,"Native processor is unavailable.");
        report.getDynamicObject()->setProperty("plugin_id",pluginId);
        report.getDynamicObject()->setProperty("parameter_count",processor->getParameters().size());
        stage="runtime module identity";
        {
            struct RestoreDescription {
                te::ExternalPlugin& plugin;juce::PluginDescription original;
                ~RestoreDescription(){plugin.desc=std::move(original);}
            } restore{*external,external->desc};
            // TE prepareToPlay performs this same assignment. Using the real
            // instance descriptor exercises bundle/binary aliases without
            // starting playback or relying on fabricated plugin metadata.
            external->desc=processor->getPluginDescription();
            storage::StoredPlugin canonical;canonical.id=pluginId;
            const auto captured=plugins::PluginHost::capture(*external,canonical,false);
            observations.add(object({{"stage","runtime_identity"},{"scanned",description.fileOrIdentifier},
                {"runtime",external->desc.fileOrIdentifier},{"captured",canonical.identifier}}));
            verify(captured.wasOk()&&juce::File(canonical.identifier)==juce::File(description.fileOrIdentifier)
                &&canonical.uniqueId==description.uniqueId&&canonical.deprecatedUniqueId==description.deprecatedUid,
                "Runtime descriptor captures the exact canonical scanned module and class");
            verify(plugins::PluginHost::matchesCachedIdentity(*external),"Actual runtime module alias retains Undo cache identity");
            const auto runtime=external->desc;
            if(runtime.fileOrIdentifier!=description.fileOrIdentifier){
                require(plugins::PluginHost::capture(*external,canonical,true).wasOk(),"Capture native state for legacy module alias regression");
                auto legacy=canonical;legacy.id=uid();legacy.identifier=runtime.fileOrIdentifier;
                juce::Result loaded=juce::Result::ok();
                {
                    auto instance=impl->pluginHost.instantiate(*impl->edit,legacy,loaded);
                    storage::StoredPlugin restored;restored.id=legacy.id;
                    verify(instance&&loaded.wasOk()&&plugins::PluginHost::capture(*instance,restored,false).wasOk()
                        &&restored.identifier==description.fileOrIdentifier,
                        "Legacy exact runtime binary alias loads through scanned catalog and captures canonical identity");
                }
                const auto rejectsLegacy=[&](storage::StoredPlugin rejected,const juce::String& label){
                    rejected.id=uid();const auto beforeState=rejected.state;
                    auto instance=impl->pluginHost.instantiate(*impl->edit,rejected,loaded);
                    verify(!instance&&loaded.failed()&&rejected.state==beforeState,label+" keeps missing-plugin state intact");
                };
                auto rejected=legacy;rejected.identifier=juce::File(description.fileOrIdentifier)
                    .getChildFile("Contents/x86_64-win/nested").getChildFile(juce::File(description.fileOrIdentifier).getFileName()).getFullPathName();
                rejectsLegacy(rejected,"Noncanonical nested binary");
                rejected=legacy;rejected.uniqueId^=1;rejectsLegacy(rejected,"Legacy alias with wrong class UID");
                rejected=legacy;rejected.version+="-mismatch";rejectsLegacy(rejected,"Legacy alias with wrong positional-state version");
            }
            const auto rejects=[&](const juce::PluginDescription& changed,const juce::String& label){
                external->desc=changed;auto untouched=canonical;
                const auto result=plugins::PluginHost::capture(*external,untouched,false);
                verify(!plugins::PluginHost::matchesCachedIdentity(*external)&&result.failed()
                    &&untouched.identifier==canonical.identifier&&untouched.uniqueId==canonical.uniqueId,
                    label+" is rejected without replacing captured metadata");
            };
            auto mismatch=runtime;mismatch.fileOrIdentifier=directory.getChildFile("other-module.vst3").getFullPathName();
            rejects(mismatch,"Different runtime module");
            mismatch=runtime;mismatch.uniqueId^=1;rejects(mismatch,"Different runtime class UID");
            mismatch=runtime;mismatch.deprecatedUid^=1;rejects(mismatch,"Different runtime legacy UID");
            mismatch=runtime;mismatch.pluginFormatName=runtime.pluginFormatName=="VST3"?"VST":"VST3";
            rejects(mismatch,"Different runtime plugin format");
            mismatch=runtime;mismatch.version+="-mismatch";rejects(mismatch,"Different positional-state plugin version");
            mismatch=runtime;mismatch.isInstrument=!runtime.isInstrument;rejects(mismatch,"Different runtime plugin role");
        }
        const auto waitCurrentJob=[&]{
            require(!impl->jobs.empty(),"File operation did not create a job.");const auto job=impl->jobs.back();
            const auto deadline=juce::Time::getMillisecondCounterHiRes()+15000;
            while(job->worker.joinable()&&juce::Time::getMillisecondCounterHiRes()<deadline)pump(10);
            require(!job->worker.joinable(),"Timed out waiting for the file operation.");
            {std::lock_guard lock(job->mutex);require(job->status=="completed","File operation failed: "+job->error);}
        };
        const auto saveClean=[&](const juce::String& label){
            stage=label;command("save_project",object({{"path",directory.getChildFile(label+".emproj").getFullPathName()}}));
            waitCurrentJob();
            pump(200);require(!snapshot().dirty,"Plugin did not settle to clean state after saving.");
        };
        saveClean("before-notifications");
        stage="same-value callbacks";
        const auto before=snapshot();const auto generation=impl->pluginHost.changeGeneration(pluginId);
        int notificationCount=0;
        for(int round=0;round<2;++round){
            for(auto* raw:processor->getParameters()){
                const auto value=raw->getValue();require(std::isfinite(value),"Plugin exposes a nonfinite parameter.");
                // This enters JUCE's actual listener dispatcher; a same-value
                // set_plugin_parameter command would return before this path.
                raw->sendValueChangedMessageToListeners(value);++notificationCount;
            }
            pump(250);const auto after=snapshot();const auto now=impl->pluginHost.changeGeneration(pluginId);
            observations.add(object({{"stage","same_value"},{"round",round+1},{"notifications",notificationCount},
                {"generation",juce::int64(now)},{"revision",juce::int64(after.revision)},{"dirty",after.dirty}}));
            verify(now==generation,"Same-value round "+juce::String(round+1)+" leaves change generation unchanged");
            verify(after.revision==before.revision,"Same-value round "+juce::String(round+1)+" leaves project revision unchanged");
            verify(!after.dirty,"Same-value round "+juce::String(round+1)+" leaves project clean");
        }
        require(notificationCount>0,"Plugin has no raw parameters to notify.");

        stage="choose continuous parameter";
        juce::AudioProcessorParameter* selected=nullptr;te::AutomatableParameter* parameter=nullptr;
        juce::String parameterId,parameterName;int best=100;
        const juce::StringArray excluded{"bypass","mute","solo","preset","program","bank","random","reset","init","license","licence","auth","load","save","file","enable","power","on/off"};
        for(int index=0;index<processor->getParameters().size();++index){
            auto* raw=processor->getParameters()[index];const auto name=raw->getName(256);
            if(raw->isDiscrete()||raw->isBoolean()||raw->isMetaParameter()||!raw->isAutomatable()||raw->getNumSteps()<4096)continue;
            if(std::any_of(excluded.begin(),excluded.end(),[&](const auto& word){return name.containsIgnoreCase(word);}))continue;
            const auto id=[&]{if(auto* named=dynamic_cast<juce::AudioProcessorParameterWithID*>(raw))return named->paramID;return juce::String(index);}();
            auto* target=exposedParameter(external,id);if(!target||!target->isParameterActive())continue;
            const auto value=raw->getValue();if(!std::isfinite(value)||value<0||value>1)continue;
            const int rank=name.containsIgnoreCase("volume")||name.containsIgnoreCase("gain")?0:
                name.containsIgnoreCase("mix")||name.containsIgnoreCase("cutoff")?1:2;
            if(rank<best){best=rank;selected=raw;parameter=target;parameterId=id;parameterName=name;}
        }
        require(selected&&parameter,"No suitable continuous parameter; choose another explicit test plugin.");
        const auto refreshSelected=[&]{
            require(impl->loadedPlugin(*impl->edit,pluginId)==external,"Plugin instance changed during notification test.");
            selected=nullptr;
            for(int index=0;index<processor->getParameters().size();++index){
                auto* raw=processor->getParameters()[index];auto* named=dynamic_cast<juce::AudioProcessorParameterWithID*>(raw);
                if((named?named->paramID:juce::String(index))==parameterId){selected=raw;break;}
            }
            parameter=exposedParameter(external,parameterId);
            require(selected&&parameter,"Selected parameter disappeared while pumping plugin callbacks.");
        };
        report.getDynamicObject()->setProperty("parameter",object({{"id",parameterId},{"name",parameterName}}));
        saveClean("before-real-change");refreshSelected();stage="real raw parameter change";
        const auto original=selected->getValue();const float changed=original<0.97f?original+0.013f:original-0.013f;
        const auto beforeChange=snapshot();const auto beforeGeneration=impl->pluginHost.changeGeneration(pluginId);
        selected->setValueNotifyingHost(changed);
        verify(impl->pluginHost.hasPendingChanges(),"Real raw change is visible before the timer drains it");
        verify(snapshot().dirty,"Snapshot sees a pending real plugin change immediately");
        pump(250);refreshSelected();
        const auto afterChange=snapshot();const auto afterGeneration=impl->pluginHost.changeGeneration(pluginId);
        observations.add(object({{"stage","real_change"},{"before_value",original},{"requested",changed},{"observed",selected->getValue()},
            {"generation_before",juce::int64(beforeGeneration)},{"generation_after",juce::int64(afterGeneration)},
            {"revision_before",juce::int64(beforeChange.revision)},{"revision_after",juce::int64(afterChange.revision)},{"dirty",afterChange.dirty}}));
        verify(std::abs(selected->getValue()-original)>1.0e-5f,"Real raw parameter value changes");
        verify(afterGeneration>beforeGeneration,"Real raw change advances change generation");
        verify(afterChange.revision>beforeChange.revision&&afterChange.dirty,"Real raw change advances revision and marks dirty");

        stage="prepare automation echo";
        const auto explicitBefore=parameter->getCurrentExplicitValue();
        const auto start=parameter->valueRange.convertTo0to1(explicitBefore);
        const float automated=start<0.96f?start+0.023f:start-0.023f;
        juce::Array<juce::var> points{object({{"id",uid()},{"time_seconds",0.0},{"value",start},{"curve",0.0}}),
            object({{"id",uid()},{"time_seconds",1.0},{"value",automated},{"curve",0.0}})};
        const auto laneId=uid();
        command("set_automation_lane",object({{"track_id",trackId},{"lane_id",laneId},{"target","plugin_parameter"},
            {"plugin_id",pluginId},{"parameter_id",parameterId},{"enabled",true},{"points",points}}));
        saveClean("before-automation-echo");refreshSelected();stage="forced automation echo";
        const auto beforeEcho=snapshot();const auto echoGeneration=impl->pluginHost.changeGeneration(pluginId);
        const auto base=parameter->getCurrentExplicitValue();
        parameter->updateToFollowCurve(te::TimePosition::fromSeconds(1.0));
        const auto applied=selected->getValue();const auto baseBeforeEcho=parameter->getCurrentExplicitValue();
        require(std::abs(applied-automated)<1.0e-4f&&std::abs(applied-start)>1.0e-5f,"Automation did not apply the distinct test value.");
        verify(baseBeforeEcho==base,"Host automation alone preserves explicit base value");
        selected->sendValueChangedMessageToListeners(applied);pump(300);refreshSelected();
        const auto afterEcho=snapshot();const auto finalGeneration=impl->pluginHost.changeGeneration(pluginId);
        observations.add(object({{"stage","automation_echo"},{"explicit_before",base},{"explicit_before_echo",baseBeforeEcho},
            {"explicit_after",parameter->getCurrentExplicitValue()},{"applied",applied},{"current_after",parameter->getCurrentValue()},
            {"generation_before",juce::int64(echoGeneration)},{"generation_after",juce::int64(finalGeneration)},
            {"revision_before",juce::int64(beforeEcho.revision)},{"revision_after",juce::int64(afterEcho.revision)},{"dirty",afterEcho.dirty}}));
        verify(parameter->getCurrentExplicitValue()==base,"Automation echo preserves explicit base value");
        verify(finalGeneration==echoGeneration,"Automation echo does not create an edit generation");
        verify(afterEcho.revision==beforeEcho.revision&&!afterEcho.dirty,"Automation echo leaves revision and dirty unchanged");
        verify(!afterEcho.playing,"Notification test never starts playback");

        stage="save automated parameter base";
        parameter->updateToFollowCurve(te::TimePosition::fromSeconds(1.0));
        const auto rawBeforeSave=selected->getValue();
        saveClean("automation-base-roundtrip");refreshSelected();
        verify(std::abs(selected->getValue()-rawBeforeSave)<1.0e-5f,"Capturing explicit base does not rewrite the live automated parameter");
        stage="reopen automated parameter base";
        command("open_project",object({{"path",directory.getChildFile("automation-base-roundtrip.emproj").getFullPathName()}}));
        waitCurrentJob();pump(200);
        external=impl->loadedPlugin(*impl->edit,pluginId);require(external!=nullptr,"Saved native plugin did not reopen.");
        processor=external->getAudioPluginInstance();refreshSelected();
        const auto reopened=impl->capture();
        const auto track=std::find_if(reopened.tracks.begin(),reopened.tracks.end(),[&](const auto& item){return item.id==trackId;});
        require(track!=reopened.tracks.end(),"Saved automation track disappeared.");
        const auto lane=std::find_if(track->automation.begin(),track->automation.end(),[&](const auto& item){return item.id==laneId;});
        const bool lanePreserved=lane!=track->automation.end()&&lane->points.size()==2&&lane->pluginId==pluginId
            &&lane->parameterId==parameterId&&lane->points[0].id==points[0].getProperty("id",{}).toString()
            &&lane->points[1].id==points[1].getProperty("id",{}).toString()
            &&std::abs(lane->points[0].value-start)<1.0e-5f&&std::abs(lane->points[1].value-automated)<1.0e-5f;
        observations.add(object({{"stage","automation_base_roundtrip"},{"explicit_expected",base},
            {"raw_at_save",rawBeforeSave},{"explicit_reopened",parameter->getCurrentExplicitValue()},{"lane_preserved",lanePreserved},
            {"dirty",snapshot().dirty}}));
        verify(std::abs(parameter->getCurrentExplicitValue()-base)<1.0e-5f,"Save/reopen preserves explicit base rather than automated instant");
        verify(lanePreserved,"Save/reopen preserves managed plugin lane and stable point IDs");
        verify(!snapshot().dirty&&!snapshot().playing,"Reopened automated project stays clean and stopped");
    }catch(const std::exception& error){failures.add(stage+": "+error.what());}
    catch(...){failures.add(stage+": unexpected failure");}
    report.getDynamicObject()->setProperty("status",failures.isEmpty()?"passed":"failed");
    report.getDynamicObject()->setProperty("last_stage",stage);report.getDynamicObject()->setProperty("observations",observations);
    report.getDynamicObject()->setProperty("checks",checks);report.getDynamicObject()->setProperty("error",failures.joinIntoString("; "));
    if(!directory.getChildFile("report.json").replaceWithText(juce::JSON::toString(report,true)))return juce::Result::fail("Could not write plugin notification test report.");
    return failures.isEmpty()?juce::Result::ok():juce::Result::fail(failures.joinIntoString("; "));
}
