#include "AnalysisPanel.h"
#include "UiLanguage.h"
#include <algorithm>
#include <cmath>
#include <cstdlib>
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
    return state == "ready" || state == "applied" || state == "failed" || state == "cancelled" || state == "stale" || state == "conflict" || state == "completed";
}
juce::String modeName(const juce::String& kind) {
    return kind == "separate" ? uiText("Separate", "音源分离") : kind == "transcribe" ? uiText("MIDI", "转 MIDI") : kind=="beats"?uiText("Beats", "节拍"):kind=="score"?uiText("Score", "综合"):uiText("Chords", "和弦");
}
juce::String chordName(const juce::String& label) {
    if(label == "N") return "-";
    const auto root = label.upToFirstOccurrenceOf(":", false, false), quality = label.fromFirstOccurrenceOf(":", false, false);
    if(!juce::StringArray{"maj","min","7","maj7","min7","dim","aug","sus2","sus4","hdim7","dim7"}.contains(quality))return label;
    return root + (quality == "maj" ? "" : quality == "min" ? "m" : quality == "min7" ? "m7" : quality == "hdim7" ? "m7b5" : quality);
}
struct AnalysisCanvas final : juce::Component {
    std::function<void(juce::Graphics&,juce::Rectangle<int>)> draw;
    std::function<void(juce::Point<float>)> select;
    void paint(juce::Graphics& g) override { if(draw) draw(g,getLocalBounds()); }
    void mouseDown(const juce::MouseEvent& e) override { if(select) select(e.position); }
};
class AnalysisOptions final : public juce::Component {
public:
    using Changed=std::function<void(const juce::String&,const juce::String&,double,double)>;
    AnalysisOptions(const juce::String& begin,const juce::String& duration,double onset,double minimum,bool notes,Changed changed)
        : notify(std::move(changed)) {
        for(auto* c:std::initializer_list<juce::Component*>{&startLabel,&lengthLabel,&thresholdLabel,&minimumLabel,&from,&length,&threshold,&minimumNote,&done})addAndMakeVisible(c);
        startLabel.setText(uiText("Start / s", "起点 / 秒"),juce::dontSendNotification);
        lengthLabel.setText(uiText("Length / s", "长度 / 秒"),juce::dontSendNotification);
        thresholdLabel.setText(uiText("Threshold", "阈值"),juce::dontSendNotification);minimumLabel.setText(uiText("Min note / ms", "最短音符 / ms"),juce::dontSendNotification);
        for(auto* label:{&startLabel,&lengthLabel,&thresholdLabel,&minimumLabel}){label->setFont(mono(12));label->setColour(juce::Label::textColourId,ink);}
        for(auto* field:{&from,&length}){field->setFont(mono(12));field->setInputRestrictions(16,"0123456789.");field->setSelectAllWhenFocused(true);
            field->setColour(juce::TextEditor::backgroundColourId,paper);field->setColour(juce::TextEditor::textColourId,ink);field->setColour(juce::TextEditor::outlineColourId,rule);}
        from.setText(begin,false);length.setText(duration,false);
        threshold.setRange(.05,.95,.01);threshold.setValue(onset,juce::dontSendNotification);
        minimumNote.setRange(20,1000,10);minimumNote.setValue(minimum,juce::dontSendNotification);
        for(auto* slider:{&threshold,&minimumNote}){slider->setSliderStyle(juce::Slider::LinearHorizontal);slider->setTextBoxStyle(juce::Slider::TextBoxRight,false,50,24);slider->setScrollWheelEnabled(false);}
        const auto update=[this]{if(notify)notify(from.getText(),length.getText(),threshold.getValue(),minimumNote.getValue());};
        from.onTextChange=update;length.onTextChange=update;threshold.onValueChange=update;minimumNote.onValueChange=update;
        done.setButtonText(uiText("Done", "完成"));done.onClick=[this]{if(auto* box=findParentComponentOfClass<juce::CallOutBox>())box->dismiss();};
        thresholdLabel.setVisible(notes);threshold.setVisible(notes);minimumLabel.setVisible(notes);minimumNote.setVisible(notes);
        setSize(310,notes?204:132);
    }
    void paint(juce::Graphics& g)override{g.fillAll(paper);}
    void resized()override{
        startLabel.setBounds(8,10,110,28);from.setBounds(120,10,180,28);
        lengthLabel.setBounds(8,46,110,28);length.setBounds(120,46,180,28);
        thresholdLabel.setBounds(8,82,110,28);threshold.setBounds(120,82,180,28);
        minimumLabel.setBounds(8,118,110,28);minimumNote.setBounds(120,118,180,28);
        done.setBounds(218,getHeight()-40,82,28);
    }
private:
    Changed notify;
    juce::Label startLabel,lengthLabel,thresholdLabel,minimumLabel;
    juce::TextEditor from,length;juce::Slider threshold,minimumNote;juce::TextButton done;
};
}

struct AnalysisPanel::Impl final : juce::ListBoxModel {
    explicit Impl(AnalysisPanel& component, EngineSession& engine, std::function<void(const juce::Result&)> callback)
        : owner(component), session(engine), report(std::move(callback)), results("Analysis results", this), progress(progressValue)
    {
        for (auto* control : std::initializer_list<juce::Component*> {
                 &separate, &transcribe, &chords, &source, &from, &length, &start, &cancel, &availability,
                 &threshold, &minimumNote, &thresholdLabel, &minimumLabel, &jobs, &status, &progress,
                 &results, &emptyResults, &failureDetails, &previous, &next, &page, &play, &stop, &accept, &guidance,
                 &showSaved, &chordLabel, &chordStart, &chordEnd, &updateChord, &correctionHelp,
                 &canvas, &stemCount, &quality, &instrument, &vocabulary, &options,
                 &beats, &score, &execution, &model, &scoreComponent, &beatBpm, &beatFirst, &beatMeter, &beatBpmLabel, &beatFirstLabel, &halfTempo, &doubleTempo, &useTempo }) owner.addAndMakeVisible(control);
        execution.addItem("Auto",1);execution.addItem("Local",2);execution.addItem("Cloud",3);execution.setSelectedId(1,juce::dontSendNotification);
        execution.setName("Analysis execution location");model.setName("Analysis model");
        execution.onChange=[this]{modelIds.clear();applyCapabilities();};model.onChange=[this]{applyCapabilities();};
        scoreComponent.addItem("Notes",1);scoreComponent.addItem("Chords",2);scoreComponent.addItem("Beats",3);scoreComponent.addItem("Sections",4);scoreComponent.setSelectedId(1,juce::dontSendNotification);
        scoreComponent.onChange=[this]{pageOffset=0;fetchPage();};scoreComponent.setName("Score candidate component");
        canvas.draw = [this](auto& g, auto bounds) { paintTimeline(g,bounds); };
        canvas.select = [this](auto point) { for(int i=int(hitRegions.size())-1;i>=0;--i) if(size_t(i)<items.size()&&hitRegions[size_t(i)].contains(point)) {
            results.selectRow(i);if(resultKind=="beats")beatFirst.setText(juce::String(double(items[size_t(i)]["time_seconds"]),6),false);canvas.repaint();return;
        } };
        stemCount.addItem("4",4); stemCount.addItem("6",6); stemCount.setSelectedId(4,juce::dontSendNotification);
        quality.addItem("Fast",1); quality.addItem("Quality",2); quality.setSelectedId(1,juce::dontSendNotification);
        int instrumentId=1; for(const auto* label:{"Auto","Piano","Bass","Guitar","Vocals"}) instrument.addItem(label,instrumentId++);
        instrument.setSelectedId(1,juce::dontSendNotification);
        vocabulary.addItem("Common chords",1); vocabulary.addItem("Major / minor",2); vocabulary.setSelectedId(1,juce::dontSendNotification);
        beatMeter.addItem("Auto meter",1);beatMeter.addItem("3/4",3);beatMeter.addItem("4/4",4);beatMeter.setSelectedId(1,juce::dontSendNotification);
        beatBpm.setTextToShowWhenEmpty("BPM",secondary);beatFirst.setTextToShowWhenEmpty("--",secondary);
        beatBpmLabel.setText("BPM",juce::dontSendNotification);
        for(auto* label:{&beatBpmLabel,&beatFirstLabel}){label->setFont(mono(11));label->setColour(juce::Label::textColourId,secondary);}
        const auto scaleTempo=[this](double factor){const auto bpm=beatBpm.getText().getDoubleValue()*factor;if(bpm>=20&&bpm<=300)beatBpm.setText(juce::String(bpm,3),false);};
        halfTempo.onClick=[scaleTempo]{scaleTempo(.5);};doubleTempo.onClick=[scaleTempo]{scaleTempo(2);};
        useTempo.onClick=[this]{applyBeats(true);};
        beatBpm.setTooltip(uiText("Detected playback tempo. Correct half/double tempo before aligning.","当前听到的速度；对齐前可修正半速或倍速。"));
        beatFirst.setTooltip(uiText("First bar beat, seconds within the analyzed range. Click a beat line to choose it.","小节首拍在分析选区中的秒数；点击拍线可重新选择。"));
        options.onClick=[this]{
            auto content=std::make_unique<AnalysisOptions>(from.getText(),length.getText(),threshold.getValue(),minimumNote.getValue(),kind=="transcribe"&&!cloudSelected,
                [safe=juce::Component::SafePointer<AnalysisPanel>(&owner),sourceId=clipId,project=projectId](const auto& begin,const auto& duration,double onset,double minimum){
                    if(!safe||safe->impl->clipId!=sourceId||safe->impl->projectId!=project)return;
                    auto& p=*safe->impl;p.from.setText(begin,false);p.length.setText(duration,false);
                    p.threshold.setValue(onset,juce::dontSendNotification);p.minimumNote.setValue(minimum,juce::dontSendNotification);
                });
            auto* parent=owner.getTopLevelComponent();
            juce::CallOutBox::launchAsynchronously(std::move(content),parent->getLocalArea(&options,options.getLocalBounds()),parent).setDismissalMouseClicksAreAlwaysConsumed(true);
        };
        stemCount.onChange=[this]{applyCapabilities();};
        stemCount.setTooltip(uiText("Number of separated tracks", "分离轨道数量"));
        quality.setTooltip(uiText("Quality takes longer; the original audio stays unchanged.", "高质量模式耗时更长，原音频保持不变。"));
        instrument.setTooltip(uiText("Choose the instrument to limit the detected note range.", "选择乐器，限制识别音域。"));
        for (auto* button : { &separate, &transcribe, &chords, &beats, &score }) button->getProperties().set("flat", true);
        separate.onClick = [this] { chooseMode("separate"); };
        transcribe.onClick = [this] { chooseMode("transcribe"); };
        chords.onClick = [this] { chooseMode("chords"); };
        beats.onClick = [this] { chooseMode("beats"); };
        score.onClick = [this] { chooseMode("score"); };
        for (auto* button : { &separate, &transcribe, &chords, &beats, &score })
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
        failureDetails.setMultiLine(true, true); failureDetails.setReadOnly(true);
        failureDetails.setScrollbarsShown(true); failureDetails.setCaretVisible(false);
        failureDetails.setFont(mono(12));
        failureDetails.setColour(juce::TextEditor::backgroundColourId, paper);
        failureDetails.setColour(juce::TextEditor::textColourId, ink);
        failureDetails.setColour(juce::TextEditor::outlineColourId, rule);
        failureDetails.setName("Analysis failure details");
        for (auto* field : { &from, &length, &chordStart, &chordEnd, &beatBpm, &beatFirst }) {
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
            savedView = !savedView;savedScore=savedView&&kind=="score"; savedAnalysisId.clear(); pageOffset = 0; results.deselectAllRows(); fetchPage();
        };
        showSaved.setTooltip(uiText("Open the latest chord track. Double-click any chord in the arrangement to edit it.", "打开最新和弦轨；双击编曲区中的和弦可编辑。"));
        static const char* roots[] { "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B" };
        int option = 1;
        chordLabel.addItem("N", option++);
        for (const auto* root : roots) for(const auto* type:{"maj","min","7","maj7","min7","dim","aug","sus2","sus4","hdim7","dim7"}) {
            const auto canonical=juce::String(root)+":"+type; chordValues.add(canonical); chordLabel.addItem(chordName(canonical),option++);
        }
        chordValues.insert(0,"N");
        chordLabel.setTextWhenNothingSelected("label"); chordLabel.setName("Chord label");
        chordLabel.setEditableText(true);
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
        if(kind!=nextKind)modelIds.clear();kind = nextKind;
        // Beats currently has a local provider and no visible route picker.
        // Do not inherit a hidden Cloud filter from the previous analysis tab.
        if (kind == "beats") execution.setSelectedId(2, juce::dontSendNotification);
        separate.setToggleState(kind == "separate", juce::dontSendNotification);
        transcribe.setToggleState(kind == "transcribe", juce::dontSendNotification);
        chords.setToggleState(kind == "chords", juce::dontSendNotification);
        beats.setToggleState(kind == "beats", juce::dontSendNotification);
        score.setToggleState(kind == "score", juce::dontSendNotification);
        if (savedView && kind != (savedScore?"score":"chords")) { savedView = false;savedScore=false; savedAnalysisId.clear(); pageOffset = 0; fetchPage(); }
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
            savedAnalysisId.clear();
            if (previewing) { request("stop_analysis_preview", object({})); previewing = false; previewJobId.clear(); }
            projectId = snapshot.projectId; jobId.clear(); displayJobId.clear(); resultId.clear(); items.clear(); jobState.clear();beatResultId.clear();
            savedView = false;savedScore=false; pageOffset = total = 0; results.updateContent(); error.clear();
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
        source.setText(clipId.isEmpty() ? uiText("Select one audio clip", "选择一个音频片段") : selectedName, juce::dontSendNotification);
        source.setTooltip(source.getText());
        recording = snapshot.recording || snapshot.recordingFinalizing;
        juce::StringArray nextIds, names;
        for (const auto& job : snapshot.jobs) if (job.kind=="analysis.separate"||job.kind=="analysis.transcribe"||job.kind=="analysis.chords"||job.kind=="analysis.beats"||job.kind=="analysis.score") {
            nextIds.add(job.id); names.add(modeName(job.kind.fromFirstOccurrenceOf(".", false, false)) + " " + juce::String(nextIds.size()));
        }
        if (nextIds != jobIds || names != jobNames) {
            jobIds = nextIds; jobNames = names; jobs.clear(juce::dontSendNotification);
            for (int i = 0; i < jobIds.size(); ++i) jobs.addItem(jobNames[i], i + 1);
            jobs.setSelectedId(jobIds.indexOf(displayJobId) + 1, juce::dontSendNotification);
        }
        if (--capabilityCountdown <= 0) {
            const auto reply = request("get_analysis_capabilities", object({}));
            if (succeeded(reply)) capabilities = reply["result"];
            capabilityCountdown = 12;
        }
        applyCapabilities();
        if(savedView)status.setText(uiText("Chord track", "和弦轨"),juce::dontSendNotification);
        else if (jobId.isNotEmpty()) refreshJob();
        else if (error.isEmpty()) status.setText(uiText("Ready", "就绪"), juce::dontSendNotification);
        if (previewing && previewJobId.isNotEmpty()) {
            const auto reply = request("get_job", object({ {"job_id", previewJobId} }));
            if (!succeeded(reply)) { check(reply); previewing = false; previewJobId.clear(); }
            else {
                const auto preparation = reply["result"], preparationStatus = preparation["status"];
                if (preparationStatus.toString() == "completed") previewJobId.clear();
                else if (preparationStatus.toString() == "failed" || preparationStatus.toString() == "cancelled") {
                    error = preparation["error"].toString(); status.setText(error.isEmpty() ? "Stem preview cancelled." : error, juce::dontSendNotification);
                    status.setTooltip(error); previewing = false; previewJobId.clear();
                } else { status.setText(uiText("Preparing preview…", "准备试听…"), juce::dontSendNotification); }
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
                else { status.setText(uiText("Listening", "试听中"), juce::dontSendNotification); status.setTooltip(preview["detail"].toString()); }
            } else { check(reply); previewing = false; }
        }
        if (savedView && savedRevision != revision && !chordStart.hasKeyboardFocus(true)
            && !chordEnd.hasKeyboardFocus(true) && !chordLabel.hasKeyboardFocus(true) && !chordLabel.isPopupActive()) fetchPage();
        updateControls();
    }
    void applyLanguage() {
        if(languageRevision==uiLanguageRevision())return;
        languageRevision=uiLanguageRevision();
        const int qualityId=quality.getSelectedId(),instrumentId=instrument.getSelectedId(),vocabularyId=vocabulary.getSelectedId(),meterId=beatMeter.getSelectedId();
        separate.setButtonText(modeName("separate")); transcribe.setButtonText(modeName("transcribe")); chords.setButtonText(modeName("chords"));
        beats.setButtonText(modeName("beats"));useTempo.setButtonText(uiText("Use this tempo", "采用此速度"));
        score.setButtonText(modeName("score"));execution.changeItemText(1,uiText("Auto","自动"));execution.changeItemText(2,uiText("Local","本地"));execution.changeItemText(3,uiText("Cloud","云端"));
        scoreComponent.changeItemText(1,uiText("Notes","音符"));scoreComponent.changeItemText(2,uiText("Chords","和弦"));scoreComponent.changeItemText(3,uiText("Beats","节拍"));scoreComponent.changeItemText(4,uiText("Sections","段落"));
        beatFirstLabel.setText(uiText("First / s", "首拍 / 秒"),juce::dontSendNotification);
        beatMeter.changeItemText(1,uiText("Auto meter", "自动拍号"));beatMeter.setSelectedId(meterId,juce::dontSendNotification);
        start.setButtonText(uiText("Analyze", "分析"));cancel.setButtonText(uiText("Cancel", "取消"));
        play.setButtonText(uiText("Listen", "试听"));stop.setButtonText(uiText("Stop", "停止"));
        showSaved.setButtonText(uiText("Chord track", "和弦轨"));updateChord.setButtonText(uiText("Apply", "应用"));
        thresholdLabel.setText(uiText("Threshold", "阈值"),juce::dontSendNotification);
        minimumLabel.setText(uiText("Min / ms", "最短 / ms"),juce::dontSendNotification);
        quality.changeItemText(1,uiText("Fast", "快速"));quality.changeItemText(2,uiText("Quality", "高质量"));
        instrument.changeItemText(1,uiText("Auto", "自动"));instrument.changeItemText(2,uiText("Piano", "钢琴"));
        instrument.changeItemText(3,uiText("Bass", "贝斯"));instrument.changeItemText(4,uiText("Guitar", "吉他"));instrument.changeItemText(5,uiText("Vocals", "人声"));
        vocabulary.changeItemText(1,uiText("Common chords", "常用和弦"));vocabulary.changeItemText(2,uiText("Major / minor", "大 / 小三和弦"));
        quality.setSelectedId(qualityId,juce::dontSendNotification);instrument.setSelectedId(instrumentId,juce::dontSendNotification);vocabulary.setSelectedId(vocabularyId,juce::dontSendNotification);
        jobs.setTextWhenNothingSelected(uiText("Recent analyses", "最近分析"));
        correctionHelp.setText(uiText("Chord    Start / s    End / s", "和弦    起点 / 秒    终点 / 秒"),juce::dontSendNotification);
    }
    void applyCapabilities() {
        applyLanguage(); available=false;
        const auto providerList=capabilities.getProperty("providers",juce::Array<juce::var>());
        juce::StringArray ids,labels;juce::Array<juce::var> choices;int defaultIndex=0,best=-1;
        if(const auto* list=providerList.getArray())for(const auto& provider:*list){
            const auto route=provider.getProperty("execution","local").toString();
            if(provider["kind"].toString()!=kind||(execution.getSelectedId()==2&&route!="local")||(execution.getSelectedId()==3&&route!="cloud"))continue;
            ids.add(route+":"+provider["model_id"].toString());labels.add(provider["model_id"].toString()+(bool(provider["available"])?"":uiText(" · unavailable"," · 未就绪")));choices.add(provider);
            const int rank=(bool(provider["available"])?4:0)+(bool(provider["default"])?2:0)+(route=="cloud"?1:0);if(rank>best){best=rank;defaultIndex=choices.size();}
        }
        if(ids!=modelIds){const auto previous=model.getSelectedId()>0&&model.getSelectedId()<=modelIds.size()?modelIds[model.getSelectedId()-1]:juce::String();modelIds=ids;model.clear(juce::dontSendNotification);for(int i=0;i<labels.size();++i)model.addItem(labels[i],i+1);model.setSelectedId(ids.contains(previous)?ids.indexOf(previous)+1:defaultIndex,juce::dontSendNotification);}
        const int index=model.getSelectedId()-1;selectedProvider=index>=0&&index<choices.size()?choices[index]:juce::var();
        available=bool(selectedProvider["available"]);cloudSelected=selectedProvider["execution"].toString()=="cloud";
        model.setTooltip(selectedProvider["model_id"].toString()+"\n"+selectedProvider["detail"].toString());
        if(!cloudSelected&&kind=="separate"&&stemCount.getSelectedId()==6)available=bool(capabilities["separation_six_stems"]);
        availability.setText(available ? juce::String() : uiText("Model unavailable", "模型未就绪"),juce::dontSendNotification);
        guidance.setText({},juce::dontSendNotification);
        updateControls();
    }
    void updateControls() {
        applyLanguage();
        const bool busy=jobId.isNotEmpty()&&!terminal(jobState);
        start.setEnabled(available&&clipId.isNotEmpty()&&!busy&&!recording);
        cancel.setEnabled(busy&&jobState!="applying");cancel.setVisible(busy);
        const bool ready=resultLoaded&&terminal(jobState)&&resultId.isNotEmpty()&&!savedView;
        accept.setEnabled(ready&&(total>0||resultTaskKind=="score"&&candidateHasContent)&&!recording&&!applied&&!resultStale);
        accept.setButtonText(applied ? (presentInProject?(resultKind=="beats"?uiText("Aligned", "已对齐"):uiText("Added", "已添加")):uiText("Undone", "已撤销"))
            : resultTaskKind=="score"?uiText("Add score", "加入结果"):resultKind=="beats"?uiText("Align audio", "对齐音频")
            : resultKind=="transcribe"?uiText("Add MIDI track", "添加 MIDI 轨")
            : resultKind=="chords"?uiText("Add chord track", "添加和弦轨"):uiText("Add tracks", "添加轨道"));
        accept.setVisible(!savedView);
        useTempo.setVisible(resultTaskKind!="score"&&resultKind=="beats"&&!savedView);useTempo.setEnabled(accept.isEnabled());
        scoreComponent.setVisible(resultTaskKind=="score"&&(!savedView||savedScore));scoreComponent.setEnabled(resultLoaded||savedScore);
        execution.setEnabled(!busy);model.setEnabled(!busy);
        accept.setTooltip(resultStale?uiText("Source changed. Analyze again.", "来源已改变，请重新分析。")
            :resultKind=="beats"?uiText("Align the first downbeat to a bar; preserve pre-roll. Undo restores the original timing.", "将首个小节拍对齐到小节线，保留前奏；可撤销还原。")
            :uiText("Add the result to the arrangement. Undo removes this import.", "将结果添加到编曲区；可一次撤销。"));
        for(juce::Component* c:std::initializer_list<juce::Component*>{&from,&length,&threshold,&minimumNote,&stemCount,&quality,&instrument,&vocabulary,&beatBpm,&beatFirst,&beatMeter,&halfTempo,&doubleTempo})c->setEnabled(!busy);
        const bool canPreview=bool(capabilities["preview_stems"])&&resultKind=="separate"&&!savedView&&!resultId.isEmpty()&&!resultStale;
        play.setVisible(canPreview);stop.setVisible(canPreview);play.setEnabled(canPreview&&results.getSelectedRow()>=0);stop.setEnabled(canPreview&&previewing);
        showSaved.setVisible(kind=="chords"||kind=="score");showSaved.setToggleState(savedView,juce::dontSendNotification);showSaved.setButtonText(kind=="score"?uiText("Saved score","已存结果"):uiText("Chord track","和弦轨"));
        updateChord.setEnabled(savedView&&resultKind=="chords"&&!selectedChordId.isEmpty()&&!recording);
        emptyResults.setText(savedView?uiText("No saved items in this view", "此视图暂无已存结果")
            :jobState=="ready"?(resultKind=="beats"?uiText("No steady beats found. Try a rhythmic section.", "未找到稳定节拍，请选择节奏明显的段落。"):uiText("No notes or chords found", "未检测到音符或和弦"))
            :busy?uiText("Analyzing…", "正在分析…"):uiText("Select audio, then Analyze", "选择音频，然后点击分析"),juce::dontSendNotification);
        const bool showFailure = items.empty() && error.isNotEmpty() && !busy && !savedView;
        emptyResults.setVisible(items.empty() && !showFailure);
        failureDetails.setVisible(showFailure);
        if (showFailure) {
            const auto detail = uiText("Analysis stopped. Your project is unchanged.", "分析已停止，工程未改动。") + "\n\n" + error;
            if (failureDetails.getText() != detail) { failureDetails.setText(detail, false); failureDetails.setCaretPosition(0); }
            failureDetails.toFront(false);
        } else if(items.empty())emptyResults.toFront(false);
        previous.setEnabled(pageOffset>0);next.setEnabled(pageOffset+int(items.size())<total);
        previous.setVisible(total>pageSize);next.setVisible(total>pageSize);
        page.setText(total>pageSize?juce::String(pageOffset+1)+"-"+juce::String(pageOffset+int(items.size()))+" / "+juce::String(total)
            :total>0?juce::String(total)+" "+(resultKind=="separate"?uiText("tracks", "轨道"):resultKind=="transcribe"?uiText("notes", "音符"):resultKind=="beats"?uiText("beats", "拍"):resultKind=="structure"?uiText("sections","段落"):uiText("chords", "和弦")):juce::String(),juce::dontSendNotification);
        options.setButtonText(uiText("Options", "选项"));options.setEnabled(!busy&&!recording);
        results.setRowHeight(resultKind=="separate"?44:28);
        results.setVisible(resultKind=="separate");canvas.setVisible(resultKind!="separate");
        progress.setVisible(busy);guidance.setVisible(false);correctionHelp.setVisible(false);
        owner.resized();canvas.repaint();
    }
    juce::Rectangle<float> plotBounds(juce::Rectangle<int> bounds)const {
        return bounds.toFloat().withTrimmedLeft(resultKind=="transcribe"?35.f:6.f).withTrimmedTop(22.f).withTrimmedBottom(4.f).withTrimmedRight(6.f);
    }
    void paintTimeline(juce::Graphics& g,juce::Rectangle<int> bounds) {
        g.fillAll(paper);hitRegions.clear();
        if(items.empty())return;
        if(resultKind=="beats"){
            const auto plot=plotBounds(bounds);if(plot.getWidth()<1||plot.getHeight()<1)return;
            const double begin=pageOffset==0?0:double(items.front()["time_seconds"]);
            const double end=juce::jmax(begin+.001,double(items.back()["time_seconds"])+.25);
            const auto x=[&](double t){return plot.getX()+float((t-begin)/(end-begin))*plot.getWidth();};
            g.setFont(mono(10));g.setColour(secondary);
            for(int i=0;i<=4;++i){const double t=begin+(end-begin)*i/4.;const int px=juce::jlimit(0,juce::jmax(0,bounds.getWidth()-64),int(x(t))-(i==4?58:i==0?0:30));g.drawText(juce::String(t,2)+" s",px,0,64,18,juce::Justification::centredLeft);}
            if(const auto* peaks=beatPeaks.getArray();peaks&&!peaks->isEmpty()&&beatDuration>0){
                float maximum=.001f;for(const auto& v:*peaks)maximum=juce::jmax(maximum,float(v));
                g.setColour(rule);const float middle=plot.getCentreY();
                for(int px=int(plot.getX());px<int(plot.getRight());++px){
                    const double t=begin+(end-begin)*(px-plot.getX())/plot.getWidth();
                    const int index=juce::jlimit(0,peaks->size()-1,int(t/beatDuration*peaks->size()));
                    const float h=juce::jlimit(0.f,1.f,float((*peaks)[index])/maximum)*plot.getHeight()*.4f;g.drawVerticalLine(px,middle-h,middle+h);
                }
            }
            const bool firstSet=beatFirst.getText().isNotEmpty();const double first=beatFirst.getText().getDoubleValue();
            for(const auto& beat:items){const double t=double(beat["time_seconds"]);const float px=x(t);const bool down=bool(beat["is_downbeat"]),chosen=firstSet&&std::abs(t-first)<.000001;
                const auto hit=juce::Rectangle<float>(px-5,plot.getY(),10,plot.getHeight()).getIntersection(plot);hitRegions.push_back(hit);
                g.setColour(down||chosen?ink:secondary.withAlpha(.55f));g.fillRect(px,plot.getY()+(down?0:plot.getHeight()*.22f),down||chosen?2.f:1.f,plot.getHeight()*(down?1.f:.78f));
                if(chosen){juce::Path marker;marker.addTriangle(px-5,plot.getY(),px+5,plot.getY(),px,plot.getY()+7);g.fillPath(marker);}
            }
            g.setColour(rule);g.drawRect(plot,1.f);return;
        }
        double first=std::numeric_limits<double>::max(),last=0;
        int low=127,high=0;
        for(const auto& item:items){const double a=double(item["start_seconds"]),b=resultKind=="transcribe"?a+double(item["duration_seconds"]):double(item["end_seconds"]);
            first=juce::jmin(first,a);last=juce::jmax(last,b);if(resultKind=="transcribe"){low=juce::jmin(low,int(item["pitch"]));high=juce::jmax(high,int(item["pitch"]));}}
        const auto plot=plotBounds(bounds);if(plot.getWidth()<1||plot.getHeight()<1)return;
        last=juce::jmax(first+.001,last);const auto x=[&](double t){return plot.getX()+float((t-first)/(last-first))*plot.getWidth();};
        g.setFont(mono(10));g.setColour(secondary);
        for(int i=0;i<=4;++i){const double t=first+(last-first)*i/4.;const float px=x(t);
            const int labelX=juce::jlimit(0,juce::jmax(0,bounds.getWidth()-64),int(px)-(i==4?58:i==0?0:30));
            g.drawText(juce::String(t,2)+" s",labelX,0,64,18,juce::Justification::centredLeft);
            g.setColour(rule.withAlpha(.6f));g.drawVerticalLine(int(px),plot.getY(),plot.getBottom());g.setColour(secondary);}
        if(resultKind=="transcribe"){
            low=juce::jmax(0,low-1);high=juce::jmin(127,juce::jmax(low+6,high+1));
            const float row=plot.getHeight()/float(high-low+1);
            for(int pitch=low;pitch<=high;++pitch){const float y=plot.getBottom()-(pitch-low+1)*row;
                const int pc=pitch%12;const bool black=pc==1||pc==3||pc==6||pc==8||pc==10;
                g.setColour(black?rule.withAlpha(.17f):paper);g.fillRect(plot.getX(),y,plot.getWidth(),row);
                if(pitch%12==0){g.setColour(secondary);g.drawText(juce::MidiMessage::getMidiNoteName(pitch,true,true,4),0,int(y),32,juce::jmax(12,int(row)),juce::Justification::centredRight);}}
            for(size_t i=0;i<items.size();++i){const auto& n=items[i];const double a=double(n["start_seconds"]);const float y=plot.getBottom()-(int(n["pitch"])-low+1)*row;
                const juce::Rectangle<float> rect{x(a),y,juce::jmax(1.f,x(a+double(n["duration_seconds"]))-x(a)),row};hitRegions.push_back(rect);
                g.setColour(int(i)==results.getSelectedRow()?ink:ink.withAlpha(.55f));g.fillRect(rect);}
        }else{
            for(size_t i=0;i<items.size();++i){const auto& c=items[i];const juce::Rectangle<float> rect{x(double(c["start_seconds"])),plot.getY()+4.f,juce::jmax(1.f,x(double(c["end_seconds"]))-x(double(c["start_seconds"]))),juce::jmax(1.f,plot.getHeight()-8.f)};
                hitRegions.push_back(rect);const bool selected=int(i)==results.getSelectedRow();g.setColour(selected?ink:rule.withAlpha(.25f));g.fillRect(rect);
                g.setColour(selected?paper:ink);g.drawRect(rect,1.f);
                if(rect.getWidth()>22)g.drawFittedText(chordName(c["label"].toString()),rect.toNearestInt().reduced(5,2),juce::Justification::centred,1);}
        }
        g.setColour(rule);g.drawRect(plot,1.f);
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
        const double maximum = double(selectedProvider.getProperty("max_duration_seconds", 600.0));
        if (duration > maximum) { check(object({ {"status", "invalid"}, {"error", "Choose a range no longer than " + juce::String(maximum, 0) + " seconds."} })); return; }
        static const char* instruments[]{"auto","piano","bass","guitar","vocals"};
        auto parameters = kind=="separate"?object({{"stems",stemCount.getSelectedId()},{"quality",quality.getSelectedId()==2?"quality":"fast"}})
            :kind=="transcribe"?object({{"onset_threshold",threshold.getValue()},{"minimum_note_ms",minimumNote.getValue()},{"instrument",instruments[juce::jlimit(0,4,instrument.getSelectedId()-1)]}})
            :kind=="beats"?object({{"meter",beatMeter.getSelectedId()==3?"3/4":beatMeter.getSelectedId()==4?"4/4":"auto"}})
            :object({{"vocabulary",vocabulary.getSelectedId()==2?"triads":"extended"}});
        if(cloudSelected)parameters=kind=="separate"?object({{"stems",4}}):object({});
        const auto reply = request("start_analysis", object({ {"clip_id", clipId}, {"kind", kind}, {"execution",execution.getSelectedId()==2?"local":execution.getSelectedId()==3?"cloud":"auto"},{"model_id",selectedProvider["model_id"]},{"start_seconds", begin}, {"duration_seconds", duration}, {"parameters", parameters} }));
        if (!check(reply)) return;
        error.clear(); savedView = false;savedScore=false; applied = presentInProject = resultStale = resultLoaded = false; resultId.clear(); items.clear(); total = pageOffset = 0;
        selectJob(reply["result"]["job_id"].toString());
    }
    void selectJob(const juce::String& id) {
        if (previewing) { request("stop_analysis_preview", object({})); previewing = false; previewJobId.clear(); }
        jobId = id; displayJobId=id; resultId.clear(); resultKind.clear();resultTaskKind.clear(); jobState.clear(); resultVersion.clear(); error.clear();scoreComponent.setSelectedId(1,juce::dontSendNotification);
        savedView = false;savedScore=false; applied = presentInProject = resultStale = resultLoaded = false;
        resultCheckedRevision = std::numeric_limits<std::uint64_t>::max(); items.clear(); total = pageOffset = 0; results.updateContent();
        results.deselectAllRows(); refreshJob();if(resultTaskKind.isNotEmpty())chooseMode(resultTaskKind);
    }
    void refreshJob() {
        if (jobId.isEmpty()) return;
        const auto reply = request("get_analysis_job", object({ {"job_id", jobId} }));
        if (!succeeded(reply)) { check(reply); jobId.clear(); updateControls(); return; }
        const auto job = reply["result"]; jobState = job["status"].toString();
        if(!savedView){resultTaskKind=job["kind"].toString();if(resultKind.isEmpty())resultKind=resultTaskKind=="score"?"transcribe":resultTaskKind;}
        const bool justApplied = jobState == "applied" && !applied;
        const auto phase = job["phase"].toString(), detail = job["detail"].toString();
        progressValue = juce::jlimit(0.0, 1.0, double(job["progress"]));
        const auto failure = job["error"].toString();
        if (failure.isNotEmpty()) error = failure;
        const auto message=failure.isNotEmpty()?uiText("Analysis stopped", "分析已停止")
            :jobState=="ready"?(kind=="beats"?uiText("Review tempo and first beat", "确认速度与首拍"):uiText("Ready to add", "可添加到编曲"))
            :jobState=="applied"?(kind=="beats"?uiText("Aligned", "已对齐"):uiText("Added to arrangement", "已添加到编曲"))
            :jobState=="cancelled"?(job["execution"].toString()=="cloud"&&!bool(job["remote_cancel_confirmed"])?uiText("Cloud stop pending", "云端取消待确认"):uiText("Cancelled", "已取消"))
            :jobState=="applying"?(kind=="beats"?uiText("Aligning audio…", "正在对齐音频…"):uiText("Adding tracks…", "正在添加轨道…"))
            :uiText("Analyzing…", "正在分析…")+" "+juce::String(int(progressValue*100))+"%";
        const auto jobSource = job["source"];
        auto sourceName = jobSource.getProperty("source_name", jobSource["clip_name"]).toString();
        if (sourceName.isEmpty() && jobSource["clip_id"].toString().isNotEmpty()) sourceName = "clip " + jobSource["clip_id"].toString().substring(0, 8);
        status.setText(message, juce::dontSendNotification);
        status.setTooltip(failure.isNotEmpty()?failure:sourceName);
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
            if (justApplied && presentInProject && resultTaskKind == "chords" && !savedView) { savedView = true; savedAnalysisId=resultId; pageOffset = 0; fetchPage(); }
        }
        if (applied && !presentInProject) {
            status.setText(uiText("Undone — use Redo to restore", "已撤销，可重做恢复"), juce::dontSendNotification);
            status.setTooltip("This result was imported once and then undone. Redo restores it; duplicate import is disabled.");
        } else if (resultStale && !applied) {
            status.setText(uiText("Source changed. Analyze again.", "来源已改变，请重新分析。"), juce::dontSendNotification);
            status.setTooltip("This candidate no longer matches its source clip or project tempo. Import and audition are disabled.");
        }
        updateControls();
    }
    void applyResultState(const juce::var& data) {
        applied = bool(data["applied"]); presentInProject = bool(data["present_in_project"]);
        resultStale = bool(data["stale"]); resultLoaded = true; resultCheckedRevision = revision;
        if(data["kind"].toString()=="score"){beatPeaks=juce::var();beatDuration=0;beatFirst.clear();}
        if(data["kind"].toString()=="beats"&&beatResultId!=resultId){
            beatResultId=resultId;const auto tempo=data["tempo"];
            beatBpm.setText(tempo["bpm"].isVoid()?juce::String():juce::String(double(tempo["bpm"]),3),false);
            beatFirst.setText(tempo["first_downbeat_seconds"].isVoid()?juce::String():juce::String(double(tempo["first_downbeat_seconds"]),6),false);
            const int meter=int(tempo["meter_numerator"]);beatMeter.setSelectedId(meter==3||meter==4?meter:1,juce::dontSendNotification);
            beatPeaks=data["waveform_peaks"];beatDuration=double(data["source"]["duration_seconds"]);
        }
        if (resultStale && previewing) { request("stop_analysis_preview", object({})); previewing = false; previewJobId.clear(); }
    }
    void fetchPage() {
        const auto keepSelection=selectedChordId;
        juce::var reply;
        if (savedView) {
            if(savedScore){static const char* components[]{"notes","chords","beats","structure"};reply=request("get_analysis_annotations",object({{"kind","score"},{"component",components[juce::jlimit(0,3,scoreComponent.getSelectedId()-1)]},{"offset",pageOffset},{"limit",pageSize}}));}
            else reply = request("get_chord_regions", object({ {"clip_id", savedAnalysisId.isEmpty()?clipId:juce::String()}, {"analysis_id",savedAnalysisId}, {"latest_only",savedAnalysisId.isEmpty()}, {"offset", pageOffset}, {"limit", pageSize} }));
        } else {
            if (resultId.isEmpty()) { items.clear(); total = 0; results.updateContent(); updateControls(); return; }
            auto args=object({ {"result_id", resultId}, {"offset", pageOffset}, {"limit", pageSize} });
            if(resultTaskKind=="score"){static const char* components[]{"notes","chords","beats","structure"};args.getDynamicObject()->setProperty("component",components[juce::jlimit(0,3,scoreComponent.getSelectedId()-1)]);}
            reply = request("get_analysis_result",args);
        }
        if (!check(reply)) return;
        revision = std::uint64_t(juce::int64(reply["revision"]));
        const auto data = reply["result"];
        items.clear();hitRegions.clear();
        if (const auto* list = data["items"].getArray()) for (const auto& value : *list) items.push_back(value);
        total = int(data["total"]);resultTaskKind=savedView?(savedScore?"score":"chords"):data["kind"].toString();resultKind = resultTaskKind;
        if(resultTaskKind=="score"){const auto component=data["component"].toString();resultKind=component=="notes"?"transcribe":component;}
        const auto summary=data["summary"];candidateHasContent=int(summary["track_count"])+int(summary["chord_count"])+int(summary["beat_count"])+int(summary["annotation_count"])>0;
        if (!savedView) applyResultState(data);
        else savedRevision = revision;
        selectedChordId.clear(); results.deselectAllRows(); results.updateContent(); results.repaint();
        int selected=0;if(savedView&&!keepSelection.isEmpty())for(int i=0;i<int(items.size());++i)if(items[size_t(i)]["id"].toString()==keepSelection){selected=i;break;}
        if (!items.empty()) results.selectRow(selected);
        updateControls(); owner.repaint();
    }
    void acceptResult() {
        if (resultId.isEmpty() || applied || resultStale || !resultLoaded) return;
        if(resultKind=="beats"&&resultTaskKind!="score"){applyBeats(false);return;}
        if (previewing) { request("stop_analysis_preview", object({})); previewing = false; previewJobId.clear(); }
        const auto reply = request("accept_analysis_result", object({ {"result_id", resultId}, {"expected_revision", juce::int64(session.snapshot().revision)} }));
        if (!check(reply)) return;
        const auto newJobId = reply["result"]["job_id"].toString();
        if (newJobId.isNotEmpty()) { jobId = newJobId; jobState = "applying"; refreshJob(); }
        else { applied = true; jobState = "applied"; updateControls(); }
        if (report) report(juce::Result::ok());
    }
    void applyBeats(bool projectTempo) {
        if(resultKind!="beats"||resultId.isEmpty()||applied||resultStale||!resultLoaded)return;
        const auto bpmText=beatBpm.getText().trim(),firstText=beatFirst.getText().trim();
        const auto parse=[](const juce::String& text){char* end=nullptr;const auto* start=text.toRawUTF8();const double value=std::strtod(start,&end);
            return end!=start&&*end=='\0'&&std::isfinite(value)?value:std::numeric_limits<double>::quiet_NaN();};
        const double bpm=parse(bpmText),first=parse(firstText);
        if(!std::isfinite(bpm)||bpm<20||bpm>300||!std::isfinite(first)||first<0||first>=beatDuration){
            check(object({{"status","invalid"},{"error",uiText("Enter BPM and choose the first bar beat on the graph.","填写 BPM，并在图中选择小节第一拍。")}}));return;
        }
        const int meter=beatMeter.getSelectedId();
        if(projectTempo&&meter!=3&&meter!=4){check(object({{"status","invalid"},{"error",uiText("Choose 3/4 or 4/4 before changing the project tempo.","修改工程速度前，请选择 3/4 或 4/4。")}}));return;}
        auto args=object({{"result_id",resultId},{"mode",projectTempo?"project_to_audio":"audio_to_project"},
            {"bpm",bpm},{"first_beat_seconds",first},{"follow_tempo",true}});
        if(projectTempo){args.getDynamicObject()->setProperty("numerator",meter);args.getDynamicObject()->setProperty("denominator",4);}
        const auto reply=request("apply_beat_analysis",args);
        if(!check(reply))return;
        const auto nextJob=reply["result"]["job_id"].toString();
        if(nextJob.isNotEmpty()){jobId=nextJob;jobState="applying";refreshJob();}
        else{applied=true;jobState="applied";updateControls();}
        if(report)report(juce::Result::ok());
    }
    void correctChord() {
        if (selectedChordId.isEmpty()) return;
        if (session.snapshot().revision != selectedChordRevision) {
            check(object({ {"status", "conflict"}, {"error", "The project changed while editing this chord. Select its row again before applying."} }));
            savedRevision = std::numeric_limits<std::uint64_t>::max(); fetchPage(); return;
        }
        const auto label = chordLabel.getSelectedId()>0?chordValues[chordLabel.getSelectedId()-1]:chordLabel.getText().trim();
        const double begin = chordStart.getText() == selectedChordStartText ? selectedChordStart : chordStart.getText().getDoubleValue();
        const double end = chordEnd.getText() == selectedChordEndText ? selectedChordEnd : chordEnd.getText().getDoubleValue();
        if (label.isEmpty() || !std::isfinite(begin) || !std::isfinite(end) || begin < 0.0 || end <= begin) {
            check(object({ {"status", "invalid"}, {"error", "Choose a chord label and an end later than its start."} })); return;
        }
        const auto reply = request("edit_chord_region", object({ {"id", selectedChordId}, {"label", label}, {"start_seconds", begin}, {"end_seconds", end} }));
        if (check(reply)) { savedRevision = std::numeric_limits<std::uint64_t>::max(); fetchPage(); if (report) report(juce::Result::ok()); }
    }
    int getNumRows() override { return int(items.size()); }
    void paintListBoxItem(int row,juce::Graphics& g,int width,int height,bool selected) override {
        if(row<0||row>=int(items.size()))return;
        g.fillAll(selected?rule.withAlpha(.25f):paper);g.setColour(ink);g.setFont(mono(12));
        const auto& item=items[size_t(row)];const auto rawName=item["name"].toString();
        g.drawFittedText(uiText(rawName),8,0,88,height,juce::Justification::centredLeft,1);
        const auto* peaks=item["waveform_peaks"].getArray();
        if(peaks&&!peaks->isEmpty()){
            const float x0=104.f,span=juce::jmax(0.f,float(width)-x0-12.f),middle=height*.5f;
            float maximum=.001f;for(const auto& v:*peaks)maximum=juce::jmax(maximum,float(v));
            for(int i=0;i<peaks->size();++i){const float x=x0+span*float(i)/float(juce::jmax(1,peaks->size()-1));const float a=juce::jlimit(0.f,1.f,float(peaks->getReference(i))/maximum)*(height*.38f);g.drawVerticalLine(int(x),middle-a,middle+a);}
        }else{g.setColour(secondary);g.drawText(juce::String(double(item["duration_seconds"]),1)+" s",104,0,width-112,height,juce::Justification::centredLeft);}
        g.setColour(rule);g.drawHorizontalLine(height-1,0.f,float(width));
    }

    juce::String getTooltipForRow(int row) override {
        if(row<0||row>=int(items.size()))return {};
        return resultKind=="separate"?uiText("Select a track and Listen", "选择轨道后试听")
            :uiText("Select a chord to edit", "选择和弦进行编辑");
    }

    void selectedRowsChanged(int row) override {
        canvas.repaint();
        selectedChordId.clear();
        if (savedView && resultKind=="chords" && row >= 0 && row < int(items.size())) {
            const auto& value = items[size_t(row)]; selectedChordId = value["id"].toString();
            selectedChordRevision = revision;
            chordLabel.setSelectedId(chordValues.indexOf(value["label"].toString())+1, juce::dontSendNotification);
            if(chordLabel.getSelectedId()==0)chordLabel.setText(value["label"].toString(),juce::dontSendNotification);
            selectedChordStart = double(value["start_seconds"]); selectedChordEnd = double(value["end_seconds"]);
            selectedChordStartText = juce::String(selectedChordStart, 6); selectedChordEndText = juce::String(selectedChordEnd, 6);
            chordStart.setText(selectedChordStartText, false); chordEnd.setText(selectedChordEndText, false);
        }
        play.setEnabled(bool(capabilities["preview_stems"]) && resultKind == "separate" && !savedView && row >= 0 && !resultStale);
        updateChord.setEnabled(savedView && resultKind=="chords" && selectedChordId.isNotEmpty() && !recording);
    }

    AnalysisPanel& owner; EngineSession& session; std::function<void(const juce::Result&)> report;
    juce::TextButton separate { "separate" }, transcribe { "audio to MIDI" }, chords { "chords" }, beats { "beats" },score {"Score"};
    juce::ComboBox execution,model,scoreComponent;juce::StringArray modelIds;juce::var selectedProvider;bool cloudSelected=false,candidateHasContent=false;juce::String resultTaskKind;
    juce::TextEditor beatBpm,beatFirst;juce::ComboBox beatMeter;juce::Label beatBpmLabel,beatFirstLabel;
    juce::TextButton halfTempo{"/2"},doubleTempo{"x2"},useTempo;juce::String beatResultId;juce::var beatPeaks;double beatDuration=0;
    juce::Label source, availability, thresholdLabel, minimumLabel, status, guidance, page, correctionHelp, emptyResults;
    juce::TextEditor from, length, chordStart, chordEnd, failureDetails;
    juce::Slider threshold, minimumNote;
    juce::ComboBox jobs, chordLabel, stemCount, quality, instrument, vocabulary;
    juce::TextButton options; AnalysisCanvas canvas;
    juce::StringArray chordValues;std::vector<juce::Rectangle<float>> hitRegions;
    juce::String savedAnalysisId,displayJobId;
    std::uint64_t languageRevision=std::numeric_limits<std::uint64_t>::max();
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
    bool available = false, recording = false, savedView = false, savedScore=false, applied = false, previewing = false;
    bool presentInProject = false, resultStale = false, resultLoaded = false;
    int pageOffset = 0, total = 0, capabilityCountdown = 0;
    static constexpr int pageSize = 100;
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
void AnalysisPanel::timerCallback() { if(!impl->session.isControlBusy())impl->refresh(); }
void AnalysisPanel::refreshLanguage() { impl->applyLanguage(); impl->refresh(); repaint(); }
void AnalysisPanel::showBeats() { impl->refresh(); impl->chooseMode("beats"); }
void AnalysisPanel::setSelectedTimeRange(double startSeconds, double endSeconds) {
    impl->refresh();
    const auto begin = juce::jmax(0.0, startSeconds - impl->clipTimelineStart);
    const auto end = juce::jmin(impl->clipDuration, endSeconds - impl->clipTimelineStart);
    if (end > begin && endSeconds > startSeconds) impl->setRange(begin, end - begin);
}
void AnalysisPanel::paint(juce::Graphics& g) {
    const auto& p=*impl;g.fillAll(paper);g.setColour(rule);g.drawHorizontalLine(34,0.f,float(getWidth()));
    g.drawVerticalLine(p.left.getRight()+8,43.f,float(getHeight()-8));
    g.setColour(secondary);g.setFont(mono(11));
}
void AnalysisPanel::resized() {
    if(!impl)return;auto& p=*impl;const int width=getWidth(),height=getHeight();
    p.separate.setBounds(4,2,91,28);p.transcribe.setBounds(99,2,64,28);p.chords.setBounds(167,2,78,28);
    p.beats.setBounds(249,2,64,28);p.score.setBounds(317,2,70,28);p.showSaved.setBounds(391,2,105,28);
    const int leftWidth=juce::jlimit(164,208,width/3);
    p.left={8,42,leftWidth,height-50};p.right={leftWidth+25,42,juce::jmax(0,width-leftWidth-33),height-50};
    p.source.setBounds(p.left.getX(),42,p.left.getWidth(),27);
    const bool separation=p.kind=="separate",transcription=p.kind=="transcribe",beatMode=p.kind=="beats",beatResult=p.resultTaskKind!="score"&&p.resultKind=="beats"&&!p.savedView;
    p.execution.setVisible(!beatMode);p.model.setVisible(!beatMode);
    p.execution.setBounds(p.left.getX(),73,72,26);p.model.setBounds(p.left.getX()+76,73,p.left.getWidth()-76,26);
    p.stemCount.setVisible(separation&&!p.cloudSelected);p.quality.setVisible(separation&&!p.cloudSelected);p.instrument.setVisible(transcription&&!p.cloudSelected);p.vocabulary.setVisible(p.kind=="chords"&&!p.cloudSelected);
    p.stemCount.setBounds(p.left.getX(),105,52,26);p.quality.setBounds(p.left.getX()+58,105,p.left.getWidth()-58,26);
    p.instrument.setBounds(p.left.getX(),105,p.left.getWidth(),26);p.vocabulary.setBounds(p.instrument.getBounds());
    const int optionY=p.cloudSelected||p.kind=="score"?105:137;
    p.options.setBounds(p.left.getX(),optionY,82,25);p.availability.setBounds(p.left.getX()+84,optionY+1,p.left.getWidth()-84,24);
    p.model.setTooltip(p.selectedProvider["detail"].toString()+"\n"+p.selectedProvider["model_id"].toString());
    for(juce::Component* c:std::initializer_list<juce::Component*>{&p.beatBpm,&p.beatFirst,&p.beatBpmLabel,&p.beatFirstLabel,&p.beatMeter,&p.halfTempo,&p.doubleTempo})c->setVisible(beatMode);
    if(beatMode){
        p.beatMeter.setBounds(p.left.getX(),76,p.left.getWidth()-80,26);p.options.setBounds(p.beatMeter.getRight()+4,76,76,26);
        p.beatBpmLabel.setBounds(p.left.getX(),108,32,26);p.beatBpm.setBounds(p.left.getX()+32,108,p.left.getWidth()-100,26);
        p.halfTempo.setBounds(p.left.getRight()-64,108,30,26);p.doubleTempo.setBounds(p.left.getRight()-31,108,31,26);
        p.beatFirstLabel.setBounds(p.left.getX(),140,72,26);p.beatFirst.setBounds(p.left.getX()+74,140,p.left.getWidth()-74,26);
        p.availability.setBounds(p.left.getX(),168,p.left.getWidth(),20);p.availability.setVisible(height>=236);
    }else p.availability.setVisible(true);
    // Range and note options live in a compact popover at every dock size.
    for(juce::Component* c:std::initializer_list<juce::Component*>{&p.from,&p.length,&p.threshold,&p.minimumNote,&p.thresholdLabel,&p.minimumLabel})c->setVisible(false);
    p.start.setVisible(true);p.cancel.setVisible(p.jobId.isNotEmpty()&&!terminal(p.jobState));
    p.start.setBounds(p.left.getX(),height-34,p.left.getWidth()-70,27);p.cancel.setBounds(p.start.getRight()+4,height-34,66,27);
    p.jobs.setBounds(p.right.getX(),42,juce::jmax(90,p.right.getWidth()-138),25);p.status.setBounds(p.jobs.getRight()+5,42,p.right.getRight()-p.jobs.getRight()-5,25);
    p.progress.setBounds(p.right.getX(),71,p.right.getWidth(),3);
    const int correctionHeight=p.savedView&&p.resultKind=="chords"?32:0;
    const bool scoreResult=p.resultTaskKind=="score"&&(!p.savedView||p.savedScore);
    p.scoreComponent.setVisible(scoreResult);p.scoreComponent.setBounds(p.right.getX(),79,juce::jmin(160,p.right.getWidth()),25);
    const int top=scoreResult?110:82,bottom=height-(beatResult?70:42)-correctionHeight;
    p.results.setBounds(p.right.getX(),top,p.right.getWidth(),juce::jmax(26,bottom-top));p.canvas.setBounds(p.results.getBounds());
    p.emptyResults.setBounds(p.results.getBounds().reduced(5));
    p.failureDetails.setBounds(p.results.getBounds().reduced(5));
    for(juce::Component* c:std::initializer_list<juce::Component*>{&p.chordLabel,&p.chordStart,&p.chordEnd,&p.updateChord})c->setVisible(p.savedView&&p.resultKind=="chords");
    const int chordWidth=juce::jlimit(66,90,p.right.getWidth()/4),fieldWidth=juce::jmax(42,(p.right.getWidth()-chordWidth-70)/2);
    p.chordLabel.setBounds(p.right.getX(),bottom+3,chordWidth,25);p.chordStart.setBounds(p.chordLabel.getRight()+4,bottom+3,fieldWidth,25);
    p.chordEnd.setBounds(p.chordStart.getRight()+4,bottom+3,fieldWidth,25);p.updateChord.setBounds(p.right.getRight()-58,bottom+3,58,25);
    p.previous.setBounds(p.right.getX(),height-32,24,25);p.next.setBounds(p.right.getX()+28,height-32,24,25);
    const int pageX=p.right.getX()+(p.total>p.pageSize?56:0);
    p.page.setBounds(pageX,height-32,juce::jmax(30,p.right.getWidth()- (pageX-p.right.getX())-140),25);
    p.accept.setBounds(p.right.getRight()-138,height-33,138,27);
    if(beatResult){
        const int actionWidth=(p.right.getWidth()-6)/2;
        p.accept.setBounds(p.right.getX(),height-33,actionWidth,27);p.useTempo.setBounds(p.accept.getRight()+6,height-33,p.right.getWidth()-actionWidth-6,27);
        p.previous.setTopLeftPosition(p.right.getX(),height-63);p.next.setTopLeftPosition(p.right.getX()+28,height-63);
        p.page.setBounds(pageX,height-63,juce::jmax(30,p.right.getRight()-pageX),25);
    }
    p.play.setBounds(p.right.getX(),height-33,65,27);p.stop.setBounds(p.right.getX()+69,height-33,58,27);
    if(p.resultKind=="separate")p.page.setVisible(false);else p.page.setVisible(true);
}
void AnalysisPanel::showChordRegion(const juce::String& chordId) {
    auto& p=*impl;p.refresh();
    const auto snapshot=p.session.snapshot();if(!snapshot.chordRegions)return;
    const auto selected=std::find_if(snapshot.chordRegions->begin(),snapshot.chordRegions->end(),[&](const auto& c){return c.id==chordId;});
    if(selected==snapshot.chordRegions->end())return;
    p.chooseMode("chords");p.savedView=true;p.savedScore=false;p.savedAnalysisId=selected->analysisId;p.resultKind="chords";
    int index=0;for(const auto& c:*snapshot.chordRegions){if(c.id==chordId)break;if(c.analysisId==p.savedAnalysisId)++index;}
    p.pageOffset=(index/p.pageSize)*p.pageSize;p.fetchPage();
    for(int i=0;i<int(p.items.size());++i)if(p.items[size_t(i)]["id"].toString()==chordId){p.results.selectRow(i);break;}
    p.updateControls();repaint();
}

juce::Result AnalysisPanel::runInteractionSmokeTest(juce::DynamicObject& report, const juce::File& directory) {
    auto& p = *impl; p.refresh();
    const auto before = p.session.snapshot();
    if (before.selectedClipId.isEmpty()) return juce::Result::fail("Analysis UI smoke requires a selected audio source.");
    const auto realCapabilities = p.capabilities;
    p.capabilities = object({ {"providers", juce::Array<juce::var> {
        object({ {"kind", "chords"}, {"execution", "cloud"}, {"model_id", "synthetic-chord"}, {"available", true} }),
        object({ {"kind", "beats"}, {"execution", "local"}, {"model_id", "synthetic-beat"}, {"available", true} })
    }} });
    p.execution.setSelectedId(3, juce::dontSendNotification); p.chooseMode("chords");
    p.chooseMode("beats");
    if (p.execution.getSelectedId() != 2 || !p.available || p.selectedProvider["model_id"].toString() != "synthetic-beat")
        return juce::Result::fail("Cloud-to-Beats switch retained a hidden route filter.");
    report.setProperty("cloudToLocalBeatRoute", true);
    p.capabilities = realCapabilities; p.execution.setSelectedId(1, juce::dontSendNotification); p.modelIds.clear();
    for (const auto size : { juce::Point<int>(930, 308), juce::Point<int>(600, 260), juce::Point<int>(540, 210) }) {
        setSize(size.x, size.y); p.chooseMode("transcribe");
        if ((p.minimumNote.isVisible() && p.start.getBounds().intersects(p.minimumNote.getBounds())) || p.right.getWidth() < 300)
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
    if (p.accept.isEnabled() || p.accept.getButtonText() != uiText("Undone", "已撤销")) return juce::Result::fail("Undone import is not distinguished from an active import.");
    p.presentInProject = true; p.updateControls();
    if (p.accept.isEnabled() || p.accept.getButtonText() != uiText("Added", "已添加")) return juce::Result::fail("Redo import projection is incorrect.");
    p.resultId.clear(); p.resultLoaded = p.applied = p.presentInProject = false; p.total = 0; p.jobState.clear(); p.updateControls();
    p.jobState = "failed"; p.error = "The isolated analysis worker crashed with an access violation (0xc0000005). The project is unchanged. See process.log.";
    for (const auto size : { juce::Point<int>(600,260), juce::Point<int>(540,210) }) {
        setSize(size.x,size.y); p.updateControls();
        if (!p.failureDetails.isVisible() || !p.failureDetails.isReadOnly() || !p.failureDetails.getText().contains(p.error)
            || p.failureDetails.getHeight() < 40 || p.accept.isEnabled())
            return juce::Result::fail("Analysis failure is not visibly readable or can still be accepted.");
        auto output = directory.getChildFile("ui-analysis-failed-"+juce::String(size.x)+"x"+juce::String(size.y)+"-synthetic.png").createOutputStream();
        if (!output || !juce::PNGImageFormat().writeImageToStream(createComponentSnapshot(getLocalBounds()),*output))
            return juce::Result::fail("Cannot capture analysis failure fixture.");
    }
    report.setProperty("analysis_ui_failure_visible_selectable_scrollable",true);
    p.error.clear(); p.jobState.clear(); p.updateControls();
    // These are explicitly synthetic view fixtures; real inference and import
    // quality are separate process tests. No music is written by a screenshot.
    const auto oldLanguage=uiLanguageCode();
    struct RestoreLanguage{juce::String value;~RestoreLanguage(){setUiLanguage(value,false);}} restore{oldLanguage};
    for(const auto* language:{"en","zh-CN"})for(const auto* visualKind:{"transcribe","chords","beats"}){
        setUiLanguage(language,false);setSize(600,260);p.chooseMode(visualKind);p.resultKind=visualKind;p.items.clear();
        p.savedView=false;p.jobState="ready";p.resultLoaded=true;p.resultId="synthetic-view-only";
        const bool notes=p.resultKind=="transcribe",beatView=p.resultKind=="beats";
        for(int i=0;i<(notes?32:8);++i)p.items.push_back(notes?object({{"pitch",60+i%12},{"start_seconds",i*.25},{"duration_seconds",.2},{"velocity",80},{"channel",1}})
            :beatView?object({{"time_seconds",i*.5+.125},{"is_downbeat",i%4==0}})
            :object({{"id","synthetic-"+juce::String(i)},{"label",i%2?"G:7":"C:maj7"},{"start_seconds",i*1.0},{"end_seconds",i+1.0},{"score",.6},{"uncertain",false}}));
        if(beatView){
            p.beatDuration=4.;p.beatBpm.setText("120",false);p.beatFirst.setText("0.125000",false);p.beatMeter.setSelectedId(4,juce::dontSendNotification);
            juce::Array<juce::var> peaks;for(int i=0;i<128;++i)peaks.add(.2+.5*std::abs(std::sin(i*.23)));p.beatPeaks=peaks;
            p.halfTempo.onClick();if(p.beatBpm.getText().getDoubleValue()!=60)return juce::Result::fail("Beat half-tempo correction failed.");
            p.doubleTempo.onClick();if(p.beatBpm.getText().getDoubleValue()!=120)return juce::Result::fail("Beat double-tempo correction failed.");
        }
        p.total=int(p.items.size());p.results.updateContent();p.updateControls();
        const auto capture=createComponentSnapshot(getLocalBounds());
        auto output=directory.getChildFile("ui-analysis-"+p.resultKind+"-"+language+"-synthetic.png").createOutputStream();
        if(!output||!juce::PNGImageFormat().writeImageToStream(capture,*output))return juce::Result::fail("Cannot capture analysis visual fixture.");
        if(p.hitRegions.size()!=p.items.size())return juce::Result::fail("Analysis visual omitted paged notes/chords.");
        for(const auto& bounds:p.hitRegions)if(!p.canvas.getLocalBounds().toFloat().expanded(1.f).contains(bounds))return juce::Result::fail("Analysis visual escaped its viewport.");
        p.canvas.select(p.hitRegions.front().getCentre());
        if(p.results.getSelectedRow()!=0)return juce::Result::fail("Analysis visual selection does not target the real page item.");
        if(beatView){
            if(std::abs(p.beatFirst.getText().getDoubleValue()-.125)>1e-8)return juce::Result::fail("Beat line selection did not correct the first beat.");
            for(const auto size:{juce::Point<int>(540,210),juce::Point<int>(930,308)}){
                setSize(size.x,size.y);p.updateControls();
                if(p.accept.getBounds().intersects(p.useTempo.getBounds())||p.beatFirst.getBounds().intersects(p.start.getBounds())||p.beats.getBounds().getRight()>getWidth()-92)
                    return juce::Result::fail("Beat controls overlap at a supported dock size.");
                auto shot=directory.getChildFile("ui-analysis-beats-"+juce::String(size.x)+"x"+juce::String(size.y)+"-"+language+"-synthetic.png").createOutputStream();
                if(!shot||!juce::PNGImageFormat().writeImageToStream(createComponentSnapshot(getLocalBounds()),*shot))return juce::Result::fail("Cannot capture beat panel fixture.");
            }
            const auto previousHit=p.hitRegions.back().getCentre();p.items.clear();p.canvas.select(previousHit);
            report.setProperty("analysis_ui_stale_beat_hit_is_bounded",true);
        }
    }
    const auto actualCapabilities=p.capabilities;
    p.beatPeaks=juce::Array<juce::var>{.5};p.beatDuration=4;p.beatFirst.setText(".125",false);
    p.applyResultState(object({{"kind","score"}}));
    if(!p.beatPeaks.isVoid()||p.beatDuration!=0||p.beatFirst.getText().isNotEmpty())return juce::Result::fail("Score view reused a previous source waveform.");
    p.capabilities=object({{"providers",juce::Array<juce::var>{object({{"kind","score"},{"execution","cloud"},{"model_id","sheetsage2 (synthetic UI)"},{"available",true},{"default",true}})}}});
    for(const auto* language:{"en","zh-CN"})for(const auto size:{juce::Point<int>(600,260),juce::Point<int>(930,308)})for(const bool saved:{false,true}){
        setUiLanguage(language,false);setSize(size.x,size.y);p.chooseMode("score");p.resultTaskKind="score";p.resultKind="structure";p.savedView=p.savedScore=saved;p.resultLoaded=true;p.resultId="synthetic-score-ui";p.jobState="ready";p.candidateHasContent=true;
        p.scoreComponent.setSelectedId(4,juce::dontSendNotification);p.items={object({{"label","Intro · synthetic"},{"start_seconds",0.0},{"end_seconds",4.0}}),object({{"label","Verse"},{"start_seconds",4.0},{"end_seconds",12.0}})};p.total=2;p.results.updateContent();p.updateControls();
        for(auto* control:std::initializer_list<juce::Component*>{&p.execution,&p.model,&p.scoreComponent,&p.showSaved})if(!control->isVisible()||control->getWidth()<30||!getLocalBounds().contains(control->getBounds()))return juce::Result::fail("Hybrid score controls escape the lower dock.");
        if(p.quality.isVisible()||p.instrument.isVisible()||p.vocabulary.isVisible()||saved&&p.accept.isVisible())return juce::Result::fail("Cloud score exposes ignored controls or re-imports saved metadata.");
        auto output=directory.getChildFile("ui-score-"+juce::String(saved?"saved-":"candidate-")+juce::String(size.x)+"-"+language+"-synthetic.png").createOutputStream();
        if(!output||!juce::PNGImageFormat().writeImageToStream(createComponentSnapshot(getLocalBounds()),*output))return juce::Result::fail("Cannot capture score dock.");
    }
    p.capabilities=actualCapabilities;p.savedView=p.savedScore=false;p.modelIds.clear();p.resultTaskKind.clear();setUiLanguage(oldLanguage,false);p.items.clear();p.total=0;p.resultId.clear();p.resultLoaded=false;p.jobState.clear();p.updateControls();
    const auto after = p.session.snapshot();
    report.setProperty("analysis_ui_range_mapping", rangeApplied);
    report.setProperty("analysis_ui_read_only_navigation", before.revision == after.revision && before.projectId == after.projectId);
    report.setProperty("analysis_ui_empty_saved_chords", true);
    report.setProperty("analysis_ui_synthetic_stale_undo_redo_projection", true);
    report.setProperty("analysis_ui_bilingual_piano_and_chord_visual_fixtures",true);
    report.setProperty("analysis_ui_beats_first_downbeat_half_double_and_compact_actions",true);
    if (!rangeApplied || before.revision != after.revision || before.projectId != after.projectId)
        return juce::Result::fail("Analysis navigation changed the project or mapped the range incorrectly.");
    return juce::Result::ok();
}
}
