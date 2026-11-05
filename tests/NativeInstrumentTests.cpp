#include "apps/desktop/NativeInstrument.h"
#include <algorithm>
#include <cmath>
#include <iostream>
#include <stdexcept>

namespace {
juce::var args(std::initializer_list<std::pair<const char*, juce::var>> values)
{
    auto* object = new juce::DynamicObject;
    for (const auto& value : values) object->setProperty(value.first, value.second);
    return juce::var(object);
}
void require(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
}

int main()
{
    try {
        const auto file = juce::File::getSpecialLocation(juce::File::tempDirectory)
            .getChildFile("emusician-native-test-" + juce::Uuid().toString() + ".wav");
        struct DeleteFixture { juce::File file; ~DeleteFixture() { file.deleteFile(); } } cleanup { file };
        auto stream = file.createOutputStream(); require(stream != nullptr, "fixture stream");
        juce::WavAudioFormat wav;
        std::unique_ptr<juce::AudioFormatWriter> writer(wav.createWriterFor(stream.get(), 48000, 1, 16, {}, 0));
        require(writer != nullptr, "fixture writer"); stream.release();
        juce::AudioBuffer<float> tone(1, 256);
        for (int i = 0; i < 256; ++i) tone.setSample(0, i, 0.5f);
        require(writer->writeFromAudioSampleBuffer(tone, 0, 256), "fixture write"); writer.reset();

        emusician::storage::StoredProject project;
        emusician::storage::StoredTrack track; track.id = "track-a"; track.kind = "instrument";
        project.tracks.push_back(track);
        using emusician::native::mutate;
        require(mutate(project, "add_native_instrument", args({{"track_id", "track-a"}, {"type", "drum_rack"}})).wasOk(), "create rack");
        require(mutate(project, "add_native_instrument", args({{"track_id", "track-a"}, {"type", "sampler"}})).failed(), "existing instrument protected");
        require(mutate(project, "set_native_sample", args({{"track_id", "track-a"}, {"pad", 0}, {"path", file.getFullPathName()}})).wasOk(), "set sample");
        require(mutate(project, "set_native_sample", args({{"track_id", "track-a"}, {"pad", 1}, {"path", file.getFullPathName()}})).wasOk(), "reuse sample");
        require(project.assets.size() == 1, "shared path reuses asset");
        juce::var state; require(emusician::native::describe(project, "track-a", state).wasOk(), "describe rack");
        require(state["type"].toString() == "drum_rack" && state["pads"].getArray()->size() == 16, "16 pads");
        require(int(state["version"]) == 1, "default-equivalent instruments retain legacy version");
        std::map<juce::String, juce::File> assets {{project.assets[0].id, file}};
        std::unique_ptr<emusician::native::PreparedBank> bank;
        require(emusician::native::prepareBank(state, assets, 1, bank).wasOk(), "prepare rack");
        require(bank->bank.slots[0].minNote == 36 && bank->bank.slots[1].minNote == 37, "pad mapping");
        require(bank->samples[0] == bank->samples[1], "decoded sample sharing");
        require(std::abs(bank->bank.slots[0].attackSeconds - .003f) < .000001f && bank->bank.slots[0].oneShot, "legacy rack envelope defaults");
        emusician::sampler::Renderer renderer;
        float output[128] {};
        const emusician::sampler::Event note {0, emusician::sampler::EventType::noteOn, 1, 36, 1.0f};
        renderer.process(bank->bank, output, nullptr, 128, &note, 1, 48000);
        require(output[100] > 0.1f, "rack renders sample");
        require(mutate(project, "set_native_pad", args({{"track_id", "track-a"}, {"pad", 0}, {"gain_db", -3.0}, {"muted", false},
            {"attack_ms", 1.0}, {"release_ms", 1.0}, {"one_shot", false}})).wasOk(), "configure pad envelope and gate");
        require(emusician::native::describe(project, "track-a", state).wasOk(), "describe envelope");
        const auto first = state["pads"].getArray()->getReference(0);
        require(int(state["version"]) == 2, "nondefault envelope marks state version 2 to reject silent legacy downgrade");
        require(double(first["attack_ms"]) == 1 && double(first["release_ms"]) == 1 && !bool(first["one_shot"]), "envelope DTO round trip");
        require(mutate(project, "set_native_pad", args({{"track_id", "track-a"}, {"pad", 0}, {"gain_db", -3.0}, {"muted", false}, {"attack_ms", 0.0}})).failed(), "invalid envelope rejected");
        require(mutate(project, "set_native_pad", args({{"track_id", "track-a"}, {"pad", 0}, {"gain_db", -3.0}, {"muted", false}, {"one_shot", "true"}})).failed(), "nonboolean playback mode rejected");
        require(mutate(project, "set_native_pad", args({{"track_id", "track-a"}, {"pad", 0}, {"gain_db", 0.0}, {"muted", false}})).wasOk(), "legacy partial pad command");
        require(emusician::native::describe(project, "track-a", state).wasOk(), "describe preserved envelope");
        require(double(state["pads"].getArray()->getReference(0)["attack_ms"]) == 1, "legacy gain edit preserves envelope");
        auto loaded = std::move(bank); require(file.deleteFile(), "remove fixture to prove parameter edit has no source IO");
        require(emusician::native::prepareBank(state, assets, 2, bank, loaded.get()).wasOk(), "parameter edit reuses immutable loaded sample");
        require(bank->samples[0] == loaded->samples[0] && bank->sourceHashes == loaded->sourceHashes, "reused sample and identity retained");
        require(!bank->bank.slots[0].oneShot && std::abs(bank->bank.slots[0].attackSeconds - .001f) < .000001f, "configured envelope reaches renderer");
        renderer.reset(); std::fill(std::begin(output), std::end(output), 0.0f);
        const emusician::sampler::Event gateEvents[] {{0, emusician::sampler::EventType::noteOn, 1, 36, 1}, {64, emusician::sampler::EventType::noteOff, 1, 36, 0}};
        renderer.process(bank->bank, output, nullptr, 128, gateEvents, 2, 48000);
        require(output[47] > .4f && output[120] == 0, "configured attack and gate release shape audible output");
        bank->bank.slots[0].oneShot = true; ++bank->bank.generation; renderer.reset(); std::fill(std::begin(output), std::end(output), 0.0f);
        renderer.process(bank->bank, output, nullptr, 128, gateEvents, 2, 48000);
        require(output[120] > .4f, "one-shot ignores note-off with the same configured envelope");
        std::unique_ptr<emusician::native::PreparedBank> explicitReload;
        require(emusician::native::prepareBank(state, assets, 3, explicitReload).failed(), "explicit load still checks source file");
        assets.clear(); bank.reset();
        require(emusician::native::prepareBank(state, assets, 2, bank).failed() && !bank, "missing asset refused");
        std::cout << "Native instrument DTO and offline bank smoke passed.\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n'; return 1;
    }
}
