// Included after EngineSession::Impl and public methods, inside emusician.
#include "StorageV3Tests.inc"

namespace {
juce::Result writeDawTestTone(const juce::File& file, int seconds, float amplitude)
{
    if (file.exists()) return juce::Result::fail("Test tone target already exists.");
    auto stream = file.createOutputStream();
    if (!stream) return juce::Result::fail("Could not create synthetic fixture.");
    juce::WavAudioFormat format;
    std::unique_ptr<juce::AudioFormatWriter> writer(format.createWriterFor(stream.get(), 48000, 2, 24, {}, 0));
    if (!writer) return juce::Result::fail("Could not create synthetic WAV writer.");
    stream.release();
    juce::AudioBuffer<float> buffer(2, 48000);
    for (int channel = 0; channel < 2; ++channel)
        for (int sample = 0; sample < buffer.getNumSamples(); ++sample)
            buffer.setSample(channel, sample, amplitude * float(std::sin(juce::MathConstants<double>::twoPi
                * (220 + 110 * channel) * sample / 48000.0)));
    for (int second = 0; second < seconds; ++second)
        if (!writer->writeFromAudioSampleBuffer(buffer, 0, buffer.getNumSamples()))
            return juce::Result::fail("Could not write synthetic WAV.");
    return juce::Result::ok();
}
}

juce::Result EngineSession::runDawSmokeTest(const juce::File& directory, const juce::File& fixtureDirectory)
{
    requireControlThread();
    int checks = 0;
    const auto check = [&](bool condition, const juce::String& message) {
        if (!condition) throw std::runtime_error(("DAW smoke: " + message).toStdString());
        ++checks;
    };
    const auto okay = [&](const juce::Result& result, const juce::String& context) {
        check(result.wasOk(), context + ": " + result.getErrorMessage());
    };
    const auto command = [&](EngineSession& target, const juce::String& name, juce::var args = object({})) {
        okay(target.execute(name, args, target.snapshot().revision), name);
    };
    try {
        okay(directory.createDirectory(), "create report directory");
        {
            bool usedNative=false;
            check(sessionSha256("abc",3,&usedNative)=="ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
                  "session SHA256 matches the published abc digest");
           #if JUCE_WINDOWS
            check(usedNative,"Windows session hashing exercises CNG rather than silently falling back");
           #endif
            std::vector<unsigned char> payload(6500000);
            for(size_t i=0;i<payload.size();++i)payload[i]=static_cast<unsigned char>((i*37+i/251)&255);
            for(size_t length:std::initializer_list<size_t>{0,1,55,56,63,64,65,4096,6500000})
                check(sessionSha256(payload.data(),length)==juce::SHA256(payload.data(),length).toHexString(),
                      "platform and JUCE SHA256 preserve identical bytes at size "+juce::String(juce::int64(length)));
        }
        // Project smoke supplies a saved, owned three-track fixture for the
        // subsequent transport and arrangement checks. DAW cases may replace
        // the active Edit; restore that same fixture before returning.
        const auto reviewProject = snapshot().projectFile;
        check(reviewProject.existsAsFile() && reviewProject.isAChildOf(directory),
              "saved UI review fixture belongs to this smoke directory");
        const auto workspace = directory.getChildFile("daw-cases-" + uid());
        okay(workspace.createDirectory(), "create owned workspace");
        okay(runStorageV3Tests(directory), "storage schema 4 regression");
        #include "EngineSessionJobRetryCases.inc"
        const auto wav = workspace.getChildFile("source.wav");
        okay(writeDawTestTone(wav, 2, 0.2f), "generate owned WAV");
        juce::Array<juce::File> sources { wav };
        for (const auto* name : { "stereo-cbr-48000.mp3", "mono-vbr-44100.mp3" }) {
            const auto owned = workspace.getChildFile(name);
            check(fixtureDirectory.getChildFile(name).copyFileTo(owned), "copy owned MP3 fixture");
            sources.add(owned);
        }
        std::vector<juce::MemoryBlock> sourceBytes;
        for (const auto& file : sources) { juce::MemoryBlock bytes; check(file.loadFileAsData(bytes), "read source bytes"); sourceBytes.push_back(bytes); }

        const auto render = [&](EngineSession& target, const juce::String& name, double seconds, int blockSize = 256) {
            const auto output = workspace.getChildFile(name + ".wav");
            check(!output.exists(), "fresh render output");
            juce::WavAudioFormat format;
            te::Renderer::Parameters params(*target.impl->edit);
            params.destFile = output; params.audioFormat = &format; params.sampleRateForAudio = 48000;
            params.blockSizeForAudio = blockSize; params.bitDepth = 24; params.canRenderInMono = false; params.useMasterPlugins = true;
            params.time = { te::TimePosition::fromSeconds(0), te::TimePosition::fromSeconds(seconds) };
            params.tracksToDo = te::toBitSet(te::getAllTracks(*target.impl->edit));
            {
                te::Edit::ScopedRenderStatus rendering(*target.impl->edit, true);
                te::Renderer::RenderTask task("DAW editing verification", params, nullptr, nullptr);
                while (task.runJob() == juce::ThreadPoolJob::jobNeedsRunningAgain) {}
                check(task.errorMessage.isEmpty(), "render " + name + ": " + task.errorMessage);
            }
            auto stream = output.createInputStream();
            check(stream != nullptr, "rendered file exists");
            std::unique_ptr<juce::AudioFormatReader> reader(format.createReaderFor(stream.release(), true));
            check(reader && reader->numChannels == 2 && reader->sampleRate == 48000
                  && std::abs(reader->lengthInSamples - juce::int64(std::llround(seconds * 48000))) <= 1,
                  "actual render format and duration");
            juce::AudioBuffer<float> samples(2, int(reader->lengthInSamples));
            check(reader->read(&samples, 0, samples.getNumSamples(), 0, true, true), "decode rendered samples");
            return samples;
        };
        const auto difference = [&](const juce::AudioBuffer<float>& a, int offsetA,
                                    const juce::AudioBuffer<float>& b, int offsetB, int count) {
            check(offsetA >= 0 && offsetB >= 0 && count > 0 && offsetA + count <= a.getNumSamples()
                  && offsetB + count <= b.getNumSamples(), "comparison bounds");
            double maximum = 0;
            for (int channel = 0; channel < 2; ++channel)
                for (int sample = 0; sample < count; ++sample)
                    maximum = juce::jmax(maximum, std::abs(double(a.getSample(channel, offsetA + sample))
                                                         - b.getSample(channel, offsetB + sample)));
            return maximum;
        };
        juce::Array<juce::var> formatReports;
        for (int index = 0; index < sources.size(); ++index) {
            EngineSession target(false);
            check(target.snapshot().bpm == 120 && target.snapshot().numerator == 4 && target.snapshot().denominator == 4,
                  "new project defaults to 120 BPM and 4/4");
            okay(target.importFile(sources[index], target.snapshot().revision), "import actual audio");
            const auto original = target.snapshot().tracks.front().clips.front();
            const auto originalTrack = target.snapshot().tracks.front().id;
            auto* editIdentity = target.impl->edit.get();
            auto* pluginIdentity = target.impl->find(originalTrack)->track->getVolumePlugin();
            auto clipIdentity = target.impl->findClip(original.id)->clip;
            const auto prefix = "format-" + juce::String(index);
            const auto baseline = render(target, prefix + "-baseline", 2);
            check(baseline.getRMSLevel(0, 12000, 60000) > 0.01f, "source render is non-silent");
            double blockSizeDifference = 0.0;
            if (original.sampleRate != 48000) {
                const auto otherBlock = render(target, prefix + "-baseline-512", 2, 512);
                blockSizeDifference = difference(baseline, 12000, otherBlock, 12000, 72000);
                check(blockSizeDifference < 0.00002, "resampled source is independent of 256/512-frame render blocks");
            }
            command(target, "trim_clip", object({ {"clip_id",original.id}, {"start_seconds",0.25}, {"end_seconds",1.75} }));
            auto trimmed = target.snapshot().tracks.front().clips.front();
            check(std::abs(trimmed.sourceOffset - 0.25) < 1e-9 && std::abs(trimmed.duration - 1.5) < 1e-9, "trim changes source window non-destructively");
            const auto trimmedAudio = render(target, prefix + "-trim", 2);
            const auto trimDifference = difference(baseline, 24000, trimmedAudio, 24000, 48000);
            check(trimDifference < 0.00002 && trimmedAudio.getMagnitude(0, 0, 11000) < 0.000001f,
                  "trim render matches retained source interval and preceding silence");
            command(target, "split_clip", object({ {"clip_id",original.id}, {"at_seconds",1.0} }));
            auto state = target.snapshot();
            check(state.tracks.front().clips.size() == 2, "split creates two clips");
            const auto right = state.tracks.front().clips.back().id;
            check(std::abs(state.tracks.front().clips.back().sourceOffset - 1.0) < 1e-9, "split right side advances source offset");
            const auto splitAudio = render(target, prefix + "-split", 2);
            check(difference(trimmedAudio, 24000, splitAudio, 24000, 20000) < 0.00002
                  && difference(trimmedAudio, 52000, splitAudio, 52000, 20000) < 0.00002,
                  "split retains audio on both sides of the boundary");
            command(target, "duplicate_clips", object({ {"clip_ids",juce::var(juce::Array<juce::var>{ original.id,right })} }));
            state = target.snapshot();
            check(state.tracks.front().clips.size() == 4, "duplicate two clips");
            juce::Array<juce::var> duplicateIds;
            for (const auto& c : state.tracks.front().clips) if (c.id != original.id && c.id != right) duplicateIds.add(c.id);
            const auto duplicated = render(target, prefix + "-duplicate", 3.5);
            check(difference(baseline, 24000, duplicated, 96000, 18000) < 0.00002, "duplicate renders the same source window later");
            command(target, "create_track", object({ {"kind","audio"}, {"name","Destination"} }));
            const auto otherTrack = target.snapshot().tracks.back().id;
            command(target, "move_clips", object({ {"clip_ids",juce::var(juce::Array<juce::var>{right})}, {"delta_seconds",0.0}, {"target_track_id",otherTrack} }));
            check(target.snapshot().tracks.back().clips.front().id == right, "cross-track movement retains clip identity");
            const auto crossTrack = render(target, prefix + "-cross-track", 3.5);
            check(difference(duplicated, 52000, crossTrack, 52000, 20000) < 0.00002, "cross-track move preserves source samples");
            const auto beforeDelete = contentKey(target.impl->capture());
            command(target, "delete_clips", object({ {"clip_ids",duplicateIds} }));
            const auto afterDelete = contentKey(target.impl->capture());
            check(beforeDelete != afterDelete, "delete changes project");
            command(target, "undo"); check(contentKey(target.impl->capture()) == beforeDelete, "one undo restores complete deletion");
            command(target, "redo"); check(contentKey(target.impl->capture()) == afterDelete, "one redo repeats complete deletion");
            command(target, "set_track_pan", object({ {"track_id",otherTrack}, {"pan",0.5} }));
            check(std::abs(target.snapshot().tracks.back().pan - 0.5f) < 1e-6, "track pan reaches engine");
            const auto beforeGesture = contentKey(target.impl->capture());
            target.beginEditGesture();
            command(target, "set_track_gain", object({{"track_id",originalTrack},{"gain_db",-2.0}}));
            command(target, "set_track_gain", object({{"track_id",originalTrack},{"gain_db",-4.0}}));
            const auto acceptedGesture = contentKey(target.impl->capture());
            const auto gestureRevision = target.snapshot().revision;
            check(target.execute("trim_clip",object({{"clip_id",original.id},{"start_seconds",0.0},{"end_seconds",10.0},{"source_offset",0.0}}),gestureRevision).failed(),
                  "source-bound failure inside gesture rejected");
            check(contentKey(target.impl->capture()) == acceptedGesture && target.snapshot().revision == gestureRevision,
                  "failed gesture command preserves prior successful edits");
            target.endEditGesture();
            command(target,"undo");
            check(contentKey(target.impl->capture()) == beforeGesture, "one gesture undo restores state before gain gesture");
            command(target, "set_clip_fades", object({ {"clip_id",original.id}, {"fade_in_seconds",0.1}, {"fade_out_seconds",0.1} }));
            command(target, "set_tempo", object({ {"bpm",145.0} }));
            command(target, "set_time_signature", object({ {"numerator",3}, {"denominator",4} }));
            command(target, "set_loop_range", object({ {"start_seconds",0.25}, {"end_seconds",1.75} }));
            command(target, "set_loop", object({ {"enabled",true} }));
            check(target.snapshot().looping, "loop command enables looping");
            command(target,"undo");
            check(!target.snapshot().looping, "one undo restores disabled looping");
            command(target,"redo");
            check(target.snapshot().looping, "one redo restores enabled looping");
            check(target.snapshot().bpm == 145 && target.snapshot().looping && target.snapshot().numerator == 3
                  && target.impl->edit.get() == editIdentity && target.impl->findClip(original.id)->clip == clipIdentity
                  && target.impl->find(originalTrack)->track->getVolumePlugin() == pluginIdentity,
                  "ordinary edits retain Edit, original Clip and unrelated built-in volume plugin instances");
            const auto savedKey = contentKey(target.impl->capture());
            const auto file = workspace.getChildFile(prefix + ".emproj");
            okay(target.saveProject(file, target.snapshot().revision), "save schema 4 project");
            check(int(juce::JSON::parse(file.loadFileAsString()).getProperty("schema",0)) == 4, "schema 4 manifest written");
            EngineSession reopened(false);
            okay(reopened.openProject(file, reopened.snapshot().revision), "reopen schema 4 project");
            check(contentKey(reopened.impl->capture()) == savedKey && !reopened.snapshot().dirty, "save/load preserves edits and marks clean");
            formatReports.add(object({ {"format",original.format}, {"sample_rate",original.sampleRate},
                {"channels",original.channels}, {"trim_max_sample_difference",trimDifference},
                {"block_size_max_sample_difference",blockSizeDifference}, {"source",sources[index].getFileName()} }));
        }

        EngineSession midi(false);
        command(midi, "create_track", object({ {"kind","instrument"}, {"name","MIDI test"} }));
        const auto trackId = midi.snapshot().tracks.front().id;
        command(midi, "create_midi_clip", object({ {"track_id",trackId}, {"start_beats",4.0}, {"length_beats",32.0} }));
        const auto clipId = midi.snapshot().tracks.front().clips.front().id;
        juce::Array<juce::var> notes;
        for (int i = 0; i < 32; ++i) notes.add(object({ {"id","note-" + juce::String(i)}, {"pitch",60+i%5},
            {"start_beats",double(i)}, {"length_beats",0.5}, {"velocity",80}, {"channel",1} }));
        const auto beforeNotes = contentKey(midi.impl->capture());
        command(midi, "write_notes", object({ {"clip_id",clipId}, {"notes",notes} }));
        const auto afterNotes = contentKey(midi.impl->capture());
        check(midi.snapshot().tracks.front().clips.front().notes->size() == 32, "write notes persists actual MIDI events");
        command(midi, "undo"); check(contentKey(midi.impl->capture()) == beforeNotes, "one undo removes complete note edit");
        command(midi, "redo"); check(contentKey(midi.impl->capture()) == afterNotes, "one redo restores complete note edit");
        for (const auto* name : { "delete_clips", "duplicate_clips", "move_clips" }) {
            const auto beforeInvalidIds = contentKey(midi.impl->capture());
            const auto revision = midi.snapshot().revision;
            const auto invalidIds = object({{"clip_ids",juce::var(juce::Array<juce::var>{clipId,123})},{"delta_seconds",0.5}});
            check(midi.execute(name,invalidIds,revision).failed(), "mixed string/non-string clip_ids rejects whole command");
            check(contentKey(midi.impl->capture()) == beforeInvalidIds && midi.snapshot().revision == revision,
                  "invalid clip_ids preserves content and revision: " + juce::String(name));
        }

        const auto partialBefore = contentKey(midi.impl->capture());
        const auto updatedNote = object({{"id","note-0"},{"pitch",72},{"start_beats",0.125},{"length_beats",0.25},{"velocity",91},{"channel",1}});
        const auto addedNote = object({{"id","note-added"},{"pitch",84},{"start_beats",31.75},{"length_beats",0.25},{"velocity",63},{"channel",1}});
        command(midi,"edit_notes",object({{"clip_id",clipId},{"upsert",juce::var(juce::Array<juce::var>{updatedNote,addedNote})},
                                         {"delete_ids",juce::var(juce::Array<juce::var>{"note-1"})}}));
        const auto partialNotes = midi.snapshot().tracks.front().clips.front().notes;
        const auto findNote = [&](const juce::String& id) {
            return std::find_if(partialNotes->begin(),partialNotes->end(),[&](const auto& note){return note.id == id;});
        };
        const auto updated = findNote("note-0"), added = findNote("note-added"), untouchedNote = findNote("note-2");
        check(partialNotes->size() == 32 && updated != partialNotes->end() && updated->pitch == 72
              && updated->velocity == 91 && std::abs(updated->startBeats-0.125) < 1e-9
              && std::abs(updated->lengthBeats-0.25) < 1e-9 && updated->channel == 1,
              "edit_notes updates full note data without changing its stable ID");
        check(added != partialNotes->end() && added->pitch == 84 && findNote("note-1") == partialNotes->end()
              && untouchedNote != partialNotes->end() && untouchedNote->pitch == 62 && untouchedNote->startBeats == 2,
              "edit_notes adds/deletes requested IDs and preserves unrelated notes");
        const auto partialAfter = contentKey(midi.impl->capture());
        const auto partialRevision = midi.snapshot().revision;
        const juce::var emptyIds = juce::Array<juce::var>{};
        for (const auto& invalidEdit : std::initializer_list<juce::var> {
                object({{"clip_id",clipId},{"upsert",emptyIds},{"delete_ids",juce::var(juce::Array<juce::var>{"missing-note"})}}),
                object({{"clip_id",clipId},{"upsert",juce::var(juce::Array<juce::var>{updatedNote,updatedNote})},{"delete_ids",emptyIds}}),
                object({{"clip_id",clipId},{"upsert",emptyIds},{"delete_ids",juce::var(juce::Array<juce::var>{"note-2","note-2"})}}),
                object({{"clip_id",clipId},{"upsert",juce::var(juce::Array<juce::var>{updatedNote})},{"delete_ids",juce::var(juce::Array<juce::var>{"note-0"})}}) }) {
            check(midi.execute("edit_notes",invalidEdit,partialRevision).failed(), "invalid deletion or repeated/conflicting note IDs rejected");
            check(contentKey(midi.impl->capture()) == partialAfter && midi.snapshot().revision == partialRevision,
                  "invalid partial note edit preserves content and revision");
        }
        command(midi,"undo");
        check(contentKey(midi.impl->capture()) == partialBefore, "one undo restores update/add/delete note edit together");
        command(midi, "set_tempo", object({ {"bpm",150.0} }));
        check(std::abs(midi.snapshot().tracks.front().clips.front().timelineStart - 1.6) < 1e-9
              && std::abs(midi.snapshot().tracks.front().clips.front().duration - 12.8) < 1e-9, "MIDI beats remain authoritative across tempo changes");

        const auto envelope = [&](EngineSession& target, const juce::String& commandName, juce::var args) {
            const auto state = target.snapshot();
            return object({ {"request_id",uid()}, {"project_id",state.projectId}, {"expected_revision",juce::int64(state.revision)}, {"command",commandName}, {"args",args} });
        };
        const auto mutation = envelope(midi, "set_track_pan", object({ {"track_id",trackId}, {"pan",0.25} }));
        const auto reply = midi.executeRequest(mutation);
        check(reply.getProperty("status",{}).toString() == "completed", "write envelope completes");
        auto before = midi.snapshot(); auto beforeKey = contentKey(midi.impl->capture());
        check(juce::JSON::toString(midi.executeRequest(mutation)) == juce::JSON::toString(reply)
              && midi.snapshot().revision == before.revision, "idempotency returns same result without repeating edit");
        auto stale = envelope(midi, "set_tempo", object({ {"bpm",160.0} }));
        stale.getDynamicObject()->setProperty("expected_revision",juce::int64(before.revision - 1));
        check(midi.executeRequest(stale).getProperty("status",{}).toString() == "conflict", "stale revision rejected");
        juce::Array<juce::var> invalidBatch { object({ {"command","set_tempo"}, {"args",object({{"bpm",160.0}})} }),
            object({ {"command","set_track_pan"}, {"args",object({{"track_id",trackId},{"pan",2.0}})} }) };
        check(midi.executeRequest(envelope(midi,"batch",object({{"commands",invalidBatch}}))).getProperty("status",{}).toString() == "failed",
              "invalid batch rejected");
        check(contentKey(midi.impl->capture()) == beforeKey && midi.snapshot().revision == before.revision,
              "conflict and invalid batch preserve state/revision");
        const auto page = midi.executeRequest(object({ {"command","get_clip_notes"}, {"args",object({{"clip_id",clipId},{"offset",7},{"limit",5}})} }));
        auto pageResult = page.getProperty("result",{});
        check(int(pageResult.getProperty("total",0)) == 32 && pageResult.getProperty("notes",{}).size() == 5,
              "Agent paginates actual note state");
        const auto waitJob = [&](EngineSession& target, const juce::var& response) {
            check(response.getProperty("status",{}).toString() == "accepted", "background task is accepted, not completed");
            const auto jobId = response.getProperty("result",{}).getProperty("job_id",{}).toString();
            const auto deadline = juce::Time::getMillisecondCounterHiRes() + 60000;
            while (juce::Time::getMillisecondCounterHiRes() < deadline) {
                auto current = target.executeRequest(object({ {"command","get_job"}, {"args",object({{"job_id",jobId}})} })).getProperty("result",{});
                const auto status = current.getProperty("status",{}).toString();
                if (status == "completed" && !target.hasActiveJobs()) { ++checks; return; }
                check(status != "failed" && status != "cancelled" && status != "conflict",
                      "background task: " + status + " " + current.getProperty("error",{}).toString());
                juce::MessageManager::getInstance()->runDispatchLoopUntil(10);
            }
            check(false, "background task completion timeout");
        };
        const auto midiFile = workspace.getChildFile("notes.mid");
        waitJob(midi, midi.executeRequest(envelope(midi,"export_midi",object({{"path",midiFile.getFullPathName()}}))));
        check(midiFile.existsAsFile() && midiFile.getSize() > 14, "SMF written by export job");
        const auto savedMidi = workspace.getChildFile("notes.emproj");
        okay(midi.saveProject(savedMidi, midi.snapshot().revision), "save MIDI project");
        EngineSession reopenedMidi(false);
        okay(reopenedMidi.openProject(savedMidi, reopenedMidi.snapshot().revision), "reopen MIDI project");
        check(contentKey(reopenedMidi.impl->capture()) == contentKey(midi.impl->capture()), "schema 4 MIDI round trip");
        EngineSession importedMidi(false);
        waitJob(importedMidi, importedMidi.executeRequest(envelope(importedMidi,"import_midi",object({{"path",midiFile.getFullPathName()}}))));
        int importedNotes = 0;
        for (const auto& track : importedMidi.snapshot().tracks) for (const auto& clip : track.clips)
            if (clip.notes) importedNotes += int(clip.notes->size());
        check(importedNotes == 32, "SMF import restores all exported notes");

        // Real completed jobs exercise bounded history eviction and the 65th
        // request acknowledgement; a constant ring size is not a completion signal.
        juce::String previousJob;
        for (int i = 0; i < 65; ++i) {
            const auto file = workspace.getChildFile("job-ring-" + juce::String(i) + ".mid");
            const auto response = midi.executeRequest(envelope(midi,"export_midi",object({{"path",file.getFullPathName()}})));
            const auto jobId = response.getProperty("result",{}).getProperty("job_id",{}).toString();
            check(jobId.isNotEmpty() && jobId != previousJob, "each file task receives a new job ID across ring eviction");
            waitJob(midi,response); previousJob = jobId;
        }
        check(midi.impl->jobs.size() == 64, "completed job history remains bounded to 64");

        EngineSession paged(false);
        command(paged,"create_track",object({{"kind","instrument"},{"name","Paged clips"}}));
        const auto pagedTrack = paged.snapshot().tracks.front().id;
        juce::Array<juce::var> clipCommands;
        for (int i = 0; i < 70; ++i) clipCommands.add(object({{"command","create_midi_clip"},
            {"args",object({{"track_id",pagedTrack},{"start_beats",double(i*4)},{"length_beats",4.0}})}}));
        command(paged,"batch",object({{"commands",clipCommands}}));
        const auto overview = paged.snapshotJson();
        const auto trackOverview = overview.getProperty("tracks",{})[0];
        check(int(trackOverview.getProperty("clip_count",0)) == 70 && trackOverview.getProperty("clips",{}).size() == 64
              && bool(trackOverview.getProperty("clips_truncated",false)), "snapshot advertises bounded clip preview");
        const auto clipPage = paged.executeRequest(object({{"command","get_track_clips"},
            {"args",object({{"track_id",pagedTrack},{"offset",64},{"limit",10}})}})).getProperty("result",{});
        check(int(clipPage.getProperty("total",0)) == 70 && clipPage.getProperty("clips",{}).size() == 6,
              "clip page retrieves objects omitted from snapshot");
        const auto catalogPage = paged.executeRequest(object({{"command","get_plugin_catalog"},{"args",object({{"offset",0},{"limit",1}})}}));
        check(catalogPage.getProperty("status",{}).toString() == "completed", "plugin catalog has a bounded read API");
        for (juce::var invalid : {juce::var(-1),juce::var(1.5),juce::var(1.0e300),juce::var("1")})
            check(paged.executeRequest(object({{"command","get_events"},{"args",object({{"after_sequence",invalid}})}})).getProperty("status",{}).toString() == "invalid",
                  "event cursor rejects non-integer or negative values");

        // A complete SEQUENCE replacement must invalidate Tracktion's derived
        // looped MIDI cache on apply, Undo and Redo, even when its channel stays
        // unchanged. Snapshot-only checks cannot detect stale playback notes.
        {
            EngineSession looped(false);
            command(looped,"create_track",object({{"kind","instrument"},{"name","Sequence cache regression"}}));
            const auto loopTrack=looped.snapshot().tracks.front().id;
            command(looped,"create_midi_clip",object({{"track_id",loopTrack},{"start_beats",0.0},{"length_beats",8.0}}));
            const auto loopClip=looped.snapshot().tracks.front().clips.front().id;
            juce::Array<juce::var> notes;
            for(int i=0;i<256;++i)notes.add(object({{"id","loop-note-"+juce::String(i)},{"pitch",60+i%12},
                {"start_beats",double(i)/64.0},{"length_beats",1.0/128.0},{"velocity",80},{"channel",1}}));
            command(looped,"write_notes",object({{"clip_id",loopClip},{"notes",notes}}));
            auto* native=dynamic_cast<te::MidiClip*>(looped.impl->findClip(loopClip)->clip.get());
            auto* originalEdit=looped.impl->edit.get();auto* originalTrack=looped.impl->find(loopTrack)->track;
            native->setLoopRangeBeats({te::BeatPosition::fromBeats(0),te::BeatPosition::fromBeats(4)});
            const auto cachedVelocity=[&](int velocity){
                const auto& values=native->getSequenceLooped().getNotes();
                return values.size()==512&&std::all_of(values.begin(),values.end(),[&](auto* n){return n->getVelocity()==velocity;});
            };
            check(cachedVelocity(80),"build native loop cache before dense sequence edit");
            const auto snapshotNotes=looped.snapshot().tracks.front().clips.front().notes;
            command(looped,"set_track_pan",object({{"track_id",loopTrack},{"pan",0.25}}));
            check(looped.snapshot().tracks.front().clips.front().notes==snapshotNotes,
                  "mix revision reuses immutable note view");
            command(looped,"undo");
            for(auto& note:notes)note.getDynamicObject()->setProperty("velocity",103);
            command(looped,"write_notes",object({{"clip_id",loopClip},{"notes",notes}}));
            check(cachedVelocity(103),"dense sequence edit refreshes native looped playback notes");
            command(looped,"undo");check(cachedVelocity(80),"dense sequence undo refreshes native looped playback notes");
            command(looped,"redo");check(cachedVelocity(103),"dense sequence redo refreshes native looped playback notes");
            check(looped.impl->edit.get()==originalEdit&&looped.impl->find(loopTrack)->track==originalTrack
                  &&looped.impl->findClip(loopClip)->clip.get()==native,
                  "dense sequence apply/undo/redo retains Edit, track and clip instances");
            check(looped.impl->currentKey==contentKey(looped.impl->capture()),
                  "cached note digest matches authoritative capture after sequence redo");
        }

        // This uses the same complete-note command as the GUI. Timings are
        // control-thread diagnostics for this fixture, not realtime guarantees.
        juce::var denseMidiDiagnostics;
        {
            EngineSession dense(false);
            command(dense,"create_track",object({{"kind","instrument"},{"name","10001 note editing"}}));
            const auto denseTrack = dense.snapshot().tracks.front().id;
            command(dense,"create_midi_clip",object({{"track_id",denseTrack},{"start_beats",0.0},{"length_beats",16.0}}));
            const auto denseClip = dense.snapshot().tracks.front().clips.front().id;
            const auto denseEmpty = contentKey(dense.impl->capture());
            juce::Array<juce::var> denseNotes;
            denseNotes.ensureStorageAllocated(10001);
            for (int i = 0; i < 10001; ++i) denseNotes.add(object({{"id","dense-note-" + juce::String(i)},
                {"pitch",60+i%12},{"start_beats",double(i)/1024.0},{"length_beats",1.0/2048.0},{"velocity",80},{"channel",1}}));
            auto started = juce::Time::getMillisecondCounterHiRes();
            command(dense,"write_notes",object({{"clip_id",denseClip},{"notes",denseNotes}}));
            const auto initialWriteMs = juce::Time::getMillisecondCounterHiRes() - started;
            check(dense.snapshot().tracks.front().clips.front().notes->size() == 10001, "complete write accepts a 10001-note clip");
            const auto denseInitial = contentKey(dense.impl->capture());
            const auto heldNotes=dense.snapshot().tracks.front().clips.front().notes;
            auto sparse=denseNotes.getReference(5000).clone();sparse.getDynamicObject()->setProperty("velocity",101);
            sparse.getDynamicObject()->setProperty("length_beats",1.0/1024.0);
            command(dense,"edit_notes",object({{"clip_id",denseClip},{"upsert",juce::var(juce::Array<juce::var>{sparse})}}));
            const auto patchedNotes=dense.snapshot().tracks.front().clips.front().notes;
            check(heldNotes!=patchedNotes&&(*heldNotes)[5000].velocity==80&&(*heldNotes)[5000].lengthBeats==1.0/2048.0,
                  "sparse note cache preserves an older immutable snapshot");
            check(patchedNotes->size()==10001&&(*patchedNotes)[5000].id=="dense-note-5000"&&(*patchedNotes)[5000].velocity==101&&(*patchedNotes)[5000].lengthBeats==1.0/1024.0,
                  "sparse value patch preserves order, stable IDs and count");
            auto* nativeDense=dynamic_cast<te::MidiClip*>(dense.impl->findClip(denseClip)->clip.get());
            std::vector<NoteSnapshot> nativeNotes;nativeNotes.reserve(size_t(nativeDense->getSequence().getNumNotes()));
            for(auto* n:nativeDense->getSequence().getNotes())nativeNotes.push_back({n->state[emId].toString(),n->getNoteNumber(),n->getStartBeat().inBeats(),n->getLengthBeats().inBeats(),n->getVelocity(),nativeDense->getMidiChannel().getChannelNumber()});
            check(noteContentKey(nativeNotes)==dense.impl->noteView(denseClip,*nativeDense).key,
                  "sparse cached digest is byte-equivalent to a fresh authoritative native read");
            const auto sparseKey=dense.impl->currentKey;
            command(dense,"undo");check(dense.impl->currentKey==denseInitial,"sparse value Undo invalidates the patched view and restores the original digest");
            command(dense,"redo");check(dense.impl->currentKey==sparseKey&&dense.snapshot().tracks.front().clips.front().notes->at(5000).velocity==101,
                  "sparse value Redo rebuilds the native-derived view");
            command(dense,"undo");
            denseNotes.getReference(5000).getDynamicObject()->setProperty("pitch",79);
            started = juce::Time::getMillisecondCounterHiRes();
            command(dense,"write_notes",object({{"clip_id",denseClip},{"notes",denseNotes}}));
            const auto completeEditMs = juce::Time::getMillisecondCounterHiRes() - started;
            auto editedNotes = dense.snapshot().tracks.front().clips.front().notes;
            const auto editedNote = std::find_if(editedNotes->begin(),editedNotes->end(),[](const auto& note){return note.id == "dense-note-5000";});
            check(editedNotes->size() == 10001 && editedNote != editedNotes->end() && editedNote->pitch == 79,
                  "full GUI-style rewrite updates a note above the former 10000-note limit");
            command(dense,"undo");
            check(contentKey(dense.impl->capture()) == denseInitial, "one undo restores complete 10001-note edit");
            started = juce::Time::getMillisecondCounterHiRes();
            command(dense,"set_track_pan",object({{"track_id",denseTrack},{"pan",0.125}}));
            const auto mixMs = juce::Time::getMillisecondCounterHiRes() - started;
            check(std::abs(dense.snapshot().tracks.front().pan-0.125f) < 1e-6, "mix edit applies with 10001 notes present");
            command(dense,"undo");
            check(contentKey(dense.impl->capture()) == denseInitial, "dense-project mix undo preserves notes");
            command(dense,"undo");
            check(contentKey(dense.impl->capture()) == denseEmpty, "one undo removes original 10001-note write");
            denseMidiDiagnostics = object({{"note_count",10001},{"initial_write_ms",initialWriteMs},{"complete_note_edit_ms",completeEditMs},
                {"single_pan_command_ms",mixMs},{"scope","Single control-thread command elapsed time in this smoke fixture; no realtime or sustained-performance claim."}});
        }

        // Device playback check is explicit and reported separately from offline renders.
        okay(newProject(snapshot().revision), "new synthetic playback project");
        okay(importFile(wav, snapshot().revision), "import synthetic playback source");
        command(*this, "set_master_gain", object({{"gain_db",-60.0}}));
        command(*this, "set_loop", object({{"enabled",true}}));
        bool playbackExercised = false;
        if (snapshot().deviceAvailable) {
            auto* originalEdit = impl->edit.get();
            auto* originalPlugin = impl->bindings.front().track->getVolumePlugin();
            togglePlay(); juce::MessageManager::getInstance()->runDispatchLoopUntil(100);
            check(snapshot().playing, "synthetic playback starts");
            command(*this, "set_track_pan", object({{"track_id",snapshot().tracks.front().id},{"pan",0.2}}));
            command(*this, "move_clip", object({{"clip_id",snapshot().tracks.front().clips.front().id},{"start_seconds",0.1}}));
            command(*this, "undo");
            check(snapshot().playing && impl->edit.get() == originalEdit
                  && impl->bindings.front().track->getVolumePlugin() == originalPlugin,
                  "edit and undo keep transport playing and preserve Edit/plugin instances");
            playbackExercised = true; stop();
        }
        for (int i = 0; i < sources.size(); ++i) {
            juce::MemoryBlock current; check(sources[i].loadFileAsData(current) && current == sourceBytes[size_t(i)], "input bytes unchanged");
        }
        okay(openProject(reviewProject, snapshot().revision), "restore saved multitrack UI fixture");
        check(snapshot().tracks.size() == 3 && !snapshot().dirty && !snapshot().playing && !snapshot().looping,
              "transport and arrangement receive the clean three-track review project");
        const auto report = object({ {"status","passed"}, {"checks_passed",checks}, {"formats",formatReports},
            {"scope","Actual Tracktion audio renders, editing/undo, schema 4, MIDI SMF jobs and in-process Agent protocol. No third-party VST binary or listening claim."},
            {"playback_edit_check",playbackExercised?"passed":"unsupported_no_output_device"},
            {"dense_midi_diagnostics",denseMidiDiagnostics},
            {"storage_report","storage-v3-report.json"}, {"workspace",workspace.getFullPathName()} });
        check(directory.getChildFile("daw-report.json").replaceWithText(juce::JSON::toString(report)), "write DAW report");
        return juce::Result::ok();
    } catch (const std::exception& error) {
        stop(); return juce::Result::fail(error.what());
    }
}

juce::Result EngineSession::runPerformanceProbe(const juce::File& directory, int seconds)
{
    requireControlThread();
    if (seconds < 1 || seconds > 86400) return juce::Result::fail("Performance duration must be 1 to 86400 seconds.");
    if (auto result = directory.createDirectory(); result.failed()) return result;
    const auto reportFile = directory.getChildFile("performance-report.json");
    if (reportFile.exists()) return juce::Result::fail("Use a fresh performance output directory.");
    const auto workspace = directory.getChildFile("performance-sources-" + uid());
    if (auto result = workspace.createDirectory(); result.failed()) return result;
    const auto source = workspace.getChildFile("track-0.wav");
    if (auto result = writeDawTestTone(source, 8, 0.002f); result.failed()) return result;
    juce::Array<juce::File> sources { source };
    for (int i = 1; i < 16; ++i) {
        const auto file = workspace.getChildFile("track-" + juce::String(i) + ".wav");
        if (!source.copyFileTo(file)) return juce::Result::fail("Could not create independent synthetic source files.");
        sources.add(file);
    }
    if (auto result = newProject(snapshot().revision); result.failed()) return result;
    if (auto result = importFiles(sources, snapshot().revision); result.failed()) return result;
    for (const auto& [name,args] : std::initializer_list<std::pair<juce::String,juce::var>> {
            {"set_master_gain",object({{"gain_db",-36.0}})},
            {"set_loop_range",object({{"start_seconds",0.0},{"end_seconds",8.0}})},
            {"set_loop",object({{"enabled",true}})} })
        if (auto result = execute(name,args,snapshot().revision); result.failed()) return result;
    auto& manager = deviceManager();
    juce::String deviceConfigurationError;
    bool deviceConfigurationChanged = false;
    if (auto* device = manager.getCurrentAudioDevice()) {
        auto setup = manager.getAudioDeviceSetup();
        if (device->getAvailableSampleRates().contains(48000.0) && device->getCurrentSampleRate() != 48000.0) { setup.sampleRate = 48000; deviceConfigurationChanged = true; }
        if (device->getAvailableBufferSizes().contains(256) && device->getCurrentBufferSizeSamples() != 256) { setup.bufferSize = 256; deviceConfigurationChanged = true; }
        if (deviceConfigurationChanged) deviceConfigurationError = manager.setAudioDeviceSetup(setup,true);
    }
    const auto initial = snapshot();
    if (!initial.deviceAvailable) {
        const auto report = object({{"status","unsupported"},{"reason","No open output device"},
            {"requested_sample_rate",48000},{"requested_buffer_size",256},{"requested_measure_seconds",seconds},
            {"actual_measure_seconds",0.0},{"tracks",16},{"configuration_error",deviceConfigurationError}});
        return reportFile.replaceWithText(juce::JSON::toString(report)) ? juce::Result::ok() : juce::Result::fail("Could not write unsupported performance report.");
    }
    struct Probe {
        double initializingAt = 0, stableSince = 0, started = 0, measuredAt = 0, previousTick = 0, nextEdit = 0, nextProgress = 0;
        double sampleRate = 0;
        int bufferSize = 0;
        int startXruns = 0, editCount = 0;
        juce::int64 stableCallbacks = 0;
        bool measuring = false, transportStayedPlaying = true, identitiesPreserved = true;
        juce::String error, stableDeviceSignature, startedIso = juce::Time::getCurrentTime().toISO8601(true);
        juce::var initialization, firstStop;
        std::vector<double> cpu, timerLag, dispatch;
        juce::Array<juce::var> memory;
        std::uint64_t startProcessTicks = 0;
        te::Edit* edit = nullptr;
        std::vector<te::Plugin*> plugins;
    };
    auto probe = std::make_shared<Probe>();
    probe->initializingAt = probe->previousTick = juce::Time::getMillisecondCounterHiRes();
    probe->nextProgress=probe->initializingAt;probe->startXruns=initial.xruns;
    probe->edit = impl->edit.get();
    for (const auto& binding : impl->bindings) probe->plugins.push_back(binding.track->getVolumePlugin());
    const std::weak_ptr<bool> lifetime = impl->alive;
    const auto processTicks = []() -> std::uint64_t {
       #if JUCE_WINDOWS
        FILETIME created {}, exited {}, kernel {}, user {};
        if (GetProcessTimes(GetCurrentProcess(),&created,&exited,&kernel,&user))
            return (std::uint64_t(kernel.dwHighDateTime)<<32) + kernel.dwLowDateTime
                 + (std::uint64_t(user.dwHighDateTime)<<32) + user.dwLowDateTime;
       #endif
        return 0;
    };
    const auto sampleMemory = [](double elapsed) -> juce::var {
       #if JUCE_WINDOWS
        using ReadMemory = BOOL (WINAPI*)(HANDLE, PPROCESS_MEMORY_COUNTERS, DWORD);
        auto read = reinterpret_cast<ReadMemory>(GetProcAddress(GetModuleHandleW(L"kernel32.dll"),"K32GetProcessMemoryInfo"));
        PROCESS_MEMORY_COUNTERS_EX counters {};
        counters.cb = sizeof(counters);
        if (read && read(GetCurrentProcess(),reinterpret_cast<PPROCESS_MEMORY_COUNTERS>(&counters),sizeof(counters)))
            return object({{"elapsed_seconds",elapsed},{"private_bytes",juce::int64(counters.PrivateUsage)},
                           {"working_set_bytes",juce::int64(counters.WorkingSetSize)}});
       #endif
        return object({{"elapsed_seconds",elapsed},{"status","unavailable"}});
    };
    auto callback = std::make_shared<std::function<void()>>();
    const std::weak_ptr<std::function<void()>> recur = callback;
    *callback = [this,lifetime,recur,probe,reportFile,seconds,deviceConfigurationError,deviceConfigurationChanged,processTicks,sampleMemory] {
        const auto alive = lifetime.lock();
        if (!alive || !*alive) return;
        auto now = juce::Time::getMillisecondCounterHiRes();
        auto state = snapshot();
        if (probe->started == 0) {
            // The pinned engine queues driver preparation, wave-list changes
            // and Edit graph rebuilds. Drain their public message-thread hooks
            // before the single Play. There is no public all-MIDI-updates-ready
            // predicate: the stable interval below is an explicit startup
            // barrier, not proof of the cause of a previous interruption.
            auto& dm = impl->engine.getDeviceManager();
            deviceManager().dispatchPendingMessages();
            dm.dispatchPendingUpdates();dm.dispatchPendingMessages();
            impl->edit->dispatchPendingUpdatesSynchronously();
            impl->edit->getTransport().ensureContextAllocated();
            auto* device = deviceManager().getCurrentAudioDevice();
            auto* context = impl->edit->getCurrentPlaybackContext();
            const bool open = device && device->isOpen();
            const bool callbacksStarted = open && device->isPlaying();
            const bool graphAllocated = context && context->isPlaybackGraphAllocated();
            const bool formatReady = open && std::abs(dm.getSampleRate()-device->getCurrentSampleRate()) < 0.01 && dm.getBlockSize() == device->getCurrentBufferSizeSamples();
            const auto callbacks = juce::int64(dm.getCPUStatistics().numRuns);
            juce::String signature = deviceManager().getCurrentAudioDeviceType();
            if (device) signature += "|" + device->getName() + "|" + juce::String(device->getCurrentSampleRate()) + "|" + juce::String(device->getCurrentBufferSizeSamples())
                + "|" + device->getActiveInputChannels().toString(2) + "|" + device->getActiveOutputChannels().toString(2);
            for (auto* input : dm.getWaveInputDevices()) signature += "|wave:" + input->getDeviceID() + ":" + juce::String(int(input->isEnabled()));
            for (const auto& input : dm.getMidiInDevices()) signature += "|midi:" + input->getDeviceID() + ":" + juce::String(int(input->isEnabled()));
            const bool ready = open && callbacksStarted && graphAllocated && formatReady;
            if (!ready || signature != probe->stableDeviceSignature || probe->stableSince == 0) {
                probe->stableDeviceSignature = signature;probe->stableSince = ready ? now : 0;probe->stableCallbacks = callbacks;
            }
            probe->initialization = object({{"device_open",open},{"driver_callbacks_started",callbacksStarted},{"graph_allocated",graphAllocated},{"format_ready",formatReady},
                {"stable_seconds",probe->stableSince > 0 ? (now-probe->stableSince)/1000.0 : 0.0},{"required_stable_seconds",2.0},
                {"callbacks_since_stable",callbacks-probe->stableCallbacks},{"device_signature",signature}});
            state = snapshot();
            if (state.playing) probe->error = "Transport started before probe initialization completed.";
            else if (ready && now-probe->stableSince >= 2000 && callbacks > probe->stableCallbacks) {
                probe->sampleRate = state.sampleRate;probe->bufferSize = state.bufferSize;probe->startXruns = state.xruns;
                impl->edit->getTransport().play(false);
                now = juce::Time::getMillisecondCounterHiRes();probe->started = now;probe->nextProgress = now;state = snapshot();
                impl->status = "Performance probe: 120 s warmup, then " + juce::String(seconds) + " s measured playback.";
            } else if (now-probe->initializingAt >= 15000) probe->error = "Audio device and playback graph did not become stable within 15 seconds.";
        }
        if (probe->started > 0 && !state.playing) {
            probe->transportStayedPlaying = false;
            auto* context = impl->edit->getCurrentPlaybackContext();
            if (probe->firstStop.isVoid()) probe->firstStop = object({{"detected_at",juce::Time::getCurrentTime().toISO8601(true)},
                {"phase",probe->measuring ? "measuring" : "warmup"},{"seconds_since_play",(now-probe->started)/1000.0},
                {"position_seconds",state.position},{"looping",state.looping},{"loop_start",state.loopStart},{"loop_end",state.loopEnd},
                {"driver_type",deviceManager().getCurrentAudioDeviceType()},{"device",state.deviceName},{"device_available",state.deviceAvailable},
                {"sample_rate",state.sampleRate},{"buffer_size",state.bufferSize},{"graph_allocated",context && context->isPlaybackGraphAllocated()},
                {"native_playing",context && context->isPlaying()},{"play_pending",context && context->isPlayPending()},
                {"cause","unattributed: observed transport stop; no automatic restart"}});
            probe->error = "Playback stopped during " + juce::String(probe->measuring ? "measurement" : "warmup") + "; the probe will not resume it.";
        }
        if (probe->started > 0 && !probe->measuring && probe->error.isEmpty() && now - probe->started >= 120000) {
            impl->engine.getDeviceManager().restCPUStatistics();
            probe->measuring = true; probe->measuredAt = now; probe->nextEdit = now;
            probe->startXruns = state.xruns; probe->startProcessTicks = processTicks();
            probe->memory.add(sampleMemory(0));
        }
        if (probe->measuring && probe->error.isEmpty()) {
            probe->cpu.push_back(state.cpuUsage);
            probe->timerLag.push_back(juce::jmax(0.0,now - probe->previousTick - 100.0));
            probe->transportStayedPlaying &= state.playing;
            probe->identitiesPreserved &= impl->edit.get() == probe->edit && impl->bindings.size() == probe->plugins.size();
            for (size_t i = 0; i < juce::jmin(impl->bindings.size(),probe->plugins.size()); ++i)
                probe->identitiesPreserved &= impl->bindings[i].track->getVolumePlugin() == probe->plugins[i];
            if (now >= probe->nextEdit) {
                const auto& track = state.tracks[size_t(probe->editCount % 16)];
                const auto begin = juce::Time::getMillisecondCounterHiRes();
                auto result = execute("set_track_pan",object({{"track_id",track.id},{"pan",(probe->editCount / 16) % 2 ? -0.2 : 0.2}}),state.revision);
                probe->dispatch.push_back(juce::Time::getMillisecondCounterHiRes() - begin);
                if (result.failed()) probe->error = result.getErrorMessage();
                ++probe->editCount; probe->nextEdit = now + 5000;
                probe->memory.add(sampleMemory((now - probe->measuredAt)/1000.0));
            }
        }
        probe->previousTick = now;
        if(now>=probe->nextProgress || probe->error.isNotEmpty()){
            // Test-only heartbeat on the message thread, bounded to one small
            // file per minute. Audio callbacks never format or write JSON.
            const auto stats=impl->engine.getDeviceManager().getCPUStatistics();
            const auto measured=probe->measuring?(now-probe->measuredAt)/1000.0:0.0;
            const auto progress=object({{"phase",probe->started==0?"initializing":probe->measuring?"measuring":"warmup"},
                {"updated_at",juce::Time::getCurrentTime().toISO8601(true)},
                {"elapsed_seconds",(now-probe->initializingAt)/1000.0},{"warmup_seconds",probe->started>0 ? ((probe->measuring?probe->measuredAt:now)-probe->started)/1000.0 : 0.0},{"measured_seconds",measured},
                {"requested_measure_seconds",seconds},{"callback_count",juce::int64(stats.numRuns)},
                {"callback_mean_ms",stats.meanSeconds*1000.0},{"xrun_delta",state.xruns-probe->startXruns},
                {"edit_count",probe->editCount},{"last_dispatch_ms",probe->dispatch.empty()?0.0:probe->dispatch.back()},
                {"memory",sampleMemory(measured)},{"playing",state.playing},{"position_seconds",state.position},{"looping",state.looping},
                {"driver_type",deviceManager().getCurrentAudioDeviceType()},{"device",state.deviceName},{"sample_rate",state.sampleRate},{"buffer_size",state.bufferSize},
                {"initialization",probe->initialization},{"first_transport_stop",probe->firstStop},{"error",probe->error}});
            if(!reportFile.getSiblingFile("performance-progress.json").replaceWithText(juce::JSON::toString(progress)))
                impl->status="Could not write performance progress; measurement continues.";
            probe->nextProgress=now+60000.0;
        }
        if (probe->error.isNotEmpty() || (probe->measuring && now - probe->measuredAt >= seconds * 1000.0)) {
            const auto stats = impl->engine.getDeviceManager().getCPUStatistics();
            const auto elapsed = probe->measuring ? (now - probe->measuredAt)/1000.0 : 0.0;
            const auto quantile = [](std::vector<double> values,double q) {
                if (values.empty()) return 0.0;
                std::sort(values.begin(),values.end());
                return values[juce::jmin(values.size()-1,size_t(std::ceil(q * double(values.size())))-1)];
            };
            const auto mean = [](const std::vector<double>& values) { double sum=0; for (double x:values) sum+=x; return values.empty()?0.0:sum/double(values.size()); };
            const double budget = probe->sampleRate > 0 ? probe->bufferSize / probe->sampleRate : 0.0;
            const int xruns = state.xruns - probe->startXruns;
            const bool targetAvailable = state.sampleRate == 48000 && state.bufferSize == 256;
            const double dispatchP95 = quantile(probe->dispatch,0.95);
            const bool passed = probe->measuring && elapsed >= seconds && probe->transportStayedPlaying && probe->identitiesPreserved && probe->error.isEmpty()
                && stats.numRuns > 0 && xruns == 0 && stats.meanSeconds < budget * 0.8 && dispatchP95 < 50.0;
            const auto finalTicks = processTicks();
            probe->memory.add(sampleMemory(elapsed));
            const auto report = object({
                {"status",!passed?"failed":targetAvailable?"passed":"unsupported"},
                {"actual_device_status",passed?"passed":"failed"},
                {"target_configuration_status",targetAvailable?"available":"unsupported"},
                {"scope","16 independent synthetic WAV files; audio engine callback aggregate timings; 10 Hz sampled load and timer scheduling; control-thread pan edits every 5 s. No VST load or mouse/render latency measurement."},
                {"b01_acceptance_complete",false}, {"b01_missing","Callback P99.9 distribution and physical GUI input-to-paint latency are not measured."},
                {"requested_sample_rate",48000},{"requested_buffer_size",256},{"actual_sample_rate",state.sampleRate},{"actual_buffer_size",state.bufferSize},
                {"device",state.deviceName},{"driver_type",deviceManager().getCurrentAudioDeviceType()},{"configuration_error",deviceConfigurationError},{"configuration_changed",deviceConfigurationChanged},
                {"requested_measure_seconds",seconds},{"initialization_seconds",((probe->started>0?probe->started:now)-probe->initializingAt)/1000.0},
                {"initialization",probe->initialization},{"first_transport_stop",probe->firstStop},
                {"warmup_seconds",probe->started>0 ? ((probe->measuring?probe->measuredAt:now)-probe->started)/1000.0 : 0.0},{"actual_measure_seconds",elapsed},
                {"tracks",16},{"channels_per_track",2},{"source_seconds_per_track",8},{"third_party_plugins",0},
                {"callback_budget_ms",budget*1000.0},{"callback_count",juce::int64(stats.numRuns)},
                {"callback_mean_ms",stats.meanSeconds*1000.0},{"callback_max_ms",stats.maximumSeconds*1000.0},
                {"callback_min_ms",stats.minimumSeconds*1000.0},{"callback_stddev_ms",std::sqrt(juce::jmax(0.0,stats.getVarianceSeconds()))*1000.0},
                {"callback_p99_9","unavailable"},{"xrun_delta",xruns},{"xrun_source","JUCE device native count plus host callback overruns"},
                {"sampled_device_cpu_mean",mean(probe->cpu)},{"sampled_device_cpu_max",quantile(probe->cpu,1.0)},
                {"process_cpu_one_core_percent",elapsed>0 && finalTicks>=probe->startProcessTicks?(finalTicks-probe->startProcessTicks)/100000.0/elapsed:0.0},
                {"message_timer_lag_p95_ms",quantile(probe->timerLag,0.95)},{"message_timer_lag_max_ms",quantile(probe->timerLag,1.0)},
                {"edit_dispatch_p95_ms",dispatchP95},{"edit_dispatch_max_ms",quantile(probe->dispatch,1.0)},{"edit_count",probe->editCount},
                {"transport_stayed_playing",probe->transportStayedPlaying},{"edit_and_plugin_identity_preserved",probe->identitiesPreserved},
                {"memory_samples",probe->memory},{"error",probe->error},
                {"operating_system",juce::SystemStats::getOperatingSystemName()},{"cpu_model",juce::SystemStats::getCpuModel()},
                {"logical_cpus",juce::SystemStats::getNumCpus()},{"physical_cpus",juce::SystemStats::getNumPhysicalCpus()},
                {"system_ram_mib",juce::SystemStats::getMemorySizeInMegabytes()},{"pointer_bits",int(sizeof(void*)*8)},
               #if JUCE_DEBUG
                {"build_configuration","Debug"},
               #else
                {"build_configuration","Release"},
               #endif
                {"started_at",probe->startedIso},{"finished_at",juce::Time::getCurrentTime().toISO8601(true)} });
            stop();
            if (!reportFile.replaceWithText(juce::JSON::toString(report))) impl->status = "Could not write performance report.";
            else impl->status = "Performance probe completed; inspect measured metrics and unavailable acceptance criteria.";
            return;
        }
        if (auto next = recur.lock()) juce::Timer::callAfterDelay(100,[next] { (*next)(); });
    };
    impl->status = "Performance probe: initializing audio device and playback graph before warmup.";
    juce::Timer::callAfterDelay(100,[callback] { (*callback)(); });
    return juce::Result::ok();
}
