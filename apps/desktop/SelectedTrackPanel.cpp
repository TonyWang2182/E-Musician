#include "SelectedTrackPanel.h"
#include "UiLanguage.h"
#include <algorithm>
#include <cmath>

namespace emusician {
namespace {
const juce::Colour ink(0xff171817), quiet(0xff626560), rule(0xffc6c9c3), paper(0xfffefefd);
juce::Font font(float size) { return juce::Font(juce::FontOptions(juce::Font::getDefaultMonospacedFontName(), size, juce::Font::plain)); }
juce::var object(std::initializer_list<std::pair<juce::Identifier, juce::var>> fields) {
    auto* result = new juce::DynamicObject; for (const auto& field : fields) result->setProperty(field.first, field.second); return juce::var(result);
}
}
struct SelectedTrackPanel::Impl {
    struct Curve final : juce::Component {
        explicit Curve(Impl& component) : p(component) { setWantsKeyboardFocus(true); setTitle("Automation curve"); setDescription("Double-click to add a point. Drag to move. Delete removes the selected point. One gesture is one undo step."); }
        juce::Rectangle<float> area() const { return getLocalBounds().toFloat().reduced(36, 22); }
        double span() const { return juce::jmax(8.0, p.state.duration); }
        juce::Point<float> position(const EngineSession::AutomationPointSnapshot& point) const {
            const auto a = area(); return { a.getX() + float(point.timeSeconds / span()) * a.getWidth(), a.getBottom() - point.value * a.getHeight() };
        }
        const std::vector<EngineSession::AutomationPointSnapshot>& points() const {
            if (dragging) return preview;
            if (const auto* lane = p.currentLane()) if (lane->points) return *lane->points;
            static const std::vector<EngineSession::AutomationPointSnapshot> empty; return empty;
        }
        int hit(juce::Point<float> at, const std::vector<EngineSession::AutomationPointSnapshot>& values) const {
            for (int i = int(values.size()); --i >= 0;) if (position(values[size_t(i)]).getDistanceFrom(at) < 9.0f) return i;
            return -1;
        }
        void paint(juce::Graphics& g) override {
            g.fillAll(paper); const auto a = area(); g.setColour(rule); g.drawRect(a);
            g.setFont(font(11)); g.setColour(quiet);
            g.drawText("100%", 0, int(a.getY()) - 7, 34, 18, juce::Justification::centredRight);
            g.drawText("0%", 0, int(a.getBottom()) - 8, 34, 18, juce::Justification::centredRight);
            g.drawText("0 s", int(a.getX()), int(a.getBottom()) + 2, 60, 18, juce::Justification::centredLeft);
            g.drawText(juce::String(span(), 1) + " s", int(a.getRight()) - 75, int(a.getBottom()) + 2, 75, 18, juce::Justification::centredRight);
            const auto& values = points();
            if (values.empty()) g.drawFittedText(uiText(p.currentTarget().isObject() ? "Double-click to add automation points" : "Choose an available parameter"), a.toNearestInt(), juce::Justification::centred, 2);
            juce::Path path;
            if (!values.empty()) path.startNewSubPath(position(values.front()));
            for (size_t i = 1; i < values.size(); ++i) {
                const auto a = position(values[i - 1]), b = position(values[i]); const auto c = values[i - 1].curve;
                if (c == 0) { path.lineTo(b); continue; }
                const auto scaled = juce::jlimit(-1.0f, 1.0f, c * 2.0f);
                const juce::Point<float> control { (a.x + b.x) * 0.5f + (b.x - a.x) * 0.5f * scaled,
                    (a.y + b.y) * 0.5f - (b.y - a.y) * 0.5f * scaled };
                if (std::abs(c) <= 0.5f) path.quadraticTo(control, b);
                else {
                    const auto amount = (std::abs(c) - 0.5f) * 2.0f;
                    const juce::Point<float> start { c > 0 ? a.x + amount * (b.x - a.x) : a.x, c > 0 ? a.y : a.y + amount * (b.y - a.y) };
                    const juce::Point<float> end { c > 0 ? b.x : b.x - amount * (b.x - a.x), c > 0 ? b.y - amount * (b.y - a.y) : b.y };
                    path.lineTo(start); path.quadraticTo(control, end); path.lineTo(b);
                }
            }
            g.setColour(ink); g.strokePath(path, juce::PathStrokeType(1.5f));
            for (const auto& point : values) { const auto at = position(point); if (point.id == selected) g.fillEllipse(at.x - 4, at.y - 4, 8, 8); else g.drawEllipse(at.x - 3, at.y - 3, 6, 6, 1.5f); }
        }
        void mouseDown(const juce::MouseEvent& event) override {
            if (!isEnabled()) return; grabKeyboardFocus(); preview = points(); const int index = hit(event.position, preview);
            selected = index >= 0 ? preview[size_t(index)].id : juce::String();
            dragging = index >= 0; changed = false; revision = p.state.revision; project = p.state.projectId; track = p.ownerId(); repaint();
            anchorY = event.position.y; originalCurve = index >= 0 ? preview[size_t(index)].curve : 0;
        }
        void mouseDrag(const juce::MouseEvent& event) override {
            if (!dragging || !isEnabled()) return;
            for (auto& point : preview) if (point.id == selected) {
                if (event.mods.isAltDown()) point.curve = juce::jlimit(-1.0f, 1.0f, originalCurve + (anchorY - event.position.y) / 80.0f);
                else {
                    const auto a = area(); point.timeSeconds = juce::jlimit(0.0, span(), double((event.position.x - a.getX()) / a.getWidth()) * span());
                    point.value = juce::jlimit(0.0f, 1.0f, (a.getBottom() - event.position.y) / a.getHeight());
                }
                changed = true;
                p.hint.setText(juce::String(point.timeSeconds, 2) + " s / " + juce::String(point.value * 100, 1) + "% / curve " + juce::String(point.curve, 2), juce::dontSendNotification);
            }
            std::sort(preview.begin(), preview.end(), [](const auto& a, const auto& b) { return a.timeSeconds < b.timeSeconds; }); repaint();
        }
        void mouseUp(const juce::MouseEvent&) override { if (dragging && changed) commit(); dragging = false; preview.clear(); repaint(); }
        void mouseDoubleClick(const juce::MouseEvent& event) override {
            if (!isEnabled() || !area().contains(event.position) || !p.currentTarget().isObject()) return;
            preview = points(); if (hit(event.position, preview) >= 0) return;
            const auto a = area(); selected = juce::Uuid().toString();
            preview.push_back({ selected, double((event.position.x - a.getX()) / a.getWidth()) * span(), (a.getBottom() - event.position.y) / a.getHeight(), 0 });
            std::sort(preview.begin(), preview.end(), [](const auto& x, const auto& y) { return x.timeSeconds < y.timeSeconds; });
            revision = p.state.revision; project = p.state.projectId; track = p.ownerId(); commit(); preview.clear(); repaint();
        }
        bool keyPressed(const juce::KeyPress& key) override {
            if (key.getKeyCode() == juce::KeyPress::escapeKey) { dragging = false; preview.clear(); repaint(); return true; }
            if (key.getKeyCode() != juce::KeyPress::deleteKey && key.getKeyCode() != juce::KeyPress::backspaceKey) return false;
            if (!isEnabled() || selected.isEmpty()) return true;
            preview = points(); preview.erase(std::remove_if(preview.begin(), preview.end(), [&](const auto& n) { return n.id == selected; }), preview.end());
            revision = p.state.revision; project = p.state.projectId; track = p.ownerId(); commit(); preview.clear(); selected.clear(); repaint(); return true;
        }
        void commit() { if (project == p.state.projectId && track == p.ownerId()) p.writeCurve(preview, revision); }
        void cancel() { dragging = false; preview.clear(); selected.clear(); repaint(); }
        Impl& p; std::vector<EngineSession::AutomationPointSnapshot> preview;
        juce::String selected, project, track; std::uint64_t revision = 0; bool dragging = false, changed = false; float anchorY = 0, originalCurve = 0;
    };
    Impl(SelectedTrackPanel& component, EngineSession& engine) : owner(component), session(engine), curve(*this) {
        for (auto* c : std::initializer_list<juce::Component*>{ &devices, &io, &automation, &plugin, &open, &bypass, &removePlugin, &up, &down, &browse, &nativeFx,
                &input, &arm, &monitor, &output, &send, &sendTarget, &sendGain, &pre, &sendEnabled, &addSend, &removeSend,
                &target, &laneEnabled, &deleteLane, &master, &curve, &hint }) owner.addAndMakeVisible(c);
        for (auto* button : { &devices, &io, &automation, &open, &bypass, &removePlugin, &up, &down, &browse, &nativeFx, &arm, &pre, &sendEnabled, &addSend, &removeSend, &laneEnabled, &deleteLane, &master }) uiButton(*button, button->getButtonText());
        devices.onClick = [this] { page = 0; owner.resized(); owner.repaint(); };
        io.onClick = [this] { page = 1; refreshInputs(); owner.resized(); owner.repaint(); };
        automation.onClick = [this] { page = 2; refreshTargets(); owner.resized(); owner.repaint(); };
        for (auto* button : { &devices, &io, &automation }) button->getProperties().set("flat", true);
        master.setTooltip("Show master devices and automation"); master.onClick = [this] { masterView = !masterView; rebuild(); };
        plugin.onChange = [this] { refreshPlugin(); };
        open.onClick = [this] {
            if (const auto* slot = currentPlugin()) {
                if (slot->format == "E-musician") {
                    if (!masterView && slot->isInstrument && owner.onOpenNative) owner.onOpenNative(ownerId());
                    else if (!slot->isInstrument && owner.onOpenNativeEffect) owner.onOpenNativeEffect(ownerId(), slot->id);
                } else pluginCommand("open_plugin");
            }
        };
        removePlugin.onClick = [this] { pluginCommand("remove_plugin"); };
        bypass.onClick = [this] { if (const auto* slot = currentPlugin()) run("set_plugin_enabled", object({ {"track_id", ownerId()}, {"plugin_id", slot->id}, {"enabled", !slot->enabled} })); };
        up.onClick = [this] { movePlugin(-1); }; down.onClick = [this] { movePlugin(1); };
        browse.onClick = [this] { if (owner.onBrowsePlugins) owner.onBrowsePlugins(ownerId()); };
        nativeFx.onClick = [this] { if (owner.onOpenNativeEffect) owner.onOpenNativeEffect(ownerId(), {}); };
        input.setTextWhenNothingSelected(uiText("Choose recording input"));
        input.onChange = [this] { if (!updating) { const int i = input.getSelectedId() - 1; if (i >= 0 && i < int(inputs.size())) run("set_track_input", object({ {"track_id", ownerId()}, {"input_device_id", inputs[size_t(i)]["id"]} })); } };
        arm.onClick = [this] { if (const auto* t = track()) run("set_track_armed", object({ {"track_id", t->id}, {"armed", !t->armed} })); };
        uiComboItem(monitor, 1, "monitor off"); uiComboItem(monitor, 3, "monitor on");
        monitor.setTooltip("Monitoring applies to this track only.");
        monitor.onChange = [this] { if (!updating) if (const auto* t = track()) run("set_input_monitor", object({ {"track_id", t->id}, {"mode", monitor.getSelectedId() == 3 ? "on" : "off"} })); };
        output.onChange = [this] { if (!updating && output.getSelectedId() > 0) run("set_track_output", object({ {"track_id", ownerId()}, {"target_track_id", destinations[output.getSelectedId() - 1]} })); };
        send.onChange = [this] { refreshSend(); };
        sendGain.setRange(-60, 6, 0.1); sendGain.setSliderStyle(juce::Slider::LinearHorizontal); sendGain.setTextBoxStyle(juce::Slider::TextBoxRight, false, 64, 28); sendGain.setTextValueSuffix(" dB");
        sendGain.onDragStart = [this] { session.beginEditGesture(); }; sendGain.onDragEnd = [this] { session.endEditGesture(); };
        sendGain.onValueChange = [this] { if (!updating) if (const auto* s = currentSend()) run("update_send", object({ {"track_id", ownerId()}, {"send_id", s->id}, {"gain_db", sendGain.getValue()} })); };
        pre.onClick = [this] { if (const auto* s = currentSend()) run("update_send", object({ {"track_id", ownerId()}, {"send_id", s->id}, {"pre_fader", !s->preFader} })); };
        sendEnabled.onClick = [this] { if (const auto* s = currentSend()) run("update_send", object({ {"track_id", ownerId()}, {"send_id", s->id}, {"enabled", !s->enabled} })); };
        addSend.onClick = [this] { const int i = sendTarget.getSelectedId() - 1; if (i >= 0 && i < sendDestinations.size()) run("add_send", object({ {"track_id", ownerId()}, {"target_track_id", sendDestinations[i]}, {"gain_db", -12.0}, {"pre_fader", false}, {"enabled", true} })); };
        removeSend.onClick = [this] { if (const auto* s = currentSend()) run("remove_send", object({ {"track_id", ownerId()}, {"send_id", s->id} })); };
        target.onChange = [this] { curve.cancel(); refreshLane(); };
        laneEnabled.onClick = [this] { if (const auto* lane = currentLane()) { auto values = lane->points ? *lane->points : std::vector<EngineSession::AutomationPointSnapshot>(); writeCurve(values, state.revision, !lane->enabled); } };
        deleteLane.onClick = [this] { if (const auto* lane = currentLane()) run("remove_automation_lane", object({ {"track_id", ownerId()}, {"lane_id", lane->id} })); };
        hint.setFont(font(11)); hint.setColour(juce::Label::textColourId, quiet); hint.setInterceptsMouseClicks(false, false);
    }
    const EngineSession::TrackSnapshot* track() const { for (const auto& t : state.tracks) if (t.id == state.selectedTrackId) return &t; return nullptr; }
    juce::String ownerId() const { return masterView ? "master" : state.selectedTrackId; }
    const std::vector<EngineSession::PluginSlotSnapshot>& plugins() const { if (masterView) return state.masterPlugins; if (const auto* t = track()) return t->plugins; return emptyPlugins; }
    const EngineSession::PluginSlotSnapshot* currentPlugin() const { const int i = plugin.getSelectedId() - 1; return i >= 0 && i < int(plugins().size()) ? &plugins()[size_t(i)] : nullptr; }
    const EngineSession::SendSnapshot* currentSend() const { if (const auto* t = track()) { const int i = send.getSelectedId() - 1; if (i >= 0 && i < int(t->sends.size())) return &t->sends[size_t(i)]; } return nullptr; }
    juce::var currentTarget() const { const int i = target.getSelectedId() - 1; return i >= 0 && i < int(targets.size()) ? targets[size_t(i)] : juce::var(); }
    const EngineSession::AutomationLaneSnapshot* currentLane() const {
        const auto selected = currentTarget(); if (!selected.isObject()) return nullptr;
        const auto* t = track(); const auto* lanes = masterView ? &state.masterAutomation : t ? &t->automation : nullptr;
        if (lanes) for (const auto& lane : *lanes) if (lane.target == selected["target"].toString() && lane.pluginId == selected["plugin_id"].toString()
            && (lane.target != "plugin_parameter" || lane.parameterId == selected["parameter_id"].toString())) return &lane;
        return nullptr;
    }
    void run(const juce::String& command, const juce::var& args, std::uint64_t expected = 0) {
        const auto result = session.execute(command, args, expected == 0 ? state.revision : expected); if (owner.onResult) owner.onResult(result);
        owner.update(session.snapshot());
    }
    juce::var query(const juce::String& command, juce::var args = {}) {
        if (!args.isObject()) args = object({});
        return session.executeRequest(object({ {"request_id", juce::Uuid().toString()}, {"command", command}, {"args", args}, {"project_id", state.projectId}, {"expected_revision", juce::int64(state.revision)} }))["result"];
    }
    void pluginCommand(const juce::String& command) { if (const auto* slot = currentPlugin()) run(command, object({ {"track_id", ownerId()}, {"plugin_id", slot->id} })); }
    void movePlugin(int direction) { if (const auto* slot = currentPlugin()) { const int index = plugin.getSelectedId() - 1 + direction; if (index >= 0 && index < int(plugins().size())) run("move_plugin", object({ {"track_id", ownerId()}, {"plugin_id", slot->id}, {"index", index} })); } }
    void refreshPlugin() { const auto* slot = currentPlugin(); open.setEnabled(slot && !slot->missing); bypass.setEnabled(slot); removePlugin.setEnabled(slot); up.setEnabled(slot && plugin.getSelectedId() > 1); down.setEnabled(slot && plugin.getSelectedId() < int(plugins().size())); uiButton(bypass, slot && !slot->enabled ? "enable" : "bypass"); }
    void refreshInputs() {
        inputs.clear(); input.clear(juce::dontSendNotification); const auto result = query("get_recording_inputs");
        if (const auto* list = result["inputs"].getArray()) for (const auto& item : *list) {
            const auto* t = track(); if (!t || t->kind == "bus" || bool(item["midi"]) != (t->kind == "instrument")) continue;
            inputs.push_back(item); input.addItem(item["name"].toString(), int(inputs.size()));
        }
        if (const auto* t = track()) for (size_t i = 0; i < inputs.size(); ++i) if (inputs[i]["id"].toString() == t->inputDeviceId) input.setSelectedId(int(i) + 1, juce::dontSendNotification);
        lastInputRefresh = juce::Time::getMillisecondCounter();
    }
    void refreshTargets() {
        const auto before = currentTarget(); targets.clear(); target.clear(juce::dontSendNotification);
        const auto result = query("get_automation_targets", object({ {"track_id", ownerId()} }));
        const auto* list = result.isArray() ? result.getArray() : result["targets"].getArray();
        int selection = 1;
        if (list) for (const auto& item : *list) { targets.push_back(item); target.addItem(item["name"].toString(), int(targets.size()));
            if (item["target"] == before["target"] && item["plugin_id"] == before["plugin_id"] && item["parameter_id"] == before["parameter_id"]) selection = int(targets.size()); }
        target.setSelectedId(targets.empty() ? 0 : selection, juce::dontSendNotification); refreshLane();
    }
    void refreshLane() {
        const auto* lane = currentLane(); laneEnabled.setEnabled(lane != nullptr); deleteLane.setEnabled(lane != nullptr);
        uiButton(laneEnabled, lane && !lane->enabled ? "enable lane" : "bypass lane");
        const auto t = currentTarget(); hint.setText(t.isObject() ? "Current: " + t["text"].toString() + " / double-click: add; drag: move; Alt-drag: curve; Delete: remove." : "Choose a track with an available automation parameter.", juce::dontSendNotification); curve.repaint();
    }
    void writeCurve(const std::vector<EngineSession::AutomationPointSnapshot>& values, std::uint64_t revision, bool enabled = true) {
        const auto selected = currentTarget(); if (!selected.isObject()) return;
        juce::Array<juce::var> points; for (const auto& p : values) points.add(object({ {"id", p.id}, {"time_seconds", p.timeSeconds}, {"value", p.value}, {"curve", p.curve} }));
        const bool isPlugin = selected["target"].toString() == "plugin_parameter";
        auto args = object({ {"track_id", ownerId()}, {"target", selected["target"]}, {"plugin_id", isPlugin ? selected["plugin_id"] : juce::var("")}, {"parameter_id", isPlugin ? selected["parameter_id"] : juce::var("")}, {"enabled", enabled}, {"points", points} });
        if (const auto* lane = currentLane()) args.getDynamicObject()->setProperty("lane_id", lane->id);
        run("set_automation_lane", args, revision);
    }
    void refreshSend() {
        const auto* s = currentSend(); updating = true; sendGain.setValue(s ? s->gainDb : -12, juce::dontSendNotification); updating = false;
        for (auto* c : std::initializer_list<juce::Component*>{ &sendGain, &pre, &sendEnabled, &removeSend }) c->setEnabled(s != nullptr);
        uiButton(pre, s && s->preFader ? "pre-fader" : "post-fader"); uiButton(sendEnabled, s && !s->enabled ? "enable send" : "bypass send");
    }
    void rebuild() {
        updating = true;
        const int oldPlugin = plugin.getSelectedId(), oldSend = send.getSelectedId(); plugin.clear(juce::dontSendNotification);
        for (size_t i = 0; i < plugins().size(); ++i) plugin.addItem(juce::String(int(i) + 1) + ". " + plugins()[i].name + (plugins()[i].enabled ? "" : " [off]"), int(i) + 1);
        plugin.setSelectedId(plugins().empty() ? 0 : juce::jlimit(1, int(plugins().size()), oldPlugin), juce::dontSendNotification);
        destinations = { "master" }; output.clear(juce::dontSendNotification); output.addItem("Master output", 1);
        sendDestinations.clear(); sendTarget.clear(juce::dontSendNotification);
        for (const auto& t : state.tracks) if (t.kind == "bus" && t.id != ownerId()) { destinations.add(t.id); output.addItem(t.name, destinations.size()); sendDestinations.add(t.id); sendTarget.addItem(t.name, sendDestinations.size()); }
        sendTarget.setSelectedId(sendDestinations.isEmpty() ? 0 : 1, juce::dontSendNotification);
        send.clear(juce::dontSendNotification);
        if (const auto* t = track()) {
            output.setSelectedId(destinations.indexOf(t->outputTargetId) + 1, juce::dontSendNotification);
            monitor.setSelectedId(t->monitorMode == "on" ? 3 : 1, juce::dontSendNotification);
            uiButton(arm, t->armed ? "armed" : "arm record"); arm.setToggleState(t->armed, juce::dontSendNotification);
            for (size_t i = 0; i < t->sends.size(); ++i) { juce::String name = t->sends[i].targetTrackId; for (const auto& b : state.tracks) if (b.id == name) name = b.name; send.addItem(juce::String(int(i) + 1) + ". " + name, int(i) + 1); }
            send.setSelectedId(t->sends.empty() ? 0 : juce::jlimit(1, int(t->sends.size()), oldSend), juce::dontSendNotification);
        }
        updating = false; refreshPlugin(); refreshSend();
        if (page == 1) refreshInputs(); if (page == 2) refreshTargets();
        master.setToggleState(masterView, juce::dontSendNotification); owner.resized(); owner.repaint();
    }
    SelectedTrackPanel& owner; EngineSession& session; EngineSession::Snapshot state;
    int page = 0; bool updating = false, masterView = false;
    juce::uint32 lastInputRefresh = 0;
    juce::TextButton devices { "devices" }, io { "I/O + sends" }, automation { "automation" }, master { "master" };
    juce::ComboBox plugin, input, monitor, output, send, sendTarget, target;
    juce::TextButton open { "open" }, bypass { "bypass" }, removePlugin { "remove" }, up { "up" }, down { "down" }, browse { "add plug-in..." }, nativeFx { "built-in effects..." };
    juce::TextButton arm { "arm record" }, pre { "post-fader" }, sendEnabled { "bypass send" }, addSend { "add send" }, removeSend { "remove send" };
    juce::Slider sendGain;
    juce::TextButton laneEnabled { "bypass lane" }, deleteLane { "delete lane" };
    Curve curve; juce::Label hint;
    juce::StringArray destinations, sendDestinations;
    std::vector<juce::var> inputs, targets;
    const std::vector<EngineSession::PluginSlotSnapshot> emptyPlugins;
};
SelectedTrackPanel::SelectedTrackPanel(EngineSession& engine) : impl(std::make_unique<Impl>(*this, engine)) {}
SelectedTrackPanel::~SelectedTrackPanel() = default;
void SelectedTrackPanel::showDevices() { impl->page = 0; impl->masterView = false; impl->rebuild(); }
bool SelectedTrackPanel::isMasterView() const { return impl->masterView; }
void SelectedTrackPanel::update(const EngineSession::Snapshot& state) {
    auto& p = *impl; const bool changed = state.projectId != p.state.projectId || state.revision != p.state.revision || state.selectedTrackId != p.state.selectedTrackId;
    bool recordingChanged = state.recording != p.state.recording || state.recordingFinalizing != p.state.recordingFinalizing;
    const auto* previous = p.track(); const auto armed = previous && previous->armed; const auto monitor = previous ? previous->monitorMode : juce::String();
    if (changed) p.curve.cancel(); p.state = state;
    const auto* current = p.track(); recordingChanged = recordingChanged || armed != (current && current->armed) || monitor != (current ? current->monitorMode : juce::String());
    if (changed || recordingChanged) p.rebuild();
    if (isVisible() && p.page == 1 && !p.input.isPopupActive() && juce::Time::getMillisecondCounter() - p.lastInputRefresh > 2000) p.refreshInputs();
    setEnabled(!state.recording && !state.recordingFinalizing);
}
void SelectedTrackPanel::resized() {
    if (!impl) return; refreshUiButtons(*this); auto& p = *impl;
    p.devices.setBounds(8, 4, 94, 28); p.io.setBounds(108, 4, 118, 28); p.automation.setBounds(232, 4, 120, 28); p.master.setBounds(getWidth() - 88, 4, 80, 28);
    for (auto* c : std::initializer_list<juce::Component*>{ &p.plugin, &p.open, &p.bypass, &p.removePlugin, &p.up, &p.down, &p.browse, &p.nativeFx }) c->setVisible(p.page == 0);
    for (auto* c : std::initializer_list<juce::Component*>{ &p.input, &p.arm, &p.monitor, &p.output, &p.send, &p.sendTarget, &p.sendGain, &p.pre, &p.sendEnabled, &p.addSend, &p.removeSend }) c->setVisible(p.page == 1 && !p.masterView);
    for (auto* c : std::initializer_list<juce::Component*>{ &p.target, &p.laneEnabled, &p.deleteLane, &p.curve, &p.hint }) c->setVisible(p.page == 2);
    p.plugin.setBounds(12, 66, 270, 30); p.open.setBounds(294, 66, 76, 30); p.bypass.setBounds(376, 66, 84, 30); p.removePlugin.setBounds(466, 66, 84, 30);
    p.up.setBounds(12, 108, 60, 28); p.down.setBounds(78, 108, 60, 28); p.browse.setBounds(154, 108, 128, 28);
    p.nativeFx.setBounds(290, 108, 150, 28); p.nativeFx.setEnabled(p.masterView || p.track() != nullptr);
    const int split = juce::jmax(310, getWidth() / 2);
    p.input.setBounds(12, 58, 212, 28); p.arm.setBounds(230, 58, 98, 28); p.monitor.setBounds(12, 98, 212, 28);
    p.output.setBounds(12, 157, 270, 28);
    p.sendTarget.setBounds(split, 58, 210, 28); p.addSend.setBounds(split + 216, 58, 98, 28);
    p.send.setBounds(split, 98, 210, 28); p.removeSend.setBounds(split + 216, 98, 110, 28);
    p.sendGain.setBounds(split, 139, 210, 28); p.pre.setBounds(split, 179, 102, 28); p.sendEnabled.setBounds(split + 108, 179, 112, 28);
    p.addSend.setEnabled(!p.sendDestinations.isEmpty()); p.input.setEnabled(p.track() && p.track()->kind != "bus"); p.arm.setEnabled(p.track() && p.track()->kind != "bus" && !p.track()->inputDeviceId.isEmpty());
    p.monitor.setEnabled(p.track() && !p.track()->inputDeviceId.isEmpty()); p.output.setEnabled(p.track() != nullptr);
    p.target.setBounds(12, 42, juce::jmin(300, getWidth() - 280), 28); p.laneEnabled.setBounds(p.target.getRight() + 8, 42, 110, 28); p.deleteLane.setBounds(p.laneEnabled.getRight() + 8, 42, 110, 28);
    p.hint.setBounds(12, getHeight() - 24, getWidth() - 24, 22); p.curve.setBounds(6, 76, getWidth() - 12, juce::jmax(78, getHeight() - 102));
}
void SelectedTrackPanel::paint(juce::Graphics& g) {
    auto& p = *impl; g.fillAll(paper); g.setColour(rule); g.drawHorizontalLine(35, 8, float(getWidth() - 8)); g.setColour(quiet); g.setFont(font(12));
    if (p.page == 0) g.drawText(uiText(p.masterView ? "Master signal chain" : "Selected track signal chain"), 12, 39, getWidth() - 24, 22, juce::Justification::centredLeft);
    if (p.page == 1) {
        if (p.masterView) { g.drawFittedText(uiText("Choose a track to configure recording inputs, output and sends."), getLocalBounds().reduced(12).withTrimmedTop(40), juce::Justification::centred, 2); return; }
        const int split = juce::jmax(310, getWidth() / 2);
        g.drawText(uiText("recording input"), 12, 36, 240, 22, juce::Justification::centredLeft); g.drawText(uiText("send to bus"), split, 36, 240, 22, juce::Justification::centredLeft);
        g.drawText(uiText("track output"), 12, 133, 240, 22, juce::Justification::centredLeft);
        g.drawText(uiText("Monitoring applies to this track only."), 12, getHeight() - 24, getWidth() - 24, 22, juce::Justification::centredLeft);
    }
}
juce::Result SelectedTrackPanel::runInteractionSmokeTest(juce::DynamicObject& report) {
    // Called by the root harness in an isolated session with an instrument track.
    auto& p = *impl; p.page = 2; update(p.session.snapshot()); p.refreshTargets(); resized();
    if (!p.currentTarget().isObject()) return juce::Result::fail("Automation targets are not available in the selected-track panel.");
    std::vector<EngineSession::AutomationPointSnapshot> values { {juce::Uuid().toString(), 0.0, 0.25f, 0}, {juce::Uuid().toString(), 2.0, 0.75f, 0} };
    p.writeCurve(values, p.state.revision);
    const auto* lane = p.currentLane();
    if (!lane || !lane->points || lane->points->size() != 2) return juce::Result::fail("Automation panel did not commit its curve through the shared command API.");
    p.curve.selected = lane->points->front().id; p.curve.keyPressed(juce::KeyPress(juce::KeyPress::deleteKey));
    lane = p.currentLane(); if (!lane || !lane->points || lane->points->size() != 1) return juce::Result::fail("Deleting an automation point did not commit.");
    p.deleteLane.onClick(); if (p.currentLane()) return juce::Result::fail("Automation panel could not delete its lane.");
    report.setProperty("automation_panel_command_and_delete", true);
    // The native instrument uses the main-window device dock, not a VST editor.
    const auto oldState = p.state; const auto oldMaster = p.masterView; const auto oldOpen = onOpenNative;
    EngineSession::TrackSnapshot nativeTrack; nativeTrack.id = "synthetic-native-track"; nativeTrack.kind = "instrument";
    EngineSession::PluginSlotSnapshot slot; slot.id = "synthetic-native"; slot.name = "Sampler"; slot.format = "E-musician"; slot.isInstrument = true;
    nativeTrack.plugins.push_back(slot); p.state.tracks.clear(); p.state.tracks.push_back(nativeTrack);
    p.state.selectedTrackId = nativeTrack.id; p.masterView = false;
    p.plugin.clear(juce::dontSendNotification); p.plugin.addItem("Sampler", 1); p.plugin.setSelectedId(1, juce::dontSendNotification);
    juce::String opened; onOpenNative = [&](const auto& id) { opened = id; }; p.open.onClick();
    const auto oldEffect = onOpenNativeEffect; juce::String effectTrack, effectDevice;
    onOpenNativeEffect = [&](const auto& track, const auto& device) { effectTrack = track; effectDevice = device; };
    EngineSession::PluginSlotSnapshot effect; effect.id = "master-effect"; effect.name = "EQ Eight"; effect.format = "E-musician";
    p.state.masterPlugins = {effect}; p.masterView = true; p.plugin.clear(juce::dontSendNotification);
    p.plugin.addItem("EQ Eight", 1); p.plugin.setSelectedId(1, juce::dontSendNotification); p.open.onClick();
    const bool masterOpen = effectTrack == "master" && effectDevice == effect.id;
    effectTrack.clear(); effectDevice = "not-empty"; p.nativeFx.onClick();
    const bool masterAdd = effectTrack == "master" && effectDevice.isEmpty(); onOpenNativeEffect = oldEffect;
    onOpenNative = oldOpen; p.masterView = oldMaster; update(oldState);
    if (opened != nativeTrack.id) return juce::Result::fail("Native instrument did not open in its track dock.");
    if (!masterOpen || !masterAdd) return juce::Result::fail("Master native effects did not route to the master target.");
    report.setProperty("selected_track_native_open", true); report.setProperty("master_native_effect_routing", true); return juce::Result::ok();
}
}
