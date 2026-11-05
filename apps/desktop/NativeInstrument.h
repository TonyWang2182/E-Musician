#pragma once

#include "core/NativeSampler.h"
#include "ProjectStorage.h"
#include <tracktion_engine/tracktion_engine.h>
#include <atomic>
#include <array>
#include <memory>
#include <map>
#include <vector>

namespace emusician::native {
// Shared creation and capability inventory. Adding a type without exposing
// its Agent contract causes the capability check to fail closed.
inline constexpr std::array<const char*,2> supportedInstrumentTypes {"sampler", "drum_rack"};

// Prepared on a non-audio thread. The sample data is immutable once published.
struct SampleData {
    std::vector<float> left, right;
    double sampleRate = 0;
};
struct PreparedBank {
    sampler::Bank bank;
    std::array<std::shared_ptr<const SampleData>, sampler::maxSlots> samples;
    std::array<juce::String, sampler::maxSlots> sampleHashes;
    std::array<juce::String, sampler::maxSlots> sampleAssets;
    std::map<juce::String, juce::String> sourceHashes;
};

// File decoding is synchronous and must run on a worker, never the audio or
// GUI thread. Asset IDs resolve to saved project assets, not arbitrary paths
// from instrument state. The returned bank owns all decoded sample buffers.
juce::Result prepareBank(const juce::var& state,
                         const std::map<juce::String, juce::File>& assets,
                         std::uint64_t generation,
                         std::unique_ptr<PreparedBank>& result,
                         const PreparedBank* reusable = nullptr);

// Control-thread DTO operations. Caller validates and commits via the same
// project transaction as other editing commands.
juce::Result mutate(storage::StoredProject&, const juce::String& command, const juce::var& arguments);
juce::Result describe(const storage::StoredProject&, const juce::String& trackId, juce::var& result);

class Instrument final : public tracktion::Plugin {
public:
    explicit Instrument(tracktion::PluginCreationInfo);
    ~Instrument() override;
    static constexpr const char* xmlTypeName = "emusician_native_instrument";
    juce::String getName() const override { return "E-musician Instrument"; }
    juce::String getPluginType() override { return xmlTypeName; }
    juce::String getSelectableDescription() override { return "E-musician Instrument"; }
    bool isSynth() override { return true; }
    bool takesMidiInput() override { return true; }
    bool producesAudioWhenNoAudioInput() override { return true; }
    int getNumOutputChannelsGivenInputs(int channels) override { return juce::jmin(channels, 2); }
    void initialise(const tracktion::PluginInitialisationInfo&) override;
    void deinitialise() override;
    void reset() override;
    void midiPanic() override;
    void applyToBuffer(const tracktion::PluginRenderContext&) override;

    // Single non-realtime publisher. Old buffers are retained while callbacks
    // are running and reclaimed only on this thread. No callback ownership
    // decrement or destruction is permitted.
    void publish(std::unique_ptr<PreparedBank>);
    void collectRetired();
    std::map<juce::String, juce::String> sourceHashes() const;
    // Message-thread-only read of the active immutable bank. No audio-thread ownership.
    std::shared_ptr<const SampleData> sampleForDisplay(int pad, const juce::String& expectedHash) const;
    // Message-thread snapshot of immutable PCM ownership for parameter-only
    // jobs. No copying of sample arrays and no audio-thread refcount changes.
    std::shared_ptr<const PreparedBank> bankForConfiguration() const;
    std::uint64_t concurrentBlocks() const noexcept { return reentrantBlocks.load(std::memory_order_relaxed); }
    // Preview is transient: no MIDI is sent to the track or recorded.
    bool previewSample(int slot) noexcept;
    void stopPreview() noexcept;

private:
    std::atomic<const PreparedBank*> active { nullptr };
    std::atomic<unsigned> readers { 0 };
    std::atomic_flag rendering = ATOMIC_FLAG_INIT;
    std::atomic<bool> panicPending { false };
    std::atomic<double> renderSampleRate { 44100.0 };
    std::atomic<std::uint64_t> reentrantBlocks { 0 };
    std::vector<std::unique_ptr<PreparedBank>> owned;
    sampler::Renderer renderer;
    sampler::Renderer previewRenderer;
    // 0 = no request, 1 = stop, 2..17 = start selected slot.
    std::atomic<int> previewRequest { 0 };
    std::array<sampler::Event, 4096> events {};
};
}
