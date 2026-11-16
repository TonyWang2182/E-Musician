// Included inside runProductionSmokeTest's try block. These devices implement
// JUCE's real packed callback contract without opening OS audio/MIDI drivers.
{
    struct FakeAudioState {
        bool dropRight = false, panelAvailable = true;
        int panelCalls = 0;
        std::function<void()> panelAction;
        std::function<void()> deviceOpening;
    } fakeState;
    struct FakeAudioDevice final : juce::AudioIODevice {
        FakeAudioState& state;
        int inputCount;
        bool opened = false;
        double rate = 48000;
        int blockSize = 256;
        juce::BigInteger inputs, outputs;
        juce::AudioIODeviceCallback* callback = nullptr;
        FakeAudioDevice(FakeAudioState& s, const juce::String& name, const juce::String& type)
            : AudioIODevice(name, type), state(s), inputCount(name == "One input" ? 1 : name == "Four inputs" ? 4 : 2) {}
        ~FakeAudioDevice() override { close(); }
        juce::StringArray getInputChannelNames() override {
            juce::StringArray result;
            for (int i = 0; i < inputCount; ++i) result.add("Physical " + juce::String(i + 1));
            return result;
        }
        juce::StringArray getOutputChannelNames() override { return {"Left", "Right"}; }
        juce::Array<double> getAvailableSampleRates() override { return {44100, 48000}; }
        juce::Array<int> getAvailableBufferSizes() override { return {128, 256}; }
        int getDefaultBufferSize() override { return 256; }
        juce::String open(const juce::BigInteger& in, const juce::BigInteger& out, double sampleRate, int size) override {
            if (state.deviceOpening) state.deviceOpening();
            inputs.clear(); outputs.clear();
            for (int i = 0; i < inputCount; ++i) inputs.setBit(i, in[i] && !(state.dropRight && i == 1));
            for (int i = 0; i < 2; ++i) outputs.setBit(i, out[i]);
            rate = sampleRate; blockSize = size; opened = true;
            return {};
        }
        void close() override { stop(); opened = false; }
        bool isOpen() override { return opened; }
        void start(juce::AudioIODeviceCallback* cb) override { callback = cb; if (callback) callback->audioDeviceAboutToStart(this); }
        void stop() override { auto* cb = callback; callback = nullptr; if (cb) cb->audioDeviceStopped(); }
        bool isPlaying() override { return callback != nullptr; }
        juce::String getLastError() override { return {}; }
        int getCurrentBufferSizeSamples() override { return blockSize; }
        double getCurrentSampleRate() override { return rate; }
        int getCurrentBitDepth() override { return 24; }
        juce::BigInteger getActiveInputChannels() const override { return inputs; }
        juce::BigInteger getActiveOutputChannels() const override { return outputs; }
        int getInputLatencyInSamples() override { return 0; }
        int getOutputLatencyInSamples() override { return 0; }
        bool hasControlPanel() const override { return state.panelAvailable; }
        bool showControlPanel() override { ++state.panelCalls; if (state.panelAction) state.panelAction(); return false; }
        // Null and oversized blocks exercise the production dependency's
        // defensive callback mapping, not a separate application-side mapper.
        void pump(bool nullInput = false, int samples = 256, bool fullSlots = false) {
            juce::AudioBuffer<float> physical(inputCount, samples), output(2, samples);
            for (int ch = 0; ch < inputCount; ++ch)
                for (int i = 0; i < samples; ++i) physical.setSample(ch, i, ch == 1 ? -0.625f : 0.25f);
            std::vector<const float*> packed;
            for (int i = 0; i < inputCount; ++i)
                if (inputs[i] || fullSlots) packed.push_back(nullInput || !inputs[i] ? nullptr : physical.getReadPointer(i));
            output.clear();
            if (callback) callback->audioDeviceIOCallbackWithContext(packed.data(), int(packed.size()), output.getArrayOfWritePointers(), 2, samples, {});
        }
    };
    struct FakeAudioType final : juce::AudioIODeviceType {
        FakeAudioState& state;
        FakeAudioType(FakeAudioState& s, const juce::String& name) : AudioIODeviceType(name), state(s) {}
        void scanForDevices() override {}
        juce::StringArray getDeviceNames(bool = false) const override { return {"Two inputs A", "Two inputs B", "One input", "Four inputs"}; }
        int getDefaultDeviceIndex(bool) const override { return 0; }
        int getIndexOfDevice(juce::AudioIODevice* device, bool) const override { return device ? getDeviceNames().indexOf(device->getName()) : -1; }
        bool hasSeparateInputsAndOutputs() const override { return false; }
        juce::AudioIODevice* createDevice(const juce::String& out, const juce::String& in) override {
            return new FakeAudioDevice(state, out.isNotEmpty() ? out : in, getTypeName());
        }
    };
    EngineSession fixture(false);
    auto& engineDevices = fixture.impl->engine.getDeviceManager();
    auto& manager = engineDevices.deviceManager;
    // Keep initialise() from enumerating or opening a system audio backend.
    std::vector<juce::AudioIODeviceType*> oldTypes;
    for (auto* type : manager.getAvailableDeviceTypes()) oldTypes.push_back(type);
    for (auto* type : oldTypes) manager.removeAudioDeviceType(type);
    manager.addAudioDeviceType(std::make_unique<FakeAudioType>(fakeState, "Fixture audio A"));
    manager.addAudioDeviceType(std::make_unique<FakeAudioType>(fakeState, "Fixture audio B"));
    engineDevices.initialise(0, 2);
    engineDevices.dispatchPendingUpdates();
    auto& recorder = fixture.impl->recording;
    const auto configure = [&](juce::var args) { return fixture.execute("configure_audio_device", args, fixture.snapshot().revision); };
    const auto active = [&] { return manager.getCurrentAudioDevice()->getActiveInputChannels(); };
    const auto array = [](std::initializer_list<int> values) { juce::Array<juce::var> result; for (int value : values) result.add(value); return juce::var(result); };
    const auto input = [&](std::initializer_list<int> channels) {
        const auto wanted = juce::JSON::toString(array(channels), true);
        auto catalog = recorder.inputs();
        if (const auto* list = catalog["inputs"].getArray())
            for (const auto& row : *list) if (!bool(row["midi"]) && juce::JSON::toString(row["channels"], true) == wanted) return row;
        return juce::var();
    };
    const auto opened = [&]() -> FakeAudioDevice& {
        auto* device = dynamic_cast<FakeAudioDevice*>(manager.getCurrentAudioDevice());
        check(device != nullptr, "fake device remains the selected driver"); return *device;
    };
    check(active().isZero(), "output-only startup reproduces a physically disabled input mask");
    check(configure(object({{"device_name", "Two inputs A"}, {"input_channels", array({2})}})).failed() && active().isZero(), "rollback from initial default mode restores exact zero mask despite changed JUCE default counts");
    okay(configure(object({{"device_name", "Two inputs A"}, {"input_channels", array({0, 1})}})), "explicit settings enable both physical inputs");
    check(active()[0] && active()[1], "physical mask is read back after configuration");
    command(fixture, "create_track", object({{"kind", "audio"}, {"name", "Physical channel capture"}}));
    const auto trackId = fixture.snapshot().tracks.back().id;
    const auto select = [&](const juce::var& row) { command(fixture, "set_track_input", object({{"track_id", trackId}, {"input_device_id", row["id"]}})); };
    const auto arm = [&] { return fixture.execute("set_track_armed", object({{"track_id", trackId}, {"armed", true}}), fixture.snapshot().revision); };
    check(input({0})["id"].toString().startsWith("audioin_") && input({0})["engine_id"].toString().startsWith("wavein_"), "audio catalog separates persisted interface identity from native TE name hash");
    const auto duplexId = input({0})["id"].toString();
    check(configure(object({{"output_device_name", "Two inputs B"}})).failed()
        && manager.getCurrentAudioDevice()->getName() == "Two inputs A" && input({0})["id"].toString() == duplexId,
        "a duplex backend rejects mismatched input/output names instead of silently opening another interface");
    command(fixture, "set_track_input", object({{"track_id", trackId}, {"input_device_id", input({0})["engine_id"]}}));
    check(arm().failed(), "unqualified physical input from a legacy project requires explicit re-selection");
    select(input({0}));
    okay(configure(object({{"input_channels", array({})}})), "disable all physical input channels");
    const auto disabled = arm();
    check(disabled.failed() && disabled.getErrorMessage().contains("Audio Settings") && active().isZero(), "arm reports disabled physical input without silently undoing settings");
    check(!bool(input({0})["physical_active"]), "catalog exposes physical disabled status separately from native routing");
    okay(configure(object({{"input_channels", array({1})}})), "activate only physical channel two");
    check(arm().failed(), "channel one cannot be armed when only physical channel two is active");
    select(input({1})); okay(arm(), "arm second physical channel");
    okay(configure(object({{"sample_rate", 44100.0}, {"buffer_size", 128}})), "rate and buffer update without a mask");
    check(!active()[0] && active()[1], "omitted channel mask preserves the same interface's sparse selection");
    check(fixture.snapshot().tracks.back().armed && fixture.snapshot().tracks.back().monitorMode == "off", "same-device reconfiguration restores the previous arm without enabling monitor");
    okay(configure(object({{"sample_rate", 48000.0}, {"buffer_size", 256}})), "restore capture rate and size");
    for (const auto& malformed : {juce::var("1"), juce::var(true), juce::var(0.5), juce::var(-1), juce::var(1024)}) {
        juce::Array<juce::var> values; values.add(malformed);
        check(configure(object({{"input_channels", values}})).failed() && active()[1] && !active()[0], "malformed channel index is rejected without changing the mask");
    }
    check(configure(object({{"input_channels", array({1, 1})}})).failed(), "duplicate physical channel indices are rejected");
    check(configure(object({{"input_channels", array({2})}})).failed() && active()[1], "out-of-device channel index rolls back the previous mask");
    check(fixture.snapshot().tracks.back().armed, "failed configuration restores the matching input's previous arm");
    check(configure(object({{"input_stereo_pairs", array({1})}})).failed(), "odd stereo pair starts are rejected");
    check(configure(object({{"input_stereo_pairs", array({0})}})).failed() && active()[1] && !active()[0], "stereo pairing requires both active physical channels and rolls back");
    okay(configure(object({{"input_channels", array({0})}})), "prepare driver readback refusal test");
    fakeState.dropRight = true;
    check(configure(object({{"input_channels", array({1})}})).failed() && active()[0] && !active()[1], "driver mask refusal is detected by readback and the original mask is restored");
    fakeState.dropRight = false;
    okay(configure(object({{"input_channels", array({1})}})), "restore sparse input for PCM test");
    select(input({1})); okay(arm(), "rearm sparse input after configuration");
    recorder.attach(*fixture.impl->edit, directory.getChildFile("audio-input-fake-takes"));
    command(fixture, "set_recording_preferences", object({{"count_in_enabled", false}}));
    command(fixture, "set_input_monitor", object({{"track_id", trackId}, {"mode", "on"}}));
    check(!fixture.snapshot().tracks.back().armed && fixture.snapshot().tracks.back().monitorMode == "on", "audio Monitor On does not arm the track");
    command(fixture, "set_input_monitor", object({{"track_id", trackId}, {"mode", "off"}}));
    okay(arm(), "arm with monitor off");
    check(fixture.snapshot().tracks.back().armed && fixture.snapshot().tracks.back().monitorMode == "off", "audio arm does not enable live monitoring");
    juce::Array<juce::var> captureReports;
    const auto capture = [&](const juce::var& row, bool nullInput, int samples, const std::vector<float>& expected, bool fullSlots = false) {
        select(row); okay(arm(), "arm callback capture");
        fixture.seek(0);
        fixture.impl->edit->dispatchPendingUpdatesSynchronously();
        // Seek/Stop are audio-clock messages. Commit them before preparing the
        // next take, otherwise the previous take's position creates a WAV gap.
        opened().pump(); opened().pump();
        auto* context = fixture.impl->edit->getTransport().getCurrentPlaybackContext();
        const double settledPosition = context ? context->getPosition().inSeconds() : -1;
        check(std::abs(settledPosition) < 1.0e-8, "stopped audio clock commits seek before preparing a repeated take: " + juce::String(settledPosition, 9));
        juce::StringArray previousClips;
        for (auto* clip : te::getAudioTracks(*fixture.impl->edit).getLast()->getClips()) previousClips.add(clip->state["emId"].toString());
        command(fixture, "start_recording");
        check(configure(object({{"input_channels", array({0, 1})}})).failed(), "physical input changes are blocked during a take");
        check(fixture.execute("show_audio_driver_panel", object({}), fixture.snapshot().revision).failed(), "native panel is blocked during a take");
        for (int block = 0; block < 64; ++block) opened().pump(nullInput, samples, fullSlots);
        command(fixture, "stop_recording");
        fixture.impl->finishRecording();
            auto* track = te::getAudioTracks(*fixture.impl->edit).getLast();
        te::WaveAudioClip* clip = nullptr;
        for (auto* candidate : track->getClips()) if (!previousClips.contains(candidate->state["emId"].toString())) clip = dynamic_cast<te::WaveAudioClip*>(candidate);
        check(clip != nullptr, "fake callback creates a real recorded audio clip");
        juce::WavAudioFormat format;
        std::unique_ptr<juce::AudioFormatReader> reader(format.createReaderFor(clip->getOriginalFile().createInputStream().release(), true));
        check(reader && reader->numChannels == expected.size() && reader->lengthInSamples > 1024, "captured WAV has the requested mono/stereo layout and actual sample data");
        juce::AudioBuffer<float> pcm(int(reader->numChannels), int(reader->lengthInSamples));
        check(reader->read(&pcm, 0, pcm.getNumSamples(), 0, true, true), "decode fake device recording");
        const int start = pcm.getNumSamples() / 4, length = pcm.getNumSamples() / 2;
        juce::Array<juce::var> means, expectedValues;
        for (int ch = 0; ch < pcm.getNumChannels(); ++ch) {
            double sum = 0; for (int i = start; i < start + length; ++i) sum += pcm.getSample(ch, i);
            means.add(sum / length); expectedValues.add(expected[size_t(ch)]);
        }
        captureReports.add(object({{"channels", row["channels"]}, {"full_slots", fullSlots}, {"null_input", nullInput},
            {"callback_samples", samples}, {"settled_position", settledPosition}, {"frames", juce::int64(reader->lengthInSamples)},
            {"expected_means", expectedValues}, {"actual_means", means}, {"file", clip->getOriginalFile().getFullPathName()}}));
        check(directory.getChildFile("audio-input-capture-report.json").replaceWithText(juce::JSON::toString(captureReports, true)), "write physical channel capture diagnostics before PCM assertions");
        for (int ch = 0; ch < pcm.getNumChannels(); ++ch)
            check(std::abs(double(means[ch]) - expected[size_t(ch)]) < 0.001, "recorded channel contains its physical source, including sparse and missing input cases");
    };
    capture(input({1}), false, 256, {-0.625f});
    capture(input({1}), false, 256, {-0.625f}, true);
    capture(input({1}), true, 512, {0.0f});
    okay(configure(object({{"input_channels", array({0, 1})}})), "enable two independent mono channels");
    capture(input({0}), false, 256, {0.25f});
    capture(input({1}), false, 256, {-0.625f});
    const auto monoId = input({0})["id"].toString();
    okay(configure(object({{"input_stereo_pairs", array({0})}})), "make a real stereo input pair");
    check(input({0}).isVoid() && bool(input({0, 1})["stereo"]), "pairing exposes a stereo input instead of separate mono inputs");
    capture(input({0, 1}), false, 256, {0.25f, -0.625f});
    okay(configure(object({{"input_channels", array({1})}})), "disable one side of a stereo pair");
    check(input({0, 1}).isVoid() && input({0})["id"].toString() == monoId, "partial activation returns to stable mono input identities");
    select(input({1})); okay(arm(), "arm original interface before switching");
    command(fixture, "set_input_monitor", object({{"track_id", trackId}, {"mode", "on"}}));
    int disconnectedOpens = 0;
    const auto targetsDetached = [&] {
        auto* track = te::getAudioTracks(*fixture.impl->edit).getLast();
        for (auto* instance : fixture.impl->edit->getAllInputDevices())
            if (!instance->getInputDevice().isMidi() && instance->getTargets().contains(track->itemID)) return false;
        return true;
    };
    fakeState.deviceOpening = [&] { check(targetsDetached(), "audio targets are detached before a replacement native device opens"); ++disconnectedOpens; };
    const auto originalId = input({1})["id"].toString(), nativeId = input({1})["engine_id"].toString();
    okay(configure(object({{"device_name", "Two inputs B"}})), "switch to a different interface with identical native channel names");
    fakeState.deviceOpening = {};
    check(disconnectedOpens > 0 && !fixture.snapshot().tracks.back().armed, "a native open cannot transiently reuse old armed/live audio targets");
    check(active()[0] && active()[1], "new interface resets physical channels instead of inheriting an old sparse or disabled mask");
    check(input({1})["engine_id"].toString() == nativeId && input({1})["id"].toString() != originalId, "same native channel hash does not identify a different audio interface");
    check(!recorder.inputForId(originalId) && arm().failed(), "previous interface selection is unavailable and cannot silently arm the new card");
    const auto saved = fixture.impl->capture();
    check(saved.tracks.back().inputDeviceId == originalId, "project capture retains the unavailable qualified identity without substituting the new card");
    okay(configure(object({{"driver_type", "Fixture audio B"}, {"device_name", "Two inputs B"}})), "switch backend with identical device names");
    check(!recorder.inputForId(originalId), "driver identity also participates in input selection");
    okay(configure(object({{"device_name", "One input"}})), "open a single-input interface");
    check(active()[0] && active().countNumberOfSetBits() == 1, "new interface default is bounded by actual physical input count");
    okay(configure(object({{"device_name", "Four inputs"}, {"input_channels", array({2, 3})}, {"input_stereo_pairs", array({2})}})), "configure a later stereo pair on a multichannel interface");
    check(bool(input({2, 3})["physical_active"]), "pair settings apply beyond the first two inputs");
    fakeState.panelAvailable = false;
    check(!bool(recorder.audioDevices()["has_control_panel"]) && fixture.execute("show_audio_driver_panel", object({}), fixture.snapshot().revision).failed(), "drivers without a native panel report unsupported and do not invoke it");
    fakeState.panelAvailable = true;
    select(input({2, 3})); okay(arm(), "arm current interface before panel");
    command(fixture, "set_input_monitor", object({{"track_id", trackId}, {"mode", "on"}}));
    bool rejectedNested = false;
    fakeState.panelAction = [&] {
        check(targetsDetached(), "audio targets remain detached inside the native panel callback");
        rejectedNested = recorder.execute("configure_audio_device", object({{"input_channels", array({0})}})).failed();
        recorder.poll();
        opened().rate = 44100;
    };
    command(fixture, "show_audio_driver_panel");
    check(fakeState.panelCalls == 1 && rejectedNested && double(recorder.audioDevices()["sample_rate"]) == 44100, "panel invocation rejects reentrant input changes and returns actual post-panel device state");
    check(fixture.snapshot().tracks.back().armed && fixture.snapshot().tracks.back().monitorMode == "on", "same-device panel return restores only the matching track's prior arm and monitor choices");
    fakeState.panelAction = {};
    fixture.togglePlay();
    check(fixture.snapshot().playing, "fixture starts actual playback before testing the native panel guard");
    check(fixture.execute("show_audio_driver_panel", object({}), fixture.snapshot().revision).failed(), "native panel is blocked during playback");
    fixture.stop();
    manager.closeAudioDevice();
}
