#include "SampleWaveform.h"
#include "NativeInstrument.h"
#include <juce_cryptography/juce_cryptography.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <condition_variable>
#include <deque>
#include <mutex>
#include <thread>
#include <vector>

namespace emusician {
namespace {
constexpr int peakCount = 2048;
constexpr juce::int64 maximumBytes = 64 * 1024 * 1024;
const juce::Colour ink(0xff171817), quiet(0xff626560), rule(0xffc6c9c3), paper(0xfffefefd);

struct Overview {
    std::array<float, peakCount> low {}, high {};
    juce::int64 frames = 0;
    double sampleRate = 0;
};

enum class State { empty, waitingForBank, loading, ready, failed };
struct Shared {
    std::atomic<std::uint64_t> generation {0};
    std::atomic<State> state {State::empty};
    std::mutex mutex;
    std::shared_ptr<const Overview> overview;
    juce::String error;
};

bool validHash(const juce::String& hash)
{
    if (hash.length() != 64) return false;
    for (auto c : hash) if (juce::CharacterFunctions::getHexDigitValue(c) < 0) return false;
    return true;
}

// Deliberately process-lifetime, detached, and limited to one serial worker:
// a stalled network/removable file must not make closing a device panel block
// the UI. The worker owns no Component and holds at most one 64 MiB snapshot.
// Pending requests are coalesced and bounded; weak receivers allow components
// and projects to disappear without use-after-free.
class OverviewService {
public:
    static OverviewService& instance() { static auto* service = new OverviewService; return *service; }
    void submit(std::weak_ptr<Shared> target, std::uint64_t generation, juce::File path, juce::String hash,
                std::shared_ptr<const native::SampleData> prepared)
    {
        auto owner = target.lock(); if (!owner) return;
        std::lock_guard guard(mutex);
        std::erase_if(queue, [&](const Request& item) { return item.target.lock() == owner; });
        if (queue.size() >= 16) {
            std::lock_guard resultGuard(owner->mutex);
            owner->error = "Waveform queue is full. Select the sample again.";
            owner->state.store(State::failed, std::memory_order_release);
            return;
        }
        queue.push_back({std::move(target), generation, std::move(path), std::move(hash), std::move(prepared)});
        wake.notify_one();
    }

private:
    struct Request { std::weak_ptr<Shared> target; std::uint64_t generation; juce::File path; juce::String hash; std::shared_ptr<const native::SampleData> prepared; };
    OverviewService() { std::thread([this] { run(); }).detach(); }
    std::mutex mutex;
    std::condition_variable wake;
    std::deque<Request> queue;
    std::vector<std::pair<juce::String, std::shared_ptr<const Overview>>> cache;

    static bool current(const std::shared_ptr<Shared>& target, std::uint64_t token)
    { return target && target->generation.load(std::memory_order_acquire) == token; }
    static void fail(const std::shared_ptr<Shared>& target, std::uint64_t token, const juce::String& text)
    {
        if (!current(target, token)) return;
        std::lock_guard guard(target->mutex);
        if (!current(target, token)) return;
        target->overview.reset(); target->error = text;
        target->state.store(State::failed, std::memory_order_release);
    }
    static void publish(const std::shared_ptr<Shared>& target, std::uint64_t token, std::shared_ptr<const Overview> data)
    {
        if (!current(target, token)) return;
        std::lock_guard guard(target->mutex);
        if (!current(target, token)) return;
        target->overview = std::move(data); target->error.clear();
        target->state.store(State::ready, std::memory_order_release);
    }
    static std::shared_ptr<const Overview> decode(const Request& request, const std::shared_ptr<Shared>& target, juce::String& error)
    {
        auto input = request.path.createInputStream();
        if (!input) { error = "Sample unavailable."; return {}; }
        const auto bytesCount = input->getTotalLength();
        if (bytesCount <= 0 || bytesCount > maximumBytes) { error = "Sample exceeds waveform size limit."; return {}; }
        juce::MemoryBlock bytes;
        input->readIntoMemoryBlock(bytes, static_cast<juce::ssize_t>(maximumBytes + 1));
        if (!current(target, request.generation)) return {};
        if (input->getStatus().failed() || bytes.getSize() != std::size_t(bytesCount)) { error = "Cannot read the complete sample."; return {}; }
        if (juce::SHA256(bytes).toHexString() != request.hash) {
            error = "Sample file changed; reload it before displaying waveform."; return {};
        }
        juce::WavAudioFormat format;
        auto stream = std::make_unique<juce::MemoryInputStream>(bytes.getData(), bytes.getSize(), false);
        std::unique_ptr<juce::AudioFormatReader> reader(format.createReaderFor(stream.release(), true));
        if (!reader || reader->lengthInSamples < 2 || reader->numChannels < 1 || reader->numChannels > 2
            || !std::isfinite(reader->sampleRate) || reader->sampleRate < 8000 || reader->sampleRate > 384000
            || reader->lengthInSamples > maximumBytes / (juce::int64(reader->numChannels) * juce::int64(sizeof(float)))) {
            error = "Unsupported waveform source."; return {};
        }
        auto data = std::make_shared<Overview>();
        data->frames = reader->lengthInSamples; data->sampleRate = reader->sampleRate;
        data->low.fill(0.0f); data->high.fill(0.0f);
        constexpr int blockSize = 8192;
        juce::AudioBuffer<float> block(int(reader->numChannels), blockSize);
        for (juce::int64 offset = 0; offset < data->frames; offset += blockSize) {
            if (!current(target, request.generation)) return {};
            const int count = int(juce::jmin<juce::int64>(blockSize, data->frames - offset));
            if (!reader->read(&block, 0, count, offset, true, true)) { error = "Cannot decode waveform."; return {}; }
            for (int frame = 0; frame < count; ++frame) {
                const auto bin = std::size_t((offset + frame) * peakCount / data->frames);
                for (int channel = 0; channel < block.getNumChannels(); ++channel) {
                    const auto raw = block.getSample(channel, frame);
                    const float value = std::isfinite(raw) ? juce::jlimit(-1.0f, 1.0f, raw) : 0.0f;
                    data->low[bin] = std::min(data->low[bin], value);
                    data->high[bin] = std::max(data->high[bin], value);
                }
            }
        }
        return data;
    }
    static std::shared_ptr<const Overview> fromPrepared(const Request& request, const std::shared_ptr<Shared>& target)
    {
        const auto& sample = *request.prepared;
        const auto frames = sample.left.size();
        if (frames < 2 || frames > std::size_t(maximumBytes / sizeof(float))
            || (!sample.right.empty() && sample.right.size() != frames)
            || !std::isfinite(sample.sampleRate) || sample.sampleRate < 8000 || sample.sampleRate > 384000)
            return {};
        auto data = std::make_shared<Overview>();
        data->frames = juce::int64(frames); data->sampleRate = sample.sampleRate;
        for (std::size_t bin = 0; bin < peakCount; ++bin) {
            if (!current(target, request.generation)) return {};
            const auto begin = (bin * frames + peakCount - 1) / peakCount;
            const auto end = ((bin + 1) * frames + peakCount - 1) / peakCount;
            for (const auto* channel : { &sample.left, &sample.right }) {
                if (channel->empty()) continue;
                for (auto offset = begin; offset < end; ++offset) {
                    const auto raw = (*channel)[offset];
                    const auto value = std::isfinite(raw) ? juce::jlimit(-1.0f, 1.0f, raw) : 0.0f;
                    data->low[bin] = std::min(data->low[bin], value);
                    data->high[bin] = std::max(data->high[bin], value);
                }
            }
        }
        return data;
    }
    void run()
    {
        for (;;) {
            Request request;
            {
                std::unique_lock lock(mutex); wake.wait(lock, [this] { return !queue.empty(); });
                request = std::move(queue.front()); queue.pop_front();
            }
            auto target = request.target.lock();
            if (!current(target, request.generation)) continue;
            try {
                auto cached = std::find_if(cache.begin(), cache.end(), [&](const auto& entry) { return entry.first == request.hash; });
                if (cached != cache.end()) {
                    auto hit = *cached; cache.erase(cached); cache.push_back(hit);
                    publish(target, request.generation, hit.second); continue;
                }
                juce::String error;
                // The session has already verified project/revision/device/pad and
                // SHA identity. Reuse its immutable PCM; keep disk fallback for
                // callers without a prepared bank or a malformed sample.
                auto result = request.prepared ? fromPrepared(request, target) : nullptr;
                if (!result && current(target, request.generation)) result = decode(request, target, error);
                if (!current(target, request.generation)) continue;
                if (!result) { fail(target, request.generation, error.isEmpty() ? "Waveform unavailable." : error); continue; }
                cache.emplace_back(request.hash, result);
                if (cache.size() > 16) cache.erase(cache.begin());
                publish(target, request.generation, std::move(result));
            } catch (...) { fail(target, request.generation, "Waveform preparation failed."); }
        }
    }
};
}

struct SampleWaveform::Impl {
    std::shared_ptr<Shared> shared = std::make_shared<Shared>();
    std::shared_ptr<const Overview> overview;
    juce::File file;
    juce::String hash, message;
    State displayed = State::empty;
    double start = 0, end = 1, initialStart = 0, initialEnd = 1;
    bool editable = false, active = true;
    enum class Drag { none, start, end } drag = Drag::none;
};

SampleWaveform::SampleWaveform() : impl(std::make_unique<Impl>())
{
    setWantsKeyboardFocus(true);
    startTimerHz(20);
}
SampleWaveform::~SampleWaveform() { stopTimer(); impl->shared->generation.fetch_add(1); }

void SampleWaveform::setActive(bool active)
{
    if (impl->active == active) return;
    impl->active = active;
    if (!active) { stopTimer(); cancelDrag(); return; }
    timerCallback(); startTimerHz(20);
}

void SampleWaveform::setSource(const juce::File& file, const juce::String& expected,
                               std::shared_ptr<const native::SampleData> prepared)
{
    const auto hash = expected.toLowerCase();
    if (impl->file == file && impl->hash == hash) return;
    cancelDrag(); impl->file = file; impl->hash = hash; impl->overview.reset();
    const auto generation = impl->shared->generation.fetch_add(1) + 1;
    { std::lock_guard guard(impl->shared->mutex); impl->shared->overview.reset(); impl->shared->error.clear(); }
    if (file == juce::File()) { impl->displayed = State::empty; impl->shared->state.store(State::empty, std::memory_order_release); }
    else if (!validHash(hash)) { impl->displayed = State::waitingForBank; impl->shared->state.store(State::waitingForBank, std::memory_order_release); }
    else {
        impl->displayed = State::loading;
        impl->shared->state.store(State::loading, std::memory_order_release);
        OverviewService::instance().submit(impl->shared, generation, file, hash, std::move(prepared));
    }
    repaint();
}

void SampleWaveform::setRange(double start, double end, bool editable)
{
    impl->editable = editable;
    if (impl->drag != Impl::Drag::none) return;
    if (!std::isfinite(start) || !std::isfinite(end) || start < 0 || end > 1 || start >= end) { start = 0; end = 1; }
    if (impl->start != start || impl->end != end) { impl->start = start; impl->end = end; repaint(); }
}
void SampleWaveform::cancelDrag()
{
    if (impl->drag == Impl::Drag::none) return;
    impl->drag = Impl::Drag::none; impl->start = impl->initialStart; impl->end = impl->initialEnd; repaint();
    if (onRangeCancel) onRangeCancel();
}
bool SampleWaveform::isReady() const { return impl->displayed == State::ready && bool(impl->overview); }
double SampleWaveform::durationSeconds() const { return isReady() ? double(impl->overview->frames) / impl->overview->sampleRate : 0; }
juce::String SampleWaveform::statusText() const
{
    switch (impl->displayed) {
        case State::empty: return "Load a WAV sample to see its waveform.";
        case State::waitingForBank: return "Waiting for sample to finish loading.";
        case State::loading: return "Preparing waveform...";
        case State::ready: return {};
        case State::failed: return impl->message.isNotEmpty() ? impl->message : "Waveform unavailable.";
    }
    return {};
}
void SampleWaveform::timerCallback()
{
    const auto state = impl->shared->state.load(std::memory_order_acquire);
    if (state == impl->displayed) return;
    impl->displayed = state;
    { std::lock_guard guard(impl->shared->mutex); impl->overview = impl->shared->overview; impl->message = impl->shared->error; }
    if (state != State::ready) cancelDrag();
    repaint();
}
void SampleWaveform::paint(juce::Graphics& g)
{
    auto area = getLocalBounds().toFloat().reduced(10.0f, 8.0f);
    g.fillAll(paper); g.setColour(rule); g.drawRect(area, 1.0f);
    if (!isReady()) {
        g.setColour(quiet); g.setFont(juce::Font(juce::FontOptions(juce::Font::getDefaultMonospacedFontName(), 12.0f, juce::Font::plain)));
        g.drawFittedText(statusText(), area.toNearestInt().reduced(8), juce::Justification::centred, 2); return;
    }
    const auto left = area.getX(), width = area.getWidth(), centre = area.getCentreY(), amplitude = area.getHeight() * 0.44f;
    g.setColour(juce::Colour(0xffeeeeeb));
    g.fillRect(juce::Rectangle<float>(left, area.getY(), width * float(impl->start), area.getHeight()));
    g.fillRect(juce::Rectangle<float>(left + width * float(impl->end), area.getY(), width * float(1.0 - impl->end), area.getHeight()));
    g.setColour(ink); g.drawHorizontalLine(juce::roundToInt(centre), left, area.getRight());
    const int pixels = juce::jmax(1, int(std::ceil(width)));
    for (int x = 0; x < pixels; ++x) {
        const int first = juce::jlimit(0, peakCount - 1, x * peakCount / pixels);
        const int last = juce::jlimit(first + 1, peakCount, (x + 1) * peakCount / pixels);
        float low = 0, high = 0;
        for (int bin = first; bin < last; ++bin) { low = std::min(low, impl->overview->low[std::size_t(bin)]); high = std::max(high, impl->overview->high[std::size_t(bin)]); }
        g.drawVerticalLine(juce::roundToInt(left) + x, centre - high * amplitude, centre - low * amplitude);
    }
    for (auto point : {impl->start, impl->end}) {
        const float x = left + width * float(point);
        g.setColour(ink); g.drawVerticalLine(juce::roundToInt(x), area.getY(), area.getBottom());
        g.fillRect(juce::Rectangle<float>(x - 3.0f, area.getY(), 6.0f, 10.0f));
    }
}

void SampleWaveform::mouseDown(const juce::MouseEvent& e)
{
    if (!isReady() || !impl->editable || !e.mods.isLeftButtonDown()) return;
    const auto area = getLocalBounds().toFloat().reduced(10.0f, 8.0f);
    if (area.getWidth() <= 1 || !area.expanded(6.0f).contains(e.position)) return;
    const float sx = area.getX() + area.getWidth() * float(impl->start), ex = area.getX() + area.getWidth() * float(impl->end);
    const auto ds = std::abs(e.position.x - sx), de = std::abs(e.position.x - ex);
    if (std::min(ds, de) > 12.0f) return;
    impl->initialStart = impl->start; impl->initialEnd = impl->end;
    impl->drag = ds <= de ? Impl::Drag::start : Impl::Drag::end;
    grabKeyboardFocus(); if (onRangeDragStart) onRangeDragStart();
}
void SampleWaveform::mouseDrag(const juce::MouseEvent& e)
{
    if (impl->drag == Impl::Drag::none || !isReady()) return;
    const auto area = getLocalBounds().toFloat().reduced(10.0f, 8.0f);
    if (area.getWidth() <= 1) return;
    const double fraction = juce::jlimit(0.0, 1.0, double((e.position.x - area.getX()) / area.getWidth()));
    // One full sample frame ensures both normalized edges stay representable.
    const double epsilon = 1.0 / double(impl->overview->frames);
    if (impl->drag == Impl::Drag::start) impl->start = juce::jlimit(0.0, std::max(0.0, impl->end - epsilon), fraction);
    else impl->end = juce::jlimit(std::min(1.0, impl->start + epsilon), 1.0, fraction);
    repaint();
}
void SampleWaveform::mouseUp(const juce::MouseEvent&)
{
    if (impl->drag == Impl::Drag::none) return;
    impl->drag = Impl::Drag::none;
    const bool changed = impl->start != impl->initialStart || impl->end != impl->initialEnd;
    if (changed && onRangeCommit) onRangeCommit(impl->start, impl->end);
    else if (onRangeCancel) onRangeCancel();
}
bool SampleWaveform::keyPressed(const juce::KeyPress& key)
{
    if (key == juce::KeyPress::escapeKey && impl->drag != Impl::Drag::none) { cancelDrag(); return true; }
    return false;
}

juce::Result SampleWaveform::runSmokeTest(const juce::File& outputDirectory)
{
    const auto fail = [](const char* text) { return juce::Result::fail(text); };
    if (!outputDirectory.isDirectory()) return fail("Waveform smoke output directory is missing.");
    const auto file = outputDirectory.getChildFile("native-waveform-fixture.wav");
    if (file.exists()) return fail("Waveform smoke fixture already exists; refusing to overwrite it.");
    auto output = file.createOutputStream(); if (!output) return fail("Could not create waveform fixture.");
    juce::WavAudioFormat format;
    std::unique_ptr<juce::AudioFormatWriter> writer(format.createWriterFor(output.get(), 48000, 1, 16, {}, 0));
    if (!writer) return fail("Could not write waveform fixture.");
    output.release(); juce::AudioBuffer<float> block(1, 1024);
    for (int i = 0; i < 1024; ++i) block.setSample(0, i, float(std::sin(double(i) * 0.1) * 0.5));
    if (!writer->writeFromAudioSampleBuffer(block, 0, 1024)) return fail("Could not write waveform fixture samples.");
    writer.reset();
    auto input = file.createInputStream(); if (!input) return fail("Could not read waveform fixture.");
    const auto hash = juce::SHA256(*input).toHexString();
    SampleWaveform wave; wave.setSize(600, 140);
    wave.setActive(false);
    if (wave.isTimerRunning()) return fail("Hidden waveform retained its polling timer.");
    wave.setActive(true);
    if (!wave.isTimerRunning()) return fail("Visible waveform did not restart its polling timer.");
    wave.setSource(file, hash); wave.setRange(0.0, 1.0, true);
    const auto wait = [&](State wanted) {
        const auto deadline = juce::Time::getMillisecondCounterHiRes() + 8000;
        while (juce::Time::getMillisecondCounterHiRes() < deadline) {
            wave.timerCallback(); if (wave.impl->displayed == wanted) return true;
            juce::MessageManager::getInstance()->runDispatchLoopUntil(10);
        }
        return false;
    };
    if (!wait(State::ready) || wave.durationSeconds() <= 0.02 || !wave.impl->overview) return fail("Waveform worker did not publish a valid result.");
    const auto max = *std::max_element(wave.impl->overview->high.begin(), wave.impl->overview->high.end());
    if (max < 0.4f) return fail("Waveform peaks do not reflect source audio.");
    int started = 0, committed = 0, cancelled = 0; double result = -1;
    wave.onRangeDragStart = [&] { ++started; }; wave.onRangeCommit = [&](double a, double) { ++committed; result = a; }; wave.onRangeCancel = [&] { ++cancelled; };
    const auto event = [&](juce::Point<float> position, juce::Point<float> down, bool dragged) {
        const auto now = juce::Time::getCurrentTime();
        return juce::MouseEvent(juce::Desktop::getInstance().getMainMouseSource(), position,
            juce::ModifierKeys(juce::ModifierKeys::leftButtonModifier), 1, 0, 0, 0, 0, &wave, &wave, now, down, now, 1, dragged);
    };
    const juce::Point<float> down(10, 40), moved(155, 40);
    wave.mouseDown(event(down, down, false)); wave.mouseDrag(event(moved, down, true));
    if (committed != 0 || started != 1) return fail("Waveform drag committed before mouse up.");
    wave.mouseUp(event(moved, down, true));
    if (committed != 1 || std::abs(result - 0.25) > 0.01) return fail("Waveform boundary commit was incorrect.");
    wave.setRange(0, 1, true); wave.mouseDown(event(down, down, false)); wave.mouseDrag(event(moved, down, true)); wave.cancelDrag();
    if (committed != 1 || cancelled != 1) return fail("Waveform boundary cancel did not restore preview.");
    // An immediately superseded request must never replace the selected
    // source, even when the previous decode finishes after this selection.
    wave.setSource(file, juce::String::repeatedString("f", 64));
    wave.setSource(file, hash);
    if (!wait(State::ready) || !wave.statusText().isEmpty()) return fail("Stale waveform result was published.");
    wave.setSource(file, juce::String::repeatedString("0", 64));
    if (!wait(State::failed) || !wave.statusText().containsIgnoreCase("changed")) return fail("Waveform accepted mismatched source bytes.");
    wave.setSource(file, hash);
    if (!wait(State::ready)) return fail("Waveform cache did not restore the trusted sample.");
    // An already decoded published bank must not reopen the path. This path
    // deliberately does not exist; only the supplied immutable PCM can succeed.
    auto prepared = std::make_shared<native::SampleData>();
    prepared->sampleRate = 48000; prepared->left.assign(1024, 0.75f);
    const auto memoryHash = juce::String::repeatedString("1", 64);
    wave.setSource(outputDirectory.getChildFile("missing-prepared-fixture.wav"), memoryHash, prepared);
    if (!wait(State::ready) || !wave.impl->overview || wave.impl->overview->high[0] < 0.7f)
        return fail("Prepared PCM waveform reopened a missing source or lost its peaks.");
    // Invalid prepared PCM retains the existing verified disk fallback.
    auto malformed = std::make_shared<native::SampleData>();
    const auto fallbackFile = outputDirectory.getChildFile("native-waveform-fallback.wav");
    if (fallbackFile.exists() || !file.copyFileTo(fallbackFile)) return fail("Cannot create waveform fallback fixture.");
    { auto append = fallbackFile.createOutputStream(); if (!append || !append->setPosition(fallbackFile.getSize()) || !append->writeByte(0)) return fail("Cannot vary waveform fallback fixture."); }
    auto fallbackInput = fallbackFile.createInputStream();
    if (!fallbackInput) return fail("Cannot read waveform fallback fixture.");
    const auto fallbackHash = juce::SHA256(*fallbackInput).toHexString();
    wave.setSource(fallbackFile, fallbackHash, malformed);
    if (!wait(State::ready)) return fail("Waveform failed to fall back from malformed PCM.");
    const auto screenshot = outputDirectory.getChildFile("ui-native-waveform-real.png");
    if (screenshot.exists()) return fail("Waveform screenshot already exists; refusing to overwrite it.");
    auto imageOutput = screenshot.createOutputStream();
    const auto image = wave.createComponentSnapshot(wave.getLocalBounds());
    if (!imageOutput || !image.isValid() || !juce::PNGImageFormat().writeImageToStream(image, *imageOutput))
        return fail("Could not save the real sample waveform capture.");
    imageOutput->flush();
    return juce::Result::ok();
}
}
