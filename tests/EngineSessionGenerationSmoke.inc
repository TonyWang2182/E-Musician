// Synthetic local PCM tests: no inference, network or physical audio device.
juce::Result EngineSession::runGenerationEngineSmokeTest(juce::DynamicObject& report,const juce::File& directory)
{
    requireControlThread();
    struct ScopedRoot {
        juce::String previous=juce::SystemStats::getEnvironmentVariable("EMUSICIAN_GENERATION_ROOT",{});
        explicit ScopedRoot(const juce::File& file){set(file.getFullPathName());}
        ~ScopedRoot(){set(previous);}
        static void set(const juce::String& value){
#if JUCE_WINDOWS
            _putenv_s("EMUSICIAN_GENERATION_ROOT",value.toRawUTF8());
#else
            if(value.isEmpty())unsetenv("EMUSICIAN_GENERATION_ROOT");else setenv("EMUSICIAN_GENERATION_ROOT",value.toRawUTF8(),1);
#endif
        }
    } scopedRoot(directory);
    EngineSession test(false);int checks=0;
    const auto check=[&](bool ok,const juce::String& text){if(!ok)throw std::runtime_error(text.toStdString());++checks;};
    const auto okay=[&](const juce::Result& r,const juce::String& text){check(r.wasOk(),text+": "+r.getErrorMessage());};
    const auto run=[&](const juce::String& cmd,const juce::var& args,juce::var* output=nullptr){return test.execute(cmd,args,test.snapshot().revision,output);};
    try{
        okay(directory.createDirectory(),"generation fixture directory");
        auto g=std::make_shared<Impl::GenerationEntry>();g->id=uid();g->directory=directory.getChildFile("candidate");okay(g->directory.createDirectory(),"candidate directory");
        const auto file=g->directory.getChildFile("audio.wav");
        {juce::WavAudioFormat format;auto stream=file.createOutputStream();check(bool(stream),"fixture stream");
            std::unique_ptr<juce::AudioFormatWriter> writer(format.createWriterFor(stream.release(),48000,2,16,{},0));check(bool(writer),"PCM writer");
            juce::AudioBuffer<float> samples(2,48000);for(int c=0;c<2;++c)for(int i=0;i<48000;++i)samples.setSample(c,i,.1f*std::sin(float(i)*.05f));check(writer->writeFromAudioSampleBuffer(samples,0,48000),"synthetic waveform");}
        const auto snapshot=test.snapshot();g->source=object({{"project_id",snapshot.projectId},{"revision",juce::int64(snapshot.revision)},{"bpm",snapshot.bpm},{"meter_numerator",snapshot.numerator},{"meter_denominator",snapshot.denominator},{"timeline_start",2.0}});
        g->parameters=object({{"prompt","Synthetic fixture; not generated music"},{"lyrics",""},{"seed",123},{"duration_seconds",10.0},{"bpm",120.0}});
        JobFingerprint hash;okay(fingerprint(file,hash,{}),"fixture hash");
        g->result=object({{"schema_version",1},{"job_id",g->id},{"result_id",g->id},{"kind","generate"},{"audio",object({{"path","audio.wav"},{"sha256",hash.hash},{"duration_seconds",1.0},{"sample_rate",48000},{"channels",2}})},{"model",object({{"id","synthetic-test"},{"revision","fixture-v1"}})},{"parameters",g->parameters}});
        auto resultFile=g->directory.getChildFile("result.json");check(resultFile.replaceWithText(juce::JSON::toString(g->result)),"fixture manifest");okay(fingerprint(resultFile,hash,{}),"manifest hash");g->resultHash=hash.hash;
        g->job=std::make_shared<Impl::Job>();g->job->kind="generation.generate";g->job->status="ready";g->job->done=true;test.impl->generations[g->id]=g;
        AudioInfo info;okay(generationAudio(g->result,g->directory,g->id,info,{}),"valid local generated candidate");
        auto bad=g->result.clone();bad["audio"].getDynamicObject()->setProperty("path","../audio.wav");check(generationAudio(bad,g->directory,g->id,info,{}).failed(),"reject path escape");
        bad=g->result.clone();bad["audio"].getDynamicObject()->setProperty("sha256",juce::String::repeatedString("0",64));check(generationAudio(bad,g->directory,g->id,info,{}).failed(),"reject corrupt checksum");
        bad=g->result.clone();bad["audio"].getDynamicObject()->setProperty("duration_seconds",2.0);check(generationAudio(bad,g->directory,g->id,info,{}).failed(),"reject false duration");
        check(run("start_generation",object({{"prompt",""},{"duration_seconds",10}})).failed(),"reject empty prompt before runtime");
        check(run("start_generation",object({{"prompt","x"},{"duration_seconds",0}})).failed(),"reject zero requested duration");
        check(run("accept_generation_result",object({{"result_id",g->id},{"result_hash","changed"}})).failed(),"accept binds reviewed hash");
        auto args=object({{"result_id",g->id},{"result_hash",g->resultHash}});juce::var started;
        okay(run("accept_generation_result",args,&started),"start local candidate adoption");
        const auto deadline=juce::Time::getMillisecondCounterHiRes()+10000;
        while(g->acceptJob->worker.joinable()&&juce::Time::getMillisecondCounterHiRes()<deadline){juce::MessageManager::getInstance()->runDispatchLoopUntil(10);test.impl->reapFinishedJobs(true);}
        check(g->acceptJob->status=="applied","adoption completes: "+g->acceptJob->error);
        check(test.snapshot().tracks.size()==1&&test.snapshot().tracks.front().clips.size()==1,"one track and clip");
        check(test.snapshot().revision==snapshot.revision+1,"one project revision");
        check(std::abs(test.snapshot().tracks.front().clips.front().timelineStart-2.0)<1e-9,"frozen timeline position retained");
        const auto accepted=test.impl->capture();check(accepted.schemaVersion==7&&accepted.generations.size()==1,"generation has distinct schema7 provenance");
        check(accepted.generations.front().modelId=="synthetic-test"&&accepted.generations.front().parametersJson.contains("Synthetic fixture"),"model and prompt retained");
        okay(run("accept_generation_result",args),"duplicate accept idempotent");check(test.snapshot().revision==snapshot.revision+1,"duplicate no edit");
        okay(test.undo(test.snapshot().revision),"generation one Undo");check(test.snapshot().tracks.empty()&&test.impl->capture().generations.empty(),"Undo removes track and provenance together");
        check(run("accept_generation_result",args).failed(),"undone result cannot duplicate import");
        okay(test.redo(test.snapshot().revision),"generation Redo");check(test.snapshot().tracks.size()==1&&test.impl->capture().generations.size()==1,"Redo restores asset references");
        const auto project=directory.getChildFile("generated.emproj");okay(test.saveProject(project,test.snapshot().revision),"save generated project");
        storage::StoredProject saved;okay(storage::load(project,saved),"load schema7 manifest");check(saved.generations.size()==1&&saved.assets.size()==1&&saved.assets.front().source.existsAsFile(),"saved generation is a local project asset");
        auto unsupported=saved;unsupported.schemaVersion=6;check(storage::validate(unsupported).failed(),"generation may not masquerade as schema6");
        okay(test.newProject(test.snapshot().revision),"switch project");check(run("accept_generation_result",args).failed(),"wrong project rejects old candidate");
        okay(test.openProject(project,test.snapshot().revision),"reopen generated project without inference");check(test.snapshot().tracks.size()==1&&test.impl->capture().generations.size()==1,"reopen retains track and provenance");
        const auto beforeHybrid=checks;
#include "EngineSessionHybridSmoke.inc"
        report.setProperty("hybrid_checks",checks-beforeHybrid);
        report.setProperty("generation_checks",beforeHybrid);report.setProperty("generation_fixture","synthetic PCM; no model, network or physical audio");return juce::Result::ok();
    }catch(const std::exception& e){report.setProperty("generation_checks",checks);report.setProperty("generation_error",e.what());return juce::Result::fail(e.what());}
}
