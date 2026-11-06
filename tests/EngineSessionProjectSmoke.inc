// Included inside namespace emusician after EngineSession::Impl; development-only entry point.
juce::Result EngineSession::runProjectSmokeTest(const juce::File& directory, const juce::File& fixtureDirectory)
{
    requireControlThread();
    struct ScopedAudioCache {
        juce::String previous=juce::SystemStats::getEnvironmentVariable("EMUSICIAN_AUDIO_CACHE_ROOT",{});
        explicit ScopedAudioCache(const juce::String& value){set(value);}
        ~ScopedAudioCache(){set(previous);}
        static void set(const juce::String& value){
#if JUCE_WINDOWS
            _putenv_s("EMUSICIAN_AUDIO_CACHE_ROOT",value.toRawUTF8());
#else
            if(value.isEmpty())unsetenv("EMUSICIAN_AUDIO_CACHE_ROOT");else setenv("EMUSICIAN_AUDIO_CACHE_ROOT",value.toRawUTF8(),1);
#endif
        }
    } scopedCache(directory.getChildFile("owned-audio-cache").getFullPathName());
    int checks = 0;
    const auto check = [&](bool condition, const juce::String& message) {
        if (!condition) throw std::runtime_error(("Project smoke: " + message).toStdString());
        ++checks;
    };
    const auto okay = [&](const juce::Result& result, const juce::String& context) {
        check(result.wasOk(), context + ": " + result.getErrorMessage());
    };
    try {
        okay(directory.createDirectory(), "create test directory");
        const auto ownedSources = directory.getChildFile("owned-project-sources");
        check(!ownedSources.exists(), "source fixture directory must be fresh");
        okay(ownedSources.createDirectory(), "create source fixture directory");
        const auto wav = ownedSources.getChildFile("source.wav");
        const auto cbr = ownedSources.getChildFile(juce::String::fromUTF8("测试 CBR.MP3"));
        const auto vbr = ownedSources.getChildFile("mono VBR.mp3");
        check(directory.getChildFile("generated-tone.wav").copyFileTo(wav), "copy owned WAV");
        check(fixtureDirectory.getChildFile("stereo-cbr-48000.mp3").copyFileTo(cbr), "copy CBR fixture to Unicode/uppercase path");
        check(fixtureDirectory.getChildFile("mono-vbr-44100.mp3").copyFileTo(vbr), "copy VBR fixture");
        ScopedAudioCache::set("relative-cache-is-invalid");audio::PreparedSource rejectedCache;
        const auto invalidCacheRoot=audio::prepareSource(cbr,rejectedCache);
        check(invalidCacheRoot.failed()&&invalidCacheRoot.getErrorMessage().contains("absolute")&&rejectedCache.playbackFile==juce::File(),"relative audio-cache root is rejected without fallback");
        ScopedAudioCache::set(directory.getChildFile("owned-audio-cache").getFullPathName());

        // This performs a real Tracktion render, not a reader-only or synthetic output check.
        const auto render = [&](EngineSession& target, const juce::String& name) {
            const auto output = directory.getChildFile(name + ".wav");
            check(!output.exists(), "render target must be fresh: " + name);
            juce::WavAudioFormat format;
            te::Renderer::Parameters params(*target.impl->edit);
            params.destFile = output;
            params.audioFormat = &format;
            params.sampleRateForAudio = 48000;
            params.blockSizeForAudio = 256;
            params.bitDepth = 24;
            params.canRenderInMono = false;
            params.useMasterPlugins = true;
            params.time = { te::TimePosition::fromSeconds(0), te::TimePosition::fromSeconds(2) };
            params.tracksToDo = te::toBitSet(te::getAllTracks(*target.impl->edit));
            {
                te::Edit::ScopedRenderStatus rendering(*target.impl->edit, true);
                te::Renderer::RenderTask task("Project integration verification", params, nullptr, nullptr);
                while (task.runJob() == juce::ThreadPoolJob::jobNeedsRunningAgain) {}
                check(task.errorMessage.isEmpty(), "render " + name + ": " + task.errorMessage);
            }
            auto stream = output.createInputStream();
            check(stream != nullptr, "render output exists: " + name);
            std::unique_ptr<juce::AudioFormatReader> reader(format.createReaderFor(stream.release(), true));
            check(reader != nullptr && reader->numChannels == 2 && reader->sampleRate == 48000
                  && std::abs(reader->lengthInSamples - 96000) <= 1, "render format and duration: " + name);
            juce::AudioBuffer<float> decoded(2, int(reader->lengthInSamples));
            check(reader->read(&decoded, 0, decoded.getNumSamples(), 0, true, true), "read rendered samples: " + name);
            return decoded;
        };
        const auto rms = [](const juce::AudioBuffer<float>& samples) { return double(samples.getRMSLevel(0, 12000, 72000)); };
        const auto difference = [&](const juce::AudioBuffer<float>& a, const juce::AudioBuffer<float>& b) {
            check(a.getNumChannels() == b.getNumChannels() && a.getNumSamples() == b.getNumSamples(), "comparable rendered buffers");
            double maximum = 0;
            for (int ch = 0; ch < a.getNumChannels(); ++ch)
                for (int i = 12000; i < 84000; ++i)
                    maximum = juce::jmax(maximum, std::abs(double(a.getSample(ch, i)) - double(b.getSample(ch, i))));
            return maximum;
        };
        const auto unchanged = [&](const juce::String& key, const Snapshot& before, const juce::String& label) {
            const auto after = snapshot();
            check(contentKey(impl->capture()) == key && after.revision == before.revision
                  && after.projectId == before.projectId && after.selectedTrackId == before.selectedTrackId
                  && after.dirty == before.dirty, label + " preserves active state and revision");
        };
        juce::Array<juce::var> formatReports;
        for (int index = 0; index < 2; ++index) {
            const auto source = index == 0 ? cbr : vbr;
            okay(newProject(snapshot().revision), "new isolated MP3 project");
            okay(importFile(source, snapshot().revision), "import actual MP3");
            const auto state = snapshot();
            check(state.tracks.size() == 1 && state.sourceFormat == "MP3", "MP3 imported as one audio track");
            check(state.tracks[0].waveformSource == state.waveformSource
                  && state.tracks[0].waveformSource != source
                  && state.tracks[0].waveformSource.hasFileExtension("wav")
                  && state.tracks[0].waveformSource.existsAsFile(), "per-track MP3 waveform uses prepared PCM");
            check(state.waveformSource.isAChildOf(directory.getChildFile("owned-audio-cache/audio-v1")),"MP3 cache honors absolute root override");
            check(state.channels == (index == 0 ? 2 : 1)
                  && state.sourceSampleRate == (index == 0 ? 48000 : 44100), "MP3 decoded channels/sample rate");
            check(std::abs(state.sourceDuration - 2.0) < 0.12, "MP3 duration with codec padding tolerance: "
                  + source.getFileName() + " decoded=" + juce::String(state.sourceDuration, 6)
                  + "s rate=" + juce::String(state.sourceSampleRate));
            const auto decoded = render(*this, index == 0 ? "project-cbr-render" : "project-vbr-render");
            const auto level = rms(decoded);
            check(std::isfinite(level) && level > 0.02 && level < 0.2, "MP3 engine render is non-silent and bounded");
            auto row = std::make_unique<juce::DynamicObject>();
            row->setProperty("format", index == 0 ? "MP3 CBR / ID3v2.3 / Unicode uppercase path" : "MP3 VBR / ID3v2.3");
            row->setProperty("source_sample_rate", state.sourceSampleRate);
            row->setProperty("source_channels", state.channels);
            row->setProperty("decoded_duration_seconds", state.sourceDuration);
            row->setProperty("render_rms", level);
            formatReports.add(juce::var(row.release()));
        }

        const auto invalid = ownedSources.getChildFile("invalid.mp3");
        check(invalid.replaceWithText("This is not MPEG audio."), "create corrupt fixture");
        const auto beforeBad = snapshot();
        const auto beforeBadKey = contentKey(impl->capture());
        check(importFile(invalid, beforeBad.revision).failed(), "reject corrupt MP3");
        unchanged(beforeBadKey, beforeBad, "corrupt import");
        check(importFiles({ wav, invalid }, beforeBad.revision).failed(), "reject mixed valid/invalid batch atomically");
        unchanged(beforeBadKey, beforeBad, "failed batch import");

        okay(newProject(snapshot().revision), "new mixed project");
        okay(importFiles({ wav, cbr, vbr }, snapshot().revision), "import WAV and two MP3 files together");
        auto state = snapshot();
        check(state.tracks.size() == 3 && state.dirty, "three-track mixed project exists and is dirty");
        check(state.tracks[0].waveformSource == wav, "WAV arrangement source remains the original PCM file");
        for (const auto& track : state.tracks)
            check(track.waveformSource.existsAsFile() && track.duration > 0.0
                  && track.duration <= state.duration, "every arrangement lane has prepared source and shared duration bounds");
        const auto wavId = state.tracks[0].id, cbrId = state.tracks[1].id, vbrId = state.tracks[2].id;
        const auto allMixed = render(*this, "project-three-track-mix");
        check(rms(allMixed) > 0.02, "three-track mix is audible");
        okay(setTrackMuted(vbrId, true, snapshot().revision), "mute VBR track");
        const auto withoutVbr = render(*this, "project-muted-vbr");
        check(difference(allMixed, withoutVbr) > 0.01, "mute changes actual rendered audio");
        okay(setTrackMuted(vbrId, false, snapshot().revision), "unmute VBR track");
        okay(setTrackSolo(vbrId, true, snapshot().revision), "solo VBR track");
        const auto soloVbr = render(*this, "project-solo-vbr");
        okay(setTrackSolo(vbrId, false, snapshot().revision), "clear solo");
        okay(setTrackMuted(wavId, true, snapshot().revision), "mute WAV");
        okay(setTrackMuted(cbrId, true, snapshot().revision), "mute CBR");
        const auto onlyVbr = render(*this, "project-only-vbr");
        check(difference(soloVbr, onlyVbr) < 0.00001, "solo output equals explicitly muting other tracks");
        okay(setTrackGain(vbrId, -6.0f, snapshot().revision), "attenuate VBR track");
        const auto attenuated = render(*this, "project-vbr-minus6");
        check(std::abs(rms(attenuated) / rms(onlyVbr) - std::pow(10.0, -6.0 / 20.0)) < 0.02,
              "per-track gain changes actual rendered level");

        const auto guarded = snapshot();
        const auto guardedKey = contentKey(impl->capture());
        check(setTrackGain(vbrId, -20.0f, guarded.revision - 1).failed(), "reject stale expected revision");
        unchanged(guardedKey, guarded, "stale gain request");
        check(setTrackMuted("missing-track-id", true, guarded.revision).failed(), "reject missing track target");
        unchanged(guardedKey, guarded, "missing target request");

        // Persist varied mix settings, including a fractional dB value that must not drift.
        okay(setTrackMuted(wavId, false, snapshot().revision), "restore WAV mute");
        okay(setTrackGain(wavId, -23.4f, snapshot().revision), "set fractional track gain");
        okay(setTrackGain(cbrId, -9.0f, snapshot().revision), "set CBR gain");
        okay(setTrackGain(vbrId, -4.0f, snapshot().revision), "set VBR gain");
        okay(setTrackSolo(vbrId, true, snapshot().revision), "save distinct solo state");
        setGain(-6.0f);
        setLoop(true);
        const auto bundle = directory.getChildFile("saved-bundle");
        check(!bundle.exists(), "saved bundle must be fresh");
        okay(bundle.createDirectory(), "create saved bundle");
        const auto project = bundle.getChildFile("Mixed Audio.emproj");
        okay(saveProject(project, snapshot().revision), "save archived mixed project");
        const auto saved = snapshot();
        check(!saved.dirty, "save clears dirty state");
        const auto savedAudio = render(*this, "project-saved-mix");
        const auto assertMix = [&](const Snapshot& actual, const juce::String& context) {
            check(actual.projectId == saved.projectId && actual.tracks.size() == saved.tracks.size()
                  && actual.looping == saved.looping && std::abs(actual.gainDb - saved.gainDb) < 0.002f, context + " project settings");
            for (size_t i = 0; i < saved.tracks.size(); ++i) {
                const auto& a = actual.tracks[i]; const auto& b = saved.tracks[i];
                check(a.id == b.id && a.name == b.name && a.format == b.format
                      && a.channels == b.channels && a.sampleRate == b.sampleRate
                      && std::abs(a.duration - b.duration) < 0.001
                      && std::abs(a.gainDb - b.gainDb) < 0.002f && a.muted == b.muted && a.solo == b.solo,
                      context + " track " + juce::String(int(i)));
            }
        };
        okay(setTrackGain(wavId, -8.0f, snapshot().revision), "edit fractional gain after save");
        check(snapshot().dirty && snapshot().canUndo, "edit sets dirty and enables undo");
        okay(undo(snapshot().revision), "undo fractional gain");
        assertMix(snapshot(), "fractional gain undo");
        check(!snapshot().dirty, "undo to -23.4 dB returns to clean saved state");
        okay(setTrackGain(vbrId, -12.0f, snapshot().revision), "edit audible saved mix");
        check(snapshot().dirty, "audible edit marks project dirty");
        okay(undo(snapshot().revision), "undo audible mix edit");
        check(!snapshot().dirty && snapshot().canRedo, "undo restores clean saved state and redo");
        okay(redo(snapshot().revision), "redo audible mix edit");
        check(snapshot().dirty && std::abs(snapshot().tracks[2].gainDb + 12.0f) < 0.002f, "redo restores edited gain");
        okay(undo(snapshot().revision), "return to saved mix");
        const auto undoAudio = render(*this, "project-undo-restored");
        check(difference(savedAudio, undoAudio) < 0.00001, "undo restores actual audio output");
        beginEditGesture();
        okay(setTrackGain(vbrId, -6.0f, snapshot().revision), "gesture first gain");
        okay(setTrackGain(vbrId, -8.0f, snapshot().revision), "gesture final gain");
        endEditGesture();
        okay(undo(snapshot().revision), "undo grouped gesture once");
        assertMix(snapshot(), "grouped gesture undo");
        check(!snapshot().dirty, "one gesture undo restores clean state");

        const auto beforeSaveFailure = snapshot();
        const auto saveFailureKey = contentKey(impl->capture());
        const auto manifestBytes = project.loadFileAsString();
        check(project.setReadOnly(true), "make owned manifest read-only for failure injection");
        const auto failedSave = saveProject(project, snapshot().revision);
        const bool writableRestored = project.setReadOnly(false);
        check(writableRestored, "restore owned manifest writable attribute");
        check(failedSave.failed(), "read-only manifest rejects replacement");
        check(project.loadFileAsString() == manifestBytes, "failed save preserves prior manifest bytes");
        unchanged(saveFailureKey, beforeSaveFailure, "failed save");

        double reopenedDifference = 0;
        {
            EngineSession reopened;
            okay(reopened.openProject(project, reopened.snapshot().revision), "reopen in fresh engine session");
            assertMix(reopened.snapshot(), "fresh session reopen");
            check(!reopened.snapshot().dirty, "freshly opened project is clean");
            const auto reopenedAudio = render(reopened, "project-fresh-session-render");
            reopenedDifference = difference(savedAudio, reopenedAudio);
            check(reopenedDifference < 0.00001, "fresh-session render matches saved mix");
        }

        // Delete only copies in this unique test directory after releasing their live Edit.
        okay(newProject(snapshot().revision), "release external source handles");
        for (const auto& source : { wav, cbr, vbr }) {
            check(source.isAChildOf(ownedSources) && ownedSources.isAChildOf(directory), "source cleanup stays in owned fixture directory");
            check(source.deleteFile(), "delete owned source copy");
        }
        okay(openProject(project, snapshot().revision), "reopen after original source copies are removed");
        assertMix(snapshot(), "archived reopen");
        const auto archivedAudio = render(*this, "project-after-source-removal");
        check(difference(savedAudio, archivedAudio) < 0.00001, "archived copies preserve output without external sources");

        const auto copyBundle = [&](const juce::String& name) {
            const auto target = directory.getChildFile(name);
            check(target.isAChildOf(directory) && !target.exists(), "bundle copy destination is fresh and owned");
            check(bundle.copyDirectoryTo(target), "copy bundle for " + name);
            return target.getChildFile(project.getFileName());
        };
        const auto missingManifest = copyBundle("missing-asset-case");
        storage::StoredProject missingState;
        okay(storage::load(missingManifest, missingState), "read missing-case asset map");
        check(missingState.assets[0].source.isAChildOf(missingManifest.getParentDirectory()), "missing-case asset is owned");
        check(missingState.assets[0].source.deleteFile(), "remove one owned archived asset");
        const auto active = snapshot();
        const auto activeKey = contentKey(impl->capture());
        check(openProject(missingManifest, active.revision).failed(), "reject missing archived asset");
        unchanged(activeKey, active, "missing asset open");
        const auto corruptManifest = copyBundle("corrupt-asset-case");
        storage::StoredProject corruptState;
        okay(storage::load(corruptManifest, corruptState), "read corrupt-case asset map");
        check(corruptState.assets[1].source.replaceWithText("Not an MP3"), "corrupt owned archived MP3");
        check(openProject(corruptManifest, active.revision).failed(), "reject corrupt archived audio");
        unchanged(activeKey, active, "corrupt asset open");
        const auto badManifest = directory.getChildFile("malformed.emproj");
        check(badManifest.replaceWithText("{ this is not valid JSON"), "create malformed owned manifest");
        check(openProject(badManifest, active.revision).failed(), "reject malformed project manifest");
        unchanged(activeKey, active, "malformed manifest open");

        const auto relocated = copyBundle("relocated-bundle");
        okay(openProject(relocated, snapshot().revision), "open relocated project bundle");
        assertMix(snapshot(), "relocated bundle");
        for (const auto& track : snapshot().tracks)
            check(track.source.isAChildOf(relocated.getParentDirectory()), "relocated assets resolve inside copied bundle");
        const auto relocatedAudio = render(*this, "project-relocated-render");
        check(difference(savedAudio, relocatedAudio) < 0.00001, "relocated project output is unchanged");

        // Leave a usable, audible three-track review project for UI/device verification.
        okay(setTrackMuted(cbrId, false, snapshot().revision), "unmute final review CBR track");
        okay(setTrackSolo(vbrId, false, snapshot().revision), "clear final review solo");
        setLoop(false); setGain(-6.0f); stop(); selectTrack(cbrId);
        okay(saveProject(relocated, snapshot().revision), "save final review mix");
        check(snapshot().tracks.size() == 3 && snapshot().sourceFormat == "MP3"
              && !snapshot().looping && !snapshot().playing && !snapshot().dirty, "final review state");

        auto report = std::make_unique<juce::DynamicObject>();
        report->setProperty("status", "passed");
        report->setProperty("scope", "actual MP3 decode and Tracktion offline renders; multi-track controls, undo/redo and archived project round trips; no listening or performance claim");
        report->setProperty("checks_passed", checks);
        report->setProperty("formats", juce::var(formatReports));
        report->setProperty("mixed_render_rms", rms(allMixed));
        report->setProperty("solo_render_rms", rms(soloVbr));
        report->setProperty("attenuated_track_rms", rms(attenuated));
        report->setProperty("fresh_session_max_sample_difference", reopenedDifference);
        report->setProperty("source_removal_and_relocation", "passed; only test-owned source copies deleted");
        report->setProperty("failed_import_open_save_preserve_active", true);
        report->setProperty("undo_redo_saved_dirty_state", "passed, including -23.4 dB and grouped gesture");
        report->setProperty("review_project", relocated.getFullPathName());
        report->setProperty("final_tracks", int(snapshot().tracks.size()));
        report->setProperty("final_revision", static_cast<juce::int64>(snapshot().revision));
        check(directory.getChildFile("project-report.json").replaceWithText(juce::JSON::toString(juce::var(report.release()))), "write project smoke report");
        return juce::Result::ok();
    } catch (const std::exception& error) {
        return juce::Result::fail(error.what());
    }
}
