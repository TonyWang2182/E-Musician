#pragma once
#include "core/NativeEffects.h"
#include "core/NativeReverb.h"
#include "core/NativeAutoFilter.h"
#include "ProjectStorage.h"
#include <tracktion_engine/tracktion_engine.h>
#include <atomic>
#include <cstdint>

namespace emusician::native_effects {
inline constexpr std::array<const char*,5> supportedTypes {"eq8", "compressor", "delay", "reverb", "auto_filter"};
struct Settings { bool eq = true, delay = false, reverb = false, autoFilter = false; effects::EqSettings equalizer; effects::CompressorSettings compressor; effects::DelaySettings delaySettings; effects::ReverbSettings reverbSettings; autofilter::Settings filterSettings; };
juce::Result decode(const storage::StoredPlugin&, Settings&);
juce::var encode(const Settings&);
juce::Result mutate(storage::StoredProject&, const juce::String&, const juce::var&, juce::var* result = nullptr);
juce::Result describe(const storage::StoredProject&, const juce::String& trackId, const juce::String& deviceId, juce::var& result);

class Effect final : public tracktion::Plugin {
public:
    explicit Effect(tracktion::PluginCreationInfo);
    ~Effect() override;
    static constexpr const char* xmlTypeName = "emusician_native_effect";
    juce::String getName() const override { return "E-musician Effect"; }
    juce::String getPluginType() override { return xmlTypeName; }
    juce::String getSelectableDescription() override { return "E-musician Effect"; }
    void initialise(const tracktion::PluginInitialisationInfo&) override;
    void deinitialise() override { resetPending.store(true); }
    void reset() override { resetPending.store(true); }
    void applyToBuffer(const tracktion::PluginRenderContext&) override;
    // Called by the control thread before a delay is inserted into a graph.
    void prepareDelay();
    void prepareReverb();
    bool producesAudioWhenNoAudioInput() override { return isDelay.load(std::memory_order_relaxed) || isReverb.load(std::memory_order_relaxed) || Plugin::producesAudioWhenNoAudioInput(); }
    bool noTail() override { return !isDelay.load(std::memory_order_relaxed) && !isReverb.load(std::memory_order_relaxed); }
    double getTailLength() const override;
    // Non-persistent telemetry from the audio callback. Sequence stops changing
    // when the device is bypassed, inactive or no audio callback is running.
    float gainReductionDb() const noexcept { return reductionDb.load(std::memory_order_relaxed); }
    std::uint64_t meterSequence() const noexcept { return meterBlocks.load(std::memory_order_acquire); }
    // Control-thread transient tuning; persistent state remains owned by Edit.
    void previewSettings(const Settings&) noexcept;
    void restorePublishedSettings() { publish(); }
    // Read-only display lease. Audio captures bounded output frames while a UI
    // reader polls; copying/FFT/painting happen outside the audio callback.
    bool readSpectrum(std::array<float,2048>&,std::uint64_t&) const noexcept;
private:
    void valueTreePropertyChanged(juce::ValueTree&, const juce::Identifier&) override;
    void publish();
    std::atomic<double> rate{44100};
    std::atomic<bool> isEq{true}, isDelay{false}, isReverb{false}, isFilter{false}, resetPending{true};
    std::atomic_flag rendering=ATOMIC_FLAG_INIT;
    // Bounded seqlock: the audio callback makes one attempt, then retains its
    // last coherent snapshot. It never waits on the control thread.
    std::atomic<std::uint64_t> settingsVersion{0};
    Settings currentSettings;
    std::array<std::atomic<bool>,effects::eqBandCount> enabled{};
    std::array<std::atomic<float>,effects::eqBandCount> freq{}, gain{}, q{};
    std::array<std::atomic<effects::FilterShape>,effects::eqBandCount> shape{};
    std::atomic<float> threshold{-18},ratio{4},attack{10},release{100},makeup{0},dryWet{1};
    std::atomic<float> delayMs{350},feedback{.35f},delayMix{.35f};
    std::atomic<float> reverbDecay{1.8f},reverbDamping{.35f},reverbMix{.25f};
    std::atomic<float> filterFreq{1000},filterQ{.7071f},filterLfoHz{1},filterLfoDepth{0},filterMix{1};
    std::atomic<bool> filterHigh{false},filterLfoOn{false};
    std::atomic<float> reductionDb{0};
    std::atomic<std::uint64_t> meterBlocks{0};
    mutable std::atomic<unsigned> spectrumLease{0};
    std::array<float,2048> spectrumPending{};
    std::array<std::atomic<float>,2048> spectrumFrame{};
    std::atomic<std::uint64_t> spectrumVersion{0};
    std::size_t spectrumPosition=0;
    effects::Equalizer equalizer;
    effects::Compressor compressor;
    autofilter::Filter autoFilter;
    std::unique_ptr<effects::StereoDelay> delay;
    std::unique_ptr<effects::StereoReverb> reverb;
};
}
