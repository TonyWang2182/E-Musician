#include "AnalysisPanel.h"
#include <algorithm>
#include <cmath>
#include <limits>

namespace emusician {
namespace {
const juce::Colour ink {0xff171817}, paper {0xfffefefd}, secondary {0xff626560}, rule {0xffc6c9c3};
juce::Font mono(float size = 12.0f) { return juce::Font(juce::FontOptions(juce::Font::getDefaultMonospacedFontName(), size, juce::Font::plain)); }
juce::var object(std::initializer_list<std::pair<juce::Identifier, juce::var>> properties) {
    auto* value = new juce::DynamicObject();
    for (const auto& [key, data] : properties) value->setProperty(key, data);
    return juce::var(value);
}
bool succeeded(const juce::var& reply) {
    const auto status = reply["status"].toString(); return status == "completed" || status == "accepted";
}
bool terminal(const juce::String& state) {
    return state == "ready" || state == "applied" || state == "failed" || state == "cancelled" || state == "stale";
}
}

struct AnalysisPanel::Impl final : juce::ListBoxModel {
    explicit Impl(AnalysisPanel& component, EngineSession& engine, std::function<void(const juce::Result&)> callback)
        : owner(component), session(engine), report(std::move(callback)), results("Analysis results", this), progress(progressValue)
    {
        for (auto* control : std::initializer_list<juce::Component*> {
                 &separate, &transcribe, &chords, &source, &from, &length, &start, &cancel, &availability,
                 &threshold, &minimumNote, &thresholdLabel, &minimumLabel, &jobs, &status, &progress,
                 &results, &emptyResults, &previous, &next, &page, &play, &stop, &accept, &guidance,
                 &showSaved, &chordLabel, &chordStart, &chordEnd, &updateChord, &correctionHelp }) owner.addAndMakeVisible(control);
        for (auto* button : { &separate, &transcribe, &chords }) button->getProperties().set("flat", true);
        separate.onClick = [this] { chooseMode("separate"); };
        transcribe.onClick = [this] { chooseMode("transcribe"); };
        chords.onClick = [this] { chooseMode("chords"); };
        for (auto* button : { &separate, &transcribe, &chords })
            button->setTooltip("Configure the next analysis. Use the task list on the right to review existing results.");
        source.setFont(mono()); source.setColour(juce::Label::textColourId, ink);
        for (auto* label : { &availability, &status, &guidance, &page, &thresholdLabel, &minimumLabel, &correctionHelp, &emptyResults }) {
            label->setFont(mono(11)); label->setColour(juce::Label::textColourId, secondary);
            label->setMinimumHorizontalScale(1.0f);
        }
        availability.setJustificationType(juce::Justification::topLeft);
        guidance.setJustificationType(juce::Justification::topLeft);
        emptyResults.setJustificationType(juce::Justification::centred);
        emptyResults.setInterceptsMouseClicks(false, false);
        for (auto* field : { &from, &length, &chordStart, &chordEnd }) {
            field->setFont(mono()); field->setInputRestrictions(16, "0123456789.");
            field->setColour(juce::TextEditor::backgroundColourId, paper);
            field->setColour(juce::TextEditor::textColourId, ink);
            field->setColour(juce::TextEditor::outlineColourId, rule);
            field->setSelectAllWhenFocused(true);
        }
        from.setText("0.000000", false); length.setText("0.000000", false);
        from.setName("Analysis start, seconds within the clip"); length.setName("Analysis length, seconds");
        from.setTooltip("Seconds from the start of the selected audio clip. Analysis uses its dry source.");
        length.setTooltip("Length in seconds. Drag a time selection in the arrangement before opening Analyze to use that range.");
        threshold.setRange(0.05, 0.95, 0.01); threshold.setValue(0.5, juce::dontSendNotification);
        minimumNote.setRange(20.0, 1000.0, 10.0); minimumNote.setValue(80.0, juce::dontSendNotification);
        for (auto* slider : { &threshold, &minimumNote }) {
            slider->setSliderStyle(juce::Slider::LinearHorizontal);
            slider->setTextBoxStyle(juce::Slider::TextBoxRight, false, 52, 24);
            slider->setScrollWheelEnabled(false);
            slider->setColour(juce::Slider::textBoxTextColourId, ink);
            slider->setColour(juce::Slider::textBoxOutlineColourId, rule);
            slider->setColour(juce::Slider::textBoxBackgroundColourId, paper);
        }
        threshold.setName("Note onset threshold"); minimumNote.setName("Minimum note length in milliseconds");
        thresholdLabel.setText("onset", juce::dontSendNotification); minimumLabel.setText("min / ms", juce::dontSendNotification);
        threshold.setTooltip("Higher thresholds detect fewer note starts. Re-run analysis to change the candidate.");
        minimumNote.setTooltip("Discard candidate notes shorter than this duration. Timing is not quantized.");
        start.setTooltip("Analyze a frozen copy of the selected source range. The project stays unchanged until Import.");
        start.onClick = [this] { startAnalysis(); };
        cancel.onClick = [this] {
            if (jobId.isEmpty()) return;
            auto reply = request("cancel_analysis_job", object({ {"job_id", jobId} }));
            if (check(reply)) refreshJob();
        };
        jobs.setTextWhenNothingSelected("analysis jobs"); jobs.setTooltip("Review jobs started manually or by the Agent.");
        jobs.onChange = [this] {
            const auto index = jobs.getSelectedId() - 1;
            if (index >= 0 && index < jobIds.size()) selectJob(jobIds[index]);
        };
        results.setRowHeight(26); results.setColour(juce::ListBox::backgroundColourId, paper);
        results.setColour(juce::ListBox::outlineColourId, rule); results.setOutlineThickness(1);
        results.setMultipleSelectionEnabled(false); results.setName("Analysis candidate or saved chord regions");
        progress.setPercentageDisplay(true); progress.setColour(juce::ProgressBar::foregroundColourId, ink);
        progress.setColour(juce::ProgressBar::backgroundColourId, rule);
        previous.onClick = [this] { pageOffset = juce::jmax(0, pageOffset - pageSize); fetchPage(); };
        next.onClick = [this] { pageOffset += pageSize; fetchPage(); };
        play.onClick = [this] {
            if (resultId.isEmpty() || results.getSelectedRow() < 0) return;
            const auto reply = request("preview_analysis_stem", object({ {"result_id", resultId}, {"index", pageOffset + results.getSelectedRow()} }));
            previewing = check(reply); previewJobId = previewing ? reply["result"]["job_id"].toString() : juce::String();
        };
        stop.onClick = [this] { check(request("stop_analysis_preview", object({}))); previewing = false; previewJobId.clear(); };
        play.setTooltip("Preview only the selected stem. This does not start or change the arrangement.");
        accept.onClick = [this] { acceptResult(); };
        accept.setTooltip("Import the whole candidate with one Undo step. Original clips remain unchanged. Save as a new project to keep a 0.8.1 copy.");
        showSaved.onClick = [this] {
            savedView = !savedView; pageOffset = 0; results.deselectAllRows(); fetchPage();
        };
        showSaved.setTooltip("Show saved chords for the selected audio clip, or all project chords when no audio clip is selected. Select a row to correct its label or timing.");
        static const char* roots[] { "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B" };
        int option = 1;
        chordLabel.addItem("N", option++);
        for (const auto* root : roots) { chordLabel.addItem(juce::String(root) + ":maj", option++); chordLabel.addItem(juce::String(root) + ":min", option++); }
        chordLabel.setTextWhenNothingSelected("label"); chordLabel.setName("Chord label");
        chordStart.setName("Chord start, timeline seconds"); chordEnd.setName("Chord end, timeline seconds");
        chordStart.setTooltip("Start in absolute project timeline seconds."); chordEnd.setTooltip("End in absolute project timeline seconds.");
        updateChord.onClick = [this] { correctChord(); };
        correctionHelp.setText("label   start / s   end / s", juce::dontSendNotification);
    }

    ~Impl() override { results.setModel(nullptr); }

    juce::var request(const juce::String& command, const juce::var& args) {
        const auto snapshot = session.snapshot();
        return session.executeRequest(object({ {"request_id", "analysis-ui-" + juce::Uuid().toString()},
            {"project_id", snapshot.projectId}, {"expected_revision", juce::int64(snapshot.revision)},
            {"command", command}, {"args", args} }));
    }
    bool check(const juce::var& reply) {
        if (succeeded(reply)) return true;
        error = reply["error"].toString();
        if (error.isEmpty()) error = "Analysis request failed. Review the source and try again.";
        status.setText(error, juce::dontSendNotification); status.setTooltip(error);
        if (report) report(juce::Result::fail(error));
        return false;
    }
    void chooseMode(const juce::String& nextKind) {
        kind = nextKind;
        separate.setToggleState(kind == "separate", juce::dontSendNotification);
        transcribe.setToggleState(kind == "transcribe", juce::dontSendNotification);
        chords.setToggleState(kind == "chords", juce::dontSendNotification);
        if (savedView && kind != "chords") { savedView = false; pageOffset = 0; fetchPage(); }
        applyCapabilities(); owner.resized(); owner.repaint();
    }
    void setRange(double begin, double duration) {
        rangeStartExact = begin; rangeLengthExact = duration;
        rangeStartText = juce::String(begin, 6); rangeLengthText = juce::String(duration, 6);
        from.setText(rangeStartText, false); length.setText(rangeLengthText, false);
    }
    void refresh() {
        const auto snapshot = session.snapshot();
        if (snapshot.projectId != projectId) {
            if (previewing) { request("stop_analysis_preview", object({})); previewing = false; previewJobId.clear(); }
            projectId = snapshot.projectId; jobId.clear(); resultId.clear(); items.clear(); jobState.clear();
            savedView = false; pageOffset = total = 0; results.updateContent(); error.clear();
            applied = presentInProject = resultStale = resultLoaded = false;
            resultCheckedRevision = std::numeric_limits<std::uint64_t>::max();
        }
        revision = snapshot.revision;
        const EngineSession::ClipSnapshot* selected = nullptr;
        juce::String selectedName;
        for (const auto& track : snapshot.tracks) for (const auto& clip : track.clips)
            if (clip.id == snapshot.selectedClipId) { selected = &clip; selectedName = track.name; break; }
        const auto nextClipId = selected && selected->kind == "audio" ? selected->id : juce::String();
        if (clipId != nextClipId) {
            clipId = nextClipId; clipDuration = selected ? selected->duration : 0.0;
            clipTimelineStart = selected ? selected->timelineStart : 0.0;
            setRange(0.0, clipDuration);
            if (savedView) { pageOffset = 0; fetchPage(); }
        } else if (selected) { clipDuration = selected->duration; clipTimelineStart = selected->timelineStart; }
        source.setText(clipId.isEmpty() ? "Select one audio clip" : selectedName + " / " + (selected ? selected->source.getFileName() : juce::String()), juce::dontSendNotification);
        source.setTooltip(source.getText());
        recording = snapshot.recording || snapshot.recordingFinalizing;
        juce::StringArray nextIds, names;
        for (const auto& job : snapshot.jobs) if (job.kind.startsWith("analysis.") && job.kind != "analysis.preview") {
            nextIds.add(job.id); names.add(job.kind.fromFirstOccurrenceOf(".", false, false) + " / " + job.status + " / " + job.id.substring(0, 6));
        }
        if (nextIds != jobIds || names != jobNames) {
            jobIds = nextIds; jobNames = names; jobs.clear(juce::dontSendNotification);
            for (int i = 0; i < jobIds.size(); ++i) jobs.addItem(jobNames[i], i + 1);
            jobs.setSelectedId(jobIds.indexOf(jobId) + 1, juce::dontSendNotification);
        }
        if (--capabilityCountdown <= 0) {
            const auto reply = request("get_analysis_capabilities", object({}));
            if (succeeded(reply)) capabilities = reply["result"];
            capabilityCountdown = 12;
        }
        applyCapabilities();
        if (jobId.isNotEmpty()) refreshJob();
        else if (error.isEmpty()) status.setText("Choose a source, then run analysis.", juce::dontSendNotification);
        if (previewing && previewJobId.isNotEmpty()) {
            const auto reply = request("get_job", object({ {"job_id", previewJobId} }));
            if (!succeeded(reply)) { check(reply); previewing = false; previewJobId.clear(); }
            else {
                const auto preparation = reply["result"], preparationStatus = preparation["status"];
                if (preparationStatus.toString() == "completed") previewJobId.clear();
                else if (preparationStatus.toString() == "failed" || preparationStatus.toString() == "cancelled") {
                    error = preparation["error"].toString(); status.setText(error.isEmpty() ? "Stem preview cancelled." : error, juce::dontSendNotification);
                    status.setTooltip(error); previewing = false; previewJobId.clear();
                } else { status.setText(jobState + " / preparing stem preview", juce::dontSendNotification); }
            }
        }
        if (previewing && previewJobId.isEmpty()) {
            const auto reply = request("get_analysis_preview_status", object({}));
            if (succeeded(reply)) {
                const auto preview = reply["result"];
                const auto phase = preview["status"].toString();
                if (phase == "failed" || phase == "unavailable") {
                    error = preview["detail"].toString(); status.setText(error, juce::dontSendNotification); status.setTooltip(error);
                    previewing = false;
                } else if (phase == "completed" || phase == "stopped") previewing = false;
                else { status.setText(jobState + " / preview " + phase, juce::dontSendNotification); status.setTooltip(preview["detail"].toString()); }
            } else { check(reply); previewing = false; }
        }
        if (savedView && savedRevision != revision && !chordStart.hasKeyboardFocus(true)
            && !chordEnd.hasKeyboardFocus(true) && !chordLabel.hasKeyboardFocus(true) && !chordLabel.isPopupActive()) fetchPage();
        updateControls();
    }
    void applyCapabilities() {
        available = false; juce::String modelDetail = "Analysis worker is not ready.";
        if (const auto* providers = capabilities["providers"].getArray()) for (const auto& provider : *providers) {
            if (provider["kind"].toString() != kind) continue;
            available = bool(provider["available"]);
            modelDetail = provider["model_id"].toString();
            const auto reason = provider.getProperty("reason", provider["detail"]).toString();
            if (reason.isNotEmpty()) modelDetail += (modelDetail.isEmpty() ? "" : "\n") + reason;
            if (modelDetail.isEmpty()) modelDetail = available ? "Local model ready." : "Model not installed.";
        }
        availability.setText(modelDetail, juce::dontSendNotification); availability.setTooltip(modelDetail);
        guidance.setText(kind == "separate" ? "4 stems: vocals / drums / bass / other. Original audio stays in place."
            : kind == "transcribe" ? "Pitched notes only; no drums or pitch bends. Import, add an instrument, then edit in the piano roll."
            : "Major / minor / N baseline. Scores are not probabilities. Import labels, then correct below.", juce::dontSendNotification);
        guidance.setTooltip(guidance.getText());
        updateControls();
    }
    void updateControls() {
        const bool busy = jobId.isNotEmpty() && !terminal(jobState);
        start.setEnabled(available && clipId.isNotEmpty() && !busy && !recording);
        cancel.setEnabled(busy && jobState != "applying");
        const bool ready = resultLoaded && terminal(jobState) && resultId.isNotEmpty() && !savedView;
        accept.setEnabled(ready && total > 0 && !recording && !applied && !resultStale);
        accept.setButtonText(applied ? (presentInProject ? "imported" : "undone") : "import result");
        accept.setTooltip(applied && !presentInProject ? "This import was undone. Use Redo to restore it; the same result cannot be imported twice."
            : resultStale ? "The source clip or tempo changed. Run a new analysis before importing."
            : "Import the whole candidate with one Undo step. Original clips remain unchanged. Save as a new project to keep a 0.8.1 copy.");
        from.setEnabled(!busy); length.setEnabled(!busy);
        threshold.setEnabled(!busy); minimumNote.setEnabled(!busy);
        threshold.setVisible(kind == "transcribe"); minimumNote.setVisible(kind == "transcribe");
        thresholdLabel.setVisible(kind == "transcribe"); minimumLabel.setVisible(kind == "transcribe");
        const bool canPreview = bool(capabilities["preview_stems"]) && resultKind == "separate" && !savedView && resultId.isNotEmpty() && !resultStale;
        play.setVisible(resultKind == "separate" && !savedView); stop.setVisible(resultKind == "separate" && !savedView);
        play.setEnabled(canPreview && results.getSelectedRow() >= 0); stop.setEnabled(canPreview);
        showSaved.setVisible(kind == "chords"); showSaved.setEnabled(true);
        showSaved.setToggleState(savedView, juce::dontSendNotification);
        for (juce::Component* c : std::initializer_list<juce::Component*> { &chordLabel, &chordStart, &chordEnd, &updateChord, &correctionHelp }) c->setVisible(savedView);
        updateChord.setEnabled(savedView && selectedChordId.isNotEmpty() && !recording);
        emptyResults.setText(savedView ? (clipId.isEmpty() ? "No saved chord regions in this project." : "No saved chord regions for this clip.") : jobState == "ready" ? "No events detected in this range."
            : "Results appear here. Your project changes only after Import.", juce::dontSendNotification);
        emptyResults.setVisible(items.empty());
        previous.setEnabled(pageOffset > 0); next.setEnabled(pageOffset + int(items.size()) < total);
        page.setText(total > 0 ? juce::String(pageOffset + 1) + "-" + juce::String(pageOffset + int(items.size())) + " / " + juce::String(total) : "0 items", juce::dontSendNotification);
        owner.resized();
    }
    void startAnalysis() {
        if (!available || clipId.isEmpty()) return;
        const auto startText = from.getText().trim(), lengthText = length.getText().trim();
        // Keep the exact clip/range values behind the rounded display. A full
        // clip ending between milliseconds must not request beyond its end.
        const double begin = startText == rangeStartText ? rangeStartExact : startText.getDoubleValue();
        const double duration = lengthText == rangeLengthText ? rangeLengthExact : lengthText.getDoubleValue();
        if (startText.isEmpty() || lengthText.isEmpty() || !std::isfinite(begin) || !std::isfinite(duration)
            || begin < 0.0 || duration <= 0.0 || begin + duration > clipDuration + 1.0e-9) {
            check(object({ {"status", "invalid"}, {"error", "Choose a start and positive length inside the selected clip."} })); return;
        }
        const double maximum = double(capabilities.getProperty("max_duration_seconds", 600.0));
        if (duration > maximum) { check(object({ {"status", "invalid"}, {"error", "Choose a range no longer than " + juce::String(maximum, 0) + " seconds."} })); return; }
        auto parameters = kind == "transcribe" ? object({ {"onset_threshold", threshold.getValue()}, {"minimum_note_ms", minimumNote.getValue()} }) : object({});
        const auto reply = request("start_analysis", object({ {"clip_id", clipId}, {"kind", kind}, {"start_seconds", begin}, {"duration_seconds", duration}, {"parameters", parameters} }));
        if (!check(reply)) return;
        error.clear(); savedView = false; applied = presentInProject = resultStale = resultLoaded = false; resultId.clear(); items.clear(); total = pageOffset = 0;
        selectJob(reply["result"]["job_id"].toString());
    }
    void selectJob(const juce::String& id) {
        if (previewing) { request("stop_analysis_preview", object({})); previewing = false; previewJobId.clear(); }
        jobId = id; resultId.clear(); resultKind.clear(); jobState.clear(); resultVersion.clear(); error.clear();
        savedView = false; applied = presentInProject = resultStale = resultLoaded = false;
        resultCheckedRevision = std::numeric_limits<std::uint64_t>::max(); items.clear(); total = pageOffset = 0; results.updateContent();
        results.deselectAllRows(); refreshJob();
    }
    void refreshJob() {
        if (jobId.isEmpty()) return;
        const auto reply = request("get_analysis_job", object({ {"job_id", jobId} }));
        if (!succeeded(reply)) { check(reply); jobId.clear(); updateControls(); return; }
        const auto job = reply["result"]; jobState = job["status"].toString();
        const bool justApplied = jobState == "applied" && !applied;
        const auto phase = job["phase"].toString(), detail = job["detail"].toString();
        progressValue = juce::jlimit(0.0, 1.0, double(job["progress"]));
        const auto failure = job["error"].toString();
        const auto message = failure.isNotEmpty() ? failure : jobState + (phase.isNotEmpty() && phase != jobState ? " / " + phase : "") + (detail.isNotEmpty() ? "  " + detail : "");
        const auto jobSource = job["source"];
        auto sourceName = jobSource.getProperty("source_name", jobSource["clip_name"]).toString();
        if (sourceName.isEmpty() && jobSource["clip_id"].toString().isNotEmpty()) sourceName = "clip " + jobSource["clip_id"].toString().substring(0, 8);
        status.setText(message, juce::dontSendNotification);
        status.setTooltip(message + (sourceName.isEmpty() ? "" : "\nTask source: " + sourceName));
        const auto nextResult = job["result_id"].toString();
        if (nextResult.isNotEmpty() && resultId != nextResult) { resultId = nextResult; pageOffset = 0; resultVersion.clear(); }
        const bool hasCandidate = jobState == "ready" || jobState == "applied" || (terminal(jobState) && (resultLoaded || int(job["summary"]["total"]) > 0));
        if (hasCandidate && resultId.isNotEmpty()) {
            if (resultVersion != resultId + jobState && !savedView) { fetchPage(); resultVersion = resultId + jobState; }
            if (resultCheckedRevision != revision) {
                const auto metadataReply = request("get_analysis_result", object({ {"result_id", resultId}, {"offset", 0}, {"limit", 1} }));
                if (succeeded(metadataReply)) applyResultState(metadataReply["result"]);
            }
        }
        if (jobState == "applied") {
            applied = true;
            if (justApplied && presentInProject && resultKind == "chords" && !savedView) { savedView = true; pageOffset = 0; fetchPage(); }
        }
        if (applied && !presentInProject) {
            status.setText("Import undone. Use Redo to restore this result.", juce::dontSendNotification);
            status.setTooltip("This result was imported once and then undone. Redo restores it; duplicate import is disabled.");
        } else if (resultStale && !applied) {
            status.setText("Source or tempo changed. Run a new analysis.", juce::dontSendNotification);
            status.setTooltip("This candidate no longer matches its source clip or project tempo. Import and audition are disabled.");
        }
        updateControls();
    }
    void applyResultState(const juce::var& data) {
        applied = bool(data["applied"]); presentInProject = bool(data["present_in_project"]);
        resultStale = bool(data["stale"]); resultLoaded = true; resultCheckedRevision = revision;
        if (resultStale && previewing) { request("stop_analysis_preview", object({})); previewing = false; previewJobId.clear(); }
    }
    void fetchPage() {
        juce::var reply;
        if (savedView) {
            reply = request("get_chord_regions", object({ {"clip_id", clipId}, {"offset", pageOffset}, {"limit", pageSize} }));
        } else {
            if (resultId.isEmpty()) { items.clear(); total = 0; results.updateContent(); updateControls(); return; }
            reply = request("get_analysis_result", object({ {"result_id", resultId}, {"offset", pageOffset}, {"limit", pageSize} }));
        }
        if (!check(reply)) return;
        revision = std::uint64_t(juce::int64(reply["revision"]));
        const auto data = reply["result"];
        items.clear();
        if (const auto* list = data["items"].getArray()) for (const auto& value : *list) items.push_back(value);
        total = int(data["total"]); resultKind = savedView ? "chords" : data["kind"].toString();
        if (!savedView) applyResultState(data);
        else savedRevision = revision;
        selectedChordId.clear(); results.deselectAllRows(); results.updateContent(); results.repaint();
        if (!items.empty()) results.selectRow(0);
        updateControls(); owner.repaint();
    }
    void acceptResult() {
        if (resultId.isEmpty() || applied || resultStale || !resultLoaded) return;
        if (previewing) { request("stop_analysis_preview", object({})); previewing = false; previewJobId.clear(); }
        const auto reply = request("accept_analysis_result", object({ {"result_id", resultId}, {"expected_revision", juce::int64(session.snapshot().revision)} }));
        if (!check(reply)) return;
        const auto newJobId = reply["result"]["job_id"].toString();
        if (newJobId.isNotEmpty()) { jobId = newJobId; jobState = "applying"; refreshJob(); }
        else { applied = true; jobState = "applied"; updateControls(); }
        if (report) report(juce::Result::ok());
    }
    void correctChord() {
        if (selectedChordId.isEmpty()) return;
        if (session.snapshot().revision != selectedChordRevision) {
            check(object({ {"status", "conflict"}, {"error", "The project changed while editing this chord. Select its row again before applying."} }));
            savedRevision = std::numeric_limits<std::uint64_t>::max(); fetchPage(); return;
        }
        const auto label = chordLabel.getText();
        const double begin = chordStart.getText() == selectedChordStartText ? selectedChordStart : chordStart.getText().getDoubleValue();
        const double end = chordEnd.getText() == selectedChordEndText ? selectedChordEnd : chordEnd.getText().getDoubleValue();
        if (label.isEmpty() || !std::isfinite(begin) || !std::isfinite(end) || begin < 0.0 || end <= begin) {
            check(object({ {"status", "invalid"}, {"error", "Choose a chord label and an end later than its start."} })); return;
        }
        const auto reply = request("edit_chord_region", object({ {"id", selectedChordId}, {"label", label}, {"start_seconds", begin}, {"end_seconds", end} }));
        if (check(reply)) { savedRevision = std::numeric_limits<std::uint64_t>::max(); fetchPage(); if (report) report(juce::Result::ok()); }
    }
    int getNumRows() override { return int(items.size()); }
    void paintListBoxItem(int row, juce::Graphics& g, int width, int height, bool selected) override {
        if (row < 0 || row >= int(items.size())) return;
        g.fillAll(selected ? ink : paper); g.setColour(selected ? paper : ink); g.setFont(mono(12));
        const auto& item = items[size_t(row)]; juce::String text;
        if (resultKind == "separate") {
            text = item["name"].toString() + "  " + juce::String(double(item["duration_seconds"]), 2) + " s  "
                + juce::String(double(item["sample_rate"]) / 1000.0, 1) + " kHz";
        } else if (resultKind == "transcribe") {
            const int pitch = int(item["pitch"]);
            text = juce::MidiMessage::getMidiNoteName(pitch, true, true, 4) + " (" + juce::String(pitch) + ")  "
                + juce::String(double(item["start_seconds"]), 3) + " s  len " + juce::String(double(item["duration_seconds"]), 3)
                + "  vel " + juce::String(int(item["velocity"]));
        } else {
            text = item["label"].toString() + "  " + juce::String(double(item["start_seconds"]), 3) + " - "
                + juce::String(double(item["end_seconds"]), 3) + " s";
            if (bool(item["uncertain"])) text += "  uncertain";
            else if (item.hasProperty("score")) text += (savedView ? "  original score " : "  score ") + juce::String(double(item["score"]), 2);
        }
        g.drawFittedText(text, 8, 0, width - 16, height, juce::Justification::centredLeft, 1, 1.0f);
    }
    juce::String getTooltipForRow(int row) override {
        if (row < 0 || row >= int(items.size()) || resultKind != "chords") return {};
        const auto& item = items[size_t(row)];
        return item["label"].toString() + " / " + juce::String(double(item["start_seconds"]), 6) + " - "
            + juce::String(double(item["end_seconds"]), 6) + " seconds\nOriginal analysis score: "
            + juce::String(double(item["score"]), 3) + ". Uncalibrated; not the probability that the label is correct."
            + (savedView ? "\nEditing a label or boundary does not re-score the audio." : "");
    }
    void selectedRowsChanged(int row) override {
        selectedChordId.clear();
        if (savedView && row >= 0 && row < int(items.size())) {
            const auto& value = items[size_t(row)]; selectedChordId = value["id"].toString();
            selectedChordRevision = revision;
            chordLabel.setText(value["label"].toString(), juce::dontSendNotification);
            selectedChordStart = double(value["start_seconds"]); selectedChordEnd = double(value["end_seconds"]);
            selectedChordStartText = juce::String(selectedChordStart, 6); selectedChordEndText = juce::String(selectedChordEnd, 6);
            chordStart.setText(selectedChordStartText, false); chordEnd.setText(selectedChordEndText, false);
        }
        play.setEnabled(bool(capabilities["preview_stems"]) && resultKind == "separate" && !savedView && row >= 0 && !resultStale);
        updateChord.setEnabled(savedView && selectedChordId.isNotEmpty() && !recording);
    }

    AnalysisPanel& owner; EngineSession& session; std::function<void(const juce::Result&)> report;
    juce::TextButton separate { "separate" }, transcribe { "audio to MIDI" }, chords { "chords" };
    juce::Label source, availability, thresholdLabel, minimumLabel, status, guidance, page, correctionHelp, emptyResults;
    juce::TextEditor from, length, chordStart, chordEnd;
    juce::Slider threshold, minimumNote;
    juce::ComboBox jobs, chordLabel;
    juce::TextButton start { "run analysis" }, cancel { "cancel" }, accept { "import result" }, previous { "<" }, next { ">" };
    juce::TextButton play { "play stem" }, stop { "stop" }, showSaved { "saved chords" }, updateChord { "apply" };
    juce::ListBox results; double progressValue = 0.0; juce::ProgressBar progress;
    juce::String projectId, clipId, kind { "separate" }, jobId, resultId, resultKind, resultVersion, jobState, error, selectedChordId, previewJobId;
    juce::String rangeStartText, rangeLengthText, selectedChordStartText, selectedChordEndText;
    juce::StringArray jobIds, jobNames; juce::var capabilities;
    std::vector<juce::var> items;
    double clipDuration = 0.0, clipTimelineStart = 0.0;
    double rangeStartExact = 0.0, rangeLengthExact = 0.0;
    double selectedChordStart = 0.0, selectedChordEnd = 0.0;
    std::uint64_t revision = 0, selectedChordRevision = 0, savedRevision = std::numeric_limits<std::uint64_t>::max(), resultCheckedRevision = std::numeric_limits<std::uint64_t>::max();
    bool available = false, recording = false, savedView = false, applied = false, previewing = false;
    bool presentInProject = false, resultStale = false, resultLoaded = false;
    int pageOffset = 0, total = 0, capabilityCountdown = 0;
    static constexpr int pageSize = 50;
    juce::Rectangle<int> left, right;
};

AnalysisPanel::AnalysisPanel(EngineSession& engine, std::function<void(const juce::Result&)> report)
    : impl(std::make_unique<Impl>(*this, engine, std::move(report))) { setOpaque(true); setName("Local audio analysis"); impl->chooseMode("separate"); }
AnalysisPanel::~AnalysisPanel() {
    stopTimer();
    if (impl->previewing) impl->request("stop_analysis_preview", object({}));
}
void AnalysisPanel::visibilityChanged() {
    if (isShowing()) { impl->capabilityCountdown = 0; impl->refresh(); startTimerHz(4); }
    else {
        stopTimer();
        if (impl->previewing) { impl->request("stop_analysis_preview", object({})); impl->previewing = false; impl->previewJobId.clear(); }
    }
}
void AnalysisPanel::timerCallback() { impl->refresh(); }
void AnalysisPanel::setSelectedTimeRange(double startSeconds, double endSeconds) {
    impl->refresh();
    const auto begin = juce::jmax(0.0, startSeconds - impl->clipTimelineStart);
    const auto end = juce::jmin(impl->clipDuration, endSeconds - impl->clipTimelineStart);
    if (end > begin && endSeconds > startSeconds) impl->setRange(begin, end - begin);
}
void AnalysisPanel::paint(juce::Graphics& g) {
    const auto& p = *impl;
    g.fillAll(paper); g.setColour(rule);
    g.drawHorizontalLine(34, 0.0f, float(getWidth()));
    g.drawVerticalLine(p.left.getRight() + 8, 43.0f, float(getHeight() - 7));
    g.setColour(secondary); g.setFont(mono(11));
    g.drawText("from / s", p.left.getX(), 76, 65, 24, juce::Justification::centredLeft);
    g.drawText("length / s", p.left.getX(), 105, 78, 24, juce::Justification::centredLeft);
}
void AnalysisPanel::resized() {
    if (!impl) return;
    auto& p = *impl;
    const auto width = getWidth(), height = getHeight();
    p.separate.setBounds(4, 2, 96, 28); p.transcribe.setBounds(104, 2, 132, 28); p.chords.setBounds(240, 2, 84, 28);
    p.showSaved.setBounds(332, 2, 122, 28);
    const auto leftWidth = juce::jlimit(190, 224, width / 3);
    p.left = {8, 42, leftWidth, height - 50}; p.right = {leftWidth + 26, 42, juce::jmax(0, width - leftWidth - 34), height - 50};
    p.source.setBounds(p.left.getX(), 42, p.left.getWidth(), 26);
    p.from.setBounds(p.left.getX() + 82, 76, p.left.getWidth() - 82, 24);
    p.length.setBounds(p.left.getX() + 82, 105, p.left.getWidth() - 82, 24);
    const bool compact = height < 288;
    p.thresholdLabel.setBounds(p.left.getX(), 135, 62, 24); p.threshold.setBounds(p.left.getX() + 62, 135, p.left.getWidth() - 62, 24);
    p.minimumLabel.setBounds(p.left.getX(), 163, 62, 24); p.minimumNote.setBounds(p.left.getX() + 62, 163, p.left.getWidth() - 62, 24);
    const auto availableY = p.kind == "transcribe" ? 193 : 140;
    p.availability.setBounds(p.left.getX(), availableY, p.left.getWidth(), juce::jmax(0, height - availableY - 40));
    p.availability.setVisible(p.kind != "transcribe" || !compact);
    p.start.setBounds(p.left.getX(), height - 34, p.left.getWidth() - 72, 28); p.cancel.setBounds(p.start.getRight() + 4, height - 34, 68, 28);
    p.jobs.setBounds(p.right.getX(), 42, p.right.getWidth(), 25);
    p.status.setBounds(p.right.getX(), 70, p.right.getWidth(), 22); p.progress.setBounds(p.right.getX(), 95, p.right.getWidth(), 5);
    p.guidance.setBounds(p.right.getX(), 104, p.right.getWidth(), compact ? 32 : 34);
    const int correctionHeight = p.savedView ? 52 : 0;
    const int listTop = compact ? 139 : 143, listBottom = height - 40 - correctionHeight;
    p.results.setBounds(p.right.getX(), listTop, p.right.getWidth(), juce::jmax(26, listBottom - listTop));
    p.emptyResults.setBounds(p.results.getBounds().reduced(12, 3));
    p.correctionHelp.setBounds(p.right.getX(), listBottom + 2, p.right.getWidth(), 18);
    const auto correctionY = listBottom + 22;
    const int chordWidth = juce::jlimit(76, 104, p.right.getWidth() / 4);
    p.chordLabel.setBounds(p.right.getX(), correctionY, chordWidth, 25);
    const auto fieldWidth = juce::jmax(48, (p.right.getWidth() - chordWidth - 74) / 2);
    p.chordStart.setBounds(p.chordLabel.getRight() + 4, correctionY, fieldWidth, 25);
    p.chordEnd.setBounds(p.chordStart.getRight() + 4, correctionY, fieldWidth, 25);
    p.updateChord.setBounds(p.right.getRight() - 62, correctionY, 62, 25);
    p.previous.setBounds(p.right.getX(), height - 33, 26, 26); p.next.setBounds(p.right.getX() + 30, height - 33, 26, 26);
    p.page.setBounds(p.right.getX() + 60, height - 33, juce::jmax(50, p.right.getWidth() - 200), 26);
    p.accept.setBounds(p.right.getRight() - 126, height - 33, 126, 26);
    const auto previewX = p.right.getRight() - 280;
    p.play.setBounds(previewX, height - 33, 88, 26); p.stop.setBounds(previewX + 92, height - 33, 54, 26);
    const bool previewFits = p.right.getWidth() >= 400;
    if (p.resultKind == "separate" && !p.savedView) {
        p.play.setVisible(previewFits); p.stop.setVisible(previewFits);
        if (!previewFits) {
            p.play.setVisible(true); p.stop.setVisible(true);
            p.play.setBounds(p.right.getX(), 104, 92, 28); p.stop.setBounds(p.play.getRight() + 4, 104, 54, 28); p.guidance.setVisible(false);
        } else p.guidance.setVisible(true);
    } else p.guidance.setVisible(true);
}

juce::Result AnalysisPanel::runInteractionSmokeTest(juce::DynamicObject& report, const juce::File& directory) {
    auto& p = *impl; p.refresh();
    const auto before = p.session.snapshot();
    if (before.selectedClipId.isEmpty()) return juce::Result::fail("Analysis UI smoke requires a selected audio source.");
    for (const auto size : { juce::Point<int>(930, 308), juce::Point<int>(600, 260) }) {
        setSize(size.x, size.y); p.chooseMode("transcribe");
        if (p.start.getBounds().intersects(p.minimumNote.getBounds()) || p.right.getWidth() < 320)
            return juce::Result::fail("Analysis controls overlap at the supported dock size.");
        auto output = directory.getChildFile("ui-analysis-" + juce::String(size.x) + "x" + juce::String(size.y) + ".png").createOutputStream();
        if (!output || !juce::PNGImageFormat().writeImageToStream(createComponentSnapshot(getLocalBounds()), *output))
            return juce::Result::fail("Could not write analysis panel screenshot.");
    }
    setSelectedTimeRange(p.clipTimelineStart + .1, p.clipTimelineStart + juce::jmin(p.clipDuration, .6));
    const bool rangeApplied = p.clipDuration <= .1 || p.from.getText().getDoubleValue() >= .099;
    p.chooseMode("chords"); p.savedView = true; p.fetchPage();
    p.chooseMode("separate");
    // Synthetic status projection only: the native integration suite verifies
    // real stale/Undo/Redo commands. Here ready must not override stale metadata.
    p.resultId = "synthetic-ui-status-only"; p.resultLoaded = true; p.total = 4; p.jobState = "ready";
    p.resultStale = true; p.applied = false; p.updateControls();
    if (p.accept.isEnabled()) return juce::Result::fail("A stale candidate can still be imported from the UI.");
    p.resultStale = false; p.applied = true; p.presentInProject = false; p.updateControls();
    if (p.accept.isEnabled() || p.accept.getButtonText() != "undone") return juce::Result::fail("Undone import is not distinguished from an active import.");
    p.presentInProject = true; p.updateControls();
    if (p.accept.isEnabled() || p.accept.getButtonText() != "imported") return juce::Result::fail("Redo import projection is incorrect.");
    p.resultId.clear(); p.resultLoaded = p.applied = p.presentInProject = false; p.total = 0; p.jobState.clear(); p.updateControls();
    const auto after = p.session.snapshot();
    report.setProperty("analysis_ui_range_mapping", rangeApplied);
    report.setProperty("analysis_ui_read_only_navigation", before.revision == after.revision && before.projectId == after.projectId);
    report.setProperty("analysis_ui_empty_saved_chords", true);
    report.setProperty("analysis_ui_synthetic_stale_undo_redo_projection", true);
    if (!rangeApplied || before.revision != after.revision || before.projectId != after.projectId)
        return juce::Result::fail("Analysis navigation changed the project or mapped the range incorrectly.");
    return juce::Result::ok();
}
}
