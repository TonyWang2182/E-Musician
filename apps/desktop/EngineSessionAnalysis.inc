// Control/file-worker analysis pipeline. Model processes never receive an Edit,
// audio callback or arbitrary model-supplied path. Published results are immutable.
namespace {
juce::File analysisRoot()
{
    auto path=juce::SystemStats::getEnvironmentVariable("EMUSICIAN_ANALYSIS_ROOT","E:/MusicAgent&DAW/analysis");
    return juce::File::isAbsolutePath(path)?juce::File(path):juce::File("E:/MusicAgent&DAW/analysis");
}
juce::Result analysisJson(const juce::File& file,juce::var& value,juce::int64 maxBytes=16*1024*1024)
{
    if(!file.existsAsFile()||file.isSymbolicLink()||file.getSize()<=0||file.getSize()>maxBytes)return juce::Result::fail("Missing or oversized analysis JSON.");
    return juce::JSON::parse(file.loadFileAsString(),value);
}
bool analysisNumber(const juce::var& value){return (value.isInt()||value.isInt64()||value.isDouble())&&std::isfinite(double(value));}
double analysisOption(const juce::var& args,const char* key,double fallback){return args.hasProperty(key)?number(args,key):fallback;}
juce::String analysisItemsKey(const juce::String& kind){return kind=="separate"?"stems":kind=="transcribe"?"notes":"chord_regions";}
juce::Result validateAnalysisResult(const juce::var& value,const juce::String& id,const juce::String& kind,double duration)
{
    if(!value.isObject()||int(value["schema_version"])!=1||value["job_id"].toString()!=id||value["result_id"].toString()!=id||value["kind"].toString()!=kind
       ||!value["model"].isObject()||value["model"]["id"].toString().isEmpty()||value["model"]["id"].toString().length()>256
       ||!analysisNumber(value["duration_seconds"])||std::abs(double(value["duration_seconds"])-duration)>.002)return juce::Result::fail("The analysis result does not match this request.");
    const auto list=value.getProperty(analysisItemsKey(kind),{});if(!list.isArray())return juce::Result::fail("Analysis result items are missing.");
    if(list.size()>(kind=="separate"?4:kind=="chords"?10000:100000))return juce::Result::fail("Analysis result exceeds the project limit.");
    if(kind=="separate"){
        std::set<juce::String> names;for(const auto& stem:*list.getArray()){
            const auto name=stem["name"].toString();if((name!="vocals"&&name!="drums"&&name!="bass"&&name!="other")||!names.insert(name).second
                ||!stem["path"].isString()||!analysisNumber(stem["duration_seconds"])||std::abs(double(stem["duration_seconds"])-duration)>.002)return juce::Result::fail("Invalid separated stem metadata.");
        }if(names.size()!=4)return juce::Result::fail("Four stems were expected.");
    }else for(const auto& item:*list.getArray()){
        const double start=number(item,"start_seconds"),length=kind=="transcribe"?number(item,"duration_seconds"):number(item,"end_seconds")-start;
        if(!item.isObject()||!std::isfinite(start)||!std::isfinite(length)||start<0||length<=0||start+length>duration+1.0e-7)return juce::Result::fail("Analysis item is outside the analyzed range.");
        if(kind=="transcribe"){
            if(!item["pitch"].isInt()||int(item["pitch"])<0||int(item["pitch"])>127||!item["velocity"].isInt()||int(item["velocity"])<1||int(item["velocity"])>127||int(item["channel"])!=1)
                return juce::Result::fail("Invalid transcribed MIDI note.");
        }else if(!item["label"].isString()||!analysisNumber(item["score"])||double(item["score"])<0||double(item["score"])>1||!item["uncertain"].isBool())return juce::Result::fail("Invalid chord candidate.");
    }
    return juce::Result::ok();
}
juce::var chordJson(const storage::StoredChordRegion& c)
{return object({{"id",c.id},{"label",c.label},{"analysis_id",c.analysisId},{"start_seconds",c.startSeconds},{"end_seconds",c.endSeconds},{"score",c.score},{"uncertain",c.uncertain}});}
}

juce::var EngineSession::Impl::analysisCapabilities()
{
    juce::var registry;const auto root=analysisRoot();const auto read=analysisJson(root.getChildFile("registry.json"),registry,128*1024);
    juce::Array<juce::var> providers;
    for(const auto* name:{"separate","transcribe","chords"}){
        auto p=registry["providers"][name];const auto python=p["python_executable"].toString();
        const bool available=read.wasOk()&&bool(p["available"])&&juce::File::isAbsolutePath(python)&&juce::File(python).existsAsFile();
        providers.add(object({{"kind",name},{"available",available},{"model_id",p["model_id"]},{"version",p["version"]},{"experimental",true},{"device",p["device"]},{"cpu_threads",2},
            {"detail",available?p.getProperty("reason","Local analysis; review candidates before import."):juce::var("Model runtime is not installed or not ready. Run scripts/setup_analysis.py.")}}));
    }
    return object({{"protocol_version",1},{"providers",providers},{"max_duration_seconds",600},{"max_parallel_jobs",1},{"preview_stems",true},{"drum_transcription",false},{"cpu_threads",2},{"score_kind","uncalibrated_similarity"}});
}
bool EngineSession::Impl::analysisSourceMatches(const AnalysisEntry& a)const
{
    if(a.source["project_id"].toString()!=juce::String(guard.projectId())||std::abs(double(a.source["bpm"])-edit->tempoSequence.getTempo(0)->getBpm())>1.0e-9)return false;
    for(const auto& t:bindings)for(const auto& c:t.clips)if(c.id==a.source["clip_id"].toString()){
        const auto p=c.clip->getPosition();return c.assetId==a.source["asset_id"].toString()&&c.source==a.boundOriginal&&c.info.playbackFile==a.sourceFile
            &&std::abs(p.time.getStart().inSeconds()-double(a.source["clip_timeline_start"]))<1.0e-9
            &&std::abs(p.offset.inSeconds()-double(a.source["clip_source_offset"]))<1.0e-9
            &&std::abs(p.time.getLength().inSeconds()-double(a.source["clip_duration"]))<1.0e-9;
    }return false;
}
juce::var EngineSession::Impl::analysisJobs()const
{
    juce::Array<juce::var> list;
    for(const auto& [id,a]:analyses){if(a->source["project_id"].toString()!=juce::String(guard.projectId())||!a->job)continue;
        std::lock_guard lock(a->job->mutex);
        list.add(object({{"job_id",a->job->id},{"kind",a->kind},{"status",a->applied?juce::String("applied"):a->job->status},{"result_id",id},{"clip_id",a->source["clip_id"]}}));
    }return list;
}
juce::Result EngineSession::Impl::beginAnalysis(const juce::var& args,juce::var& out)
{
    if(recordingBusy()||nativePending)return fail("Finish recording and pending device edits before analysis.");
    const auto kind=textArg(args,"kind");if(kind!="separate"&&kind!="transcribe"&&kind!="chords")return fail("Choose separate, transcribe or chords.");
    for(const auto& j:jobs)if(j->worker.joinable()&&j->kind.startsWith("analysis.")&&j->kind!="analysis.preview")return fail("One analysis is already running. Wait or cancel it first.");
    Binding* track=nullptr;auto* clip=findClip(textArg(args,"clip_id"),&track);
    if(!clip||!dynamic_cast<te::WaveAudioClip*>(clip->clip.get())||clip->info.playbackFile==juce::File())return fail("Select a prepared audio clip to analyze.");
    const auto p=clip->clip->getPosition();double start=analysisOption(args,"start_seconds",0),length=analysisOption(args,"duration_seconds",p.time.getLength().inSeconds()-start);
    if(!std::isfinite(start)||!std::isfinite(length)||start<0||length<=0||length>600||start+length>p.time.getLength().inSeconds()+1.0e-9)return fail("Analysis requires a positive clip-relative range of at most 600 seconds.");
    // Analyze complete source samples contained by the requested range. The
    // frozen duration is then identical in Python, MIDI validation and import;
    // sub-sample grid selections cannot create a final note beyond its clip.
    const auto rate=clip->info.rate;const auto first=std::ceil((p.offset.inSeconds()+start)*rate-1.0e-7);
    const auto last=std::floor((p.offset.inSeconds()+start+length)*rate+1.0e-7);
    if(!std::isfinite(rate)||rate<=0||last<=first)return fail("The selected range must contain at least one full source sample.");
    start=juce::jmax(0.0,first/rate-p.offset.inSeconds());length=(last-first)/rate;
    juce::var registry;if(auto r=analysisJson(analysisRoot().getChildFile("registry.json"),registry,128*1024);r.failed())return fail("Install the local analysis runtimes first.");
    auto provider=registry["providers"].getProperty(kind,{});const auto python=provider["python_executable"].toString();
    if(!bool(provider["available"])||!juce::File::isAbsolutePath(python)||!juce::File(python).existsAsFile())return fail("This analysis runtime is not ready.");
    auto params=args.getProperty("parameters",object({}));if(!params.isObject()||juce::JSON::toString(params).getNumBytesAsUTF8()>4096)return fail("Invalid analysis parameters.");
    if(analyses.size()>=32){auto old=std::find_if(analyses.begin(),analyses.end(),[](const auto& a){return a.second->job&&!a.second->job->worker.joinable()&&(!a.second->acceptJob||!a.second->acceptJob->worker.joinable());});if(old==analyses.end())return fail("Analysis result history is full.");analyses.erase(old);}
    auto a=std::make_shared<AnalysisEntry>();a->id=uid();a->kind=kind;a->original=a->boundOriginal=clip->source;a->sourceFile=clip->info.playbackFile;a->parameters=params.clone();
    a->directory=analysisRoot().getChildFile("cache/jobs").getChildFile(a->id);
    juce::String role=clip->clip->state["emAnalysisRole"].toString();if(role.isEmpty())role="pitched_or_unknown";
    if(kind=="transcribe"&&(role=="drums"||role=="other"))return fail("Pitched transcription does not support drums or mixed other stems. Use a pitched instrument source.");
    a->source=object({{"project_id",juce::String(guard.projectId())},{"clip_id",clip->id},{"asset_id",clip->assetId},{"track_id",track->id},{"clip_timeline_start",p.time.getStart().inSeconds()},{"clip_source_offset",p.offset.inSeconds()},{"clip_duration",p.time.getLength().inSeconds()},
        {"bpm",edit->tempoSequence.getTempo(0)->getBpm()},{"range_start_seconds",start},{"duration_seconds",length},{"timeline_start",p.time.getStart().inSeconds()+start},{"sample_rate",clip->info.rate},{"input_role",role}});
    const auto script=juce::File(EMUSICIAN_SOURCE_DIR).getChildFile("scripts/audio_analysis/run.py");const auto preset=textArg(args,"preset");
    a->job=startJob("analysis."+kind,[this,a,script,python,preset,length](const auto& j){
        const auto cancelled=[j]{return j->cancel.load();};JobFingerprint before,after;
        if(auto r=fingerprint(a->original,before,cancelled);r.failed()||!before.exists){jobStatus(j,cancelled()?"cancelled":"failed",r.failed()?r.getErrorMessage():"The source audio is missing.");return;}
        // AudioSource names each prepared MP3 WAV by the original MP3 hash.
        // External replacement must not analyze an old decode under a new hash.
        if(a->original.hasFileExtension("mp3")&&a->sourceFile.getFileNameWithoutExtension()!=before.hash){jobStatus(j,"stale","The MP3 changed after import. Reimport it before analyzing.");return;}
        if(!a->directory.createDirectory()){jobStatus(j,"failed","Cannot create the analysis cache directory.");return;}
        auto request=object({{"schema_version",1},{"job_id",a->id},{"kind",a->kind},{"preset",preset},{"source_path",a->sourceFile.getFullPathName()},
            {"source_offset_seconds",double(a->source["clip_source_offset"])+double(a->source["range_start_seconds"])},{"duration_seconds",length},{"analysis_root",analysisRoot().getFullPathName()},{"source",a->source},{"parameters",a->parameters}});
        if(!a->directory.getChildFile("request.json").replaceWithText(juce::JSON::toString(request))){jobStatus(j,"failed","Cannot write the analysis request.");return;}
        juce::ChildProcess process;juce::StringArray command{python,script.getFullPathName(),"--request",a->directory.getChildFile("request.json").getFullPathName()};
        if(!process.start(command,0)){jobStatus(j,"failed","Cannot start the isolated analysis worker.");return;}
        const auto began=juce::Time::getMillisecondCounterHiRes();bool terminated=false;
        while(process.isRunning()){
            if(cancelled()||juce::Time::getMillisecondCounterHiRes()-began>60.0*60.0*1000.0){
                a->directory.getChildFile("cancel").replaceWithText("cancel");if(!process.waitForProcessToFinish(500))process.kill();terminated=true;break;
            }
            juce::var progress;if(analysisJson(a->directory.getChildFile("progress.json"),progress,32768).wasOk()){
                std::lock_guard lock(j->mutex);j->phase=progress["phase"].toString().substring(0,128);j->detail=progress["detail"].toString().substring(0,512);
                if(analysisNumber(progress["progress"]))j->progress=juce::jlimit(0.0,1.0,double(progress["progress"]));
            }std::this_thread::sleep_for(std::chrono::milliseconds(200));
        }
        if(terminated||cancelled()){jobStatus(j,cancelled()?"cancelled":"failed",cancelled()?"":"Analysis exceeded its one-hour worker limit.");return;}
        if(process.getExitCode()!=0){juce::var error;analysisJson(a->directory.getChildFile("error.json"),error,32768);jobStatus(j,"failed",error["message"].toString().isNotEmpty()?error["message"].toString().substring(0,1024):"The analysis worker exited before producing a result.");return;}
        juce::var result;const auto file=a->directory.getChildFile("result.json");
        if(auto r=analysisJson(file,result);r.failed()){jobStatus(j,"failed",r.getErrorMessage());return;}
        if(auto r=validateAnalysisResult(result,a->id,a->kind,length);r.failed()){jobStatus(j,"failed",r.getErrorMessage());return;}
        if(auto r=fingerprint(a->original,after,cancelled);r.failed()||before.hash!=after.hash){jobStatus(j,cancelled()?"cancelled":"stale","Source audio changed during analysis.");return;}
        JobFingerprint resultFingerprint;if(auto r=fingerprint(file,resultFingerprint,cancelled);r.failed()){jobFailure(j,r);return;}
        // Publish on the control thread; workers never touch Edit/selection/maps.
        std::lock_guard lock(j->mutex);j->commit=[this,a,j,result,before,resultFingerprint]{
            if(j->cancel){jobStatus(j,"cancelled");return;}
            if(!analysisSourceMatches(*a)){jobStatus(j,"stale","The source clip, tempo or project changed. Run a new analysis.");return;}
            a->originalHash=before.hash;a->resultHash=resultFingerprint.hash;a->result=result;
            a->source.getDynamicObject()->setProperty("source_sha256",result["source"]["source_sha256"]);
            jobStatus(j,"ready",{},1);publish("analysis_ready",object({{"job_id",j->id},{"result_id",a->id},{"kind",a->kind}}));
        };
    });
    if(!a->job)return juce::Result::fail(status);analyses[a->id]=a;out=object({{"job_id",a->job->id},{"result_id",a->id}});return juce::Result::ok();
}

juce::Result EngineSession::Impl::acceptAnalysis(const juce::var& args,juce::var& out)
{
    auto found=analyses.find(textArg(args,"result_id"));if(found==analyses.end())return fail("Analysis result is no longer available.");auto a=found->second;
    if(!analysisSourceMatches(*a))return fail("The source clip, tempo or project changed. Analyze the current range again.");
    if(a->applied){if(!metadata(*edit).getChildWithName("EM_ANALYSES").getChildWithProperty("id",a->id).isValid())return fail("This import was undone. Use Redo to restore it; it cannot be imported twice.");out=a->receipt;return juce::Result::ok();}
    if(a->acceptJob&&a->acceptJob->worker.joinable()){out=object({{"job_id",a->acceptJob->id},{"result_id",a->id}});return juce::Result::ok();}
    {std::lock_guard lock(a->job->mutex);if(a->job->status!="ready"||!a->result.isObject())return fail("Wait for a ready analysis result.");}
    if(a->result.getProperty(analysisItemsKey(a->kind),{}).size()==0)return fail("The candidate is empty; there is nothing to import.");
    if(recordingBusy()||nativePending)return fail("Finish recording and pending device edits before importing analysis.");
    auto candidate=std::make_shared<storage::StoredProject>(capture());const auto source=a->source;const auto result=a->result;const auto revision=guard.revision();const auto project=juce::String(guard.projectId());
    const auto boundOriginal=a->boundOriginal;
    a->acceptJob=startJob("analysis.accept",[this,a,candidate,source,result,revision,project,boundOriginal](const auto& j){
        jobStatus(j,"applying",{},0);const auto cancelled=[j]{return j->cancel.load();};JobFingerprint actual;
        if(auto r=fingerprint(a->original,actual,cancelled);r.failed()||actual.hash!=a->originalHash){jobStatus(j,cancelled()?"cancelled":"stale","Source audio changed since the candidate was created.");return;}
        if(boundOriginal!=a->original){
            if(auto r=fingerprint(boundOriginal,actual,cancelled);r.failed()||actual.hash!=a->originalHash){jobStatus(j,cancelled()?"cancelled":"stale","Archived source audio changed since analysis.");return;}
        }
        if(auto r=fingerprint(a->sourceFile,actual,cancelled);r.failed()||actual.hash!=result["source"]["source_sha256"].toString()){jobStatus(j,cancelled()?"cancelled":"stale","Prepared source audio changed since analysis.");return;}
        if(auto r=fingerprint(a->directory.getChildFile("result.json"),actual,cancelled);r.failed()||actual.hash!=a->resultHash){jobStatus(j,cancelled()?"cancelled":"failed","The immutable analysis result changed on disk.");return;}
        std::map<juce::String,AudioInfo> preparedOutputs;juce::Array<juce::var> trackIds,clipIds,chordIds;
        const double start=double(source["timeline_start"]),length=double(source["duration_seconds"]);
        storage::StoredAnalysis provenance{a->id,a->kind,result["model"]["id"].toString(),result["model"]["version"].toString(),source["clip_id"].toString(),source["asset_id"].toString(),a->originalHash,a->resultHash,juce::JSON::toString(a->parameters,true),start,length};
        candidate->analyses.push_back(provenance);candidate->schemaVersion=5;
        if(a->kind=="separate"){
            for(const auto& stem:*result["stems"].getArray()){
                const auto path=stem["path"].toString();if(juce::File::isAbsolutePath(path)||path.contains("..")||!path.endsWithIgnoreCase(".wav")){jobStatus(j,"failed","Invalid stem path.");return;}
                auto file=a->directory.getChildFile(path);if(!file.isAChildOf(a->directory)||file.isSymbolicLink()){jobStatus(j,"failed","Stem escaped the analysis directory.");return;}
                if(auto r=fingerprint(file,actual,cancelled);r.failed()||!actual.exists||actual.hash!=stem["sha256"].toString()){jobStatus(j,cancelled()?"cancelled":"failed","Separated audio content changed or is missing.");return;}
                AudioInfo info;if(auto r=inspectAudio(file,info);r.failed()||std::abs(info.duration-length)>.002||info.channels<1||info.channels>2||std::abs(info.rate-double(stem["sample_rate"]))>.01){jobStatus(j,"failed","Separated audio format or duration is invalid.");return;}
                // Copy outside disposable candidate cache before accepting. This
                // session asset remains valid through Undo/Redo; save bundles it.
                const auto assetDir=analysisRoot().getChildFile("assets").getChildFile(project).getChildFile(a->id);
                if(!assetDir.createDirectory()){jobStatus(j,"failed","Cannot create accepted audio asset directory.");return;}
                auto retained=assetDir.getChildFile(stem["name"].toString()+".wav");if(!file.copyFileTo(retained)){jobStatus(j,"failed","Cannot retain separated audio.");return;}
                info.playbackFile=retained;preparedOutputs[retained.getFullPathName()]=info;
                storage::StoredAsset asset{uid(),retained};storage::StoredTrack track;track.id=uid();track.name="Separated / "+stem["name"].toString();
                storage::StoredClip clip{uid(),asset.id,start,0,info.duration};clip.analysisRole=stem["name"].toString();track.clips.push_back(clip);trackIds.add(track.id);clipIds.add(clip.id);candidate->assets.push_back(asset);candidate->tracks.push_back(std::move(track));
            }
        }else if(a->kind=="transcribe"){
            storage::StoredTrack track;track.id=uid();track.name="Transcribed MIDI";track.kind="instrument";
            storage::StoredClip clip;clip.id=uid();clip.kind="midi";clip.timelineStart=start;clip.duration=length;clip.startBeats=time::secondsToBeats(start,candidate->bpm);clip.lengthBeats=time::secondsToBeats(length,candidate->bpm);
            for(const auto& n:*result["notes"].getArray())clip.notes.push_back({uid(),int(n["pitch"]),time::secondsToBeats(double(n["start_seconds"]),candidate->bpm),time::secondsToBeats(double(n["duration_seconds"]),candidate->bpm),int(n["velocity"]),1});
            track.clips.push_back(clip);trackIds.add(track.id);clipIds.add(clip.id);candidate->tracks.push_back(std::move(track));
        }else for(const auto& c:*result["chord_regions"].getArray()){
            storage::StoredChordRegion chord{uid(),c["label"].toString(),a->id,start+double(c["start_seconds"]),start+double(c["end_seconds"]),double(c["score"]),bool(c["uncertain"])};
            chordIds.add(chord.id);candidate->chordRegions.push_back(std::move(chord));
        }
        if(auto r=storage::validate(*candidate);r.failed()){jobStatus(j,"failed",r.getErrorMessage());return;}
        if(cancelled()){jobStatus(j,"cancelled");return;}
        auto receipt=object({{"result_id",a->id},{"applied",true},{"track_ids",trackIds},{"clip_ids",clipIds},{"chord_ids",chordIds},{"revision",juce::int64(revision+1)}});
        std::lock_guard lock(j->mutex);j->commit=[this,a,j,candidate,preparedOutputs,receipt,revision,project]{
            if(j->cancel){jobStatus(j,"cancelled");return;}
            if(guard.revision()!=revision||juce::String(guard.projectId())!=project||!analysisSourceMatches(*a)||recordingBusy()||nativePending){jobStatus(j,"stale","Project changed while validating the import. Review and import again.");return;}
            for(const auto& [path,info]:preparedOutputs)prepared[path]=info;
            finishGesture();remember("Import analysis result");
            auto applied=juce::Result::ok();
            try{applied=applyTo(*edit,*candidate,bindings,false);}catch(const std::exception& error){applied=juce::Result::fail(error.what());}
            if(applied.failed()){
                edit->getUndoManager().undoCurrentTransactionOnly();rebuild(*edit,bindings);refreshRange();refreshPluginWatches();
                cachedRevision=std::numeric_limits<std::uint64_t>::max();jobStatus(j,"failed",applied.getErrorMessage());return;
            }
            refreshRange();if(receipt["clip_ids"].size()>0)choose(receipt["track_ids"][0].toString(),receipt["clip_ids"][0].toString());
            // Tracktion finishes some new track/clip properties on the next
            // message turn. Keep that tail in this atomic import transaction,
            // exactly as for batch edits and recorded takes. The next explicit
            // edit/save/Undo closes it; one Undo must remove the entire import.
            recordEdit(false);a->applied=true;a->receipt=receipt;jobStatus(j,"applied",{},1);publish("analysis_applied",receipt);
        };
    });
    if(!a->acceptJob)return juce::Result::fail(status);out=object({{"job_id",a->acceptJob->id},{"result_id",a->id}});return juce::Result::ok();
}

juce::Result EngineSession::Impl::analysisCommand(const juce::String& command,const juce::var& args,juce::var& out)
{
    if(command=="get_analysis_preview_status"){out=analysisPreview?analysisPreview->status():object({{"status","stopped"}});return juce::Result::ok();}
    if(command=="stop_analysis_preview"){++analysisPreviewGeneration;if(analysisPreview)analysisPreview->stop();for(const auto& j:jobs)if(j->kind=="analysis.preview"&&j->worker.joinable())j->cancel=true;out=object({{"status","stopped"}});return juce::Result::ok();}
    if(command=="preview_analysis_stem"){
        if(recordingBusy())return fail("Stop recording before auditioning a candidate.");
        auto found=analyses.find(textArg(args,"result_id"));if(found==analyses.end()||!analysisSourceMatches(*found->second))return fail("Candidate source is no longer current.");auto a=found->second;
        const auto index=args["index"];if(!index.isInt()||a->kind!="separate"||!a->result.isObject()||int(index)<0||int(index)>=a->result["stems"].size())return fail("Select a separated stem to audition.");
        if(!engine.getDeviceManager().deviceManager.getCurrentAudioDevice())return fail("Select an audio output before auditioning.");
        if(!analysisPreview)analysisPreview=std::make_unique<AnalysisPreview>(engine.getDeviceManager().deviceManager);
        const auto token=++analysisPreviewGeneration;analysisPreview->stop();
        // A new selection supersedes the entire old load, including its file
        // hash. Generation checks alone would discard output but keep disk I/O.
        for(const auto& previous:jobs)if(previous->kind=="analysis.preview"&&previous->worker.joinable())previous->cancel=true;
        const auto stem=a->result["stems"][int(index)];const auto path=stem["path"].toString();
        if(juce::File::isAbsolutePath(path)||path.contains("..")||!path.endsWithIgnoreCase(".wav"))return fail("Invalid candidate artifact path.");
        const auto file=a->directory.getChildFile(path);if(!file.isAChildOf(a->directory)||file.isSymbolicLink())return fail("Invalid candidate artifact location.");
        auto job=startJob("analysis.preview",[this,a,token,file,stem](const auto& j){
            JobFingerprint value;if(auto r=fingerprint(file,value,[j]{return j->cancel.load();});r.failed()||!value.exists||value.hash!=stem["sha256"].toString()){jobStatus(j,j->cancel.load()?"cancelled":"failed","Candidate audio changed or could not be verified.");return;}
            std::lock_guard lock(j->mutex);j->commit=[this,a,j,token,file]{
                if(j->cancel||token!=analysisPreviewGeneration||!analysisSourceMatches(*a)){jobStatus(j,"cancelled");return;}
                if(recordingBusy()){jobStatus(j,"failed","Recording has priority over audition.");return;}
                auto r=analysisPreview->prepareAndPlay(file);jobStatus(j,r.wasOk()?"completed":"failed",r.getErrorMessage(),1);
            };
        });
        if(!job)return juce::Result::fail(status);out=object({{"job_id",job->id},{"status","loading"}});return juce::Result::ok();
    }
    if(command=="get_analysis_capabilities"){out=analysisCapabilities();return juce::Result::ok();}
    if(command=="start_analysis")return beginAnalysis(args,out);
    if(command=="accept_analysis_result")return acceptAnalysis(args,out);
    if(command=="get_analysis_job"||command=="cancel_analysis_job"){
        for(const auto& [id,a]:analyses)for(const auto& j:{a->job,a->acceptJob})if(j&&j->id==textArg(args,"job_id")){
            if(a->source["project_id"].toString()!=juce::String(guard.projectId()))return fail("This task belongs to another project.");
            if(command=="cancel_analysis_job"){j->cancel=true;out=object({{"job_id",j->id},{"cancel_requested",true}});return juce::Result::ok();}
            std::lock_guard lock(j->mutex);const auto& result=a->result;const int count=result.getProperty(analysisItemsKey(a->kind),{}).size();
            out=object({{"job_id",j->id},{"id",j->id},{"kind",a->kind},{"status",a->applied?juce::String("applied"):j->status},{"progress",j->progress},{"phase",j->phase},{"detail",j->detail},{"error",j->error},{"result_id",a->id},{"source",a->source},{"receipt",a->receipt},{"summary",object({{"kind",a->kind},{"total",count}})}});return juce::Result::ok();
        }return fail("Analysis task not found.");
    }
    if(command=="get_analysis_result"){
        const auto found=analyses.find(textArg(args,"result_id"));if(found==analyses.end())return fail("Analysis result not found.");const auto& a=*found->second;
        if(a.source["project_id"].toString()!=juce::String(guard.projectId()))return fail("This result belongs to another project.");
        if(!a.result.isObject())return fail("Analysis result is not ready.");
        const auto offset=analysisOption(args,"offset",0),limit=analysisOption(args,"limit",100);
        if(!std::isfinite(offset)||!std::isfinite(limit)||offset<0||offset>100000||offset!=std::floor(offset)||limit<1||limit>100||limit!=std::floor(limit))return fail("Analysis pages require offset >= 0 and limit 1 to 100.");
        const auto& list=a.result.getProperty(analysisItemsKey(a.kind),{});juce::Array<juce::var> page;
        for(int i=int(offset);i<std::min(list.size(),int(offset+limit));++i){auto item=list[i].clone();if(auto* o=item.getDynamicObject()){o->removeProperty("path");o->setProperty("index",i);}page.add(item);}
        out=object({{"result_id",a.id},{"kind",a.kind},{"total",list.size()},{"offset",int(offset)},{"has_more",offset+page.size()<list.size()},{"items",page},{"source",a.source},{"model",a.result["model"]},{"parameters",a.parameters},{"score_kind",a.result.getProperty("score_kind","uncalibrated_similarity")},{"result_hash",a.resultHash},{"applied",a.applied},{"present_in_project",metadata(*edit).getChildWithName("EM_ANALYSES").getChildWithProperty("id",a.id).isValid()},{"receipt",a.receipt},{"stale",!analysisSourceMatches(a)},{"limitations",a.result["limitations"]}});return juce::Result::ok();
    }
    if(command=="get_chord_regions"){
        const auto offset=analysisOption(args,"offset",0),limit=analysisOption(args,"limit",100);if(!std::isfinite(offset)||!std::isfinite(limit)||offset<0||offset>10000||offset!=std::floor(offset)||limit<1||limit>100||limit!=std::floor(limit))return fail("Invalid chord page.");
        auto meta=metadata(*edit);std::set<juce::String> selectedAnalyses;const auto clip=textArg(args,"clip_id");
        for(const auto& a:meta.getChildWithName("EM_ANALYSES"))if(clip.isEmpty()||a["source_clip_id"].toString()==clip)selectedAnalyses.insert(a["id"].toString());
        juce::Array<juce::var> page;int total=0;
        for(const auto& c:meta.getChildWithName("EM_CHORDS"))if(selectedAnalyses.contains(c["analysis_id"].toString())){
            if(total>=int(offset)&&page.size()<int(limit))page.add(object({{"id",c["id"]},{"label",c["label"]},{"analysis_id",c["analysis_id"]},{"start_seconds",c["start_seconds"]},{"end_seconds",c["end_seconds"]},{"score",c["score"]},{"uncertain",c["uncertain"]}}));++total;
        }
        out=object({{"total",total},{"items",page},{"offset",int(offset)},{"has_more",offset+page.size()<total},{"score_kind","uncalibrated_similarity"}});return juce::Result::ok();
    }
    if(command=="edit_chord_region"){
        auto region=metadata(*edit).getChildWithName("EM_CHORDS").getChildWithProperty("id",textArg(args,"id"));
        if(!region.isValid())return fail("Chord region not found.");
        const auto label=args.hasProperty("label")?textArg(args,"label"):region["label"].toString();
        const auto start=analysisOption(args,"start_seconds",double(region["start_seconds"])),end=analysisOption(args,"end_seconds",double(region["end_seconds"]));
        if(!storage::isSupportedChordLabel(label)||!std::isfinite(start)||!std::isfinite(end)||start<0||end<=start||end>storage::maximumTimelineSeconds)return fail("Invalid chord label or timeline range.");
        finishGesture();remember("Edit chord region");auto* undo=&edit->getUndoManager();
        region.setProperty("label",label,undo);region.setProperty("start_seconds",start,undo);region.setProperty("end_seconds",end,undo);
        out=object({{"id",region["id"]},{"label",region["label"]},{"analysis_id",region["analysis_id"]},{"start_seconds",start},{"end_seconds",end},{"score",region["score"]},{"uncertain",region["uncertain"]}});
        recordEdit();return juce::Result::ok();
    }
    return fail("Unsupported analysis command.");
}
