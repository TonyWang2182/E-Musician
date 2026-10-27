#include "PianoRoll.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <set>

namespace emusician {
namespace {
const juce::Colour ink { 0xff171817 }, rule { 0xffc6c9c3 }, paper { 0xfffefefd }, quiet { 0xff626560 };
juce::Font mono(float size) { return juce::Font(juce::FontOptions(juce::Font::getDefaultMonospacedFontName(), size, juce::Font::plain)); }
bool isBlack(int pitch) { const int n = pitch % 12; return n == 1 || n == 3 || n == 6 || n == 8 || n == 10; }
juce::String pitchName(int pitch)
{
    static const char* names[] { "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B" };
    return juce::String(names[juce::jlimit(0, 127, pitch) % 12]) + juce::String(pitch / 12 - 1);
}
}

struct PianoRoll::Impl : private juce::ScrollBar::Listener {
    struct Grid final : juce::Component {
        explicit Grid(Impl& model) : p(model) { setWantsKeyboardFocus(true); }
        void paint(juce::Graphics& g) override { p.paintGrid(g); }
        void mouseDown(const juce::MouseEvent& e) override { p.begin(e); }
        void mouseDrag(const juce::MouseEvent& e) override { p.dragTo(e); }
        void mouseUp(const juce::MouseEvent& e) override { p.end(e); }
        void mouseDoubleClick(const juce::MouseEvent& e) override { p.insert(e.position); }
        void mouseWheelMove(const juce::MouseEvent& e, const juce::MouseWheelDetails& wheel) override
        {
            if (e.mods.isCtrlDown()) p.setZoom(p.pixelsPerBeat * (wheel.deltaY > 0 ? 1.25 : 0.8));
            else if (e.mods.isShiftDown()) { p.firstBeat = juce::jmax(0.0, p.firstBeat - wheel.deltaY * p.visibleBeats()); p.layout(); }
            else { p.topPitch = juce::jlimit(12, 127, p.topPitch + juce::roundToInt(wheel.deltaY * 24.0f)); p.layout(); }
        }
        bool keyPressed(const juce::KeyPress& key) override { return p.owner.keyPressed(key); }
        Impl& p;
    };
    explicit Impl(PianoRoll& c) : owner(c), grid(*this), horizontal(false), vertical(true)
    {
        for (juce::Component* item : std::initializer_list<juce::Component*> {
                &grid, &horizontal, &vertical, &snap, &erase, &duplicate, &quantize,
                &down, &up, &velocity, &zoomOut, &zoomIn, &fit, &drums, &drumPitch, &drumBar }) owner.addAndMakeVisible(item);
        for (auto* button : { &erase, &duplicate, &quantize, &down, &up, &zoomOut, &zoomIn, &fit, &drums }) button->getProperties().set("flat", true);
        snap.addItem("grid off", 1); snap.addItem("1/4", 2); snap.addItem("1/8", 3); snap.addItem("1/16", 4); snap.addItem("1/32", 5);
        snap.setSelectedId(4, juce::dontSendNotification);
        snap.onChange = [this] { gridBeats = snap.getSelectedId() == 1 ? 0.0 : std::pow(0.5, snap.getSelectedId() - 2); layout(); };
        snap.setTooltip("Snap in quarter-note beats. Hold Alt while dragging to bypass snap.");
        erase.onClick = [this] { deleteSelected(); };
        duplicate.onClick = [this] { duplicateSelected(); };
        quantize.onClick = [this] { modify([](Note& n, Impl& p) { n.startBeats = p.snapped(n.startBeats); n.lengthBeats = juce::jmax(0.03125, p.snapped(n.lengthBeats)); }); };
        down.onClick = [this] { transpose(-1); }; up.onClick = [this] { transpose(1); };
        zoomIn.onClick = [this] { setZoom(pixelsPerBeat * 1.5); }; zoomOut.onClick = [this] { setZoom(pixelsPerBeat / 1.5); };
        fit.onClick = [this] { firstBeat = 0; pixelsPerBeat = juce::jlimit(12.0, 300.0, plot().getWidth() / juce::jmax(1.0, length)); fitPitch(); layout(); };
        velocity.setRange(1, 127, 1); velocity.setValue(90, juce::dontSendNotification);
        velocity.setSliderStyle(juce::Slider::LinearHorizontal); velocity.setTextBoxStyle(juce::Slider::TextBoxRight, false, 48, 26);
        velocity.setName("Note velocity"); velocity.setTooltip("Velocity of selected notes. One drag is one edit.");
        velocity.onDragStart = [this] { velocityGesture = true; beforeVelocity = notes; gestureRevision = revision; };
        velocity.onValueChange = [this] {
            if (updating) return;
            if (velocityGesture) { for (auto& n : notes) if (selected.count(n.id)) n.velocity = int(velocity.getValue()); grid.repaint(); }
            else modify([](Note& n, Impl& p) { n.velocity = int(p.velocity.getValue()); });
        };
        velocity.onDragEnd = [this] { if (velocityGesture) { velocityGesture = false; submit(gestureRevision); } };
        drums.setClickingTogglesState(true); drums.onClick = [this] { refreshSteps(); owner.resized(); };
        drumPitch.addItem("kick / 36", 36); drumPitch.addItem("snare / 38", 38); drumPitch.addItem("closed hat / 42", 42);
        drumPitch.addItem("open hat / 46", 46); drumPitch.addItem("clap / 39", 39); drumPitch.addItem("tom / 45", 45);
        drumPitch.setSelectedId(36, juce::dontSendNotification); drumPitch.onChange = [this] { refreshSteps(); };
        drumBar.setFont(mono(13)); drumBar.setInputRestrictions(6, "0123456789");
        drumBar.setColour(juce::TextEditor::textColourId, ink); drumBar.setText("1", false);
        drumBar.setName("Drum four-beat block");
        drumBar.setTooltip("Four-quarter-note block number for the 16-step row (independent of time signature)."); drumBar.onTextChange = [this] { refreshSteps(); };
        for (int i = 0; i < 16; ++i) {
            auto button = std::make_unique<juce::TextButton>(juce::String(i + 1));
            button->onClick = [this, i] { toggleStep(i); };
            owner.addAndMakeVisible(*button); steps.push_back(std::move(button));
        }
        horizontal.setAutoHide(false); vertical.setAutoHide(false); horizontal.addListener(this); vertical.addListener(this);
        owner.setWantsKeyboardFocus(true);
    }
    ~Impl() override { horizontal.removeListener(this); vertical.removeListener(this); }
    juce::Rectangle<float> plot() const { return grid.getLocalBounds().toFloat().withTrimmedLeft(48).withTrimmedTop(27).withTrimmedBottom(owner.getHeight() < 300 ? 24 : 47); }
    void fitPitch()
    {
        if (notes.empty()) { topPitch = 72; return; }
        int low = 127, high = 0;
        for (const auto& n : notes) { low = juce::jmin(low, n.pitch); high = juce::jmax(high, n.pitch); }
        rowHeight = juce::jlimit(8.0f, 18.0f, plot().getHeight() / float(high - low + 3));
        const int rows = juce::jmax(1, int(plot().getHeight() / rowHeight));
        topPitch = juce::jmin(127, high + juce::jlimit(0, 2, (rows - (high - low + 1)) / 2));
    }
    double visibleBeats() const { return juce::jmax(0.01, plot().getWidth() / pixelsPerBeat); }
    double snapped(double value) const { return gridBeats > 0.0 ? std::round(value / gridBeats) * gridBeats : value; }
    float x(double beat) const { return plot().getX() + float((beat - firstBeat) * pixelsPerBeat); }
    float y(int pitch) const { return plot().getY() + float(topPitch - pitch) * rowHeight; }
    double atBeat(float px, bool bypass = false) const { const double b = firstBeat + (px - plot().getX()) / pixelsPerBeat; return juce::jmax(0.0, bypass ? b : snapped(b)); }
    int atPitch(float py) const { return juce::jlimit(0, 127, topPitch - int(std::floor((py - plot().getY()) / rowHeight))); }
    void layout()
    {
        firstBeat = juce::jlimit(0.0, juce::jmax(0.0, length - visibleBeats()), firstBeat);
        horizontal.setRangeLimits(0, juce::jmax(length, visibleBeats()), juce::dontSendNotification);
        horizontal.setCurrentRange(firstBeat, visibleBeats(), juce::dontSendNotification);
        vertical.setRangeLimits(0, 128, juce::dontSendNotification);
        vertical.setCurrentRange(127 - topPitch, juce::jmin(128.0, double(plot().getHeight() / rowHeight)), juce::dontSendNotification);
        visible.clear();
        for (std::size_t i = 0; i < notes.size(); ++i) {
            const auto& n = notes[i];
            juce::Rectangle<float> r { x(n.startBeats), y(n.pitch) + 1, float(n.lengthBeats * pixelsPerBeat), rowHeight - 2 };
            if (r.intersects(plot())) visible.push_back({ i, r });
        }
        grid.repaint(); owner.repaint();
    }
    void scrollBarMoved(juce::ScrollBar* bar, double value) override { if (bar == &horizontal) firstBeat = value; else topPitch = 127 - int(value); layout(); }
    void setZoom(double value) { pixelsPerBeat = juce::jlimit(12.0, 400.0, value); layout(); }
    void refreshButtons()
    {
        const bool usable = clipId.isNotEmpty(); const bool chosen = usable && !selected.empty();
        for (auto* b : { &erase, &duplicate, &quantize, &down, &up }) b->setEnabled(chosen);
        velocity.setEnabled(chosen); drums.setEnabled(usable);
        if (chosen && !velocityGesture) for (const auto& n : notes) if (selected.count(n.id)) {
            updating = true; velocity.setValue(n.velocity, juce::dontSendNotification); updating = false; break;
        }
        refreshSteps();
    }
    void refreshSteps()
    {
        if (steps.size() != 16) return;
        const auto block = juce::jmax(0, drumBar.getText().getIntValue() - 1) * 4.0;
        std::array<bool, 16> active {};
        for (const auto& note : notes) if (note.pitch == drumPitch.getSelectedId()) {
            const auto step = (note.startBeats - block) * 4.0;
            const int index = int(std::round(step));
            if (index >= 0 && index < 16 && std::abs(step - index) < 1.0e-6) active[std::size_t(index)] = true;
        }
        for (int i = 0; i < 16; ++i) {
            steps[std::size_t(i)]->setToggleState(active[std::size_t(i)], juce::dontSendNotification);
            steps[std::size_t(i)]->setEnabled(clipId.isNotEmpty() && block + i * 0.25 + 0.125 <= length);
        }
    }
    void submit(std::uint64_t expected)
    {
        refreshButtons(); layout();
        if (owner.onWriteNotes && clipId.isNotEmpty()) owner.onWriteNotes(clipId, notes, expected);
    }
    template<typename F> void modify(F fn)
    {
        if (selected.empty() || clipId.isEmpty()) return;
        for (auto& n : notes) if (selected.count(n.id)) { fn(n, *this); n.lengthBeats = juce::jlimit(0.001, length, n.lengthBeats); n.startBeats = juce::jlimit(0.0, length - n.lengthBeats, n.startBeats); }
        submit(revision);
    }
    void transpose(int delta) { modify([delta](Note& n, Impl&) { n.pitch = juce::jlimit(0, 127, n.pitch + delta); }); }
    void deleteSelected()
    {
        if (selected.empty()) return;
        std::erase_if(notes, [this](const auto& n) { return selected.count(n.id) != 0; }); selected.clear(); submit(revision);
    }
    void duplicateSelected()
    {
        if (selected.empty()) return;
        double first = length, last = 0;
        for (const auto& n : notes) if (selected.count(n.id)) { first = juce::jmin(first, n.startBeats); last = juce::jmax(last, n.startBeats + n.lengthBeats); }
        const auto delta = last - first; std::vector<Note> copies; std::set<juce::String> ids;
        for (const auto& n : notes) if (selected.count(n.id) && n.startBeats + delta + n.lengthBeats <= length + 1.0e-9) {
            auto copy = n; copy.id = juce::Uuid().toString(); copy.startBeats += delta; ids.insert(copy.id); copies.push_back(std::move(copy));
        }
        if (copies.empty()) return;
        notes.insert(notes.end(), copies.begin(), copies.end()); selected = std::move(ids); submit(revision);
    }
    void insert(juce::Point<float> point)
    {
        if (clipId.isEmpty() || !plot().contains(point)) return;
        const auto start = atBeat(point.x); const auto len = juce::jmin(gridBeats > 0 ? gridBeats : 0.25, length - start);
        if (len <= 0.001) return;
        Note n { juce::Uuid().toString(), atPitch(point.y), start, len, int(velocity.getValue()), notes.empty() ? 1 : notes.front().channel };
        selected = { n.id }; notes.push_back(n); submit(revision);
    }
    void toggleStep(int step)
    {
        if (clipId.isEmpty()) return;
        const double beat = juce::jmax(0, drumBar.getText().getIntValue() - 1) * 4.0 + step * 0.25;
        if (beat + 0.125 > length) return;
        const int pitch = drumPitch.getSelectedId();
        const auto found = std::find_if(notes.begin(), notes.end(), [&](const auto& n) { return n.pitch == pitch && std::abs(n.startBeats - beat) < 1.0e-6; });
        if (found != notes.end()) notes.erase(found);
        else notes.push_back({ juce::Uuid().toString(), pitch, beat, 0.125, 100, notes.empty() ? 10 : notes.front().channel });
        submit(revision);
    }
    void begin(const juce::MouseEvent& e)
    {
        if (grid.isShowing()) grid.grabKeyboardFocus();
        drag = {}; if (clipId.isEmpty()) return;
        if (e.position.y < plot().getY() && e.position.x >= plot().getX()) { if (owner.onSeek) owner.onSeek((clipStart + atBeat(e.position.x, true)) * 60.0 / bpm); return; }
        for (auto it = visible.rbegin(); it != visible.rend(); ++it) if (it->second.contains(e.position)) {
            const auto& n = notes[it->first];
            if (e.mods.isShiftDown() || e.mods.isCtrlDown()) { if (selected.count(n.id)) selected.erase(n.id); else selected.insert(n.id); }
            else if (!selected.count(n.id)) selected = { n.id };
            drag.mode = e.position.x >= it->second.getRight() - 6 ? Drag::resize : Drag::move;
            drag.anchor = e.position; drag.revision = revision; drag.before = notes; drag.activeId = n.id;
            refreshButtons(); grid.repaint(); return;
        }
        if (e.position.y >= plot().getBottom() && e.position.x >= plot().getX()) {
            for (const auto& v : visible) if (std::abs(e.position.x - v.second.getX()) < 6) { selected = { notes[v.first].id }; drag.mode = Drag::velocity; drag.anchor = e.position; drag.revision = revision; drag.before = notes; refreshButtons(); return; }
        }
        if (plot().contains(e.position)) { if (!e.mods.isShiftDown() && !e.mods.isCtrlDown()) selected.clear(); drag.mode = Drag::box; drag.selectionBefore = selected; drag.anchor = e.position; drag.revision = revision; drag.selectionBox = { e.position, e.position }; refreshButtons(); grid.repaint(); }
    }
    void dragTo(const juce::MouseEvent& e)
    {
        if (drag.mode == Drag::none) return;
        drag.changed = drag.changed || e.getDistanceFromDragStart() >= 3;
        if (!drag.changed) return;
        if (drag.mode == Drag::box) {
            selected = drag.selectionBefore; drag.selectionBox = { drag.anchor, e.position }; for (const auto& v : visible) if (v.second.intersects(drag.selectionBox)) selected.insert(notes[v.first].id); grid.repaint(); refreshButtons(); return;
        }
        notes = drag.before;
        double delta = (e.position.x - drag.anchor.x) / pixelsPerBeat;
        if (!e.mods.isAltDown() && gridBeats > 0) delta = snapped(delta);
        const int pitchDelta = juce::roundToInt((drag.anchor.y - e.position.y) / rowHeight);
        double minStart = length, maxEnd = 0; int minPitch = 127, maxPitch = 0;
        for (const auto& n : notes) if (selected.count(n.id)) { minStart = juce::jmin(minStart, n.startBeats); maxEnd = juce::jmax(maxEnd, n.startBeats + n.lengthBeats); minPitch = juce::jmin(minPitch, n.pitch); maxPitch = juce::jmax(maxPitch, n.pitch); }
        if (drag.mode == Drag::move) delta = juce::jlimit(-minStart, length - maxEnd, delta);
        for (auto& n : notes) if (selected.count(n.id)) {
            if (drag.mode == Drag::move) { n.startBeats += delta; n.pitch += juce::jlimit(-minPitch, 127 - maxPitch, pitchDelta); }
            else if (drag.mode == Drag::resize) n.lengthBeats = juce::jlimit(juce::jmin(0.03125, length - n.startBeats), length - n.startBeats, n.lengthBeats + delta);
            else if (drag.mode == Drag::velocity) n.velocity = juce::jlimit(1, 127, n.velocity + juce::roundToInt((drag.anchor.y - e.position.y) * 2));
        }
        layout();
    }
    void end(const juce::MouseEvent&)
    {
        const auto mode = drag.mode; const auto changed = drag.changed; const auto expected = drag.revision; drag = {};
        if (changed && mode != Drag::none && mode != Drag::box) submit(expected); else grid.repaint();
    }
    void paintGrid(juce::Graphics& g)
    {
        g.fillAll(paper); const auto area = plot();
        if (clipId.isEmpty()) { g.setColour(quiet); g.setFont(mono(15)); g.drawFittedText("Select a MIDI clip to edit notes.", grid.getLocalBounds(), juce::Justification::centred, 2); return; }
        const int rows = int(std::ceil(area.getHeight() / rowHeight));
        for (int r = 0; r < rows; ++r) {
            const int pitch = topPitch - r; if (pitch < 0) break;
            const auto yy = area.getY() + r * rowHeight;
            if (isBlack(pitch)) { g.setColour(ink.withAlpha(0.035f)); g.fillRect(area.getX(), yy, area.getWidth(), rowHeight); }
            g.setColour(rule.withAlpha(pitch % 12 == 0 ? 1.0f : 0.45f)); g.drawHorizontalLine(juce::roundToInt(yy), 0, area.getRight());
            g.setColour(isBlack(pitch) ? ink : paper); g.fillRect(0.0f, yy + 1, 43.0f, rowHeight - 1);
            g.setColour(isBlack(pitch) ? paper : ink); g.setFont(mono(12)); g.drawText(pitchName(pitch), 3, juce::roundToInt(yy), 38, int(rowHeight), juce::Justification::centredRight);
        }
        const double gridStep = gridBeats > 0 ? gridBeats : 1.0;
        const double step = pixelsPerBeat * gridStep >= 6 ? gridStep : 1.0;
        for (double b = std::ceil(firstBeat / step) * step; b <= juce::jmin(length, firstBeat + visibleBeats()); b += step) {
            const auto xx = x(b); const bool bar = std::abs(std::remainder(b, barBeats)) < 1.0e-6;
            g.setColour(rule.withAlpha(bar ? 1.0f : 0.4f)); g.drawVerticalLine(juce::roundToInt(xx), 27, float(grid.getHeight()));
            if (bar) { g.setColour(quiet); g.setFont(mono(11)); g.drawText(juce::String(int(std::round(b / barBeats)) + 1), juce::roundToInt(xx) + 4, 1, 50, 23, juce::Justification::centredLeft); }
        }
        {
            juce::Graphics::ScopedSaveState save(g); g.reduceClipRegion(area.toNearestInt());
            for (const auto& v : visible) {
                const auto& n = notes[v.first]; const bool chosen = selected.count(n.id) != 0;
                g.setColour(chosen ? ink : rule); g.fillRoundedRectangle(v.second, 2);
                g.setColour(ink); g.drawRoundedRectangle(v.second, 2, chosen ? 1.5f : 0.8f);
                if (v.second.getWidth() > 35) { g.setColour(chosen ? paper : ink); g.setFont(mono(10)); g.drawText(pitchName(n.pitch), v.second.toNearestInt().reduced(3, 0), juce::Justification::centredLeft); }
            }
            if (drag.mode == Drag::box && drag.changed) { g.setColour(ink.withAlpha(0.08f)); g.fillRect(drag.selectionBox); g.setColour(ink); g.drawRect(drag.selectionBox); }
        }
        g.setColour(rule); g.drawHorizontalLine(juce::roundToInt(area.getBottom()), 0, float(grid.getWidth()));
        const float velocityHeight = owner.getHeight() < 300 ? 18.0f : 35.0f;
        g.setFont(mono(10)); g.setColour(quiet); g.drawText("vel", 2, int(area.getBottom()), 40, int(velocityHeight), juce::Justification::centred);
        for (const auto& v : visible) {
            const auto& n = notes[v.first]; const float h = float(n.velocity) / 127.0f * velocityHeight;
            g.setColour(selected.count(n.id) ? ink : quiet); g.fillRect(v.second.getX(), float(grid.getHeight()) - h - 3, 2.0f, h);
        }
        const auto head = x(playheadBeat - clipStart);
        if (head >= area.getX() && head <= area.getRight()) { g.setColour(ink.withAlpha(playing ? 1.0f : 0.45f)); g.drawVerticalLine(juce::roundToInt(head), 0, float(grid.getHeight())); }
        if (grid.hasKeyboardFocus(true)) { g.setColour(ink); g.drawRect(grid.getLocalBounds().reduced(1), 1); }
    }
    PianoRoll& owner;
    Grid grid;
    juce::ScrollBar horizontal, vertical;
    juce::ComboBox snap, drumPitch;
    juce::TextEditor drumBar;
    juce::TextButton erase { "delete" }, duplicate { "duplicate" }, quantize { "quantize" }, down { "- semitone" }, up { "+ semitone" };
    juce::TextButton zoomOut { "-" }, zoomIn { "+" }, fit { "fit" }, drums { "drum steps" };
    juce::Slider velocity;
    std::vector<std::unique_ptr<juce::TextButton>> steps;
    std::vector<Note> notes, beforeVelocity;
    std::vector<std::pair<std::size_t, juce::Rectangle<float>>> visible;
    std::set<juce::String> selected;
    juce::String projectId, clipId, name;
    std::uint64_t revision = 0, gestureRevision = 0;
    double clipStart = 0, length = 4, bpm = 120, firstBeat = 0, pixelsPerBeat = 80, gridBeats = 0.25, playheadBeat = 0, barBeats = 4;
    float rowHeight = 18;
    int topPitch = 84;
    bool updating = false, velocityGesture = false, playing = false;
    struct Drag { enum Mode { none, move, resize, box, velocity } mode = none; juce::Point<float> anchor; juce::Rectangle<float> selectionBox; std::vector<Note> before; std::set<juce::String> selectionBefore; std::uint64_t revision = 0; juce::String activeId; bool changed = false; } drag;
};

PianoRoll::PianoRoll() : impl(std::make_unique<Impl>(*this)) { setSize(1000, 580); }
PianoRoll::~PianoRoll() = default;
void PianoRoll::setTimeSignature(int numerator, int denominator)
{
    const double next = juce::jmax(0.125, numerator * 4.0 / juce::jmax(1, denominator));
    if (next != impl->barBeats) { impl->barBeats = next; impl->grid.repaint(); }
}
void PianoRoll::setClip(const juce::String& projectId, const juce::String& clipId, const juce::String& name,
                       std::uint64_t revision, double startBeats, double lengthBeats, double bpm,
                       const std::vector<Note>& notes)
{
    auto& p = *impl;
    if (p.projectId == projectId && p.clipId == clipId && p.revision == revision) return;
    const bool other = p.projectId != projectId || p.clipId != clipId;
    p.drag = {}; p.velocityGesture = false;
    p.projectId = projectId; p.clipId = clipId; p.name = name; p.revision = revision;
    p.clipStart = startBeats; p.length = juce::jmax(0.001, lengthBeats); p.bpm = bpm; p.notes = notes;
    if (other) { p.selected.clear(); p.firstBeat = 0; p.fitPitch(); }
    // Select-all must not make a later edit perform one full note scan per ID.
    std::set<juce::String> retained;
    if (!p.selected.empty()) for (const auto& note : notes)
        if (p.selected.count(note.id)) retained.insert(note.id);
    p.selected = std::move(retained);
    p.refreshButtons(); p.layout();
}
bool PianoRoll::updateUnchangedClip(const juce::String& projectId, const juce::String& clipId,
                                    const juce::String& name, std::uint64_t revision,
                                    double startBeats, double lengthBeats, double bpm)
{
    auto& p = *impl;
    if (p.projectId != projectId || p.clipId != clipId) return false;
    const bool geometryChanged = p.clipStart != startBeats || p.length != lengthBeats || p.bpm != bpm;
    bool previewCancelled = false;
    if (p.revision != revision) {
        if (p.drag.mode != Impl::Drag::none && !p.drag.before.empty()) { p.notes = p.drag.before; previewCancelled = true; }
        if (p.velocityGesture) { p.notes = p.beforeVelocity; previewCancelled = true; }
        p.drag = {}; p.velocityGesture = false;
    }
    p.name = name; p.revision = revision; p.clipStart = startBeats;
    p.length = juce::jmax(0.001, lengthBeats); p.bpm = bpm;
    if (previewCancelled) p.refreshButtons();
    if (geometryChanged || previewCancelled) p.layout();
    return true;
}
void PianoRoll::setPlayhead(double seconds, bool playing)
{
    auto& p = *impl; const auto old = p.x(p.playheadBeat - p.clipStart); p.playheadBeat = seconds * p.bpm / 60.0; p.playing = playing;
    const auto now = p.x(p.playheadBeat - p.clipStart);
    p.grid.repaint(juce::roundToInt(old) - 2, 0, 5, p.grid.getHeight()); p.grid.repaint(juce::roundToInt(now) - 2, 0, 5, p.grid.getHeight());
}
void PianoRoll::resized()
{
    auto& p = *impl; auto top = getLocalBounds().reduced(12).removeFromTop(30);
    p.snap.setBounds(top.removeFromLeft(94)); top.removeFromLeft(8);
    p.erase.setBounds(top.removeFromLeft(65)); p.duplicate.setBounds(top.removeFromLeft(95)); p.quantize.setBounds(top.removeFromLeft(90));
    p.down.setButtonText("pitch -"); p.up.setButtonText("pitch +");
    p.down.setBounds(top.removeFromLeft(72)); p.up.setBounds(top.removeFromLeft(72));
    p.zoomOut.setBounds(top.removeFromLeft(30)); p.zoomIn.setBounds(top.removeFromLeft(30)); p.fit.setBounds(top.removeFromLeft(42));
    const bool drumMode = p.drums.getToggleState();
    const bool compact = getHeight() < 300;
    const bool stepOnly = compact && drumMode;
    p.grid.setVisible(!stepOnly); p.horizontal.setVisible(!stepOnly); p.vertical.setVisible(!stepOnly);
    p.grid.setBounds(12, compact ? 76 : 82, getWidth() - 38, juce::jmax(62, getHeight() - (compact ? 110 : drumMode ? 190 : 134)));
    p.horizontal.setBounds(60, p.grid.getBottom() + 2, getWidth() - 86, 13);
    p.vertical.setBounds(p.grid.getRight() + 2, p.grid.getY() + 27, 13, int(p.plot().getHeight()));
    p.velocity.setBounds(82, 46, 205, 27); p.drums.setBounds(getWidth() - 138, 46, 122, 27);
    p.drumPitch.setVisible(drumMode); p.drumBar.setVisible(drumMode);
    p.drumPitch.setBounds(12, getHeight() - 62, 150, 28); p.drumBar.setBounds(170, getHeight() - 62, 44, 28);
    const auto stepWidth = (getWidth() - 236) / 16;
    for (int i = 0; i < 16; ++i) { p.steps[std::size_t(i)]->setVisible(drumMode); p.steps[std::size_t(i)]->setBounds(224 + i * stepWidth, getHeight() - 62, stepWidth - 2, 28); }
    p.layout();
}
void PianoRoll::paint(juce::Graphics& g)
{
    auto& p = *impl; g.fillAll(paper); g.setColour(quiet); g.setFont(mono(12));
    g.drawText("velocity", 12, 46, 70, 27, juce::Justification::centredLeft);
    if (p.drums.getToggleState()) g.drawText("block", 170, getHeight() - 80, 44, 18, juce::Justification::centredLeft);
    g.drawFittedText(juce::String(int(p.notes.size())) + " notes / " + juce::String(int(p.selected.size())) + " selected   double-click: draw   drag: move / resize   Shift: select",
                    14, getHeight() - 26, getWidth() - 28, 20, juce::Justification::centredLeft, 1);
}
bool PianoRoll::keyPressed(const juce::KeyPress& key)
{
    auto& p = *impl;
    for (auto* focus = juce::Component::getCurrentlyFocusedComponent(); focus != nullptr; focus = focus->getParentComponent())
        if (dynamic_cast<juce::TextEditor*>(focus) != nullptr) return false;
    const auto mods = key.getModifiers(); const auto code = key.getKeyCode();
    if (code == juce::KeyPress::escapeKey && p.drag.mode != Impl::Drag::none) { if (!p.drag.before.empty()) p.notes = p.drag.before; p.drag = {}; p.layout(); return true; }
    if (code == juce::KeyPress::spaceKey) { if (onTogglePlay) onTogglePlay(); return true; }
    if (mods.isCtrlDown() || mods.isCommandDown()) {
        if (code == 'a' || code == 'A') { for (const auto& n : p.notes) p.selected.insert(n.id); p.refreshButtons(); p.grid.repaint(); return true; }
        if (code == 'd' || code == 'D') { p.duplicateSelected(); return true; }
        return onProjectKey ? onProjectKey(key) : false;
    }
    if (code == juce::KeyPress::deleteKey || code == juce::KeyPress::backspaceKey) { p.deleteSelected(); return true; }
    if (code == juce::KeyPress::upKey || code == juce::KeyPress::downKey) { p.transpose((code == juce::KeyPress::upKey ? 1 : -1) * (mods.isShiftDown() ? 12 : 1)); return true; }
    return false;
}
juce::Result PianoRoll::runInteractionSmokeTest(juce::DynamicObject& report)
{
    auto& p = *impl;
    std::uint64_t acceptedRevision = 7;
    int commits = 0;
    bool staleSubmission = false;
    std::vector<Note> accepted { { "test-note", 72, 1.0, 1.0, 90, 1 } };
    setClip("ui-test", "ui-test-clip", "MIDI interaction", acceptedRevision, 0, 8, 120, accepted);
    onWriteNotes = [&](const juce::String& id, const std::vector<Note>& notes, std::uint64_t expected) {
        if (expected != acceptedRevision || id != "ui-test-clip") staleSubmission = true;
        accepted = notes; ++commits; ++acceptedRevision;
        setClip("ui-test", "ui-test-clip", "MIDI interaction", acceptedRevision, 0, 8, 120, accepted);
    };
    const auto event = [&](juce::Point<float> position, juce::Point<float> start, bool dragged) {
        const auto now = juce::Time::getCurrentTime();
        return juce::MouseEvent(juce::Desktop::getInstance().getMainMouseSource(), position,
            juce::ModifierKeys(juce::ModifierKeys::leftButtonModifier), 1, 0, 0, 0, 0,
            &p.grid, &p.grid, now, start, now, 1, dragged);
    };
    const auto fail = [&](const char* message) { onWriteNotes = {}; return juce::Result::fail(message); };
    p.selected.insert("test-note");
    const auto* projection = p.notes.data();
    ++acceptedRevision;
    if (!updateUnchangedClip("ui-test", "ui-test-clip", "MIDI interaction", acceptedRevision, 0, 8, 120)
        || p.notes.data() != projection || !p.selected.count("test-note"))
        return fail("An unrelated project revision copied the unchanged MIDI projection or lost selection.");
    if (updateUnchangedClip("another-project", "ui-test-clip", "MIDI interaction", acceptedRevision, 0, 8, 120))
        return fail("MIDI projection reuse accepted a different project identity.");
    report.setProperty("midi_unchanged_snapshot_projection_reused", true);
    if (p.visible.empty()) return fail("Piano roll did not expose the visible note.");
    const auto start = p.visible.front().second.getCentre();
    const auto moved = start + juce::Point<float>(float(p.pixelsPerBeat * 0.5), -p.rowHeight);
    p.grid.mouseDown(event(start, start, false));
    p.grid.mouseDrag(event(start + juce::Point<float>(10, 0), start, true));
    p.grid.mouseDrag(event(moved, start, true));
    if (commits != 0) return fail("Piano roll wrote an edit before pointer release.");
    p.grid.mouseUp(event(moved, start, true));
    if (commits != 1 || accepted.size() != 1 || accepted.front().pitch != 73 || std::abs(accepted.front().startBeats - 1.5) > 1.0e-8)
        return fail("Piano roll move did not submit one snapped pitch/time edit.");
    report.setProperty("midi_drag_single_commit", true);

    const auto cancelStart = p.visible.front().second.getCentre();
    p.grid.mouseDown(event(cancelStart, cancelStart, false));
    p.grid.mouseDrag(event(cancelStart + juce::Point<float>(40, 18), cancelStart, true));
    keyPressed(juce::KeyPress(juce::KeyPress::escapeKey));
    p.grid.mouseUp(event(cancelStart + juce::Point<float>(40, 18), cancelStart, true));
    if (commits != 1 || p.notes.front().pitch != 73 || p.notes.front().startBeats != accepted.front().startBeats)
        return fail("Escape failed to discard the local MIDI preview.");
    report.setProperty("midi_escape_preserves_notes", true);

    p.grid.mouseDown(event(cancelStart, cancelStart, false));
    p.grid.mouseDrag(event(cancelStart + juce::Point<float>(40, 18), cancelStart, true));
    ++acceptedRevision;
    updateUnchangedClip("ui-test", "ui-test-clip", "MIDI interaction", acceptedRevision, 0, 8, 120);
    p.grid.mouseUp(event(cancelStart + juce::Point<float>(40, 18), cancelStart, true));
    if (commits != 1 || p.notes.front().pitch != accepted.front().pitch || p.notes.front().startBeats != accepted.front().startBeats)
        return fail("A changed project revision failed to cancel an unchanged-note local preview.");
    report.setProperty("midi_external_revision_cancels_preview", true);

    const auto resizeStart = p.visible.front().second.getTopRight() + juce::Point<float>(-2, 6);
    const auto resizeEnd = resizeStart + juce::Point<float>(float(p.pixelsPerBeat * 0.25), 0);
    p.grid.mouseDown(event(resizeStart, resizeStart, false)); p.grid.mouseDrag(event(resizeEnd, resizeStart, true)); p.grid.mouseUp(event(resizeEnd, resizeStart, true));
    if (commits != 2 || std::abs(accepted.front().lengthBeats - 1.25) > 1.0e-8) return fail("MIDI note resize did not preserve its start and extend its length.");
    report.setProperty("midi_note_resize", true);

    p.duplicate.onClick();
    if (commits != 3 || accepted.size() != 2 || accepted[0].id == accepted[1].id) return fail("Duplicate did not create an independently identified MIDI note.");
    p.velocity.setValue(110, juce::sendNotificationSync);
    if (commits != 4 || accepted.back().velocity != 110) return fail("Velocity editing did not target the selected note.");
    p.erase.onClick();
    if (commits != 5 || accepted.size() != 1) return fail("Delete did not remove just the selected MIDI note.");
    report.setProperty("midi_duplicate_velocity_delete", true);
    p.steps[0]->onClick();
    if (commits != 6 || accepted.size() != 2 || accepted.back().channel != accepted.front().channel || accepted.back().pitch != 36)
        return fail("The drum row failed to preserve the clip MIDI channel.");
    p.steps[0]->onClick();
    if (commits != 7 || accepted.size() != 1 || staleSubmission) return fail("The drum row or revision contract did not toggle cleanly.");
    report.setProperty("midi_drum_steps_share_note_model", true);
    report.setProperty("midi_editor_revision_contract", true);
    onWriteNotes = {};
    setSize(726, 224);
    setClip("first-open", "bass-notes", "Bass", 1, 0, 4, 120, { { "low-note", 36, 0, 1, 90, 1 } });
    if (p.visible.empty()) return fail("First opening a low MIDI note in the dock left the note outside the visible pitch range.");
    report.setProperty("midi_first_open_fits_pitch_in_dock", true);
    p.drums.setToggleState(true, juce::dontSendNotification); resized();
    if (p.grid.isVisible() || !p.steps.front()->isVisible() || p.steps.front()->getBottom() > getHeight() - 26)
        return fail("Compact drum mode overlaps the piano editor or falls outside the dock.");
    report.setProperty("midi_compact_drum_mode_fits_dock", true);
    setSize(1000, 580);
    setClip("ui-test", "ui-test-clip", "MIDI interaction", acceptedRevision, 0, 8, 120, accepted);
    p.drums.setToggleState(true, juce::dontSendNotification);
    resized();
    onWriteNotes = {};
    return juce::Result::ok();
}
}
