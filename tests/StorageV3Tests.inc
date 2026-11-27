// Included inside namespace emusician by the integration runner.
// These exercise storage bytes/DTOs, not audio decoding or installed plugins.
juce::Result runStorageV3Tests(const juce::File& directory)
{
    int checks = 0;
    const auto check = [&](bool condition, const juce::String& description) {
        if (!condition) throw std::runtime_error(("Storage v3: " + description).toStdString());
        ++checks;
    };
    const auto okay = [&](const juce::Result& result, const juce::String& description) {
        check(result.wasOk(), description + ": " + result.getErrorMessage());
    };
    try {
        const auto workspace = directory.getChildFile("storage-v3-" + juce::Uuid().toString());
        okay(workspace.createDirectory(), "create independent workspace");
        // Storage preserves arbitrary bytes. Engine tests separately prove WAV/MP3 decoding.
        const auto source = workspace.getChildFile("storage-byte-fixture.wav");
        juce::MemoryBlock original(196608);
        auto* sourceBytes = static_cast<unsigned char*>(original.getData());
        for (std::size_t i = 0; i < original.getSize(); ++i) sourceBytes[i] = static_cast<unsigned char>((i * 31) & 255);
        check(source.replaceWithData(original.getData(), original.getSize()), "write owned byte fixture");

        storage::StoredProject state;
        state.projectId = "storage_v3_project"; state.revision = 12;
        state.bpm = 120; state.numerator = 7; state.denominator = 8;
        state.looping = true; state.loopStart = 1; state.loopEnd = 9;
        state.assets.push_back({ "asset_a", source });
        storage::StoredTrack audio;
        audio.id = "audio_track"; audio.name = "Audio"; audio.pan = -0.3f;
        audio.clips.push_back({ "audio_a", "asset_a", 0.0, 0.0, 2.0 });
        audio.clips.push_back({ "audio_b", "asset_a", 4.0, 0.25, 1.0 });
        audio.clips[0].fadeIn = 0.1; audio.clips[0].fadeOut = 0.2;
        storage::StoredTrack midi;
        midi.id = "midi_track"; midi.name = "MIDI"; midi.kind = "instrument";
        storage::StoredClip phrase;
        phrase.id = "midi_clip"; phrase.kind = "midi"; phrase.startBeats = 8; phrase.lengthBeats = 8;
        phrase.notes.push_back({ "note_a", 60, 0.0, 1.5, 96, 2 });
        phrase.notes.push_back({ "note_b", 64, 2.0, 0.5, 72, 2 });
        midi.clips.push_back(phrase);
        storage::StoredPlugin instrument;
        instrument.id = "instrument_a"; instrument.format = "VST3";
        instrument.identifier = "C:/Missing/Preserved.vst3"; instrument.uniqueId = -123;
        instrument.deprecatedUniqueId = 456; instrument.name = "Preserved instrument";
        instrument.manufacturer = "Storage test"; instrument.version = "1.2.3";
        instrument.role = "instrument"; instrument.enabled = false;
        const unsigned char opaque[] { 0, 255, 17, 93, 0, 64, 128, 2 };
        instrument.state.replaceAll(opaque, sizeof(opaque));
        midi.plugins.push_back(instrument);
        storage::StoredPlugin master = instrument;
        master.id = "master_effect"; master.format = "VST"; master.role = "effect";
        master.state.reset(); master.enabled = true;
        state.masterPlugins.push_back(master);
        state.tracks = { audio, midi };
        okay(storage::validate(state), "validate new schema4 DTO without plugin binaries");

        // The public validator is pure: a missing audio path is left to file preparation.
        auto structuralOnly = state;
        structuralOnly.assets[0].source = workspace.getChildFile("not-created.wav");
        okay(storage::validate(structuralOnly), "pure DTO validation does not read audio files");
        const auto target = workspace.getChildFile("Roundtrip.emproj");
        storage::StoredProject archived, reopened;
        double lastProgress = -1;
        storage::IOOptions observed;
        observed.progress = [&](double fraction, const juce::String&) {
            if (fraction >= lastProgress) lastProgress = fraction;
        };
        okay(storage::save(target, state, archived, observed), "save schema4 with state binaries");
        check(lastProgress == 1.0, "successful save reports completion");
        check(archived.assets.size() == 1, "shared audio archived once");
        juce::MemoryBlock copied;
        check(archived.assets[0].source.loadFileAsData(copied) && copied == original, "archive preserves audio bytes");
        check(archived.tracks[1].clips[0].timelineStart == 4 && archived.tracks[1].clips[0].duration == 4,
              "MIDI seconds derive from authoritative beats");
        okay(storage::load(target, reopened), "reopen schema4");
        check(reopened.schemaVersion == 4 && reopened.bpm == 120 && reopened.numerator == 7 && reopened.denominator == 8,
              "tempo and signature roundtrip");
        check(reopened.loopStart == 1 && reopened.loopEnd == 9 && reopened.looping, "explicit loop roundtrip");
        check(reopened.tracks[0].pan == audio.pan && reopened.tracks[0].clips[0].fadeIn == 0.1
              && reopened.tracks[0].clips[0].fadeOut == 0.2, "pan and fades roundtrip");
        const auto& restoredNote = reopened.tracks[1].clips[0].notes[1];
        check(restoredNote.id == "note_b" && restoredNote.pitch == 64 && restoredNote.startBeats == 2.0
              && restoredNote.lengthBeats == 0.5 && restoredNote.velocity == 72 && restoredNote.channel == 2,
              "stable MIDI notes roundtrip");
        const auto& restoredPlugin = reopened.tracks[1].plugins[0];
        check(restoredPlugin.state == instrument.state && restoredPlugin.identifier == instrument.identifier
              && restoredPlugin.uniqueId == -123 && restoredPlugin.deprecatedUniqueId == 456
              && restoredPlugin.role == "instrument" && !restoredPlugin.enabled,
              "missing plugin identity and opaque state retained");
        check(reopened.masterPlugins[0].state.isEmpty() && reopened.masterPlugins[0].format == "VST",
              "empty VST2 master state retained");

        // Native instruments store only stable sample IDs. Audio clip, sampler
        // and several drum pads may all reference the same bundled audio.
        {
            auto nativeState = state;
            auto& native = nativeState.tracks[1].plugins[0];
            native.format = "E-musician"; native.identifier = "native.sampler";
            native.name = "Sampler"; native.role = "instrument";
            const auto setState = [](storage::StoredPlugin& plugin, const juce::String& json) {
                plugin.state.replaceAll(json.toRawUTF8(), json.getNumBytesAsUTF8());
            };
            const juce::String samplerJson = R"({"version":1,"type":"sampler","root_note":60,"start":0.0,"end":1.0,"pads":[{"asset_id":"asset_a","gain_db":0.0,"muted":false}]})";
            setState(native, samplerJson);
            const auto samplerBytes = native.state;
            {
                auto envelopeProject=nativeState;
                const auto withEnvelope=samplerJson.replace("\"muted\":false", "\"muted\":false,\"attack_ms\":100,\"release_ms\":400,\"one_shot\":true");
                setState(envelopeProject.tracks[1].plugins[0],withEnvelope);
                okay(storage::validate(envelopeProject),"optional sample envelope fields are valid");
                for(const auto& invalid:{withEnvelope.replace("\"attack_ms\":100","\"attack_ms\":0"),withEnvelope.replace("\"release_ms\":400","\"release_ms\":5001"),withEnvelope.replace("\"one_shot\":true","\"one_shot\":1")}) {
                    setState(envelopeProject.tracks[1].plugins[0],invalid);
                    check(storage::validate(envelopeProject).failed(),"invalid sample envelope/mode rejected by archive validation");
                }
            }
            const auto extraSource = workspace.getChildFile("native-extra.wav");
            check(extraSource.replaceWithData(original.getData(), original.getSize()), "write second native sample");
            nativeState.assets.push_back({"native_extra", extraSource});
            storage::StoredTrack drum; drum.id = "drum_track"; drum.name = "Drums"; drum.kind = "instrument";
            storage::StoredPlugin rack; rack.id = "native_rack"; rack.format = "E-musician";
            rack.identifier = "native.drum_rack"; rack.name = "Drum Rack"; rack.role = "instrument";
            juce::String pads;
            for (int i = 0; i < 16; ++i) {
                if (i) pads += ",";
                const auto id = i == 0 || i == 1 ? "asset_a" : i == 2 ? "native_extra" : "";
                pads += "{\"asset_id\":\"" + juce::String(id) + "\",\"gain_db\":-3.0,\"muted\":false}";
            }
            setState(rack, "{\"version\":1,\"type\":\"drum_rack\",\"root_note\":60,\"start\":0.0,\"end\":1.0,\"pads\":[" + pads + "]}");
            drum.plugins.push_back(rack); nativeState.tracks.push_back(drum);
            okay(storage::validate(nativeState), "native sample references share audio clip asset and support repeated pad IDs");
            std::vector<juce::String> refs;
            okay(storage::nativePluginAssetIds(rack, refs), "extract verified native references");
            check(refs.size() == 3 && refs[0] == "asset_a" && refs[1] == "asset_a" && refs[2] == "native_extra", "native reference extraction preserves pad order and repeats");
            const auto nativeTarget = workspace.getChildFile("native-project.emproj");
            storage::StoredProject nativeArchived, nativeLoaded, nativeCopy;
            okay(storage::save(nativeTarget, nativeState, nativeArchived), "save native sampler and rack sample assets");
            check(nativeArchived.assets.size() == 2 && nativeArchived.assets[1].source != extraSource
                  && nativeArchived.assets[1].source.existsAsFile(), "sample-only asset archived into bundle");
            okay(storage::load(nativeTarget, nativeLoaded), "reopen native instrument state and samples");
            check(nativeLoaded.tracks[1].plugins[0].state == samplerBytes
                  && nativeLoaded.tracks.back().plugins[0].state == rack.state, "native states round trip without embedding absolute paths");
            const auto nativeCopyTarget = workspace.getChildFile("native-save-as.emproj");
            okay(storage::save(nativeCopyTarget, nativeLoaded, nativeCopy), "save as relocates native sample assets");
            check(nativeCopy.assets.size() == 2 && nativeCopy.assets[1].source != nativeLoaded.assets[1].source
                  && nativeCopy.assets[1].source.existsAsFile(), "save as provides independent native sample copy");
            storage::IOOptions verifiedSave;
            const auto originalHash = juce::SHA256(original).toHexString();
            verifiedSave.expectedAssetHashes = {{"asset_a", originalHash}, {"native_extra", originalHash}};
            storage::StoredProject verifiedArchive;
            okay(storage::save(nativeTarget, nativeState, verifiedArchive, verifiedSave), "matching decoded sample hashes allow save");
            juce::MemoryBlock verifiedManifest;
            check(nativeTarget.loadFileAsData(verifiedManifest), "capture verified native manifest");
            auto changedExtra = original; static_cast<unsigned char*>(changedExtra.getData())[13] ^= 1;
            check(extraSource.replaceWithData(changedExtra.getData(), changedExtra.getSize()), "modify native source after decode");
            storage::StoredProject unchangedOutput; unchangedOutput.projectId = "unchanged";
            check(storage::save(nativeTarget, nativeState, unchangedOutput, verifiedSave).failed()
                  && unchangedOutput.projectId == "unchanged", "hash mismatch rejects copied sample before commit");
            juce::MemoryBlock afterMismatch;
            check(nativeTarget.loadFileAsData(afterMismatch) && afterMismatch == verifiedManifest, "hash mismatch preserves old project manifest");
            check(extraSource.replaceWithData(original.getData(), original.getSize()), "restore native source");
            auto unknownHash = verifiedSave; unknownHash.expectedAssetHashes["unknown_asset"] = originalHash;
            check(storage::save(nativeTarget, nativeState, unchangedOutput, unknownHash).failed(), "unknown expected asset hash rejected");
            auto invalidHash = verifiedSave; invalidHash.expectedAssetHashes["native_extra"] = "invalid";
            check(storage::save(nativeTarget, nativeState, unchangedOutput, invalidHash).failed(), "invalid expected hash rejected");
            // Change a reused archive after the reuse decision, while restoring
            // size and mtime. Only the destination content hash detects this.
            const auto reusedSample = verifiedArchive.assets[1].source;
            const auto reusedTimestamp = reusedSample.getLastModificationTime();
            bool archiveTampered = false, archiveWrite = false;
            auto tamper = verifiedSave;
            tamper.progress = [&](double, const juce::String& stage) {
                if (!archiveTampered && stage == "Writing project manifest") {
                    archiveTampered = true;
                    archiveWrite = reusedSample.replaceWithData(changedExtra.getData(), changedExtra.getSize());
                    archiveWrite = reusedSample.setLastModificationTime(reusedTimestamp) && archiveWrite;
                }
            };
            const auto archiveMismatch = storage::save(nativeTarget, nativeState, unchangedOutput, tamper);
            check(reusedSample.replaceWithData(original.getData(), original.getSize()), "restore tampered owned sample archive");
            check(archiveTampered && archiveWrite && archiveMismatch.failed()
                  && archiveMismatch.getErrorMessage().contains("changed since it was loaded"),
                  "hash mismatch detects changed reused archive even with restored metadata");
            juce::MemoryBlock afterArchiveMismatch;
            check(nativeTarget.loadFileAsData(afterArchiveMismatch) && afterArchiveMismatch == verifiedManifest,
                  "changed reused archive does not replace old manifest");
            auto missing = nativeState; missing.assets.pop_back();
            check(storage::validate(missing).failed(), "unknown native asset reference rejects project");
            auto badState = nativeState; setState(badState.tracks[1].plugins[0], samplerJson.replace("asset_a", "../bad"));
            check(storage::validate(badState).failed(), "native asset IDs cannot contain path traversal");
            setState(badState.tracks[1].plugins[0], samplerJson.replace("\"end\":1.0", "\"end\":0.0"));
            check(storage::validate(badState).failed(), "native invalid excerpt rejects project");
            setState(badState.tracks[1].plugins[0], samplerJson.replace("\"version\":1", "\"version\":3"));
            check(storage::validate(badState).failed(), "unknown native state version is rejected");
            setState(badState.tracks[1].plugins[0], samplerJson.replace("\"version\":1", "\"version\":1,\"version\":1"));
            check(storage::validate(badState).failed(), "duplicate native state JSON keys are rejected");
        }

        juce::MemoryBlock manifestBytes;
        check(target.loadFileAsData(manifestBytes), "capture canonical manifest bytes");
        const auto parsed = juce::JSON::parse(manifestBytes.toString());
        const auto pluginObject = parsed.getDynamicObject()->getProperty("tracks").getArray()->getReference(1)
            .getDynamicObject()->getProperty("plugins").getArray()->getReference(0);
        const auto stateFile = target.getParentDirectory().getChildFile(pluginObject.getDynamicObject()->getProperty("state_file").toString());
        juce::MemoryBlock damaged = instrument.state;
        static_cast<unsigned char*>(damaged.getData())[0] ^= 1;
        check(stateFile.replaceWithData(damaged.getData(), damaged.getSize()), "damage only owned state fixture");
        storage::StoredProject untouched;
        untouched.projectId = "untouched";
        check(storage::load(target, untouched).failed() && untouched.projectId == "untouched", "bad state hash rejects without output mutation");
        check(stateFile.replaceWithData(instrument.state.getData(), instrument.state.getSize()), "restore state fixture bytes");

        const auto rejectMutation = [&](const std::function<void(juce::DynamicObject&)>& mutate, const juce::String& label) {
            auto json = juce::JSON::parse(manifestBytes.toString());
            mutate(*json.getDynamicObject());
            check(target.replaceWithText(juce::JSON::toString(json, true)), "write " + label);
            untouched.projectId = "untouched";
            check(storage::load(target, untouched).failed() && untouched.projectId == "untouched", label + " preserves output");
            check(target.replaceWithData(manifestBytes.getData(), manifestBytes.getSize()), "restore exact manifest");
        };
        rejectMutation([](auto& root) { root.setProperty("bpm", 301); }, "out-of-range tempo");
        rejectMutation([](auto& root) { root.setProperty("schema", 5); }, "future schema");
        rejectMutation([](auto& root) {
            auto* clip = root.getProperty("tracks").getArray()->getReference(1).getDynamicObject()
                ->getProperty("clips").getArray()->getReference(0).getDynamicObject();
            clip->setProperty("duration", 5.0);
        }, "MIDI seconds/beat disagreement");
        rejectMutation([](auto& root) {
            auto* plugin = root.getProperty("tracks").getArray()->getReference(1).getDynamicObject()
                ->getProperty("plugins").getArray()->getReference(0).getDynamicObject();
            plugin->setProperty("state_file", "../outside.bin");
        }, "escaped plugin state path");
        rejectMutation([](auto& root) {
            auto* plugin = root.getProperty("tracks").getArray()->getReference(1).getDynamicObject()
                ->getProperty("plugins").getArray()->getReference(0).getDynamicObject();
            plugin->setProperty("state_bytes", static_cast<juce::int64>(storage::maximumPluginStateBytes + 1));
        }, "oversized plugin state metadata");

        const auto rejects = [&](const std::function<void(storage::StoredProject&)>& mutate, const juce::String& label) {
            auto invalid = state;
            mutate(invalid);
            check(storage::validate(invalid).failed(), label);
        };
        rejects([](auto& p) { p.tracks[1].clips[0].notes[1].channel = 3; }, "mixed channel clip rejected");
        rejects([](auto& p) { p.tracks[1].clips[0].notes[1].id = "note_a"; }, "duplicate note identity rejected");
        rejects([](auto& p) { p.tracks[1].clips[0].notes[0].lengthBeats = 9; }, "out-of-clip note rejected");
        rejects([](auto& p) { p.tracks[1].clips[0].notes[0].velocity = 0; }, "zero note velocity rejected");
        rejects([](auto& p) { p.tracks[0].clips[0].fadeOut = 2; }, "overlapping fades rejected");
        rejects([](auto& p) { p.masterPlugins[0].id = "instrument_a"; }, "duplicate plugin identity rejected");
        rejects([](auto& p) { p.masterPlugins[0].role = "instrument"; }, "master instrument rejected");
        rejects([](auto& p) { p.loopEnd = p.loopStart; }, "empty explicit loop rejected");
        rejects([](auto& p) { p.tracks[1].clips[0].lengthBeats = std::numeric_limits<double>::infinity(); }, "nonfinite MIDI range rejected");
        rejects([](auto& p) { p.tracks[1].clips[0].notes.resize(storage::maximumNotes + 1); }, "note object bound enforced");

        bool cancelCopy = false;
        storage::IOOptions cancelledSave;
        cancelledSave.cancelled = [&] { return cancelCopy; };
        cancelledSave.progress = [&](double fraction, const juce::String&) { if (fraction > 0.1) cancelCopy = true; };
        untouched.projectId = "untouched";
        check(storage::save(target, state, untouched, cancelledSave).failed() && untouched.projectId == "untouched", "cancel during copy preserves output DTO");
        juce::MemoryBlock afterCancel;
        check(target.loadFileAsData(afterCancel) && afterCancel == manifestBytes, "cancelled save preserves old manifest bytes");
        storage::IOOptions cancelledLoad;
        cancelledLoad.cancelled = [] { return true; };
        check(storage::load(target, untouched, cancelledLoad).failed() && untouched.projectId == "untouched", "cancelled load preserves output DTO");

        // Build an independent schema2 manifest, using its original asset filename convention.
        auto legacy = std::make_unique<juce::DynamicObject>();
        legacy->setProperty("schema", 2); legacy->setProperty("project_id", state.projectId);
        legacy->setProperty("revision", 8); legacy->setProperty("master_gain_db", -6.0); legacy->setProperty("looping", false);
        legacy->setProperty("assets", parsed.getDynamicObject()->getProperty("assets"));
        auto legacyTrack = std::make_unique<juce::DynamicObject>();
        legacyTrack->setProperty("id", audio.id); legacyTrack->setProperty("name", audio.name);
        legacyTrack->setProperty("gain_db", 0.0); legacyTrack->setProperty("muted", false); legacyTrack->setProperty("solo", false);
        auto legacyClip = std::make_unique<juce::DynamicObject>();
        legacyClip->setProperty("id", "legacy_clip"); legacyClip->setProperty("asset_id", "asset_a");
        legacyClip->setProperty("timeline_start", 3.0); legacyClip->setProperty("source_offset", 0.0); legacyClip->setProperty("duration", 2.0);
        legacyTrack->setProperty("clips", juce::var(juce::Array<juce::var> { juce::var(legacyClip.release()) }));
        legacy->setProperty("tracks", juce::var(juce::Array<juce::var> { juce::var(legacyTrack.release()) }));
        const auto legacyText = juce::JSON::toString(juce::var(legacy.release()), true) + "\n";
        check(target.replaceWithData(legacyText.toRawUTF8(), legacyText.getNumBytesAsUTF8()), "write exact schema2 fixture");
        juce::MemoryBlock legacyBytes;
        check(target.loadFileAsData(legacyBytes), "read schema2 bytes");
        storage::StoredProject migrated;
        okay(storage::load(target, migrated), "load schema2 read-only");
        check(migrated.schemaVersion == 2 && migrated.bpm == 120 && migrated.tracks[0].kind == "audio"
              && migrated.tracks[0].clips[0].timelineStart == 3, "schema2 defaults and position retained");
        // JUCE loadFileAsData appends to its destination MemoryBlock. Use a
        // fresh capture for each exact-byte comparison instead of reusing the
        // block that already contains the earlier schema4 manifest.
        juce::MemoryBlock afterLegacyOpen;
        check(target.loadFileAsData(afterLegacyOpen) && afterLegacyOpen == legacyBytes, "legacy open leaves manifest unchanged");
        migrated.schemaVersion = 4;
        okay(storage::save(target, migrated, archived), "upgrade schema2 explicitly");
        juce::Array<juce::File> backups;
        workspace.findChildFiles(backups, juce::File::findFiles, false, "Roundtrip.emproj.schema2-*.bak");
        check(backups.size() == 1, "one schema2 recovery backup created");
        juce::MemoryBlock backedUp;
        check(backups[0].loadFileAsData(backedUp) && backedUp == legacyBytes, "schema2 backup exact bytes");
        okay(storage::load(target, reopened), "reopen upgraded schema4");
        check(reopened.schemaVersion == 4 && reopened.tracks[0].clips[0].id == "legacy_clip", "legacy clip identity survives upgrade");
        juce::MemoryBlock sourceAfter;
        check(source.loadFileAsData(sourceAfter) && sourceAfter == original, "owned source unchanged by every save");

        // A repeated save may write a small manifest/plugin blob, but must not
        // allocate another complete copy of unchanged audio.
        const auto incremental = workspace.getChildFile("Incremental.emproj");
        storage::StoredProject first, second;
        juce::int64 written = 0, reused = 0;
        storage::IOOptions metrics;
        metrics.transferred = [&](auto w, auto r) { written = w; reused = r; };
        okay(storage::save(incremental, state, first, metrics), "initial incremental save");
        check(written >= juce::int64(original.getSize()) && reused == 0, "first save reports copied bytes");
        written = reused = 0;
        okay(storage::save(incremental, state, second, metrics), "same external source byte comparison reuse");
        check(first.assets[0].source == second.assets[0].source && reused == juce::int64(original.getSize())
              && written < juce::int64(original.getSize()), "unchanged external source does not duplicate audio");
        written = reused = 0;
        okay(storage::save(incremental, second, first, metrics), "already archived source direct reuse");
        check(first.assets[0].source == second.assets[0].source && reused == juce::int64(original.getSize()), "archive fast path retains media identity");
        const auto copyTarget = workspace.getChildFile("SaveAs.emproj");
        written = reused = 0;
        okay(storage::save(copyTarget, first, second, metrics), "Save As creates a self-contained bundle");
        check(first.assets[0].source != second.assets[0].source && reused == 0
              && second.assets[0].source.isAChildOf(workspace.getChildFile("SaveAs.assets")), "Save As never refers to previous bundle");
        auto changedSource = original;
        static_cast<unsigned char*>(changedSource.getData())[0] ^= 1;
        check(source.replaceWithData(changedSource.getData(), changedSource.getSize()), "change same-size owned source");
        written = reused = 0;
        okay(storage::save(incremental, state, second, metrics), "changed source creates new generation");
        check(second.assets[0].source != first.assets[0].source && reused == 0, "same-size byte change cannot reuse stale archive");
        check(source.replaceWithData(original.getData(), original.getSize()), "restore owned source");
        juce::MemoryBlock beforeConflict;
        check(incremental.loadFileAsData(beforeConflict), "capture target before conflict");
        bool modifiedTarget = false, wroteExternalTarget = false;
        auto externalBytes = beforeConflict;
        const char externalSuffix = ' ';
        externalBytes.append(&externalSuffix, 1);
        storage::IOOptions externalChange;
        externalChange.progress = [&](double, const juce::String& stage) {
            if (!modifiedTarget && stage == "Writing project manifest") {
                modifiedTarget = true;
                // The transaction contract is byte-for-byte. JUCE's default
                // replaceWithText converts LF to CRLF, so construct/write the
                // exact competing bytes rather than comparing normalized text.
                wroteExternalTarget = incremental.replaceWithData(externalBytes.getData(), externalBytes.getSize());
            }
        };
        untouched.projectId = "untouched";
        const auto conflictResult = storage::save(incremental, state, untouched, externalChange);
        check(modifiedTarget && wroteExternalTarget, "concurrent edit fixture wrote the expected external bytes");
        check(conflictResult.failed() && conflictResult.getErrorMessage().contains("existing project changed") && untouched.projectId == "untouched",
              "concurrent manifest change rejects commit");
        juce::MemoryBlock afterConflict;
        check(incremental.loadFileAsData(afterConflict) && afterConflict == externalBytes, "external manifest bytes survive failed save");
        check(incremental.replaceWithData(beforeConflict.getData(), beforeConflict.getSize()), "restore owned target");
        const auto referenced = second.assets[0].source;
        const auto beforeSize = referenced.getSize();
        bool changedArchive = false;
        storage::IOOptions archiveChange;
        archiveChange.progress = [&](double, const juce::String& stage) {
            if (!changedArchive && stage == "Writing project manifest") {
                changedArchive = true;
                juce::FileOutputStream append(referenced); append.writeByte(1); append.flush();
            }
        };
        check(storage::save(incremental, second, untouched, archiveChange).failed(), "reused media mutation rejects manifest switch");
        juce::MemoryBlock afterArchiveConflict;
        check(incremental.loadFileAsData(afterArchiveConflict) && afterArchiveConflict == beforeConflict,
              "changed reused media leaves prior manifest bytes unchanged");
        check(referenced.getSize() == beforeSize + 1, "save cleanup leaves reused files untouched");
        check(referenced.replaceWithData(changedSource.getData(), changedSource.getSize()), "restore owned archive after conflict fixture");

        bool cancelReuse = false;
        storage::IOOptions cancelReused;
        cancelReused.cancelled = [&] { return cancelReuse; };
        cancelReused.progress = [&](double, const juce::String& stage) { if (stage.startsWith("Reusing audio")) cancelReuse = true; };
        check(storage::save(incremental, second, untouched, cancelReused).failed(), "cancel after reuse before manifest commit");
        juce::MemoryBlock afterReuseCancel;
        check(incremental.loadFileAsData(afterReuseCancel) && afterReuseCancel == beforeConflict && referenced.existsAsFile(),
              "cancelled reuse retains manifest and old media");

        auto production = state;
        storage::StoredTrack bus; bus.id = "bus_a"; bus.name = "Bus"; bus.kind = "bus";
        production.tracks.push_back(bus);
        production.tracks[0].inputDeviceId = "test_input_device";
        production.tracks[0].outputTargetId = "bus_a";
        production.tracks[1].sends.push_back({"send_a", "bus_a", -9.0f, true, false});
        storage::StoredAutomationLane lane; lane.id = "gain_lane"; lane.target = "track_gain";
        lane.points = {{"gain_p1", 0.0, 0.2f, -0.5f}, {"gain_p2", 5.0, 0.8f, 0.5f}};
        production.tracks[0].automation.push_back(lane);
        lane.id = "plugin_lane"; lane.target = "plugin_parameter"; lane.pluginId = "instrument_a"; lane.parameterId = "stable_parameter";
        lane.points = {{"plugin_p1", 0.0, 0.3f, 0.0f}};
        production.tracks[1].automation.push_back(lane);
        lane.id = "master_lane"; lane.target = "master_gain"; lane.pluginId = {}; lane.parameterId = {};
        lane.points = {{"master_p1", 1.0, 0.7f, 0.0f}}; production.masterAutomation.push_back(lane);
        production.tracks[1].clips[0].controllers = {{"cc_a", 1.0, 64, 127 << 7, 0},
            {"bend_a", 2.0, 0x1005, 8193, 0}, {"pressure_a", 3.0, 0x1004, 42 << 7, 64}};
        const auto productionTarget = workspace.getChildFile("Production.emproj");
        okay(storage::save(productionTarget, production, archived), "save schema4 production graph");
        okay(storage::load(productionTarget, reopened), "load schema4 production graph");
        check(reopened.tracks[2].kind == "bus" && reopened.tracks[0].outputTargetId == "bus_a"
              && reopened.tracks[0].inputDeviceId == "test_input_device", "bus, output and input identity roundtrip");
        check(reopened.tracks[1].sends[0].preFader && !reopened.tracks[1].sends[0].enabled
              && reopened.tracks[1].sends[0].gainDb == -9, "pre/post and disabled send state roundtrip");
        check(reopened.tracks[0].automation[0].points[1].curve == 0.5f
              && reopened.tracks[1].automation[0].parameterId == "stable_parameter"
              && reopened.masterAutomation[0].target == "master_gain", "curve and missing-plugin automation roundtrip");
        check(reopened.tracks[1].clips[0].controllers.size() == 3
              && reopened.tracks[1].clips[0].controllers[1].value == 8193
              && reopened.tracks[1].clips[0].controllers[2].metadata == 64, "MIDI controller values and metadata roundtrip");
        const auto rejectsProduction = [&](const std::function<void(storage::StoredProject&)>& mutate, const juce::String& label) {
            auto invalid = production; mutate(invalid); check(storage::validate(invalid).failed(), label);
        };
        rejectsProduction([](auto& p) { p.tracks[2].outputTargetId = "bus_a"; }, "bus self-loop rejected");
        rejectsProduction([](auto& p) { p.tracks[1].sends[0].targetTrackId = "audio_track"; }, "send to nonbus rejected");
        rejectsProduction([](auto& p) { auto send = p.tracks[1].sends[0]; send.id = "send_duplicate_target"; p.tracks[1].sends.push_back(send); }, "duplicate send target rejected");
        rejectsProduction([](auto& p) { p.tracks[0].automation[0].points[1].timeSeconds = 0; }, "duplicate point times rejected");
        rejectsProduction([](auto& p) { p.tracks[1].automation[0].pluginId = "master_effect"; }, "foreign plugin automation rejected");
        rejectsProduction([](auto& p) { p.masterAutomation[0].target = "track_gain"; }, "invalid master target rejected");
        rejectsProduction([](auto& p) { p.tracks[1].clips[0].controllers[0].value = 16384; }, "out-of-range controller value rejected");
        rejectsProduction([](auto& p) { p.tracks[1].clips[0].controllers[0].type = 0x1006; }, "unsupported controller type rejected");
        rejectsProduction([](auto& p) { p.tracks[1].clips[0].controllers[0].beats = 9; }, "out-of-clip controller rejected");

        // The previous generation is read-only on open and copied exactly once
        // before an explicit schema3 -> schema4 save.
        auto oldThree = juce::JSON::parse(manifestBytes.toString());
        oldThree.getDynamicObject()->setProperty("schema", 3);
        const auto oldThreeText = juce::JSON::toString(oldThree, true) + "\n";
        const juce::MemoryBlock oldThreeBytes(oldThreeText.toRawUTF8(), oldThreeText.getNumBytesAsUTF8());
        check(target.replaceWithData(oldThreeBytes.getData(), oldThreeBytes.getSize()), "write exact schema3 migration fixture bytes");
        okay(storage::load(target, migrated), "open schema3 read-only");
        check(migrated.schemaVersion == 3 && migrated.tracks[0].outputTargetId == "master"
              && migrated.tracks[0].automation.empty(), "schema3 migration defaults");
        juce::MemoryBlock afterThreeOpen;
        check(target.loadFileAsData(afterThreeOpen) && afterThreeOpen == oldThreeBytes, "schema3 open does not write manifest");
        migrated.schemaVersion = 4;
        okay(storage::save(target, migrated, archived), "explicit schema3 upgrade");
        juce::Array<juce::File> threeBackups;
        workspace.findChildFiles(threeBackups, juce::File::findFiles, false, "Roundtrip.emproj.schema3-*.bak");
        juce::MemoryBlock threeBackupBytes;
        check(threeBackups.size() == 1 && threeBackups[0].loadFileAsData(threeBackupBytes) && threeBackupBytes == oldThreeBytes, "schema3 backup preserves exact old bytes");

        auto report = std::make_unique<juce::DynamicObject>();
        report->setProperty("status", "passed"); report->setProperty("checks_passed", checks);
        report->setProperty("scope", "schema4 DTO/binary persistence, incremental media, conflict/cancellation, routing/automation/controllers and schema2/3 migration; no plugin instantiation or audio decode claim");
        report->setProperty("workspace", workspace.getFullPathName());
        check(directory.getChildFile("storage-v3-report.json").replaceWithText(juce::JSON::toString(juce::var(report.release()))), "write storage report");
        return juce::Result::ok();
    } catch (const std::exception& error) {
        return juce::Result::fail(error.what());
    }
}
