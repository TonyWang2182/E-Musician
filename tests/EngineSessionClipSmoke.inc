// Included inside namespace emusician after EngineSession::Impl. All mutations
// and failure injections are confined to this invocation's unique test folder.
juce::Result EngineSession::runClipSmokeTest(const juce::File& directory)
{
    requireControlThread();
    int checks = 0;
    const auto check = [&](bool condition, const juce::String& message) {
        if (!condition) throw std::runtime_error(("Clip smoke: " + message).toStdString());
        ++checks;
    };
    const auto okay = [&](const juce::Result& result, const juce::String& context) {
        check(result.wasOk(), context + ": " + result.getErrorMessage());
    };
    try {
        const auto workspace = directory.getChildFile("clip-cases");
        check(!workspace.exists(), "clip workspace must be fresh");
        okay(workspace.createDirectory(), "create clip workspace");
        std::vector<juce::File> inputs;
        std::vector<juce::MemoryBlock> originalBytes;
        juce::File wav;
        for (const auto& track : snapshot().tracks) {
            const auto input = workspace.getChildFile("source-" + juce::String(int(inputs.size()))
                                                     + track.source.getFileExtension());
            check(track.source.copyFileTo(input), "copy test-owned source for clip edits");
            juce::MemoryBlock bytes;
            check(input.loadFileAsData(bytes), "read original source bytes");
            inputs.push_back(input); originalBytes.push_back(std::move(bytes));
            if (track.format == "WAV") wav = input;
        }
        check(inputs.size() == 3 && wav.existsAsFile(), "WAV, CBR and VBR inputs available from preceding project smoke");

        const auto render = [&](EngineSession& target, const juce::String& name, double seconds) {
            const auto output = workspace.getChildFile(name + ".wav");
            check(!output.exists(), "render output is fresh: " + name);
            juce::WavAudioFormat format;
            te::Renderer::Parameters params(*target.impl->edit);
            params.destFile = output; params.audioFormat = &format;
            params.sampleRateForAudio = 48000; params.blockSizeForAudio = 256;
            params.bitDepth = 24; params.canRenderInMono = false; params.useMasterPlugins = true;
            params.time = { te::TimePosition::fromSeconds(0), te::TimePosition::fromSeconds(seconds) };
            params.tracksToDo = te::toBitSet(te::getAllTracks(*target.impl->edit));
            {
                te::Edit::ScopedRenderStatus rendering(*target.impl->edit, true);
                te::Renderer::RenderTask task("Clip audio verification", params, nullptr, nullptr);
                while (task.runJob() == juce::ThreadPoolJob::jobNeedsRunningAgain) {}
                check(task.errorMessage.isEmpty(), "render " + name + ": " + task.errorMessage);
            }
            auto stream = output.createInputStream();
            check(stream != nullptr, "render output exists");
            std::unique_ptr<juce::AudioFormatReader> reader(format.createReaderFor(stream.release(), true));
            check(reader && reader->numChannels == 2 && reader->sampleRate == 48000
                  && std::abs(reader->lengthInSamples - juce::int64(std::llround(seconds * 48000))) <= 1,
                  "render sample format and length");
            juce::AudioBuffer<float> samples(2, int(reader->lengthInSamples));
            check(reader->read(&samples, 0, samples.getNumSamples(), 0, true, true), "decode rendered samples");
            return samples;
        };
        const auto compare = [&](const juce::AudioBuffer<float>& a, int startA,
                                 const juce::AudioBuffer<float>& b, int startB, int count) {
            check(startA >= 0 && startB >= 0 && count > 0 && startA + count <= a.getNumSamples()
                  && startB + count <= b.getNumSamples(), "sample comparison has valid bounds");
            double maximum = 0;
            for (int ch = 0; ch < 2; ++ch)
                for (int i = 0; i < count; ++i)
                    maximum = juce::jmax(maximum, std::abs(double(a.getSample(ch, startA + i)) - b.getSample(ch, startB + i)));
            return maximum;
        };
        const auto onlyClip = [&](const EngineSession& target) {
            const auto state = target.snapshot();
            check(state.tracks.size() == 1 && state.tracks.front().clips.size() == 1, "single clip state");
            return state.tracks.front().clips.front();
        };
        const auto unchanged = [&](EngineSession& target, const Snapshot& before,
                                   const juce::String& key, const juce::String& context) {
            const auto after = target.snapshot();
            check(contentKey(target.impl->capture()) == key && after.projectId == before.projectId
                  && after.revision == before.revision && after.dirty == before.dirty
                  && after.selectedTrackId == before.selectedTrackId && after.selectedClipId == before.selectedClipId
                  && after.canUndo == before.canUndo && after.canRedo == before.canRedo,
                  context + " preserves content, selection, revision and history availability");
        };

        juce::Array<juce::var> formatReports;
        double maximumMovedDifference = 0, maximumReopenedDifference = 0;
        for (std::size_t index = 0; index < inputs.size(); ++index) {
            EngineSession target;
            const auto prefix = "clip-" + juce::String(int(index));
            okay(target.importFile(inputs[index], target.snapshot().revision), "import movement source");
            const auto original = onlyClip(target);
            check(original.id.isNotEmpty() && original.assetId.isNotEmpty()
                  && original.timelineStart == 0 && original.sourceOffset == 0,
                  "import assigns clip/asset identities at timeline and source zero");
            const auto project = workspace.getChildFile(prefix + ".emproj");
            okay(target.saveProject(project, target.snapshot().revision), "save movement baseline");
            const auto baseline = render(target, prefix + "-baseline", 2);
            check(baseline.getRMSLevel(0, 12000, 72000) > 0.02f, "baseline is audible");
            const auto before = target.snapshot();
            const auto beforeKey = contentKey(target.impl->capture());
            okay(target.moveClip(original.id, 0, before.revision), "same start is an accepted no-op");
            unchanged(target, before, beforeKey, "no-op move");
            for (const double invalid : { -0.01, std::numeric_limits<double>::quiet_NaN(),
                                         std::numeric_limits<double>::infinity(), 172800.0 }) {
                check(target.moveClip(original.id, invalid, before.revision).failed(), "reject invalid move position");
                unchanged(target, before, beforeKey, "invalid move");
            }
            check(target.moveClip(original.id, 8, before.revision - 1).failed(), "reject stale move");
            unchanged(target, before, beforeKey, "stale move");
            check(target.moveClip("missing-clip", 8, before.revision).failed(), "reject missing clip");
            unchanged(target, before, beforeKey, "missing clip move");

            okay(target.moveClip(original.id, 8, before.revision), "move clip to eight seconds");
            const auto movedClip = onlyClip(target);
            check(movedClip.id == original.id && movedClip.assetId == original.assetId
                  && movedClip.timelineStart == 8 && movedClip.sourceOffset == original.sourceOffset
                  && std::abs(movedClip.duration - original.duration) < 1.0e-9,
                  "move preserves source range and stable identities");
            check(target.snapshot().revision == before.revision + 1 && target.snapshot().dirty
                  && target.snapshot().canUndo && !target.snapshot().playing
                  && std::abs(target.snapshot().duration - (8 + original.duration)) < 1.0e-9,
                  "move is one stopped edit and project length follows clip end");
            const auto moved = render(target, prefix + "-moved", 11);
            check(moved.getMagnitude(0, 0, 8 * 48000) < 0.000001f
                  && moved.getMagnitude(1, 0, 8 * 48000) < 0.000001f, "first eight seconds are silent");
            const auto movedDifference = compare(baseline, 512, moved, 8 * 48000 + 512, 96000 - 1024);
            check(movedDifference < 0.00002, "audio at eight seconds matches source-origin render");
            maximumMovedDifference = juce::jmax(maximumMovedDifference, movedDifference);
            okay(target.undo(target.snapshot().revision), "undo move once");
            check(onlyClip(target).timelineStart == 0 && !target.snapshot().dirty && target.snapshot().canRedo,
                  "one undo restores baseline start and saved cleanliness");
            const auto undone = render(target, prefix + "-undone", 2);
            check(compare(baseline, 0, undone, 0, 96000) < 0.000001, "undo restores original rendered audio");
            okay(target.redo(target.snapshot().revision), "redo move once");
            check(onlyClip(target).timelineStart == 8 && target.snapshot().dirty, "redo restores moved state");
            const auto redone = render(target, prefix + "-redone", 11);
            check(compare(moved, 0, redone, 0, 11 * 48000) < 0.000001, "redo restores moved rendered audio");
            okay(target.saveProject(project, target.snapshot().revision), "save moved clip");
            check(!target.snapshot().dirty, "saving moved state clears dirty");
            {
                EngineSession reopened;
                okay(reopened.openProject(project, reopened.snapshot().revision), "reopen moved clip in fresh session");
                const auto restored = onlyClip(reopened);
                check(restored.id == original.id && restored.assetId == original.assetId
                      && restored.timelineStart == 8 && restored.sourceOffset == 0
                      && !reopened.snapshot().dirty && !reopened.snapshot().canUndo,
                      "reopen preserves moved identity/range without persisting undo stack");
                const auto audio = render(reopened, prefix + "-reopened", 11);
                const auto error = compare(moved, 0, audio, 0, 11 * 48000);
                check(error < 0.000001, "fresh session preserves all rendered samples");
                maximumReopenedDifference = juce::jmax(maximumReopenedDifference, error);
            }
            auto item = std::make_unique<juce::DynamicObject>();
            item->setProperty("format", original.format);
            item->setProperty("sample_rate", original.sampleRate);
            item->setProperty("channels", original.channels);
            item->setProperty("moved_start_seconds", 8);
            item->setProperty("delayed_max_sample_difference", movedDifference);
            formatReports.add(juce::var(item.release()));
        }

        // Multiple clips reference one immutable asset; source offset is a source
        // coordinate, independent of where the clip is placed on the timeline.
        storage::StoredProject shared;
        shared.projectId = "shared-clip-project";
        shared.assets.push_back({ "shared-asset", wav });
        storage::StoredTrack lane;
        lane.id = "shared-track"; lane.name = "two excerpts";
        lane.clips.push_back({ "excerpt-a", "shared-asset", 1, 0.173, 0.4 });
        lane.clips.push_back({ "excerpt-b", "shared-asset", 2, 0.173, 0.4 });
        shared.tracks.push_back(lane);
        storage::StoredTrack empty;
        empty.id = "empty-track"; empty.name = "empty";
        shared.tracks.push_back(empty);
        const auto sharedFile = workspace.getChildFile("Shared.emproj");
        storage::StoredProject archived;
        okay(storage::save(sharedFile, shared, archived), "save shared asset clips and empty track");
        check(archived.assets.size() == 1 && archived.tracks.size() == 2 && archived.tracks[1].clips.empty(),
              "archive retains shared identity and empty track");
        juce::Array<juce::File> archivedFiles;
        archived.assets.front().source.getParentDirectory().findChildFiles(archivedFiles, juce::File::findFiles, false);
        check(archivedFiles.size() == 1, "shared asset is copied once per generation");
        EngineSession sharedSession;
        okay(sharedSession.openProject(sharedFile, sharedSession.snapshot().revision), "open multiple clips and empty track");
        auto sharedSnapshot = sharedSession.snapshot();
        check(sharedSnapshot.tracks.size() == 2 && sharedSnapshot.tracks[0].clips.size() == 2
              && sharedSnapshot.tracks[1].clips.empty() && std::abs(sharedSnapshot.duration - 2.4) < 1.0e-9,
              "snapshot represents multiple clips, empty track and latest clip end");
        const auto excerpts = render(sharedSession, "shared-excerpts", 3);
        check(excerpts.getMagnitude(0, 0, 48000) < 0.000001f
              && excerpts.getMagnitude(0, 70000, 24000) < 0.000001f,
              "shared excerpts preserve intervening timeline silence");
        check(compare(excerpts, 48000 + 512, excerpts, 96000 + 512, 19200 - 1024) < 0.000001,
              "same source excerpt sounds identical at two timeline positions");
        EngineSession untrimmed;
        okay(untrimmed.importFile(wav, untrimmed.snapshot().revision), "import offset comparison source");
        const auto sourceAudio = render(untrimmed, "shared-source", 2);
        check(compare(sourceAudio, 8304 + 512, excerpts, 48000 + 512, 19200 - 1024) < 0.00002,
              "source offset selects corresponding original audio samples");
        sharedSession.selectClip("excerpt-b");
        check(sharedSession.snapshot().selectedClipId == "excerpt-b"
              && sharedSession.snapshot().selectedTrackId == "shared-track", "selecting second clip selects its parent track");
        okay(sharedSession.moveClip("excerpt-b", 4, sharedSession.snapshot().revision), "move second shared clip independently");
        sharedSnapshot = sharedSession.snapshot();
        check(sharedSnapshot.tracks[0].clips[0].timelineStart == 1
              && sharedSnapshot.tracks[0].clips[1].timelineStart == 4
              && sharedSnapshot.tracks[0].clips[1].sourceOffset == 0.173,
              "moving one shared clip leaves peer and source offset unchanged");
        okay(sharedSession.undo(sharedSession.snapshot().revision), "undo second shared clip move");

        // Mutate only an owned manifest. Every rejected open must leave the
        // existing audible Edit, revision, selection and history untouched.
        juce::MemoryBlock validSharedBytes;
        check(sharedFile.loadFileAsData(validSharedBytes), "capture exact valid manifest bytes before failure injection");
        const auto validSharedJson = sharedFile.loadFileAsString();
        const auto sharedManifestUnchanged = [&]() {
            juce::MemoryBlock bytes;
            return sharedFile.loadFileAsData(bytes) && bytes == validSharedBytes;
        };
        const auto active = sharedSession.snapshot();
        const auto activeKey = contentKey(sharedSession.impl->capture());
        const auto corruptClip = [&](const juce::String& property, const juce::var& value, const juce::String& label) {
            auto json = juce::JSON::parse(validSharedJson);
            auto* clip = json.getDynamicObject()->getProperty("tracks").getArray()->getReference(0)
                             .getDynamicObject()->getProperty("clips").getArray()->getReference(0).getDynamicObject();
            clip->setProperty(property, value);
            check(sharedFile.replaceWithText(juce::JSON::toString(json)), "write malformed clip case: " + label);
            check(sharedSession.openProject(sharedFile, active.revision).failed(), "reject " + label);
            unchanged(sharedSession, active, activeKey, label);
        };
        corruptClip("asset_id", "missing-asset", "dangling asset reference");
        corruptClip("id", "excerpt-b", "duplicate clip identity");
        corruptClip("timeline_start", -0.1, "negative timeline start");
        corruptClip("timeline_start", 172800.0, "timeline beyond engine limit");
        corruptClip("timeline_start", "NaN", "non-numeric timeline start");
        corruptClip("duration", 0.0, "zero clip duration");
        corruptClip("duration", 1.0e-30, "positive duration that collapses at its timeline position");
        corruptClip("duration", 3.0, "clip range beyond actual audio source");
        corruptClip("source_offset", -0.1, "negative source offset");
        corruptClip("source_offset", 1.9, "offset plus duration beyond source");
        const auto revisionKey = validSharedJson.indexOf("\"revision\"");
        const auto revisionColon = validSharedJson.indexOf(revisionKey, ":");
        const auto revisionComma = validSharedJson.indexOf(revisionColon, ",");
        check(revisionKey >= 0 && revisionColon > revisionKey && revisionComma > revisionColon,
              "locate schema revision for overflow fixture");
        const auto overflowJson = validSharedJson.substring(0, revisionColon + 1)
                                + "18446744073709551617" + validSharedJson.substring(revisionComma);
        check(sharedFile.replaceWithText(overflowJson), "write overflowing JSON integer revision");
        check(sharedSession.openProject(sharedFile, active.revision).failed(), "reject overflowing integer before parser wraparound");
        unchanged(sharedSession, active, activeKey, "oversized JSON revision");
        // File::replaceWithText defaults to CRLF on this JUCE version, whereas
        // ProjectStorage writes LF. Restore bytes, without newline conversion.
        check(sharedFile.replaceWithData(validSharedBytes.getData(), validSharedBytes.getSize())
              && sharedManifestUnchanged(), "restore exact valid owned shared manifest bytes");
        auto invalidDto = shared;
        invalidDto.tracks[0].clips[0].timelineStart = std::numeric_limits<double>::quiet_NaN();
        storage::StoredProject untouchedOutput;
        untouchedOutput.projectId = "output-sentinel";
        check(storage::save(sharedFile, invalidDto, untouchedOutput).failed(), "save rejects non-finite DTO");
        check(untouchedOutput.projectId == "output-sentinel" && untouchedOutput.assets.empty()
              && sharedManifestUnchanged(), "failed save preserves output DTO and existing manifest bytes");
        invalidDto = shared;
        invalidDto.assets.push_back({ "unreferenced-asset", wav });
        check(storage::save(sharedFile, invalidDto, untouchedOutput).failed(), "reject unreferenced assets without silently dropping them");
        check(untouchedOutput.projectId == "output-sentinel" && untouchedOutput.assets.empty()
              && sharedManifestUnchanged(), "unreferenced asset failure preserves output and manifest bytes");
        for (const bool tooManyAssets : { false, true }) {
            auto oversized = shared;
            if (tooManyAssets)
                oversized.assets.resize(storage::maximumAssets + 1, shared.assets.front());
            else
                oversized.tracks[0].clips.resize(storage::maximumClips + 1, shared.tracks[0].clips.front());
            std::unique_ptr<te::Edit> candidate;
            std::vector<Impl::Binding> candidateBindings;
            check(sharedSession.impl->build(oversized, candidate, candidateBindings).failed()
                  && !candidate && candidateBindings.empty(), "control boundary rejects excessive objects before preparing an Edit");
            unchanged(sharedSession, active, activeKey, "oversized internal project candidate");
        }

        // Create schema 1 directly, independently of the schema 2 writer.
        const auto legacyDir = workspace.getChildFile("legacy-case");
        const auto legacyAssetDir = legacyDir.getChildFile("Legacy.assets/initial");
        okay(legacyAssetDir.createDirectory(), "create legacy asset directory");
        const auto legacyAsset = legacyAssetDir.getChildFile("legacy-track.wav");
        check(wav.copyFileTo(legacyAsset), "copy schema 1 source");
        const auto legacyFile = legacyDir.getChildFile("Legacy.emproj");
        const juce::String legacyJson = R"({"schema":1,"project_id":"legacy-project","revision":7,"master_gain_db":-6.0,"looping":true,"tracks":[{"id":"legacy-track","name":"legacy audio","source":"Legacy.assets/initial/legacy-track.wav","gain_db":-3.0,"muted":false,"solo":false}]})";
        check(legacyFile.replaceWithText(legacyJson), "write owned schema 1 manifest");
        EngineSession migrated;
        okay(migrated.openProject(legacyFile, migrated.snapshot().revision), "open schema 1 without saving");
        const auto legacyClip = onlyClip(migrated);
        check(legacyClip.timelineStart == 0 && legacyClip.sourceOffset == 0
              && std::abs(legacyClip.duration - 2) < 1.0e-9 && !migrated.snapshot().dirty
              && migrated.snapshot().looping && migrated.snapshot().tracks[0].id == "legacy-track"
              && std::abs(migrated.snapshot().tracks[0].gainDb + 3.0f) < 0.002f,
              "legacy migration restores complete source at zero and preserves settings");
        check(legacyFile.loadFileAsString() == legacyJson, "opening legacy project does not rewrite manifest");
        okay(migrated.openProject(legacyFile, migrated.snapshot().revision), "reopen schema 1 before saving");
        check(onlyClip(migrated).id == legacyClip.id && onlyClip(migrated).assetId == legacyClip.assetId,
              "legacy derived clip and asset identities are deterministic");
        okay(migrated.moveClip(legacyClip.id, 8, migrated.snapshot().revision), "edit migrated clip");
        const auto beforeFailedSave = migrated.snapshot();
        const auto beforeFailedSaveKey = contentKey(migrated.impl->capture());
        check(legacyFile.setReadOnly(true), "make owned legacy manifest read-only");
        const auto failedLegacySave = migrated.saveProject(legacyFile, migrated.snapshot().revision);
        const bool writableRestored = legacyFile.setReadOnly(false);
        check(writableRestored && failedLegacySave.failed(), "read-only legacy save fails and test restores permissions");
        check(legacyFile.loadFileAsString() == legacyJson, "failed legacy save preserves schema 1 bytes");
        unchanged(migrated, beforeFailedSave, beforeFailedSaveKey, "failed legacy save");
        okay(migrated.saveProject(legacyFile, migrated.snapshot().revision), "explicitly save migrated project as schema 4");
        check(int(juce::JSON::parse(legacyFile.loadFileAsString()).getDynamicObject()->getProperty("schema")) == 4,
              "explicit save writes schema 4");
        juce::Array<juce::File> backups;
        legacyDir.findChildFiles(backups, juce::File::findFiles, false, "Legacy.emproj.schema1-*.bak");
        check(!backups.isEmpty(), "legacy save retains at least one recovery manifest");
        for (const auto& backup : backups)
            check(backup.loadFileAsString() == legacyJson, "every legacy backup preserves exact schema 1 bytes");
        const auto recoveryDir = workspace.getChildFile("legacy-recovery");
        okay(recoveryDir.createDirectory(), "create recovery case");
        check(legacyDir.getChildFile("Legacy.assets").copyDirectoryTo(recoveryDir.getChildFile("Legacy.assets")),
              "copy retained asset generations for recovery");
        const auto recoveryFile = recoveryDir.getChildFile("Legacy.emproj");
        check(backups.getFirst().copyFileTo(recoveryFile), "restore backup under original manifest name");
        EngineSession recovered;
        okay(recovered.openProject(recoveryFile, recovered.snapshot().revision), "open recovered old project");
        check(onlyClip(recovered).timelineStart == 0 && onlyClip(recovered).id == legacyClip.id,
              "legacy backup plus retained assets restores original timeline");
        okay(migrated.openProject(legacyFile, migrated.snapshot().revision), "reopen saved migrated schema 4");
        check(onlyClip(migrated).timelineStart == 8 && onlyClip(migrated).id == legacyClip.id,
              "migrated schema 4 keeps moved position and stable identity");

        for (std::size_t index = 0; index < inputs.size(); ++index) {
            juce::MemoryBlock bytes;
            check(inputs[index].loadFileAsData(bytes) && bytes == originalBytes[index], "source bytes unchanged after editing and saving");
        }
        auto report = std::make_unique<juce::DynamicObject>();
        report->setProperty("status", "passed");
        report->setProperty("scope", "real Tracktion renders for WAV and both MP3 fixtures; move, undo/redo, schema 4 round trips, shared assets, schema 1 migration and recovery; no listening or realtime performance claim");
        report->setProperty("checks_passed", checks);
        report->setProperty("formats", juce::var(formatReports));
        report->setProperty("delayed_max_sample_difference", maximumMovedDifference);
        report->setProperty("fresh_session_max_sample_difference", maximumReopenedDifference);
        report->setProperty("silence_before_eight_seconds", true);
        report->setProperty("shared_asset_multiple_clips_and_source_offset", true);
        report->setProperty("invalid_edits_and_opens_preserve_active", true);
        report->setProperty("schema1_open_is_read_only", true);
        report->setProperty("schema1_backup_recovery", true);
        report->setProperty("original_audio_bytes_unchanged", true);
        check(directory.getChildFile("clip-report.json").replaceWithText(juce::JSON::toString(juce::var(report.release()))),
              "write clip smoke report");
        return juce::Result::ok();
    } catch (const std::exception& error) {
        return juce::Result::fail(error.what());
    }
}
