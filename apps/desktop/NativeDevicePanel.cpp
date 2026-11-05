#include "NativeDevicePanel.h"
#include "SampleWaveform.h"
#include "DeviceControlStyle.h"
#include <juce_cryptography/juce_cryptography.h>
#include <array>
#include <cmath>

namespace emusician {
namespace {
const juce::Colour ink(0xff171817), quiet(0xff626560), rule(0xffc6c9c3), paper(0xfffefefd);
juce::Font mono(float size) { return juce::Font(juce::FontOptions(juce::Font::getDefaultMonospacedFontName(), size, juce::Font::plain)); }
juce::var object(std::initializer_list<std::pair<juce::Identifier, juce::var>> fields) {
    auto* result = new juce::DynamicObject;
    for (const auto& field : fields) result->setProperty(field.first, field.second);
    return juce::var(result);
}
}

struct NativeDevicePanel::Impl {
    struct PadButton final : juce::TextButton {
        std::function<void()> audition;
        bool previewDown = false;
        void paintButton(juce::Graphics& g, bool hover, bool down) override {
            const auto a = getLocalBounds().toFloat().reduced(0.5f);
            g.setColour(getToggleState() ? ink : down ? rule : hover ? juce::Colour(0xffeeefeb) : paper); g.fillRect(a);
            g.setColour(getToggleState() ? paper : isEnabled() ? ink : quiet); g.drawRect(a);
            const auto label = getButtonText(); const auto split = label.indexOf("  ");
            const bool compact = getHeight() < 40;
            g.setFont(mono(compact ? 10.0f : 11.0f)); g.drawText(label.substring(0, split), 6, 2, getWidth() - 12, compact ? 12 : 16, juce::Justification::topLeft);
            g.drawText(label.substring(split + 2), 6, getHeight() - (compact ? 15 : 23), getWidth() - 30, compact ? 13 : 18, juce::Justification::centredLeft, true);
            if (!label.endsWith("empty")) { juce::Path play; const float x = float(getWidth() - 18), y = float(getHeight() - (compact ? 9 : 17)); play.addTriangle(x, y - 4, x, y + 4, x + 7, y); g.fillPath(play); }
            if (hasKeyboardFocus(true)) g.drawRect(getLocalBounds().reduced(3), 1);
        }
        void mouseDown(const juce::MouseEvent& event) override {
            previewDown = event.mods.isLeftButtonDown() && event.x >= getWidth() - 27 && event.y >= getHeight() - 28 && !getButtonText().endsWith("empty");
            if (!previewDown) juce::TextButton::mouseDown(event);
        }
        void mouseUp(const juce::MouseEvent& event) override {
            if (previewDown) { previewDown = false; if (isEnabled() && getLocalBounds().contains(event.getPosition())) { if (onClick) onClick(); if (audition) audition(); } }
            else juce::TextButton::mouseUp(event);
        }
        void mouseDoubleClick(const juce::MouseEvent&) override { if (isEnabled() && !getButtonText().endsWith("empty") && audition) audition(); }
    };
    struct Envelope final : juce::Component {
        explicit Envelope(Impl& parent) : p(parent) { setWantsKeyboardFocus(true); setTitle("Sample attack and release envelope"); setDescription("Drag A or R to edit the amplitude envelope. The horizontal handle ranges are logarithmic, not a live time display. Escape cancels. Release applies only in Gate mode."); }
        juce::Rectangle<float> plot() const { return getLocalBounds().toFloat().reduced(9, getHeight() < 40 ? 5.0f : 17.0f); }
        juce::Point<float> handle(bool attack) const {
            const auto a = plot(); const auto t = attack ? p.attack.getValue() : p.release.getValue();
            const auto n = attack ? std::log(t / .1) / std::log(20000.0) : std::log(t) / std::log(5000.0);
            return {a.getX() + a.getWidth() * float(attack ? .08 + .32 * n : .6 + .36 * n), attack ? a.getY() : a.getBottom()};
        }
        void paint(juce::Graphics& g) override {
            const auto a = plot(); if (a.getWidth() <= 0 || a.getHeight() <= 0) return;
            g.setColour(quiet); g.setFont(mono(10)); if (getHeight() >= 40) g.drawText("AMPLITUDE / A - R", 7, 0, getWidth() - 14, 15, juce::Justification::centredLeft);
            g.setColour(rule); g.drawRect(a); const auto attackPoint = handle(true), releasePoint = handle(false);
            juce::Path line; line.startNewSubPath(a.getBottomLeft()); line.lineTo(attackPoint); line.lineTo(a.getX() + a.getWidth() * .6f, a.getY());
            if (p.oneShot()) line.lineTo(a.getRight(), a.getY()); else line.lineTo(releasePoint);
            g.setColour(ink); g.strokePath(line, juce::PathStrokeType(1.5f));
            g.fillEllipse(attackPoint.x - 4, attackPoint.y - 4, 8, 8);
            if (!p.oneShot()) g.fillEllipse(releasePoint.x - 4, releasePoint.y - 4, 8, 8);
            g.setColour(quiet); if (getHeight() >= 40) g.drawText(p.oneShot() ? "to sample end" : "gate / note-off", 7, getHeight() - 15, getWidth() - 14, 15, juce::Justification::centredLeft);
        }
        void mouseDown(const juce::MouseEvent& event) override {
            if (!p.valid || !event.mods.isLeftButtonDown()) return;
            const auto a = handle(true).getDistanceFrom(event.position), r = handle(false).getDistanceFrom(event.position);
            if (a > 14 && (r > 14 || p.oneShot())) return;
            moving = a <= r || p.oneShot() ? 1 : 2; changed = false; p.beginPadGesture(); grabKeyboardFocus();
        }
        void mouseDrag(const juce::MouseEvent& event) override {
            if (!moving || !p.valid) return;
            const auto a = plot(); if (a.getWidth() <= 0) return;
            const auto x = double((event.position.x - a.getX()) / a.getWidth());
            auto& control = moving == 1 ? p.attack : p.release;
            const auto n = juce::jlimit(0.0, 1.0, moving == 1 ? (x - .08) / .32 : (x - .6) / .36);
            control.setValue(moving == 1 ? .1 * std::pow(20000.0, n) : std::pow(5000.0, n), juce::dontSendNotification);
            changed = true; repaint();
        }
        void mouseUp(const juce::MouseEvent&) override { if (moving) { moving = 0; if (changed) p.finishPadGesture(); else p.gainDragging = false; } }
        bool keyPressed(const juce::KeyPress& key) override {
            if (moving && key == juce::KeyPress::escapeKey) { moving = 0; p.gainDragging = false; p.updateControls(); p.status.setText("Envelope edit cancelled.", juce::dontSendNotification); return true; } return false;
        }
        Impl& p; int moving = 0; bool changed = false;
    };
    Impl(NativeDevicePanel& component, EngineSession& engine, juce::String target, std::function<void(const juce::Result&)> callback)
        : owner(component), session(engine), trackId(std::move(target)), report(std::move(callback)), envelope(*this) {
        for (auto* c : std::initializer_list<juce::Component*>{ &title, &kind, &add, &sampleName, &choose, &clear, &preview, &stopPreview, &padGain, &padMute, &root, &start, &end, &apply, &attack, &release, &playbackMode, &status, &waveform, &envelope }) owner.addAndMakeVisible(c);
        title.setFont(mono(15)); sampleName.setFont(mono(13)); status.setFont(mono(12));
        status.setColour(juce::Label::textColourId, quiet);
        sampleName.setColour(juce::Label::textColourId, quiet);
        kind.addItem("sampler", 1); kind.addItem("drum rack / 16 pads", 2); kind.setSelectedId(1, juce::dontSendNotification);
        add.onClick = [this] { run("add_native_instrument", object({ {"track_id", trackId}, {"type", kind.getSelectedId() == 2 ? "drum_rack" : "sampler"} })); };
        for (int i = 0; i < int(pads.size()); ++i) {
            owner.addAndMakeVisible(pads[size_t(i)]);
            pads[size_t(i)].onClick = [this, i] { if (selectedPad != i) stopAudition(); selectedPad = i; updateControls(); };
            pads[size_t(i)].audition = [this] { if (preview.isEnabled()) preview.onClick(); };
            pads[size_t(i)].setTooltip("Select this pad. Click its triangle or double-click to preview the sample.");
        }
        choose.onClick = [this] { chooseSample(); };
        preview.setTooltip("Play the selected sample without recording or starting the timeline.");
        stopPreview.setTooltip("Stop sample preview.");
        preview.onClick = [this] {
            const auto result = session.execute("preview_native_sample", object({ {"track_id", trackId}, {"pad", selectedPad} }), 0);
            if (result.failed()) status.setText(result.getErrorMessage(), juce::dontSendNotification);
        };
        stopPreview.onClick = [this] { stopAudition(); };
        clear.onClick = [this] { run("set_native_sample", object({ {"track_id", trackId}, {"pad", selectedPad}, {"path", ""} })); };
        clear.setTooltip("Remove this pad's sample assignment. The original file is not deleted.");
        padGain.setRange(-60, 6, 0.1); attack.setRange(.1, 2000, .1); release.setRange(1, 5000, 1);
        attack.setSkewFactorFromMidPoint(40); release.setSkewFactorFromMidPoint(150);
        deviceui::configureKnob(padGain, controlLook, 0, " dB"); deviceui::configureKnob(attack, controlLook, 3, " ms"); deviceui::configureKnob(release, controlLook, 30, " ms");
        for (auto* slider : { &padGain, &attack, &release }) {
            slider->onDragStart = [this] { beginPadGesture(); };
            slider->onDragEnd = [this] { if (gainDragging) finishPadGesture(); };
            slider->onValueChange = [this] { envelope.repaint(); if (!updating && !gainDragging) writePad(); };
        }
        padGain.setTitle("Sample gain"); attack.setTitle("Sample attack"); release.setTitle("Sample release");
        attack.setTooltip("Time to fade in each note. Double-click resets; Shift-drag fine-tunes.");
        release.setTooltip("Fade after MIDI note-off in Gate mode. One-shot ignores note-off, so Release is inactive.");
        playbackMode.onClick = [this] { if (valid) writePad(currentMuted(), !oneShot()); };
        playbackMode.setTooltip("Gate releases when the key is released; One-shot plays to the sample end.");
        padMute.onClick = [this] { writePad(!currentMuted()); };
        root.setRange(0, 127, 1); deviceui::configureKnob(root, controlLook, 60);
        start.setRange(0, 1, .001); end.setRange(0, 1, .001);
        deviceui::configureKnob(start, controlLook, 0); deviceui::configureKnob(end, controlLook, 1);
        root.setTitle("Root MIDI note"); start.setTitle("Sample start fraction"); end.setTitle("Sample end fraction");
        for (auto* slider : { &root, &start, &end }) {
            slider->onDragStart = [this] { const auto s = session.snapshot(); rangeDragging = true; rangeRevision = s.revision; rangeProject = s.projectId; rangePad = selectedPad; };
            slider->onDragEnd = [this] { if (!rangeDragging) return; rangeDragging = false; writeRange(rangeRevision, rangeProject); };
            slider->onValueChange = [this] { if (!updating && !rangeDragging) writeRange(revision, projectId); };
        }
        apply.onClick = [this] {
            start.setValue(0, juce::dontSendNotification); end.setValue(1, juce::dontSendNotification); writeRange(revision, projectId);
        };
        waveform.onRangeDragStart = [this] {
            const auto s = session.snapshot(); rangeRevision = s.revision; rangeProject = s.projectId;
            rangePad = selectedPad; rangeDragging = true;
        };
        waveform.onRangeCancel = [this] { rangeDragging = false; status.setText("Sample range edit cancelled.", juce::dontSendNotification); };
        waveform.onRangeCommit = [this](double a, double b) {
            rangeDragging = false;
            const auto s = session.snapshot();
            if (!valid || s.projectId != rangeProject || s.revision != rangeRevision || selectedPad != rangePad || data["type"].toString() != "sampler") {
                first = true; update(); status.setText("Project changed; sample range edit cancelled.", juce::dontSendNotification); return;
            }
            run("set_native_sampler", object({ {"track_id", trackId}, {"root_note", int(root.getValue())}, {"start", a}, {"end", b} }), rangeRevision);
        };
        owner.setSize(780, 500);
        update();
    }
    bool targetExists(const EngineSession::Snapshot& state) const {
        for (const auto& track : state.tracks) if (track.id == trackId && track.kind == "instrument") return true;
        return false;
    }
    void stopAudition() {
        if (projectId.isNotEmpty() && session.snapshot().projectId == projectId)
            session.execute("stop_native_preview", object({ {"track_id", trackId} }), 0);
    }
    bool needsFastPolling() const {
        const auto load = data["load_status"].toString();
        const bool installed = data["type"].toString().isNotEmpty();
        return lastNativePending || (installed && (load.isEmpty() || load == "not_ready" || load == "queued" || load == "loading"));
    }
    void update() {
        const auto state = session.snapshot();
        if (projectId.isEmpty()) projectId = state.projectId;
        if (state.projectId != projectId || !targetExists(state)) {
            valid = false; title.setText("MIDI track unavailable", juce::dontSendNotification);
            status.setText("Close this window and choose an existing MIDI track.", juce::dontSendNotification);
            updateControls(); return;
        }
        valid = !state.recording && !state.recordingFinalizing && !state.nativePending;
        const bool pendingChanged = observedPending && lastNativePending != state.nativePending;
        const bool failedBeforeCommit = observedPending && lastNativePending && !state.nativePending && state.revision == revision;
        const bool changed = first || state.revision != revision || pendingChanged;
        const auto oldLoadState = data["load_status"].toString();
        const bool installed = data["type"].toString().isNotEmpty();
        const bool pending = installed && (oldLoadState.isEmpty() || oldLoadState == "not_ready" || oldLoadState == "queued" || oldLoadState == "loading");
        if ((!changed && !pending) || gainDragging || rangeDragging) { updateEnabled(); return; }
        observedPending = true; lastNativePending = state.nativePending;
        first = false; revision = state.revision;
        for (const auto& track : state.tracks) if (track.id == trackId) title.setText(track.name + " / native instrument", juce::dontSendNotification);
        juce::var result;
        const auto outcome = session.execute("get_native_instrument", object({ {"track_id", trackId} }), revision, &result);
        if (outcome.failed()) {
            // A transient read failure must not freeze an empty/stale panel
            // forever when the project revision itself did not change.
            first = true; valid = false; status.setText(outcome.getErrorMessage(), juce::dontSendNotification);
        }
        else {
            // The queue can move loading -> ready without advancing revision.
            // Refresh the waveform/hash as soon as the committed bank is ready.
            const bool loadChanged = oldLoadState != result["load_status"].toString();
            acceptData(result, changed || loadChanged);
            const auto type = data["type"].toString();
            const auto currentLoad = data["load_status"].toString();
            juce::String message;
            if (state.nativePending) message = "Sample change accepted; preparing in the background. Not committed yet.";
            else if (failedBeforeCommit) message = "Sample change was not committed. " + state.status;
            else if (type.isEmpty()) message = "Choose a built-in instrument for this MIDI track.";
            else if (currentLoad == "queued" || currentLoad == "loading") message = "Preparing samples in the background...";
            else if (currentLoad == "ready") message = "Sample preparation complete. Changes can be undone.";
            else if (currentLoad == "error") message = "Sample preparation failed: " + data["error"].toString();
            else message = "Sample readiness is not yet available. Choose a WAV sample for the selected pad.";
            status.setText(message, juce::dontSendNotification);
        }
        if (outcome.failed()) updateControls(); else updateEnabled();
    }
    void acceptData(juce::var next, bool refreshControls) {
        data = std::move(next);
        if (refreshControls) updateControls();
    }
    juce::var currentPad() const {
        if (const auto* list = data["pads"].getArray()) for (const auto& p : *list) if (int(p["index"]) == selectedPad) return p;
        return {};
    }
    bool currentMuted() const { return bool(currentPad()["muted"]); }
    bool oneShot() const { const auto p = currentPad(); return p.hasProperty("one_shot") ? bool(p["one_shot"]) : data["type"].toString() == "drum_rack"; }
    void beginPadGesture() {
        const auto s = session.snapshot(); gainDragging = true; gainRevision = s.revision; gainProject = s.projectId; gainPad = selectedPad;
    }
    void finishPadGesture() {
        gainDragging = false; const auto s = session.snapshot();
        if (!valid || s.projectId != gainProject || s.revision != gainRevision || selectedPad != gainPad) {
            first = true; update(); status.setText("Project or pad changed; parameter edit cancelled.", juce::dontSendNotification); return;
        }
        writePad();
    }
    void writeRange(std::uint64_t expected, const juce::String& project) {
        if (updating || !valid) return;
        if (start.getValue() >= end.getValue()) { updateControls(); status.setText("Start must be less than end.", juce::dontSendNotification); return; }
        if (session.snapshot().projectId != project) { first = true; update(); status.setText("Project changed; sample range edit cancelled.", juce::dontSendNotification); return; }
        run("set_native_sampler", object({ {"track_id", trackId}, {"root_note", int(root.getValue())}, {"start", start.getValue()}, {"end", end.getValue()} }), expected);
    }
    void updateEnabled() {
        const auto type = data["type"].toString();
        const bool installed = type == "sampler" || type == "drum_rack";
        kind.setVisible(!installed); add.setVisible(!installed);
        kind.setEnabled(valid && !installed); add.setEnabled(valid && !installed);
        choose.setEnabled(valid && installed && !chooser);
        clear.setEnabled(valid && installed && currentPad()["path"].toString().isNotEmpty() && !chooser);
        preview.setEnabled(valid && installed && data["load_status"].toString() == "ready" && currentPad()["sample_sha256"].toString().isNotEmpty() && !currentMuted());
        stopPreview.setEnabled(installed);
        preview.setVisible(installed); stopPreview.setVisible(installed);
        padGain.setEnabled(valid && installed); padMute.setEnabled(valid && installed);
        attack.setEnabled(valid && installed); release.setEnabled(valid && installed && !oneShot()); playbackMode.setEnabled(valid && installed);
        envelope.setEnabled(valid && installed); envelope.setVisible(installed); attack.setVisible(installed); release.setVisible(installed); playbackMode.setVisible(installed);
        root.setEnabled(valid && type == "sampler"); start.setEnabled(valid && type == "sampler"); end.setEnabled(valid && type == "sampler"); apply.setEnabled(valid && type == "sampler");
        for (auto& pad : pads) pad.setEnabled(valid && type == "drum_rack");
        waveform.setRange(data.hasProperty("start") ? double(data["start"]) : 0.0,
                          data.hasProperty("end") ? double(data["end"]) : 1.0,
                          valid && type == "sampler" && currentPad()["sample_sha256"].toString().isNotEmpty());
    }
    void updateControls() {
        updating = true;
        const auto type = data["type"].toString();
        if (type == "sampler") kind.setSelectedId(1, juce::dontSendNotification);
        if (type == "drum_rack") kind.setSelectedId(2, juce::dontSendNotification);
        if (type != "drum_rack") selectedPad = 0;
        for (int i = 0; i < int(pads.size()); ++i) {
            auto item = juce::var();
            if (const auto* list = data["pads"].getArray()) for (const auto& p : *list) if (int(p["index"]) == i) { item = p; break; }
            const auto path = item["path"].toString();
            pads[size_t(i)].setButtonText(juce::String(i + 36) + "  " + (path.isEmpty() ? "empty" : juce::File(path).getFileNameWithoutExtension()));
            pads[size_t(i)].setToggleState(i == selectedPad, juce::dontSendNotification);
            pads[size_t(i)].setVisible(type == "drum_rack");
        }
        const auto p = currentPad(); const auto path = p["path"].toString();
        const auto sampleLabel = path.isEmpty() ? juce::String("No sample loaded") : juce::File(path).getFileName();
        sampleName.setText(type == "drum_rack" ? juce::String(36 + selectedPad) + " / " + sampleLabel : sampleLabel, juce::dontSendNotification);
        sampleName.setTooltip(path);
        padGain.setValue(p.hasProperty("gain_db") ? double(p["gain_db"]) : 0.0, juce::dontSendNotification);
        attack.setValue(p.hasProperty("attack_ms") ? double(p["attack_ms"]) : 3.0, juce::dontSendNotification);
        release.setValue(p.hasProperty("release_ms") ? double(p["release_ms"]) : 30.0, juce::dontSendNotification);
        playbackMode.setButtonText(oneShot() ? "one-shot" : "gate"); envelope.repaint();
        padMute.setButtonText(currentMuted() ? "unmute" : "mute");
        root.setValue(data.hasProperty("root_note") ? int(data["root_note"]) : 60, juce::dontSendNotification);
        start.setValue(data.hasProperty("start") ? double(data["start"]) : 0.0, juce::dontSendNotification);
        end.setValue(data.hasProperty("end") ? double(data["end"]) : 1.0, juce::dontSendNotification);
        const auto hash = p["sample_sha256"].toString();
        // A pending/failed candidate must never be represented by stale audio.
        auto pcm = session.nativeSampleForDisplay(projectId, revision, trackId, data["device_id"].toString(), selectedPad, hash);
        waveform.setSource(path.isNotEmpty() ? juce::File(path) : juce::File(), hash, std::move(pcm));
        updating = false; updateEnabled(); owner.resized(); owner.repaint();
    }
    void run(const juce::String& command, juce::var args, std::uint64_t expected = 0) {
        const auto state = session.snapshot();
        const auto result = state.projectId == projectId
            ? session.execute(command, args, expected ? expected : state.revision)
            : juce::Result::fail("The project changed. Reopen the instrument panel.");
        if (report) report(result);
        first = true; update();
        owner.updatePollingInterval();
        if (result.failed()) status.setText(result.getErrorMessage(), juce::dontSendNotification);
    }
    void writePad(bool muted, bool shot) { if (!updating && valid) run("set_native_pad", object({ {"track_id", trackId}, {"pad", selectedPad}, {"gain_db", padGain.getValue()}, {"muted", muted}, {"attack_ms", attack.getValue()}, {"release_ms", release.getValue()}, {"one_shot", shot} }), revision); }
    void writePad(bool muted) { writePad(muted, oneShot()); }
    void writePad() { writePad(currentMuted()); }
    void chooseSample() {
        if (!valid || chooser) return;
        const auto state = session.snapshot(); const auto project = state.projectId; const auto version = state.revision; const auto pad = selectedPad;
        chooser = std::make_unique<juce::FileChooser>("Choose a WAV sample", juce::File(), "*.wav", true);
        chooser->launchAsync(juce::FileBrowserComponent::openMode | juce::FileBrowserComponent::canSelectFiles,
            [safe = juce::Component::SafePointer<NativeDevicePanel>(&owner), project, version, pad](const juce::FileChooser& dialog) {
                const auto path = dialog.getResult();
                juce::MessageManager::callAsync([safe, path, project, version, pad] {
                    if (!safe) return;
                    auto& p = *safe->impl; p.chooser.reset();
                    if (path == juce::File()) { p.updateEnabled(); return; }
                    if (p.session.snapshot().projectId != project) { p.status.setText("Project changed; select the sample again.", juce::dontSendNotification); p.update(); return; }
                    p.run("set_native_sample", object({ {"track_id", p.trackId}, {"pad", pad}, {"path", path.getFullPathName()} }), version);
                });
            });
        updateEnabled();
    }
    NativeDevicePanel& owner; EngineSession& session; juce::String trackId, projectId;
    std::function<void(const juce::Result&)> report; juce::var data;
    deviceui::ControlLook controlLook;
    juce::Label title, sampleName, status; juce::ComboBox kind;
    SampleWaveform waveform;
    Envelope envelope;
    juce::TextButton add { "add instrument" }, choose { "load sample..." }, clear { "clear" }, preview { "play" }, stopPreview { "stop" }, padMute { "mute" }, apply { "full sample" }, playbackMode { "gate" };
    std::array<PadButton, 16> pads;
    juce::Slider padGain, root, start, end, attack, release;
    std::unique_ptr<juce::FileChooser> chooser;
    std::uint64_t revision = 0, gainRevision = 0, rangeRevision = 0; int selectedPad = 0, gainPad = 0, rangePad = 0; juce::String gainProject, rangeProject;
    bool first = true, valid = false, updating = false, gainDragging = false, rangeDragging = false, observedPending = false, lastNativePending = false;
    bool previouslyShowing = false;
};

NativeDevicePanel::NativeDevicePanel(EngineSession& s, juce::String trackId, std::function<void(const juce::Result&)> report)
    : impl(nullptr) {
    // Impl's constructor sets the component size and can synchronously invoke
    // resized(). Initialise the pointer first so that callback sees nullptr,
    // not storage whose unique_ptr lifetime has not yet begun.
    impl = std::make_unique<Impl>(*this, s, std::move(trackId), std::move(report));
    resized(); updatePollingInterval();
}
NativeDevicePanel::~NativeDevicePanel() { stopTimer(); if (impl) impl->stopAudition(); }
void NativeDevicePanel::updatePollingInterval() {
    if (!impl || !isVisible()) { stopTimer(); return; }
    // A parent can be hidden or minimised without sending this child a
    // visibilityChanged callback. Keep a cheap probe alive while the child
    // itself remains visible so polling resumes after the parent returns.
    const int intervalMs = isShowing() && impl->needsFastPolling() ? 50 : 1000;
    if (!isTimerRunning() || getTimerInterval() != intervalMs) startTimer(intervalMs);
}
void NativeDevicePanel::visibilityChanged() {
    if (!impl) return;
    const auto showing = isShowing();
    impl->waveform.setActive(showing);
    if (showing) { impl->first = true; impl->update(); }
    else if (impl->previouslyShowing) { impl->waveform.cancelDrag(); impl->stopAudition(); }
    impl->previouslyShowing = showing;
    updatePollingInterval();
}
void NativeDevicePanel::timerCallback() {
    const auto showing = isShowing();
    if (showing != impl->previouslyShowing) {
        impl->waveform.setActive(showing);
        if (showing) impl->first = true;
        else { impl->waveform.cancelDrag(); impl->stopAudition(); }
        impl->previouslyShowing = showing;
    }
    if (showing) impl->update();
    updatePollingInterval();
}
juce::Result NativeDevicePanel::runInteractionSmokeTest(juce::DynamicObject& report, const juce::File& directory) {
    // Exercise component state only. Synthetic values never enter the engine.
    if (auto waveformResult = SampleWaveform::runSmokeTest(directory); waveformResult.failed()) return waveformResult;
    report.setProperty("native_waveform_source_and_gesture", true);
    const auto before = impl->session.snapshot(); const auto savedData = impl->data;
    const auto savedValid = impl->valid; const auto savedPad = impl->selectedPad; const auto savedSize = getBounds(); const auto savedVisible = isVisible();
    const auto restore = [&] { impl->data = savedData; impl->valid = savedValid; impl->selectedPad = savedPad; setBounds(savedSize); setVisible(savedVisible); impl->first = true; impl->update(); };
    const auto fail = [&](const char* message) { restore(); return juce::Result::fail(message); };
    impl->lastNativePending = false;
    impl->data = object({ {"type", "sampler"}, {"load_status", "loading"} });
    if (!impl->needsFastPolling()) return fail("Loading samples must poll promptly.");
    impl->data = object({ {"type", "sampler"}, {"load_status", "ready"} });
    if (impl->needsFastPolling()) return fail("Ready samples must return to low-frequency polling.");
    impl->lastNativePending = true;
    if (!impl->needsFastPolling()) return fail("Pending sample changes must poll promptly.");
    impl->lastNativePending = false;
    report.setProperty("native_device_dynamic_polling", true);
    impl->valid = true; impl->title.setText("Test MIDI track / synthetic fixture", juce::dontSendNotification);
    impl->data = object({ {"type", ""}, {"pads", juce::Array<juce::var>()} }); impl->updateControls();
    if (!impl->kind.isEnabled() || !impl->add.isEnabled() || impl->choose.isEnabled()) return fail("Native instrument empty state is incorrect.");
    juce::Array<juce::var> pads;
    for (int i = 0; i < 16; ++i) pads.add(object({ {"index", i}, {"note", 36+i}, {"path", i == 0 ? "C:/synthetic/kick.wav" : ""}, {"gain_db", 0.0}, {"muted", false} }));
    impl->data = object({ {"type", "drum_rack"}, {"pads", pads} }); impl->selectedPad = 0; impl->updateControls();
    for (int i = 0; i < 16; ++i) if (!impl->pads[size_t(i)].isVisible() || !impl->pads[size_t(i)].getButtonText().startsWith(juce::String(36+i) + "  ")) return fail("Rack did not display all 16 MIDI pads.");
    if (impl->sampleName.getText() != "36 / kick.wav") return fail("The selected pad did not display its MIDI note and sample filename.");
    impl->pads[1].onClick();
    if (impl->selectedPad != 1 || impl->sampleName.getText() != "37 / No sample loaded") return fail("Selecting an empty pad did not update the sample display.");
    // The pending candidate can fail without advancing revision: A -> candidate B -> A.
    // Both pending transitions must refresh displayed sample data, not just revision changes.
    impl->selectedPad = 0;
    impl->acceptData(object({ {"type", "drum_rack"}, {"pads", pads} }), true);
    auto candidatePads = pads;
    candidatePads.set(0, object({ {"index", 0}, {"note", 36}, {"path", "C:/synthetic/broken.wav"}, {"gain_db", 0.0}, {"muted", false} }));
    impl->acceptData(object({ {"type", "drum_rack"}, {"pads", candidatePads} }), true);
    if (impl->sampleName.getText() != "36 / broken.wav") return fail("Pending sample was not displayed.");
    impl->acceptData(object({ {"type", "drum_rack"}, {"pads", pads} }), true);
    if (impl->sampleName.getText() != "36 / kick.wav") return fail("Failed pending sample did not restore the committed sample display.");
    report.setProperty("native_device_pending_rollback_projection", true);
    // Render the actual disposable WAV already created by SampleWaveform's
    // test. The panel state remains a labeled fixture, never an engine edit.
    const auto waveformFile = directory.getChildFile("native-waveform-fixture.wav");
    auto waveformInput = waveformFile.createInputStream();
    if (!waveformInput) return fail("Could not read the owned panel waveform fixture.");
    const auto waveformHash = juce::SHA256(*waveformInput).toHexString();
    pads.getReference(0).getDynamicObject()->setProperty("path", waveformFile.getFullPathName());
    pads.getReference(0).getDynamicObject()->setProperty("sample_sha256", waveformHash);
    impl->data = object({ {"type", "drum_rack"}, {"pads", pads}, {"load_status", "ready"} }); impl->updateControls();
    const auto capture = [&](const char* name) {
        impl->title.setText((impl->data["type"].toString() == "drum_rack" ? "Drum Rack" : "Sampler") + juce::String(" / synthetic fixture"), juce::dontSendNotification);
        impl->status.setText("Generated WAV fixture / no engine edits", juce::dontSendNotification);
        impl->waveform.setSource(waveformFile, waveformHash);
        const auto deadline = juce::Time::getMillisecondCounterHiRes() + 3000;
        while (!impl->waveform.isReady() && juce::Time::getMillisecondCounterHiRes() < deadline) {
            // Pump only this view's result projection; unrelated application
            // timers must not replace synthetic state during the fixture.
            impl->waveform.setActive(false); impl->waveform.setActive(true); juce::Thread::sleep(5);
        }
        if (!impl->waveform.isReady()) return false;
        juce::MemoryOutputStream png; const auto image = createComponentSnapshot(getLocalBounds(), true);
        return juce::PNGImageFormat().writeImageToStream(image, png) && directory.getChildFile(name).replaceWithData(png.getData(), png.getDataSize());
    };
    setSize(780, 500); if (!capture("ui-native-rack-780x500.png")) return fail("Could not capture the native rack fixture.");
    setSize(700, 440);
    if (!getLocalBounds().contains(impl->pads[15].getBounds()) || impl->pads[15].getBottom() > impl->status.getY()) return fail("Rack controls do not fit the minimum window size.");
    if (impl->pads[0].getY() <= impl->pads[12].getY() || impl->pads[0].getX() >= impl->pads[3].getX()) return fail("Rack MIDI order is not bottom-to-top, left-to-right.");
    if (!capture("ui-native-rack-700x440.png")) return fail("Could not capture the compact native rack fixture.");
    setSize(1000, 260);
    if (!getLocalBounds().contains(impl->pads[0].getBounds()) || impl->pads[0].getBottom() > impl->status.getY() || impl->waveform.getBottom() > impl->padGain.getY()) return fail("Native rack cannot fit the compact workbench dock.");
    if (!capture("ui-native-rack-dock-1000x260.png")) return fail("Could not capture the compact native rack dock.");
    impl->data = object({ {"type", "sampler"}, {"pads", pads}, {"root_note", 60}, {"start", 0.0}, {"end", 1.0} }); impl->updateControls();
    impl->start.setValue(0.8, juce::dontSendNotification); impl->end.setValue(0.2, juce::dontSendNotification); impl->writeRange(impl->revision, impl->projectId);
    if (!impl->status.getText().contains("Start must be less than end")) return fail("Sampler did not report an invalid sample range.");
    impl->start.setValue(0, juce::dontSendNotification); impl->end.setValue(1, juce::dontSendNotification);
    if (impl->waveform.getBottom() > impl->root.getY()) return fail("Sampler waveform overlaps its controls.");
    if (!capture("ui-native-sampler-dock-1000x260.png")) return fail("Could not capture the compact native sampler fixture.");
    setSize(700, 440);
    if (!capture("ui-native-sampler-700x440.png")) return fail("Could not capture the larger native sampler fixture.");
    if (impl->attack.getSliderStyle() != juce::Slider::RotaryVerticalDrag || impl->attack.getTextBoxPosition() != juce::Slider::TextBoxBelow
        || !impl->release.isEnabled() || impl->oneShot()) return fail("Sampler rotary envelope controls or gate mode are incorrect.");
    impl->beginPadGesture(); impl->envelope.moving = 1; impl->attack.setValue(120, juce::dontSendNotification);
    if (!impl->envelope.keyPressed(juce::KeyPress(juce::KeyPress::escapeKey)) || impl->gainDragging || impl->envelope.moving != 0 || std::abs(impl->attack.getValue() - 3.0) > 1e-6)
        return fail("Escape did not cancel the envelope gesture.");
    impl->beginPadGesture(); impl->gainProject = "another-project"; impl->finishPadGesture();
    if (!impl->status.getText().contains("cancelled") || impl->session.snapshot().revision != before.revision)
        return fail("Stale envelope knob gesture was not rejected.");
    impl->valid = true;
    impl->data = object({ {"type", "drum_rack"}, {"pads", pads} }); impl->updateControls(); setSize(600, 250);
    if (impl->release.isEnabled() || !impl->oneShot()) return fail("One-shot release control must be inactive.");
    for (auto* control : std::initializer_list<juce::Component*>{ &impl->padGain, &impl->attack, &impl->release, &impl->playbackMode, &impl->envelope, &impl->waveform })
        if (!getLocalBounds().contains(control->getBounds()) || control->getBottom() > impl->status.getY()) return fail("Sampler controls overflow the narrow dock.");
    if (!capture("ui-native-rack-dock-600x250.png")) return fail("Could not capture narrow rack dock.");
    impl->data = object({ {"type", "sampler"}, {"pads", pads}, {"root_note", 60}, {"start", 0.0}, {"end", 1.0} }); impl->updateControls();
    if (!capture("ui-native-sampler-dock-600x250.png")) return fail("Could not capture narrow sampler dock.");
    for (const auto* type : {"sampler", "drum_rack"}) {
        impl->data = object({ {"type", type}, {"pads", pads}, {"root_note", 60}, {"start", 0.0}, {"end", 1.0} }); impl->updateControls(); setSize(600, 212);
        for (auto* control : std::initializer_list<juce::Component*>{ &impl->padGain, &impl->attack, &impl->release, &impl->playbackMode, &impl->envelope, &impl->waveform, &impl->apply, &impl->choose, &impl->clear, &impl->sampleName })
            if (control->isVisible() && (!getLocalBounds().contains(control->getBounds()) || control->getBottom() > impl->status.getY())) return fail("Native controls overflow the minimum-height dock.");
        if (impl->waveform.getBottom() > impl->padGain.getY() - 15 || impl->envelope.getBottom() > impl->attack.getY() - 15
            || impl->pads[0].getBottom() > impl->status.getY()) return fail("Native graph or pad overlaps compact control captions or status.");
        if (!capture(juce::String(type) == "sampler" ? "ui-native-sampler-dock-600x212.png" : "ui-native-rack-dock-600x212.png")) return fail("Could not capture minimum-height native dock.");
    }
    impl->data = object({ {"type", "sampler"}, {"pads", pads}, {"root_note", 60}, {"start", 0.0}, {"end", 1.0} }); impl->updateControls();
    report.setProperty("native_rotary_envelope_and_stale_gesture", true);
    // A gesture that started in a different project may not submit an edit.
    // Exercise the production callback path without mutating project state.
    impl->valid = true; impl->waveform.onRangeDragStart(); impl->rangeProject = "another-project";
    impl->waveform.onRangeCommit(0.25, 0.75);
    if (!impl->status.getText().contains("cancelled") || impl->session.snapshot().revision != before.revision)
        return fail("Stale waveform range gesture was not rejected.");
    if (!isShowing()) {
        // The parent may not have a desktop peer yet (or may be minimised).
        // A locally visible panel must remain able to detect its return.
        setVisible(true); visibilityChanged();
        if (!isTimerRunning() || getTimerInterval() != 1000) return fail("Visible child cannot recover polling when its parent is shown.");
        setVisible(false); visibilityChanged();
        if (isTimerRunning()) return fail("Explicitly hidden native device panel continued polling.");
    }
    if (impl->session.snapshot().revision != before.revision || impl->session.snapshot().projectId != before.projectId) return fail("Synthetic panel checks unexpectedly changed the project.");
    report.setProperty("native_device_panel_synthetic", true); restore(); return juce::Result::ok();
}
void NativeDevicePanel::paint(juce::Graphics& g) {
    g.fillAll(paper); g.setColour(rule); g.drawHorizontalLine(30, 12, float(getWidth() - 12));
    g.setColour(quiet); g.setFont(mono(11));
    const auto label = [&](const juce::Slider& control, const char* name) {
        if (control.isVisible()) g.drawText(name, control.getX(), control.getY() - 15, control.getWidth(), 14, juce::Justification::centred);
    };
    label(impl->root, "root / MIDI"); label(impl->start, "start / 0..1"); label(impl->end, "end / 0..1");
    label(impl->padGain, "gain"); label(impl->attack, "attack"); label(impl->release, "release");
}
void NativeDevicePanel::resized() {
    if (!impl) return;
    const int w = getWidth(), h = getHeight(), left = 12;
    const bool compactHeight = h < 250;
    impl->title.setBounds(left, 3, juce::jmax(80, w - 320), 25);
    impl->preview.setBounds(w - 150, 2, 64, 25); impl->stopPreview.setBounds(w - 82, 2, 70, 25);
    impl->kind.setBounds(juce::jmax(left, w - 300), 2, 170, 25); impl->add.setBounds(juce::jmax(left, w - 124), 2, 112, 25);
    const bool sampler = impl->data["type"].toString() == "sampler";
    const bool rack = impl->data["type"].toString() == "drum_rack";
    impl->title.setVisible(!compactHeight || (!sampler && !rack));
    impl->sampleName.setVisible(sampler || rack); impl->choose.setVisible(sampler || rack); impl->clear.setVisible(sampler || rack);
    const int rackWidth = juce::jlimit(180, 320, int(w * 0.30));
    const int padW = juce::jmax(24, (rackWidth - 3 * 4) / 4);
    const int padH = juce::jmax(24, (h - 70 - 3 * 4) / 4);
    for (int i = 0; i < 16; ++i)
        impl->pads[size_t(i)].setBounds(left + (i % 4) * (padW + 4), 38 + (3 - i / 4) * (padH + 4), padW, padH);
    impl->root.setVisible(sampler); impl->start.setVisible(sampler); impl->end.setVisible(sampler); impl->apply.setVisible(sampler);
    const int sampleLeft = rack ? left + rackWidth + 18 : left;
    const int sampleWidth = juce::jmax(0, w - sampleLeft - 12);
    impl->sampleName.setBounds(sampleLeft, 34, juce::jmax(0, sampleWidth - 235), 26);
    impl->choose.setBounds(juce::jmax(sampleLeft, w - 230), 34, 140, 26); impl->clear.setBounds(juce::jmax(sampleLeft, w - 84), 34, 72, 26);
    if (compactHeight) {
        impl->sampleName.setBounds(left, 3, juce::jmax(1, w - 298), 24);
        impl->choose.setBounds(w - 278, 3, 100, 24); impl->clear.setBounds(w - 174, 3, 54, 24);
        impl->preview.setBounds(w - 116, 3, 50, 24); impl->stopPreview.setBounds(w - 62, 3, 50, 24);
    }
    const int controlsY = h - (compactHeight ? 104 : 114), controlsH = compactHeight ? 72 : 82;
    const int envelopeWidth = juce::jlimit(145, 300, sampleWidth / 3);
    const int graphTop = compactHeight ? 38 : 64, graphHeight = juce::jmax(24, controlsY - graphTop - 20);
    impl->waveform.setBounds(sampleLeft, graphTop, juce::jmax(1, sampleWidth - envelopeWidth - 12), graphHeight);
    impl->envelope.setBounds(w - 12 - envelopeWidth, graphTop, envelopeWidth, graphHeight);
    const int buttonWidth = 90;
    const int count = sampler ? 6 : 3;
    const int unit = juce::jmax(40, (sampleWidth - buttonWidth - 8) / count);
    int x = sampleLeft;
    if (sampler) for (auto* control : { &impl->root, &impl->start, &impl->end }) { control->setBounds(x, controlsY, unit, controlsH); x += unit; }
    for (auto* control : { &impl->padGain, &impl->attack, &impl->release }) { control->setBounds(x, controlsY, unit, controlsH); x += unit; }
    const int buttonH = compactHeight ? 22 : 25, buttonStep = compactHeight ? 25 : 29;
    impl->playbackMode.setBounds(w - buttonWidth - 12, controlsY, buttonWidth, buttonH);
    impl->padMute.setBounds(w - buttonWidth - 12, controlsY + buttonStep, buttonWidth, buttonH);
    impl->apply.setBounds(w - buttonWidth - 12, controlsY + 2 * buttonStep, buttonWidth, compactHeight ? 22 : 24);
    impl->status.setBounds(left, h - 27, juce::jmax(0, w - 24), 20);
}
}
