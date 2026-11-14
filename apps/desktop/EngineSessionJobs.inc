// Included in EngineSession.cpp. Workers own DTOs and files, never the live Edit.
namespace {
template<class J> void jobStatus(const J& j,const juce::String& status,const juce::String& error={},double progress=-1)
{std::lock_guard lock(j->mutex);j->status=status;j->error=error;if(progress>=0)j->progress=progress;
 if(status!="queued"&&status!="running")j->phase=status;}
template<class J> void jobProgress(const J& j,double progress)
{std::lock_guard lock(j->mutex);j->progress=juce::jlimit(0.0,1.0,progress);}
template<class J> void jobFailure(const J& j,const juce::Result& r)
{jobStatus(j,j->cancel.load()?"cancelled":"failed",r.getErrorMessage());}
template<class J> storage::IOOptions jobIO(const J& j,double base=0,double scale=1)
{return {[j]{return j->cancel.load();},[j,base,scale](double value,const juce::String& stage){
 std::lock_guard lock(j->mutex);j->progress=juce::jlimit(0.0,1.0,base+scale*value);j->detail=stage;
 j->phase=stage.containsIgnoreCase("manifest")?"writing_manifest":"writing_media";},
 [j](juce::int64 written,juce::int64 reused){std::lock_guard lock(j->mutex);j->bytesWritten=written;j->bytesReused=reused;}};}
template<class J> audio::IOOptions jobAudioIO(const J& j,double base=0,double scale=1)
{return {[j]{return j->cancel.load();},[j,base,scale](double value,const juce::String&){jobProgress(j,base+scale*value);}};}
juce::Result jobPath(const juce::var& args,const char* key,const char* extensions,juce::File& file)
{
    auto path=textArg(args,key);if(path.isEmpty()||!juce::File::isAbsolutePath(path))return juce::Result::fail("An absolute file path is required.");
    file=juce::File(path);if(extensions&&!file.hasFileExtension(extensions))return juce::Result::fail("Unexpected file extension.");
    if(file.isDirectory())return juce::Result::fail("Choose a file, not a directory.");return juce::Result::ok();
}
struct JobFingerprint {bool exists=false;juce::int64 size=0,modified=0;juce::String hash;};
juce::Result fingerprint(const juce::File& file,JobFingerprint& value,const std::function<bool()>& cancelled)
{
    value={};value.exists=file.existsAsFile();if(!value.exists)return file.exists()?juce::Result::fail("The output path is not a regular file."):juce::Result::ok();
    value.size=file.getSize();value.modified=file.getLastModificationTime().toMilliseconds();
    auto input=file.createInputStream();if(!input)return juce::Result::fail("Cannot read the existing output file.");
    struct Stream final:juce::InputStream {
        juce::FileInputStream& source;const std::function<bool()>& cancel;
        Stream(juce::FileInputStream& s,const std::function<bool()>& c):source(s),cancel(c){}
        juce::int64 getTotalLength()override{return source.getTotalLength();}
        juce::int64 getPosition()override{return source.getPosition();}
        bool setPosition(juce::int64 p)override{return source.setPosition(p);}
        bool isExhausted()override{return (cancel&&cancel())||source.isExhausted();}
        int read(void* d,int n)override{return cancel&&cancel()?0:source.read(d,n);}
    } stream(*input,cancelled);
    value.hash=juce::SHA256(stream).toHexString();
    if(cancelled&&cancelled())return juce::Result::fail("Cancelled.");
    if(input->getPosition()!=value.size||file.getSize()!=value.size||file.getLastModificationTime().toMilliseconds()!=value.modified)
        return juce::Result::fail("The output file changed while being checked.");
    return juce::Result::ok();
}
bool sameFingerprint(const JobFingerprint& a,const JobFingerprint& b)
{return a.exists==b.exists&&a.size==b.size&&a.modified==b.modified&&a.hash==b.hash;}
template<class J> juce::Result replaceExport(const J& job,const juce::TemporaryFile& temp,const JobFingerprint& original)
{
    JobFingerprint current;auto r=fingerprint(temp.getTargetFile(),current,[job]{return job->cancel.load();});if(r.failed())return r;
    if(!sameFingerprint(current,original))return juce::Result::fail("The destination changed during export. It was not overwritten.");
    if(job->cancel.load())return juce::Result::fail("Cancelled.");
    return temp.overwriteTargetFileWithTemporary()?juce::Result::ok():juce::Result::fail("Cannot atomically replace the output file.");
}
template<class J> juce::Result prepareJobAssets(const J& j,const storage::StoredProject& state,std::map<juce::String,AudioInfo>& out,double base=0,double scale=1)
{
    for(size_t i=0;i<state.assets.size();++i){const auto& a=state.assets[i];audio::PreparedSource source;
        auto r=audio::prepareSource(a.source,source,jobAudioIO(j,base+scale*double(i)/state.assets.size(),scale/state.assets.size()));
        if(r.failed())return r;out[a.source.getFullPathName()]={source.duration,source.sampleRate,source.channels,source.format,source.playbackFile};
    }
    for(const auto& track:state.tracks)for(const auto& clip:track.clips)if(clip.warp.enabled){
        const auto original=std::find_if(state.assets.begin(),state.assets.end(),[&](const auto& a){return a.id==clip.assetId;});
        const auto rendered=std::find_if(state.assets.begin(),state.assets.end(),[&](const auto& a){return a.id==clip.warp.renderAssetId;});
        if(original==state.assets.end()||rendered==state.assets.end())return juce::Result::fail("Warp media reference is missing.");
        JobFingerprint sourceHash,renderHash;const auto cancel=[j]{return j->cancel.load();};
        if(auto r=fingerprint(original->source,sourceHash,cancel);r.failed())return r;
        if(auto r=fingerprint(out.at(rendered->source.getFullPathName()).playbackFile,renderHash,cancel);r.failed())return r;
        if(sourceHash.hash!=clip.warp.sourceHash||renderHash.hash!=clip.warp.renderHash)return juce::Result::fail("Warp source or rendered audio no longer matches the project.");
    }
    return juce::Result::ok();
}
// MIDI is a musical import, retaining beat positions at the current project BPM.
// Unsupported performance events must be rejected unless notes_only is explicit.
// JUCE intentionally recovers partial tracks. Imports instead require a complete
// SMF envelope so truncated events cannot silently become an incomplete project.
template<class J> juce::Result validateMidiBytes(const J& job,const juce::MemoryBlock& bytes)
{
    const auto* data=static_cast<const unsigned char*>(bytes.getData());const auto size=bytes.getSize();
    auto bad=[] {return juce::Result::fail("Malformed or truncated MIDI event stream.");};
    auto u16=[&](size_t p){return (unsigned(data[p])<<8)|unsigned(data[p+1]);};
    auto u32=[&](size_t p){return (std::uint32_t(data[p])<<24)|(std::uint32_t(data[p+1])<<16)|(std::uint32_t(data[p+2])<<8)|data[p+3];};
    if(size<14||std::memcmp(data,"MThd",4)!=0)return bad();
    const auto header=u32(4),type=u16(8),tracks=u16(10),timing=u16(12);
    if(header<6||size_t(header)>size-8||type>1||tracks==0||tracks>256||(type==0&&tracks!=1)||(timing&0x8000)||timing==0)
        return juce::Result::fail("Only complete SMF 0/1 files with PPQN timing and at most 256 source tracks are supported.");
    size_t position=8+header,totalEvents=0;
    for(unsigned track=0;track<tracks;++track){
        if(size-position<8||std::memcmp(data+position,"MTrk",4)!=0)return bad();
        const auto length=u32(position+4);position+=8;if(length>size-position)return bad();const auto end=position+length;
        unsigned running=0;bool ended=false;
        auto variable=[&](std::uint32_t& value){value=0;for(int i=0;i<4;++i){if(position>=end)return false;auto b=data[position++];value=(value<<7)|(b&127);if((b&128)==0)return true;}return false;};
        while(position<end){
            if(job->cancel.load())return juce::Result::fail("Cancelled.");if(++totalEvents>300000)return juce::Result::fail("MIDI event limit exceeded.");
            std::uint32_t delta=0;if(!variable(delta)||position>=end)return bad();unsigned status=data[position];
            if(status>=128)++position;else if(running)status=running;else return bad();
            if(status>=0x80&&status<0xf0){
                running=status;const size_t count=(status&0xf0)==0xc0||(status&0xf0)==0xd0?1:2;
                if(end-position<count)return bad();for(size_t i=0;i<count;++i)if(data[position+i]>=128)return bad();position+=count;
            }else if(status==0xff){
                running=0;if(position>=end)return bad();auto typeByte=data[position++];std::uint32_t count=0;if(typeByte>=128||!variable(count)||count>end-position)return bad();
                if((typeByte==0x2f&&count!=0)||(typeByte==0x51&&count!=3)||(typeByte==0x58&&count!=4)||(typeByte==0x59&&count!=2)||(typeByte==0x20&&count!=1))return bad();
                if(typeByte==0x58&&data[position]==0)return juce::Result::fail("Invalid MIDI time signature.");
                position+=count;if(typeByte==0x2f){ended=true;if(position!=end)return bad();}
            }else if(status==0xf0||status==0xf7){running=0;std::uint32_t count=0;if(!variable(count)||count>end-position)return bad();position+=count;}
            else return bad();
        }
        if(!ended)return juce::Result::fail("MIDI track is missing its end-of-track event.");
    }
    return position==size?juce::Result::ok():bad();
}
template<class J> juce::Result readJobMidi(const J& j,const juce::File& file,bool notesOnly,storage::StoredProject& state)
{
    if(!file.existsAsFile()||file.getSize()<=0||file.getSize()>16*1024*1024)return juce::Result::fail("MIDI must be a nonempty file no larger than 16 MiB.");
    auto input=file.createInputStream();juce::MemoryBlock bytes;juce::MidiFile midi;int type=-1;
    if(!input||input->readIntoMemoryBlock(bytes,16*1024*1024+1)!=file.getSize()||bytes.getSize()>16*1024*1024)return juce::Result::fail("Cannot read the complete MIDI file.");
    if(auto r=validateMidiBytes(j,bytes);r.failed())return r;juce::MemoryInputStream memory(bytes,false);
    if(!midi.readFrom(memory,false,&type))return juce::Result::fail("Invalid or truncated MIDI file.");
    const int ppqn=midi.getTimeFormat();
    if(type<0||type>1||ppqn<=0)return juce::Result::fail("Only SMF 0/1 with PPQN timing is supported; SMPTE and SMF 2 are not supported.");
    size_t totalEvents=0,totalNotes=0;for(const auto& t:state.tracks)for(const auto& c:t.clips)totalNotes+=c.notes.size();
    const bool initiallyEmpty=state.tracks.empty();double tempo=-1;int numerator=0,denominator=0;bool sawNotes=false;
    for(int ti=0;ti<midi.getNumTracks();++ti){
        const auto* sequence=midi.getTrack(ti);if(!sequence)continue;
        totalEvents+=size_t(sequence->getNumEvents());if(totalEvents>300000)return juce::Result::fail("MIDI event limit exceeded.");
        std::map<int,std::vector<storage::StoredNote>> channels;
        std::map<int,std::vector<juce::MidiMessage>> held;juce::String name=file.getFileNameWithoutExtension();
        for(int ei=0;ei<sequence->getNumEvents();++ei){
            if(j->cancel.load())return juce::Result::fail("Cancelled.");
            const auto& m=sequence->getEventPointer(ei)->message;double beat=m.getTimeStamp()/ppqn;
            if(!std::isfinite(beat)||beat<0||time::beatsToSeconds(beat,storage::maximumBpm)>storage::maximumTimelineSeconds)return juce::Result::fail("MIDI event time exceeds the project limit.");
            if(m.isNoteOn()){
                auto& pending=held[m.getChannel()*128+m.getNoteNumber()];
                if(pending.size()>=256)return juce::Result::fail("Too many overlapping MIDI notes on one pitch/channel.");pending.push_back(m);
            }
            else if(m.isNoteOff()){
                auto& starts=held[m.getChannel()*128+m.getNoteNumber()];
                if(starts.empty())return juce::Result::fail("MIDI contains an unmatched note-off.");
                auto start=starts.front();starts.erase(starts.begin());double begin=start.getTimeStamp()/ppqn;
                if(beat<=begin)return juce::Result::fail("MIDI contains a zero or negative note length.");
                if(++totalNotes>storage::maximumNotes)return juce::Result::fail("MIDI note limit exceeded.");
                channels[m.getChannel()].push_back({uid(),m.getNoteNumber(),begin,beat-begin,int(start.getVelocity()),m.getChannel()});sawNotes=true;
            }else if(m.isTempoMetaEvent()){
                auto value=m.getTempoSecondsPerQuarterNote();if(!std::isfinite(value)||value<=0)return juce::Result::fail("Invalid MIDI tempo.");
                if(!notesOnly&&((tempo>=0&&std::abs(value-tempo)>1e-9)||m.getTimeStamp()>0))return juce::Result::fail("Tempo maps are not supported. Use notes_only to import beat positions at the project tempo.");tempo=value;
            }else if(m.isTimeSignatureMetaEvent()){
                if(notesOnly)continue;
                if(m.getMetaEventData()[1]>5)return juce::Result::fail("MIDI time signature exceeds the supported range. Use notes_only to ignore it.");
                int n=0,d=0;m.getTimeSignatureInfo(n,d);
                if(!notesOnly&&((numerator>0&&(n!=numerator||d!=denominator))||m.getTimeStamp()>0))return juce::Result::fail("Time-signature maps are not supported. Use notes_only to import only notes.");numerator=n;denominator=d;
            }else if(m.isTrackNameEvent())name=m.getTextFromTextMetaEvent().substring(0,180);
            else if(m.isEndOfTrackMetaEvent()||m.isTextMetaEvent()){}
            else if(!notesOnly)return juce::Result::fail("MIDI contains controllers, program changes, expression or unsupported metadata. Use notes_only explicitly to import only notes.");
        }
        for(const auto& [key,starts]:held)if(!starts.empty())return juce::Result::fail("MIDI contains an unterminated note.");
        for(auto& [channel,notes]:channels){
            if(state.tracks.size()>=storage::maximumTracks)return juce::Result::fail("Import would exceed 64 tracks.");
            storage::StoredTrack track;track.id=uid();track.kind="instrument";track.name=name+" / ch "+juce::String(channel);
            storage::StoredClip clip;clip.id=uid();clip.kind="midi";clip.notes=std::move(notes);double end=0;
            for(const auto& n:clip.notes)end=juce::jmax(end,n.startBeats+n.lengthBeats);
            clip.lengthBeats=end;clip.duration=time::beatsToSeconds(clip.lengthBeats,state.bpm);track.clips.push_back(std::move(clip));state.tracks.push_back(std::move(track));
        }jobProgress(j,double(ti+1)/juce::jmax(1,midi.getNumTracks()));
    }
    if(!sawNotes)return juce::Result::fail("The MIDI file contains no notes.");
    if(!notesOnly){
        if(tempo>0){const auto bpm=60.0/tempo;if(bpm<storage::minimumBpm||bpm>storage::maximumBpm)return juce::Result::fail("MIDI tempo is outside 20 to 300 BPM. Use notes_only to keep the project tempo.");
            if(initiallyEmpty)state.bpm=bpm;else if(std::abs(state.bpm-bpm)>0.001)return juce::Result::fail("MIDI tempo differs from this project. Use notes_only to import at the current project tempo.");}
        if(numerator>0){if(initiallyEmpty){state.numerator=numerator;state.denominator=denominator;}else if(state.numerator!=numerator||state.denominator!=denominator)return juce::Result::fail("MIDI time signature differs from this project. Use notes_only to keep the project meter.");}
    }
    syncMidiSeconds(state);return storage::validate(state);
}
// JUCE 8's writer converts absolute event timestamps to signed int. The
// 1/16384 whole-note grid needs 4096 PPQN, whose 48-hour range exceeds int.
// Keep absolute ticks wide and split only long SMF deltas with inert text events.
inline constexpr int midiExportPpqn = 4096;
template<class J> juce::Result writeMidiWideTicks(const J& job, juce::OutputStream& output, const juce::MidiFile& midi)
{
    constexpr std::uint64_t maximumDelta = 0x0fffffff;
    const auto maximumTick = static_cast<std::uint64_t>(storage::maximumTimelineSeconds * storage::maximumBpm / 60.0 * midiExportPpqn);
    const auto variable = [](juce::OutputStream& stream, std::uint32_t value) {
        unsigned char bytes[4]; int count = 0;
        bytes[count++] = static_cast<unsigned char>(value & 127);
        while ((value >>= 7) != 0) bytes[count++] = static_cast<unsigned char>((value & 127) | 128);
        while (count > 0) if (!stream.writeByte(static_cast<char>(bytes[--count]))) return false;
        return true;
    };
    if (!output.writeIntBigEndian(0x4d546864) || !output.writeIntBigEndian(6)
        || !output.writeShortBigEndian(1) || !output.writeShortBigEndian(static_cast<short>(midi.getNumTracks()))
        || !output.writeShortBigEndian(midiExportPpqn)) return juce::Result::fail("Could not write MIDI header.");
    for (int track = 0; track < midi.getNumTracks(); ++track) {
        juce::MemoryOutputStream bytes; std::uint64_t previous = 0;
        const auto* sequence = midi.getTrack(track);
        for (int index = 0; index < sequence->getNumEvents(); ++index) {
            if (job->cancel.load()) return juce::Result::fail("Cancelled.");
            const auto& message = sequence->getEventPointer(index)->message;
            const double time = message.getTimeStamp();
            if (!std::isfinite(time) || time < 0 || time > double(maximumTick))
                return juce::Result::fail("A MIDI event exceeds the supported timeline.");
            const auto tick = static_cast<std::uint64_t>(std::llround(time));
            if (tick < previous) return juce::Result::fail("MIDI events are not ordered.");
            while (tick - previous > maximumDelta) {
                if (!variable(bytes, static_cast<std::uint32_t>(maximumDelta))
                    || !bytes.writeByte(static_cast<char>(0xff)) || !bytes.writeByte(1) || !bytes.writeByte(0))
                    return juce::Result::fail("Could not write MIDI gap.");
                previous += maximumDelta;
            }
            if (!variable(bytes, static_cast<std::uint32_t>(tick - previous))
                || !bytes.write(message.getRawData(), static_cast<size_t>(message.getRawDataSize())))
                return juce::Result::fail("Could not write MIDI event.");
            previous = tick;
        }
        const unsigned char end[] = { 0, 0xff, 0x2f, 0 };
        if (!bytes.write(end, sizeof(end)) || bytes.getDataSize() > static_cast<size_t>(std::numeric_limits<int>::max())
            || !output.writeIntBigEndian(0x4d54726b) || !output.writeIntBigEndian(static_cast<int>(bytes.getDataSize()))
            || !output.write(bytes.getData(), bytes.getDataSize())) return juce::Result::fail("Could not write MIDI track.");
    }
    return juce::Result::ok();
}

template<class J> juce::Result writeJobMidi(const J& j,const juce::File& file,const storage::StoredProject& state,const std::vector<juce::String>& selected)
{
    if(!std::isfinite(state.bpm)||state.bpm<storage::minimumBpm||state.bpm>storage::maximumBpm)return juce::Result::fail("MIDI tempo is outside the supported range.");
    constexpr int ppqn=midiExportPpqn;const double maximumTicks=storage::maximumTimelineSeconds*state.bpm/60.0*ppqn;
    const auto lastTick=static_cast<std::int64_t>(std::floor(maximumTicks));juce::MidiFile midi;midi.setTicksPerQuarterNote(ppqn);
    juce::MidiMessageSequence meta;auto tempo=juce::MidiMessage::tempoMetaEvent(int(std::llround(60000000.0/state.bpm)));meta.addEvent(tempo);
    meta.addEvent(juce::MidiMessage::timeSignatureMetaEvent(state.numerator,state.denominator));midi.addTrack(meta);
    std::set<juce::String> ids(selected.begin(),selected.end());double origin=0;
    if(!ids.empty()){
        origin=std::numeric_limits<double>::infinity();for(const auto& t:state.tracks)for(const auto& c:t.clips)if(ids.contains(c.id)&&c.kind=="midi")origin=juce::jmin(origin,c.startBeats);
        if(!std::isfinite(origin))return juce::Result::fail("No MIDI clips selected.");
        for(const auto& id:ids){bool found=false;for(const auto& t:state.tracks)for(const auto& c:t.clips)if(c.id==id&&c.kind=="midi")found=true;if(!found)return juce::Result::fail("A selected MIDI clip no longer exists.");}
    }
    bool hasNotes=false;
    for(size_t ti=0;ti<state.tracks.size();++ti){const auto& track=state.tracks[ti];std::vector<juce::MidiMessage> events;
        for(const auto& c:track.clips)if(c.kind=="midi"&&(ids.empty()||ids.contains(c.id))){
          for(const auto& n:c.notes){
            if(j->cancel.load())return juce::Result::fail("Cancelled.");
            if(!std::isfinite(n.startBeats)||!std::isfinite(n.lengthBeats)||n.startBeats<0||n.lengthBeats<=0)
                return juce::Result::fail("A note cannot be represented safely at 4096 PPQN.");
            const auto beginTicks=(c.startBeats+n.startBeats-origin)*ppqn, endTicks=(c.startBeats+n.startBeats+n.lengthBeats-origin)*ppqn;
            if(!std::isfinite(beginTicks)||!std::isfinite(endTicks)||beginTicks<0||endTicks<beginTicks
                ||beginTicks>=maximumTicks||endTicks>maximumTicks)
                return juce::Result::fail("A note cannot be represented safely at 4096 PPQN.");
            auto begin=std::llround(beginTicks), end=std::llround(endTicks);
            if(end<begin)return juce::Result::fail("A note cannot be represented safely at 4096 PPQN.");
            // Positive sub-tick notes survive as one tick. At the project horizon,
            // move that tick inward rather than creating an unimportable note-off.
            begin=std::min(begin,static_cast<long long>(lastTick-1));
            end=std::min(std::max(end,begin+1),static_cast<long long>(lastTick));
            auto on=juce::MidiMessage::noteOn(n.channel,n.pitch,juce::uint8(n.velocity));on.setTimeStamp(double(begin));events.push_back(on);
            auto off=juce::MidiMessage::noteOff(n.channel,n.pitch);off.setTimeStamp(double(end));events.push_back(off);hasNotes=true;
          }
          for(const auto& e:c.controllers){
            if(j->cancel.load())return juce::Result::fail("Cancelled.");
            const double rawTick=(c.startBeats+e.beats-origin)*ppqn;
            if(!std::isfinite(rawTick)||rawTick<0||rawTick>maximumTicks)return juce::Result::fail("A controller cannot be represented safely at 4096 PPQN.");
            const auto tick=std::min(std::llround(rawTick),static_cast<long long>(lastTick));
            const int channel=c.midiChannel>0?c.midiChannel:c.notes.empty()?1:c.notes.front().channel;juce::MidiMessage message;
            if(e.type>=0&&e.type<=127)message=juce::MidiMessage::controllerEvent(channel,e.type,e.value>>7);
            else if(e.type==0x1001)message=juce::MidiMessage::programChange(channel,e.value>>7);
            else if(e.type==0x1004)message=juce::MidiMessage::aftertouchChange(channel,e.metadata,e.value>>7);
            else if(e.type==0x1005)message=juce::MidiMessage::pitchWheel(channel,e.value);
            else if(e.type==0x1007)message=juce::MidiMessage::channelPressureChange(channel,e.value>>7);
            else return juce::Result::fail("Unsupported MIDI controller type.");
            message.setTimeStamp(double(tick));events.push_back(message);hasNotes=true;
          }
        }
        if(!events.empty()){
            std::stable_sort(events.begin(),events.end(),[](const auto& a,const auto& b){return a.getTimeStamp()!=b.getTimeStamp()?a.getTimeStamp()<b.getTimeStamp():a.isNoteOff()&&!b.isNoteOff();});
            juce::MidiMessageSequence sequence;sequence.addEvent(juce::MidiMessage::textMetaEvent(3,track.name));
            for(const auto& event:events)sequence.addEvent(event);midi.addTrack(sequence);
        }jobProgress(j,0.8*double(ti+1)/juce::jmax(size_t(1),state.tracks.size()));
    }
    if(!hasNotes)return juce::Result::fail("There are no MIDI notes to export.");
    JobFingerprint original;if(auto r=fingerprint(file,original,[j]{return j->cancel.load();});r.failed())return r;
    if(!file.getParentDirectory().isDirectory())return juce::Result::fail("The output directory does not exist.");
    juce::TemporaryFile temp(file);auto output=temp.getFile().createOutputStream();if(!output)return juce::Result::fail("Cannot create MIDI output.");
    if(auto r=writeMidiWideTicks(j,*output,midi);r.failed())return r;output->flush();auto error=output->getStatus();output.reset();if(error.failed())return error;
    return replaceExport(j,temp,original);
}
juce::File renderJobsRoot()
{return juce::File::getSpecialLocation(juce::File::userApplicationDataDirectory).getChildFile("E-musician/render-jobs");}
// Only this task's UUID directory is removed; user project directories are never cleaned here.
struct OwnedRenderDirectory {
    juce::File root=renderJobsRoot(),directory;
    explicit OwnedRenderDirectory(const juce::String& id):directory(root.getChildFile(id)){}
    ~OwnedRenderDirectory(){if(directory.isAChildOf(root)&&directory.getParentDirectory()==root&&!directory.isSymbolicLink())directory.deleteRecursively();}
};
struct OwnedRenderProcess {
    juce::ChildProcess child;
    ~OwnedRenderProcess(){if(child.isRunning()){child.kill();child.waitForProcessToFinish(2000);}}
};
bool writeRenderReport(const juce::File& file,const juce::String& state,double progress,const juce::String& error={})
{
    juce::TemporaryFile temporary(file);return temporary.getFile().replaceWithText(juce::JSON::toString(object({{"status",state},{"progress",progress},{"error",error}})))&&temporary.overwriteTargetFileWithTemporary();
}
void trimRenderInputs(storage::StoredProject& state,double end)
{
    for(auto& track:state.tracks){
        std::erase_if(track.clips,[&](const auto& c){return c.timelineStart>=end;});
        for(auto& c:track.clips)if(c.timelineStart+c.duration>end){
            c.duration=end-c.timelineStart;c.fadeIn=juce::jmin(c.fadeIn,c.duration);c.fadeOut=0;
            if(c.kind=="midi"){
                c.lengthBeats=c.duration*state.bpm/60.0;std::erase_if(c.notes,[&](const auto& n){return n.startBeats>=c.lengthBeats;});
                for(auto& n:c.notes)n.lengthBeats=juce::jmin(n.lengthBeats,c.lengthBeats-n.startBeats);
            }
        }
    }state.looping=false;state.loopStart=0;state.loopEnd=0;pruneAssets(state);
}
template<class J> juce::Result renderJob(const J& j,const juce::File& target,storage::StoredProject state,double start,double end,double rate,int bits,double tail,bool realtime,std::map<juce::String,juce::String> expectedHashes)
{
    if(!target.getParentDirectory().isDirectory())return juce::Result::fail("The output directory does not exist.");
    JobFingerprint original;if(auto r=fingerprint(target,original,[j]{return j->cancel.load();});r.failed())return r;
    OwnedRenderDirectory owned(j->id);if(auto r=owned.directory.createDirectory();r.failed())return r;
    const auto manifest=owned.directory.getChildFile("snapshot.emproj"),specFile=owned.directory.getChildFile("spec.json"),report=owned.directory.getChildFile("report.json");
    trimRenderInputs(state,end);storage::StoredProject archived;
    auto options=jobIO(j,0,0.2);options.expectedAssetHashes=std::move(expectedHashes);
    if(auto r=storage::save(manifest,state,archived,options);r.failed())return r;
    auto staging=target.getSiblingFile(".emusician-render-"+j->id+".wav");
    if(staging.exists())return juce::Result::fail("The render staging path already exists.");juce::TemporaryFile output(target,staging);
    auto spec=object({{"id",j->id},{"snapshot",manifest.getFullPathName()},{"output",staging.getFullPathName()},{"start",start},{"end",end},{"sample_rate",rate},{"bit_depth",bits},{"tail",tail},{"realtime",realtime}});
    if(!specFile.replaceWithText(juce::JSON::toString(spec)))return juce::Result::fail("Cannot create render job specification.");
    if(j->cancel.load())return juce::Result::fail("Cancelled.");
    OwnedRenderProcess process;auto& child=process.child;juce::StringArray command{juce::File::getSpecialLocation(juce::File::currentExecutableFile).getFullPathName(),"--render-worker",specFile.getFullPathName(),report.getFullPathName()};
    if(!child.start(command,0))return juce::Result::fail("Could not start the isolated render worker.");
    const auto began=juce::Time::getMillisecondCounterHiRes();const double timeout=juce::jmax(120000.0,(end-start+tail)*4000.0+60000.0);
    while(child.isRunning()){
        if(j->cancel.load()||juce::Time::getMillisecondCounterHiRes()-began>timeout){child.kill();child.waitForProcessToFinish(2000);return juce::Result::fail(j->cancel.load()?"Cancelled.":"Render worker timed out; the destination was not changed.");}
        if(report.existsAsFile()&&report.getSize()<65536){auto value=juce::JSON::parse(report);auto fraction=number(value,"progress",0);if(std::isfinite(fraction))jobProgress(j,0.2+0.79*juce::jlimit(0.0,1.0,fraction));}
        juce::Thread::sleep(50);
    }
    child.waitForProcessToFinish(1000);auto result=report.existsAsFile()&&report.getSize()<65536?juce::JSON::parse(report):juce::var();
    if(child.getExitCode()!=0||textArg(result,"status")!="completed")return juce::Result::fail(textArg(result,"error").isNotEmpty()?textArg(result,"error"):"Render worker exited without completing. The destination was not changed.");
    if(!staging.existsAsFile()||staging.getSize()<44)return juce::Result::fail("Render worker produced no valid WAV.");return replaceExport(j,output,original);
}
} // namespace

std::shared_ptr<EngineSession::Impl::Job> EngineSession::Impl::startJob(const juce::String& kind,std::function<void(const std::shared_ptr<Job>&)> work)
{
    requireControlThread();if(hasBlockingFileTask()){fail("A file task is running or awaiting its commit. Wait for it or cancel it first.");return {};}
    while(jobs.size()>=64){
        const auto retired=std::find_if(jobs.begin(),jobs.end(),[](const auto& j){return !j->worker.joinable();});
        if(retired==jobs.end()){fail("Task history is busy. Wait for a task to finish.");return {};}
        jobs.erase(retired);
    }
    auto job=std::make_shared<Job>();job->kind=kind;job->projectId=guard.projectId();job->revision=guard.revision();jobs.push_back(job);
    publish("job_changed",object({{"job_id",job->id},{"status","queued"},{"kind",kind}}));status=kind.replaceCharacter('_',' ')+" queued.";
    try{
        job->worker=std::thread([job,work=std::move(work)]()mutable{
            jobStatus(job,"running",{},0);
            try{if(job->cancel.load())jobStatus(job,"cancelled");else work(job);}
            catch(const std::exception& e){jobStatus(job,"failed",e.what());}catch(...){jobStatus(job,"failed","Unexpected file task failure.");}
            // Release worker-owned buffers/process handles before advertising
            // completion; the UI must not join while their destructors wait.
            work={};job->done.store(true,std::memory_order_release);
        });
    }catch(const std::exception& e){
        jobStatus(job,"failed","Cannot create background worker: "+juce::String(e.what()));job->done=true;
        fail(job->error);return {};
    }return job;
}

void EngineSession::Impl::timerCallback()
{
    if(shuttingDown||controlOperationActive)return;
    const juce::ScopedValueSetter<bool> busy(controlOperationActive,true);
    auto completions=std::move(deferredNativeCompletions);
    deferredNativeCompletions.clear();
    for(auto& completion:completions)completeNative(std::move(completion));
    finishRecording();
    auto changed=pluginHost.takeChangedPluginIds();juce::Array<juce::var> ids;
    for(const auto& id:changed)if(livePlugin(*edit,id))ids.add(id);
    if(!ids.isEmpty()){
        pluginDirty=true;advanceRevision();cachedRevision=std::numeric_limits<std::uint64_t>::max();
        publish("plugin_changed",object({{"plugin_ids",ids}}));
    }
    auto& transport=edit->getTransport();if(transport.isPlaying()&&!transport.isRecording()&&!transport.isRecordingStopping()&&!transport.looping.get()&&!(edit->clickTrackEnabled.get()&&!edit->clickTrackRecordingOnly.get())&&transport.getPosition().inSeconds()>=duration){transport.stop(false,false);transport.setPosition(te::TimePosition::fromSeconds(duration));}
    for(auto& job:jobs)if(job->preparation&&!job->done.load(std::memory_order_acquire)){
        auto step=job->preparation;step(); // Keep the callable alive if it clears itself.
    }
    reapFinishedJobs(true);
    reconcileNative();
}

void EngineSession::Impl::reapFinishedJobs(bool applyCommits)
{
    requireControlThread();
    for(auto& job:jobs)if(job->done.load(std::memory_order_acquire)&&job->worker.joinable()){
        if(!applyCommits){
            // Request admission must not apply an earlier import/open/save
            // after its expected revision has already been checked. Only
            // retire terminal workers with no outstanding model commit here.
            std::lock_guard lock(job->mutex);
            if(job->commit||job->status=="running"||job->status=="queued")continue;
        }
        job->preparation={};
        // done is published after work returns; never join an active task.
        // The thread may still be destroying its work callable before exit.
        job->worker.join();std::function<void()> commit;juce::String state;
        {std::lock_guard lock(job->mutex);state=job->status;commit=std::move(job->commit);}
        const bool writesProject=job->kind=="import_audio"||job->kind=="import_midi"||job->kind=="open_project"||job->kind=="set_audio_warp";
        if(commit){
            if(writesProject&&(job->projectId!=juce::String(guard.projectId())||job->revision!=guard.revision()))jobStatus(job,"conflict","The project changed while this task was running. Its result was not applied.");
            else if(writesProject&&job->cancel.load())jobStatus(job,"cancelled");
            else try{commit();}catch(const std::exception& e){jobStatus(job,"failed",e.what());}
        }else if(state=="running"||state=="queued")jobStatus(job,job->cancel.load()?"cancelled":"completed",{},1);
        {std::lock_guard lock(job->mutex);status=job->error.isNotEmpty()?job->error:job->kind.replaceCharacter('_',' ')+" "+job->status+".";
            publish("job_changed",object({{"job_id",job->id},{"kind",job->kind},{"status",job->status},{"progress",job->progress},{"error",job->error}}));}
    }
}

juce::Result EngineSession::Impl::beginSave(const juce::File& file)
{
    finishGesture();
    // Include notifications which already preceded the Save click. Subsequent
    // genuine changes remain a separate generation and cannot be cleared by it.
    auto changed=pluginHost.takeChangedPluginIds();
    if(std::any_of(changed.begin(),changed.end(),[&](const auto& id){return livePlugin(*edit,id)!=nullptr;})){
        pluginDirty=true;advanceRevision();cachedRevision=std::numeric_limits<std::uint64_t>::max();publish("plugin_changed");
    }
    struct Capture {
        struct Slot {juce::String track,id;std::uint64_t generation=0;const te::Plugin* instance=nullptr;};
        storage::StoredProject state;std::vector<Slot> slots;size_t next=0;
        std::map<juce::String,juce::String> expectedHashes;
        juce::String failure,failureStatus="failed";
    };
    auto captured=std::make_shared<Capture>();
    const auto began=juce::Time::getMillisecondCounterHiRes();captured->state=capture();
    if(auto r=nativeAssetHashes(captured->state,captured->expectedHashes);r.failed())return fail(r.getErrorMessage());
    auto add=[&](auto& list,const juce::String& track,juce::ValueTree owner){for(auto& p:list){
        auto* live=loadedPlugin(*edit,p.id);
        if(!live)p.state=readSlot(owner.getChildWithName("EM_PLUGINS").getChildWithProperty("id",p.id)).state;
        captured->slots.push_back({track,p.id,pluginHost.changeGeneration(p.id),live});}};
    add(captured->state.masterPlugins,"master",metadata(*edit));for(auto& track:captured->state.tracks)add(track.plugins,track.id,find(track.id)->track->state);
    auto job=startJob("save_project",[this,file,captured](const auto& job){
        {
            std::unique_lock lock(job->mutex);
            while(!job->prepared.load(std::memory_order_acquire)&&!job->cancel.load())
                job->preparationReady.wait_for(lock,std::chrono::milliseconds(20));
        }
        if(job->cancel.load()){jobStatus(job,"cancelled",{},0);return;}
        if(captured->failure.isNotEmpty()){jobStatus(job,captured->failureStatus,captured->failure);return;}
        storage::StoredProject archived;
        auto options=jobIO(job,0.1,0.9);options.expectedAssetHashes=captured->expectedHashes;
        if(auto result=storage::save(file,captured->state,archived,options);result.failed()){jobFailure(job,result);return;}
        const auto key=contentKey(captured->state); // Hash/serialization are not message-thread work.
        std::lock_guard lock(job->mutex);job->phase="committing";job->detail="Confirming saved project";
        job->commit=[this,job,file,captured,key,archived=std::move(archived)]{
            if(job->projectId==juce::String(guard.projectId())){
                projectFile=file;savedKey=key;
                bool same=job->revision==guard.revision();
                for(const auto& slot:captured->slots)
                    same &= loadedPlugin(*edit,slot.id)==slot.instance&&pluginHost.changeGeneration(slot.id)==slot.generation;
                if(same)pluginDirty=false;
                // The archive becomes the canonical media reference without
                // replacing playback clips/graphs. Prepared PCM stays valid.
                for(const auto& original:captured->state.assets){
                    auto next=std::find_if(archived.assets.begin(),archived.assets.end(),[&](const auto& a){return a.id==original.id;});
                    if(next==archived.assets.end())continue;
                    // Save preserves asset identity/content while rebinding its
                    // canonical path. Keep in-flight/ready candidates valid;
                    // never mutate the immutable paths read by their workers.
                    for(auto& [id,analysis]:analyses)
                        if(analysis->source["project_id"].toString()==job->projectId
                           &&analysis->source["asset_id"].toString()==original.id
                           &&analysis->boundOriginal==original.source)
                            analysis->boundOriginal=next->source;
                    for(auto& track:bindings)for(auto& clip:track.clips)
                        if(clip.assetId==original.id&&clip.source==original.source){
                            clip.source=next->source;clip.clip->state.setProperty(emSource,next->source.getFullPathName(),nullptr);
                            prepared[next->source.getFullPathName()]=clip.originalInfo;
                        }
                    for(auto& track:bindings)for(auto& clip:track.clips){
                        const auto warp=clip.clip->state["emAudioWarp"];
                        if(bool(warp["enabled"])&&warp["render_asset_id"].toString()==original.id
                           &&clip.clip->state["emWarpRenderSource"].toString()==original.source.getFullPathName()){
                            clip.clip->state.setProperty("emWarpRenderSource",next->source.getFullPathName(),nullptr);
                            prepared[next->source.getFullPathName()]=clip.info;
                        }
                    }
                    auto assets=metadata(*edit).getChildWithName("EM_NATIVE_ASSETS");
                    if(auto item=assets.getChildWithProperty("id",original.id);item.isValid()
                       &&item["source"].toString()==original.source.getFullPathName())
                        item.setProperty("source",next->source.getFullPathName(),nullptr);
                }
                nativeLastScan=std::numeric_limits<std::uint64_t>::max();
                cachedRevision=std::numeric_limits<std::uint64_t>::max();
            }
            jobStatus(job,"completed",{},1);
        };
    });
    if(!job)return juce::Result::fail(status);
    {std::lock_guard lock(job->mutex);job->phase="capturing_plugins";job->detail="Preparing project snapshot";
        job->captureMs=juce::Time::getMillisecondCounterHiRes()-began;}
    const std::weak_ptr<Job> weakJob=job;
    job->preparation=[this,weakJob,captured]{
        auto job=weakJob.lock();if(!job)return;
        const auto finish=[&]{job->preparation={};job->prepared.store(true,std::memory_order_release);job->preparationReady.notify_one();};
        const auto reject=[&](const juce::String& message,const juce::String& state="conflict"){
            captured->failure=message;captured->failureStatus=state;finish();};
        if(job->cancel.load()){finish();return;}
        if(job->projectId!=juce::String(guard.projectId())){reject("The active project changed while preparing the save.");return;}
        if(captured->next<captured->slots.size()){
            const auto& target=captured->slots[captured->next];auto* live=loadedPlugin(*edit,target.id);
            if(live!=target.instance||pluginHost.changeGeneration(target.id)!=target.generation){reject("A plugin changed while preparing the save. Save again to capture the latest state.");return;}
            auto* list=&captured->state.masterPlugins;
            juce::ValueTree owner=metadata(*edit);
            if(target.track!="master"){
                auto* binding=find(target.track);if(!binding){reject("A plugin track was removed while preparing the save.");return;}
                owner=binding->track->state;
                auto track=std::find_if(captured->state.tracks.begin(),captured->state.tracks.end(),[&](const auto& t){return t.id==target.track;});
                list=&track->plugins;
            }
            auto slot=std::find_if(list->begin(),list->end(),[&](const auto& p){return p.id==target.id;});
            const auto started=juce::Time::getMillisecondCounterHiRes();
            {std::lock_guard lock(job->mutex);job->detail="Capturing plugin: "+slot->name;}
            try{
                if(live){auto value=*slot;auto result=plugins::PluginHost::capture(*live,value,true);
                    if(result.failed()){reject(result.getErrorMessage(),"failed");return;}slot->state=std::move(value.state);
                }else {auto cached=owner.getChildWithName("EM_PLUGINS").getChildWithProperty("id",target.id);
                    if(!cached.isValid()){reject("A missing plugin slot was removed while preparing the save.");return;}
                    // capture() already owns its original opaque state. Never
                    // substitute a newer missing-plugin state into that snapshot.
                }
            }catch(const std::exception& e){reject(e.what(),"failed");return;}catch(...){reject("Plugin state capture failed.","failed");return;}
            const auto elapsed=juce::Time::getMillisecondCounterHiRes()-started;
            {std::lock_guard lock(job->mutex);job->captureMs+=elapsed;job->maxPluginCaptureMs=juce::jmax(job->maxPluginCaptureMs,elapsed);
                ++job->pluginsCaptured;job->progress=0.1*double(++captured->next)/double(captured->slots.size());}
        }
        if(captured->next==captured->slots.size()){
            for(const auto& target:captured->slots)
                if(loadedPlugin(*edit,target.id)!=target.instance||pluginHost.changeGeneration(target.id)!=target.generation){reject("A plugin changed while preparing the save. Save again to capture the latest state.");return;}
            finish();
        }
    };
    // With no native plugins there is no message-thread preparation to defer.
    if(captured->slots.empty()){auto step=job->preparation;step();}
    return juce::Result::ok();
}

juce::Result EngineSession::Impl::performJob(const juce::String& command,const juce::var& args)
{
    if(!args.isObject())return fail("Command arguments must be an object.");
    if(command=="cancel_job"){
        const auto id=textArg(args,"job_id");if(id=="plugin-scan"){pluginHost.cancelScan();return juce::Result::ok();}
        if(nativePending&&id=="native-"+juce::String(juce::int64(nativePending->token)))
            return fail("The current sample decode cannot yet be cancelled; wait for it to finish.");
        for(auto& j:jobs)if(j->id==id){j->cancel=true;return juce::Result::ok();}return fail("Task not found.");
    }
    if(command=="scan_plugins"){
        auto includeDefault=args.getProperty("include_default_paths",true);if(!includeDefault.isBool())return fail("include_default_paths must be boolean.");
        auto paths=bool(includeDefault)?plugins::PluginHost::defaultSearchPaths():juce::FileSearchPath();auto value=args.getProperty("paths",{});
        if(!value.isVoid()){auto* list=value.getArray();if(!list||list->size()>64)return fail("Plugin paths must be an array with at most 64 directories.");
            for(const auto& p:*list){if(!p.isString()||!juce::File::isAbsolutePath(p.toString()))return fail("Plugin paths must be absolute directories.");juce::File path(p.toString());if(!path.isDirectory())return fail("Plugin directory does not exist.");paths.add(path);}}
        juce::Array<juce::File> modules;auto moduleValue=args.getProperty("modules",{});
        if(!moduleValue.isVoid()){auto* list=moduleValue.getArray();if(!list||list->size()>64)return fail("modules must contain at most 64 absolute VST2/VST3 module paths.");
            for(const auto& module:*list){if(!module.isString()||!juce::File::isAbsolutePath(module.toString()))return fail("Module paths must be absolute.");modules.addIfNotAlreadyThere(juce::File(module.toString()));}}
        return pluginHost.scanAsync(paths,modules);
    }
    // A worker can publish failure between timer ticks. Permit immediate retry
    // without running the timer's recording/plugin/transport side effects.
    reapFinishedJobs(false);
    if(hasBlockingFileTask())return fail("A file task is running or awaiting its commit. Wait for it or cancel it first.");
    if(command=="import_audio"){
        auto value=args.getProperty("paths",{});auto* paths=value.getArray();auto state=capture();
        if(!paths||paths->isEmpty()||state.tracks.size()+size_t(paths->size())>storage::maximumTracks)return fail("Choose audio files within the 64-track limit.");
        juce::Array<juce::File> files;for(const auto& path:*paths){if(!path.isString()||!juce::File::isAbsolutePath(path.toString()))return fail("Audio paths must be absolute.");juce::File f(path.toString());if(!f.hasFileExtension("wav;mp3"))return fail("Only WAV and MP3 audio is supported.");files.add(f);}
        auto j=startJob(command,[this,state=std::move(state),files](const auto& job)mutable{
            std::map<juce::String,AudioInfo> preparedSources;
            for(int i=0;i<files.size();++i){audio::PreparedSource source;if(auto r=audio::prepareSource(files[i],source,jobAudioIO(job,double(i)/files.size(),1.0/files.size()));r.failed()){jobFailure(job,r);return;}
                preparedSources[files[i].getFullPathName()]={source.duration,source.sampleRate,source.channels,source.format,source.playbackFile};
                storage::StoredAsset asset{uid(),files[i]};storage::StoredTrack track;track.id=uid();track.name=files[i].getFileNameWithoutExtension();track.clips.push_back({uid(),asset.id,0,0,source.duration});state.assets.push_back(asset);state.tracks.push_back(std::move(track));}
            if(auto r=storage::validate(state);r.failed()){jobFailure(job,r);return;}
            std::lock_guard lock(job->mutex);job->commit=[this,job,state=std::move(state),preparedSources=std::move(preparedSources)]()mutable{
                for(const auto& [path,info]:preparedSources)prepared[path]=info;finishGesture();remember("Import audio");
                if(auto r=applyTo(*edit,state,bindings,false);r.failed()){edit->getUndoManager().undoCurrentTransactionOnly();rebuild(*edit,bindings);refreshRange();jobFailure(job,r);return;}
                refreshRange();refreshPluginWatches();choose(state.tracks.back().id);recordEdit();jobStatus(job,"completed",{},1);
            };
        });return j?juce::Result::ok():juce::Result::fail(status);
    }
    juce::File file;if(auto r=jobPath(args,"path",command=="import_midi"||command=="export_midi"?"mid;midi":command=="export_wav"?"wav":"emproj",file);r.failed())return fail(r.getErrorMessage());
    if(command=="import_midi"){
        auto notesOnly=args.getProperty("notes_only",false);if(!notesOnly.isBool())return fail("notes_only must be boolean.");
        auto j=startJob(command,[this,file,state=capture(),notesOnly=bool(notesOnly)](const auto& job)mutable{
            if(auto r=readJobMidi(job,file,notesOnly,state);r.failed()){jobFailure(job,r);return;}
            std::lock_guard lock(job->mutex);job->commit=[this,job,state=std::move(state)]{
                finishGesture();remember("Import MIDI");if(auto r=applyTo(*edit,state,bindings,false);r.failed()){edit->getUndoManager().undoCurrentTransactionOnly();rebuild(*edit,bindings);refreshRange();jobFailure(job,r);return;}
                refreshRange();refreshPluginWatches();choose(state.tracks.back().id);recordEdit();jobStatus(job,"completed",{},1);
            };
        });return j?juce::Result::ok():juce::Result::fail(status);
    }
    if(command=="open_project"){
        auto j=startJob(command,[this,file](const auto& job){
            storage::StoredProject state;std::map<juce::String,AudioInfo> sources;
            if(auto r=storage::load(file,state,jobIO(job,0,0.5));r.failed()){jobFailure(job,r);return;}
            if(state.revision>=std::uint64_t(std::numeric_limits<juce::int64>::max())-1){jobFailure(job,juce::Result::fail("Project revision is too large."));return;}
            if(auto r=prepareJobAssets(job,state,sources,0.5,0.5);r.failed()){jobFailure(job,r);return;}
            std::lock_guard lock(job->mutex);job->commit=[this,job,file,state=std::move(state),sources=std::move(sources)]{
                for(const auto& [path,info]:sources)prepared[path]=info;std::unique_ptr<te::Edit> next;std::vector<Binding> bs;
                if(auto r=build(state,next,bs);r.failed()){jobFailure(job,r);return;}
                const auto revision=juce::jmax(guard.revision(),state.revision)+1;guard=commands::RevisionGuard(state.projectId.toStdString(),revision);adopt(std::move(next),std::move(bs),{});
                projectFile=file;savedKey=currentKey=contentKey(capture());pluginDirty=false;publish("project_opened");jobStatus(job,"completed",{},1);
            };
        });return j?juce::Result::ok():juce::Result::fail(status);
    }
    if(command=="save_project"){
        return beginSave(file);
    }
    if(command=="export_midi"){
        auto v=args.getProperty("clip_ids",{});if(!v.isVoid()&&!v.isArray())return fail("clip_ids must be an array.");
        auto ids=idsArg(args,"clip_ids");if(v.isArray()&&ids.size()!=size_t(v.size()))return fail("clip_ids must contain only strings.");
        auto j=startJob(command,[file,state=capture(),ids](const auto& job){auto r=writeJobMidi(job,file,state,ids);if(r.failed())jobFailure(job,r);else jobStatus(job,"completed",{},1);});return j?juce::Result::ok():juce::Result::fail(status);
    }
    if(command=="export_wav"){
        double start=number(args,"start_seconds",0),end=number(args,"end_seconds",duration),rate=number(args,"sample_rate",48000),bits=number(args,"bit_depth",24),tail=number(args,"tail_seconds",2);auto realtime=args.getProperty("realtime",false);
        if(!std::isfinite(start)||!std::isfinite(end)||!std::isfinite(tail)||start<0||end<=start||end>storage::maximumTimelineSeconds-tail||tail<0||tail>60)return fail("Invalid export range or tail (0 to 60 seconds).");
        if((rate!=44100&&rate!=48000&&rate!=88200&&rate!=96000)||(bits!=16&&bits!=24&&bits!=32)||!realtime.isBool())return fail("Use 44.1/48/88.2/96 kHz, 16/24/32 bit, and a boolean realtime option.");
        auto state=capture();auto check=[&](const auto& ps){for(const auto& p:ps)if(p.enabled){
            if(p.format=="E-musician"&&p.role=="effect") {
                if(!dynamic_cast<native_effects::Effect*>(livePlugin(*edit,p.id)))return false;
            }else if(p.format=="E-musician"){
                auto it=nativeRuntime.find(p.id);if(!dynamic_cast<native::Instrument*>(livePlugin(*edit,p.id))||it==nativeRuntime.end()||it->second.status!="ready")return false;
            }else if(!loadedPlugin(*edit,p.id))return false;}return true;};
        if(!check(state.masterPlugins))return fail("Restore or disable the missing master plugin before rendering.");
        for(const auto& t:state.tracks)if(!t.muted&&!check(t.plugins))return fail("Restore or disable missing plugins before rendering.");
        if(auto r=capturePluginStates(state);r.failed())return fail(r.getErrorMessage());
        std::map<juce::String,juce::String> hashes;if(auto r=nativeAssetHashes(state,hashes);r.failed())return fail(r.getErrorMessage());
        auto j=startJob(command,[file,state=std::move(state),start,end,rate,bits,tail,realtime=bool(realtime),hashes=std::move(hashes)](const auto& job){auto r=renderJob(job,file,state,start,end,rate,int(bits),tail,realtime,hashes);if(r.failed())jobFailure(job,r);else jobStatus(job,"completed",{},1);});return j?juce::Result::ok():juce::Result::fail(status);
    }
    return fail("Unknown file task.");
}

int EngineSession::runRenderWorker(const juce::StringArray& arguments)
{
    const auto flag=arguments.indexOf("--render-worker");if(flag<0||arguments.size()!=flag+3)return 2;
    if(!juce::File::isAbsolutePath(arguments[flag+1])||!juce::File::isAbsolutePath(arguments[flag+2]))return 2;
    const juce::File specFile(arguments[flag+1]),report(arguments[flag+2]);
    if(!specFile.isAChildOf(renderJobsRoot())||specFile.getFileName()!="spec.json"||report!=specFile.getSiblingFile("report.json")||specFile.getSize()>65536)return 2;
    auto spec=juce::JSON::parse(specFile);const auto id=textArg(spec,"id"),source=textArg(spec,"snapshot"),outputPath=textArg(spec,"output");
    if(id!=specFile.getParentDirectory().getFileName()||id.isEmpty()||!juce::File::isAbsolutePath(source)||!juce::File::isAbsolutePath(outputPath))return 2;
    const juce::File sourceFile(source),output(outputPath);
    if(sourceFile!=specFile.getSiblingFile("snapshot.emproj")||output.getFileName()!=".emusician-render-"+id+".wav"||output.exists())return 2;
    auto failed=[&](const juce::String& error){writeRenderReport(report,"failed",0,error);return 1;};
    const double start=number(spec,"start"),end=number(spec,"end"),rate=number(spec,"sample_rate"),tail=number(spec,"tail"),bits=number(spec,"bit_depth");
    if(!std::isfinite(start)||!std::isfinite(end)||!std::isfinite(tail)||start<0||end<=start||tail<0||tail>60||end+tail>storage::maximumTimelineSeconds||(rate!=44100&&rate!=48000&&rate!=88200&&rate!=96000)||(bits!=16&&bits!=24&&bits!=32))return failed("Invalid render specification.");
    try{
        writeRenderReport(report,"running",0);EngineSession session(false);auto& p=*session.impl;p.shuttingDown=true;storage::StoredProject state;
        if(auto r=storage::load(sourceFile,state);r.failed())return failed(r.getErrorMessage());
        std::unique_ptr<te::Edit> next;std::vector<Impl::Binding> bindings;if(auto r=p.build(state,next,bindings);r.failed())return failed(r.getErrorMessage());
        p.adopt(std::move(next),std::move(bindings),{});
        auto check=[&](const auto& ps){for(const auto& plugin:ps)if(plugin.enabled){
            if(plugin.format=="E-musician"&&plugin.role=="effect") {
                if(!dynamic_cast<native_effects::Effect*>(p.livePlugin(*p.edit,plugin.id)))return false;
            }else if(plugin.format=="E-musician"){
                auto* instrument=dynamic_cast<native::Instrument*>(p.livePlugin(*p.edit,plugin.id));if(!instrument)return false;
                native::NativeLoadQueue::Request request;
                if(auto r=nativeRequestFor(plugin,state.assets,state.projectId,state.revision,++p.nativeGeneration,request);r.failed())return false;
                auto data=juce::JSON::parse(request.stateJson);std::unique_ptr<native::PreparedBank> bank;
                // This process is an isolated render worker; no audio graph is
                // running yet, and no user GUI or realtime callback is blocked.
                if(auto r=native::prepareBank(data,request.assets,request.generation,bank);r.failed())return false;
                instrument->publish(std::move(bank));
            }else if(!p.loadedPlugin(*p.edit,plugin.id))return false;}return true;};
        if(!check(state.masterPlugins))return failed("A master plugin could not be restored in the render worker.");
        for(const auto& track:state.tracks)if(!track.muted&&!check(track.plugins))return failed("A track plugin could not be restored in the render worker.");
        juce::WavAudioFormat format;te::Renderer::Parameters params(*p.edit);params.destFile=output;params.audioFormat=&format;params.sampleRateForAudio=rate;params.bitDepth=int(bits);params.blockSizeForAudio=512;
        params.canRenderInMono=false;params.useMasterPlugins=true;params.usePlugins=true;params.realTimeRender=bool(spec.getProperty("realtime",false));params.shouldNormalise=false;params.trimSilenceAtEnds=false;
        params.time={te::TimePosition::fromSeconds(start),te::TimePosition::fromSeconds(end+tail)};params.tracksToDo=te::toBitSet(te::getAllTracks(*p.edit));
        std::atomic<float> progress{0};
        {te::Edit::ScopedRenderStatus rendering(*p.edit,false);te::Renderer::RenderTask task("Project export",params,&progress,nullptr);double last=0;
            for(;;){const auto result=task.runJob();auto now=juce::Time::getMillisecondCounterHiRes();if(now-last>=100){writeRenderReport(report,"running",progress.load());last=now;}
                if(result!=juce::ThreadPoolJob::jobNeedsRunningAgain)break;
            }
            if(task.errorMessage.isNotEmpty())return failed(task.errorMessage);
        }
        auto stream=output.createInputStream();if(!stream)return failed("Rendered WAV is missing.");std::unique_ptr<juce::AudioFormatReader> reader(format.createReaderFor(stream.release(),true));
        const auto expected=juce::int64(std::llround((end+tail-start)*rate));
        if(!reader||reader->numChannels!=2||reader->sampleRate!=rate||std::abs(reader->lengthInSamples-expected)>1)return failed("Rendered WAV failed format/duration verification.");
        if(!writeRenderReport(report,"completed",1))return 1;return 0;
    }catch(const std::exception& error){return failed(error.what());}catch(...){return failed("Unexpected render worker failure.");}
}
