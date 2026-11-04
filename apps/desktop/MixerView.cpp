#include "MixerView.h"
#include "FocusTheme.h"
#include <algorithm>
#include <cmath>

namespace emusician {
namespace {
juce::var mixObject(std::initializer_list<std::pair<juce::Identifier, juce::var>> fields)
{
    auto* result = new juce::DynamicObject;
    for (const auto& field : fields) result->setProperty(field.first, field.second);
    return juce::var(result);
}
juce::String panText(double value)
{
    if (std::abs(value) < 0.005) return "C";
    return (value < 0 ? "L " : "R ") + juce::String(int(std::round(std::abs(value) * 100.0)));
}
}

struct MixerView::Impl {
    struct Strip final : juce::Component {
        Strip(Impl& parent, juce::String trackId) : p(parent), id(std::move(trackId))
        {
            setWantsKeyboardFocus(true);
            for (auto* c : std::initializer_list<juce::Component*>{ &title, &route, &device, &details, &mute, &solo, &arm, &gain, &pan, &peakReset })
                addAndMakeVisible(c);
            title.getProperties().set("flat", true);
            title.onClick = [this] {
                if (isMaster()) { showDetails(); return; }
                auto& parent = p; const auto trackId = id;
                const auto changed = parent.owner.onUserStateChange;
                parent.session.endEditGesture(); parent.session.selectTrack(trackId);
                parent.owner.update(parent.session.snapshot());
                // Selection may replace the compact strip. Do not read this afterward.
                if (changed) changed();
            };
            route.onClick = [this] { showDetails(); };
            details.onClick = [this] { showDetails(); };
            device.onClick = [this] {
                // Existing devices are managed in the original signal-chain panel.
                // Empty chains go directly to the established plug-in browser.
                if (plugins().empty()) { const auto browse = p.owner.onBrowsePlugins; const auto trackId = id; if (browse) browse(trackId); }
                else showDetails();
            };
            gain.setSliderStyle(juce::Slider::LinearVertical);
            gain.setTextBoxStyle(juce::Slider::TextBoxBelow, false, 76, 24);
            gain.setRange(-60, 6, 0.1); gain.setTextValueSuffix(" dB"); gain.setNumDecimalPlacesToDisplay(1);
            gain.setDoubleClickReturnValue(true, isMaster() ? -6.0 : 0.0);
            gain.onDragStart = [this] { beginGesture(); };
            gain.onDragEnd = [this] { endGesture(); };
            gain.onValueChange = [this] {
                if (updating) return;
                run(isMaster() ? "set_master_gain" : "set_track_gain",
                    mixObject({ {"track_id", id}, {"gain_db", gain.getValue()} }));
            };
            pan.setSliderStyle(juce::Slider::LinearHorizontal);
            pan.setTextBoxStyle(juce::Slider::TextBoxBelow, false, 76, 22);
            pan.setRange(-1, 1, 0.01); pan.setDoubleClickReturnValue(true, 0.0);
            pan.textFromValueFunction = [](double value) { return panText(value); };
            pan.valueFromTextFunction = [](const juce::String& text) {
                const auto value = text.trim().toUpperCase();
                if (value == "C") return 0.0;
                if (value.startsWithChar('L') || value.startsWithChar('R'))
                    return juce::jlimit(0.0, 1.0, value.substring(1).trim().getDoubleValue() / 100.0) * (value.startsWithChar('L') ? -1.0 : 1.0);
                return juce::jlimit(-1.0, 1.0, value.getDoubleValue());
            };
            // setValue(0) is a no-op for a newly constructed slider; refresh the
            // already-created text box after installing the C / L / R formatter.
            pan.updateText();
            pan.onDragStart = [this] { beginGesture(); }; pan.onDragEnd = [this] { endGesture(); };
            pan.onValueChange = [this] { if (!updating) run("set_track_pan", mixObject({ {"track_id", id}, {"pan", pan.getValue()} })); };
            mute.onClick = [this] { if (const auto* t = track()) run("set_track_muted", mixObject({ {"track_id", id}, {"muted", !t->muted} })); };
            solo.onClick = [this] { if (const auto* t = track()) run("set_track_solo", mixObject({ {"track_id", id}, {"solo", !t->solo} })); };
            arm.onClick = [this] { if (const auto* t = track()) run("set_track_armed", mixObject({ {"track_id", id}, {"armed", !t->armed} })); };
            peakReset.onClick = [this] { run("reset_meters", mixObject({})); };
            mute.setTooltip("Mute this track"); solo.setTooltip("Solo this track");
            arm.setTooltip("Arm for recording. Choose an input in I/O first.");
            gain.setTooltip("Output gain, -60 to +6 dB. Double-click resets. One drag is one Undo step.");
            pan.setTooltip("Stereo balance. C = centre; L/R 100 = full left/right. Double-click resets.");
            route.setTooltip("Track output, recording inputs and sends");
            details.setTooltip("Open devices, I/O, sends and automation for this channel");
            device.setTooltip("Open the device chain; an empty chain opens the plug-in browser");
        }
        ~Strip() override { endGesture(); }
        bool isMaster() const { return id == "master"; }
        const EngineSession::TrackSnapshot* track() const {
            for (const auto& t : p.state.tracks) if (t.id == id) return &t;
            return nullptr;
        }
        const std::vector<EngineSession::PluginSlotSnapshot>& plugins() const {
            if (isMaster()) return p.state.masterPlugins;
            if (const auto* t = track()) return t->plugins;
            static const std::vector<EngineSession::PluginSlotSnapshot> empty; return empty;
        }
        void showDetails() {
            auto& parent = p; const auto trackId = id;
            const auto show = parent.owner.onShowTrackDetails;
            const auto changed = parent.owner.onUserStateChange;
            juce::Component::SafePointer<MixerView> safe(&parent.owner);
            parent.session.endEditGesture();
            if (!isMaster()) parent.session.selectTrack(trackId);
            if (show) show(trackId);
            if (safe && changed) changed();
        }
        void beginGesture() { if (!gesture) { gesture = true; p.session.beginEditGesture(); } }
        void endGesture() { if (gesture) { gesture = false; p.session.endEditGesture(); } }
        void run(const juce::String& command, const juce::var& args) {
            auto& parent = p;
            const auto notify = parent.owner.onResult;
            const auto result = parent.session.execute(command, args, parent.state.revision);
            parent.owner.update(parent.session.snapshot());
            // A concurrent selection can rebuild a compact strip during update.
            // The parent and copied callback outlive this strip; no member read follows.
            if (notify) notify(result);
        }
        juce::Colour colour() const {
            if (isMaster()) return juce::Colour(0xffafb8c1);
            for (size_t i = 0; i < p.state.tracks.size(); ++i)
                if (p.state.tracks[i].id == id) return focus::trackColour(p.state.tracks[i].kind, int(i));
            return focus::muted;
        }
        void syncScalars() {
            const auto* t = track();
            const double nextGain = isMaster() ? p.state.gainDb : t ? t->gainDb : 0.0;
            const double nextPan = t ? t->pan : 0.0;
            // A changed snapshot may arrive while a slider is held. Its revision
            // is cached, but the control still needs one readback after release.
            // Comparing scalars on telemetry ticks is cheap and emits no command.
            if (!gain.isMouseButtonDown() && std::abs(gain.getValue() - nextGain) > 0.00001)
                gain.setValue(nextGain, juce::dontSendNotification);
            if (!pan.isMouseButtonDown() && std::abs(pan.getValue() - nextPan) > 0.00001)
                pan.setValue(nextPan, juce::dontSendNotification);
        }
        void update() {
            updating = true; const auto* t = track(); const bool master = isMaster();
            const bool busy = p.state.recording || p.state.recordingFinalizing;
            title.setButtonText(master ? "Master" : t ? t->name : "No track");
            title.setTooltip(title.getButtonText());
            title.setEnabled(master || t != nullptr);
            title.setToggleState(!master && id == p.state.selectedTrackId, juce::dontSendNotification);
            juce::String destination = "Master";
            if (t && t->outputTargetId != "master") {
                destination = t->outputTargetId;
                for (const auto& candidate : p.state.tracks) if (candidate.id == t->outputTargetId) destination = candidate.name;
            }
            route.setButtonText(master ? "Stereo out" : "To " + destination);
            route.setEnabled(!busy && (master || t != nullptr));
            const auto& chain = plugins(); device.setButtonText(chain.empty() ? "Add device" : chain.front().name + (chain.size() > 1 ? " +" + juce::String(int(chain.size() - 1)) : ""));
            gain.setName((master ? juce::String("Master") : t ? t->name : id) + " output gain");
            pan.setName((t ? t->name : id) + " pan");
            syncScalars();
            gain.setEnabled((master || t != nullptr) && !busy); pan.setEnabled(t != nullptr && !busy);
            mute.setToggleState(t && t->muted, juce::dontSendNotification); solo.setToggleState(t && t->solo, juce::dontSendNotification);
            arm.setToggleState(t && t->armed, juce::dontSendNotification);
            mute.setEnabled(t && !busy); solo.setEnabled(t && !busy);
            arm.setEnabled(t && t->kind != "bus" && t->inputDeviceId.isNotEmpty() && !busy);
            device.setEnabled(!busy && (master || t)); details.setEnabled(!busy && (master || t));
            updateMeters(master ? p.state.masterPeakLeftDb : t ? t->peakLeftDb : -100.0f,
                         master ? p.state.masterPeakRightDb : t ? t->peakRightDb : -100.0f,
                         master ? p.state.masterOverloaded : t && t->overloaded);
            updating = false; repaint();
        }
        void updateMeters(float nextLeft, float nextRight, bool nextOverload) {
            if (left != nextLeft || right != nextRight || overload != nextOverload || peakReset.getButtonText().isEmpty()) {
                left = nextLeft; right = nextRight; overload = nextOverload;
                peakReset.setButtonText(overload ? "CLIP" : "Peak");
                peakReset.setToggleState(overload, juce::dontSendNotification);
                peakReset.setTooltip("L " + juce::String(left, 1) + " dB / R " + juce::String(right, 1) + " dB. Click to reset overload indicators.");
                repaint(meter);
            }
        }
        void resized() override {
            const int width = getWidth(); const int content = width - 16;
            title.setBounds(5, 8, width - 10, 30);
            route.setBounds(8, 59, content, 28); device.setBounds(8, 93, content, 28);
            pan.setVisible(!isMaster()); pan.setBounds(10, 149, width - 20, 46);
            const int faderTop = 212;
            const int faderBottom = juce::jmax(faderTop + 100, getHeight() - 118);
            gain.setBounds(5, faderTop, width - 26, faderBottom - faderTop);
            meter = {width - 23, faderTop + 9, 15, juce::jmax(60, gain.getHeight() - 39)};
            peakReset.setBounds(8, faderBottom + 4, content, 24);
            mute.setVisible(!isMaster()); solo.setVisible(!isMaster()); arm.setVisible(!isMaster());
            const int controlsY = faderBottom + 33;
            const int controlWidth = juce::jmin(30, (width - 22) / 3);
            const int controlsX = (width - controlWidth * 3 - 8) / 2;
            mute.setBounds(controlsX, controlsY, controlWidth, 28);
            solo.setBounds(controlsX + controlWidth + 4, controlsY, controlWidth, 28);
            arm.setBounds(controlsX + controlWidth * 2 + 8, controlsY, controlWidth, 28);
            details.setBounds(8, getHeight() - 40, content, 30);
        }
        void paint(juce::Graphics& g) override {
            g.fillAll(focus::panel); g.setColour(focus::line); g.drawVerticalLine(getWidth() - 1, 0, float(getHeight()));
            g.setColour(colour()); g.fillRect(0, 0, getWidth(), 2);
            g.setColour(focus::muted); g.setFont(focus::font(11));
            const auto* t = track();
            g.drawText(isMaster() ? "MAIN OUTPUT" : !t ? "SELECT A TRACK" : t->kind == "instrument" ? "MIDI" : t->kind == "bus" ? "BUS" : "AUDIO", 10, 36, getWidth() - 20, 18, juce::Justification::centredLeft);
            g.drawText(isMaster() ? "Stereo output" : "Pan / balance", 10, 128, getWidth() - 20, 19, juce::Justification::centredLeft);
            if (isMaster()) { g.setColour(focus::text); g.drawText("L  /  R", 10, 158, getWidth() - 20, 24, juce::Justification::centred); }
            g.setColour(focus::muted); g.drawText("Gain", 10, 192, getWidth() - 20, 18, juce::Justification::centredLeft);
            g.setFont(focus::font(10));
            for (const int db : { 6, 0, -12, -24, -48, -60 }) {
                // Short faders retain a useful scale without overlapping adjacent labels.
                if (meter.getHeight() < 160 && db == 6) continue;
                if (meter.getHeight() < 110 && (db == -12 || db == -48)) continue;
                const int y = meter.getBottom() - int(std::round(meter.getHeight() * (db + 60.0) / 66.0));
                g.drawText(db > 0 ? "+" + juce::String(db) : juce::String(db), 5, y - 7, 25, 14, juce::Justification::centredRight);
            }
            g.setColour(focus::base); g.fillRect(meter);
            const auto amount = [](float value) { return juce::jlimit(0.0f, 1.0f, (value + 60.0f) / 66.0f); };
            const int l = int(std::round(meter.getHeight() * amount(left))), r = int(std::round(meter.getHeight() * amount(right)));
            g.setColour(left >= 0 ? focus::danger : focus::green); g.fillRect(meter.getX(), meter.getBottom() - l, 6, l);
            g.setColour(right >= 0 ? focus::danger : focus::green); g.fillRect(meter.getX() + 9, meter.getBottom() - r, 6, r);
            const int zero = meter.getBottom() - int(std::round(meter.getHeight() * 60.0 / 66.0));
            g.setColour(focus::muted); g.drawHorizontalLine(zero, float(meter.getX()), float(meter.getRight()));
            if (hasKeyboardFocus(false)) { g.setColour(focus::accent); g.drawRect(getLocalBounds().reduced(2), 1); }
        }
        Impl& p; juce::String id;
        juce::TextButton title, route, device, details { "Details" }, mute { "M" }, solo { "S" }, arm { "R" }, peakReset;
        juce::Slider gain, pan; juce::Rectangle<int> meter;
        bool updating = false, gesture = false, overload = false;
        float left = -100, right = -100;
    };
    Impl(MixerView& component, EngineSession& engine) : owner(component), session(engine) {
        owner.addAndMakeVisible(viewport); viewport.setViewedComponent(&canvas, false);
        viewport.setScrollBarsShown(false, true); viewport.setScrollBarThickness(10);
        viewport.setScrollOnDragEnabled(false);
        owner.setTitle("Mixer"); owner.setDescription("Shared track and master gain, pan, mute, solo, record arm and actual stereo peak meters.");
    }
    ~Impl() { viewport.setViewedComponent(nullptr, false); }
    void rebuildIfNeeded() {
        juce::StringArray ids;
        if (compact) {
            for (const auto& t : state.tracks) if (t.id == state.selectedTrackId) ids.add(t.id);
            if (ids.isEmpty()) ids.add(juce::String());
        }
        else { for (const auto& t : state.tracks) ids.add(t.id); }
        ids.add("master");
        if (ids == visibleIds) return;
        visibleIds = ids; strips.clear();
        for (const auto& id : visibleIds) {
            auto strip = std::make_unique<Strip>(*this, id); canvas.addAndMakeVisible(*strip);
            strip->update(); strips.push_back(std::move(strip));
        }
        owner.resized();
    }
    MixerView& owner; EngineSession& session; EngineSession::Snapshot state;
    bool compact = false; juce::Viewport viewport; juce::Component canvas;
    juce::StringArray visibleIds; std::vector<std::unique_ptr<Strip>> strips;
};
MixerView::MixerView(EngineSession& session) : impl(std::make_unique<Impl>(*this, session)) { update(session.snapshot()); }
MixerView::~MixerView() = default;
void MixerView::setCompact(bool compact) { if (impl->compact != compact) { impl->compact = compact; impl->rebuildIfNeeded(); resized(); repaint(); } }
void MixerView::update(const EngineSession::Snapshot& state) {
    auto& p = *impl;
    bool changed = p.state.projectId != state.projectId || p.state.revision != state.revision
        || p.state.selectedTrackId != state.selectedTrackId || p.state.tracks.size() != state.tracks.size()
        || p.state.recording != state.recording || p.state.recordingFinalizing != state.recordingFinalizing;
    if (!changed) for (size_t i = 0; i < state.tracks.size(); ++i)
        if (state.tracks[i].armed != p.state.tracks[i].armed || state.tracks[i].inputDeviceId != p.state.tracks[i].inputDeviceId) { changed = true; break; }
    if (changed || p.strips.empty()) {
        p.state = state; p.rebuildIfNeeded(); for (auto& strip : p.strips) strip->update();
    } else {
        // Immutable music projections do not get recopied for each telemetry tick.
        // Only the actual meters invalidate their small pixel rectangles.
        for (auto& strip : p.strips) {
            strip->syncScalars();
            if (strip->isMaster()) strip->updateMeters(state.masterPeakLeftDb, state.masterPeakRightDb, state.masterOverloaded);
            else for (const auto& track : state.tracks) if (track.id == strip->id) {
                strip->updateMeters(track.peakLeftDb, track.peakRightDb, track.overloaded); break;
            }
        }
    }
}
void MixerView::resized() {
    if (!impl) return; auto& p = *impl;
    p.viewport.setBounds(0, 33, getWidth(), juce::jmax(0, getHeight() - 33));
    const int count = juce::jmax(1, int(p.strips.size()));
    bool horizontal = !p.compact && count * 142 > getWidth();
    bool vertical = p.viewport.getHeight() - (horizontal ? 10 : 0) < 450;
    int availableWidth = juce::jmax(1, getWidth() - (vertical ? 10 : 0));
    if (!p.compact && count * 142 > availableWidth) horizontal = true;
    vertical = p.viewport.getHeight() - (horizontal ? 10 : 0) < 450;
    availableWidth = juce::jmax(1, getWidth() - (vertical ? 10 : 0));
    const int stripWidth = p.compact ? juce::jmax(1, availableWidth / count) : 142;
    const int contentWidth = p.compact ? availableWidth : juce::jmax(availableWidth, stripWidth * count);
    const int contentHeight = juce::jmax(450, p.viewport.getHeight() - (horizontal ? 10 : 0));
    p.viewport.setScrollBarsShown(vertical, horizontal);
    p.canvas.setSize(contentWidth, contentHeight);
    int x = 0;
    for (size_t i = 0; i < p.strips.size(); ++i) {
        const int width = p.compact && i + 1 == p.strips.size() ? contentWidth - x : stripWidth;
        p.strips[i]->setBounds(x, 0, width, contentHeight); x += width;
    }
}
void MixerView::paint(juce::Graphics& g) {
    g.fillAll(focus::canvas); g.setColour(focus::line); g.drawHorizontalLine(32, 0, float(getWidth()));
    g.setColour(focus::text); g.setFont(focus::font(13, juce::Font::bold));
    g.drawText(impl->compact ? "Selected track / Master" : "Mixer", 12, 0, getWidth() - 24, 32, juce::Justification::centredLeft);
}
juce::Result MixerView::runInteractionSmokeTest(juce::DynamicObject& report) {
    auto& p = *impl; update(p.session.snapshot());
    if (p.state.tracks.empty()) return juce::Result::fail("Mixer smoke requires an isolated session with a track.");
    p.session.selectTrack(p.state.tracks.front().id); update(p.session.snapshot());
    const auto id = p.state.selectedTrackId; const auto initial = p.state;
    setCompact(true); setSize(248, 620);
    if (p.strips.size() != 2 || p.strips[0]->id != id || !p.strips[1]->isMaster()) return juce::Result::fail("Compact mixer did not show selected track and Master.");
    auto& strip = *p.strips.front();
    const auto gainBefore = strip.track()->gainDb, panBefore = strip.track()->pan;
    strip.gain.onDragStart(); strip.gain.setValue(gainBefore == -9 ? -8 : -9, juce::sendNotificationSync); strip.gain.setValue(-7.5, juce::sendNotificationSync); strip.gain.onDragEnd();
    if (std::abs(p.session.snapshot().tracks.front().gainDb + 7.5f) > 0.01f) return juce::Result::fail("Mixer gain did not use the shared engine state.");
    auto result = p.session.undo(p.session.snapshot().revision); if (result.failed()) return result; update(p.session.snapshot());
    if (std::abs(p.state.tracks.front().gainDb - gainBefore) > 0.01f) return juce::Result::fail("One Undo did not restore the mixer gain drag.");
    strip.pan.setValue(panBefore == 0.25f ? -0.25 : 0.25, juce::sendNotificationSync);
    if (std::abs(p.session.snapshot().tracks.front().pan - strip.pan.getValue()) > 0.01f) return juce::Result::fail("Mixer pan did not commit.");
    result = p.session.undo(p.session.snapshot().revision); if (result.failed()) return result; update(p.session.snapshot());
    strip.mute.onClick(); if (p.state.tracks.front().muted == initial.tracks.front().muted) return juce::Result::fail("Mixer mute did not commit.");
    result = p.session.undo(p.session.snapshot().revision); if (result.failed()) return result; update(p.session.snapshot());
    strip.solo.onClick(); if (p.state.tracks.front().solo == initial.tracks.front().solo) return juce::Result::fail("Mixer solo did not commit.");
    result = p.session.undo(p.session.snapshot().revision); if (result.failed()) return result; update(p.session.snapshot());
    auto& master = *p.strips.back(); const auto masterBefore = p.state.gainDb;
    master.gain.setValue(masterBefore == -9 ? -8 : -9, juce::sendNotificationSync);
    if (std::abs(p.session.snapshot().gainDb - master.gain.getValue()) > 0.01f) return juce::Result::fail("Mixer Master gain did not commit.");
    result = p.session.undo(p.session.snapshot().revision); if (result.failed()) return result; update(p.session.snapshot());
    if (std::abs(p.state.gainDb - masterBefore) > 0.01f) return juce::Result::fail("Mixer Master gain Undo failed.");
    // Two projections share the same authority. A control can temporarily retain
    // a drag value after its model revision was consumed; the next unchanged
    // snapshot must repair it, without another edit or a full projection rebuild.
    MixerView sibling(p.session); sibling.setCompact(true); sibling.setSize(248, 620);
    strip.gain.setValue(gainBefore == -11.0f ? -10.0 : -11.0, juce::sendNotificationSync);
    const auto shared = p.session.snapshot(); sibling.update(shared);
    const auto& siblingTrack = *sibling.impl->strips.front();
    if (std::abs(siblingTrack.gain.getValue() - strip.gain.getValue()) > 0.01)
        return juce::Result::fail("The second mixer did not read back the first mixer's edit.");
    strip.gain.setValue(-31.0, juce::dontSendNotification);
    strip.pan.setValue(panBefore == 0.43f ? -0.43 : 0.43, juce::dontSendNotification);
    master.gain.setValue(-37.0, juce::dontSendNotification);
    update(shared);
    if (p.session.snapshot().revision != shared.revision
        || std::abs(strip.gain.getValue() - shared.tracks.front().gainDb) > 0.01
        || std::abs(strip.pan.getValue() - shared.tracks.front().pan) > 0.01
        || std::abs(master.gain.getValue() - shared.gainDb) > 0.01)
        return juce::Result::fail("Unchanged-revision telemetry did not repair deferred mixer scalar readback.");
    bool panLabelMatches = false;
    for (auto* child : strip.pan.getChildren())
        if (auto* label = dynamic_cast<juce::Label*>(child)) panLabelMatches = label->getText() == panText(strip.pan.getValue());
    if (!panLabelMatches) return juce::Result::fail("Mixer pan text does not show its C / L / R value.");
    result = p.session.undo(p.session.snapshot().revision); if (result.failed()) return result; update(p.session.snapshot());
    report.setProperty("mixer_deferred_scalar_readback_same_revision", true);
    report.setProperty("mixer_two_views_share_gain_and_pan_text", true);
    setCompact(false); setSize(800, 620);
    if (p.strips.size() != p.state.tracks.size() + 1 || p.state.selectedTrackId != id) return juce::Result::fail("Expanded mixer changed selection or omitted channels.");
    report.setProperty("mixer_compact_expanded_shared_state", true);
    report.setProperty("mixer_gain_gesture_pan_mute_solo_master_undo", true);
    return juce::Result::ok();
}
}
