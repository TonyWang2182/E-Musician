#include "ArrangementView.h"
#include "core/time/EditGrid.hpp"
#include "core/time/MusicalPosition.hpp"
#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <map>

namespace emusician {
namespace {
const juce::Colour ink { 0xff171817 }, secondary { 0xff626560 }, rule { 0xffc6c9c3 }, paper { 0xfffefefd };
constexpr int rulerHeight = 54, scrollSize = 12, rowHeight = 104;
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
constexpr int detailFrames = 65536, detailWindowLimit = 16;
struct WaveformDetail {
    juce::int64 firstSample = 0;
    double sampleRate = 0;
    juce::AudioBuffer<float> samples;
    bool covers(double start, double end) const
    {
        return start * sampleRate >= double(firstSample)
            && end * sampleRate <= double(firstSample + samples.getNumSamples());
    }
    void draw(juce::Graphics& g, juce::Rectangle<int> area, double start, double end, float gain) const
    {
        if (area.isEmpty() || samples.getNumSamples() == 0) return;
        juce::Graphics::ScopedSaveState clipped(g); g.reduceClipRegion(area);
        const double first = start * sampleRate - double(firstSample);
        const double perPixel = (end - start) * sampleRate / area.getWidth();
        const int channels = samples.getNumChannels();
        for (int channel = 0; channel < channels; ++channel) {
            const auto top = area.getY() + channel * area.getHeight() / channels;
            const auto bottom = area.getY() + (channel + 1) * area.getHeight() / channels;
            const auto centre = (top + bottom) * 0.5f, amplitude = (bottom - top) * 0.5f * gain;
            const auto* data = samples.getReadPointer(channel);
            const auto at = [&](int index) { return data[juce::jlimit(0, samples.getNumSamples() - 1, index)]; };
            if (perPixel < 1.0) {
                juce::Path path;
                for (int x = 0; x < area.getWidth(); ++x) {
                    const auto sample = first + double(x) * perPixel;
                    const auto index = int(std::floor(sample));
                    const auto value = at(index) + float(sample - index) * (at(index + 1) - at(index));
                    const auto px = float(area.getX() + x), py = centre - value * amplitude;
                    if (x == 0) path.startNewSubPath(px, py); else path.lineTo(px, py);
                }
                g.strokePath(path, juce::PathStrokeType(1.0f));
            } else {
                for (int x = 0; x < area.getWidth(); ++x) {
                    const auto begin = juce::jlimit(0, samples.getNumSamples() - 1, int(std::floor(first + double(x) * perPixel)));
                    const auto finish = juce::jlimit(begin + 1, samples.getNumSamples(), int(std::ceil(first + double(x + 1) * perPixel)));
                    const auto range = juce::FloatVectorOperations::findMinAndMax(data + begin, finish - begin);
                    g.drawVerticalLine(area.getX() + x, centre - range.getEnd() * amplitude,
                        std::max(centre - range.getEnd() * amplitude + 1.0f, centre - range.getStart() * amplitude));
                }
            }
        }
    }
};
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
    // Metadata is published before status=ready. Detail windows are immutable.
    double sampleRate = 0;
    juce::int64 sampleCount = 0;
    juce::CriticalSection detailLock;
    std::shared_ptr<const WaveformDetail> detail;
    std::uint64_t detailGeneration = 0;
    std::atomic<bool> detailPending { false };
    std::atomic<bool> detailFailed { false };
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
        juce::WavAudioFormat format;
        auto stream = peaks->source.createInputStream();
        std::unique_ptr<juce::AudioFormatReader> reader(stream != nullptr ? format.createReaderFor(stream.release(), true) : nullptr);
        if (reader == nullptr || reader->lengthInSamples <= 0 || reader->sampleRate <= 0 || reader->numChannels == 0) {
            peaks->status.store(PeakStatus::failed, std::memory_order_release);
            return jobHasFinished;
        }
        peaks->sampleRate = reader->sampleRate;
        peaks->sampleCount = reader->lengthInSamples;
        if (cache.loadThumb(peaks->thumbnail, peaks->hash)) {
            peaks->status.store(PeakStatus::ready, std::memory_order_release);
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

// A separate serial worker prevents close-zoom requests waiting for a complete
// long-file overview. Reads, allocation and decoder creation never happen in paint.
class DetailJob final : public juce::ThreadPoolJob {
public:
    DetailJob(std::shared_ptr<Peaks> target, juce::int64 first, std::uint64_t generation)
        : ThreadPoolJob("Waveform detail window"), peaks(std::move(target)), firstSample(first), token(generation) {}
    JobStatus runJob() override
    {
        struct Complete { Peaks& target; ~Complete() { target.detailPending.store(false); } } complete { *peaks };
        if (shouldExit() || peaks->cancelled.load()) return jobHasFinished;
        juce::WavAudioFormat format;
        auto stream = peaks->source.createInputStream();
        std::unique_ptr<juce::AudioFormatReader> reader(stream != nullptr ? format.createReaderFor(stream.release(), true) : nullptr);
        if (reader == nullptr || reader->sampleRate <= 0 || reader->numChannels == 0 || firstSample >= reader->lengthInSamples) {
            peaks->detailFailed.store(true); return jobHasFinished;
        }
        auto window = std::make_shared<WaveformDetail>();
        window->firstSample = firstSample; window->sampleRate = reader->sampleRate;
        const auto count = int(std::min<juce::int64>(detailFrames, reader->lengthInSamples - firstSample));
        window->samples.setSize(std::min(2, int(reader->numChannels)), count);
        if (!reader->read(&window->samples, 0, count, firstSample, true, true)) {
            peaks->detailFailed.store(true); return jobHasFinished;
        }
        const juce::ScopedLock guard(peaks->detailLock);
        if (!shouldExit() && !peaks->cancelled.load() && peaks->detailGeneration == token) peaks->detail = std::move(window);
        return jobHasFinished;
    }
private:
    std::shared_ptr<Peaks> peaks;
    juce::int64 firstSample;
    std::uint64_t token;
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
            p.followSuspended = true;
            p.rangeSelection = {};
            if (e.position.x >= p.labelWidth()) p.explicitTrackSelection.clear();
            p.marquee = false;
            p.marqueeOrigin = e.position;
            p.marqueeBase = (e.mods.isCtrlDown() || e.mods.isCommandDown()) ? p.selection : juce::StringArray{};
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
                p.drag.fadeIn = p.drag.originalFadeIn = picked.fadeIn;
                p.drag.fadeOut = p.drag.originalFadeOut = picked.fadeOut;
                p.drag.midi = picked.kind == "midi";
                p.drag.trackIndex = p.drag.targetTrackIndex = index;
                p.drag.clipIds = p.selection;
                p.dragEdges.clear();
                for (const auto& track : p.state.tracks) for (const auto& other : track.clips)
                    if (!p.drag.clipIds.contains(other.id)) {
                        p.dragEdges.push_back(other.timelineStart);
                        p.dragEdges.push_back(other.timelineStart + other.duration);
                    }
                std::sort(p.dragEdges.begin(), p.dragEdges.end());
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
                if (!p.drag.midi && hit.getWidth() > 32 && e.position.y <= hit.getY() + 24) {
                    if (std::abs(e.position.x - p.fadeHandleX(picked, true)) <= 7) p.drag.edge = -2;
                    else if (std::abs(e.position.x - p.fadeHandleX(picked, false)) <= 7) p.drag.edge = 2;
                }
                p.drag.downX = e.position.x;
                p.drag.downY = e.position.y;
                p.drag.secondsPerPixel = p.visibleDuration() / p.plotWidth();
                return;
            }
            if (e.position.x < p.labelWidth()) {
                p.explicitTrackSelection = p.state.tracks[static_cast<std::size_t>(index)].id;
                p.selection.clear();
                p.engine.selectTrack(p.explicitTrackSelection);
                if (p.owner.onTrackFocus) p.owner.onTrackFocus(p.explicitTrackSelection);
                p.notifyState();
                return;
            }
            else if (!e.mods.isCtrlDown() && !e.mods.isCommandDown()) p.selection.clear();
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
                    const auto snap = [&](double value) { return p.snapTime(value, e.mods.isAltDown(), true); };
                    if (p.drag.edge == -2) {
                        p.drag.fadeIn = juce::jlimit(0.0, p.drag.duration - p.drag.fadeOut, p.drag.originalFadeIn + delta);
                    } else if (p.drag.edge == 2) {
                        p.drag.fadeOut = juce::jlimit(0.0, p.drag.duration - p.drag.fadeIn, p.drag.originalFadeOut - delta);
                    } else if (p.drag.edge < 0) {
                        p.drag.previewStart = juce::jlimit(p.drag.midi ? 0.0 : juce::jmax(0.0, p.drag.originalStart - p.drag.sourceOffset),
                            p.drag.originalStart + p.drag.originalDuration - time::minimumEditSpanSeconds, snap(p.drag.originalStart + delta));
                        p.drag.duration = p.drag.originalStart + p.drag.originalDuration - p.drag.previewStart;
                    } else if (p.drag.edge > 0) {
                        const auto end = juce::jlimit(p.drag.originalStart + time::minimumEditSpanSeconds,
                            p.drag.midi ? 172800.0 : juce::jmin(172800.0, p.drag.originalStart + p.drag.sourceDuration - p.drag.sourceOffset),
                            snap(p.drag.originalStart + p.drag.originalDuration + delta));
                        p.drag.duration = end - p.drag.originalStart;
                    } else {
                        p.drag.previewStart = juce::jlimit(p.drag.originalStart - p.drag.groupStart,
                            172800.0 - p.drag.groupEnd + p.drag.originalStart, snap(p.drag.originalStart + delta));
                        p.drag.targetTrackIndex = juce::jlimit(0, int(p.state.tracks.size()) - 1, int(e.position.y) / p.rowHeight);
                    }
                    repaint();
                }
            } else if (seeking && e.position.getDistanceFrom(p.marqueeOrigin) >= 4.0f) {
                p.marquee = true;
                p.marqueeArea = juce::Rectangle<float>(p.marqueeOrigin, e.position);
                p.selection = p.marqueeBase;
                for (std::size_t row = 0; row < p.state.tracks.size(); ++row)
                    for (const auto& clip : p.state.tracks[row].clips)
                        if (p.clipArea(row, clip).intersects(p.marqueeArea)) p.selection.addIfNotAlreadyThere(clip.id);
                repaint();
            }
        }
        void mouseUp(const juce::MouseEvent&) override {
            seeking = false;
            if (p.marquee) {
                p.marquee = false;
                p.selecting = true;
                if (!p.selection.isEmpty()) p.engine.selectClip(p.selection[0]);
                p.notifyState(); p.selecting = false; repaint();
            }
            p.commitDrag();
        }
        void mouseDoubleClick(const juce::MouseEvent& e) override
        {
            const int row = int(e.position.y) / p.rowHeight;
            if (row >= 0 && row < int(p.state.tracks.size()))
                if (const auto* clip = p.hitClip(std::size_t(row), e.position); clip && clip->kind == "midi" && p.owner.onOpenMidiClip)
                    p.owner.onOpenMidiClip(clip->id);
        }
        void mouseWheelMove(const juce::MouseEvent& e, const juce::MouseWheelDetails& wheel) override
        {
            p.followSuspended = true;
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
                    ? "Double-click: edit MIDI. Ctrl-click: multiple clips. Drag: move; edges: trim. Alt: free move." : clip->source.getFullPathName() + "\nDrag: move; edges: trim; upper handles: fades. Alt: free move.";
            return "Click: locate. Drag empty space: select clips. Shift-drag ruler: select time. Ctrl+L: loop selection.";
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
        detailPool.removeAllJobs(true, -1);
        horizontal.removeListener(this);
        viewport.setViewedComponent(nullptr, false);
    }
    double projectDuration() const
    {
        const auto bar = time::beatsPerBar(state.numerator, state.denominator) * 60.0 / state.bpm;
        const auto music = std::max(state.duration, state.loopEnd);
        return std::min(172800.0, std::max({ 8.0 * bar, std::ceil(music / bar) * bar + 4.0 * bar, extendedTimelineEnd }));
    }
    double visibleDuration() const { return projectDuration() / zoom; }
    double maximumZoom() const
    {
        // Keep the finest fixed grid 16 pixels apart, even at the 48-hour limit.
        // Horizontal coordinates remain viewport-local; no giant component exists.
        const auto minimumVisible = time::minimumEditGridBeats * 60.0 / state.bpm * plotWidth() / 16.0;
        return std::max(1.0, projectDuration() / minimumVisible);
    }
    int labelWidth() const { return canvas.getWidth() >= 560 ? 192 : 160; }
    int plotWidth() const { return juce::jmax(1, canvas.getWidth() - labelWidth() - 7); }
    float timeX(double seconds) const
    {
        return static_cast<float>(labelWidth() + (seconds - viewStart) * plotWidth() / visibleDuration());
    }
    double timeAt(float x) const { return juce::jlimit(0.0, 172800.0, viewStart + (x - labelWidth()) * visibleDuration() / plotWidth()); }
    double effectiveGrid() const { return time::editGridBeats(gridBeats, adaptiveGrid, visibleDuration() * state.bpm / 60.0, plotWidth()); }
    double snapTime(double value, bool bypass, bool edges = false) const
    {
        if (bypass || !snapEnabled) return value;
        const auto beat = 60.0 / state.bpm;
        double result = time::snapEditBeat(value / beat, effectiveGrid()) * beat;
        double distance = std::abs(result - value);
        if (edges) {
            const double tolerance = visibleDuration() / plotWidth() * 6.0;
            const auto right = std::lower_bound(dragEdges.begin(), dragEdges.end(), value);
            const auto consider = [&](double edge) {
                const auto d = std::abs(edge - value);
                if (d <= tolerance && d < distance) { distance = d; result = edge; }
            };
            if (right != dragEdges.end()) consider(*right);
            if (right != dragEdges.begin()) consider(*std::prev(right));
        }
        return result;
    }
    float fadeHandleX(const EngineSession::ClipSnapshot& clip, bool left) const
    {
        const auto start = displayedStart(clip);
        const auto in = drag.id == clip.id ? drag.fadeIn : clip.fadeIn;
        const auto out = drag.id == clip.id ? drag.fadeOut : clip.fadeOut;
        const auto a = clipArea(0, clip);
        return juce::jlimit(a.getX() + 7.0f, a.getRight() - 7.0f, timeX(left ? start + in : start + clip.duration - out));
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
        const auto end = juce::jlimit(viewStart, viewStart + visibleDuration(), clipStart + duration);
        const auto start = juce::jlimit(viewStart, viewStart + visibleDuration(), clipStart);
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
        if (drag.id.isEmpty() && !marquee && rulerDrag == 0) return false;
        drag = {};
        marquee = false; rulerDrag = 0;
        canvas.repaint();
        return true;
    }
    void commitDrag()
    {
        if (drag.id.isEmpty()) return;
        const auto pending = drag;
        drag = {};
        if (!pending.moved || (std::abs(pending.previewStart - pending.originalStart) < 0.0000001
            && std::abs(pending.duration - pending.originalDuration) < 0.0000001 && pending.trackIndex == pending.targetTrackIndex
            && pending.fadeIn == pending.originalFadeIn && pending.fadeOut == pending.originalFadeOut)) { canvas.repaint(); return; }
        auto args = new juce::DynamicObject;
        if (std::abs(pending.edge) == 2) {
            args->setProperty("clip_id", pending.id); args->setProperty("fade_in_seconds", pending.fadeIn); args->setProperty("fade_out_seconds", pending.fadeOut);
            lastMoveResult = engine.execute("set_clip_fades", juce::var(args), pending.revision);
        } else if (pending.edge != 0) {
            args->setProperty("clip_id", pending.id); args->setProperty("start_seconds", pending.previewStart);
            args->setProperty("end_seconds", pending.previewStart + pending.duration);
            lastMoveResult = engine.execute("trim_clip", juce::var(args), pending.revision);
        } else if (pending.clipIds.size() == 1 && pending.trackIndex == pending.targetTrackIndex) {
            delete args; lastMoveResult = engine.moveClip(pending.id, pending.previewStart, pending.revision);
        } else if (pending.trackIndex != pending.targetTrackIndex) {
            delete args; juce::Array<juce::var> commands;
            const int offset = pending.targetTrackIndex - pending.trackIndex;
            bool valid = true;
            for (int row = 0; row < int(state.tracks.size()); ++row) {
                juce::Array<juce::var> ids;
                for (const auto& clip : state.tracks[size_t(row)].clips) if (pending.clipIds.contains(clip.id)) ids.add(clip.id);
                if (ids.isEmpty()) continue;
                const int target = row + offset;
                if (target < 0 || target >= int(state.tracks.size()) || state.tracks[size_t(target)].kind != state.tracks[size_t(row)].kind) { valid = false; break; }
                auto* move = new juce::DynamicObject;
                move->setProperty("clip_ids", ids); move->setProperty("delta_seconds", pending.previewStart - pending.originalStart);
                move->setProperty("target_track_id", state.tracks[size_t(target)].id);
                auto* item = new juce::DynamicObject; item->setProperty("command", "move_clips"); item->setProperty("args", juce::var(move)); commands.add(juce::var(item));
            }
            auto* batch = new juce::DynamicObject; batch->setProperty("commands", commands);
            juce::var batchArgs(batch);
            lastMoveResult = valid ? engine.execute("batch", batchArgs, pending.revision) : juce::Result::fail("Every selected clip needs a compatible destination track; the group was not moved.");
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
        const double seconds = viewStart + (x - labelWidth()) * visibleDuration() / plotWidth();
        engine.seek(juce::jlimit(0.0, projectDuration(), seconds));
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
        horizontal.setEnabled(zoom > 1.0);
        canvas.repaint(); owner.repaint();
    }
    void setZoom(double value, double anchorFraction)
    {
        followSuspended = true;
        const auto fraction = juce::jlimit(0.0, 1.0, anchorFraction);
        const auto anchor = viewStart + visibleDuration() * fraction;
        zoom = juce::jlimit(1.0, maximumZoom(), value);
        viewStart = anchor - visibleDuration() * fraction;
        syncScroll();
    }
    void wheel(float x, juce::ModifierKeys modifiers, const juce::MouseWheelDetails& wheel)
    {
        followSuspended = true;
        if (modifiers.isCtrlDown() || modifiers.isCommandDown())
            setZoom(zoom * std::exp2(juce::jlimit(-1.0, 1.0, double(wheel.deltaY) * 4.0)), (x - labelWidth()) / plotWidth());
        else if (modifiers.isShiftDown()) {
            viewStart -= static_cast<double>(wheel.deltaY + wheel.deltaX) * visibleDuration();
            syncScroll();
        }
    }
    void scrollBarMoved(juce::ScrollBar*, double start) override { followSuspended = true; viewStart = start; syncScroll(); }
    time::MusicalRulerGrid musicalRuler() const
    {
        return time::musicalRulerStep(visibleDuration() * state.bpm / 60.0, plotWidth(), state.numerator, state.denominator);
    }
    double tickStep() const
    {
        if (bars) return musicalRuler().stepBeats * 60.0 / state.bpm;
        const auto target = visibleDuration() / juce::jmax(1.0, plotWidth() / 100.0);
        const auto power = std::pow(10.0, std::floor(std::log10(target)));
        const auto normal = target / power;
        return juce::jmax(0.000001, (normal <= 1.0 ? 1.0 : normal <= 2.0 ? 2.0 : normal <= 5.0 ? 5.0 : 10.0) * power);
    }
    juce::String tickText(double seconds) const
    {
        if (bars) return juce::String(time::musicalRulerLabel(seconds * state.bpm / 60.0,
            state.numerator, state.denominator, musicalRuler().labelTier));
        const int digits = juce::jlimit(1, 6, static_cast<int>(std::ceil(-std::log10(tickStep()) - 0.000001)));
        const auto scale = static_cast<juce::int64>(std::pow(10, digits));
        const auto units = static_cast<juce::int64>(std::llround(juce::jmax(0.0, seconds) * static_cast<double>(scale)));
        return juce::String(units / (scale * 60)).paddedLeft('0', 2) + ":"
            + juce::String((units / scale) % 60).paddedLeft('0', 2) + "."
            + juce::String(units % scale).paddedLeft('0', digits);
    }
    template<class Callback> void eachTick(Callback callback) const
    {
        const auto step = tickStep();
        const auto first = static_cast<juce::int64>(std::ceil(viewStart / step - 1e-7));
        const auto last = static_cast<juce::int64>(std::floor((viewStart + visibleDuration()) / step + 1e-7));
        for (auto index = first; index <= last; ++index) {
            const auto t = double(index) * step;
            callback(t, timeX(t));
        }
    }
    template<class Callback> void eachGrid(Callback callback) const
    {
        const double beatSeconds = 60.0 / state.bpm;
        const double bar = time::beatsPerBar(state.numerator, state.denominator);
        double step = effectiveGrid();
        // Screen density only thins drawing, never the fixed editing lattice.
        while (step * beatSeconds / visibleDuration() * plotWidth() < 8.0) step *= 2.0;
        const double startBeat = viewStart / beatSeconds, endBeat = (viewStart + visibleDuration()) / beatSeconds;
        const auto visit = [&](double interval, auto&& visitor) {
            const auto first = static_cast<juce::int64>(std::ceil(startBeat / interval - 1e-7));
            const auto last = static_cast<juce::int64>(std::floor(endBeat / interval + 1e-7));
            for (auto index = first; index <= last; ++index) visitor(double(index) * interval);
        };
        visit(step, [&](double b) {
            const bool barLine = std::abs(b / bar - std::round(b / bar)) < 1e-7;
            const bool beatLine = std::abs(b * state.denominator / 4.0 - std::round(b * state.denominator / 4.0)) < 1e-7;
            callback(b * beatSeconds, timeX(b * beatSeconds), barLine ? 2 : beatLine ? 1 : 0);
        });
        // Non-power-of-two meters need their own bounded bar overlay.
        double barStep = bar;
        while (barStep * beatSeconds / visibleDuration() * plotWidth() < 8.0) barStep *= 2.0;
        visit(barStep, [&](double b) { callback(b * beatSeconds, timeX(b * beatSeconds), 2); });
    }
    void drawGridLine(juce::Graphics& g, float x, float top, float bottom, int level) const
    {
        g.setColour(level == 2 ? secondary.withAlpha(0.75f) : rule.withAlpha(level == 1 ? 0.9f : 0.6f));
        const auto thickness = level == 2 ? 1.35f : 1.0f;
        const juce::Line<float> line(x, top, x, bottom);
        if (snapEnabled) g.drawLine(line, thickness);
        else {
            constexpr float pattern[] { 3.0f, 3.0f };
            g.drawDashedLine(line, pattern, 2, thickness);
        }
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
            if (rowHeight >= 104) g.drawText(track.kind + " / " + juce::String(track.gainDb, 1) + " dB", 10, y + 39, labelWidth() - 18, 17, juce::Justification::centredLeft);
            const int meterY = y + (rowHeight < 104 ? 26 : 60);
            const int meterWidth = labelWidth() - 20;
            for (int channel = 0; channel < 2; ++channel) {
                const float level = channel == 0 ? track.peakLeftDb : track.peakRightDb;
                g.setColour(rule.withAlpha(0.7f)); g.fillRect(10, meterY + channel * 3, meterWidth, 2);
                g.setColour(ink); g.fillRect(10, meterY + channel * 3, juce::roundToInt(meterWidth * juce::jlimit(0.0f, 1.0f, (level + 60.0f) / 60.0f)), 2);
            }
            if (track.overloaded) { g.setColour(ink); g.setFont(mono(10.0f, juce::Font::bold)); g.drawText("CLIP", labelWidth() - 38, y + 1, 35, 15, juce::Justification::centredRight); }
            if (rowHeight >= 104 && track.armed && track.inputDeviceId.isNotEmpty()) {
                g.setFont(mono(10.0f)); g.setColour(secondary);
                g.drawText("IN " + (track.inputPeakDb <= -99.0f ? juce::String("--") : juce::String(track.inputPeakDb, 1)) + " dB", 80, y + 39, labelWidth() - 90, 17, juce::Justification::centredRight);
            }
            auto flags = track.format + "  " + juce::String(track.gainDb, 1) + " dB";
            if (track.muted) flags = "MUTED";
            else if (track.solo) flags = "SOLO";
            else if (hasSolo) flags = "solo excluded";
            eachGrid([&](double, float x, int level) {
                drawGridLine(g, x, static_cast<float>(y), static_cast<float>(y + rowHeight - 1), level);
            });
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
                        const auto origin = drag.id == clip.id && drag.edge < 0 ? drag.originalStart : start;
                        for (const auto& line : overview->second.lines) {
                            // Keep source timing in double, intersect first, then convert
                            // to local pixels. A 48-hour clip never reaches the rasterizer.
                            const auto noteStart = origin + double(line.getX()) * clip.duration;
                            const auto noteEnd = noteStart + double(line.getWidth()) * clip.duration;
                            if (noteEnd <= viewStart || noteStart >= viewStart + visibleDuration()) continue;
                            const auto noteX = timeX(std::max(noteStart, viewStart));
                            const auto right = timeX(std::min(noteEnd, viewStart + visibleDuration()));
                            const auto noteY = waveArea.getBottom() - 3.0f - line.getY() * (waveArea.getHeight() - 5);
                            g.fillRect(noteX, noteY, juce::jmax(1.0f, right - noteX), 2.0f);
                        }
                    }
                } else if (owner.trackWaveformReady(clip.id)) {
                    const double previewOffset = clip.sourceOffset + (drag.id == clip.id && drag.edge == -1 ? drag.previewStart - drag.originalStart : 0.0);
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
                    const auto caption = (moving ? "edit: " : "") + clipName
                        + " @ " + (bars ? tickText(start) : juce::String(start, 3) + " s")
                        + (moving ? "  len " + juce::String(drag.duration * state.bpm / 60.0, 3) + " beats" : "");
                    g.drawFittedText(caption, area.toNearestInt().reduced(5, 1).withHeight(16), juce::Justification::centredLeft, 1);
                }
                g.setColour(selectedClip ? ink : (silent ? rule : secondary));
                g.drawRect(area, selectedClip ? 1.8f : 0.7f);
                if (selectedClip && area.getWidth() > 20) {
                    g.drawVerticalLine(juce::roundToInt(area.getX() + 4), area.getY() + 24, area.getBottom() - 8);
                    g.drawVerticalLine(juce::roundToInt(area.getRight() - 4), area.getY() + 24, area.getBottom() - 8);
                    if (clip.kind == "audio" && area.getWidth() > 32) {
                        const auto left = fadeHandleX(clip, true), right = fadeHandleX(clip, false);
                        g.drawLine(area.getX(), area.getBottom(), left, area.getY() + 20, 1.0f);
                        g.drawLine(right, area.getY() + 20, area.getRight(), area.getBottom(), 1.0f);
                        g.fillRect(left - 3, area.getY() + 17, 6.0f, 6.0f); g.fillRect(right - 3, area.getY() + 17, 6.0f, 6.0f);
                    }
                }
            };
            for (const auto& clip : track.clips) if (clip.id != state.selectedClipId) paintClip(clip);
            for (const auto& clip : track.clips) if (clip.id == state.selectedClipId) paintClip(clip);
        }
        if (!rangeSelection.isEmpty()) {
            const auto x = timeX(juce::jlimit(viewStart, viewStart + visibleDuration(), rangeSelection.getStart()));
            const auto right = timeX(juce::jlimit(viewStart, viewStart + visibleDuration(), rangeSelection.getEnd()));
            juce::Graphics::ScopedSaveState clipped(g); g.reduceClipRegion(labelWidth(), dirty.getY(), plotWidth(), dirty.getHeight());
            g.setColour(ink.withAlpha(0.055f)); g.fillRect(x, float(dirty.getY()), right - x, float(dirty.getHeight()));
        }
        if (marquee) { g.setColour(ink.withAlpha(0.07f)); g.fillRect(marqueeArea); g.setColour(ink); g.drawRect(marqueeArea, 1.0f); }
        if (drag.moved && drag.edge == 0 && drag.targetTrackIndex != drag.trackIndex) {
            const auto xx = timeX(juce::jlimit(viewStart, viewStart + visibleDuration(), drag.previewStart));
            const auto ww = timeX(juce::jlimit(viewStart, viewStart + visibleDuration(), drag.previewStart + drag.duration)) - xx;
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
    std::shared_ptr<const WaveformDetail> detailFor(const std::shared_ptr<Peaks>& peaks, double start, double end)
    {
        // Only 16 resident windows (8 MiB stereo float), plus one worker window.
        // LRU eviction invalidates an in-flight publication under a short lock.
        if (end <= start || peaks->sampleRate <= 0 || (end - start) * peaks->sampleRate > detailFrames / 2
            || peaks->detailFailed.load()) return {};
        detailLru.erase(std::remove_if(detailLru.begin(), detailLru.end(), [&](const auto& weak) {
            const auto item = weak.lock(); return item == nullptr || item == peaks;
        }), detailLru.end());
        detailLru.push_back(peaks);
        while (detailLru.size() > detailWindowLimit) {
            if (const auto old = detailLru.front().lock()) {
                const juce::ScopedLock guard(old->detailLock); ++old->detailGeneration; old->detail.reset();
            }
            detailLru.erase(detailLru.begin());
        }
        std::uint64_t generation;
        {
            const juce::ScopedLock guard(peaks->detailLock);
            if (peaks->detail != nullptr && peaks->detail->covers(start, end)) return peaks->detail;
            generation = peaks->detailGeneration;
        }
        if (!peaks->detailPending.exchange(true)) {
            constexpr juce::int64 quantum = detailFrames / 4;
            const auto requested = juce::jmax<juce::int64>(0, juce::int64(std::floor(start * peaks->sampleRate)) - quantum);
            const auto first = (requested / quantum) * quantum;
            detailPool.addJob(new DetailJob(peaks, first, generation), true);
        }
        return {};
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
    juce::ThreadPool detailPool { 1 };
    std::vector<std::weak_ptr<Peaks>> detailLru;
    std::map<juce::String, std::shared_ptr<Peaks>> entries;
    std::map<juce::String, MidiOverview> midiOverviews;
    EngineSession::Snapshot state;
    struct Drag {
        juce::String id, projectId;
        std::uint64_t revision = 0;
        double originalStart = 0.0, previewStart = 0.0, duration = 0.0, secondsPerPixel = 0.0;
        double originalDuration = 0.0, sourceOffset = 0.0, sourceDuration = 0.0;
        double groupStart = 0.0, groupEnd = 0.0;
        double fadeIn = 0, fadeOut = 0, originalFadeIn = 0, originalFadeOut = 0;
        juce::StringArray clipIds;
        int edge = 0, trackIndex = 0, targetTrackIndex = 0;
        float downX = 0.0f, downY = 0.0f;
        bool moved = false, midi = false;
    } drag;
    std::vector<double> dragEdges;
    juce::Result lastMoveResult = juce::Result::ok();
    Canvas canvas;
    std::vector<std::unique_ptr<TrackControls>> headers;
    juce::Viewport viewport;
    juce::ScrollBar horizontal;
    double zoom = 1.0, viewStart = 0.0;
    double extendedTimelineEnd = 0.0;
    int rowHeight = 104;
    double gridBeats = 0.25;
    bool bars = false;
    int rulerMode = 1;
    bool snapEnabled = true, adaptiveGrid = false, follow = false, followSuspended = false;
    bool marquee = false;
    juce::Point<float> marqueeOrigin;
    juce::Rectangle<float> marqueeArea;
    juce::StringArray marqueeBase;
    juce::Range<double> rangeSelection;
    int rulerDrag = 0; // 1 seek, 2 time selection, 3 loop start, 4 loop end, 5 move loop
    double rulerDownTime = 0, loopBeforeStart = 0, loopBeforeEnd = 0, loopPreviewStart = 0, loopPreviewEnd = 0;
    std::uint64_t rulerRevision = 0;
    juce::StringArray selection;
    juce::String explicitTrackSelection;
    juce::uint32 lastSourceCheck = 0;
    bool forceSourceCheck = true, dropActive = false, selecting = false;
};

ArrangementView::ArrangementView(EngineSession& session) : impl(std::make_unique<Impl>(*this, session))
{
    setWantsKeyboardFocus(true);
    setTitle("Multitrack audio arrangement");
    setDescription("Click to locate, drag empty space to select clips. Shift-drag ruler selects time; Ctrl+L loops selection. Drag lower ruler loop handles. Control plus wheel zooms; Shift plus wheel scrolls.");
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
    const auto previousHorizon = p.projectDuration();
    const auto previousVisible = p.visibleDuration();
    const bool playbackStarted = next.playing && !p.state.playing;
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
    if (projectChanged) p.extendedTimelineEnd = 0;
    if (next.position > p.projectDuration()) {
        const auto bar = time::beatsPerBar(next.numerator, next.denominator) * 60.0 / next.bpm;
        p.extendedTimelineEnd = std::min(172800.0, std::ceil(next.position / bar) * bar + 4.0 * bar);
    }
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
    if (projectChanged) { p.selection.clear(); p.rangeSelection = {}; p.rulerDrag = 0; p.followSuspended = false; }
    if (projectChanged || next.selectedTrackId != p.explicitTrackSelection) p.explicitTrackSelection.clear();
    for (int i = p.selection.size(); --i >= 0;) {
        bool exists = false;
        for (const auto& track : next.tracks) for (const auto& clip : track.clips) if (clip.id == p.selection[i]) exists = true;
        if (!exists) p.selection.remove(i);
    }
    if (!p.selecting && p.explicitTrackSelection.isEmpty() && (primaryClipChanged || projectChanged) && next.selectedClipId.isNotEmpty()) p.selection = { next.selectedClipId };
    p.updatePeaks(sourcesChanged || p.forceSourceCheck);
    p.forceSourceCheck = false;
    if (projectChanged) { p.zoom = 1.0; p.viewStart = 0.0; p.viewport.setViewPosition(0, 0); }
    if (!projectChanged && p.zoom > 1.0 && p.projectDuration() != previousHorizon)
        p.zoom = juce::jlimit(1.0, p.maximumZoom(), p.projectDuration() / previousVisible);
    if (contentChanged || lengthChanged || p.projectDuration() != previousHorizon) p.layout();
    if (playbackStarted) p.followSuspended = false;
    if (p.follow && !p.followSuspended && next.playing && p.drag.id.isEmpty() && !p.marquee && p.rulerDrag == 0
        && (next.position < p.viewStart || next.position > p.viewStart + p.visibleDuration() * 0.9)) {
        p.viewStart = juce::jmax(0.0, next.position - p.visibleDuration() * 0.15); p.syncScroll();
    }
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
void ArrangementView::fitToProject() { impl->followSuspended = true; impl->zoom = 1.0; impl->viewStart = 0.0; impl->syncScroll(); }
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
juce::String ArrangementView::explicitSelectedTrackId() const { return impl->explicitTrackSelection; }
void ArrangementView::setGrid(double beats, bool bars) { setGridBeats(beats > 0 ? beats : impl->gridBeats); setSnapEnabled(beats > 0); setRulerMode(bars ? 0 : 1); }
void ArrangementView::setRulerMode(int mode) { impl->rulerMode = juce::jlimit(0, 2, mode); impl->bars = impl->rulerMode != 1; repaint(); }
void ArrangementView::setGridBeats(double beats) { if (std::isfinite(beats) && beats > 0) impl->gridBeats = beats; impl->canvas.repaint(); repaint(); }
void ArrangementView::setSnapEnabled(bool enabled) { impl->snapEnabled = enabled; impl->canvas.repaint(); repaint(); }
void ArrangementView::setAdaptiveGrid(bool enabled) { impl->adaptiveGrid = enabled; impl->canvas.repaint(); repaint(); }
void ArrangementView::setFollowPlayhead(bool enabled) { impl->follow = enabled; impl->followSuspended = false; }
void ArrangementView::selectClipIds(const juce::StringArray& ids)
{
    auto& p = *impl; p.explicitTrackSelection.clear(); p.selection = ids; p.rangeSelection = {}; p.selecting = true;
    if (!ids.isEmpty()) p.engine.selectClip(ids[0]); p.notifyState(); p.selecting = false; p.canvas.repaint();
}
juce::Range<double> ArrangementView::selectedTimeRange() const
{
    const auto& p = *impl;
    if (!p.rangeSelection.isEmpty()) return p.rangeSelection;
    double start = 172800, end = 0;
    for (const auto& track : p.state.tracks) for (const auto& clip : track.clips) if (p.selection.contains(clip.id)) {
        start = juce::jmin(start, clip.timelineStart); end = juce::jmax(end, clip.timelineStart + clip.duration);
    }
    return end > start ? juce::Range<double>(start, end) : juce::Range<double>();
}
juce::Range<double> ArrangementView::explicitSelectedTimeRange() const { return impl->rangeSelection; }
juce::Result ArrangementView::loopSelection()
{
    const auto range = selectedTimeRange();
    if (range.isEmpty()) return juce::Result::fail("Select clips or Shift-drag a time range in the ruler first.");
    auto* values = new juce::DynamicObject; values->setProperty("start_seconds", range.getStart()); values->setProperty("end_seconds", range.getEnd());
    auto* rangeCommand = new juce::DynamicObject; rangeCommand->setProperty("command", "set_loop_range"); rangeCommand->setProperty("args", juce::var(values));
    auto* enabled = new juce::DynamicObject; enabled->setProperty("enabled", true);
    auto* loopCommand = new juce::DynamicObject; loopCommand->setProperty("command", "set_loop"); loopCommand->setProperty("args", juce::var(enabled));
    auto* batch = new juce::DynamicObject; batch->setProperty("commands", juce::Array<juce::var>{juce::var(rangeCommand), juce::var(loopCommand)});
    auto result = impl->engine.execute("batch", juce::var(batch), impl->state.revision); impl->notifyState(); return result;
}
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
    if (peaks != nullptr && peaks->status.load(std::memory_order_acquire) == PeakStatus::ready && end > start) {
        if (const auto detail = impl->detailFor(peaks, start, end)) detail->draw(g, area, start, end, verticalZoom);
        else peaks->thumbnail.drawChannels(g, area, start, end, verticalZoom);
    }
}
void ArrangementView::resized() { impl->layout(); }
void ArrangementView::paint(juce::Graphics& g)
{
    auto& p = *impl;
    g.fillAll(paper);
    g.setColour(secondary); g.setFont(mono(11.0f));
    g.drawText(p.dropActive ? "drop audio / MIDI" : juce::String(p.bars ? "bars / " : "seconds / ") + juce::String(p.zoom, 0) + "x",
               10, 0, p.labelWidth() - 15, 24, juce::Justification::centredLeft);
    const auto gridDenominator = juce::roundToInt(4.0 / p.effectiveGrid());
    const auto gridName = gridDenominator >= 1 ? "1/" + juce::String(gridDenominator) : juce::String(p.effectiveGrid() / 4.0, 0) + " whole";
    g.drawText((p.snapEnabled ? (p.adaptiveGrid ? "auto " : "snap ") : "off ") + gridName,
        10, 22, p.labelWidth() - 15, 18, juce::Justification::centredLeft);
    p.eachGrid([&](double, float x, int level) {
        g.setColour(level == 2 ? secondary : rule);
        g.drawLine(x, level == 2 ? 35.0f : level == 1 ? 41.0f : 47.0f, x, float(rulerHeight));
    });
    int previousLabelRight = p.labelWidth() - 8;
    p.eachTick([&](double seconds, float x) {
        g.setColour(secondary); g.setFont(mono(11.0f));
        const auto width = p.bars ? 86 : 112;
        const auto left = juce::jlimit(p.labelWidth(), p.canvas.getWidth() - width, juce::roundToInt(x) - width / 2);
        if (left >= previousLabelRight + 8) {
            g.drawText(p.tickText(seconds), left, 0, width, 24, juce::Justification::centred);
            if (p.rulerMode == 2) g.drawText(timeText(seconds), left, 20, width, 17, juce::Justification::centred);
            previousLabelRight = left + width;
        }
        g.setColour(rule); g.drawLine(x, 38.0f, x, static_cast<float>(rulerHeight));
    });
    g.setColour(rule); g.drawHorizontalLine(rulerHeight - 1, 0.0f, static_cast<float>(getWidth()));
    const double loopStart = p.rulerDrag >= 3 ? p.loopPreviewStart : p.state.loopStart;
    const double loopEnd = p.rulerDrag >= 3 ? p.loopPreviewEnd : p.state.loopEnd;
    if (loopEnd > loopStart) {
        const auto left = juce::jlimit(float(p.labelWidth()), float(p.labelWidth() + p.plotWidth()), p.timeX(loopStart));
        const auto right = juce::jlimit(float(p.labelWidth()), float(p.labelWidth() + p.plotWidth()), p.timeX(loopEnd));
        if (right > left) {
            g.setColour(p.state.looping ? ink : secondary.withAlpha(0.45f));
            g.drawLine(left, 47, right, 47, 2);
            g.drawLine(left, 41, left, 53, 2); g.drawLine(right, 41, right, 53, 2);
        }
    }
    const auto head = p.timeX(p.state.position);
    if (!p.state.tracks.empty() && head >= p.labelWidth() && head <= p.labelWidth() + p.plotWidth()) {
        g.setColour(ink);
        juce::Path marker;
        marker.addTriangle(head - 4.0f, 34.0f, head + 4.0f, 34.0f, head, 41.0f);
        g.fillPath(marker);
    }
}
void ArrangementView::mouseDown(const juce::MouseEvent& e)
{
    if (!isEnabled() || e.position.x < impl->labelWidth()) return;
    if (isShowing()) grabKeyboardFocus();
    auto& p = *impl; p.cancelDrag(); p.followSuspended = true; p.explicitTrackSelection.clear();
    p.rulerRevision = p.state.revision; p.rulerDownTime = p.snapTime(p.timeAt(e.position.x), e.mods.isAltDown());
    p.loopBeforeStart = p.loopPreviewStart = p.state.loopStart; p.loopBeforeEnd = p.loopPreviewEnd = p.state.loopEnd;
    p.rulerDrag = 1;
    if (e.mods.isShiftDown()) { p.rulerDrag = 2; p.rangeSelection = {}; }
    else if (e.position.y >= 40 && p.state.loopEnd > p.state.loopStart) {
        if (std::abs(e.position.x - p.timeX(p.state.loopStart)) <= 7) p.rulerDrag = 3;
        else if (std::abs(e.position.x - p.timeX(p.state.loopEnd)) <= 7) p.rulerDrag = 4;
        else if (e.position.x >= p.timeX(p.state.loopStart) && e.position.x <= p.timeX(p.state.loopEnd)) p.rulerDrag = 5;
    }
    if (p.rulerDrag == 1) { p.rangeSelection = {}; p.seekAt(e.position.x); }
}
void ArrangementView::mouseDrag(const juce::MouseEvent& e)
{
    auto& p = *impl; if (p.rulerDrag == 0) return;
    const double at = p.snapTime(p.timeAt(e.position.x), e.mods.isAltDown());
    if (p.rulerDrag == 1) p.seekAt(e.position.x);
    else if (p.rulerDrag == 2) {
        p.rangeSelection = {std::min(at, p.rulerDownTime), std::max(at, p.rulerDownTime)};
        p.selection.clear();
        for (const auto& track : p.state.tracks) for (const auto& clip : track.clips)
            if (clip.timelineStart < p.rangeSelection.getEnd() && clip.timelineStart + clip.duration > p.rangeSelection.getStart()) p.selection.add(clip.id);
    } else if (p.rulerDrag == 3) p.loopPreviewStart = juce::jlimit(0.0, p.loopBeforeEnd - time::minimumEditSpanSeconds, at);
    else if (p.rulerDrag == 4) p.loopPreviewEnd = juce::jlimit(p.loopBeforeStart + time::minimumEditSpanSeconds, 172800.0, at);
    else {
        const auto delta = juce::jlimit(-p.loopBeforeStart, 172800.0 - p.loopBeforeEnd, at - p.rulerDownTime);
        p.loopPreviewStart = p.loopBeforeStart + delta; p.loopPreviewEnd = p.loopBeforeEnd + delta;
    }
    p.canvas.repaint(); repaint();
}
void ArrangementView::mouseUp(const juce::MouseEvent&)
{
    auto& p = *impl; const auto mode = p.rulerDrag; p.rulerDrag = 0;
    if (mode >= 3 && (p.loopPreviewStart != p.loopBeforeStart || p.loopPreviewEnd != p.loopBeforeEnd)) {
        auto* args = new juce::DynamicObject; args->setProperty("start_seconds", p.loopPreviewStart); args->setProperty("end_seconds", p.loopPreviewEnd);
        auto result = p.engine.execute("set_loop_range", juce::var(args), p.rulerRevision);
        if (onEditResult) onEditResult(result); p.notifyState();
    }
    repaint();
}
void ArrangementView::mouseWheelMove(const juce::MouseEvent& e, const juce::MouseWheelDetails& wheel) { impl->wheel(e.position.x, e.mods, wheel); }
bool ArrangementView::keyPressed(const juce::KeyPress& key)
{
    if (key == juce::KeyPress::escapeKey && cancelClipDrag()) return true;
    const auto mods = key.getModifiers();
    if ((mods.isCtrlDown() || mods.isCommandDown()) && key.getKeyCode() == 'L') {
        const auto result = loopSelection(); if (onEditResult) onEditResult(result); return true;
    }
    if (key.getModifiers().isAnyModifierKeyDown()) return false;
    const auto& state = impl->state;
    if (key == juce::KeyPress::homeKey) impl->engine.seek(0.0);
    else if (key == juce::KeyPress::endKey) impl->engine.seek(state.duration);
    else if (key == juce::KeyPress::leftKey) impl->engine.seek(juce::jmax(0.0, state.position - impl->effectiveGrid() * 60.0 / state.bpm));
    else if (key == juce::KeyPress::rightKey) impl->engine.seek(juce::jmin(172800.0, state.position + impl->effectiveGrid() * 60.0 / state.bpm));
    else return false;
    impl->notifyState();
    return true;
}
void ArrangementView::focusGained(FocusChangeType) { impl->canvas.repaint(); repaint(); if (onFocus) onFocus(); }
void ArrangementView::focusLost(FocusChangeType) { impl->canvas.repaint(); repaint(); }
void ArrangementView::focusOfChildComponentChanged(FocusChangeType) { impl->canvas.repaint(); repaint(); if (hasKeyboardFocus(true) && onFocus) onFocus(); }

juce::Result ArrangementView::runSmokeTest(juce::DynamicObject& report, const juce::File& outputDirectory)
{
    auto& p = *impl;
    const auto initial = p.engine.snapshot();
    const auto originalBounds = getBounds();
    const auto check = [](bool success, const char* message) { return success ? juce::Result::ok() : juce::Result::fail(message); };
    if (initial.tracks.size() < 2 || initial.duration <= 0.0) return juce::Result::fail("Arrangement smoke requires at least two real imported tracks.");
    fitToProject();
    const double initialHorizon = p.projectDuration();
    report.setProperty("track_rows", static_cast<int>(p.state.tracks.size()));
    report.setProperty("waveforms_complete", waveformsReady());
    if (!waveformsReady()) return juce::Result::fail("Arrangement waveform peaks have not completed successfully.");
    auto result = check(p.canvas.getHeight() >= static_cast<int>(initial.tracks.size()) * rowHeight, "Track canvas does not contain all real rows.");
    if (result.failed()) return result;
    juce::Array<juce::var> widths;
    for (std::size_t row = 0; row < initial.tracks.size(); ++row) for (const auto& clip : initial.tracks[row].clips) {
        const auto actual = p.clipArea(row, clip);
        const auto expectedWidth = clip.duration / initialHorizon * p.plotWidth();
        const auto expectedX = p.labelWidth() + clip.timelineStart / initialHorizon * p.plotWidth();
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
    const auto event = [&](float x, float y, bool dragging = false, int modifiers = 0) {
        const auto now = juce::Time::getCurrentTime();
        return juce::MouseEvent(juce::Desktop::getInstance().getMainMouseSource(), { x, y },
            juce::ModifierKeys(juce::ModifierKeys::leftButtonModifier | modifiers), 1.0f, 0.0f, 0.0f, 0.0f, 0.0f,
            &p.canvas, &p.canvas, now, { x, y }, now, 1, dragging);
    };
    const auto lastRow = static_cast<int>(initial.tracks.size()) - 1;
    const auto headerRevision = p.engine.snapshot().revision;
    p.canvas.mouseDown(event(20.0f, static_cast<float>(lastRow * rowHeight + 30)));
    if (p.engine.snapshot().selectedTrackId != initial.tracks.back().id) return juce::Result::fail("Clicking an arrangement row did not select its real track.");
    update(p.engine.snapshot()); // A periodic refresh must not restore the first clip selection.
    if (explicitSelectedTrackId() != initial.tracks.back().id || !selectedClipIds().isEmpty()
        || !explicitSelectedTimeRange().isEmpty() || p.engine.snapshot().revision != headerRevision)
        return juce::Result::fail("Track header selection did not remain track-only across refresh.");
    if (!initial.tracks.back().clips.empty()) {
        const auto clipId = initial.tracks.back().clips.front().id;
        if (p.engine.snapshot().selectedClipId != clipId)
            return juce::Result::fail("Track header selection changed the engine active-clip semantics.");
        selectClipIds(juce::StringArray{clipId});
        if (explicitSelectedTrackId().isNotEmpty() || !selectedClipIds().contains(clipId))
            return juce::Result::fail("Explicit clip selection did not leave track-only mode.");
        p.canvas.mouseDown(event(20.0f, static_cast<float>(lastRow * rowHeight + 30)));
    }
    report.setProperty("track_header_scope_and_clip_restore", true);
    const auto halfX = static_cast<float>(p.labelWidth() + p.plotWidth() * 0.5);
    p.canvas.mouseDown(event(halfX, static_cast<float>(lastRow * rowHeight + 5)));
    if (explicitSelectedTrackId().isNotEmpty()) return juce::Result::fail("Timeline selection did not leave track-only mode.");
    if (std::abs(p.engine.snapshot().position - initialHorizon * 0.5) > 0.002) return juce::Result::fail("Timeline click did not seek to the shared time coordinate including trailing space.");
    // Empty-space dragging now selects clips; transport scrubbing stays in the ruler.
    p.canvas.mouseUp(event(halfX, static_cast<float>(lastRow * rowHeight + 5)));
    mouseDown(event(halfX, 10.0f));
    mouseDrag(event(static_cast<float>(p.labelWidth() + p.plotWidth() + 100), 10.0f, true));
    if (std::abs(p.engine.snapshot().position - initialHorizon) > 0.002) return juce::Result::fail("Timeline drag did not clamp at the displayed horizon.");
    mouseDrag(event(-100.0f, 10.0f, true));
    mouseUp(event(-100.0f, 10.0f));
    if (p.engine.snapshot().position > 0.002) return juce::Result::fail("Timeline drag did not clamp at zero.");
    report.setProperty("selection_and_seek_events", true);
    p.setZoom(p.maximumZoom() * 2.0, 0.5);
    if (zoomFactor() != p.maximumZoom()) return juce::Result::fail("Zoom maximum did not stop at the finest visible editing grid.");
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
    p.horizontal.setCurrentRangeStart(initialHorizon, juce::sendNotificationSync);
    if (std::abs(p.viewStart + p.visibleDuration() - initialHorizon) > 0.00001) return juce::Result::fail("Horizontal scroll did not reach the final time range.");
    for (int n = 0; n < 64; ++n) zoomOut();
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

    // Display units and fixed grid precision must not silently change each other.
    const auto priorGrid = p.gridBeats; const auto priorSnap = p.snapEnabled;
    const auto priorMode = p.rulerMode; const auto priorAdaptive = p.adaptiveGrid;
    setGridBeats(0.25); setSnapEnabled(true); setAdaptiveGrid(false); setRulerMode(0);
    const auto testTime = 0.37 * 60.0 / p.state.bpm;
    const auto snapped = p.snapTime(testTime, false);
    setRulerMode(1);
    if (!p.snapEnabled || p.snapTime(testTime, false) != snapped || p.snapTime(testTime, true) != testTime
        || std::abs(snapped * p.state.bpm / 60.0 - 0.25) > 1e-9)
        return juce::Result::fail("Ruler units changed snapping or Alt did not preserve the raw time.");
    zoomIn(); const auto fixedBefore = p.effectiveGrid(); zoomIn();
    if (p.effectiveGrid() != fixedBefore) return juce::Result::fail("Fixed snap precision changed on zoom.");
    if (time::beatsPerBar(6, 8) != 3.0 || time::beatsPerBar(3, 4) != 3.0)
        return juce::Result::fail("Editing bar length ignores the meter denominator.");
    const auto savedBpm = p.state.bpm; const auto savedNumerator = p.state.numerator, savedDenominator = p.state.denominator;
    const auto savedHorizon = p.extendedTimelineEnd;
    p.state.bpm = 120; p.state.numerator = 4; p.state.denominator = 4; p.bars = true;
    p.extendedTimelineEnd = 172800;
    const std::array<std::pair<double, const char*>, 4> rulerCases {{{8.0, "1"}, {0.75, "1.1"}, {0.2, "1.1.1"}, {0.00001, "1.1.1"}}};
    for (const auto& [targetStep, expected] : rulerCases) {
        const auto visibleBeats = targetStep * p.plotWidth() / 72.0;
        p.setZoom(p.projectDuration() / (visibleBeats * 0.5), 0.0); p.viewStart = 0;
        if (p.tickText(0) != expected) return juce::Result::fail("Musical ruler did not follow bar / beat / quarter-beat zoom tiers.");
    }
    p.state.numerator = 6; p.state.denominator = 8;
    const bool sixEightTicks = p.tickText(0.0625) == "1.1.2";
    p.state.numerator = 3;
    const bool threeEightTicks = p.tickText(0.8125) == "2.1.2";
    if (!sixEightTicks || !threeEightTicks) return juce::Result::fail("Three-tier ruler ignored the meter denominator.");
    report.setProperty("ruler_three_zoom_tiers_and_meter", true);

    // Real 48-hour coordinates, including the fastest supported tempo. Work is
    // bounded by screen width, never project length divided by the fixed grid.
    p.state.bpm = 300; p.state.numerator = 4; p.state.denominator = 4;
    setGridBeats(time::minimumEditGridBeats); setAdaptiveGrid(false);
    p.setZoom(p.maximumZoom() * 2, 0.0); p.viewStart = p.projectDuration() - p.visibleDuration(); p.syncScroll();
    const auto gridSeconds = time::minimumEditGridBeats * 60.0 / p.state.bpm;
    const auto centre = p.viewStart + p.visibleDuration() * 0.5;
    const auto coordinateError = std::abs(p.timeAt(p.timeX(centre)) - centre);
    const auto gridPixels = gridSeconds * p.plotWidth() / p.visibleDuration();
    if (coordinateError > gridSeconds * 0.001 || std::abs(gridPixels - 16.0) > 0.001
        || p.canvas.getWidth() > getWidth())
        return juce::Result::fail("Finest-grid coordinates lost precision or created a large horizontal canvas.");
    p.viewStart = 172700.0; p.syncScroll();
    const auto anchorBefore = p.viewStart + p.visibleDuration() * 0.37;
    p.setZoom(p.zoom * 0.5, 0.37); p.setZoom(p.zoom * 2.0, 0.37);
    if (std::abs(p.viewStart + p.visibleDuration() * 0.37 - anchorBefore) > gridSeconds * 0.001)
        return juce::Result::fail("Deep zoom moved the mouse anchor.");
    int worstGridLines = 0; double coordinateChecksum = 0;
    std::vector<double> gridTimings;
    for (int iteration = 0; iteration < 120; ++iteration) {
        const auto began = juce::Time::getMillisecondCounterHiRes();
        int count = 0;
        p.eachGrid([&](double seconds, float x, int) { ++count; coordinateChecksum += seconds + x; });
        gridTimings.push_back(juce::Time::getMillisecondCounterHiRes() - began);
        worstGridLines = std::max(worstGridLines, count);
    }
    if (worstGridLines > p.plotWidth() / 4 + 6 || coordinateChecksum <= 0)
        return juce::Result::fail("Deep grid iteration exceeded the viewport work bound.");
    std::sort(gridTimings.begin(), gridTimings.end());
    report.setProperty("deep_zoom_48h_300bpm_grid_pixels", gridPixels);
    report.setProperty("deep_zoom_coordinate_error_seconds", coordinateError);
    report.setProperty("deep_zoom_anchor_preserved", true);
    report.setProperty("deep_zoom_grid_line_bound", worstGridLines);
    report.setProperty("deep_zoom_grid_iteration_count", int(gridTimings.size()));
    report.setProperty("deep_zoom_grid_iteration_p50_ms", gridTimings[60]);
    report.setProperty("deep_zoom_grid_iteration_p95_ms", gridTimings[114]);
    report.setProperty("deep_zoom_grid_iteration_worst_ms", gridTimings.back());
    report.setProperty("deep_zoom_canvas_width", p.canvas.getWidth());
    // Pixel evidence exercises the same line painter used by every track.
    juce::Image solid(juce::Image::RGB, 64, 96, true), dashed(juce::Image::RGB, 64, 96, true);
    {
        juce::Graphics a(solid), b(dashed); a.fillAll(paper); b.fillAll(paper);
        setSnapEnabled(true); p.drawGridLine(a, 32, 0, 96, 2);
        setSnapEnabled(false); p.drawGridLine(b, 32, 0, 96, 2);
    }
    int solidPixels = 0, dashedPixels = 0;
    for (int y = 1; y < 95; ++y) {
        if (solid.getPixelAt(32, y) != paper) ++solidPixels;
        if (dashed.getPixelAt(32, y) != paper) ++dashedPixels;
    }
    if (solidPixels < 90 || dashedPixels < 30 || dashedPixels > 65)
        return juce::Result::fail("Snap solid/dashed grid feedback did not appear in rendered pixels.");
    report.setProperty("snap_solid_pixel_rows", solidPixels); report.setProperty("snap_dashed_pixel_rows", dashedPixels);
    if (outputDirectory.isDirectory()) {
        const auto saveImage = [&](const juce::Image& image, const juce::String& name) {
            auto stream = outputDirectory.getChildFile(name).createOutputStream();
            return stream != nullptr && juce::PNGImageFormat().writeImageToStream(image, *stream);
        };
        if (!saveImage(solid, "arrangement-grid-solid.png") || !saveImage(dashed, "arrangement-grid-dashed.png"))
            return juce::Result::fail("Could not save arrangement grid visual evidence.");
    }
    p.state.bpm = savedBpm; p.state.numerator = savedNumerator; p.state.denominator = savedDenominator;
    p.extendedTimelineEnd = savedHorizon; p.bars = false; setGridBeats(0.25); setSnapEnabled(true);
    fitToProject(); p.viewStart = 0;
    // At a close zoom, every drawn subdivision lies on the same lattice used by snap.
    for (int i = 0; i < 5; ++i) zoomIn();
    bool gridMatches = true;
    p.eachGrid([&](double t, float, int) { if (std::abs(p.snapTime(t, false) - t) > 1e-8) gridMatches = false; });
    if (!gridMatches) return juce::Result::fail("Drawn subdivisions and edit snap locations disagree.");
    fitToProject(); setGridBeats(priorGrid); setSnapEnabled(priorSnap); setAdaptiveGrid(priorAdaptive); setRulerMode(priorMode);
    report.setProperty("ruler_units_independent_of_snap", true);
    report.setProperty("fixed_grid_and_rendered_subdivisions", true);

    // Rectangle selection changes no musical data and can include several rows.
    const auto beforeRectangle = p.engine.snapshot();
    p.canvas.mouseDown(event(float(p.labelWidth() + 1), 2.0f));
    p.canvas.mouseDrag(event(float(p.labelWidth() + p.plotWidth()), float(lastRow * rowHeight + rowHeight - 2), true));
    p.canvas.mouseUp(event(float(p.labelWidth() + p.plotWidth()), float(lastRow * rowHeight + rowHeight - 2)));
    int expectedSelected = 0; for (const auto& track : p.state.tracks) expectedSelected += int(track.clips.size());
    if (p.selection.size() != expectedSelected || p.engine.snapshot().revision != beforeRectangle.revision)
        return juce::Result::fail("Rectangle selection missed clips or edited the project.");
    report.setProperty("rectangle_multitrack_selection", true);
    const auto loopBefore = p.engine.snapshot();
    const auto expectedLoop = selectedTimeRange();
    if (auto loopResult = loopSelection(); loopResult.failed()) return loopResult;
    const auto loopAfter = p.engine.snapshot();
    if (!loopAfter.looping || std::abs(loopAfter.loopStart - expectedLoop.getStart()) > 1e-8 || std::abs(loopAfter.loopEnd - expectedLoop.getEnd()) > 1e-8
        || loopAfter.revision != loopBefore.revision + 1)
        return juce::Result::fail("Loop selection did not apply one transaction to the complete selected range.");
    if (auto undone = p.engine.undo(loopAfter.revision); undone.failed()) return undone;
    p.notifyState();
    if (p.engine.snapshot().looping != loopBefore.looping || p.engine.snapshot().loopStart != loopBefore.loopStart
        || p.engine.snapshot().loopEnd != loopBefore.loopEnd)
        return juce::Result::fail("Loop selection did not restore its complete state with one Undo.");
    report.setProperty("loop_selection_atomic_undo", true);
    const auto rangeBefore = p.engine.snapshot();
    setSnapEnabled(false);
    mouseDown(event(float(p.labelWidth() + p.plotWidth() * 0.25), 10, false, juce::ModifierKeys::shiftModifier));
    mouseDrag(event(float(p.labelWidth() + p.plotWidth() * 0.75), 10, true, juce::ModifierKeys::shiftModifier));
    mouseUp(event(float(p.labelWidth() + p.plotWidth() * 0.75), 10));
    if (std::abs(selectedTimeRange().getStart() - initialHorizon * 0.25) > 1e-5
        || std::abs(selectedTimeRange().getEnd() - initialHorizon * 0.75) > 1e-5
        || p.engine.snapshot().revision != rangeBefore.revision)
        return juce::Result::fail("Shift-drag ruler failed to select time without changing music.");
    p.rangeSelection = {}; setSnapEnabled(priorSnap);
    report.setProperty("ruler_time_selection", true);

    const auto followBefore = p.engine.snapshot();
    fitToProject(); zoomIn(); zoomIn(); setFollowPlayhead(true);
    auto simulatedPlayback = followBefore; simulatedPlayback.playing = true; simulatedPlayback.position = initialHorizon * 0.8;
    update(simulatedPlayback);
    if (p.viewStart <= 0) return juce::Result::fail("Follow did not reveal the simulated playhead.");
    p.horizontal.setCurrentRangeStart(0, juce::sendNotificationSync);
    simulatedPlayback.position = initialHorizon * 0.9; update(simulatedPlayback);
    if (p.viewStart != 0 || !p.followSuspended) return juce::Result::fail("Follow stole the manually scrolled viewport.");
    setFollowPlayhead(false); update(followBefore); fitToProject();
    report.setProperty("follow_pauses_for_manual_scroll", true);
    p.selection.clear();

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

    // A single finest-grid mouse gesture must commit and Undo, with no 1 ms floor.
    setGridBeats(time::minimumEditGridBeats); setAdaptiveGrid(false); setSnapEnabled(true);
    p.setZoom(p.maximumZoom(), 0.5);
    p.viewStart = std::max(0.0, original.timelineStart + original.duration * 0.5 - p.visibleDuration() * 0.5); p.syncScroll();
    const auto finePoint = p.clipArea(0, original).getCentre();
    const auto fineSeconds = time::minimumEditGridBeats * 60.0 / p.state.bpm;
    const auto fineDx = float(fineSeconds * p.plotWidth() / p.visibleDuration());
    const auto fineBefore = p.engine.snapshot();
    const auto expectedFineStart = p.snapTime(original.timelineStart + fineSeconds, false);
    p.canvas.mouseDown(event(finePoint.x, finePoint.y)); p.canvas.mouseDrag(event(finePoint.x + fineDx, finePoint.y, true));
    if (p.engine.snapshot().revision != fineBefore.revision) return juce::Result::fail("Deep drag changed the model before mouse-up.");
    p.canvas.mouseUp(event(finePoint.x + fineDx, finePoint.y));
    if (p.lastMoveResult.failed() || p.engine.snapshot().revision != fineBefore.revision + 1
        || std::abs(currentClip().timelineStart - expectedFineStart) > 1e-9)
        return juce::Result::fail("Finest-grid clip move did not commit at the precise snap location.");
    if (auto undone = p.engine.undo(p.engine.snapshot().revision); undone.failed()) return undone;
    p.notifyState();
    const auto clipEnd = original.timelineStart + original.duration;
    p.viewStart = std::max(0.0, clipEnd - p.visibleDuration() * 0.5); p.syncScroll();
    const auto edgeX = p.timeX(clipEnd) - 1.0f, edgeY = p.clipArea(0, original).getCentreY();
    const auto fineTrimBefore = p.engine.snapshot();
    p.canvas.mouseDown(event(edgeX, edgeY)); p.canvas.mouseDrag(event(edgeX - fineDx, edgeY, true));
    p.canvas.mouseUp(event(edgeX - fineDx, edgeY));
    const auto trimmedAmount = original.duration - currentClip().duration;
    if (p.lastMoveResult.failed() || p.engine.snapshot().revision != fineTrimBefore.revision + 1 || trimmedAmount <= 0 || trimmedAmount >= 0.001)
        return juce::Result::fail("Sub-millisecond clip edge trim failed at maximum zoom.");
    if (auto undone = p.engine.undo(p.engine.snapshot().revision); undone.failed()) return undone;
    p.notifyState();
    if (std::abs(currentClip().timelineStart - original.timelineStart) > 1e-9 || std::abs(currentClip().duration - original.duration) > 1e-9)
        return juce::Result::fail("Finest-grid drag and trim did not each restore with one Undo.");
    report.setProperty("finest_grid_move_trim_single_undo", true);
    report.setProperty("finest_grid_trim_seconds", trimmedAmount);
    if (outputDirectory.isDirectory()) {
        auto image = createComponentSnapshot(getLocalBounds());
        auto stream = outputDirectory.getChildFile("arrangement-deepzoom.png").createOutputStream();
        if (stream == nullptr || !juce::PNGImageFormat().writeImageToStream(image, *stream))
            return juce::Result::fail("Could not save deep-zoom arrangement evidence.");
    }
    setGridBeats(priorGrid); setSnapEnabled(priorSnap); setAdaptiveGrid(priorAdaptive);

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

    // Fade handles modify only fades and the complete gesture remains one Undo.
    if (original.kind == "audio" && original.duration - original.fadeIn - original.fadeOut > 0.02) {
        fitToProject(); p.engine.selectClip(original.id); p.notifyState();
        const auto area = p.clipArea(0, original);
        const auto fadeBefore = p.engine.snapshot();
        const float hx = p.fadeHandleX(original, true), hy = area.getY() + 20;
        const double available = original.duration - original.fadeIn - original.fadeOut;
        const float dx = float(available * 0.5 * p.plotWidth() / p.visibleDuration());
        if (dx >= 4) {
            p.canvas.mouseDown(event(hx, hy)); p.canvas.mouseDrag(event(hx + dx, hy, true));
            if (p.drag.edge != -2 || p.engine.snapshot().revision != fadeBefore.revision)
                return juce::Result::fail("Fade drag did not remain a fade-only preview.");
            p.canvas.mouseUp(event(hx + dx, hy));
            if (p.lastMoveResult.failed() || currentClip().fadeIn <= original.fadeIn || currentClip().timelineStart != original.timelineStart
                || std::abs(currentClip().duration - original.duration) > 1e-9)
                return juce::Result::fail("Fade handle changed clip timing or did not commit.");
            if (auto undone = p.engine.undo(p.engine.snapshot().revision); undone.failed()) return undone;
            p.notifyState();
            if (std::abs(currentClip().fadeIn - original.fadeIn) > 1e-9) return juce::Result::fail("One Undo did not restore the fade.");
            report.setProperty("fade_handle_preview_commit_undo", true);
        }
    }
    // A vertical group keeps track offsets and refuses an incomplete destination.
    fitToProject(); juce::StringArray groupIds;
    for (const auto& track : p.state.tracks) for (const auto& clip : track.clips) groupIds.add(clip.id);
    selectClipIds(groupIds);
    const auto groupBefore = p.engine.snapshot(); const auto groupPoint = p.clipArea(0, original).getCentre();
    p.canvas.mouseDown(event(groupPoint.x, groupPoint.y));
    p.canvas.mouseDrag(event(groupPoint.x, groupPoint.y + p.rowHeight, true));
    p.canvas.mouseUp(event(groupPoint.x, groupPoint.y + p.rowHeight));
    if (p.lastMoveResult.wasOk() || p.engine.snapshot().revision != groupBefore.revision)
        return juce::Result::fail("An out-of-bounds multi-track drag partially moved the group.");
    report.setProperty("group_cross_track_bounds_atomic", true);
    selectClipIds({original.id});
    const auto crossBefore = p.engine.snapshot(); const auto crossPoint = p.clipArea(0, original).getCentre();
    p.canvas.mouseDown(event(crossPoint.x, crossPoint.y));
    p.canvas.mouseDrag(event(crossPoint.x, crossPoint.y + p.rowHeight, true));
    p.canvas.mouseUp(event(crossPoint.x, crossPoint.y + p.rowHeight));
    if (p.lastMoveResult.failed()) return p.lastMoveResult;
    const auto crossAfter = p.engine.snapshot();
    bool movedAcross = false;
    for (const auto& clip : crossAfter.tracks[1].clips) if (clip.id == original.id) movedAcross = true;
    if (!movedAcross || crossAfter.revision != crossBefore.revision + 1)
        return juce::Result::fail("Cross-track drag failed to preserve the selected clip identity.");
    if (auto undone = p.engine.undo(p.engine.snapshot().revision); undone.failed()) return undone;
    p.notifyState();
    report.setProperty("cross_track_move_single_undo", true);
    {
        // A fresh, device-free session must allow placing the insert marker
        // before importing or creating the first clip.
        EngineSession emptySession(false);
        ArrangementView emptyView(emptySession);
        emptyView.setBounds(0, 0, 1000, 198);
        emptyView.update(emptySession.snapshot());
        auto& empty = *emptyView.impl;
        const auto beforeSeek = emptySession.snapshot();
        const auto horizon = empty.projectDuration();
        empty.seekAt(float(empty.labelWidth() + empty.plotWidth() * 0.5));
        const auto afterSeek = emptySession.snapshot();
        if (horizon < 16.0 || std::abs(afterSeek.position - horizon * 0.5) > 0.002 || afterSeek.duration != 0.0
            || afterSeek.revision != beforeSeek.revision || afterSeek.dirty != beforeSeek.dirty)
            return juce::Result::fail("Empty-project ruler seeking failed or created musical content.");
        // An explicit future locate expands a bounded viewport, not the project.
        emptySession.seek(horizon * 2); emptyView.update(emptySession.snapshot());
        if (empty.projectDuration() <= horizon * 2 || empty.projectDuration() >= 172800.0)
            return juce::Result::fail("Future locating did not reveal a bounded editing horizon.");
        report.setProperty("empty_project_seek_and_future_horizon", true);
    }
    // Exercise worker publication, bounded memory, stale completion and teardown.
    const auto waitForDetails = [&]() {
        const auto began = juce::Time::getMillisecondCounter();
        while (p.detailPool.getNumJobs() > 0) {
            const auto remaining = 3000 - int(juce::Time::getMillisecondCounter() - began);
            if (remaining <= 0 || !p.detailPool.waitForJobToFinish(p.detailPool.getJob(0), remaining)) return false;
        }
        return true;
    };
    if (const auto peaks = p.findPeaks(original.id); peaks != nullptr && peaks->sampleRate > 0) {
        const auto detailEnd = double(std::min<juce::int64>(256, peaks->sampleCount)) / peaks->sampleRate;
        p.detailFor(peaks, 0, detailEnd);
        if (!waitForDetails()) return juce::Result::fail("Waveform detail worker did not complete.");
        std::shared_ptr<const WaveformDetail> detail;
        { const juce::ScopedLock guard(peaks->detailLock); detail = peaks->detail; }
        if (detail == nullptr || !detail->covers(0, detailEnd) || detail->samples.getNumSamples() > detailFrames)
            return juce::Result::fail("Worker waveform detail is missing or exceeds its frame cap.");
        std::vector<double> times;
        juce::Image detailImage(juce::Image::RGB, 1200, 180, true);
        for (int iteration = 0; iteration < 60; ++iteration) {
            juce::Graphics g(detailImage); g.fillAll(paper); g.setColour(ink);
            const auto began = juce::Time::getMillisecondCounterHiRes();
            detail->draw(g, detailImage.getBounds(), 0, detailEnd, 0.9f);
            times.push_back(juce::Time::getMillisecondCounterHiRes() - began);
        }
        std::sort(times.begin(), times.end());
        report.setProperty("waveform_detail_render_count", int(times.size()));
        report.setProperty("waveform_detail_p50_ms", times[30]);
        report.setProperty("waveform_detail_p95_ms", times[57]);
        report.setProperty("waveform_detail_worst_ms", times.back());
        report.setProperty("waveform_detail_frames", detail->samples.getNumSamples());
        report.setProperty("waveform_detail_resident_limit_bytes", detailFrames * detailWindowLimit * 2 * int(sizeof(float)));
        for (const auto cancelled : {false, true}) {
            auto discarded = std::make_shared<Peaks>(p.formats, p.cache, peaks->source, peaks->fingerprint, peaks->hash);
            discarded->cancelled.store(cancelled); discarded->detailGeneration = 1; discarded->detailPending.store(true);
            p.detailPool.addJob(new DetailJob(discarded, 0, 0), true);
            if (!waitForDetails() || discarded->detail != nullptr || discarded->detailPending.load())
                return juce::Result::fail("Stale/cancelled waveform detail was published or retained a pending job.");
        }
        if (outputDirectory.isDirectory()) {
            auto stream = outputDirectory.getChildFile("arrangement-waveform-detail.png").createOutputStream();
            if (stream == nullptr || !juce::PNGImageFormat().writeImageToStream(detailImage, *stream))
                return juce::Result::fail("Could not save waveform detail evidence.");
        }
        std::vector<std::shared_ptr<Peaks>> residentWindows;
        for (int i = 0; i <= detailWindowLimit; ++i) {
            auto item = std::make_shared<Peaks>(p.formats, p.cache, peaks->source, juce::String(i), i);
            item->sampleRate = 48000;
            auto window = std::make_shared<WaveformDetail>(); window->sampleRate = 48000; window->samples.setSize(2, 8);
            item->detail = std::move(window); residentWindows.push_back(item);
            if (p.detailFor(item, 0, 4.0 / 48000) == nullptr) return juce::Result::fail("Resident waveform window was unnecessarily queued.");
        }
        if (p.detailLru.size() != detailWindowLimit || residentWindows.front()->detail != nullptr
            || residentWindows.front()->detailGeneration == 0)
            return juce::Result::fail("Waveform detail LRU did not evict beyond its resident-memory bound.");
        report.setProperty("waveform_detail_lru_bound", int(p.detailLru.size()));
        report.setProperty("waveform_detail_async_lifetime", true);
    } else return juce::Result::fail("Waveform detail smoke requires an audio clip with worker metadata.");
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
