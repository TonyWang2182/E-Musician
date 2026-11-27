// Control-thread adapter for native device preparation and publication.
// Audio rendering never enters this file or the sample loader queue.
std::shared_ptr<const native::SampleData> EngineSession::nativeSampleForDisplay(
    const juce::String& projectId, std::uint64_t revision, const juce::String& trackId,
    const juce::String& deviceId, int pad, const juce::String& expectedHash) const
{
    requireControlThread();
    if (projectId != juce::String(impl->guard.projectId()) || revision != impl->guard.revision()
        || (impl->nativePending && impl->nativePending->trackId == trackId)
        || impl->nativeTrackErrors.contains(trackId)) return {};
    auto* binding = impl->find(trackId);
    if (!binding) return {};
    const auto slots = impl->captureSlots(binding->track->state);
    const auto slot = std::find_if(slots.begin(), slots.end(), [&](const auto& item) {
        return item.id == deviceId && item.format == "E-musician";
    });
    const auto runtime = impl->nativeRuntime.find(deviceId);
    if (slot == slots.end() || runtime == impl->nativeRuntime.end() || runtime->second.status != "ready") return {};
    auto* instrument = dynamic_cast<native::Instrument*>(impl->livePlugin(*impl->edit, deviceId));
    return instrument ? instrument->sampleForDisplay(pad, expectedHash) : nullptr;
}

namespace {
juce::Result nativeRequestFor(const storage::StoredPlugin& plugin,
                              const std::vector<storage::StoredAsset>& assets,
                              const juce::String& projectId, std::uint64_t revision,
                              std::uint64_t generation, native::NativeLoadQueue::Request& request)
{
    std::vector<juce::String> ids;
    if(auto r=storage::nativePluginAssetIds(plugin,ids);r.failed())return r;
    request.projectId=projectId;request.deviceId=plugin.id;request.revision=revision;request.generation=generation;
    request.stateJson=juce::String::fromUTF8(static_cast<const char*>(plugin.state.getData()),int(plugin.state.getSize()));
    for(const auto& id:ids){
        auto source=std::find_if(assets.begin(),assets.end(),[&](const auto& item){return item.id==id;});
        if(source==assets.end())return juce::Result::fail("Native sample asset is missing.");
        request.assets.emplace(id,source->source);
    }
    return juce::Result::ok();
}
}

juce::String EngineSession::Impl::nativeSignature(const storage::StoredPlugin& plugin,const std::map<juce::String,juce::File>& assets)const
{
    juce::MemoryOutputStream stream;stream.write(plugin.state.getData(),plugin.state.getSize());
    for(const auto& [id,file]:assets){stream.writeString(id);stream.writeString(file.getFullPathName());}
    return sessionSha256(stream.getData(),stream.getDataSize());
}

juce::Result EngineSession::Impl::nativeAssetHashes(const storage::StoredProject& state,std::map<juce::String,juce::String>& hashes)const
{
    hashes.clear();
    const auto inspect=[&](const auto& list)->juce::Result{
        for(const auto& plugin:list)if(plugin.format=="E-musician"){
            std::vector<juce::String> ids;if(auto r=storage::nativePluginAssetIds(plugin,ids);r.failed())return r;
            if(ids.empty())continue;
            const auto active=nativeRuntime.find(plugin.id);
            auto* instrument=dynamic_cast<native::Instrument*>(livePlugin(*edit,plugin.id));
            if(!instrument||active==nativeRuntime.end()||active->second.status!="ready")
                return juce::Result::fail("Wait for native samples to finish loading before saving or exporting.");
            const auto loaded=instrument->sourceHashes();
            for(const auto& id:ids){
                const auto found=loaded.find(id);
                if(found==loaded.end())return juce::Result::fail("A native sample has not been loaded. Re-select it before saving.");
                const auto previous=hashes.find(id);
                if(previous!=hashes.end()&&previous->second!=found->second)
                    return juce::Result::fail("A shared native sample has different loaded versions. Reload it before saving.");
                hashes[id]=found->second;
            }
        }
        return juce::Result::ok();
    };
    if(auto r=inspect(state.masterPlugins);r.failed())return r;
    for(const auto& track:state.tracks)if(auto r=inspect(track.plugins);r.failed())return r;
    return juce::Result::ok();
}

juce::Result EngineSession::Impl::beginNative(const juce::String& command,const juce::var& args)
{
    if(nativePending)return fail("Wait for the current native instrument edit to finish.");
    for(const auto& job:jobs)if(job->worker.joinable())return fail("Wait for the current file task before editing a native instrument.");
    if(pluginHost.scanSnapshot().running)return fail("Wait for the plugin scan before editing a native instrument.");
    auto candidate=std::make_shared<storage::StoredProject>(capture());
    if(auto r=native::mutate(*candidate,command,args);r.failed())return fail(r.getErrorMessage());
    std::set<juce::String> usedAssets;
    for(const auto& track:candidate->tracks){
        for(const auto& clip:track.clips)if(clip.assetId.isNotEmpty())usedAssets.insert(clip.assetId);
        for(const auto& plugin:track.plugins)if(plugin.format=="E-musician"){
            std::vector<juce::String> ids;if(auto r=storage::nativePluginAssetIds(plugin,ids);r.failed())return fail(r.getErrorMessage());
            usedAssets.insert(ids.begin(),ids.end());
        }
    }
    std::erase_if(candidate->assets,[&](const auto& asset){return !usedAssets.contains(asset.id);});
    if(auto r=storage::validate(*candidate);r.failed())return fail(r.getErrorMessage());
    const auto trackId=args["track_id"].toString();storage::StoredPlugin* plugin=nullptr;
    for(auto& track:candidate->tracks)if(track.id==trackId)for(auto& item:track.plugins)if(item.format=="E-musician"&&item.role=="instrument")plugin=&item;
    if(!plugin)return fail("Native instrument no longer exists.");
    if(nativeGeneration==std::numeric_limits<std::uint64_t>::max())return fail("Native instrument generation limit reached.");
    native::NativeLoadQueue::Request request;
    if(auto r=nativeRequestFor(*plugin,candidate->assets,juce::String(guard.projectId()),guard.revision(),++nativeGeneration,request);r.failed())return fail(r.getErrorMessage());
    if(command=="set_native_pad"||command=="set_native_sampler") {
        const auto previous=nativeRuntime.find(plugin->id);
        if(previous!=nativeRuntime.end()&&previous->second.status=="ready"&&!nativeTrackErrors.contains(trackId))
            if(auto* instrument=dynamic_cast<native::Instrument*>(livePlugin(*edit,plugin->id))) request.reusable=instrument->bankForConfiguration();
    }
    auto pending=std::make_unique<NativePending>();pending->candidate=candidate;pending->projectId=request.projectId;
    pending->trackId=trackId;pending->deviceId=plugin->id;pending->revision=request.revision;pending->generation=request.generation;
    pending->signature=nativeSignature(*plugin,request.assets);pending->operation=command;
    std::uint64_t token=0;if(auto r=nativeQueue->submit(std::move(request),token);r.failed())return fail(r.getErrorMessage());
    pending->token=token;nativeTrackErrors.erase(trackId);auto& runtime=nativeRuntime[pending->deviceId];
    runtime.signature=pending->signature;runtime.status="queued";runtime.error.clear();runtime.token=token;runtime.generation=pending->generation;
    nativeQueueProject=pending->projectId;nativePending=std::move(pending);status="Native instrument loading.";
    return juce::Result::ok();
}

void EngineSession::Impl::finishNativeJob(std::uint64_t token,const juce::String& state,const juce::String& error)
{
    JobSnapshot job;job.id="native-"+juce::String(juce::int64(token));job.kind="native_instrument";job.status=state;job.error=error;
    job.progress=state=="completed"?1.0:0.0;nativeJobHistory.push_back(std::move(job));
    if(nativeJobHistory.size()>64)nativeJobHistory.erase(nativeJobHistory.begin());
}

void EngineSession::Impl::completeNative(native::NativeLoadQueue::Completion completion)
{
    nativeLastScan=std::numeric_limits<std::uint64_t>::max();
    const auto& request=completion.request;
    auto current=nativeRuntime.find(request.deviceId);
    if(current==nativeRuntime.end()||current->second.token!=completion.token||current->second.generation!=request.generation)return;
    auto& runtime=current->second;
    if(request.projectId!=juce::String(guard.projectId())||request.revision!=guard.revision()){
        runtime.status="error";runtime.error="The project changed while the sample was loading. Retry.";runtime.signature.clear();
        if(nativePending&&nativePending->token==completion.token){nativeTrackErrors[nativePending->trackId]=runtime.error;finishNativeJob(completion.token,"conflict",runtime.error);nativePending.reset();}status=runtime.error;return;
    }
    if(completion.result.failed()||!completion.bank){
        runtime.status="error";runtime.error=completion.result.getErrorMessage();
        if(nativePending&&nativePending->token==completion.token){nativeTrackErrors[nativePending->trackId]=runtime.error;finishNativeJob(completion.token,"failed",runtime.error);nativePending.reset();}status=runtime.error;return;
    }
    if(nativePending&&nativePending->token==completion.token){
        auto pending=std::move(nativePending);
        if(pending->projectId!=request.projectId||pending->deviceId!=request.deviceId||pending->revision!=request.revision||pending->generation!=request.generation){
            runtime.status="error";runtime.error="Native sample request identity changed.";nativeTrackErrors[pending->trackId]=runtime.error;finishNativeJob(completion.token,"conflict",runtime.error);status=runtime.error;return;}
        if(recordingBusy()){
            runtime.status="error";runtime.error="Recording started while the instrument was loading. Retry after stopping.";nativeTrackErrors[pending->trackId]=runtime.error;finishNativeJob(completion.token,"failed",runtime.error);status=runtime.error;return;
        }
        if(pending->operation=="add_native_instrument")edit->getTransport().stop(false,false);
        finishGesture();remember(pending->operation.replaceCharacter('_',' '));
        auto applied=juce::Result::ok();
        try{applied=applyTo(*edit,*pending->candidate,bindings,false);}catch(const std::exception& e){applied=juce::Result::fail(e.what());}
        catch(...){applied=juce::Result::fail("Could not apply native instrument edit.");}
        auto* instrument=dynamic_cast<native::Instrument*>(livePlugin(*edit,request.deviceId));
        if(applied.failed()||!instrument){
            edit->getUndoManager().undoCurrentTransactionOnly();rebuild(*edit,bindings);refreshRange();refreshPluginWatches();
            runtime.status="error";runtime.error=applied.failed()?applied.getErrorMessage():"Native instrument could not be created.";nativeTrackErrors[pending->trackId]=runtime.error;finishNativeJob(completion.token,"failed",runtime.error);status=runtime.error;return;
        }
        instrument->publish(std::move(completion.bank));refreshRange();refreshPluginWatches();choose(pending->trackId);recordEdit();
        runtime.status="ready";runtime.error.clear();nativeTrackErrors.erase(pending->trackId);finishNativeJob(completion.token,"completed");status="Native instrument ready.";return;
    }
    auto* instrument=dynamic_cast<native::Instrument*>(livePlugin(*edit,request.deviceId));
    if(!instrument){runtime.status="error";runtime.error="Native instrument no longer exists.";return;}
    instrument->publish(std::move(completion.bank));runtime.status="ready";runtime.error.clear();
}

void EngineSession::Impl::reconcileNative()
{
    if(!nativeQueue||!edit)return;
    const auto now=juce::Time::getMillisecondCounterHiRes();
    if(now>=nativeRetireAt){
        nativeRetireAt=now+1000;
        for(const auto& [id,runtime]:nativeRuntime){juce::ignoreUnused(runtime);
            if(auto* instrument=dynamic_cast<native::Instrument*>(livePlugin(*edit,id)))instrument->collectRetired();}
    }
    if(nativeLastScan==guard.revision())return;
    nativeLastScan=guard.revision();
    const auto projectId=juce::String(guard.projectId());nativeQueueProject=projectId;
    std::vector<storage::StoredAsset> assets;
    for(const auto& item:metadata(*edit).getChildWithName("EM_NATIVE_ASSETS"))assets.push_back({item["id"].toString(),juce::File(item["source"].toString())});
    std::set<juce::String> present;
    for(const auto& binding:bindings)for(const auto& plugin:captureSlots(binding.track->state))if(plugin.format=="E-musician"){
        present.insert(plugin.id);auto* instrument=dynamic_cast<native::Instrument*>(livePlugin(*edit,plugin.id));
        if(!instrument)continue;instrument->collectRetired();
        if(nativePending&&nativePending->deviceId==plugin.id)continue;
        if(nativeGeneration==std::numeric_limits<std::uint64_t>::max())continue;
        native::NativeLoadQueue::Request request;
        auto r=nativeRequestFor(plugin,assets,projectId,guard.revision(),nativeGeneration+1,request);
        auto& runtime=nativeRuntime[plugin.id];
        if(r.failed()){runtime.status="error";runtime.error=r.getErrorMessage();continue;}
        const auto signature=nativeSignature(plugin,request.assets);
        if(signature==runtime.signature)continue;
        request.generation=++nativeGeneration;std::uint64_t token=0;
        if(auto submitted=nativeQueue->submit(std::move(request),token);submitted.failed()){
            runtime.status="error";runtime.error=submitted.getErrorMessage();continue;}
        runtime.signature=signature;runtime.status="queued";runtime.error.clear();runtime.token=token;runtime.generation=nativeGeneration;
    }
    for(auto it=nativeRuntime.begin();it!=nativeRuntime.end();){
        if(!present.contains(it->first)&&(!nativePending||nativePending->deviceId!=it->first)){
            nativeQueue->cancelDevice(projectId,it->first);it=nativeRuntime.erase(it);
        }else ++it;
    }
}
