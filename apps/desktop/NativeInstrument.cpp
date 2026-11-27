#include "NativeInstrument.h"
#include <juce_cryptography/juce_cryptography.h>
#include <algorithm>
#include <cmath>

namespace emusician::native {
namespace te = tracktion;

namespace {
juce::var nativeState(const storage::StoredPlugin& plugin)
{
    if (plugin.state.getSize() == 0 || plugin.state.getSize() > 16384) return {};
    return juce::JSON::parse(juce::String::fromUTF8(static_cast<const char*>(plugin.state.getData()), int(plugin.state.getSize())));
}
void setNativeState(storage::StoredPlugin& plugin, const juce::var& state)
{
    auto encoded = state.clone();
    const bool defaultShot = encoded["type"].toString() == "drum_rack";
    bool extended = false;
    if (const auto* pads = encoded["pads"].getArray()) for (const auto& pad : *pads)
        extended = extended || double(pad.getProperty("attack_ms", 3.0)) != 3.0
            || double(pad.getProperty("release_ms", 30.0)) != 30.0
            || bool(pad.getProperty("one_shot", defaultShot)) != defaultShot;
    // Legacy binaries reject version 2 instead of silently discarding sound-
    // shaping settings. Default-equivalent instruments keep version 1.
    if (auto* data = encoded.getDynamicObject()) data->setProperty("version", extended ? 2 : 1);
    const auto json = juce::JSON::toString(encoded, true);
    plugin.state = juce::MemoryBlock(json.toRawUTF8(), json.getNumBytesAsUTF8());
}
storage::StoredTrack* findTrack(storage::StoredProject& project, const juce::String& id)
{
    for (auto& track : project.tracks) if (track.id == id) return &track;
    return nullptr;
}
storage::StoredPlugin* findNative(storage::StoredTrack& track)
{
    for (auto& plugin : track.plugins) if (plugin.format == "E-musician" && plugin.role == "instrument") return &plugin;
    return nullptr;
}
juce::var initialState(bool rack)
{
    auto* state = new juce::DynamicObject;
    state->setProperty("version", 1);
    state->setProperty("type", rack ? "drum_rack" : "sampler");
    state->setProperty("root_note", 60);
    state->setProperty("start", 0.0);
    state->setProperty("end", 1.0);
    juce::Array<juce::var> pads;
    for (int i = 0; i < (rack ? 16 : 1); ++i) {
        auto* pad = new juce::DynamicObject;
        pad->setProperty("asset_id", ""); pad->setProperty("gain_db", 0.0); pad->setProperty("muted", false);
        pad->setProperty("attack_ms", 3.0); pad->setProperty("release_ms", 30.0); pad->setProperty("one_shot", rack);
        pads.add(juce::var(pad));
    }
    state->setProperty("pads", pads);
    return juce::var(state);
}
bool integral(const juce::var& value) { return value.isInt() || value.isInt64(); }
bool numeric(const juce::var& value) { return integral(value) || value.isDouble(); }
}

juce::Result mutate(storage::StoredProject& project, const juce::String& command, const juce::var& args)
{
    if (!args.isObject() || !args["track_id"].isString()) return juce::Result::fail("A track ID is required.");
    auto* track = findTrack(project, args["track_id"].toString());
    if (!track || track->kind != "instrument") return juce::Result::fail("Choose a MIDI track.");
    if (command == "add_native_instrument") {
        const auto type = args["type"].toString();
        if (std::none_of(supportedInstrumentTypes.begin(),supportedInstrumentTypes.end(),[&](const auto* id){return type==id;})) return juce::Result::fail("Unknown native instrument type.");
        for (const auto& old : track->plugins)
            if (old.role == "instrument")
                return juce::Result::fail("This track already has an instrument. Remove it first or create another MIDI track.");
        storage::StoredPlugin plugin;
        plugin.id = juce::Uuid().toString(); plugin.format = "E-musician";
        plugin.identifier = "native." + type;
        plugin.name = type == "sampler" ? "Sampler" : "Drum Rack";
        plugin.manufacturer = "E-musician"; plugin.version = "1"; plugin.role = "instrument";
        setNativeState(plugin, initialState(type == "drum_rack"));
        track->plugins.insert(track->plugins.begin(), std::move(plugin));
        return juce::Result::ok();
    }
    auto* plugin = findNative(*track);
    if (!plugin) return juce::Result::fail("This track has no native instrument.");
    auto state = nativeState(*plugin);
    auto* data = state.getDynamicObject();
    auto* pads = state["pads"].getArray();
    if (!data || !pads) return juce::Result::fail("Invalid native instrument state.");
    if (command == "set_native_sampler") {
        if (plugin->identifier != "native.sampler" || !integral(args["root_note"]) || !numeric(args["start"]) || !numeric(args["end"]))
            return juce::Result::fail("Sampler requires an integer root note and numeric start/end.");
        const int root = int(args["root_note"]); const double start = double(args["start"]), end = double(args["end"]);
        if (root < 0 || root > 127 || !std::isfinite(start) || !std::isfinite(end) || start < 0 || end > 1 || start >= end)
            return juce::Result::fail("Invalid sampler root or normalized start/end.");
        data->setProperty("root_note", root); data->setProperty("start", start); data->setProperty("end", end);
    } else if (command == "set_native_sample" || command == "set_native_pad") {
        if (!integral(args["pad"])) return juce::Result::fail("Pad index must be an integer.");
        const int index = int(args["pad"]);
        if (index < 0 || index >= pads->size()) return juce::Result::fail("Pad index is out of range.");
        auto* pad = pads->getReference(index).getDynamicObject();
        if (!pad) return juce::Result::fail("Invalid pad.");
        if (command == "set_native_sample") {
            if (!args["path"].isString()) return juce::Result::fail("Sample path must be a string.");
            const auto path = args["path"].toString();
            juce::String id;
            if (path.isNotEmpty()) {
                if (!juce::File::isAbsolutePath(path)) return juce::Result::fail("Sample path must be absolute.");
                const juce::File file(path);
                for (const auto& asset : project.assets) if (asset.source == file) { id = asset.id; break; }
                if (id.isEmpty()) { id = juce::Uuid().toString(); project.assets.push_back({id, file}); }
            }
            pad->setProperty("asset_id", id);
        } else {
            if (!args["muted"].isBool() || (!args["gain_db"].isDouble() && !args["gain_db"].isInt() && !args["gain_db"].isInt64()))
                return juce::Result::fail("Pad needs a gain and mute state.");
            const double gain = double(args["gain_db"]);
            if (!std::isfinite(gain) || gain < -60 || gain > 6) return juce::Result::fail("Pad gain must be -60 to +6 dB.");
            for (const auto* key : {"attack_ms", "release_ms"}) if (args.hasProperty(key)) {
                const auto value = args[key]; const double low = juce::String(key) == "attack_ms" ? 0.1 : 1.0;
                const double high = juce::String(key) == "attack_ms" ? 2000.0 : 5000.0;
                if (!numeric(value) || !std::isfinite(double(value)) || double(value) < low || double(value) > high)
                    return juce::Result::fail("Invalid pad envelope time: " + juce::String(key));
            }
            if (args.hasProperty("one_shot") && !args["one_shot"].isBool()) return juce::Result::fail("Pad one_shot must be boolean.");
            pad->setProperty("gain_db", gain); pad->setProperty("muted", args["muted"]);
            for (const auto* key : {"attack_ms", "release_ms", "one_shot"}) if (args.hasProperty(key)) pad->setProperty(key, args[key]);
        }
    } else return juce::Result::fail("Unsupported native instrument command.");
    setNativeState(*plugin, state);
    return juce::Result::ok();
}

juce::Result describe(const storage::StoredProject& project, const juce::String& trackId, juce::var& result)
{
    result = juce::var();
    const storage::StoredTrack* track = nullptr;
    for (const auto& candidate : project.tracks) if (candidate.id == trackId) { track = &candidate; break; }
    if (!track) return juce::Result::fail("Track not found.");
    for (const auto& plugin : track->plugins) if (plugin.format == "E-musician" && plugin.role == "instrument") {
        auto state = nativeState(plugin);
        auto* pads = state["pads"].getArray();
        if (!state.isObject() || !pads) return juce::Result::fail("Invalid native instrument state.");
        for (int i = 0; i < pads->size(); ++i) {
            auto* pad = pads->getReference(i).getDynamicObject(); if (!pad) return juce::Result::fail("Invalid native pad.");
            const auto assetId = pad->getProperty("asset_id").toString(); juce::String path;
            for (const auto& asset : project.assets) if (asset.id == assetId) { path = asset.source.getFullPathName(); break; }
            pad->setProperty("index", i); pad->setProperty("note", 36 + i); pad->setProperty("path", path);
            if (!pad->hasProperty("attack_ms")) pad->setProperty("attack_ms", 3.0);
            if (!pad->hasProperty("release_ms")) pad->setProperty("release_ms", 30.0);
            if (!pad->hasProperty("one_shot")) pad->setProperty("one_shot", plugin.identifier == "native.drum_rack");
        }
        state.getDynamicObject()->setProperty("device_id", plugin.id);
        result = state;
        return juce::Result::ok();
    }
    result = initialState(false); result.getDynamicObject()->setProperty("type", "");
    return juce::Result::ok();
}

juce::Result prepareBank(const juce::var& state, const std::map<juce::String, juce::File>& assets,
                         std::uint64_t generation, std::unique_ptr<PreparedBank>& result, const PreparedBank* reusable)
{
    result.reset();
    if (!state.isObject()) return juce::Result::fail("Invalid native instrument state.");
    const auto type = state["type"].toString();
    const bool rack = type == "drum_rack";
    auto* pads = state["pads"].getArray();
    if ((!rack && type != "sampler") || !pads || pads->size() != (rack ? 16 : 1))
        return juce::Result::fail("Invalid native instrument pads.");
    const double start = double(state["start"]), end = double(state["end"]);
    const int root = int(state["root_note"]);
    if (!std::isfinite(start) || !std::isfinite(end) || start < 0 || end > 1 || start >= end || root < 0 || root > 127)
        return juce::Result::fail("Invalid native instrument sample range.");
    auto prepared = std::make_unique<PreparedBank>();
    prepared->bank.generation = generation;
    juce::AudioFormatManager formats;
    formats.registerBasicFormats();
    std::map<juce::String, std::shared_ptr<const SampleData>> cache;
    constexpr std::size_t maxDecodedBytes = 64u * 1024u * 1024u;
    std::size_t decodedBytes = 0;
    for (int i = 0; i < pads->size(); ++i) {
        const auto& pad = pads->getReference(i);
        if (!pad.isObject() || !pad["muted"].isBool()) return juce::Result::fail("Invalid native pad state.");
        const double db = double(pad["gain_db"]);
        if (!std::isfinite(db) || db < -60 || db > 6) return juce::Result::fail("Invalid native pad gain.");
        auto& slot = prepared->bank.slots[std::size_t(i)];
        slot.minNote = rack ? 36 + i : 0;
        slot.maxNote = rack ? 36 + i : 127;
        slot.rootNote = rack ? 36 + i : root;
        const auto attack = pad.getProperty("attack_ms", 3.0), release = pad.getProperty("release_ms", 30.0), oneShot = pad.getProperty("one_shot", rack);
        if (!numeric(attack) || !numeric(release) || !oneShot.isBool()
            || !std::isfinite(double(attack)) || double(attack) < 0.1 || double(attack) > 2000.0
            || !std::isfinite(double(release)) || double(release) < 1.0 || double(release) > 5000.0)
            return juce::Result::fail("Invalid native pad envelope or playback mode.");
        slot.attackSeconds = float(double(attack) / 1000.0); slot.releaseSeconds = float(double(release) / 1000.0);
        slot.oneShot = bool(oneShot);
        slot.muted = bool(pad["muted"]);
        slot.gain = juce::Decibels::decibelsToGain(float(db));
        const auto assetId = pad["asset_id"].toString();
        if (assetId.isEmpty()) continue;
        if (reusable && !cache.contains(assetId)) {
            for (std::size_t old = 0; old < sampler::maxSlots; ++old) {
                const auto& sample = reusable->samples[old]; const auto hash = reusable->sourceHashes.find(assetId);
                if (reusable->sampleAssets[old] != assetId || !sample || hash == reusable->sourceHashes.end() || hash->second.isEmpty()) continue;
                const auto bytes = (sample->left.size() + sample->right.size()) * sizeof(float);
                if (bytes > maxDecodedBytes - decodedBytes) return juce::Result::fail("Decoded native samples exceed the 64 MiB per-device limit.");
                decodedBytes += bytes; cache.emplace(assetId, sample); prepared->sourceHashes.emplace(assetId, hash->second); break;
            }
        }
        if (!cache.contains(assetId)) {
            const auto found = assets.find(assetId);
            if (found == assets.end() || !found->second.existsAsFile()) return juce::Result::fail("Native sample is missing: " + assetId);
            constexpr juce::int64 maxEncodedBytes = 64 * 1024 * 1024;
            const auto fileSize = found->second.getSize();
            if(fileSize<=0||fileSize>maxEncodedBytes)return juce::Result::fail("Sample source exceeds the 64 MiB file limit.");
            auto input=found->second.createInputStream();
            if(!input||input->getTotalLength()!=fileSize)return juce::Result::fail("Cannot open sample source.");
            juce::MemoryBlock bytes;
            input->readIntoMemoryBlock(bytes,static_cast<juce::ssize_t>(maxEncodedBytes+1));
            if(input->getStatus().failed()||bytes.getSize()!=std::size_t(fileSize))return juce::Result::fail("Could not read the complete sample source.");
            // Decode exactly the bytes that were hashed; later path changes
            // cannot make the audible bank disagree with this identity.
            const auto hash=juce::SHA256(bytes).toHexString();
            auto memory=std::make_unique<juce::MemoryInputStream>(bytes.getData(),bytes.getSize(),false);
            std::unique_ptr<juce::AudioFormatReader> reader(formats.createReaderFor(std::move(memory)));
            if (!reader || reader->lengthInSamples < 2 || reader->numChannels < 1 || reader->numChannels > 2
                || !std::isfinite(reader->sampleRate) || reader->sampleRate < 8000 || reader->sampleRate > 384000)
                return juce::Result::fail("Unsupported or invalid sample file: " + found->second.getFileName());
            const auto frames = std::uint64_t(reader->lengthInSamples);
            const auto channels = std::uint64_t(reader->numChannels);
            if (frames > (maxDecodedBytes - decodedBytes) / (channels * sizeof(float)))
                return juce::Result::fail("Decoded native samples exceed the 64 MiB per-device limit.");
            const auto length = int(frames);
            juce::AudioBuffer<float> buffer(int(channels), length);
            if (!reader->read(&buffer, 0, length, 0, true, true)) return juce::Result::fail("Could not decode sample: " + found->second.getFileName());
            auto data = std::make_shared<SampleData>();
            data->sampleRate = reader->sampleRate;
            data->left.assign(buffer.getReadPointer(0), buffer.getReadPointer(0) + length);
            if (channels == 2) data->right.assign(buffer.getReadPointer(1), buffer.getReadPointer(1) + length);
            for (auto* channel : { &data->left, &data->right })
                for (auto& value : *channel) if (!std::isfinite(value)) value = 0;
            decodedBytes += std::size_t(frames * channels * sizeof(float));
            cache.emplace(assetId, std::move(data));
            prepared->sourceHashes.emplace(assetId,hash);
        }
        const auto data = cache.at(assetId);
        prepared->samples[std::size_t(i)] = data;
        prepared->sampleAssets[std::size_t(i)] = assetId;
        prepared->sampleHashes[std::size_t(i)] = prepared->sourceHashes.at(assetId);
        slot.left = data->left.data();
        slot.right = data->right.empty() ? nullptr : data->right.data();
        slot.frames = data->left.size();
        slot.sampleRate = data->sampleRate;
        slot.startFrame = rack ? 0 : std::size_t(start * double(slot.frames));
        slot.endFrame = rack ? slot.frames : std::size_t(end * double(slot.frames));
        if (slot.endFrame <= slot.startFrame) return juce::Result::fail("Sample range is shorter than one frame.");
    }
    result = std::move(prepared);
    return juce::Result::ok();
}

static_assert(std::atomic<double>::is_always_lock_free);
static_assert(std::atomic<std::uint64_t>::is_always_lock_free);

Instrument::Instrument(te::PluginCreationInfo info) : te::Plugin(info) {}
Instrument::~Instrument() { notifyListenersOfDeletion(); }

void Instrument::initialise(const te::PluginInitialisationInfo& info)
{
    renderSampleRate.store(info.sampleRate, std::memory_order_release);
    panicPending.store(true, std::memory_order_release);
}
void Instrument::deinitialise() { panicPending.store(true, std::memory_order_release); }
void Instrument::reset() { panicPending.store(true, std::memory_order_release); }
void Instrument::midiPanic() { panicPending.store(true, std::memory_order_release); }

void Instrument::publish(std::unique_ptr<PreparedBank> next)
{
    jassert(juce::MessageManager::getInstance()->isThisTheMessageThread());
    if (!next) return;
    const auto* ptr = next.get();
    owned.push_back(std::move(next));
    active.store(ptr, std::memory_order_seq_cst);
    collectRetired();
}

void Instrument::collectRetired()
{
    if (readers.load(std::memory_order_seq_cst) != 0) return;
    const auto* keep = active.load(std::memory_order_seq_cst);
    std::erase_if(owned, [keep](const auto& item) { return item.get() != keep; });
}

std::map<juce::String, juce::String> Instrument::sourceHashes() const
{
    jassert(juce::MessageManager::getInstance()->isThisTheMessageThread());
    const auto* current=active.load(std::memory_order_seq_cst);
    return current ? current->sourceHashes : std::map<juce::String, juce::String>{};
}

bool Instrument::previewSample(int slot) noexcept
{
    jassert(juce::MessageManager::getInstance()->isThisTheMessageThread());
    if (slot < 0 || slot >= int(sampler::maxSlots)) return false;
    const auto* bank = active.load(std::memory_order_seq_cst);
    if (!bank || !bank->bank.slots[std::size_t(slot)].left || bank->bank.slots[std::size_t(slot)].muted) return false;
    previewRequest.store(slot + 2, std::memory_order_release);
    return true;
}

void Instrument::stopPreview() noexcept { previewRequest.store(1, std::memory_order_release); }

std::shared_ptr<const SampleData> Instrument::sampleForDisplay(int pad, const juce::String& expectedHash) const
{
    jassert(juce::MessageManager::getInstance()->isThisTheMessageThread());
    if (pad < 0 || pad >= int(sampler::maxSlots) || expectedHash.isEmpty()) return {};
    const auto* current = active.load(std::memory_order_seq_cst);
    if (!current || current->sampleHashes[std::size_t(pad)] != expectedHash) return {};
    return current->samples[std::size_t(pad)];
}

std::shared_ptr<const PreparedBank> Instrument::bankForConfiguration() const
{
    jassert(juce::MessageManager::getInstance()->isThisTheMessageThread());
    const auto* current = active.load(std::memory_order_seq_cst);
    return current ? std::make_shared<const PreparedBank>(*current) : nullptr;
}

void Instrument::applyToBuffer(const te::PluginRenderContext& context)
{
    if (!context.destBuffer || context.bufferNumSamples <= 0 || context.destBuffer->getNumChannels() == 0) return;
    // A single renderer owns voice state. Do not block a realtime callback if
    // a second graph ever attempts concurrent processing of this instance.
    if (rendering.test_and_set(std::memory_order_acquire)) {
        reentrantBlocks.fetch_add(1, std::memory_order_relaxed);
        panicPending.store(true, std::memory_order_release);
        return;
    }
    if (panicPending.exchange(false, std::memory_order_acq_rel)) { renderer.reset(); previewRenderer.reset(); }
    const auto rate = renderSampleRate.load(std::memory_order_acquire);
    readers.fetch_add(1, std::memory_order_seq_cst);
    const auto* published = active.load(std::memory_order_seq_cst);
    if (published) {
        int count = 0;
        bool overflow = false;
        if (auto* midi = context.bufferForMidiMessages) {
            if (midi->isAllNotesOff)
                for (int channel = 1; channel <= 16; ++channel)
                    events[std::size_t(count++)] = {0, sampler::EventType::allNotesOff, channel};
            for (const auto& message : *midi) {
                sampler::EventType kind;
                if (message.isNoteOn()) kind = sampler::EventType::noteOn;
                else if (message.isNoteOff()) kind = sampler::EventType::noteOff;
                else if (message.isAllSoundOff()) kind = sampler::EventType::allSoundOff;
                else if (message.isAllNotesOff()) kind = sampler::EventType::allNotesOff;
                else continue;
                if (count == sampler::maxEventsPerBlock) { overflow = true; break; }
                events[std::size_t(count++)] = {juce::jlimit(0, context.bufferNumSamples - 1,
                    juce::roundToInt(message.getTimeStamp() * rate)), kind,
                    message.getChannel(), message.getNoteNumber(), message.getFloatVelocity()};
            }
        }
        // Do not discard an unseen note-off and leave a stuck voice after MIDI
        // overflow. Drop that block's input and reset existing voices instead.
        if (overflow) { renderer.reset(); count = 0; }
        const auto priority = [](sampler::EventType type) {
            return type == sampler::EventType::noteOn ? 1 : 0;
        };
        std::sort(events.begin(), events.begin() + count, [&](const auto& a, const auto& b) {
            return a.offset != b.offset ? a.offset < b.offset : priority(a.type) < priority(b.type);
        });
        auto* left = context.destBuffer->getWritePointer(0, context.bufferStartSample);
        auto* right = context.destBuffer->getNumChannels() > 1
            ? context.destBuffer->getWritePointer(1, context.bufferStartSample) : nullptr;
        renderer.process(published->bank, left, right, context.bufferNumSamples, events.data(), count, rate);
        const auto preview = previewRequest.exchange(0, std::memory_order_acq_rel);
        sampler::Event audition;
        int auditionCount = 0;
        if (preview != 0) {
            previewRenderer.reset();
            if (preview >= 2 && preview < 2 + int(sampler::maxSlots)) {
                const auto& slot = published->bank.slots[std::size_t(preview - 2)];
                audition = { 0, sampler::EventType::noteOn, 1, slot.rootNote, 1.0f };
                auditionCount = 1;
            }
        }
        previewRenderer.process(published->bank, left, right, context.bufferNumSamples, &audition, auditionCount, rate);
    }
    readers.fetch_sub(1, std::memory_order_seq_cst);
    rendering.clear(std::memory_order_release);
}
}
