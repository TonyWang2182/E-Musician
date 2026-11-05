// Native offline integration, reached by the existing logged engine CTest.
// Generated audio only; no user projects, physical devices or LLM calls.
juce::Result EngineSession::runAudioWarpSmokeTest(const juce::File& directory,const std::vector<juce::File>& audioFixtures)
{
    int checks=0;
    const auto check=[&](bool pass,const juce::String& text){if(!pass)throw std::runtime_error(("Warp smoke: "+text).toStdString());++checks;};
    const auto okay=[&](const juce::Result& r,const juce::String& context){check(r.wasOk(),context+": "+r.getErrorMessage());};
    try{
        const auto folder=directory.getChildFile("warp-cases");check(!folder.exists(),"fresh fixture directory");okay(folder.createDirectory(),"fixture folder");
        const auto source=folder.getChildFile("stereo-tones-44100.wav");constexpr int rate=44100,frames=rate*2;
        juce::AudioBuffer<float> tone(2,frames);
        for(int i=0;i<frames;++i){const double fade=std::min({1.0,double(i)/1024,double(frames-1-i)/1024});
            tone.setSample(0,i,float(.25*fade*std::sin(juce::MathConstants<double>::twoPi*440*i/rate)));
            tone.setSample(1,i,float(.20*fade*std::sin(juce::MathConstants<double>::twoPi*660*i/rate)));
        }
        juce::WavAudioFormat format;auto output=source.createOutputStream();
        std::unique_ptr<juce::AudioFormatWriter> writer(format.createWriterFor(output.get(),rate,2,24,{},0));
        check(bool(writer),"fixture writer");output.release();check(writer->writeFromAudioSampleBuffer(tone,0,frames),"write fixture");writer.reset();
        const auto originalHash=juce::SHA256(source).toHexString();
        audio::PreparedSource input;okay(audio::prepareSource(source,input),"prepare fixture");
        juce::Array<juce::var> pitchEvidence;
        for(const double speed:{.8,1.25,2.0}){
            audio::WarpRender result;okay(audio::renderWarp(input,speed,result),"render fixed ratio");
            auto stream=result.source.playbackFile.createInputStream();std::unique_ptr<juce::AudioFormatReader> reader(format.createReaderFor(stream.release(),true));
            check(reader&&reader->lengthInSamples==std::llround(frames/speed)&&reader->sampleRate==rate&&reader->numChannels==2,"exact output frames/rate/channels");
            const int begin=int(.25*reader->lengthInSamples),count=int(.5*reader->lengthInSamples);
            juce::AudioBuffer<float> buffer(2,count);check(reader->read(&buffer,0,count,begin,true,true),"read stretched center");
            for(int channel=0;channel<2;++channel){int crossings=0;double energy=0;bool allFinite=true;
                for(int i=1;i<count;++i){const auto x=buffer.getSample(channel,i);allFinite=allFinite&&std::isfinite(x);energy+=x*x;
                    if(buffer.getSample(channel,i-1)<=0&&x>0)++crossings;
                }
                const double frequency=double(crossings)*rate/(count-1),expected=channel==0?440:660;
                check(allFinite,"finite output");
                check(energy/count>.005&&std::abs(frequency-expected)<3,"retains channel tone pitch and energy");
                pitchEvidence.add(object({{"speed_ratio",speed},{"channel",channel},{"measured_hz",frequency}}));
            }
            audio::WarpRender cached;okay(audio::renderWarp(input,speed,cached),"verified cache reuse");
            check(cached.source.playbackFile==result.source.playbackFile&&cached.renderHash==result.renderHash,"cache identity is stable");
        }
        // Broadband pulses near the beginning, middle and end exercise seek,
        // processing latency and flush. Energy centroid detects a constant DSP
        // delay even when exact length and stationary tone pitch both pass.
        const auto pulsesFile=folder.getChildFile("transient-timing-44100.wav");
        juce::AudioBuffer<float> pulses(1,frames);pulses.clear();juce::Random noise(88117);
        const std::array<double,3> pulseTimes{.08,1.0,1.92};
        for(int i=0;i<frames;++i){double envelope=0;for(const auto time:pulseTimes){const double delta=(double(i)/rate-time)/.004;envelope+=std::exp(-.5*delta*delta);}
            pulses.setSample(0,i,float(.5*envelope*(2*noise.nextDouble()-1)));}
        auto pulsesOutput=pulsesFile.createOutputStream();
        std::unique_ptr<juce::AudioFormatWriter> pulsesWriter(format.createWriterFor(pulsesOutput.get(),rate,1,24,{},0));
        check(bool(pulsesWriter),"transient writer");pulsesOutput.release();check(pulsesWriter->writeFromAudioSampleBuffer(pulses,0,frames),"write transient fixture");pulsesWriter.reset();
        audio::PreparedSource pulsesInput;okay(audio::prepareSource(pulsesFile,pulsesInput),"prepare transient fixture");
        juce::Array<juce::var> timingEvidence;
        for(const double speed:{.8,1.0,1.25,2.0}){
            audio::WarpRender result;okay(audio::renderWarp(pulsesInput,speed,result),"render transient timing");
            auto stream=result.source.playbackFile.createInputStream();std::unique_ptr<juce::AudioFormatReader> reader(format.createReaderFor(stream.release(),true));
            check(reader&&reader->lengthInSamples==std::llround(frames/speed),"transient exact length");
            juce::AudioBuffer<float> buffer(1,int(reader->lengthInSamples));check(reader->read(&buffer,0,buffer.getNumSamples(),0,true,false),"read transient render");
            for(const double sourceTime:pulseTimes){const double expected=sourceTime/speed;double mass=0,moment=0;
                const int first=std::max(0,int((expected-.10)*rate)),last=std::min(buffer.getNumSamples(),int((expected+.10)*rate));
                for(int i=first;i<last;++i){const double x=buffer.getSample(0,i),energy=x*x;mass+=energy;moment+=energy*i/rate;}
                const double measured=mass>0?moment/mass:-1,error=measured-expected;
                check(mass>.001&&std::abs(error)<.020,"transient time map/latency error under 20 ms: "+juce::String(error*1000,3));
                timingEvidence.add(object({{"speed_ratio",speed},{"source_seconds",sourceTime},{"expected_seconds",expected},{"measured_energy_centroid_seconds",measured},{"error_ms",error*1000}}));
            }
        }
        audio::WarpRender untouched;check(audio::renderWarp(input,1.1,untouched,{[]{return true;},{}}).failed()&&untouched.source.playbackFile==juce::File(),"cancel before render publishes no result");
        audio::TimeMap map{.2,1.0,1.25};check(map.valid()&&std::abs(map.sourceAt(1.4)-.7)<1e-12&&std::abs(map.timelineAt(.7)-1.4)<1e-12,"affine source/timeline round trip");

        EngineSession fixture(false);
        okay(fixture.importFile(source,fixture.snapshot().revision),"import original");
        const auto id=fixture.snapshot().tracks[0].clips[0].id,trackId=fixture.snapshot().tracks[0].id;
        okay(fixture.execute("trim_clip",object({{"clip_id",id},{"start_seconds",2.0},{"end_seconds",3.6},{"source_offset",.2}}),fixture.snapshot().revision),"trim original before Warp");
        const auto original=fixture.snapshot();
        const auto envelope=[&](EngineSession& s,const juce::String& command,const juce::var& args){const auto snap=s.snapshot();return object({{"request_id",uid()},{"project_id",snap.projectId},{"expected_revision",juce::int64(snap.revision)},{"command",command},{"args",args}});};
        const auto wait=[&](EngineSession& s,const juce::var& response,const juce::String& expected="completed"){
            check(response["status"].toString()=="accepted","request accepted: "+response["error"].toString());
            const auto jobId=response["result"]["job_id"].toString();check(jobId.isNotEmpty(),"async job receipt");
            const auto deadline=juce::Time::getMillisecondCounterHiRes()+60000;
            juce::var terminal;
            while(juce::Time::getMillisecondCounterHiRes()<deadline){
                juce::MessageManager::getInstance()->runDispatchLoopUntil(5);s.impl->reapFinishedJobs(true);
                for(const auto& job:s.impl->jobs)if(job->id==jobId){std::lock_guard lock(job->mutex);
                    if(!job->worker.joinable())terminal=object({{"status",job->status},{"error",job->error},{"result",job->result.clone()}});
                }
                if(terminal.isObject())break;
            }
            check(terminal["status"].toString()==expected,"job "+expected+": "+terminal["error"].toString());return terminal;
        };
        juce::Array<juce::var> exportEvidence;
        const auto verifyExport=[&](EngineSession& s,const juce::String& label){
            const auto before=s.snapshot();check(before.tracks.size()==1&&before.tracks[0].clips.size()==1,"export has one clip");
            const auto& selected=before.tracks[0].clips[0];check(selected.warpEnabled,"export fixture Warp enabled");
            auto pcmStream=selected.waveformSource.createInputStream();std::unique_ptr<juce::AudioFormatReader> pcm(format.createReaderFor(pcmStream.release(),true));
            check(bool(pcm),"open expected Warp PCM");const double exportRate=pcm->sampleRate;
            const double end=selected.timelineStart+selected.duration+.1;const auto destination=folder.getChildFile(label+"-export.wav");
            wait(s,s.executeRequest(envelope(s,"export_wav",object({{"path",destination.getFullPathName()},{"start_seconds",0.0},
                {"end_seconds",end},{"sample_rate",exportRate},{"bit_depth",24},{"tail_seconds",0.0}}))));
            auto exportedStream=destination.createInputStream();std::unique_ptr<juce::AudioFormatReader> exported(format.createReaderFor(exportedStream.release(),true));
            check(exported&&exported->numChannels==2&&exported->sampleRate==exportRate
                &&std::abs(exported->lengthInSamples-std::llround(end*exportRate))<=1,"isolated export frame count and format");
            const int margin=2048,count=int(selected.duration*exportRate)-2*margin;check(count>1024,"export comparison interior");
            const auto sourceStart=std::llround(selected.playbackSourceOffset*exportRate)+margin;
            const auto projectStart=std::llround(selected.timelineStart*exportRate)+margin;
            juce::AudioBuffer<float> reference(2,count),actual(2,count);
            check(pcm->read(&reference,0,count,sourceStart,true,true)&&exported->read(&actual,0,count,projectStart,true,true),"read source-mapped export windows");
            double worst=0;
            for(int channel=0;channel<2;++channel){double cross=0,sourceEnergy=0,error=0,outputEnergy=0;
                const int sourceChannel=pcm->numChannels==1?0:channel;
                for(int i=0;i<count;++i){const double a=reference.getSample(sourceChannel,i),b=actual.getSample(channel,i);cross+=a*b;sourceEnergy+=a*a;outputEnergy+=b*b;}
                check(sourceEnergy>1&&outputEnergy>.01,"export audio is not silent");const double gain=cross/sourceEnergy;
                for(int i=0;i<count;++i){const double delta=actual.getSample(channel,i)-gain*reference.getSample(sourceChannel,i);error+=delta*delta;}
                const double relative=std::sqrt(error/outputEnergy);worst=std::max(worst,relative);
                check(gain>.1&&gain<1.1&&relative<.002,"export matches warped PCM at mapped source offset: relative error "+juce::String(relative,8));
            }
            check(s.snapshot().revision==before.revision,"export does not edit project");
            exportEvidence.add(object({{"fixture",label},{"rate",exportRate},{"relative_pcm_error",worst},{"source_offset",selected.sourceOffset},{"playback_offset",selected.playbackSourceOffset}}));
        };
        const auto warpArgs=object({{"clip_ids",juce::var(juce::StringArray{id})},{"enabled",true},{"source_bpm",120.0},
            {"target_bpm",150.0},{"project_bpm",150.0},{"follow_tempo",true},{"first_beat_seconds",.4},{"align_start_seconds",1.0}});
        auto response=fixture.executeRequest(envelope(fixture,"set_audio_warp",warpArgs));
        check(fixture.snapshot().bpm==120&&fixture.snapshot().revision==original.revision,"old graph/tempo remain until render commit");wait(fixture,response);
        auto clip=fixture.snapshot().tracks[0].clips[0];
        check(clip.warpEnabled&&clip.warpFollowTempo&&std::abs(clip.warpSpeedRatio-1.25)<1e-12
            &&std::abs(clip.timelineStart-.68)<1e-9&&std::abs(clip.duration-1.28)<1e-9
            &&std::abs(clip.sourceOffset-.2)<1e-9&&std::abs(clip.playbackSourceOffset-.16)<1e-9,"Warp alignment and original/rendered offsets");
        check(fixture.snapshot().revision==original.revision+1,"one revision for Warp and project tempo");
        okay(fixture.undo(fixture.snapshot().revision),"undo Warp");
        auto restored=fixture.snapshot().tracks[0].clips[0];check(!restored.warpEnabled&&fixture.snapshot().bpm==120
            &&std::abs(restored.sourceOffset-.2)<1e-9&&std::abs(restored.timelineStart-2)<1e-9&&std::abs(restored.duration-1.6)<1e-9,"one Undo restores original audio and tempo");
        okay(fixture.redo(fixture.snapshot().revision),"redo Warp");check(fixture.snapshot().tracks[0].clips[0].warpEnabled&&fixture.snapshot().bpm==150,"Redo restores rendered audio and tempo");
        verifyExport(fixture,"trimmed-wav");
        clip=fixture.snapshot().tracks[0].clips[0];
        okay(fixture.execute("trim_clip",object({{"clip_id",id},{"start_seconds",clip.timelineStart+.2},{"end_seconds",clip.timelineStart+clip.duration}}),fixture.snapshot().revision),"trim warped clip");
        clip=fixture.snapshot().tracks[0].clips[0];check(std::abs(clip.sourceOffset-.45)<1e-9&&std::abs(clip.playbackSourceOffset-.36)<1e-9,"trim maps back to original source");
        okay(fixture.execute("split_clip",object({{"clip_id",id},{"at_seconds",clip.timelineStart+.4}}),fixture.snapshot().revision),"split warped clip");
        const auto split=fixture.snapshot().tracks[0].clips;check(split.size()==2&&std::abs(split[1].sourceOffset-.95)<1e-9,"split keeps correct original-source offset");
        const auto beforeTempo=fixture.snapshot();
        response=fixture.executeRequest(envelope(fixture,"set_tempo",object({{"bpm",90.0}})));
        check(fixture.snapshot().bpm==150,"following tempo remains unchanged while preparing");wait(fixture,response);
        auto afterTempo=fixture.snapshot();check(afterTempo.bpm==90&&afterTempo.revision==beforeTempo.revision+1
            &&std::abs(afterTempo.tracks[0].clips[0].warpSpeedRatio-.75)<1e-9
            &&std::abs(afterTempo.tracks[0].clips[0].timelineStart-beforeTempo.tracks[0].clips[0].timelineStart*150/90)<1e-9,"following tempo atomic positions and render");
        const auto saved=folder.getChildFile("warp.emproj");wait(fixture,fixture.executeRequest(envelope(fixture,"save_project",object({{"path",saved.getFullPathName()}}))));
        check(!fixture.snapshot().dirty,"save clears dirty after archive rebind");
        storage::StoredProject stored;okay(storage::load(saved,stored),"load saved schema6");check(stored.schemaVersion==6&&stored.assets.size()==2,"archive keeps original and rendered assets");
        EngineSession reopened(false);wait(reopened,reopened.executeRequest(envelope(reopened,"open_project",object({{"path",saved.getFullPathName()}}))));
        const auto reopenedClip=reopened.snapshot().tracks[0].clips[0];check(reopenedClip.warpEnabled&&reopenedClip.warpFollowTempo
            &&std::abs(reopenedClip.playbackSourceOffset-afterTempo.tracks[0].clips[0].playbackSourceOffset)<1e-9,"reopen retains playback map");
        const auto reopenedRevision=reopened.snapshot().revision;
        const auto disable=object({{"clip_ids",juce::var(juce::StringArray{id})},{"enabled",false}});
        response=reopened.executeRequest(envelope(reopened,"set_audio_warp",disable));
        okay(reopened.execute("cancel_job",object({{"job_id",response["result"]["job_id"]}}),reopenedRevision),"cancel pending Warp");wait(reopened,response,"cancelled");
        check(reopened.snapshot().revision==reopenedRevision&&reopened.snapshot().tracks[0].clips[0].warpEnabled,"cancel does not commit");
        response=reopened.executeRequest(envelope(reopened,"set_audio_warp",disable));
        okay(reopened.execute("set_track_pan",object({{"track_id",trackId},{"pan",.2}}),reopened.snapshot().revision),"concurrent legitimate edit");
        wait(reopened,response,"conflict");check(reopened.snapshot().tracks[0].clips[0].warpEnabled,"stale result cannot replace newer edit");
        const auto originalAsset=std::find_if(stored.assets.begin(),stored.assets.end(),[&](const auto& a){return a.id==stored.tracks[0].clips[0].assetId;});
        check(originalAsset!=stored.assets.end(),"find archived original for integrity fixture");
        juce::MemoryBlock originalBytes;check(originalAsset->source.loadFileAsData(originalBytes),"back up generated archived original");
        auto changedBytes=originalBytes;static_cast<unsigned char*>(changedBytes.getData())[changedBytes.getSize()-1]^=1;
        check(originalAsset->source.replaceWithData(changedBytes.getData(),changedBytes.getSize()),"mutate generated original outside engine");
        const auto integrityRevision=reopened.snapshot().revision;
        const auto failure=wait(reopened,reopened.executeRequest(envelope(reopened,"set_audio_warp",disable)),"failed");
        check(failure["error"].toString().contains("changed outside")&&reopened.snapshot().revision==integrityRevision,"changed original rejected without committing");
        check(originalAsset->source.replaceWithData(originalBytes.getData(),originalBytes.getSize()),"restore generated original bytes");
        wait(reopened,reopened.executeRequest(envelope(reopened,"set_audio_warp",disable)));
        check(!reopened.snapshot().tracks[0].clips[0].warpEnabled&&std::abs(reopened.snapshot().tracks[0].clips[0].sourceOffset-.45)<1e-9,"disable uses original media and original crop");
        check(juce::SHA256(source).toHexString()==originalHash,"original source bytes preserved");
        int mp3Count=0;
        for(const auto& audioFixture:audioFixtures)if(audioFixture.hasFileExtension("mp3")){
            const auto prefix="mp3-"+juce::String(++mp3Count);const auto owned=folder.getChildFile(prefix+".mp3");
            check(audioFixture.copyFileTo(owned),"copy owned MP3 Warp source");const auto rawHash=juce::SHA256(owned).toHexString();
            EngineSession mp3(false);okay(mp3.importFile(owned,mp3.snapshot().revision),"import actual MP3 for Warp");
            auto before=mp3.snapshot().tracks[0].clips[0];
            okay(mp3.execute("trim_clip",object({{"clip_id",before.id},{"start_seconds",.2},{"end_seconds",1.6},{"source_offset",.1}}),mp3.snapshot().revision),"trim MP3 source before Warp");
            wait(mp3,mp3.executeRequest(envelope(mp3,"set_audio_warp",object({{"clip_ids",juce::var(juce::StringArray{before.id})},
                {"enabled",true},{"source_bpm",120.0},{"target_bpm",150.0},{"follow_tempo",false}}))));
            auto warped=mp3.snapshot().tracks[0].clips[0];check(warped.warpEnabled&&std::abs(warped.playbackSourceOffset-.08)<1e-9
                &&std::abs(warped.duration-1.12)<1e-9&&warped.waveformSource.hasFileExtension("wav"),"MP3 decoded source maps to Warp PCM");
            verifyExport(mp3,prefix);
            const auto archive=folder.getChildFile(prefix+".emproj");wait(mp3,mp3.executeRequest(envelope(mp3,"save_project",object({{"path",archive.getFullPathName()}}))));
            EngineSession again(false);wait(again,again.executeRequest(envelope(again,"open_project",object({{"path",archive.getFullPathName()}}))));
            check(again.snapshot().tracks[0].clips[0].warpEnabled&&std::abs(again.snapshot().tracks[0].clips[0].playbackSourceOffset-.08)<1e-9,"MP3 Warp save/reopen map");
            check(juce::SHA256(owned).toHexString()==rawHash,"original MP3 bytes preserved");
        }
        check(mp3Count==2,"CBR stereo and VBR mono MP3 Warp fixtures exercised");
        auto report=object({{"status","passed"},{"checks_passed",checks},{"pitch_measurements",pitchEvidence},{"transient_timing",timingEvidence},
            {"isolated_export_pcm_comparisons",exportEvidence},{"mp3_cases",mp3Count},
            {"scope","generated stereo tones, broadband transients, actual CBR/VBR MP3 and isolated export process; offline exact lengths, pitch, onset latency, async atomic tempo/Warp, offsets, trim/split, Undo/Redo, save/reopen, cancellation/conflict/source integrity; no physical audio or subjective quality claim"}});
        check(directory.getChildFile("warp-report.json").replaceWithText(juce::JSON::toString(report)),"write Warp report");
        return juce::Result::ok();
    }catch(const std::exception& e){return juce::Result::fail(e.what());}
}
