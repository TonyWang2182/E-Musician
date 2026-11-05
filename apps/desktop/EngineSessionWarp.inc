// Fixed-ratio Warp preparation runs only on a file worker. The live Edit owns
// the sole musical state; rendered assets are immutable and included in Save.
juce::Result EngineSession::Impl::getAudioWarp(const juce::var& args,juce::var& out)
{
    requireControlThread();
    if(!args.isObject())return fail("Warp arguments must be an object.");
    std::vector<juce::String> ids;try{ids=idsArg(args,"clip_ids");}catch(const std::exception& e){return fail(e.what());}
    if(ids.empty()&&args["clip_id"].isString())ids.push_back(args["clip_id"].toString());
    std::set<juce::String> wanted(ids.begin(),ids.end());
    if(wanted.size()!=ids.size())return fail("Warp clip IDs must be unique.");
    juce::Array<juce::var> items;
    for(const auto& track:bindings)for(const auto& clip:track.clips){
        if(!ids.empty()&&!wanted.contains(clip.id))continue;
        if(!dynamic_cast<te::WaveAudioClip*>(clip.clip.get())){if(!ids.empty())return fail("Warp needs audio clips.");continue;}
        storage::StoredAudioWarp warp;const auto v=clip.clip->state.getProperty("emAudioWarp",{});
        if(!v.isVoid())if(auto r=storage::audioWarpFromVar(v,warp);r.failed())return r;
        const auto pos=clip.clip->getPosition();const auto ratio=warp.speedRatio();
        items.add(object({{"clip_id",clip.id},{"enabled",warp.enabled},{"source_bpm",warp.sourceBpm},{"target_bpm",warp.targetBpm},
            {"follow_tempo",warp.followTempo},{"mode",warp.mode},{"warp_speed_ratio",ratio},
            {"source_offset_seconds",pos.offset.inSeconds()*ratio},{"playback_source_offset_seconds",pos.offset.inSeconds()},
            {"timeline_start_seconds",pos.time.getStart().inSeconds()},{"duration_seconds",pos.time.getLength().inSeconds()},
            {"source_duration_seconds",clip.originalInfo.duration},{"playback_duration_seconds",clip.info.duration}}));
        wanted.erase(clip.id);
    }
    if(!wanted.empty())return fail("An audio Warp clip no longer exists.");out=object({{"items",items},{"fixed_ratio_only",true}});return juce::Result::ok();
}

juce::Result EngineSession::Impl::beginAudioWarp(const juce::var& args,juce::var* out,WarpFileValidation validateFiles,
    std::shared_ptr<const storage::StoredAnalysis> provenance,std::function<void(const juce::var&)> onApplied)
{
    if(!args.isObject())return fail("Warp arguments must be an object.");
    if(recordingBusy()||hasBlockingFileTask())return fail("Finish recording and file tasks before applying Warp.");
    const auto operation=args.getProperty("operation","warp").toString();
    if(operation!="warp"&&operation!="align_only")return fail("Unknown audio alignment operation.");
    const bool alignOnly=operation=="align_only";
    if(!alignOnly&&!args["enabled"].isBool())return fail("Warp enabled must be boolean.");
    const bool enabled=bool(args["enabled"]);
    if(args.hasProperty("follow_tempo")&&!args["follow_tempo"].isBool())return fail("follow_tempo must be boolean.");
    if(args.hasProperty("mode")&&args["mode"].toString()!="preserve_pitch")return fail("Only preserve_pitch Warp is supported.");
    const bool hasAlignment=args.hasProperty("first_beat_seconds")||args.hasProperty("align_start_seconds");
    const double first=number(args,"first_beat_seconds"), align=number(args,"align_start_seconds");
    if(hasAlignment&&(!std::isfinite(first)||first<0||!std::isfinite(align)||align<0))return fail("Alignment needs a non-negative clip-relative first beat and project destination.");
    std::vector<juce::String> ids;try{ids=idsArg(args,"clip_ids");}catch(const std::exception& e){return fail(e.what());}
    const std::set<juce::String> unique(ids.begin(),ids.end());
    if(ids.empty()||ids.size()>64||unique.size()!=ids.size())return fail("Choose 1 to 64 distinct audio clips.");
    auto state=capture();std::map<juce::String,storage::StoredClip> previous;
    for(const auto& id:ids){auto* clip=storedClip(state,id);if(!clip||clip->kind!="audio")return fail("Warp needs existing audio clips.");
        if(hasAlignment&&first>clip->duration)return fail("The first beat is outside a selected clip.");
        previous.emplace(id,*clip);if(alignOnly)clip->warp.followTempo=false;
    }
    auto selectedAfter=selectedClip;
    if(args.hasProperty("project_bpm"))if(auto r=mutate(state,"set_tempo",object({{"bpm",args["project_bpm"]}}),selectedAfter);r.failed())return r;
    if(args.hasProperty("numerator")||args.hasProperty("denominator"))
        if(auto r=mutate(state,"set_time_signature",object({{"numerator",args.getProperty("numerator",state.numerator)},
            {"denominator",args.getProperty("denominator",state.denominator)}}),selectedAfter);r.failed())return r;
    const double sourceBpm=number(args,"source_bpm"), targetBpm=number(args,"target_bpm",state.bpm);
    const bool follow=bool(args.getProperty("follow_tempo",true));
    if(!alignOnly&&enabled&&(!std::isfinite(sourceBpm)||sourceBpm<20||sourceBpm>300||!std::isfinite(targetBpm)||targetBpm<20||targetBpm>300))
        return fail("Source and target BPM must be between 20 and 300.");
    if(!alignOnly&&enabled&&follow&&std::abs(targetBpm-state.bpm)>1e-9)return fail("Following clips must target the project BPM.");
    for(const auto& id:ids){auto& clip=*storedClip(state,id);const auto& old=previous.at(id);
        if(!alignOnly){
            clip.warp=enabled?storage::StoredAudioWarp{true,follow,sourceBpm,targetBpm,"preserve_pitch",{},{},{}}:storage::StoredAudioWarp{};
            const double scale=old.warp.speedRatio()/clip.warp.speedRatio();clip.duration=old.duration*scale;
            clip.sourceOffset=old.sourceOffset;clip.fadeIn=old.fadeIn*scale;clip.fadeOut=old.fadeOut*scale;
        }
        if(hasAlignment)clip.timelineStart=align-first*old.warp.speedRatio()/clip.warp.speedRatio();
        if(!std::isfinite(clip.timelineStart)||clip.timelineStart<0||clip.timelineStart+clip.duration>storage::maximumTimelineSeconds)
            return fail("Alignment would place audio before zero or outside the project. Choose a later destination beat.");
    }
    if(provenance){
        if(std::any_of(state.analyses.begin(),state.analyses.end(),[&](const auto& a){return a.id==provenance->id;}))return fail("This analysis has already been applied.");
        state.analyses.push_back(*provenance);
    }
    juce::Array<juce::var> values;for(const auto& id:ids)values.add(id);
    return beginWarpCandidate(std::move(state),selectedAfter,object({{"clip_ids",values},{"operation",operation}}),out,std::move(validateFiles),std::move(onApplied));
}

juce::Result EngineSession::Impl::beginWarpCandidate(storage::StoredProject state,juce::String selectedAfter,juce::var receipt,
    juce::var* out,WarpFileValidation validateFiles,std::function<void(const juce::var&)> onApplied)
{
    if(recordingBusy()||hasBlockingFileTask())return fail("Finish recording and file tasks before applying Warp.");
    const auto previous=capture();
    auto job=startJob("set_audio_warp",[this,state=std::move(state),previous,selectedAfter,receipt=receipt.clone(),validateFiles=std::move(validateFiles),onApplied=std::move(onApplied)](const auto& job)mutable{
        const std::function<bool()> cancelled=[job]{return job->cancel.load();};
        if(validateFiles)if(auto r=validateFiles(cancelled);r.failed()){jobFailure(job,r);return;}
        std::map<juce::String,AudioInfo> sources;
        std::map<juce::String,storage::StoredAsset> originalAssets;for(const auto& asset:state.assets)originalAssets.emplace(asset.id,asset);
        std::map<juce::String,audio::WarpRender> rendered;
        std::map<juce::String,JobFingerprint> originals;
        // A new Warp/tempo edit must never silently adopt replacement media.
        // Check the immutable original identity even when this edit disables Warp.
        for(const auto& track:previous.tracks)for(const auto& clip:track.clips)if(clip.warp.enabled){
            const auto asset=originalAssets.find(clip.assetId);if(asset==originalAssets.end())continue;
            auto found=originals.find(clip.assetId);
            if(found==originals.end()){
                JobFingerprint current;
                if(auto r=fingerprint(asset->second.source,current,cancelled);r.failed()){jobFailure(job,r);return;}
                found=originals.emplace(clip.assetId,std::move(current)).first;
            }
            if(!found->second.exists||found->second.hash!=clip.warp.sourceHash){
                jobFailure(job,juce::Result::fail("Original Warp audio changed outside this project. Re-import it before applying Warp."));return;
            }
        }
        size_t count=0,index=0;for(const auto& track:state.tracks)for(const auto& clip:track.clips)if(clip.warp.enabled)++count;
        for(auto& track:state.tracks)for(auto& clip:track.clips)if(clip.warp.enabled){
            if(cancelled()){jobStatus(job,"cancelled");return;}
            const auto asset=originalAssets.find(clip.assetId);if(asset==originalAssets.end()){jobFailure(job,juce::Result::fail("Warp source asset is missing."));return;}
            const auto key=clip.assetId+":"+juce::String(clip.warp.speedRatio(),17);
            if(!rendered.contains(key)){
                JobFingerprint original;
                if(auto r=fingerprint(asset->second.source,original,cancelled);r.failed()||!original.exists){jobFailure(job,r.failed()?r:juce::Result::fail("Warp source is missing."));return;}
                if(auto prior=originals.find(clip.assetId);prior!=originals.end()&&!sameFingerprint(prior->second,original)){jobFailure(job,juce::Result::fail("Warp source changed."));return;}
                originals[clip.assetId]=original;
                audio::PreparedSource preparedSource;
                if(auto r=audio::prepareSource(asset->second.source,preparedSource,jobAudioIO(job));r.failed()){jobFailure(job,r);return;}
                sources[asset->second.source.getFullPathName()]={preparedSource.duration,preparedSource.sampleRate,preparedSource.channels,preparedSource.format,preparedSource.playbackFile};
                audio::WarpRender result;
                if(auto r=audio::renderWarp(preparedSource,clip.warp.speedRatio(),result,jobAudioIO(job,double(index)/std::max<size_t>(1,count),1.0/std::max<size_t>(1,count)));r.failed()){jobFailure(job,r);return;}
                rendered.emplace(key,std::move(result));
            }
            const auto& result=rendered.at(key);++index;
            clip.warp.renderAssetId="warp-"+result.cacheKey.substring(0,40);clip.warp.sourceHash=originals.at(clip.assetId).hash;clip.warp.renderHash=result.renderHash;
            if(std::none_of(state.assets.begin(),state.assets.end(),[&](const auto& a){return a.id==clip.warp.renderAssetId;}))state.assets.push_back({clip.warp.renderAssetId,result.source.playbackFile});
            const auto renderAsset=std::find_if(state.assets.begin(),state.assets.end(),[&](const auto& a){return a.id==clip.warp.renderAssetId;});
            sources[renderAsset->source.getFullPathName()]={result.source.duration,result.source.sampleRate,result.source.channels,result.source.format,result.source.playbackFile};
        }
        for(const auto& [id,original]:originals){JobFingerprint after;
            if(auto r=fingerprint(originalAssets.at(id).source,after,cancelled);r.failed()||!sameFingerprint(original,after)){
                jobFailure(job,r.failed()?r:juce::Result::fail("Warp source changed during rendering."));return;
            }
        }
        // Annotations attached to a source clip follow the same affine map.
        // Independent imported MIDI/audio tracks keep their normal clip semantics.
        for(const auto& oldTrack:previous.tracks)for(const auto& old:oldTrack.clips)if(old.kind=="audio")if(auto* next=storedClip(state,old.id)){
            if(old.timelineStart==next->timelineStart&&old.warp.speedRatio()==next->warp.speedRatio())continue;
            const auto map=[&](double seconds){return next->timelineStart+(seconds-old.timelineStart)*old.warp.speedRatio()/next->warp.speedRatio();};
            for(const auto& analysis:state.analyses)if(analysis.sourceClipId==old.id&&analysis.kind=="chords")
                for(auto& chord:state.chordRegions)if(chord.analysisId==analysis.id){chord.startSeconds=map(chord.startSeconds);chord.endSeconds=map(chord.endSeconds);}
        }
        pruneAssets(state);state.schemaVersion=storage::requiredSchema(state);
        if(auto r=storage::validate(state);r.failed()){jobFailure(job,r);return;}
        if(auto r=prepareJobAssets(job,state,sources);r.failed()){jobFailure(job,r);return;}
        if(validateFiles)if(auto r=validateFiles(cancelled);r.failed()){jobFailure(job,r);return;}
        if(cancelled()){jobStatus(job,"cancelled");return;}
        std::lock_guard lock(job->mutex);job->phase="committing";
        job->commit=[this,job,state=std::move(state),sources=std::move(sources),selectedAfter,receipt=std::move(receipt),onApplied=std::move(onApplied)]()mutable{
            if(recordingBusy()){jobFailure(job,juce::Result::fail("Recording started before Warp could be committed."));return;}
            for(const auto& [path,info]:sources)prepared[path]=info;
            finishGesture();remember("Audio Warp / tempo alignment");
            auto r=juce::Result::ok();
            try{r=applyTo(*edit,state,bindings,false);}catch(const std::exception& e){r=juce::Result::fail(e.what());}
            if(r.failed()){
                edit->getUndoManager().undoCurrentTransactionOnly();rebuild(*edit,bindings);refreshRange();jobFailure(job,r);return;
            }
            refreshRange();refreshPluginWatches();if(auto* clip=findClip(selectedAfter)){Binding* track=nullptr;findClip(clip->id,&track);choose(track->id,clip->id);}
            recordEdit(false);
            if(!receipt.isObject())receipt=object({});receipt.getDynamicObject()->setProperty("job_id",job->id);
            receipt.getDynamicObject()->setProperty("project_id",juce::String(guard.projectId()));receipt.getDynamicObject()->setProperty("revision",juce::int64(guard.revision()));
            {std::lock_guard lock(job->mutex);job->result=receipt.clone();}
            if(onApplied)onApplied(receipt);jobStatus(job,"completed",{},1);
        };
    });
    if(!job)return juce::Result::fail(status);if(out)*out=object({{"job_id",job->id}});return juce::Result::ok();
}
