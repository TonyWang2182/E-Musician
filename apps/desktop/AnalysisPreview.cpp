#include "AnalysisPreview.h"
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <limits>
#include <mutex>
#include <vector>

namespace emusician {
struct AnalysisPreview::Impl final : juce::AudioIODeviceCallback {
    static_assert(std::atomic<std::uint64_t>::is_always_lock_free && std::atomic<unsigned>::is_always_lock_free
                  && std::atomic<double>::is_always_lock_free && std::atomic<bool>::is_always_lock_free
                  && std::atomic<void*>::is_always_lock_free, "Audition callback requires lock-free atomics.");
    static constexpr size_t ringSize = 65536, blockSize = 1024;
    static constexpr float previewGain = 0.2511886432f; // -12 dB, independent of the project mixer.
    struct Stream {
        explicit Stream(std::uint64_t value, double rate, std::uint64_t samples)
            : generation(value), sampleRate(rate), totalSamples(samples), left(ringSize), right(ringSize) {}
        const std::uint64_t generation;
        const double sampleRate;
        const std::uint64_t totalSamples;
        std::vector<float> left, right;
        std::atomic<std::uint64_t> written {0}, read {0};
        std::atomic<bool> ended {false};
    };
    struct RenderState {
        std::unique_ptr<juce::AudioFormatReaderSource> reader;
        std::unique_ptr<juce::ResamplingAudioSource> resampler;
        std::unique_ptr<Stream> stream;
        juce::AudioBuffer<float> block {2, int(blockSize)};
    };
    struct Worker final : juce::Thread {
        explicit Worker(Impl& value) : juce::Thread("Analysis preview decode"), owner(value) {}
        void run() override { owner.run(); }
        Impl& owner;
    };

    explicit Impl(juce::AudioDeviceManager& audioManager) : manager(audioManager), worker(*this) {
        worker.startThread(juce::Thread::Priority::low);
        manager.addAudioCallback(this);
    }
    ~Impl() override {
        // Removal completes any in-flight callback before buffers are retired.
        manager.removeAudioCallback(this);
        published.store(nullptr);
        {
            std::lock_guard lock(mutex); shuttingDown = true; pendingFile = {}; generation.fetch_add(1);
        }
        wake.notify_one();
        worker.waitForThreadToExit(-1);
    }
    juce::Result play(const juce::File& file) {
        if (deviceRate.load() <= 0.0) return juce::Result::fail("No audio output is active. Open audio settings before previewing a stem.");
        if (file == juce::File()) return juce::Result::fail("No analysis artifact was supplied for preview.");
        if (!worker.isThreadRunning()) return juce::Result::fail("The analysis preview worker is unavailable.");
        {
            std::lock_guard lock(mutex);
            if (shuttingDown) return juce::Result::fail("The analysis preview is shutting down.");
            // Unpublish before the new request becomes visible to the worker.
            // Clearing after unlocking could erase its freshly published stream.
            published.store(nullptr);
            generation.fetch_add(1); pendingFile = file; requested = true;
            phase = "loading"; detail = "Preparing a separate audition stream at -12 dB.";
            completedGeneration.store(0); consumed.store(0); underruns.store(0);
        }
        // An old worker may finish publishing concurrently, but callback
        // generation checks make that stream inaudible after this command.
        wake.notify_one(); return juce::Result::ok();
    }
    void stop() {
        {
            std::lock_guard lock(mutex);
            published.store(nullptr);
            generation.fetch_add(1); pendingFile = {}; requested = false; phase = "stopped"; detail.clear();
        }
        wake.notify_one();
    }
    juce::var status() const {
        std::lock_guard lock(mutex);
        auto* value = new juce::DynamicObject();
        const auto ended = completedGeneration.load() == generation.load();
        const auto unavailable = requested && deviceRate.load() <= 0.0;
        value->setProperty("status", unavailable ? juce::String("unavailable") : ended && requested ? juce::String("completed") : phase);
        value->setProperty("detail", unavailable ? juce::String("Audio output stopped. Select an output device or stop the preview.") : detail);
        value->setProperty("gain_db", -12.0);
        value->setProperty("sample_rate", deviceRate.load());
        value->setProperty("consumed_samples", juce::int64(consumed.load()));
        value->setProperty("underruns", juce::int64(underruns.load()));
        return juce::var(value);
    }
    void setStatus(std::uint64_t expected, const juce::String& state, const juce::String& message) {
        std::lock_guard lock(mutex);
        if (generation.load() == expected && requested) { phase = state; detail = message; }
    }
    void retire(std::unique_ptr<RenderState>& state, std::vector<std::unique_ptr<Stream>>& retired) {
        if (!state) return;
        auto* expected = state->stream.get(); published.compare_exchange_strong(expected, nullptr);
        retired.push_back(std::move(state->stream));
        // Decoder and resampler are only touched/destroyed on this worker.
        state.reset();
    }
    std::unique_ptr<RenderState> open(const juce::File& file, std::uint64_t expected, double rate) {
        juce::WavAudioFormat format;
        auto input = file.createInputStream();
        std::unique_ptr<juce::AudioFormatReader> reader(input ? format.createReaderFor(input.release(), true) : nullptr);
        if (!reader || reader->sampleRate < 8000.0 || reader->sampleRate > 384000.0
            || reader->numChannels < 1 || reader->numChannels > 2 || reader->lengthInSamples <= 0
            || double(reader->lengthInSamples) / reader->sampleRate > 600.1) {
            setStatus(expected, "failed", "This analysis artifact is missing or is not a supported mono/stereo WAV."); return {};
        }
        auto state = std::make_unique<RenderState>();
        const auto sourceRate = reader->sampleRate;
        const auto frames = std::uint64_t(std::ceil(double(reader->lengthInSamples) * rate / sourceRate));
        state->stream = std::make_unique<Stream>(expected, rate, frames);
        state->reader = std::make_unique<juce::AudioFormatReaderSource>(reader.release(), true);
        state->resampler = std::make_unique<juce::ResamplingAudioSource>(state->reader.get(), false, 2);
        state->resampler->setResamplingRatio(sourceRate / rate);
        state->resampler->prepareToPlay(int(blockSize), rate);
        return state;
    }
    void fill(RenderState& state) {
        auto& stream = *state.stream;
        const auto written = stream.written.load(), read = stream.read.load();
        if (written >= stream.totalSamples) { stream.ended.store(true); return; }
        const auto free = ringSize - size_t(written - read);
        const auto count = int(std::min<std::uint64_t>({blockSize, free, stream.totalSamples - written}));
        if (count <= 0) return;
        state.resampler->getNextAudioBlock(juce::AudioSourceChannelInfo(&state.block, 0, count));
        for (int i = 0; i < count; ++i) {
            const auto at = size_t(written + std::uint64_t(i)) & (ringSize - 1);
            const float l = state.block.getSample(0, i), r = state.block.getSample(1, i);
            stream.left[at] = std::isfinite(l) ? l : 0.0f; stream.right[at] = std::isfinite(r) ? r : 0.0f;
        }
        stream.written.store(written + std::uint64_t(count));
        if (written + std::uint64_t(count) >= stream.totalSamples) stream.ended.store(true);
    }
    void run() {
        juce::Thread::setCurrentThreadName("Analysis preview decode");
        std::unique_ptr<RenderState> state;
        std::vector<std::unique_ptr<Stream>> retired;
        std::uint64_t attempted = 0;
        for (;;) {
            juce::File file; std::uint64_t expected; bool wanted;
            {
                std::unique_lock lock(mutex);
                wake.wait_for(lock, std::chrono::milliseconds(state && !state->stream->ended.load() ? 2 : 20));
                if (shuttingDown) break;
                expected = generation.load(); file = pendingFile; wanted = requested;
            }
            const auto rate = deviceRate.load();
            if (state && (!wanted || state->stream->generation != expected || state->stream->sampleRate != rate)) retire(state, retired);
            // The callback increments readers before loading published. Once
            // the old pointer has been unpublished, zero readers is sufficient
            // to reclaim it here; no sample memory is freed on the audio thread.
            if (readers.load() == 0) retired.clear();
            if (!wanted || rate <= 0.0) continue;
            if (!state && attempted != expected) {
                attempted = expected;
                try { state = open(file, expected, rate); }
                catch (const std::exception& error) { setStatus(expected, "failed", "Could not prepare preview: " + juce::String(error.what())); }
                if (!state) continue;
                // Prefill on the worker, before publishing the ring.
                for (int block = 0; block < 8 && generation.load() == expected; ++block) fill(*state);
                if (generation.load() != expected) { retire(state, retired); continue; }
                published.store(state->stream.get());
                setStatus(expected, "playing", "Audition only / -12 dB / original arrangement unchanged.");
            }
            if (state) {
                if (state->stream->generation != generation.load()) continue;
                try {
                    for (int block = 0; block < 8 && generation.load() == expected; ++block) {
                        const auto written = state->stream->written.load(), read = state->stream->read.load();
                        if (written - read >= ringSize - blockSize || state->stream->ended.load()) break;
                        fill(*state);
                    }
                } catch (const std::exception& error) {
                    setStatus(expected, "failed", "Preview read failed: " + juce::String(error.what())); retire(state, retired);
                }
            }
        }
        published.store(nullptr);
        retire(state, retired);
        // Destruction first removes the callback, so this path has no readers.
        retired.clear();
    }

    void render(float* const* output, int outputChannels, int samples) noexcept {
        for (int channel = 0; channel < outputChannels; ++channel) if (output[channel]) juce::FloatVectorOperations::clear(output[channel], samples);
        readers.fetch_add(1);
        auto* stream = published.load();
        const auto current = generation.load();
        if (stream && stream->generation == current && stream->sampleRate == deviceRate.load()) {
            const auto read = stream->read.load(), written = stream->written.load();
            const auto count = int(std::min<std::uint64_t>(std::uint64_t(samples), written - read));
            for (int i = 0; i < count; ++i) {
                const auto at = size_t(read + std::uint64_t(i)) & (ringSize - 1);
                if (outputChannels == 1 && output[0]) output[0][i] = (stream->left[at] + stream->right[at]) * (previewGain * .5f);
                else {
                    if (outputChannels > 0 && output[0]) output[0][i] = stream->left[at] * previewGain;
                    if (outputChannels > 1 && output[1]) output[1][i] = stream->right[at] * previewGain;
                }
            }
            stream->read.store(read + std::uint64_t(count)); consumed.store(read + std::uint64_t(count));
            if (stream->ended.load() && read + std::uint64_t(count) >= stream->totalSamples) completedGeneration.store(current);
            else if (count < samples) underruns.fetch_add(1);
        }
        readers.fetch_sub(1);
    }
    void audioDeviceIOCallbackWithContext(const float* const*, int, float* const* output,
                                          int channels, int samples, const juce::AudioIODeviceCallbackContext&) override {
        render(output, channels, samples);
    }
    void changeDeviceRate(double rate) noexcept {
        deviceRate.store(std::isfinite(rate) && rate >= 8000.0 && rate <= 384000.0 ? rate : 0.0);
        // Device changes invalidate the current stream and let the worker
        // reopen from the beginning at the new hardware rate.
        // A stale worker publication after this store is filtered by generation.
        // Publishing the new generation before clearing could erase a new stream.
        published.store(nullptr); generation.fetch_add(1);
    }
    void audioDeviceAboutToStart(juce::AudioIODevice* device) override { changeDeviceRate(device ? device->getCurrentSampleRate() : 0.0); }
    void audioDeviceStopped() override { changeDeviceRate(0.0); }
    void audioDeviceError(const juce::String&) override { changeDeviceRate(0.0); }

    juce::AudioDeviceManager& manager;
    mutable std::mutex mutex; std::condition_variable wake;
    juce::File pendingFile; bool requested = false, shuttingDown = false;
    juce::String phase {"stopped"}, detail;
    std::atomic<double> deviceRate {0.0};
    std::atomic<std::uint64_t> generation {1}, completedGeneration {0}, consumed {0}, underruns {0};
    std::atomic<unsigned> readers {0}; std::atomic<Stream*> published {nullptr};
    Worker worker;
};

AnalysisPreview::AnalysisPreview(juce::AudioDeviceManager& manager) : impl(std::make_unique<Impl>(manager)) {}
AnalysisPreview::~AnalysisPreview() = default;
juce::Result AnalysisPreview::prepareAndPlay(const juce::File& file) { return impl->play(file); }
void AnalysisPreview::stop() { impl->stop(); }
juce::var AnalysisPreview::status() const { return impl->status(); }

juce::Result AnalysisPreview::runSmokeTest(juce::DynamicObject& report, const juce::File& directory) {
    const auto fixture = directory.getChildFile("analysis-preview-fixture.wav");
    juce::AudioBuffer<float> samples(2, 4410);
    for (int i = 0; i < samples.getNumSamples(); ++i) {
        samples.setSample(0, i, .4f * std::sin(float(i) * .05f)); samples.setSample(1, i, -.2f * std::sin(float(i) * .05f));
    }
    juce::WavAudioFormat wav;
    auto stream = fixture.createOutputStream();
    if (stream) { stream->setPosition(0); stream->truncate(); }
    std::unique_ptr<juce::AudioFormatWriter> writer(stream ? wav.createWriterFor(stream.release(), 44100.0, 2, 24, {}, 0) : nullptr);
    if (!writer || !writer->writeFromAudioSampleBuffer(samples, 0, samples.getNumSamples())) return juce::Result::fail("Cannot write audition fixture.");
    writer.reset();
    juce::AudioDeviceManager manager; AnalysisPreview preview(manager);
    if (preview.prepareAndPlay(fixture).wasOk()) return juce::Result::fail("Audition accepted an unavailable output device.");
    preview.impl->changeDeviceRate(48000.0); // Offline callback harness; no physical audio device.
    if (auto start = preview.prepareAndPlay(fixture); start.failed()) return start;
    const auto deadline = juce::Time::getMillisecondCounterHiRes() + 5000.0;
    while (preview.status()["status"].toString() == "loading" && juce::Time::getMillisecondCounterHiRes() < deadline) juce::Thread::sleep(2);
    if (preview.status()["status"].toString() != "playing") return juce::Result::fail("Audition worker did not publish its decoded stream.");
    juce::AudioBuffer<float> rendered(2, 256); bool sounded = false;
    for (int block = 0; block < 24; ++block) {
        preview.impl->render(rendered.getArrayOfWritePointers(), 2, 256);
        sounded = sounded || rendered.getMagnitude(0, 256) > .02f;
        if (rendered.getMagnitude(0, 256) > .15f) return juce::Result::fail("Audition gain exceeded its fixed safe monitoring level.");
    }
    const auto finished = preview.status();
    if (!sounded || finished["status"].toString() != "completed" || juce::int64(finished["consumed_samples"]) != 4800)
        return juce::Result::fail("Audition resampling or end timing is incorrect.");
    // Stop remains nonblocking and prevents a queued old publication sounding.
    for (int repeat = 0; repeat < 8; ++repeat) { preview.prepareAndPlay(fixture); preview.stop(); }
    preview.impl->render(rendered.getArrayOfWritePointers(), 2, 256);
    if (rendered.getMagnitude(0, 256) != 0.0f) return juce::Result::fail("Stopped audition leaked queued audio.");
    // Repeatedly race request publication with the decoder and device changes.
    // The final accepted generation must remain audible, not merely report playing.
    for (int repeat = 0; repeat < 32; ++repeat) {
        if (auto result = preview.prepareAndPlay(fixture); result.failed()) return result;
        if (repeat % 3 == 0) { preview.impl->changeDeviceRate(0.0); preview.impl->changeDeviceRate(48000.0); }
        juce::Thread::sleep(repeat % 3);
    }
    if (auto result = preview.prepareAndPlay(fixture); result.failed()) return result;
    const auto raceDeadline = juce::Time::getMillisecondCounterHiRes() + 5000.0;
    while (preview.status()["status"].toString() == "loading" && juce::Time::getMillisecondCounterHiRes() < raceDeadline) juce::Thread::sleep(2);
    preview.impl->render(rendered.getArrayOfWritePointers(), 2, 256);
    if (preview.status()["status"].toString() != "playing" || rendered.getMagnitude(0, 256) < .02f)
        return juce::Result::fail("An audition publication race left the latest request silent.");
    preview.stop();
    report.setProperty("analysis_preview_offline_decode_resample_end", true);
    report.setProperty("analysis_preview_generation_stop_silence", true);
    report.setProperty("analysis_preview_no_device_rejected", true);
    report.setProperty("analysis_preview_publication_race_stress", true);
    report.setProperty("analysis_preview_hardware_verified", false);
    return juce::Result::ok();
}
}
