// Remote computation is isolated in a child helper. Only validated local PCM
// enters the Edit; GUI and Agent share the same candidate/accept commands.
namespace {
juce::File generationRoot()
{
    const auto path=juce::SystemStats::getEnvironmentVariable("EMUSICIAN_GENERATION_ROOT","E:/MusicAgent&DAW/cloud-inference");
    return juce::File::isAbsolutePath(path)?juce::File(path):juce::File("E:/MusicAgent&DAW/cloud-inference");
}
bool isGenerationCommand(const juce::String& name)
{
    return name=="get_generation_jobs"||name=="get_generation_capabilities"||name=="start_generation"||name=="get_generation_job"||name=="cancel_generation_job"
        ||name=="get_generation_result"||name=="preview_generation_result"||name=="stop_generation_preview"||name=="accept_generation_result";
}
bool isGenerationRead(const juce::String& name)
{return name=="get_generation_jobs"||name=="get_generation_capabilities"||name=="get_generation_job"||name=="get_generation_result"||name=="cancel_generation_job"||name=="stop_generation_preview";}
juce::Result generationAudio(const juce::var& result,const juce::File& directory,const juce::String& id,AudioInfo& info,const std::function<bool()>& cancel)
{
    const auto audio=result["audio"];
    if(!result.isObject()||int(result["schema_version"])!=1||result["job_id"].toString()!=id||result["result_id"].toString()!=id||result["kind"].toString()!="generate"
       ||!result["model"].isObject()||result["model"]["id"].toString().isEmpty()||result["model"]["id"].toString().length()>256
       ||!result["parameters"].isObject()||juce::JSON::toString(result["parameters"]).getNumBytesAsUTF8()>32768
       ||!audio.isObject()||audio["path"].toString()!="audio.wav"||audio["sha256"].toString().length()!=64||!audio["sha256"].toString().containsOnly("0123456789abcdef")
       ||!analysisNumber(audio["duration_seconds"])||double(audio["duration_seconds"])<=0||double(audio["duration_seconds"])>150
       ||!analysisNumber(audio["sample_rate"])||!audio["channels"].isInt())return juce::Result::fail("Invalid generated audio manifest.");
    const auto file=directory.getChildFile("audio.wav");
    if(file.isSymbolicLink()||file.getSize()>128*1024*1024)return juce::Result::fail("Generated audio exceeds the local asset limit.");
    JobFingerprint hash;if(auto r=fingerprint(file,hash,cancel);r.failed())return r;
    if(!hash.exists||hash.hash!=audio["sha256"].toString())return juce::Result::fail("Generated audio checksum does not match.");
    if(auto r=inspectAudio(file,info);r.failed())return r;
    if(info.channels<1||info.channels>2||info.channels!=int(audio["channels"])||info.rate<16000||info.rate>96000
       ||std::abs(info.rate-double(audio["sample_rate"]))>.01||std::abs(info.duration-double(audio["duration_seconds"]))>.002)return juce::Result::fail("Generated audio format does not match its manifest.");
    if(result.hasProperty("waveform_peaks")){const auto peaks=result["waveform_peaks"];
        if(!peaks.isArray()||peaks.size()!=128)return juce::Result::fail("Invalid generated waveform.");
        for(const auto& peak:*peaks.getArray())if(!analysisNumber(peak)||double(peak)<0||double(peak)>1)return juce::Result::fail("Invalid generated waveform amplitude.");
    }
    return juce::Result::ok();
}
}

juce::var EngineSession::Impl::generationCapabilities()
{
    const auto compute=computeRegistry();const auto providers=cloudProviders(compute,"generate");
    if(compute.isObject()){
        bool available=false;for(const auto& p:providers)available=available||bool(p["available"]);
        const auto model=compute["defaults"]["generate"].toString();
        return object({{"available",available},{"model_id",model},{"default_model_id",model},{"providers",providers},{"experimental",true},{"min_duration_seconds",10},{"max_duration_seconds",120},{"max_parallel_jobs",1},
            {"detail","Cloud models are checked when a task starts. Duration is a target; preview the actual result."}});
    }
    juce::var registry;const auto r=analysisJson(generationRoot().getChildFile("registry.json"),registry,131072);
    const auto python=registry["python_executable"].toString();
    const bool installed=r.wasOk()&&bool(registry["available"])&&juce::File::isAbsolutePath(python)&&juce::File(python).existsAsFile();
    juce::Array<juce::var> legacy;legacy.add(object({{"kind","generate"},{"model_id",registry["model_id"]},{"execution","cloud"},{"available",installed},{"default",true},{"max_duration_seconds",120}}));
    return object({{"available",installed},{"model_id",registry["model_id"]},{"default_model_id",registry["model_id"]},{"providers",legacy},{"experimental",true},{"min_duration_seconds",10},{"max_duration_seconds",120},{"max_parallel_jobs",1},
        {"detail",installed?"Remote generation configured; connectivity is checked when a job starts.":"Remote generation is not configured."}});
}
bool EngineSession::Impl::generationSourceMatches(const GenerationEntry& g)const
{
    const auto* signature=edit->tempoSequence.getTimeSig(0);
    return g.source["project_id"].toString()==juce::String(guard.projectId())
        &&std::abs(double(g.source["bpm"])-edit->tempoSequence.getTempo(0)->getBpm())<1e-9
        &&int(g.source["meter_numerator"])==signature->numerator&&int(g.source["meter_denominator"])==signature->denominator;
}
juce::var EngineSession::Impl::generationJobs()const
{
    juce::Array<juce::var> values;
    for(const auto& [id,g]:generations)if(g->job&&g->source["project_id"].toString()==juce::String(guard.projectId())){
        std::lock_guard lock(g->job->mutex);values.add(object({{"job_id",g->job->id},{"result_id",id},{"kind","generate"},{"status",g->applied?juce::String("applied"):g->job->status}}));
    }return values;
}
juce::Result EngineSession::Impl::beginGeneration(const juce::var& args,juce::var& out)
{
    if(recordingBusy()||nativePending)return fail("Finish recording and pending device edits before generating music.");
    for(const auto& j:jobs)if(j->worker.joinable()&&(j->kind.startsWith("generation.")||j->kind.startsWith("analysis."))&&j->kind!="analysis.preview")return fail("Wait for the current AI task or cancel it first.");
    const auto prompt=textArg(args,"prompt").trim(),lyrics=textArg(args,"lyrics");
    const auto seconds=number(args,"duration_seconds"),at=number(args,"timeline_start_seconds",edit->getTransport().getPosition().inSeconds());
    if(prompt.isEmpty()||prompt.length()>2000||lyrics.length()>4096||(args.hasProperty("lyrics")&&!args["lyrics"].isString())
       ||!std::isfinite(seconds)||seconds<10||seconds>120||!std::isfinite(at)||at<0||at+150>storage::maximumTimelineSeconds)return fail("Enter a description and a duration from 10 to 120 seconds.");
    const auto seed=args.getProperty("seed",juce::Random::getSystemRandom().nextInt(std::numeric_limits<int>::max()));
    if((!seed.isInt()&&!seed.isInt64())||juce::int64(seed)<0||juce::int64(seed)>2147483647)return fail("Seed must be an integer from 0 to 2147483647.");
    juce::var selected;if(auto r=selectAnalysisRoute(generationCapabilities()["providers"],"generate",args,selected);r.failed())return fail(r.getErrorMessage());
    juce::var registry=computeRegistry();if(!registry.isObject()&&analysisJson(generationRoot().getChildFile("registry.json"),registry,131072).failed())return fail("Remote generation is not configured.");
    const auto python=registry["python_executable"].toString();
    if(!bool(registry["available"])||!juce::File::isAbsolutePath(python)||!juce::File(python).existsAsFile())return fail("Remote generation runtime is not ready.");
    while(generations.size()>=32){auto retired=std::find_if(generations.begin(),generations.end(),[](const auto& x){return x.second->job&&!x.second->job->worker.joinable()&&(!x.second->acceptJob||!x.second->acceptJob->worker.joinable());});
        if(retired==generations.end())return fail("Generation history is busy.");generations.erase(retired);}
    auto g=std::make_shared<GenerationEntry>();g->id=uid();g->modelId=selected["model_id"].toString();g->directory=generationRoot().getChildFile("jobs").getChildFile(g->id);
    const auto* signature=edit->tempoSequence.getTimeSig(0);const auto bpm=edit->tempoSequence.getTempo(0)->getBpm();
    g->source=object({{"project_id",juce::String(guard.projectId())},{"revision",juce::int64(guard.revision())},{"timeline_start",at},{"bpm",bpm},{"meter_numerator",int(signature->numerator)},{"meter_denominator",int(signature->denominator)}});
    g->parameters=object({{"prompt",prompt},{"lyrics",lyrics},{"duration_seconds",seconds},{"seed",seed},{"bpm",bpm},{"meter_numerator",int(signature->numerator)},{"meter_denominator",int(signature->denominator)}});
    const auto script=juce::File(EMUSICIAN_SOURCE_DIR).getChildFile("scripts/cloud/run_generation.py");
    const auto root=generationRoot();
    g->job=startJob("generation.generate",[this,g,script,python,root](const auto& j){
        if(!g->directory.createDirectory()){jobStatus(j,"failed","Cannot create the local generation directory.");return;}
        auto request=g->parameters.clone();auto* dto=request.getDynamicObject();dto->setProperty("schema_version",1);dto->setProperty("job_id",g->id);dto->setProperty("kind","generate");dto->setProperty("source",g->source);dto->setProperty("generation_root",root.getFullPathName());dto->setProperty("compute_root",computeRoot().getFullPathName());dto->setProperty("model_id",g->modelId);
        if(!g->directory.getChildFile("request.json").replaceWithText(juce::JSON::toString(request))){jobStatus(j,"failed","Cannot write generation request.");return;}
        analysis_worker::Process child;if(auto r=child.start(juce::StringArray{python,script.getFullPathName(),"--request",g->directory.getChildFile("request.json").getFullPathName()},g->directory.getChildFile("process.log"));r.failed()){jobStatus(j,"failed",r.getErrorMessage());return;}
        const auto began=juce::Time::getMillisecondCounterHiRes();bool aborted=false;
        while(child.isRunning()){
            if(j->cancel||juce::Time::getMillisecondCounterHiRes()-began>60.0*60*1000){
                g->directory.getChildFile("cancel").replaceWithText("cancel");if(!child.wait(8000))child.terminate();aborted=true;break;}
            juce::var progress;if(analysisJson(g->directory.getChildFile("progress.json"),progress,32768).wasOk()){
                std::lock_guard lock(j->mutex);j->phase=progress["phase"].toString().substring(0,80);j->detail=progress["detail"].toString().substring(0,512);
                if(analysisNumber(progress["progress"]))j->progress=juce::jlimit(0.0,1.0,double(progress["progress"]));
            }std::this_thread::sleep_for(std::chrono::milliseconds(200));
        }
        if(aborted||j->cancel){
            juce::var cancellation;analysisJson(g->directory.getChildFile("cancellation.json"),cancellation,32768);
            const auto remote=cancellation["remote_status"].toString();const bool confirmed=remote=="cancelled"&&bool(cancellation["remote_cancel_confirmed"]);
            {std::lock_guard lock(j->mutex);j->result=object({{"remote_status",remote=="cancelled"||remote=="cancelling"?remote:juce::String("unconfirmed")},{"remote_cancel_confirmed",confirmed}});
                j->detail=confirmed?"Local and remote tasks cancelled.":remote=="cancelling"?"Local task stopped; remote cancellation is pending.":"Local task stopped; remote cancellation is unconfirmed.";}
            jobStatus(j,j->cancel?"cancelled":"failed",j->cancel?"":"Generation exceeded its one-hour limit.");return;
        }
        if(child.exitCode()!=0){juce::var error;analysisJson(g->directory.getChildFile("error.json"),error,32768);jobStatus(j,"failed",error["message"].toString().isNotEmpty()?error["message"].toString().substring(0,1024):"Generation ended without a result.");return;}
        juce::var result;const auto file=g->directory.getChildFile("result.json");
        if(auto r=analysisJson(file,result,128*1024);r.failed()){jobStatus(j,"failed",r.getErrorMessage());return;}
        AudioInfo info;const auto cancel=[j]{return j->cancel.load();};
        if(auto r=generationAudio(result,g->directory,g->id,info,cancel);r.failed()){jobStatus(j,j->cancel?"cancelled":"failed",r.getErrorMessage());return;}
        if(g->modelId.isNotEmpty()&&result["model"]["id"].toString()!=g->modelId){jobStatus(j,"failed","The server returned a different generation model.");return;}
        JobFingerprint hash;if(auto r=fingerprint(file,hash,cancel);r.failed()){jobStatus(j,"failed",r.getErrorMessage());return;}
        std::lock_guard lock(j->mutex);j->commit=[this,g,j,result,hash]{
            if(j->cancel){jobStatus(j,"cancelled");return;}g->result=result;g->resultHash=hash.hash;
            if(!generationSourceMatches(*g)){jobStatus(j,"stale","Project or tempo changed during generation; the local result is retained.");return;}
            jobStatus(j,"ready",{},1);publish("generation_ready",object({{"job_id",j->id},{"result_id",g->id}}));
        };
    });
    if(!g->job)return fail(status);generations[g->id]=g;out=object({{"job_id",g->job->id},{"result_id",g->id}});return juce::Result::ok();
}

juce::Result EngineSession::Impl::acceptGeneration(const juce::var& args,juce::var& out)
{
    const auto found=generations.find(textArg(args,"result_id"));if(found==generations.end())return fail("Generation result is unavailable.");auto g=found->second;
    if(textArg(args,"result_hash").isEmpty()||textArg(args,"result_hash")!=g->resultHash)return fail("Review the current generation result before adding it.");
    if(!generationSourceMatches(*g))return fail("Project or tempo changed; this candidate cannot be added at its old position.");
    if(g->applied){if(!metadata(*edit).getChildWithName("EM_GENERATIONS").getChildWithProperty("id",g->id).isValid())return fail("This import was undone. Use Redo to restore it.");out=g->receipt;return juce::Result::ok();}
    if(g->acceptJob&&g->acceptJob->worker.joinable()){out=object({{"job_id",g->acceptJob->id},{"result_id",g->id}});return juce::Result::ok();}
    {std::lock_guard lock(g->job->mutex);if(g->job->status!="ready"||!g->result.isObject())return fail("Wait for a ready generation result.");}
    if(recordingBusy()||nativePending)return fail("Finish recording and pending device edits before adding generated audio.");
    auto candidate=std::make_shared<storage::StoredProject>(capture());const auto revision=guard.revision();const auto project=juce::String(guard.projectId());const auto root=generationRoot();
    g->acceptJob=startJob("generation.accept",[this,g,candidate,revision,project,root](const auto& j){
        jobStatus(j,"applying",{},0);const auto cancel=[j]{return j->cancel.load();};AudioInfo info;JobFingerprint hash;
        if(auto r=fingerprint(g->directory.getChildFile("result.json"),hash,cancel);r.failed()||hash.hash!=g->resultHash){jobStatus(j,"failed","The generation manifest changed after review.");return;}
        if(auto r=generationAudio(g->result,g->directory,g->id,info,cancel);r.failed()){jobStatus(j,j->cancel?"cancelled":"failed",r.getErrorMessage());return;}
        const auto assetDir=root.getChildFile("assets").getChildFile(project).getChildFile(g->id);const auto retained=assetDir.getChildFile("audio.wav");
        if(!assetDir.createDirectory()||!g->directory.getChildFile("audio.wav").copyFileTo(retained)){jobStatus(j,"failed","Cannot retain generated audio on the local disk.");return;}
        if(auto r=fingerprint(retained,hash,cancel);r.failed()||hash.hash!=g->result["audio"]["sha256"].toString()){jobStatus(j,"failed","Generated asset copy failed verification.");return;}
        info.playbackFile=retained;storage::StoredAsset asset{uid(),retained};storage::StoredTrack track;track.id=uid();track.name="Generated / "+g->parameters["prompt"].toString().replaceCharacters("\r\n","  ").substring(0,60);
        const double at=double(g->source["timeline_start"]);storage::StoredClip clip{uid(),asset.id,at,0,info.duration};track.clips.push_back(clip);
        candidate->assets.push_back(asset);candidate->tracks.push_back(track);
        auto provenance=g->parameters.clone();
        for(const auto* key:{"truncated","conditioning","processing","warnings","limitations","completion"})if(g->result.hasProperty(key))provenance.getDynamicObject()->setProperty(key,g->result[key]);
        provenance.getDynamicObject()->setProperty("actual_duration_seconds",info.duration);
        candidate->generations.push_back({g->id,asset.id,clip.id,g->result["model"]["id"].toString(),g->result["model"].getProperty("revision",g->result["model"]["version"]).toString(),g->result["audio"]["sha256"].toString(),g->resultHash,juce::JSON::toString(provenance,true),at,info.duration});candidate->schemaVersion=storage::requiredSchema(*candidate);
        if(auto r=storage::validate(*candidate);r.failed()){jobStatus(j,"failed",r.getErrorMessage());return;}
        auto receipt=object({{"result_id",g->id},{"project_id",project},{"applied",true},{"track_ids",juce::var(juce::StringArray{track.id})},{"clip_ids",juce::var(juce::StringArray{clip.id})},{"revision",juce::int64(revision+1)}});
        std::lock_guard lock(j->mutex);j->commit=[this,g,j,candidate,revision,project,retained,info,receipt]{
            if(j->cancel){jobStatus(j,"cancelled");return;}
            if(guard.revision()!=revision||juce::String(guard.projectId())!=project||!generationSourceMatches(*g)||recordingBusy()||nativePending){jobStatus(j,"stale","Project changed while adding audio. Review and add again.");return;}
            prepared[retained.getFullPathName()]=info;finishGesture();remember("Add generated music");auto applied=juce::Result::ok();
            try{applied=applyTo(*edit,*candidate,bindings,false);}catch(const std::exception& error){applied=juce::Result::fail(error.what());}
            if(applied.failed()){edit->getUndoManager().undoCurrentTransactionOnly();rebuild(*edit,bindings);refreshRange();refreshPluginWatches();cachedRevision=std::numeric_limits<std::uint64_t>::max();jobStatus(j,"failed",applied.getErrorMessage());return;}
            refreshRange();choose(receipt["track_ids"][0].toString(),receipt["clip_ids"][0].toString());recordEdit(false);g->applied=true;g->receipt=receipt;jobStatus(j,"applied",{},1);publish("generation_applied",receipt);
        };
    });
    if(!g->acceptJob)return fail(status);out=object({{"job_id",g->acceptJob->id},{"result_id",g->id}});return juce::Result::ok();
}

juce::Result EngineSession::Impl::generationCommand(const juce::String& command,const juce::var& args,juce::var& out)
{
    if(command=="get_generation_jobs"){out=object({{"jobs",generationJobs()}});return juce::Result::ok();}
    if(command=="get_generation_capabilities"){out=generationCapabilities();return juce::Result::ok();}
    if(command=="start_generation")return beginGeneration(args,out);
    if(command=="accept_generation_result")return acceptGeneration(args,out);
    if(command=="stop_generation_preview"){++analysisPreviewGeneration;if(analysisPreview)analysisPreview->stop();for(const auto& j:jobs)if(j->kind=="generation.preview"&&j->worker.joinable())j->cancel=true;out=object({{"status","stopped"}});return juce::Result::ok();}
    if(command=="get_generation_job"||command=="cancel_generation_job"){
        const auto id=textArg(args,"job_id");for(const auto& [resultId,g]:generations)for(const auto& j:{g->job,g->acceptJob})if(j&&j->id==id){
            if(command=="cancel_generation_job"){j->cancel=true;out=object({{"job_id",id},{"cancel_requested",true}});return juce::Result::ok();}
            std::lock_guard lock(j->mutex);out=object({{"job_id",id},{"kind",j->kind},{"execution","cloud"},{"model_id",g->modelId},{"result_id",resultId},{"status",j->status},{"phase",j->phase},{"progress",j->progress},{"error",j->error},{"detail",j->detail},{"remote_status",j->result.getProperty("remote_status","unconfirmed")},{"remote_cancel_confirmed",j->result.getProperty("remote_cancel_confirmed",false)},{"source",g->source},{"applied",g->applied},{"receipt",g->receipt}});return juce::Result::ok();
        }return fail("Generation job not found.");
    }
    auto found=generations.find(textArg(args,"result_id"));if(found==generations.end())return fail("Generation result is unavailable.");auto g=found->second;
    if(command=="get_generation_result"){
        if(!g->result.isObject())return fail("Generation result is not ready.");
        out=object({{"result_id",g->id},{"kind","generate"},{"execution","cloud"},{"model_id",g->result["model"]["id"]},{"limitations",g->result["limitations"]},{"completion",g->result["completion"]},{"truncated",g->result["truncated"]},{"conditioning",g->result["conditioning"]},{"processing",g->result["processing"]},{"warnings",g->result["warnings"]},{"source",g->source},{"audio",g->result["audio"]},{"model",g->result["model"]},{"parameters",g->parameters},{"waveform_peaks",g->result["waveform_peaks"]},{"result_hash",g->resultHash},{"applied",g->applied},{"present_in_project",metadata(*edit).getChildWithName("EM_GENERATIONS").getChildWithProperty("id",g->id).isValid()},{"stale",!generationSourceMatches(*g)},{"receipt",g->receipt}});return juce::Result::ok();
    }
    if(command=="preview_generation_result"){
        if(recordingBusy()||edit->getTransport().isPlaying()||!g->result.isObject()||!generationSourceMatches(*g))return fail("Stop playback and choose a current generated candidate to preview.");
        if(!analysisPreview)analysisPreview=std::make_unique<AnalysisPreview>(engine.getDeviceManager().deviceManager);
        const auto token=++analysisPreviewGeneration;analysisPreview->stop();
        for(const auto& j:jobs)if((j->kind=="analysis.preview"||j->kind=="generation.preview")&&j->worker.joinable())j->cancel=true;
        const auto job=startJob("generation.preview",[this,g,token](const auto& j){
            AudioInfo info;if(auto r=generationAudio(g->result,g->directory,g->id,info,[j]{return j->cancel.load();});r.failed()){jobStatus(j,"failed",r.getErrorMessage());return;}
            std::lock_guard lock(j->mutex);j->commit=[this,g,j,token]{if(j->cancel||token!=analysisPreviewGeneration||!generationSourceMatches(*g)){jobStatus(j,"cancelled");return;}
                auto result=analysisPreview->prepareAndPlay(g->directory.getChildFile("audio.wav"));jobStatus(j,result.wasOk()?"completed":"failed",result.getErrorMessage(),1);
            };
        });if(!job)return fail(status);out=object({{"job_id",job->id}});return juce::Result::ok();
    }
    return fail("Unsupported generation command.");
}
