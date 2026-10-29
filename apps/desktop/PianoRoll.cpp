#include "PianoRoll.h"
#include "core/time/EditGrid.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <set>

namespace emusician {
namespace {
const juce::Colour ink { 0xff171817 }, rule { 0xffc6c9c3 }, paper { 0xfffefefd }, quiet { 0xff626560 };
juce::Font mono(float size) { return juce::Font(juce::FontOptions(juce::Font::getDefaultMonospacedFontName(), size, juce::Font::plain)); }
bool isTextInput(const juce::Component* focus)
{
    for (; focus != nullptr; focus = focus->getParentComponent()) if (dynamic_cast<const juce::TextEditor*>(focus) != nullptr) return true;
    return false;
}
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
        void mouseDoubleClick(const juce::MouseEvent& e) override { if (!p.draw.getToggleState()) p.insert(e.position, e.mods.isAltDown()); }
        void mouseWheelMove(const juce::MouseEvent& e, const juce::MouseWheelDetails& wheel) override
        {
            if (e.mods.isCtrlDown() && wheel.deltaY != 0) p.setZoom(p.pixelsPerBeat * (wheel.deltaY > 0 ? 1.25 : 0.8), e.position.x);
            else if (e.mods.isShiftDown()) { p.firstBeat = juce::jmax(0.0, p.firstBeat - wheel.deltaY * p.visibleBeats()); p.layout(); }
            else { p.topPitch = juce::jlimit(12, 127, p.topPitch + juce::roundToInt(wheel.deltaY * 24.0f)); p.layout(); }
        }
        bool keyPressed(const juce::KeyPress& key) override { return p.owner.keyPressed(key); }
        Impl& p;
    };
    explicit Impl(PianoRoll& c) : owner(c), grid(*this), horizontal(false), vertical(true)
    {
        for (juce::Component* item : std::initializer_list<juce::Component*> {
                &grid, &horizontal, &vertical, &snap, &snapEnabled, &draw, &copy, &cut, &paste, &erase, &duplicate, &quantize,
                &down, &up, &velocity, &zoomOut, &zoomIn, &fit, &drums, &drumPitch, &drumBar }) owner.addAndMakeVisible(item);
        for (auto* button : { &draw, &snapEnabled, &copy, &cut, &paste, &erase, &duplicate, &quantize, &down, &up, &zoomOut, &zoomIn, &fit, &drums }) button->getProperties().set("flat", true);
        snap.addItem("1/4", 2); snap.addItem("1/8", 3); snap.addItem("1/16", 4); snap.addItem("1/32", 5);
        snap.addItem("1/64", 6);
        for (int power = 7; power <= 14; ++power) snap.addItem("1/" + juce::String(1 << power), power + 2);
        snap.addItem("1/8 T", 7); snap.addItem("1/16 T", 8);
        snap.setSelectedId(4, juce::dontSendNotification);
        snap.onChange = [this] { const auto id = snap.getSelectedId(); gridBeats = id == 7 ? 1.0 / 3.0 : id == 8 ? 1.0 / 6.0 : std::ldexp(1.0, id >= 9 ? 4 - id : 2 - id); layout(); };
        snap.setTooltip("Note grid: 1/4 through 1/16384 of a whole note. T means triplets. Snap off shows dashed time lines.");
        snapEnabled.setClickingTogglesState(true); snapEnabled.setToggleState(true, juce::dontSendNotification);
        snapEnabled.setTooltip("Snap note starts and ends to the grid. Alt bypasses snap temporarily; Ctrl+4 toggles it.");
        snapEnabled.onClick = [this] { grid.repaint(); owner.repaint(); };
        draw.setClickingTogglesState(true); draw.setTooltip("Draw [B]: click an empty cell to add a note. Existing notes can still be selected and dragged.");
        draw.onClick = [this] { editError.clear(); owner.repaint(); };
        copy.onClick = [this] { copySelected(false); }; cut.onClick = [this] { copySelected(true); }; paste.onClick = [this] { pasteNotes(); };
        copy.setTooltip("Copy selected notes (Ctrl+C)."); cut.setTooltip("Cut selected notes (Ctrl+X).");
        paste.setTooltip("Paste at the insertion marker (Ctrl+V). Click the ruler or an empty cell to place it; otherwise use the playhead.");
        erase.onClick = [this] { deleteSelected(); };
        duplicate.onClick = [this] { duplicateSelected(); };
        quantize.onClick = [this] { modify([](Note& n, Impl& p) { n.startBeats = time::snapEditBeat(n.startBeats, p.gridBeats); n.lengthBeats = juce::jmax(time::minimumEditGridBeats, time::snapEditBeat(n.lengthBeats, p.gridBeats)); }); };
        down.onClick = [this] { transpose(-1); }; up.onClick = [this] { transpose(1); };
        down.setTooltip("Transpose selected notes down one semitone (Down arrow; Shift+Down for one octave).");
        up.setTooltip("Transpose selected notes up one semitone (Up arrow; Shift+Up for one octave).");
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
    bool veryCompact() const { return owner.getHeight() <= 190; }
    int rulerHeight() const { return veryCompact() ? 18 : 27; }
    juce::Rectangle<float> plot() const { return grid.getLocalBounds().toFloat().withTrimmedLeft(48).withTrimmedTop(float(rulerHeight())).withTrimmedBottom(veryCompact() ? 14.0f : owner.getHeight() < 300 ? 24.0f : 47.0f); }
    void fitPitch()
    {
        if (notes.empty()) { topPitch = 72; return; }
        int low = 127, high = 0;
        for (const auto& n : notes) { low = juce::jmin(low, n.pitch); high = juce::jmax(high, n.pitch); }
        rowHeight = juce::jlimit(8.0f, 18.0f, plot().getHeight() / float(high - low + 3));
        const int rows = juce::jmax(1, int(plot().getHeight() / rowHeight));
        topPitch = juce::jmin(127, high + juce::jlimit(0, 2, (rows - (high - low + 1)) / 2));
    }
    double visibleBeats() const { return juce::jmax(time::minimumEditGridBeats, plot().getWidth() / pixelsPerBeat); }
    double snapped(double value) const { return snapEnabled.getToggleState() ? time::snapEditBeat(value, gridBeats) : value; }
    double insertionPoint() const { return juce::jlimit(0.0, length, insertionExplicit ? insertionBeat : playheadBeat - clipStart); }
    void markInsertion(double beat) { insertionBeat = juce::jlimit(0.0, length, beat); insertionExplicit = true; editError.clear(); grid.repaint(); owner.repaint(); }
    float x(double beat) const
    {
        // Convert only viewport-relative coordinates to float. A many-hour clip
        // at deep zoom must never create giant canvas geometry or int overflow.
        const double guard = juce::jmax(1, grid.getWidth()) * 4.0;
        return plot().getX() + float(juce::jlimit(-guard, guard, (beat - firstBeat) * pixelsPerBeat));
    }
    float y(int pitch) const { return plot().getY() + float(topPitch - pitch) * rowHeight; }
    double atBeat(float px, bool bypass = false) const { const double b = firstBeat + (px - plot().getX()) / pixelsPerBeat; return juce::jmax(0.0, bypass ? b : snapped(b)); }
    int atPitch(float py) const { return juce::jlimit(0, 127, topPitch - int(std::floor((py - plot().getY()) / rowHeight))); }
    static constexpr std::size_t maximumVisibleNotes = 8192;
    static constexpr double maximumPixelsPerBeat = 65536.0;
    struct IndexedNote { std::size_t note; int left = -1, right = -1; double start = 0, end = 0, maxEnd = 0; };
    int buildIndex(const std::vector<std::size_t>& entries, std::size_t begin, std::size_t end)
    {
        if (begin == end) return -1;
        const auto middle = begin + (end - begin) / 2;
        const auto noteIndex = entries[middle]; const auto& note = notes[noteIndex];
        const int index = int(noteIndexNodes.size());
        noteIndexNodes.push_back({ noteIndex, -1, -1, note.startBeats, note.startBeats + note.lengthBeats, note.startBeats + note.lengthBeats });
        const int left = buildIndex(entries, begin, middle), right = buildIndex(entries, middle + 1, end);
        auto& node = noteIndexNodes[std::size_t(index)]; node.left = left; node.right = right;
        if (left >= 0) node.maxEnd = juce::jmax(node.maxEnd, noteIndexNodes[std::size_t(left)].maxEnd);
        if (right >= 0) node.maxEnd = juce::jmax(node.maxEnd, noteIndexNodes[std::size_t(right)].maxEnd);
        return index;
    }
    void rebuildNoteIndex()
    {
        ++indexBuilds;
        noteIndexNodes.clear(); noteIndexNodes.reserve(notes.size()); noteIndexRoots.fill(-1);
        std::array<std::vector<std::size_t>, 128> pitches;
        for (std::size_t i = 0; i < notes.size(); ++i) if (notes[i].pitch >= 0 && notes[i].pitch <= 127) pitches[std::size_t(notes[i].pitch)].push_back(i);
        for (std::size_t pitch = 0; pitch < pitches.size(); ++pitch) {
            auto& entries = pitches[pitch];
            std::sort(entries.begin(), entries.end(), [&](auto a, auto b) { return notes[a].startBeats == notes[b].startBeats ? a < b : notes[a].startBeats < notes[b].startBeats; });
            noteIndexRoots[pitch] = buildIndex(entries, 0, entries.size());
        }
    }
    juce::Rectangle<float> noteRectangle(std::size_t index) const
    {
        const auto& note = notes[index]; const auto area = plot();
        const double end = note.startBeats + note.lengthBeats;
        if (end <= firstBeat || note.startBeats >= firstBeat + visibleBeats()) return {};
        const double left = juce::jmax(double(area.getX()) - 2.0, double(area.getX()) + (note.startBeats - firstBeat) * pixelsPerBeat);
        const double right = juce::jmin(double(area.getRight()) + 2.0, double(area.getX()) + (end - firstBeat) * pixelsPerBeat);
        return { float(left), y(note.pitch) + 1, float(juce::jmax(2.0, right - left)), rowHeight - 2 };
    }
    void appendVisible(std::size_t index)
    {
        const auto rectangle = noteRectangle(index);
        if (rectangle.intersects(plot())) visible.push_back({ index, rectangle });
    }
    template<typename F> void visitNotes(int index, double begin, double end, F&& visit) const
    {
        if (index < 0) return;
        const auto& node = noteIndexNodes[std::size_t(index)];
        if (node.maxEnd <= begin) return;
        visitNotes(node.left, begin, end, visit);
        if (node.start > end) return;
        if (node.end > begin) visit(node.note);
        visitNotes(node.right, begin, end, visit);
    }
    std::size_t hitNote(juce::Point<float> point) const
    {
        // Hit-testing is independent of the preview drawing budget. Choosing the
        // highest source index matches the stable paint order even in dense views.
        std::size_t hit = notes.size();
        if (!plot().contains(point)) return hit;
        const double beat = firstBeat + (point.x - plot().getX()) / pixelsPerBeat;
        visitNotes(noteIndexRoots[std::size_t(atPitch(point.y))], beat - 2.0 / pixelsPerBeat, beat,
            [&](std::size_t index) { if (noteRectangle(index).contains(point) && (hit == notes.size() || index > hit)) hit = index; });
        return hit;
    }
    void completeBoxSelection()
    {
        selected = drag.selectionBefore;
        const auto box = drag.selectionBox.getIntersection(plot());
        if (box.isEmpty()) return;
        const double begin = firstBeat + (box.getX() - plot().getX() - 2.0) / pixelsPerBeat;
        const double end = firstBeat + (box.getRight() - plot().getX()) / pixelsPerBeat;
        const int low = atPitch(box.getBottom()), high = atPitch(box.getY());
        for (int pitch = low; pitch <= high; ++pitch)
            visitNotes(noteIndexRoots[std::size_t(pitch)], begin, end, [&](std::size_t index) {
                if (noteRectangle(index).intersects(box)) selected.insert(notes[index].id);
            });
    }
    void queryVisible(int index, double end)
    {
        if (index < 0 || visible.size() >= maximumVisibleNotes) { if (index >= 0) densePreview = true; return; }
        ++queriedIndexNodes;
        const auto& node = noteIndexNodes[std::size_t(index)];
        if (node.maxEnd <= firstBeat) return;
        queryVisible(node.left, end);
        if (node.start >= end || visible.size() >= maximumVisibleNotes) { if (visible.size() >= maximumVisibleNotes) densePreview = true; return; }
        if (node.end > firstBeat && !std::binary_search(drag.indices.begin(), drag.indices.end(), node.note)) appendVisible(node.note);
        queryVisible(node.right, end);
    }
    void layout()
    {
        firstBeat = juce::jlimit(0.0, juce::jmax(0.0, length - visibleBeats()), firstBeat);
        horizontal.setRangeLimits(0, juce::jmax(length, visibleBeats()), juce::dontSendNotification);
        horizontal.setCurrentRange(firstBeat, visibleBeats(), juce::dontSendNotification);
        vertical.setRangeLimits(0, 128, juce::dontSendNotification);
        vertical.setCurrentRange(127 - topPitch, juce::jmin(128.0, double(plot().getHeight() / rowHeight)), juce::dontSendNotification);
        visible.clear(); queriedIndexNodes = 0; densePreview = false;
        // The immutable index represents the committed snapshot. Preview only the
        // selected notes separately, including those dragged into a new row/range.
        for (auto index : drag.indices) { if (visible.size() >= maximumVisibleNotes) { densePreview = true; break; } appendVisible(index); }
        const int lowest = juce::jmax(0, topPitch - int(std::ceil(plot().getHeight() / rowHeight)));
        for (int pitch = juce::jmin(127, topPitch); pitch >= lowest; --pitch) queryVisible(noteIndexRoots[std::size_t(pitch)], firstBeat + visibleBeats());
        std::sort(visible.begin(), visible.end(), [](const auto& a, const auto& b) { return a.first < b.first; });
        grid.repaint(); owner.repaint();
    }
    void scrollBarMoved(juce::ScrollBar* bar, double value) override { if (bar == &horizontal) firstBeat = value; else topPitch = 127 - int(value); layout(); }
    void setZoom(double value, float anchorX = -1)
    {
        const auto area = plot();
        if (anchorX < 0) anchorX = area.getCentreX();
        anchorX = juce::jlimit(area.getX(), area.getRight(), anchorX);
        const double anchor = firstBeat + (anchorX - area.getX()) / pixelsPerBeat;
        pixelsPerBeat = juce::jlimit(12.0, maximumPixelsPerBeat, value);
        firstBeat = anchor - (anchorX - area.getX()) / pixelsPerBeat;
        layout();
    }
    void refreshButtons()
    {
        const bool usable = clipId.isNotEmpty(); const bool chosen = usable && !selected.empty();
        for (auto* b : { &copy, &cut, &erase, &duplicate, &quantize, &down, &up }) b->setEnabled(chosen);
        paste.setEnabled(usable && clipboardProject == projectId && !clipboard.empty()); draw.setEnabled(usable);
        velocity.setEnabled(chosen); drums.setEnabled(usable);
        if (chosen && !velocityGesture) for (const auto& n : notes) if (selected.count(n.id)) {
            updating = true; velocity.setValue(n.velocity, juce::dontSendNotification); updating = false; break;
        }
        refreshSteps();
    }
    void refreshSteps()
    {
        if (steps.size() != 16 || !drums.getToggleState()) return;
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
        editError.clear();
        rebuildNoteIndex(); refreshButtons(); layout();
        if (owner.onWriteNotes && clipId.isNotEmpty()) owner.onWriteNotes(clipId, notes, expected);
    }
    template<typename F> void modify(F fn)
    {
        if (selected.empty() || clipId.isEmpty()) return;
        for (auto& n : notes) if (selected.count(n.id)) { fn(n, *this); n.lengthBeats = juce::jlimit(juce::jmin(time::minimumEditGridBeats, n.lengthBeats), length, n.lengthBeats); n.startBeats = juce::jlimit(0.0, length - n.lengthBeats, n.startBeats); }
        submit(revision);
    }
    void transpose(int delta) { modify([delta](Note& n, Impl&) { n.pitch = juce::jlimit(0, 127, n.pitch + delta); }); }
    void deleteSelected()
    {
        if (selected.empty()) return;
        std::erase_if(notes, [this](const auto& n) { return selected.count(n.id) != 0; }); selected.clear(); submit(revision);
    }
    void reject(const juce::String& message)
    {
        editError = message; owner.repaint();
        if (owner.onEditError) owner.onEditError(message);
    }
    bool validNote(const Note& n) const
    {
        return n.pitch >= 0 && n.pitch <= 127 && n.velocity >= 1 && n.velocity <= 127
            && n.channel >= 1 && n.channel <= 16 && std::isfinite(n.startBeats) && n.startBeats >= 0
            && std::isfinite(n.lengthBeats) && n.lengthBeats > 0 && std::isfinite(n.startBeats + n.lengthBeats)
            && n.startBeats + n.lengthBeats > n.startBeats;
    }
    bool copySelected(bool remove)
    {
        if (selected.empty() || clipId.isEmpty()) return false;
        std::vector<Note> content; double first = length;
        for (const auto& n : notes) if (selected.count(n.id)) {
            if (!validNote(n) || n.startBeats + n.lengthBeats > length + 1.0e-9) { reject("Cannot copy an invalid note. Correct its timing first."); return false; }
            content.push_back(n); first = juce::jmin(first, n.startBeats);
        }
        if (content.empty()) return false;
        for (auto& n : content) n.startBeats -= first;
        clipboard = std::move(content); clipboardProject = projectId; editError.clear();
        if (remove) deleteSelected(); else { refreshButtons(); owner.repaint(); }
        return true;
    }
    void pasteNotes()
    {
        if (clipId.isEmpty() || clipboard.empty() || clipboardProject != projectId) return;
        if (clipboard.size() > 100000 - juce::jmin<std::size_t>(100000, notes.size())) { reject("Paste would exceed 100,000 notes in this clip."); return; }
        const auto start = snapped(insertionPoint());
        std::vector<Note> copies; copies.reserve(clipboard.size()); std::set<juce::String> ids; double last = start;
        for (const auto& original : clipboard) {
            auto n = original; n.startBeats += start;
            if (!validNote(n) || n.startBeats + n.lengthBeats > length + 1.0e-9) {
                reject("Paste does not fit inside this clip. Move the insertion marker earlier or extend the clip."); return;
            }
            if ((!notes.empty() && n.channel != notes.front().channel) || n.channel != clipboard.front().channel) {
                reject("Paste needs the same MIDI channel as this clip. The copied notes were kept unchanged."); return;
            }
            n.id = juce::Uuid().toString(); ids.insert(n.id); last = juce::jmax(last, n.startBeats + n.lengthBeats); copies.push_back(std::move(n));
        }
        notes.insert(notes.end(), copies.begin(), copies.end()); selected = std::move(ids);
        insertionBeat = last; insertionExplicit = true; submit(revision);
    }
    void duplicateSelected()
    {
        if (selected.empty()) return;
        double first = length, last = 0;
        for (const auto& n : notes) if (selected.count(n.id)) { first = juce::jmin(first, n.startBeats); last = juce::jmax(last, n.startBeats + n.lengthBeats); }
        const auto delta = last - first; std::vector<Note> copies; std::set<juce::String> ids;
        for (const auto& n : notes) if (selected.count(n.id)) {
            if (!validNote(n) || n.startBeats + delta + n.lengthBeats > length + 1.0e-9) { reject("Duplicate does not fit inside this clip. Extend the clip first."); return; }
            auto copy = n; copy.id = juce::Uuid().toString(); copy.startBeats += delta; ids.insert(copy.id); copies.push_back(std::move(copy));
        }
        if (copies.empty()) return;
        if (copies.size() > 100000 - juce::jmin<std::size_t>(100000, notes.size())) { reject("Duplicate would exceed 100,000 notes in this clip."); return; }
        notes.insert(notes.end(), copies.begin(), copies.end()); selected = std::move(ids); submit(revision);
    }
    void insert(juce::Point<float> point, bool bypass = false)
    {
        if (clipId.isEmpty() || !plot().contains(point)) return;
        if (hitNote(point) != notes.size()) return;
        const auto start = atBeat(point.x, bypass); const auto len = juce::jmin(gridBeats, length - start);
        if (!std::isfinite(len) || len <= 0 || start + len <= start) return;
        if (notes.size() >= 100000) { reject("This clip already contains 100,000 notes."); return; }
        Note n { juce::Uuid().toString(), atPitch(point.y), start, len, int(velocity.getValue()), notes.empty() ? 1 : notes.front().channel };
        markInsertion(start);
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
        if (e.position.y < plot().getY() && e.position.x >= plot().getX()) { markInsertion(atBeat(e.position.x, e.mods.isAltDown())); if (owner.onSeek) owner.onSeek((clipStart + insertionPoint()) * 60.0 / bpm); return; }
        const auto hit = hitNote(e.position);
        if (hit != notes.size()) {
            const auto& n = notes[hit]; const auto rectangle = noteRectangle(hit);
            if (e.mods.isShiftDown() || e.mods.isCtrlDown()) { if (selected.count(n.id)) selected.erase(n.id); else selected.insert(n.id); }
            else if (!selected.count(n.id)) selected = { n.id };
            if (!selected.count(n.id)) { refreshButtons(); grid.repaint(); return; }
            const bool endVisible = n.startBeats + n.lengthBeats <= firstBeat + visibleBeats();
            drag.mode = endVisible && e.position.x >= rectangle.getRight() - juce::jmin(6.0f, rectangle.getWidth() * 0.35f) ? Drag::resize : Drag::move;
            drag.anchor = e.position; drag.revision = revision; drag.before = notes; drag.activeId = n.id; prepareDrag();
            refreshButtons(); grid.repaint(); return;
        }
        if (e.position.y >= plot().getBottom() && e.position.x >= plot().getX()) {
            for (const auto& v : visible) if (std::abs(e.position.x - v.second.getX()) < 6) { selected = { notes[v.first].id }; drag.mode = Drag::velocity; drag.anchor = e.position; drag.revision = revision; drag.before = notes; prepareDrag(); refreshButtons(); return; }
        }
        if (plot().contains(e.position)) {
            markInsertion(atBeat(e.position.x, e.mods.isAltDown()));
            if (draw.getToggleState() && !e.mods.isShiftDown() && !e.mods.isCtrlDown()) { insert(e.position, e.mods.isAltDown()); return; }
            if (!e.mods.isShiftDown() && !e.mods.isCtrlDown()) selected.clear();
            drag.mode = Drag::box; drag.selectionBefore = selected; drag.anchor = e.position; drag.revision = revision; drag.selectionBox = { e.position, e.position }; refreshButtons(); grid.repaint();
        }
    }
    void prepareDrag()
    {
        drag.minStart = length; drag.maxEnd = 0; drag.minPitch = 127; drag.maxPitch = 0;
        drag.leastResize = -length; drag.mostResize = length;
        for (std::size_t i = 0; i < notes.size(); ++i) if (selected.count(notes[i].id)) {
            const auto& n = notes[i]; drag.indices.push_back(i);
            drag.minStart = juce::jmin(drag.minStart, n.startBeats); drag.maxEnd = juce::jmax(drag.maxEnd, n.startBeats + n.lengthBeats);
            drag.minPitch = juce::jmin(drag.minPitch, n.pitch); drag.maxPitch = juce::jmax(drag.maxPitch, n.pitch);
            drag.leastResize = juce::jmax(drag.leastResize, juce::jmin(time::minimumEditGridBeats, n.lengthBeats) - n.lengthBeats);
            drag.mostResize = juce::jmin(drag.mostResize, length - n.startBeats - n.lengthBeats);
            if (n.id == drag.activeId) drag.activeEdge = n.startBeats + (drag.mode == Drag::resize ? n.lengthBeats : 0.0);
        }
    }
    void dragTo(const juce::MouseEvent& e)
    {
        if (drag.mode == Drag::none) return;
        drag.changed = drag.changed || e.getDistanceFromDragStart() >= 3;
        if (!drag.changed) return;
        if (drag.mode == Drag::box) {
            selected = drag.selectionBefore; drag.selectionBox = { drag.anchor, e.position }; for (const auto& v : visible) if (v.second.intersects(drag.selectionBox)) selected.insert(notes[v.first].id); grid.repaint(); refreshButtons(); return;
        }
        double delta = (e.position.x - drag.anchor.x) / pixelsPerBeat;
        if (!e.mods.isAltDown() && snapEnabled.getToggleState()) delta = snapped(drag.activeEdge + delta) - drag.activeEdge;
        const int pitchDelta = juce::jlimit(-drag.minPitch, 127 - drag.maxPitch, juce::roundToInt((drag.anchor.y - e.position.y) / rowHeight));
        if (drag.mode == Drag::move) delta = juce::jlimit(-drag.minStart, length - drag.maxEnd, delta);
        if (drag.mode == Drag::resize) delta = juce::jlimit(drag.leastResize, drag.mostResize, delta);
        // Never copy or scan the entire note collection for each pointer event.
        for (auto index : drag.indices) {
            auto& n = notes[index]; n = drag.before[index];
            if (drag.mode == Drag::move) { n.startBeats += delta; n.pitch += pitchDelta; }
            else if (drag.mode == Drag::resize) n.lengthBeats += delta;
            else if (drag.mode == Drag::velocity) n.velocity = juce::jlimit(1, 127, n.velocity + juce::roundToInt((drag.anchor.y - e.position.y) * 2));
        }
        layout();
    }
    void end(const juce::MouseEvent&)
    {
        const auto mode = drag.mode; const auto changed = drag.changed; const auto expected = drag.revision;
        if (changed && mode == Drag::box) completeBoxSelection();
        drag = {};
        if (changed && mode != Drag::none && mode != Drag::box) submit(expected);
        else { refreshButtons(); grid.repaint(); }
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
        lastPaintedTimeLines = 0;
        const auto timeLine = [&](float xx, float opacity) {
            ++lastPaintedTimeLines; g.setColour(rule.withAlpha(opacity));
            if (snapEnabled.getToggleState()) g.drawVerticalLine(juce::roundToInt(xx), float(rulerHeight()), float(grid.getHeight()));
            else { const float dashes[] { 4.0f, 4.0f }; g.drawDashedLine({ xx, float(rulerHeight()), xx, float(grid.getHeight()) }, dashes, 2); }
        };
        const auto gridLines = [&](double step, float opacity) {
            const double density = pixelsPerBeat * step;
            if (density < 6.0) step *= std::pow(2.0, std::ceil(std::log2(6.0 / density)));
            const auto first = std::ceil(firstBeat / step - 1.0e-8);
            const auto last = std::floor(juce::jmin(length, firstBeat + visibleBeats()) / step + 1.0e-8);
            const int count = juce::jlimit(0, int(area.getWidth() / 6.0f) + 3, int(last - first + 1));
            for (int i = 0; i < count; ++i) { const auto xx = x((first + i) * step); timeLine(xx, opacity); g.drawVerticalLine(juce::roundToInt(xx), float(rulerHeight() - 4), float(rulerHeight())); }
        };
        gridLines(gridBeats, 0.35f); gridLines(beatUnit, 0.65f); gridLines(barBeats, 1.0f);
        const auto ruler = time::musicalRulerStep(visibleBeats(), area.getWidth(), timeSignatureNumerator, timeSignatureDenominator);
        const double firstLabel = std::ceil(firstBeat / ruler.stepBeats - 1.0e-8);
        const double lastLabel = std::floor(juce::jmin(length, firstBeat + visibleBeats()) / ruler.stepBeats + 1.0e-8);
        g.setColour(quiet); g.setFont(mono(11));
        lastPaintedLabels.clear(); float labelRight = area.getX() - 4;
        for (double i = firstLabel; i <= lastLabel; ++i) {
            const double beat = i * ruler.stepBeats;
            const auto label = juce::String(time::musicalRulerLabel(beat, timeSignatureNumerator, timeSignatureDenominator, ruler.labelTier));
            const float left = float(juce::roundToInt(x(beat)) + 4);
            const int width = int(std::ceil(juce::GlyphArrangement::getStringWidth(g.getCurrentFont(), label))) + 2;
            if (left < labelRight + 4 || left + width > area.getRight()) continue;
            g.drawText(label, int(left), 1, width, rulerHeight() - 3, juce::Justification::centredLeft);
            labelRight = left + float(width); lastPaintedLabels.push_back({ left, labelRight });
        }
        if (densePreview) {
            // Visible even in the minimum dock where the lower help row is hidden.
            g.setColour(paper); g.fillRect(int(area.getRight()) - 186, 0, 186, rulerHeight() - 2);
            g.setColour(quiet); g.drawText("dense preview: zoom in", int(area.getRight()) - 184, 1, 182, rulerHeight() - 3, juce::Justification::centredRight);
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
        const float velocityHeight = veryCompact() ? 10.0f : owner.getHeight() < 300 ? 18.0f : 35.0f;
        g.setFont(mono(10)); g.setColour(quiet); g.drawText("vel", 2, int(area.getBottom()), 40, int(velocityHeight), juce::Justification::centred);
        for (const auto& v : visible) {
            const auto& n = notes[v.first]; const float h = float(n.velocity) / 127.0f * velocityHeight;
            g.setColour(selected.count(n.id) ? ink : quiet); g.fillRect(v.second.getX(), float(grid.getHeight()) - h - 3, 2.0f, h);
        }
        const auto head = x(playheadBeat - clipStart);
        if (head >= area.getX() && head <= area.getRight()) { g.setColour(ink.withAlpha(playing ? 1.0f : 0.45f)); g.drawVerticalLine(juce::roundToInt(head), 0, float(grid.getHeight())); }
        const auto insertX = x(insertionPoint());
        if (insertionExplicit && insertX >= area.getX() && insertX <= area.getRight()) {
            g.setColour(quiet); const float dashes[] { 3.0f, 3.0f };
            g.drawDashedLine(juce::Line<float>(insertX, area.getY(), insertX, area.getBottom()), dashes, 2);
            const auto markerBottom = float(rulerHeight() - 4);
            juce::Path marker; marker.addTriangle(insertX - 4, markerBottom - 6, insertX + 4, markerBottom - 6, insertX, markerBottom); g.fillPath(marker);
        }
        if (grid.hasKeyboardFocus(true)) { g.setColour(ink); g.drawRect(grid.getLocalBounds().reduced(1), 1); }
    }
    PianoRoll& owner;
    Grid grid;
    juce::ScrollBar horizontal, vertical;
    juce::ComboBox snap, drumPitch;
    juce::TextEditor drumBar;
    juce::TextButton draw { "draw B" }, snapEnabled { "snap" }, copy { "copy" }, cut { "cut" }, paste { "paste" };
    juce::TextButton erase { "delete" }, duplicate { "duplicate" }, quantize { "quantize" }, down { "-1 st" }, up { "+1 st" };
    juce::TextButton zoomOut { "-" }, zoomIn { "+" }, fit { "fit" }, drums { "drum steps" };
    juce::Slider velocity;
    std::vector<std::unique_ptr<juce::TextButton>> steps;
    std::vector<Note> notes, beforeVelocity, clipboard;
    std::vector<std::pair<std::size_t, juce::Rectangle<float>>> visible;
    std::vector<IndexedNote> noteIndexNodes;
    std::array<int, 128> noteIndexRoots = [] { std::array<int, 128> result {}; result.fill(-1); return result; }();
    std::size_t indexBuilds = 0, queriedIndexNodes = 0;
    int lastPaintedTimeLines = 0;
    std::vector<std::pair<float, float>> lastPaintedLabels;
    bool densePreview = false;
    std::set<juce::String> selected;
    juce::String projectId, clipId, name, clipboardProject, editError;
    std::uint64_t revision = 0, gestureRevision = 0;
    double clipStart = 0, length = 4, bpm = 120, firstBeat = 0, pixelsPerBeat = 80, gridBeats = 0.25, playheadBeat = 0, barBeats = 4, beatUnit = 1, insertionBeat = 0;
    float rowHeight = 18;
    int topPitch = 84, timeSignatureNumerator = 4, timeSignatureDenominator = 4;
    bool updating = false, velocityGesture = false, playing = false, insertionExplicit = false;
    struct Drag { enum Mode { none, move, resize, box, velocity } mode = none; juce::Point<float> anchor; juce::Rectangle<float> selectionBox; std::vector<Note> before; std::vector<std::size_t> indices; double minStart = 0, maxEnd = 0, leastResize = 0, mostResize = 0, activeEdge = 0; int minPitch = 0, maxPitch = 127; std::set<juce::String> selectionBefore; std::uint64_t revision = 0; juce::String activeId; bool changed = false; } drag;
};

PianoRoll::PianoRoll() : impl(std::make_unique<Impl>(*this)) { setSize(1000, 580); }
PianoRoll::~PianoRoll() = default;
void PianoRoll::setTimeSignature(int numerator, int denominator)
{
    const double next = time::beatsPerBar(numerator, denominator), unit = 4.0 / juce::jmax(1, denominator);
    if (next != impl->barBeats || unit != impl->beatUnit) { impl->barBeats = next; impl->beatUnit = unit; impl->timeSignatureNumerator = numerator; impl->timeSignatureDenominator = denominator; impl->grid.repaint(); }
}
void PianoRoll::setClip(const juce::String& projectId, const juce::String& clipId, const juce::String& name,
                       std::uint64_t revision, double startBeats, double lengthBeats, double bpm,
                       const std::vector<Note>& notes)
{
    auto& p = *impl;
    if (p.projectId == projectId && p.clipId == clipId && p.revision == revision) return;
    const bool other = p.projectId != projectId || p.clipId != clipId;
    p.drag = {}; p.velocityGesture = false;
    if (projectId.isNotEmpty() && p.clipboardProject.isNotEmpty() && p.clipboardProject != projectId) { p.clipboard.clear(); p.clipboardProject.clear(); }
    p.projectId = projectId; p.clipId = clipId; p.name = name; p.revision = revision;
    p.clipStart = startBeats; p.length = juce::jmax(time::minimumEditGridBeats, lengthBeats); p.bpm = bpm; p.notes = notes; p.rebuildNoteIndex();
    if (other) { p.selected.clear(); p.firstBeat = 0; p.insertionExplicit = false; p.editError.clear(); p.fitPitch(); }
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
    p.length = juce::jmax(time::minimumEditGridBeats, lengthBeats); p.bpm = bpm;
    if (previewCancelled) p.refreshButtons();
    if (geometryChanged || previewCancelled) p.layout();
    return true;
}
void PianoRoll::setPlayhead(double seconds, bool playing)
{
    auto& p = *impl; const auto old = p.x(p.playheadBeat - p.clipStart); p.playheadBeat = seconds * p.bpm / 60.0; p.playing = playing;
    const auto now = p.x(p.playheadBeat - p.clipStart);
    p.grid.repaint(juce::roundToInt(old) - 2, 0, 5, p.grid.getHeight()); p.grid.repaint(juce::roundToInt(now) - 2, 0, 5, p.grid.getHeight());
    if (!p.insertionExplicit && !p.veryCompact()) repaint(14, getHeight() - 26, getWidth() - 28, 20);
}
void PianoRoll::resized()
{
    auto& p = *impl; auto top = getLocalBounds().reduced(12).removeFromTop(30);
    // Allow for the host's 15 px monospaced labels and 8 px button insets.
    // Keep transpose in the second row so labels fit even in the 726 px dock.
    p.draw.setBounds(top.removeFromLeft(72)); p.snapEnabled.setBounds(top.removeFromLeft(60));
    p.snap.setBounds(top.removeFromLeft(102)); top.removeFromLeft(8);
    p.erase.setBounds(top.removeFromLeft(76)); p.duplicate.setBounds(top.removeFromLeft(104)); p.quantize.setBounds(top.removeFromLeft(96));
    p.zoomOut.setBounds(top.removeFromLeft(32)); p.zoomIn.setBounds(top.removeFromLeft(32)); p.fit.setBounds(top.removeFromLeft(48));
    const bool drumMode = p.drums.getToggleState();
    const bool compact = getHeight() < 300;
    const bool stepOnly = compact && drumMode;
    p.grid.setVisible(!stepOnly); p.horizontal.setVisible(!stepOnly); p.vertical.setVisible(!stepOnly);
    const auto gridTop = compact ? 76 : 82;
    const auto gridHeight = p.veryCompact() ? juce::jmax(1, getHeight() - gridTop - 17)
        : juce::jmax(62, getHeight() - (compact ? 110 : drumMode ? 190 : 134));
    p.grid.setBounds(12, gridTop, getWidth() - 38, gridHeight);
    p.horizontal.setBounds(60, p.grid.getBottom() + 2, getWidth() - 86, 13);
    p.vertical.setBounds(p.grid.getRight() + 2, p.grid.getY() + p.rulerHeight(), 13, int(p.plot().getHeight()));
    p.velocity.setBounds(82, 46, 205, 27); p.drums.setBounds(getWidth() - 138, 46, 122, 27);
    p.copy.setBounds(292, 46, 56, 27); p.cut.setBounds(348, 46, 48, 27); p.paste.setBounds(396, 46, 60, 27);
    p.down.setBounds(456, 46, 64, 27); p.up.setBounds(520, 46, 64, 27);
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
    // The minimum main-window dock has only 156 px after its title bar. Tooltips
    // and the main status line retain help/errors; reserve its lower area for notes.
    if (p.veryCompact()) return;
    const auto hint = juce::String(int(p.notes.size())) + " notes / " + juce::String(int(p.selected.size())) + " selected   "
        + (p.draw.getToggleState() ? "B: draw on" : "B: draw / double-click") + "   Ctrl+C/X/V   paste @ " + juce::String(p.insertionPoint(), 3) + " beats" + (p.densePreview ? "   dense preview: zoom in" : "");
    g.drawFittedText(p.editError.isNotEmpty() ? p.editError : hint,
                    14, getHeight() - 26, getWidth() - 28, 20, juce::Justification::centredLeft, 1);
}
bool PianoRoll::keyPressed(const juce::KeyPress& key)
{
    auto& p = *impl;
    if (isTextInput(juce::Component::getCurrentlyFocusedComponent())) return false;
    const auto mods = key.getModifiers(); const auto code = key.getKeyCode();
    if (code == juce::KeyPress::escapeKey && p.drag.mode != Impl::Drag::none) { if (!p.drag.before.empty()) p.notes = p.drag.before; p.drag = {}; p.layout(); return true; }
    if (code == juce::KeyPress::spaceKey && !mods.isAnyModifierKeyDown()) { if (onTogglePlay) onTogglePlay(); return true; }
    if (mods.isCtrlDown() || mods.isCommandDown()) {
        if (code == 'a' || code == 'A') { for (const auto& n : p.notes) p.selected.insert(n.id); p.refreshButtons(); p.grid.repaint(); return true; }
        if (code == 'd' || code == 'D') { p.duplicateSelected(); return true; }
        if (code == 'c' || code == 'C') { p.copySelected(false); return true; }
        if (code == 'x' || code == 'X') { p.copySelected(true); return true; }
        if (code == 'v' || code == 'V') { p.pasteNotes(); return true; }
        if (code == '4') { p.snapEnabled.setToggleState(!p.snapEnabled.getToggleState(), juce::sendNotificationSync); return true; }
        return onProjectKey ? onProjectKey(key) : false;
    }
    if (!mods.isAnyModifierKeyDown() && (code == 'b' || code == 'B')) { p.draw.setToggleState(!p.draw.getToggleState(), juce::sendNotificationSync); return true; }
    if (code == juce::KeyPress::deleteKey || code == juce::KeyPress::backspaceKey) { p.deleteSelected(); return true; }
    if (code == juce::KeyPress::upKey || code == juce::KeyPress::downKey) { p.transpose((code == juce::KeyPress::upKey ? 1 : -1) * (mods.isShiftDown() ? 12 : 1)); return true; }
    return false;
}
juce::Result PianoRoll::runInteractionSmokeTest(juce::DynamicObject& report, const juce::File& artifactDirectory)
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
    const auto fail = [&](const char* message) { onWriteNotes = {}; onEditError = {}; onProjectKey = {}; return juce::Result::fail(message); };
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

    // Daily editor regression uses the same callbacks as production. One callback
    // represents one engine command; copy, grid changes and rejected paste do not
    // emit a command, while cut/paste each emit exactly one complete edit.
    setSize(820, 440); p.drums.setToggleState(false, juce::dontSendNotification); resized();
    p.draw.setToggleState(false, juce::dontSendNotification); p.snapEnabled.setToggleState(true, juce::dontSendNotification);
    p.snap.setSelectedId(4, juce::sendNotificationSync);
    juce::String dailyProject = "daily-test", dailyClip = "source";
    double dailyStart = 0, dailyBpm = 120;
    int dailyCommits = 0, rejected = 0, projectKeys = 0;
    accepted = { { "performed-a", 60, 1.1, 0.6, 80, 2 }, { "performed-b", 67, 1.7, 0.4, 110, 2 } };
    setClip(dailyProject, dailyClip, "Daily editor", ++acceptedRevision, dailyStart, 8, dailyBpm, accepted);
    onWriteNotes = [&](const juce::String& id, const std::vector<Note>& values, std::uint64_t expected) {
        if (id != dailyClip || expected != acceptedRevision) staleSubmission = true;
        accepted = values; ++dailyCommits;
        setClip(dailyProject, dailyClip, "Daily editor", ++acceptedRevision, dailyStart, 8, dailyBpm, accepted);
    };
    onEditError = [&](const juce::String&) { ++rejected; };
    onProjectKey = [&](const juce::KeyPress&) { ++projectKeys; return true; };
    const auto command = [&](char c) { return keyPressed(juce::KeyPress(c, juce::ModifierKeys::ctrlModifier, 0)); };
    const auto equalNotes = [](const auto& a, const auto& b) {
        return a.size() == b.size() && std::equal(a.begin(), a.end(), b.begin(), [](const Note& x, const Note& y) {
            return x.id == y.id && x.pitch == y.pitch && x.startBeats == y.startBeats && x.lengthBeats == y.lengthBeats
                && x.velocity == y.velocity && x.channel == y.channel;
        });
    };
    p.selected = { "performed-a", "performed-b" }; p.refreshButtons();
    auto firstRect = std::find_if(p.visible.begin(), p.visible.end(), [&](const auto& item) { return p.notes[item.first].id == "performed-a"; });
    if (firstRect == p.visible.end()) return fail("Daily piano fixture did not expose its active note.");
    const auto groupStart = firstRect->second.getCentre();
    const auto groupEnd = groupStart + juce::Point<float>(float(p.pixelsPerBeat * 0.13), 0);
    p.grid.mouseDown(event(groupStart, groupStart, false)); p.grid.mouseDrag(event(groupEnd, groupStart, true)); p.grid.mouseUp(event(groupEnd, groupStart, true));
    if (dailyCommits != 1 || std::abs(accepted[0].startBeats - 1.25) > 1.0e-6
        || std::abs(accepted[1].startBeats - 1.85) > 1.0e-6)
        return fail("Absolute note snapping changed the selected group's relative timing.");
    report.setProperty("midi_absolute_snap_preserves_group_offsets", true);
    const auto priorGrid = p.gridBeats;
    command('4');
    if (p.snapEnabled.getToggleState() || p.gridBeats != priorGrid || std::abs(p.snapped(1.13) - 1.13) > 1.0e-9 || dailyCommits != 1)
        return fail("Turning off note snapping changed grid precision or edited the clip.");
    command('4'); setTimeSignature(6, 8);
    p.snap.setSelectedId(8, juce::sendNotificationSync);
    if (p.barBeats != 3.0 || p.beatUnit != 0.5 || std::abs(p.snapped(0.18) - 1.0 / 6.0) > 1.0e-9)
        return fail("Piano grid did not retain quarter-beat units for 6/8 or triplets.");
    p.snap.setSelectedId(4, juce::sendNotificationSync);
    report.setProperty("midi_snap_independent_and_triplet_meter", true);
    command('C');
    if (dailyCommits != 1 || p.clipboard.size() != 2) return fail("Copy modified notes or missed part of the selection.");
    command('X');
    if (dailyCommits != 2 || !accepted.empty() || p.clipboard.size() != 2) return fail("Cut did not retain an immutable clipboard and submit one deletion.");
    p.markInsertion(2.0); command('V');
    if (dailyCommits != 3 || accepted.size() != 2 || p.selected.size() != 2
        || accepted[0].id == "performed-a" || accepted[1].id == "performed-b" || accepted[0].id == accepted[1].id
        || std::abs(accepted[0].startBeats - 2.0) > 1.0e-6 || std::abs(accepted[1].startBeats - 2.6) > 1.0e-6
        || accepted[0].pitch != 60 || accepted[1].pitch != 67 || accepted[0].velocity != 80 || accepted[1].velocity != 110
        || accepted[0].channel != 2 || accepted[1].channel != 2 || std::abs(p.insertionPoint() - 3.0) > 1.0e-6)
        return fail("Paste lost note identity, timing, expression, selection, or its next insertion point.");
    report.setProperty("midi_clipboard_cut_paste_single_edits", true);
    dailyClip = "destination"; dailyStart = 16; dailyBpm = 98; accepted.clear();
    setClip(dailyProject, dailyClip, "Daily editor", ++acceptedRevision, dailyStart, 8, dailyBpm, accepted);
    setPlayhead((dailyStart + 1.5) * 60.0 / dailyBpm, false); command('V');
    if (dailyCommits != 4 || accepted.size() != 2 || std::abs(accepted[0].startBeats - 1.5) > 1.0e-6
        || std::abs(accepted[1].startBeats - 2.1) > 1.0e-6 || p.clipboard.size() != 2)
        return fail("Switching clips lost copied notes or used the wrong project-to-clip playhead offset.");
    report.setProperty("midi_clipboard_across_clips_at_playhead", true);
    const auto beforeRejected = p.notes;
    p.markInsertion(7.75); command('V');
    if (dailyCommits != 4 || rejected != 1 || !equalNotes(beforeRejected, p.notes)) return fail("Out-of-bounds paste silently dropped or changed notes.");
    p.markInsertion(0.0); p.clipboard[0].lengthBeats = 0; command('V');
    if (dailyCommits != 4 || rejected != 2 || !equalNotes(beforeRejected, p.notes)) return fail("A zero-duration clipboard note was accepted.");
    p.clipboard[0].lengthBeats = 0.6; p.clipboard[0].channel = p.clipboard[1].channel = 3; command('V');
    if (dailyCommits != 4 || rejected != 3 || !equalNotes(beforeRejected, p.notes)) return fail("Paste silently remapped copied MIDI channels.");
    report.setProperty("midi_clipboard_invalid_paste_is_atomic", true);
    accepted = { { "duplicate-a", 60, 0, 0.5, 80, 2 }, { "duplicate-b", 67, 4, 0.5, 110, 2 } };
    setClip(dailyProject, dailyClip, "Duplicate boundary", ++acceptedRevision, dailyStart, 8, dailyBpm, accepted);
    p.selected = { "duplicate-a", "duplicate-b" }; command('D');
    if (dailyCommits != 4 || rejected != 4 || !equalNotes(accepted, p.notes)) return fail("Duplicate kept only the fitting part of a selected group.");
    report.setProperty("midi_duplicate_group_boundary_is_atomic", true);
    command('S'); if (projectKeys != 1) return fail("Piano clipboard shortcuts swallowed the project Save command.");
    report.setProperty("midi_project_shortcuts_forwarded", true);
    dailyProject = "other-project"; accepted.clear();
    setClip(dailyProject, dailyClip, "New project", ++acceptedRevision, 0, 8, dailyBpm, accepted); dailyStart = 0;
    command('V');
    if (!p.clipboard.empty() || dailyCommits != 4 || !p.notes.empty()) return fail("A note clipboard leaked across project identities.");
    keyPressed(juce::KeyPress('B'));
    const auto drawPoint = juce::Point<float>(p.x(0.5), p.y(p.topPitch - 2) + p.rowHeight * 0.5f);
    p.grid.mouseDown(event(drawPoint, drawPoint, false)); p.grid.mouseUp(event(drawPoint, drawPoint, false));
    p.grid.mouseDoubleClick(event(drawPoint, drawPoint, false));
    if (!p.draw.getToggleState() || dailyCommits != 5 || accepted.size() != 1 || accepted.front().startBeats != 0.5)
        return fail("Draw mode did not create one note, or double-click created a duplicate.");
    keyPressed(juce::KeyPress('B'));
    const auto selectPoint = drawPoint + juce::Point<float>(float(p.pixelsPerBeat), 0);
    p.grid.mouseDown(event(selectPoint, selectPoint, false)); p.grid.mouseUp(event(selectPoint, selectPoint, false));
    if (p.draw.getToggleState() || dailyCommits != 5 || staleSubmission) return fail("Selection mode created notes or broke revision checks.");
    report.setProperty("midi_draw_toggle_and_single_click", true);
    // Deep editing uses real component events and the production write callback.
    // The history fixture models callback acceptance/undo; engine persistence and
    // native Undo are separately exercised by the integration smoke suite.
    {
        PianoRoll fine; auto& q = *fine.impl; fine.setSize(1000, 580);
        const double quantum = time::minimumEditGridBeats;
        std::uint64_t fineRevision = 1; int fineCommits = 0; bool fineStale = false;
        std::vector<Note> fineAccepted; std::vector<std::vector<Note>> undoNotes, redoNotes;
        fine.setClip("precision", "fine-clip", "Fine MIDI", fineRevision, 0, 8, 120, fineAccepted);
        fine.onWriteNotes = [&](const juce::String& id, const std::vector<Note>& values, std::uint64_t expected) {
            fineStale = fineStale || id != "fine-clip" || expected != fineRevision;
            undoNotes.push_back(fineAccepted); redoNotes.clear(); fineAccepted = values; ++fineCommits;
            fine.setClip("precision", "fine-clip", "Fine MIDI", ++fineRevision, 0, 8, 120, fineAccepted);
        };
        fine.onProjectKey = [&](const juce::KeyPress& key) {
            auto& source = key.getKeyCode() == 'Z' ? undoNotes : redoNotes;
            auto& destination = key.getKeyCode() == 'Z' ? redoNotes : undoNotes;
            if (source.empty()) return false;
            destination.push_back(fineAccepted); fineAccepted = source.back(); source.pop_back();
            fine.setClip("precision", "fine-clip", "Fine MIDI", ++fineRevision, 0, 8, 120, fineAccepted); return true;
        };
        const auto fineEvent = [&](juce::Point<float> position, juce::Point<float> start, bool dragged) {
            const auto now = juce::Time::getCurrentTime();
            return juce::MouseEvent(juce::Desktop::getInstance().getMainMouseSource(), position,
                juce::ModifierKeys(juce::ModifierKeys::leftButtonModifier), 1, 0, 0, 0, 0,
                &q.grid, &q.grid, now, start, now, 1, dragged);
        };
        q.snap.setSelectedId(16, juce::sendNotificationSync);
        if (q.gridBeats != quantum || q.snap.getText() != "1/16384") return fail("The piano grid menu does not expose the whole-note 1/16384 grid.");
        q.setZoom(Impl::maximumPixelsPerBeat, q.plot().getX()); q.firstBeat = 1; q.layout();
        if (q.gridBeats * q.pixelsPerBeat < 16 || q.grid.getWidth() > fine.getWidth()) return fail("Deep piano zoom enlarged the canvas or cannot resolve the minimum edit grid.");
        const auto point = juce::Point<float>(q.x(1 + 2 * quantum), q.y(70) + q.rowHeight * 0.5f);
        q.insert(point);
        if (fineCommits != 1 || fineAccepted.size() != 1 || fineAccepted[0].startBeats != 1 + 2 * quantum || fineAccepted[0].lengthBeats != quantum)
            return fail("A 1/16384 piano note was rejected or silently enlarged.");
        q.quantize.onClick();
        if (fineCommits != 2 || fineAccepted[0].lengthBeats != quantum) return fail("Fine-grid quantize enlarged a one-cell note.");
        auto startFine = q.visible.front().second.getCentre(); auto endFine = startFine + juce::Point<float>(16, 0);
        const auto beforeDragIndexBuilds = q.indexBuilds;
        q.grid.mouseDown(fineEvent(startFine, startFine, false)); q.grid.mouseDrag(fineEvent(endFine, startFine, true));
        if (fineCommits != 2 || q.indexBuilds != beforeDragIndexBuilds) return fail("Fine drag rebuilt the committed note index or submitted before release.");
        q.grid.mouseUp(fineEvent(endFine, startFine, true));
        if (fineCommits != 3 || fineAccepted[0].startBeats != 1 + 3 * quantum || fineAccepted[0].lengthBeats != quantum)
            return fail("Fine piano dragging lost a grid quantum or changed the duration.");
        startFine = q.visible.front().second.getTopRight() + juce::Point<float>(-1, 5); endFine = startFine + juce::Point<float>(16, 0);
        q.grid.mouseDown(fineEvent(startFine, startFine, false)); q.grid.mouseDrag(fineEvent(endFine, startFine, true)); q.grid.mouseUp(fineEvent(endFine, startFine, true));
        if (fineCommits != 4 || fineAccepted[0].lengthBeats != 2 * quantum || fineStale) return fail("Fine piano resizing did not commit exactly one precise edit.");
        fine.keyPressed(juce::KeyPress('Z', juce::ModifierKeys::ctrlModifier, 0));
        if (fineAccepted[0].lengthBeats != quantum) return fail("Fine-note undo callback did not restore its exact one-cell duration.");
        fine.keyPressed(juce::KeyPress('Y', juce::ModifierKeys::ctrlModifier, 0));
        if (fineAccepted[0].lengthBeats != 2 * quantum) return fail("Fine-note redo callback lost its exact duration.");
        startFine = q.visible.front().second.getCentre(); endFine = startFine + juce::Point<float>(16, 0);
        q.grid.mouseDown(fineEvent(startFine, startFine, false)); q.grid.mouseDrag(fineEvent(endFine, startFine, true)); fine.keyPressed(juce::KeyPress(juce::KeyPress::escapeKey));
        if (!equalNotes(q.notes, fineAccepted) || fineCommits != 4) return fail("Escape failed to discard a fine-note preview.");
        fineAccepted = { { "edge", 60, 8 - quantum, quantum, 90, 1 } };
        fine.setClip("precision", "fine-clip", "Fine boundary", ++fineRevision, 0, 8, 120, fineAccepted);
        q.firstBeat = 8; q.layout();
        startFine = q.visible.front().second.getTopRight() + juce::Point<float>(-1, 5); endFine = startFine + juce::Point<float>(100, 0);
        q.grid.mouseDown(fineEvent(startFine, startFine, false)); q.grid.mouseDrag(fineEvent(endFine, startFine, true)); q.grid.mouseUp(fineEvent(endFine, startFine, true));
        if (fineAccepted[0].startBeats + fineAccepted[0].lengthBeats != 8 || fineAccepted[0].lengthBeats != quantum)
            return fail("Fine resizing crossed the clip end or inflated a boundary note.");
        fine.onWriteNotes = {}; fine.onProjectKey = {};
        report.setProperty("midi_16384_create_quantize_move_resize_exact", true);
        report.setProperty("midi_16384_callback_undo_redo_cancel_boundary", true);

        // Zoom preserves the beat under the pointer; panning never scales the
        // component to the full project duration.
        q.firstBeat = 2; q.pixelsPerBeat = 4096; q.layout();
        const float anchorX = q.plot().getX() + q.plot().getWidth() * 0.37f;
        const double anchorBeat = q.firstBeat + (anchorX - q.plot().getX()) / q.pixelsPerBeat;
        juce::MouseWheelDetails wheel {}; wheel.deltaY = 1;
        const auto now = juce::Time::getCurrentTime();
        const juce::MouseEvent zoomEvent(juce::Desktop::getInstance().getMainMouseSource(), { anchorX, q.plot().getCentreY() },
            juce::ModifierKeys(juce::ModifierKeys::ctrlModifier), 1, 0, 0, 0, 0, &q.grid, &q.grid, now, {}, now, 0, false);
        q.grid.mouseWheelMove(zoomEvent, wheel);
        const double afterAnchor = q.firstBeat + (anchorX - q.plot().getX()) / q.pixelsPerBeat;
        if (std::abs(anchorBeat - afterAnchor) > 1.0e-12) return fail("Piano wheel zoom moved the pointer's musical anchor.");
        juce::TextEditor textInput; juce::Component nestedTextChild; textInput.addChildComponent(nestedTextChild);
        if (!isTextInput(&nestedTextChild) || isTextInput(&q.grid)) return fail("Piano shortcut focus gate does not protect nested text editing.");
        const auto beforeToggle = q.snapEnabled.getToggleState(); const auto beforeGrid = q.gridBeats;
        fine.keyPressed(juce::KeyPress('4', juce::ModifierKeys::ctrlModifier, 0));
        if (q.snapEnabled.getToggleState() == beforeToggle || q.gridBeats != beforeGrid) return fail("Ctrl+4 changed piano grid precision instead of toggling Snap.");
        fine.keyPressed(juce::KeyPress('4', juce::ModifierKeys::ctrlModifier, 0));
        report.setProperty("midi_deep_zoom_pointer_anchor_and_ctrl4", true);
        report.setProperty("midi_shortcut_nested_text_focus_gate", true);

        fine.setClip("render", "grid", "Grid rendering", 1, 0, 8, 120, {}); fine.setTimeSignature(4, 4);
        q.firstBeat = 0; q.setZoom(Impl::maximumPixelsPerBeat, q.plot().getX());
        const auto renderGrid = [&] { juce::Image image(juce::Image::RGB, q.grid.getWidth(), q.grid.getHeight(), true); juce::Graphics graphics(image); q.paintGrid(graphics); return image; };
        q.snapEnabled.setToggleState(true, juce::dontSendNotification); const auto solid = renderGrid();
        q.snapEnabled.setToggleState(false, juce::dontSendNotification); const auto dashed = renderGrid();
        const int lineX = juce::roundToInt(q.x(10 * quantum)); int solidPixels = 0, dashedPixels = 0;
        for (int yy = q.rulerHeight() + 10; yy < q.grid.getHeight() - 60; ++yy) {
            if (solid.getPixelAt(lineX, yy) != solid.getPixelAt(lineX + 3, yy)) ++solidPixels;
            if (dashed.getPixelAt(lineX, yy) != dashed.getPixelAt(lineX + 3, yy)) ++dashedPixels;
        }
        if (solidPixels <= dashedPixels + 12 || dashedPixels <= 0) return fail("Snap-off piano time lines are not visibly dashed while Snap-on lines are solid.");
        if (q.lastPaintedTimeLines > int(q.plot().getWidth() / 6) * 3 + 12) return fail("Piano time grid drawing exceeds its viewport budget.");
        const auto writeImage = [&](const juce::Image& image, const juce::String& name) {
            if (artifactDirectory == juce::File()) return true;
            if (!artifactDirectory.createDirectory()) return false;
            juce::FileOutputStream stream(artifactDirectory.getChildFile(name));
            return stream.openedOk() && juce::PNGImageFormat().writeImageToStream(image, stream);
        };
        if (!writeImage(solid, "piano-fine-grid-solid.png") || !writeImage(dashed, "piano-fine-grid-dashed.png")) return fail("Could not write synthetic piano grid evidence.");
        q.snapEnabled.setToggleState(true, juce::dontSendNotification);
        for (const auto [scale, tier] : std::array<std::pair<double, int>, 3> { { { 12, 0 }, { 80, 1 }, { 400, 2 } } }) {
            q.setZoom(scale, q.plot().getX());
            if (time::musicalRulerStep(q.visibleBeats(), q.plot().getWidth(), 4, 4).labelTier != tier) return fail("Piano ruler did not select the bar/beat/sixteenth zoom tiers.");
        }
        fine.setClip("render", "far-grid", "Far ruler", 2, 0, 100000000.0, 120, {});
        q.firstBeat = 99999900; q.setZoom(80, q.plot().getX()); const auto farRuler = renderGrid();
        if (q.lastPaintedLabels.empty()) return fail("Far-time piano ruler lost all labels.");
        for (std::size_t i = 1; i < q.lastPaintedLabels.size(); ++i)
            if (q.lastPaintedLabels[i].first < q.lastPaintedLabels[i - 1].second + 4) return fail("Long piano bar numbers overlap at far positions.");
        if (!writeImage(farRuler, "piano-far-ruler.png")) return fail("Could not write far-time piano ruler evidence.");
        report.setProperty("midi_snap_grid_solid_dashed_pixels", true);
        report.setProperty("midi_ruler_three_tiers_far_labels_no_overlap", true);

        std::vector<Note> crowded; crowded.reserve(100000);
        for (int i = 0; i < 100000; ++i) crowded.push_back({ juce::String(i), 60, double(i) * 2, 0.25, 90, 1 });
        fine.setClip("performance", "sparse", "100000-note index", 1, 0, 200000, 120, crowded);
        q.setZoom(Impl::maximumPixelsPerBeat, q.plot().getX()); q.firstBeat = 100000; q.layout();
        if (q.visible.empty() || q.queriedIndexNodes > 128) return fail("Deep piano viewport scanned unrelated notes instead of pruning the interval index.");
        const auto sparseBuilds = q.indexBuilds; std::vector<double> panTimes, dragTimes; std::size_t maxQueries = 0;
        juce::Image frame(juce::Image::RGB, q.grid.getWidth(), q.grid.getHeight(), true);
        for (int i = 0; i < 60; ++i) {
            const double begin = juce::Time::getMillisecondCounterHiRes();
            q.firstBeat = 100000 + double(i % 12) * quantum; q.layout(); juce::Graphics graphics(frame); q.paintGrid(graphics);
            panTimes.push_back(juce::Time::getMillisecondCounterHiRes() - begin); maxQueries = juce::jmax(maxQueries, q.queriedIndexNodes);
        }
        q.firstBeat = 100000; q.layout(); startFine = q.visible.front().second.getCentre(); q.grid.mouseDown(fineEvent(startFine, startFine, false));
        for (int i = 0; i < 60; ++i) {
            const double begin = juce::Time::getMillisecondCounterHiRes(); endFine = startFine + juce::Point<float>(float(16 + i % 12 * 8), 0);
            q.grid.mouseDrag(fineEvent(endFine, startFine, true)); juce::Graphics graphics(frame); q.paintGrid(graphics);
            dragTimes.push_back(juce::Time::getMillisecondCounterHiRes() - begin); maxQueries = juce::jmax(maxQueries, q.queriedIndexNodes);
        }
        if (q.indexBuilds != sparseBuilds || maxQueries > 128 || q.notes.size() != 100000 || q.grid.getWidth() > fine.getWidth())
            return fail("100000-note piano pan/drag rebuilt the index, scanned unrelated notes, or enlarged its viewport.");
        const auto writeTiming = [&](const char* name, std::vector<double> times) {
            std::sort(times.begin(), times.end()); report.setProperty(juce::String(name) + "_p50_ms", times[times.size() / 2]);
            report.setProperty(juce::String(name) + "_p95_ms", times[std::size_t(double(times.size() - 1) * 0.95)]);
            report.setProperty(juce::String(name) + "_worst_ms", times.back());
        };
        writeTiming("midi_100k_pan_paint_cpu", panTimes); writeTiming("midi_100k_drag_paint_cpu", dragTimes);
        report.setProperty("midi_100k_max_queried_index_nodes", int(maxQueries));
        report.setProperty("midi_100k_index_reused_during_gestures", true);
        fine.keyPressed(juce::KeyPress(juce::KeyPress::escapeKey));
        if (!writeImage(frame, "piano-100k-deep-zoom.png")) return fail("Could not write deep-zoom piano evidence.");

        for (auto& note : crowded) { note.startBeats = 1; note.lengthBeats = 1; }
        fine.setClip("performance", "dense", "Dense preview", 2, 0, 8, 120, crowded);
        q.firstBeat = 0; q.pixelsPerBeat = 80; q.layout();
        const auto densePoint = juce::Point<float>(q.x(1.5), q.y(60) + q.rowHeight * 0.5f);
        if (!q.densePreview || q.visible.size() > Impl::maximumVisibleNotes || q.hitNote(densePoint) != 99999 || q.notes.size() != 100000)
            return fail("Dense piano preview lost data, exceeded its display budget, or used truncated hit-testing.");
        q.drag.mode = Impl::Drag::box; q.drag.changed = true; q.drag.selectionBox = q.plot(); q.end(fineEvent({}, {}, true));
        if (q.selected.size() != 100000) return fail("Dense preview marquee selection silently dropped undisplayed notes.");
        report.setProperty("midi_dense_preview_budget_full_hit_and_selection", true);
    }
    onEditError = {}; onProjectKey = {};
    onWriteNotes = {};
    setSize(726, 224);
    setClip("first-open", "bass-notes", "Bass", 1, 0, 4, 120, { { "low-note", 36, 0, 1, 90, 1 } });
    if (p.visible.empty()) return fail("First opening a low MIDI note in the dock left the note outside the visible pitch range.");
    report.setProperty("midi_first_open_fits_pitch_in_dock", true);
    p.drums.setToggleState(true, juce::dontSendNotification); resized();
    if (p.grid.isVisible() || !p.steps.front()->isVisible() || p.steps.front()->getBottom() > getHeight() - 26)
        return fail("Compact drum mode overlaps the piano editor or falls outside the dock.");
    report.setProperty("midi_compact_drum_mode_fits_dock", true);
    p.drums.setToggleState(false, juce::dontSendNotification); setSize(726, 156); resized();
    if (!p.veryCompact() || !p.grid.isVisible() || p.plot().getHeight() < 24 || p.plot().getWidth() <= 0
        || p.fit.getRight() > getWidth() - 12 || p.velocity.getBottom() > p.grid.getY()
        || p.paste.getRight() >= p.drums.getX() || p.grid.getBottom() >= p.horizontal.getY()
        || p.horizontal.getBottom() > getHeight() || p.vertical.getBottom() > p.grid.getBottom())
        return fail("The 156-pixel minimum piano dock has overlapping controls or unusable note/scroll regions.");
    report.setProperty("midi_minimum_dock_geometry", true);
    setSize(1000, 580);
    setClip("ui-test", "ui-test-clip", "MIDI interaction", acceptedRevision, 0, 8, 120, accepted);
    p.drums.setToggleState(true, juce::dontSendNotification);
    resized();
    onWriteNotes = {};
    return juce::Result::ok();
}
}
