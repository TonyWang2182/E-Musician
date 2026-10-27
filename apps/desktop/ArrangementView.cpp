#include "ArrangementView.h"
#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <map>

namespace emusician {
namespace {
const juce::Colour ink { 0xff171817 }, secondary { 0xff626560 }, rule { 0xffc6c9c3 }, paper { 0xfffefefd };
constexpr int rulerHeight = 34, scrollSize = 12, rowHeight = 104;
juce::Font mono(float height, int style = juce::Font::plain)
{
    return juce::Font(juce::FontOptions(juce::Font::getDefaultMonospacedFontName(), height, style));
}
juce::String timeText(double seconds)
{
    const auto tenths = static_cast<juce::int64>(std::llround(juce::jmax(0.0, seconds) * 10.0));
    return juce::String(tenths / 600).paddedLeft('0', 2) + ":"
        + juce::String((tenths / 10) % 60).paddedLeft('0', 2) + "." + juce::String(tenths % 10);
}
enum class PeakStatus { loading, ready, failed };
struct Peaks {
    Peaks(juce::AudioFormatManager& formats, juce::AudioThumbnailCache& cache, juce::File path,
          juce::String identity, juce::int64 key)
        : thumbnail(512, formats, cache), source(std::move(path)), fingerprint(std::move(identity)), hash(key) {}
    juce::AudioThumbnail thumbnail;
    const juce::File source;
    const juce::String fingerprint;
    const juce::int64 hash;
    std::atomic<PeakStatus> status { PeakStatus::loading };
    std::atomic<bool> cancelled { false };
};

// No reader is ever attached to the display thumbnail: even close zoom cannot
// cause AudioThumbnail::drawChannels to read audio on the message thread.
class PeakJob final : public juce::ThreadPoolJob {
public:
    PeakJob(std::shared_ptr<Peaks> destination, juce::AudioThumbnailCache& thumbnailCache)
        : ThreadPoolJob("Waveform peaks"), peaks(std::move(destination)), cache(thumbnailCache) {}
    JobStatus runJob() override
    {
        const auto cancelled = [this] { return shouldExit() || peaks->cancelled.load(); };
        if (cancelled()) return jobHasFinished;
        if (cache.loadThumb(peaks->thumbnail, peaks->hash)) {
            peaks->status.store(PeakStatus::ready, std::memory_order_release);
            return jobHasFinished;
        }
        juce::WavAudioFormat format;
        auto stream = peaks->source.createInputStream();
        std::unique_ptr<juce::AudioFormatReader> reader(stream != nullptr ? format.createReaderFor(stream.release(), true) : nullptr);
        if (reader == nullptr || reader->lengthInSamples <= 0 || reader->sampleRate <= 0 || reader->numChannels == 0) {
            peaks->status.store(PeakStatus::failed, std::memory_order_release);
            return jobHasFinished;
        }
        const int channels = static_cast<int>(reader->numChannels);
        peaks->thumbnail.reset(channels, reader->sampleRate, reader->lengthInSamples);
        constexpr int blockSize = 32768;
        juce::AudioBuffer<float> buffer(channels, blockSize);
        for (juce::int64 offset = 0; offset < reader->lengthInSamples; offset += blockSize) {
            if (cancelled()) return jobHasFinished;
            const int count = static_cast<int>(juce::jmin<juce::int64>(blockSize, reader->lengthInSamples - offset));
            if (!reader->read(&buffer, 0, count, offset, true, true)) {
                peaks->status.store(PeakStatus::failed, std::memory_order_release);
                return jobHasFinished;
            }
            peaks->thumbnail.addBlock(offset, buffer, 0, count);
        }
        if (!cancelled()) {
            cache.storeThumb(peaks->thumbnail, peaks->hash);
            peaks->status.store(PeakStatus::ready, std::memory_order_release);
        }
        return jobHasFinished;
    }
private:
    std::shared_ptr<Peaks> peaks;
    juce::AudioThumbnailCache& cache;
};
}

struct ArrangementView::Impl : private juce::ScrollBar::Listener {
    struct TrackControls final : juce::Component {
        TrackControls(Impl& view, juce::String trackId) : p(view), id(std::move(trackId))
        {
            setInterceptsMouseClicks(false, true);
            for (auto* button : { &mute, &solo, &arm, &devices }) addAndMakeVisible(button);
            mute.setTooltip("Mute this track"); solo.setTooltip("Solo this track"); devices.setTooltip("Show this track's devices");
            arm.setTooltip("Arm this track for recording. Choose an input in Devices / I/O first.");
            arm.onClick = [this] {
                const auto current = p.engine.snapshot();
                for (const auto& track : current.tracks) if (track.id == id) {
                    auto* args = new juce::DynamicObject; args->setProperty("track_id", id); args->setProperty("armed", !track.armed);
                    const auto result = p.engine.execute("set_track_armed", juce::var(args), current.revision);
                    if (p.owner.onEditResult) p.owner.onEditResult(result); p.notifyState(); break;
                }
            };
            mute.onClick = [this] { toggle(false); }; solo.onClick = [this] { toggle(true); };
            devices.onClick = [this] { p.engine.selectTrack(id); p.notifyState(); if (p.owner.onOpenTrackDevices) p.owner.onOpenTrackDevices(id); };
        }
        void toggle(bool isSolo)
        {
            const auto current = p.engine.snapshot();
            for (const auto& track : current.tracks) if (track.id == id) {
                const auto result = isSolo ? p.engine.setTrackSolo(id, !track.solo, current.revision) : p.engine.setTrackMuted(id, !track.muted, current.revision);
                if (p.owner.onEditResult) p.owner.onEditResult(result); p.notifyState(); break;
            }
        }
        void resized() override { const int y = getHeight() - 34; mute.setBounds(8, y, 28, 27); solo.setBounds(40, y, 28, 27); arm.setBounds(72, y, 28, 27); devices.setBounds(106, y, getWidth() - 114, 27); }
        Impl& p; juce::String id;
        juce::TextButton mute { "M" }, solo { "S" }, arm { "R" }, devices { "devices" };
    };
    struct Canvas final : juce::Component, juce::TooltipClient {
        explicit Canvas(Impl& view) : p(view) { setWantsKeyboardFocus(true); setTitle("Audio arrangement tracks"); }
        void paint(juce::Graphics& g) override { p.paintTracks(g); }
        void mouseDown(const juce::MouseEvent& e) override
        {
            if (!isEnabled()) return;
            if (isShowing()) grabKeyboardFocus();
            p.cancelDrag();
            seeking = false;
            const int index = static_cast<int>(e.position.y) / p.rowHeight;
            if (index < 0 || index >= static_cast<int>(p.state.tracks.size())) {
                seeking = e.position.x >= p.labelWidth();
                if (seeking) p.seekAt(e.position.x);
                return;
            }
            p.engine.endEditGesture();
            if (const auto* clip = p.hitClip(static_cast<std::size_t>(index), e.position)) {
                const auto picked = *clip;
                if (e.mods.isCtrlDown() || e.mods.isCommandDown() || e.mods.isShiftDown()) {
                    if (p.selection.contains(picked.id)) p.selection.removeString(picked.id);
                    else p.selection.add(picked.id);
                } else if (!p.selection.contains(picked.id)) p.selection = { picked.id };
                p.selecting = true;
                p.engine.selectClip(picked.id);
                p.notifyState();
                p.selecting = false;
                if (!p.selection.contains(picked.id)) return;
                p.drag.id = picked.id;
                p.drag.projectId = p.state.projectId;
                p.drag.revision = p.state.revision;
                p.drag.originalStart = p.drag.previewStart = picked.timelineStart;
                p.drag.duration = picked.duration;
                p.drag.originalDuration = picked.duration;
                p.drag.sourceOffset = picked.sourceOffset;
                p.drag.sourceDuration = picked.sourceDuration;
                p.drag.midi = picked.kind == "midi";
                p.drag.trackIndex = p.drag.targetTrackIndex = index;
                p.drag.clipIds = p.selection;
                p.drag.groupStart = picked.timelineStart; p.drag.groupEnd = picked.timelineStart + picked.duration;
                for (const auto& track : p.state.tracks) for (const auto& selectedClip : track.clips) if (p.selection.contains(selectedClip.id)) {
                    p.drag.groupStart = juce::jmin(p.drag.groupStart, selectedClip.timelineStart);
                    p.drag.groupEnd = juce::jmax(p.drag.groupEnd, selectedClip.timelineStart + selectedClip.duration);
                }
                const auto hit = p.clipArea(static_cast<std::size_t>(index), picked);
                if (hit.getWidth() > 16.0f) {
                    if (picked.timelineStart >= p.viewStart && e.position.x <= hit.getX() + 6) p.drag.edge = -1;
                    else if (picked.timelineStart + picked.duration <= p.viewStart + p.visibleDuration() && e.position.x >= hit.getRight() - 6) p.drag.edge = 1;
                }
                p.drag.downX = e.position.x;
                p.drag.downY = e.position.y;
                p.drag.secondsPerPixel = p.visibleDuration() / p.plotWidth();
                return;
            }
            if (e.position.x < p.labelWidth()) p.engine.selectTrack(p.state.tracks[static_cast<std::size_t>(index)].id);
            seeking = e.position.x >= p.labelWidth();
            if (seeking) p.seekAt(e.position.x); else p.notifyState();
        }
        void mouseDrag(const juce::MouseEvent& e) override
        {
            if (!isEnabled()) return;
            if (p.drag.id.isNotEmpty()) {
                if (std::abs(e.position.x - p.drag.downX) >= 4.0f || std::abs(e.position.y - p.drag.downY) >= 8.0f) p.drag.moved = true;
                if (p.drag.moved) {
                    const auto delta = (e.position.x - p.drag.downX) * p.drag.secondsPerPixel;
                    const auto snap = [&](double value) { return !e.mods.isAltDown() && p.gridBeats > 0 && p.state.bpm > 0
                        ? std::round(value * p.state.bpm / (60 * p.gridBeats)) * 60 * p.gridBeats / p.state.bpm : value; };
                    if (p.drag.edge < 0) {
                        p.drag.previewStart = juce::jlimit(p.drag.midi ? 0.0 : juce::jmax(0.0, p.drag.originalStart - p.drag.sourceOffset),
                            p.drag.originalStart + p.drag.originalDuration - 0.001, snap(p.drag.originalStart + delta));
                        p.drag.duration = p.drag.originalStart + p.drag.originalDuration - p.drag.previewStart;
                    } else if (p.drag.edge > 0) {
                        const auto end = juce::jlimit(p.drag.originalStart + 0.001,
                            p.drag.midi ? 172800.0 : juce::jmin(172800.0, p.drag.originalStart + p.drag.sourceDuration - p.drag.sourceOffset),
                            snap(p.drag.originalStart + p.drag.originalDuration + delta));
                        p.drag.duration = end - p.drag.originalStart;
                    } else {
                        p.drag.previewStart = juce::jlimit(p.drag.originalStart - p.drag.groupStart,
                            172800.0 - p.drag.groupEnd + p.drag.originalStart, snap(p.drag.originalStart + delta));
                        if (p.drag.clipIds.size() == 1)
                            p.drag.targetTrackIndex = juce::jlimit(0, int(p.state.tracks.size()) - 1, int(e.position.y) / p.rowHeight);
                    }
                    repaint();
                }
            } else if (seeking) p.seekAt(e.position.x);
        }
        void mouseUp(const juce::MouseEvent&) override { seeking = false; p.commitDrag(); }
        void mouseDoubleClick(const juce::MouseEvent& e) override
        {
            const int row = int(e.position.y) / p.rowHeight;
            if (row >= 0 && row < int(p.state.tracks.size()))
                if (const auto* clip = p.hitClip(std::size_t(row), e.position); clip && clip->kind == "midi" && p.owner.onOpenMidiClip)
                    p.owner.onOpenMidiClip(clip->id);
        }
        void mouseWheelMove(const juce::MouseEvent& e, const juce::MouseWheelDetails& wheel) override
        {
            if (e.mods.isCtrlDown() || e.mods.isCommandDown() || e.mods.isShiftDown()) p.wheel(e.position.x, e.mods, wheel);
            else juce::Component::mouseWheelMove(e, wheel);
        }
        bool keyPressed(const juce::KeyPress& key) override { return p.owner.keyPressed(key); }
        juce::String getTooltip() override
        {
            const auto point = getMouseXYRelative().toFloat();
            const int row = static_cast<int>(point.y) / p.rowHeight;
            if (row >= 0 && row < static_cast<int>(p.state.tracks.size()))
                if (const auto* clip = p.hitClip(static_cast<std::size_t>(row), point)) return clip->kind == "midi"
                    ? "Double-click to edit MIDI notes. Ctrl-click selects multiple clips." : clip->source.getFullPathName() + "\nDrag centre to move; edges to trim. Alt bypasses snap.";
            return {};
        }
        void focusGained(FocusChangeType) override { repaint(); p.owner.repaint(); }
        void focusLost(FocusChangeType) override { repaint(); p.owner.repaint(); }
        Impl& p;
        bool seeking = false;
    };

    Impl(ArrangementView& component, EngineSession& session)
        : owner(component), engine(session), canvas(*this), horizontal(false)
    {
        owner.addAndMakeVisible(viewport);
        owner.addAndMakeVisible(horizontal);
        viewport.setViewedComponent(&canvas, false);
        viewport.setScrollBarsShown(true, false);
        viewport.setScrollBarThickness(scrollSize);
        viewport.setScrollOnDragEnabled(false);
        horizontal.setAutoHide(false);
        horizontal.addListener(this);
        horizontal.setSingleStepSize(1.0);
        horizontal.setTitle("Timeline horizontal scroll");
    }
    ~Impl()
    {
        for (auto& item : entries) item.second->cancelled.store(true);
        // Jobs own their destination and never post callbacks. Join before the
        // shared cache/format manager is destroyed.
        pool.removeAllJobs(true, -1);
        horizontal.removeListener(this);
        viewport.setViewedComponent(nullptr, false);
    }
    double projectDuration() const { return juce::jmax(0.01, state.duration); }
    double visibleDuration() const { return projectDuration() / zoom; }
    int labelWidth() const { return canvas.getWidth() >= 560 ? 192 : 160; }
    int plotWidth() const { return juce::jmax(1, canvas.getWidth() - labelWidth() - 7); }
    float timeX(double seconds) const
    {
        return static_cast<float>(labelWidth() + (seconds - viewStart) * plotWidth() / visibleDuration());
    }
    double displayedStart(const EngineSession::ClipSnapshot& clip) const
    {
        if (!drag.moved) return clip.timelineStart;
        if (drag.id == clip.id) return drag.previewStart;
        return drag.edge == 0 && drag.clipIds.contains(clip.id) ? clip.timelineStart + drag.previewStart - drag.originalStart : clip.timelineStart;
    }
    juce::Rectangle<float> clipArea(std::size_t row, const EngineSession::ClipSnapshot& clip) const
    {
        const auto clipStart = displayedStart(clip);
        const auto duration = drag.id == clip.id && drag.moved ? drag.duration : clip.duration;
        const auto end = juce::jmin(clipStart + duration, viewStart + visibleDuration());
        const auto start = juce::jmax(clipStart, viewStart);
        return { timeX(start), static_cast<float>(static_cast<int>(row) * rowHeight + (rowHeight < 104 ? 9 : 17)),
                 juce::jmax(0.0f, timeX(end) - timeX(start)), float(rowHeight < 104 ? rowHeight - 18 : 66) };
    }
    const EngineSession::ClipSnapshot* hitClip(std::size_t row, juce::Point<float> point) const
    {
        const auto& clips = state.tracks[row].clips;
        for (const auto& clip : clips)
            if (clip.id == state.selectedClipId && clipArea(row, clip).contains(point)) return &clip;
        for (auto it = clips.rbegin(); it != clips.rend(); ++it)
            if (clipArea(row, *it).contains(point)) return &*it;
        return nullptr;
    }
    bool cancelDrag()
    {
        if (drag.id.isEmpty()) return false;
        drag = {};
        canvas.repaint();
        return true;
    }
    void commitDrag()
    {
        if (drag.id.isEmpty()) return;
        const auto pending = drag;
        drag = {};
        if (!pending.moved || (std::abs(pending.previewStart - pending.originalStart) < 0.0000001
            && std::abs(pending.duration - pending.originalDuration) < 0.0000001 && pending.trackIndex == pending.targetTrackIndex)) { canvas.repaint(); return; }
        auto args = new juce::DynamicObject;
        if (pending.edge != 0) {
            args->setProperty("clip_id", pending.id); args->setProperty("start_seconds", pending.previewStart);
            args->setProperty("end_seconds", pending.previewStart + pending.duration);
            lastMoveResult = engine.execute("trim_clip", juce::var(args), pending.revision);
        } else if (pending.clipIds.size() == 1 && pending.trackIndex == pending.targetTrackIndex) {
            delete args; lastMoveResult = engine.moveClip(pending.id, pending.previewStart, pending.revision);
        } else {
            juce::Array<juce::var> ids; for (const auto& id : pending.clipIds) ids.add(id);
            args->setProperty("clip_ids", ids); args->setProperty("delta_seconds", pending.previewStart - pending.originalStart);
            if (pending.trackIndex != pending.targetTrackIndex) args->setProperty("target_track_id", state.tracks[std::size_t(pending.targetTrackIndex)].id);
            lastMoveResult = engine.execute("move_clips", juce::var(args), pending.revision);
        }
        if (owner.onEditResult) owner.onEditResult(lastMoveResult);
        notifyState();
    }
    void notifyState()
    {
        if (owner.onUserStateChange) owner.onUserStateChange();
        else owner.update(engine.snapshot());
    }
    void seekAt(float x)
    {
        if (state.duration <= 0.0) return;
        const double seconds = viewStart + (x - labelWidth()) * visibleDuration() / plotWidth();
        engine.seek(juce::jlimit(0.0, state.duration, seconds));
        notifyState();
    }
    void layout()
    {
        viewport.setBounds(0, rulerHeight, owner.getWidth(), juce::jmax(0, owner.getHeight() - rulerHeight - scrollSize - 4));
        canvas.setSize(juce::jmax(1, owner.getWidth() - scrollSize),
                       juce::jmax(viewport.getHeight(), static_cast<int>(state.tracks.size()) * rowHeight));
        for (std::size_t i = 0; i < headers.size(); ++i) headers[i]->setBounds(0, int(i) * rowHeight, labelWidth(), rowHeight);
        horizontal.setBounds(labelWidth(), owner.getHeight() - scrollSize, plotWidth(), scrollSize);
        syncScroll();
    }
    void syncScroll()
    {
        viewStart = juce::jlimit(0.0, juce::jmax(0.0, projectDuration() - visibleDuration()), viewStart);
        horizontal.setRangeLimits(0.0, projectDuration(), juce::dontSendNotification);
        horizontal.setCurrentRange(viewStart, visibleDuration(), juce::dontSendNotification);
        horizontal.setEnabled(zoom > 1.0 && state.duration > 0.0);
        canvas.repaint(); owner.repaint();
    }
    void setZoom(double value, double anchorFraction)
    {
        const auto fraction = juce::jlimit(0.0, 1.0, anchorFraction);
        const auto anchor = viewStart + visibleDuration() * fraction;
        zoom = juce::jlimit(1.0, 32.0, value);
        viewStart = anchor - visibleDuration() * fraction;
        syncScroll();
    }
    void wheel(float x, juce::ModifierKeys modifiers, const juce::MouseWheelDetails& wheel)
    {
        if (modifiers.isCtrlDown() || modifiers.isCommandDown())
            setZoom(zoom * (wheel.deltaY > 0 ? 2.0 : 0.5), (x - labelWidth()) / plotWidth());
        else if (modifiers.isShiftDown()) {
            viewStart -= static_cast<double>(wheel.deltaY + wheel.deltaX) * visibleDuration();
            syncScroll();
        }
    }
    void scrollBarMoved(juce::ScrollBar*, double start) override { viewStart = start; syncScroll(); }
    double tickStep() const
    {
        if (bars && state.bpm > 0) {
            const auto beat = 60.0 / state.bpm;
            const auto bar = beat * state.numerator * 4.0 / state.denominator;
            const auto target = visibleDuration() / juce::jmax(1.0, plotWidth() / 70.0);
            return target <= beat ? beat : bar * juce::jmax(1.0, std::ceil(target / bar));
        }
        const auto target = visibleDuration() / juce::jmax(1.0, plotWidth() / 90.0);
        const auto power = std::pow(10.0, std::floor(std::log10(target)));
        const auto normal = target / power;
        // Millisecond precision is the display floor. Very short ranges may
        // have fewer ticks; they must never show repeated rounded labels.
        return juce::jmax(0.001, (normal <= 1.0 ? 1.0 : normal <= 2.0 ? 2.0 : normal <= 5.0 ? 5.0 : 10.0) * power);
    }
    juce::String tickText(double seconds) const
    {
        if (bars && state.bpm > 0) {
            const double beat = seconds * state.bpm / 60.0 * state.denominator / 4.0;
            return juce::String(int(std::floor(beat / state.numerator)) + 1) + ":" + juce::String(int(std::floor(std::fmod(beat, double(state.numerator)) + 1.0e-6)) + 1);
        }
        const int digits = juce::jlimit(1, 3, static_cast<int>(std::ceil(-std::log10(tickStep()) - 0.000001)));
        const auto scale = static_cast<juce::int64>(std::pow(10, digits));
        const auto units = static_cast<juce::int64>(std::llround(juce::jmax(0.0, seconds) * static_cast<double>(scale)));
        return juce::String(units / (scale * 60)).paddedLeft('0', 2) + ":"
            + juce::String((units / scale) % 60).paddedLeft('0', 2) + "."
            + juce::String(units % scale).paddedLeft('0', digits);
    }
    template<class Callback> void eachTick(Callback callback) const
    {
        const auto step = tickStep();
        const auto first = std::ceil((viewStart - step * 0.000001) / step) * step;
        for (double t = first; t <= viewStart + visibleDuration() + step * 0.000001; t += step)
            callback(t, timeX(t));
    }
    void paintAttention(juce::Graphics& g)
    {
        if (!dropActive && !owner.hasKeyboardFocus(true)) return;
        const auto area = viewport.getViewArea().toFloat().reduced(3.0f);
        const auto x = area.getX(), y = area.getY(), r = area.getRight(), b = area.getBottom();
        constexpr float arm = 12.0f;
        juce::Path corners;
        corners.startNewSubPath(x, y + arm); corners.lineTo(x, y); corners.lineTo(x + arm, y);
        corners.startNewSubPath(r - arm, y); corners.lineTo(r, y); corners.lineTo(r, y + arm);
        corners.startNewSubPath(x, b - arm); corners.lineTo(x, b); corners.lineTo(x + arm, b);
        corners.startNewSubPath(r - arm, b); corners.lineTo(r, b); corners.lineTo(r, b - arm);
        g.setColour(ink);
        g.strokePath(corners, juce::PathStrokeType(dropActive ? 1.8f : 1.2f));
    }
    struct MidiOverview {
        std::shared_ptr<const std::vector<EngineSession::NoteSnapshot>> source;
        double length = 0;
        std::vector<juce::Rectangle<float>> lines;
    };
    void updateMidiOverviews()
    {
        // Pitch/time occupancy is bounded at 512 columns per clip. Building uses
        // range differences, so even long, dense notes are O(notes + 128 * 512).
        // The transport paint path never traverses the original note collection.
        std::map<juce::String, MidiOverview> next;
        constexpr int columns = 512, stride = columns + 1;
        for (const auto& track : state.tracks) for (const auto& clip : track.clips) {
            if (clip.kind != "midi") continue;
            auto previous = midiOverviews.find(clip.id);
            if (previous != midiOverviews.end() && previous->second.source == clip.notes && previous->second.length == clip.lengthBeats) {
                next.emplace(clip.id, std::move(previous->second)); continue;
            }
            MidiOverview result; result.source = clip.notes; result.length = clip.lengthBeats;
            if (clip.notes && clip.lengthBeats > 0 && !clip.notes->empty()) {
                std::vector<int> difference(128 * stride, 0);
                int low = 127, high = 0;
                for (const auto& note : *clip.notes) {
                    const int pitch = juce::jlimit(0, 127, note.pitch);
                    const int first = juce::jlimit(0, columns - 1, int(std::floor(note.startBeats / clip.lengthBeats * columns)));
                    const int end = juce::jlimit(first + 1, columns, int(std::ceil((note.startBeats + note.lengthBeats) / clip.lengthBeats * columns)));
                    ++difference[std::size_t(pitch * stride + first)]; --difference[std::size_t(pitch * stride + end)];
                    low = juce::jmin(low, pitch); high = juce::jmax(high, pitch);
                }
                const float pitchRange = float(juce::jmax(12, high - low + 1));
                std::array<int, columns> minPitch, maxPitch; minPitch.fill(128); maxPitch.fill(-1);
                for (int pitch = 0; pitch < 128; ++pitch) {
                    int active = 0;
                    for (int x = 0; x < columns; ++x) {
                        active += difference[std::size_t(pitch * stride + x)];
                        if (active > 0) { minPitch[std::size_t(x)] = juce::jmin(minPitch[std::size_t(x)], pitch); maxPitch[std::size_t(x)] = pitch; }
                    }
                }
                for (int first = 0; first < columns;) {
                    int end = first + 1;
                    while (end < columns && minPitch[std::size_t(end)] == minPitch[std::size_t(first)] && maxPitch[std::size_t(end)] == maxPitch[std::size_t(first)]) ++end;
                    const auto addLine = [&](int pitch) { result.lines.emplace_back(float(first) / columns, float(pitch - low + 1) / pitchRange, float(end - first) / columns, 0.0f); };
                    if (maxPitch[std::size_t(first)] >= 0) {
                        addLine(minPitch[std::size_t(first)]);
                        if (maxPitch[std::size_t(first)] != minPitch[std::size_t(first)]) addLine(maxPitch[std::size_t(first)]);
                    }
                    first = end;
                }
            }
            next.emplace(clip.id, std::move(result));
        }
        midiOverviews = std::move(next);
    }
    void paintTracks(juce::Graphics& g)
    {
        g.fillAll(paper);
        if (state.tracks.empty()) {
            g.setColour(ink); g.setFont(mono(20.0f));
            g.drawFittedText("Start with a sound.", canvas.getLocalBounds().reduced(12).withTrimmedBottom(canvas.getHeight() / 2), juce::Justification::centredBottom, 2);
            g.setColour(secondary); g.setFont(mono(13.0f));
            g.drawFittedText("Drop WAV or MP3 files here.\nEach track appears on this timeline.", 12, canvas.getHeight() / 2 + 14, canvas.getWidth() - 24, 50, juce::Justification::centredTop, 2);
            paintAttention(g);
            return;
        }
        const auto dirty = g.getClipBounds();
        const int first = juce::jmax(0, dirty.getY() / rowHeight);
        const int last = juce::jmin(static_cast<int>(state.tracks.size()), dirty.getBottom() / rowHeight + 1);
        const bool hasSolo = std::any_of(state.tracks.begin(), state.tracks.end(), [](const auto& t) { return t.solo; });
        for (int row = first; row < last; ++row) {
            const auto& track = state.tracks[static_cast<std::size_t>(row)];
            const int y = row * rowHeight;
            const bool selected = track.id == state.selectedTrackId;
            const bool silent = track.muted || (hasSolo && !track.solo);
            if (selected) { g.setColour(ink.withAlpha(0.045f)); g.fillRect(0, y, canvas.getWidth(), rowHeight); }
            g.setColour(selected ? ink : rule);
            g.drawHorizontalLine(y + rowHeight - 1, 0.0f, static_cast<float>(canvas.getWidth()));
            if (selected) g.fillRect(0, y + 12, 2, rowHeight - 25);
            g.setColour(ink); g.setFont(mono(13.0f, selected ? juce::Font::bold : juce::Font::plain));
            g.drawFittedText(track.name, 10, y + (rowHeight < 104 ? 2 : 10), labelWidth() - 20, rowHeight < 104 ? 26 : 34, juce::Justification::centredLeft, rowHeight < 104 ? 1 : 2);
            g.setColour(secondary); g.setFont(mono(11.0f));
            if (rowHeight >= 104) g.drawText(track.kind + " / " + juce::String(track.gainDb, 1) + " dB", 10, y + 47, labelWidth() - 18, 19, juce::Justification::centredLeft);
            auto flags = track.format + "  " + juce::String(track.gainDb, 1) + " dB";
            if (track.muted) flags = "MUTED";
            else if (track.solo) flags = "SOLO";
            else if (hasSolo) flags = "solo excluded";
            g.setColour(rule.withAlpha(0.55f));
            eachTick([&](double, float x) { g.drawVerticalLine(juce::roundToInt(x), static_cast<float>(y), static_cast<float>(y + rowHeight - 1)); });
            const auto paintClip = [&](const EngineSession::ClipSnapshot& clip) {
                const auto area = clipArea(static_cast<std::size_t>(row), clip);
                if (area.getWidth() <= 0.0f) return;
                const bool selectedClip = selection.contains(clip.id);
                const auto start = displayedStart(clip);
                const bool moving = drag.id == clip.id && drag.moved;
                g.setColour(paper.withAlpha(selectedClip ? 0.95f : 0.8f));
                g.fillRect(area);
                g.setColour(ink.withAlpha(silent ? 0.3f : 0.8f));
                const auto waveArea = area.toNearestInt().reduced(2).withTrimmedTop(16);
                if (clip.kind == "midi") {
                    if (const auto overview = midiOverviews.find(clip.id); overview != midiOverviews.end()) {
                        juce::Graphics::ScopedSaveState noteClip(g); g.reduceClipRegion(waveArea);
                        const auto fullWidth = float(clip.duration / visibleDuration() * plotWidth());
                        for (const auto& line : overview->second.lines) {
                            const auto noteX = timeX(drag.id == clip.id && drag.edge < 0 ? drag.originalStart : start) + line.getX() * fullWidth;
                            const auto width = juce::jmax(1.0f, line.getWidth() * fullWidth);
                            if (noteX + width < waveArea.getX() || noteX > waveArea.getRight()) continue;
                            const auto noteY = waveArea.getBottom() - 3.0f - line.getY() * (waveArea.getHeight() - 5);
                            g.fillRect(noteX, noteY, width, 2.0f);
                        }
                    }
                } else if (owner.trackWaveformReady(clip.id)) {
                    const double previewOffset = clip.sourceOffset + (drag.id == clip.id && drag.edge < 0 ? drag.previewStart - drag.originalStart : 0.0);
                    const double previewDuration = drag.id == clip.id && drag.moved ? drag.duration : clip.duration;
                    owner.drawTrackWaveform(g, waveArea, clip.id,
                        previewOffset + juce::jmax(0.0, viewStart - start),
                        previewOffset + juce::jmin(previewDuration, viewStart + visibleDuration() - start), 0.9f);
                } else {
                    g.setFont(mono(12.0f));
                    g.drawFittedText(owner.waveformStatus(clip.id), waveArea, juce::Justification::centred, 2);
                }
                if (area.getWidth() >= 70.0f) {
                    g.setColour(ink); g.setFont(mono(10.5f));
                    const auto clipName = track.name + (track.clips.size() > 1
                        ? " / clip " + juce::String(static_cast<int>(&clip - track.clips.data()) + 1) : juce::String());
                    const auto caption = (moving ? "move: " : "") + clipName
                        + " @ " + juce::String(start, 3) + " s";
                    g.drawFittedText(caption, area.toNearestInt().reduced(5, 1).withHeight(16), juce::Justification::centredLeft, 1);
                }
                g.setColour(selectedClip ? ink : (silent ? rule : secondary));
                g.drawRect(area, selectedClip ? 1.8f : 0.7f);
                if (selectedClip && area.getWidth() > 20) {
                    g.drawVerticalLine(juce::roundToInt(area.getX() + 4), area.getY() + 24, area.getBottom() - 8);
                    g.drawVerticalLine(juce::roundToInt(area.getRight() - 4), area.getY() + 24, area.getBottom() - 8);
                    if (clip.fadeIn > 0) g.drawLine(area.getX(), area.getBottom(), timeX(start + clip.fadeIn), area.getY() + 17, 1.0f);
                    if (clip.fadeOut > 0) g.drawLine(timeX(start + clip.duration - clip.fadeOut), area.getY() + 17, area.getRight(), area.getBottom(), 1.0f);
                }
            };
            for (const auto& clip : track.clips) if (clip.id != state.selectedClipId) paintClip(clip);
            for (const auto& clip : track.clips) if (clip.id == state.selectedClipId) paintClip(clip);
        }
        if (drag.moved && drag.edge == 0 && drag.targetTrackIndex != drag.trackIndex) {
            const auto xx = timeX(drag.previewStart); const auto ww = timeX(drag.previewStart + drag.duration) - xx;
            juce::Rectangle<float> ghost(xx, float(drag.targetTrackIndex * rowHeight + (rowHeight < 104 ? 9 : 17)), ww, float(rowHeight < 104 ? rowHeight - 18 : 66));
            g.setColour(ink.withAlpha(0.07f)); g.fillRect(ghost); g.setColour(ink); g.drawRect(ghost, 2);
        }
        const auto head = timeX(state.position);
        if (head >= labelWidth() && head <= labelWidth() + plotWidth()) {
            g.setColour(ink); g.drawVerticalLine(juce::roundToInt(head), static_cast<float>(dirty.getY()), static_cast<float>(dirty.getBottom()));
        }
        paintAttention(g);
    }
    std::shared_ptr<Peaks> findPeaks(const juce::String& id) const
    {
        const auto found = entries.find(id);
        return found == entries.end() ? nullptr : found->second;
    }
    void updatePeaks(bool force)
    {
        const auto now = juce::Time::getMillisecondCounter();
        if (!force && now - lastSourceCheck < 1000) return;
        lastSourceCheck = now;
        std::map<juce::String, std::shared_ptr<Peaks>> next;
        for (const auto& track : state.tracks) for (const auto& clip : track.clips) {
            if (clip.kind == "midi") continue;
            const auto& source = clip.waveformSource;
            const bool valid = source.existsAsFile();
            const auto fingerprint = source.getFullPathName() + "|" + juce::String(source.getSize()) + "|"
                + juce::String(source.getLastModificationTime().toMilliseconds()) + (valid ? "|ok" : "|missing");
            auto peaks = findPeaks(clip.id);
            if (peaks == nullptr || peaks->fingerprint != fingerprint) {
                if (peaks != nullptr) peaks->cancelled.store(true);
                peaks = std::make_shared<Peaks>(formats, cache, source, fingerprint, fingerprint.hashCode64());
                if (valid) pool.addJob(new PeakJob(peaks, cache), true);
                else peaks->status.store(PeakStatus::failed, std::memory_order_release);
            }
            next.emplace(clip.id, std::move(peaks));
        }
        for (auto& old : entries) if (next.find(old.first) == next.end()) old.second->cancelled.store(true);
        entries = std::move(next);
    }
    ArrangementView& owner;
    EngineSession& engine;
    juce::AudioFormatManager formats;
    juce::AudioThumbnailCache cache { 64 };
    juce::ThreadPool pool { 1 };
    std::map<juce::String, std::shared_ptr<Peaks>> entries;
    std::map<juce::String, MidiOverview> midiOverviews;
    EngineSession::Snapshot state;
    struct Drag {
        juce::String id, projectId;
        std::uint64_t revision = 0;
        double originalStart = 0.0, previewStart = 0.0, duration = 0.0, secondsPerPixel = 0.0;
        double originalDuration = 0.0, sourceOffset = 0.0, sourceDuration = 0.0;
        double groupStart = 0.0, groupEnd = 0.0;
        juce::StringArray clipIds;
        int edge = 0, trackIndex = 0, targetTrackIndex = 0;
        float downX = 0.0f, downY = 0.0f;
        bool moved = false, midi = false;
    } drag;
    juce::Result lastMoveResult = juce::Result::ok();
    Canvas canvas;
    std::vector<std::unique_ptr<TrackControls>> headers;
    juce::Viewport viewport;
    juce::ScrollBar horizontal;
    double zoom = 1.0, viewStart = 0.0;
    int rowHeight = 104;
    double gridBeats = 0.25;
    bool bars = false;
    juce::StringArray selection;
    juce::uint32 lastSourceCheck = 0;
    bool forceSourceCheck = true, dropActive = false, selecting = false;
};

ArrangementView::ArrangementView(EngineSession& session) : impl(std::make_unique<Impl>(*this, session))
{
    setWantsKeyboardFocus(true);
    setTitle("Multitrack audio arrangement");
    setDescription("Click a clip to select; drag it to move. Escape cancels. Ruler or empty space seeks. Control plus wheel zooms; Shift plus wheel scrolls time.");
}
ArrangementView::~ArrangementView() = default;
void ArrangementView::update(const EngineSession::Snapshot& next)
{
    auto& p = *impl;
    const bool projectChanged = next.projectId != p.state.projectId;
    const bool primaryClipChanged = next.selectedClipId != p.state.selectedClipId;
    const bool selectionChanged = next.selectedTrackId != p.state.selectedTrackId;
    const bool contentChanged = projectChanged || next.revision != p.state.revision || next.tracks.size() != p.state.tracks.size();
    const bool lengthChanged = next.duration != p.state.duration;
    bool sourcesChanged = next.tracks.size() != p.state.tracks.size();
    if (!sourcesChanged)
        for (std::size_t i = 0; i < next.tracks.size(); ++i) {
            const auto& a = next.tracks[i].clips;
            const auto& b = p.state.tracks[i].clips;
            if (a.size() != b.size()) { sourcesChanged = true; break; }
            for (std::size_t c = 0; c < a.size(); ++c)
                if (a[c].id != b[c].id || a[c].waveformSource != b[c].waveformSource) { sourcesChanged = true; break; }
        }
    if (projectChanged || (p.drag.id.isNotEmpty() && next.selectedClipId != p.drag.id)) p.cancelDrag();
    p.state = next;
    bool headersChanged = p.headers.size() != next.tracks.size();
    if (!headersChanged) for (std::size_t i = 0; i < p.headers.size(); ++i) if (p.headers[i]->id != next.tracks[i].id) { headersChanged = true; break; }
    if (headersChanged) {
        p.headers.clear();
        for (const auto& track : next.tracks) { auto header = std::make_unique<Impl::TrackControls>(p, track.id); p.canvas.addAndMakeVisible(*header); p.headers.push_back(std::move(header)); }
    }
    for (std::size_t i = 0; i < p.headers.size(); ++i) {
        p.headers[i]->mute.setToggleState(next.tracks[i].muted, juce::dontSendNotification);
        p.headers[i]->solo.setToggleState(next.tracks[i].solo, juce::dontSendNotification);
        p.headers[i]->arm.setToggleState(next.tracks[i].armed, juce::dontSendNotification);
        p.headers[i]->arm.setEnabled(next.tracks[i].kind != "bus" && !next.recording && !next.recordingFinalizing);
    }
    if (contentChanged) p.updateMidiOverviews();
    if (projectChanged) p.selection.clear();
    for (int i = p.selection.size(); --i >= 0;) {
        bool exists = false;
        for (const auto& track : next.tracks) for (const auto& clip : track.clips) if (clip.id == p.selection[i]) exists = true;
        if (!exists) p.selection.remove(i);
    }
    if (!p.selecting && (primaryClipChanged || projectChanged) && next.selectedClipId.isNotEmpty()) p.selection = { next.selectedClipId };
    p.updatePeaks(sourcesChanged || p.forceSourceCheck);
    p.forceSourceCheck = false;
    if (projectChanged) { p.zoom = 1.0; p.viewStart = 0.0; p.viewport.setViewPosition(0, 0); }
    if (contentChanged || lengthChanged) p.layout();
    if (selectionChanged && !projectChanged) {
        for (std::size_t i = 0; i < p.state.tracks.size(); ++i) if (p.state.tracks[i].id == p.state.selectedTrackId) {
            const int top = static_cast<int>(i) * p.rowHeight;
            if (top < p.viewport.getViewPositionY()) p.viewport.setViewPosition(0, top);
            else if (top + p.rowHeight > p.viewport.getViewArea().getBottom()) p.viewport.setViewPosition(0, top + p.rowHeight - p.viewport.getHeight());
            break;
        }
    }
    p.canvas.repaint(); repaint();
}
void ArrangementView::invalidateSources() { impl->forceSourceCheck = true; }
void ArrangementView::setCompactRows(bool compact) { const int height = compact ? 64 : 104; if (impl->rowHeight != height) { impl->rowHeight = height; impl->layout(); } }
void ArrangementView::fitToProject() { impl->zoom = 1.0; impl->viewStart = 0.0; impl->syncScroll(); }
void ArrangementView::zoomIn() { impl->setZoom(impl->zoom * 2.0, 0.5); }
void ArrangementView::zoomOut() { impl->setZoom(impl->zoom * 0.5, 0.5); }
double ArrangementView::zoomFactor() const { return impl->zoom; }
void ArrangementView::setDropActive(bool active)
{
    impl->dropActive = active;
    impl->canvas.repaint(); repaint();
}
bool ArrangementView::isDropActive() const { return impl->dropActive; }
bool ArrangementView::cancelClipDrag() { return impl->cancelDrag(); }
juce::StringArray ArrangementView::selectedClipIds() const { return impl->selection; }
void ArrangementView::setGrid(double beats, bool bars) { impl->gridBeats = juce::jmax(0.0, beats); impl->bars = bars; impl->canvas.repaint(); repaint(); }
bool ArrangementView::trackWaveformReady(const juce::String& id) const
{
    const auto peaks = impl->findPeaks(id);
    return peaks != nullptr && peaks->status.load(std::memory_order_acquire) == PeakStatus::ready;
}
bool ArrangementView::waveformsReady() const
{
    for (const auto& track : impl->state.tracks) for (const auto& clip : track.clips) if (clip.kind != "midi" && !trackWaveformReady(clip.id)) return false;
    return true;
}
juce::String ArrangementView::waveformStatus(const juce::String& id) const
{
    const auto peaks = impl->findPeaks(id);
    if (peaks == nullptr || peaks->status.load(std::memory_order_acquire) == PeakStatus::failed) return "Waveform unavailable";
    return "Reading waveform...";
}
void ArrangementView::drawTrackWaveform(juce::Graphics& g, juce::Rectangle<int> area, const juce::String& id,
                                       double start, double end, float verticalZoom)
{
    const auto peaks = impl->findPeaks(id);
    if (peaks != nullptr && peaks->status.load(std::memory_order_acquire) == PeakStatus::ready && end > start)
        peaks->thumbnail.drawChannels(g, area, start, end, verticalZoom);
}
void ArrangementView::resized() { impl->layout(); }
void ArrangementView::paint(juce::Graphics& g)
{
    auto& p = *impl;
    g.fillAll(paper);
    g.setColour(secondary); g.setFont(mono(11.0f));
    g.drawText(p.dropActive ? "drop audio / MIDI" : juce::String(p.bars ? "bars / " : "seconds / ") + juce::String(p.zoom, 0) + "x",
               10, 0, p.labelWidth() - 15, 24, juce::Justification::centredLeft);
    int previousLabelRight = p.labelWidth() - 8;
    if (p.state.duration > 0) p.eachTick([&](double seconds, float x) {
        g.setColour(secondary); g.setFont(mono(11.0f));
        const auto width = 78;
        const auto left = juce::jlimit(p.labelWidth(), p.canvas.getWidth() - width, juce::roundToInt(x) - width / 2);
        if (left >= previousLabelRight + 8) {
            g.drawText(p.tickText(seconds), left, 0, width, 24, juce::Justification::centred);
            previousLabelRight = left + width;
        }
        g.setColour(rule); g.drawLine(x, 26.0f, x, static_cast<float>(rulerHeight));
    });
    g.setColour(rule); g.drawHorizontalLine(rulerHeight - 1, 0.0f, static_cast<float>(getWidth()));
    if (p.state.loopEnd > p.state.loopStart) {
        const auto left = juce::jlimit(float(p.labelWidth()), float(p.labelWidth() + p.plotWidth()), p.timeX(p.state.loopStart));
        const auto right = juce::jlimit(float(p.labelWidth()), float(p.labelWidth() + p.plotWidth()), p.timeX(p.state.loopEnd));
        if (right > left) {
            g.setColour(p.state.looping ? ink : secondary.withAlpha(0.45f));
            g.drawLine(left, 29, right, 29, 2);
            g.drawLine(left, 26, left, 33, 1); g.drawLine(right, 26, right, 33, 1);
        }
    }
    const auto head = p.timeX(p.state.position);
    if (!p.state.tracks.empty() && head >= p.labelWidth() && head <= p.labelWidth() + p.plotWidth()) {
        g.setColour(ink);
        juce::Path marker;
        marker.addTriangle(head - 4.0f, 25.0f, head + 4.0f, 25.0f, head, 32.0f);
        g.fillPath(marker);
    }
}
void ArrangementView::mouseDown(const juce::MouseEvent& e)
{
    if (isShowing()) grabKeyboardFocus();
    if (e.position.x >= impl->labelWidth()) impl->seekAt(e.position.x);
}
void ArrangementView::mouseDrag(const juce::MouseEvent& e) { if (e.mouseDownPosition.x >= impl->labelWidth()) impl->seekAt(e.position.x); }
void ArrangementView::mouseWheelMove(const juce::MouseEvent& e, const juce::MouseWheelDetails& wheel) { impl->wheel(e.position.x, e.mods, wheel); }
bool ArrangementView::keyPressed(const juce::KeyPress& key)
{
    if (key == juce::KeyPress::escapeKey && cancelClipDrag()) return true;
    if (key.getModifiers().isAnyModifierKeyDown() || impl->state.duration <= 0.0) return false;
    const auto& state = impl->state;
    if (key == juce::KeyPress::homeKey) impl->engine.seek(0.0);
    else if (key == juce::KeyPress::endKey) impl->engine.seek(state.duration);
    else if (key == juce::KeyPress::leftKey) impl->engine.seek(juce::jmax(0.0, state.position - 5.0));
    else if (key == juce::KeyPress::rightKey) impl->engine.seek(juce::jmin(state.duration, state.position + 5.0));
    else return false;
    impl->notifyState();
    return true;
}
void ArrangementView::focusGained(FocusChangeType) { impl->canvas.repaint(); repaint(); }
void ArrangementView::focusLost(FocusChangeType) { impl->canvas.repaint(); repaint(); }
void ArrangementView::focusOfChildComponentChanged(FocusChangeType) { impl->canvas.repaint(); repaint(); }

juce::Result ArrangementView::runSmokeTest(juce::DynamicObject& report)
{
    auto& p = *impl;
    const auto initial = p.engine.snapshot();
    const auto originalBounds = getBounds();
    const auto check = [](bool success, const char* message) { return success ? juce::Result::ok() : juce::Result::fail(message); };
    if (initial.tracks.size() < 2 || initial.duration <= 0.0) return juce::Result::fail("Arrangement smoke requires at least two real imported tracks.");
    fitToProject();
    report.setProperty("track_rows", static_cast<int>(p.state.tracks.size()));
    report.setProperty("waveforms_complete", waveformsReady());
    if (!waveformsReady()) return juce::Result::fail("Arrangement waveform peaks have not completed successfully.");
    auto result = check(p.canvas.getHeight() >= static_cast<int>(initial.tracks.size()) * rowHeight, "Track canvas does not contain all real rows.");
    if (result.failed()) return result;
    juce::Array<juce::var> widths;
    for (std::size_t row = 0; row < initial.tracks.size(); ++row) for (const auto& clip : initial.tracks[row].clips) {
        const auto actual = p.clipArea(row, clip);
        const auto expectedWidth = clip.duration / initial.duration * p.plotWidth();
        const auto expectedX = p.labelWidth() + clip.timelineStart / initial.duration * p.plotWidth();
        if (std::abs(actual.getWidth() - expectedWidth) > 0.1 || std::abs(actual.getX() - expectedX) > 0.1)
            return juce::Result::fail("A clip does not use the common project time scale.");
        auto detail = new juce::DynamicObject;
        detail->setProperty("track_id", initial.tracks[row].id);
        detail->setProperty("clip_id", clip.id);
        detail->setProperty("timeline_start", clip.timelineStart);
        detail->setProperty("source_offset", clip.sourceOffset);
        detail->setProperty("duration", clip.duration);
        detail->setProperty("width_px", actual.getWidth());
        detail->setProperty("waveform_source", clip.waveformSource.getFullPathName());
        widths.add(juce::var(detail));
    }
    report.setProperty("clip_geometry", widths);
    const auto event = [&](float x, float y, bool dragging = false) {
        const auto now = juce::Time::getCurrentTime();
        return juce::MouseEvent(juce::Desktop::getInstance().getMainMouseSource(), { x, y },
            juce::ModifierKeys(juce::ModifierKeys::leftButtonModifier), 1.0f, 0.0f, 0.0f, 0.0f, 0.0f,
            &p.canvas, &p.canvas, now, { x, y }, now, 1, dragging);
    };
    const auto lastRow = static_cast<int>(initial.tracks.size()) - 1;
    p.canvas.mouseDown(event(20.0f, static_cast<float>(lastRow * rowHeight + 30)));
    if (p.engine.snapshot().selectedTrackId != initial.tracks.back().id) return juce::Result::fail("Clicking an arrangement row did not select its real track.");
    const auto halfX = static_cast<float>(p.labelWidth() + p.plotWidth() * 0.5);
    p.canvas.mouseDown(event(halfX, static_cast<float>(lastRow * rowHeight + 5)));
    if (std::abs(p.engine.snapshot().position - initial.duration * 0.5) > 0.002) return juce::Result::fail("Timeline click did not seek to the shared time coordinate.");
    p.canvas.mouseDrag(event(static_cast<float>(p.labelWidth() + p.plotWidth() + 100), 30.0f, true));
    if (std::abs(p.engine.snapshot().position - initial.duration) > 0.002) return juce::Result::fail("Timeline drag did not clamp at project end.");
    p.canvas.mouseDrag(event(-100.0f, 30.0f, true));
    p.canvas.mouseUp(event(-100.0f, 30.0f));
    if (p.engine.snapshot().position > 0.002) return juce::Result::fail("Timeline drag did not clamp at zero.");
    report.setProperty("selection_and_seek_events", true);
    for (int n = 0; n < 8; ++n) zoomIn();
    if (zoomFactor() != 32.0) return juce::Result::fail("Zoom maximum was not bounded.");
    juce::String previousTick;
    bool distinctTicks = true;
    int tickCount = 0;
    p.eachTick([&](double seconds, float) {
        const auto label = p.tickText(seconds);
        if (previousTick == label) distinctTicks = false;
        previousTick = label;
        ++tickCount;
    });
    if (!distinctTicks || tickCount < 2) return juce::Result::fail("High-zoom ruler labels are missing or repeat rounded times.");
    report.setProperty("high_zoom_tick_labels_distinct", true);
    report.setProperty("high_zoom_tick_step_seconds", p.tickStep());
    p.horizontal.setCurrentRangeStart(initial.duration, juce::sendNotificationSync);
    if (std::abs(p.viewStart + p.visibleDuration() - initial.duration) > 0.00001) return juce::Result::fail("Horizontal scroll did not reach the final time range.");
    for (int n = 0; n < 8; ++n) zoomOut();
    if (zoomFactor() != 1.0 || p.viewStart != 0.0) return juce::Result::fail("Zoom minimum did not restore the project bounds.");
    report.setProperty("zoom_and_horizontal_bounds", true);
    setSize(originalBounds.getWidth(), 180);
    p.engine.selectTrack(initial.tracks.front().id);
    p.notifyState();
    p.viewport.setViewPosition(0, 0);
    p.engine.selectTrack(initial.tracks.back().id);
    p.notifyState();
    if (getHeight() != 180) {
        setBounds(originalBounds);
        return juce::Result::fail("Track selection unexpectedly changed the constrained arrangement viewport height.");
    }
    const bool selectionRevealed = p.viewport.getViewArea().contains(juce::Rectangle<int>(0, lastRow * rowHeight, p.canvas.getWidth(), rowHeight));
    if (!selectionRevealed) {
        setBounds(originalBounds);
        return juce::Result::fail("Selecting an offscreen track did not reveal its arrangement row.");
    }
    report.setProperty("selection_reveals_row", true);
    p.viewport.setViewPosition(0, lastRow * rowHeight);
    const bool lastVisible = p.viewport.getViewArea().intersects(juce::Rectangle<int>(0, lastRow * rowHeight, p.canvas.getWidth(), rowHeight));
    const bool scrolled = p.viewport.getViewPositionY() > 0;
    report.setProperty("constrained_vertical_viewport_height", p.viewport.getHeight());
    report.setProperty("last_row_scroll_y", p.viewport.getViewPositionY());
    setBounds(originalBounds);
    p.viewport.setViewPosition(0, 0);
    if (!lastVisible || !scrolled) return juce::Result::fail("The final real track is not reachable by vertical scrolling.");
    report.setProperty("vertical_scroll_last_row", true);
    keyPressed(juce::KeyPress(juce::KeyPress::endKey));
    if (std::abs(p.engine.snapshot().position - initial.duration) > 0.002) return juce::Result::fail("End key did not seek to project end.");
    keyPressed(juce::KeyPress(juce::KeyPress::homeKey));
    if (p.engine.snapshot().position > 0.002) return juce::Result::fail("Home key did not seek to zero.");
    p.engine.selectClip(initial.selectedClipId);
    p.engine.seek(initial.position);
    p.notifyState();
    const auto after = p.engine.snapshot();
    if (after.revision != initial.revision || after.dirty != initial.dirty || after.tracks.size() != initial.tracks.size())
        return juce::Result::fail("Arrangement navigation modified the music project.");
    report.setProperty("navigation_preserves_revision_and_dirty", true);
    report.setProperty("keyboard_seek", true);
    report.setProperty("common_time_scale", true);

    // Real component input drives the production drag state and Engine command.
    // No writable copy of the musical model is used by the interaction test.
    if (initial.tracks.front().clips.empty()) return juce::Result::fail("Clip drag smoke needs a real clip.");
    const auto original = initial.tracks.front().clips.front();
    const auto currentClip = [&]() {
        for (const auto& track : p.engine.snapshot().tracks) for (const auto& clip : track.clips)
            if (clip.id == original.id) return clip;
        return EngineSession::ClipSnapshot {};
    };
    p.engine.selectClip(original.id); p.notifyState();
    fitToProject();
    const auto body = p.clipArea(0, original);
    const auto point = body.getCentre();
    const auto clickState = p.engine.snapshot();
    p.canvas.mouseDown(event(point.x, point.y));
    p.canvas.mouseDrag(event(point.x + 2.0f, point.y, true));
    p.canvas.mouseUp(event(point.x + 2.0f, point.y));
    if (p.engine.snapshot().selectedClipId != original.id || p.engine.snapshot().revision != clickState.revision
        || std::abs(p.engine.snapshot().position - clickState.position) > 0.00001)
        return juce::Result::fail("A clip click or tiny drag sought or edited the project.");
    report.setProperty("clip_click_selects_without_seek", true);
    const auto beforeMove = p.engine.snapshot();
    const float delta = static_cast<float>(0.25 * p.plotWidth() / p.visibleDuration());
    p.canvas.mouseDown(event(point.x, point.y));
    p.canvas.mouseDrag(event(point.x + delta, point.y, true));
    p.canvas.mouseDrag(event(point.x + delta * 2.0f, point.y, true));
    if (p.engine.snapshot().revision != beforeMove.revision || std::abs(currentClip().timelineStart - original.timelineStart) > 0.000001
        || !p.drag.moved || std::abs(p.drag.previewStart - original.timelineStart - 0.5) > 0.00001)
        return juce::Result::fail("Clip drag preview committed early or used the wrong time scale.");
    p.canvas.mouseUp(event(point.x + delta * 2.0f, point.y));
    const auto moved = p.engine.snapshot();
    const auto movedClip = currentClip();
    auto commitEvidence = new juce::DynamicObject;
    commitEvidence->setProperty("command_ok", p.lastMoveResult.wasOk());
    commitEvidence->setProperty("command_error", p.lastMoveResult.getErrorMessage());
    commitEvidence->setProperty("revision_before", static_cast<juce::int64>(beforeMove.revision));
    commitEvidence->setProperty("revision_after", static_cast<juce::int64>(moved.revision));
    commitEvidence->setProperty("start_seconds", juce::String(movedClip.timelineStart, 17));
    commitEvidence->setProperty("source_offset_before", juce::String(original.sourceOffset, 17));
    commitEvidence->setProperty("source_offset_after", juce::String(movedClip.sourceOffset, 17));
    commitEvidence->setProperty("length_before", juce::String(original.duration, 17));
    commitEvidence->setProperty("length_after", juce::String(movedClip.duration, 17));
    commitEvidence->setProperty("playing", moved.playing);
    report.setProperty("clip_drag_commit_evidence", juce::var(commitEvidence));
    if (p.lastMoveResult.failed() || moved.revision != beforeMove.revision + 1
        || std::abs(movedClip.timelineStart - original.timelineStart - 0.5) > 0.00001
        // TimeRange derives length from end - start. A pixel-generated start
        // may change that subtraction by one ULP, well below one audio sample.
        || std::abs(movedClip.sourceOffset - original.sourceOffset) > 1.0e-9
        || std::abs(movedClip.duration - original.duration) > 1.0e-9 || moved.playing)
        return juce::Result::fail("Mouse-up clip move failed: command=" + p.lastMoveResult.getErrorMessage()
            + "; revision=" + juce::String(static_cast<juce::int64>(beforeMove.revision)) + "->" + juce::String(static_cast<juce::int64>(moved.revision))
            + "; start=" + juce::String(movedClip.timelineStart, 17)
            + "; offset=" + juce::String(original.sourceOffset, 17) + "->" + juce::String(movedClip.sourceOffset, 17)
            + "; length=" + juce::String(original.duration, 17) + "->" + juce::String(movedClip.duration, 17)
            + "; playing=" + juce::String(moved.playing ? "true" : "false"));
    if (auto undo = p.engine.undo(moved.revision); undo.failed()) return undo;
    p.notifyState();
    if (std::abs(currentClip().timelineStart - original.timelineStart) > 0.00001 || p.engine.snapshot().dirty != initial.dirty)
        return juce::Result::fail("A single Undo did not restore the clip drag.");
    report.setProperty("clip_drag_preview_then_single_commit", true);
    report.setProperty("clip_drag_single_undo", true);

    fitToProject();
    const auto cancelState = p.engine.snapshot();
    const auto cancelPoint = p.clipArea(0, original).getCentre();
    p.canvas.mouseDown(event(cancelPoint.x, cancelPoint.y));
    p.canvas.mouseDrag(event(cancelPoint.x + 40.0f, cancelPoint.y, true));
    if (!keyPressed(juce::KeyPress(juce::KeyPress::escapeKey))) return juce::Result::fail("Escape did not cancel the clip drag.");
    p.canvas.mouseUp(event(cancelPoint.x + 40.0f, cancelPoint.y));
    if (p.engine.snapshot().revision != cancelState.revision || currentClip().timelineStart != original.timelineStart)
        return juce::Result::fail("A cancelled drag modified the clip.");
    report.setProperty("clip_drag_escape_cancel", true);

    p.canvas.mouseDown(event(cancelPoint.x, cancelPoint.y));
    p.canvas.mouseDrag(event(cancelPoint.x + 40.0f, cancelPoint.y, true));
    const auto gainBefore = p.engine.snapshot();
    const auto gain = initial.tracks.front().gainDb;
    const auto changedGain = gain < 5.9f ? gain + 0.1f : gain - 0.1f;
    if (auto changed = p.engine.setTrackGain(initial.tracks.front().id, changedGain, gainBefore.revision); changed.failed()) return changed;
    p.notifyState();
    const auto staleRevision = p.engine.snapshot().revision;
    p.canvas.mouseUp(event(cancelPoint.x + 40.0f, cancelPoint.y));
    if (p.lastMoveResult.wasOk() || p.engine.snapshot().revision != staleRevision || currentClip().timelineStart != original.timelineStart)
        return juce::Result::fail("A drag captured before a project edit was not rejected.");
    if (auto undo = p.engine.undo(staleRevision); undo.failed()) return undo;
    p.notifyState();
    report.setProperty("clip_drag_stale_revision_rejected", true);
    p.engine.selectClip(initial.selectedClipId);
    p.engine.seek(initial.position);
    p.notifyState();
    fitToProject();
    p.viewport.setViewPosition(0, 0);
    if (onEditResult) onEditResult(juce::Result::ok());
    if (p.engine.snapshot().dirty != initial.dirty) return juce::Result::fail("Clip drag tests did not restore the initial clean state.");
    return juce::Result::ok();
}
} // namespace emusician
