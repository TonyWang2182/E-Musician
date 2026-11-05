#include "ProjectStorage.h"
#include "NativeEffects.h"

#include <juce_cryptography/juce_cryptography.h>
#include <cmath>
#include <cstring>
#include <algorithm>
#include <array>
#include <limits>
#include <map>
#include <set>

namespace emusician::storage {
namespace {
using juce::File;
using juce::Result;
using juce::String;
using juce::var;

bool validIdentifier(const String& value)
{
    return value.isNotEmpty() && value.length() <= 128
        && value.containsOnly("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_");
}
bool validGain(double value) { return std::isfinite(value) && value >= -60.0 && value <= 6.0; }
bool integral(const var& value) { return value.isInt() || value.isInt64(); }
bool number(const var& value) { return integral(value) || value.isDouble(); }
bool validTime(double value) { return std::isfinite(value) && value >= 0.0 && value <= maximumTimelineSeconds; }
bool validPan(double value) { return std::isfinite(value) && value >= -1.0 && value <= 1.0; }
bool validSignature(int numerator, int denominator)
{
    return numerator >= 1 && numerator <= 32
        && (denominator == 1 || denominator == 2 || denominator == 4
            || denominator == 8 || denominator == 16 || denominator == 32);
}
bool cancelled(const IOOptions& options)
{
    try { return options.cancelled && options.cancelled(); }
    catch (...) { return true; }
}
Result cancellation() { return Result::fail("File operation cancelled before committing the project."); }
void progress(const IOOptions& options, double fraction, const String& stage)
{
    if (options.progress) {
        try { options.progress(juce::jlimit(0.0, 1.0, fraction), stage); }
        catch (...) { /* Progress observers cannot turn a committed save into a failure. */ }
    }
}

File assetRoot(const File& manifest)
{
    return manifest.getSiblingFile(manifest.getFileNameWithoutExtension() + ".assets");
}
Result validateLocation(const File& manifest)
{
    if (manifest == File() || !manifest.hasFileExtension("emproj"))
        return Result::fail("Choose an E-musician project file ending in .emproj.");
    if (!manifest.getParentDirectory().isDirectory())
        return Result::fail("The project folder does not exist: " + manifest.getParentDirectory().getFullPathName());
    if (manifest.isDirectory() || manifest.isSymbolicLink())
        return Result::fail("The project path must be a regular file, not a folder or link.");
    return Result::ok();
}

// The pinned JUCE JSON parser accumulates integer digits without overflow
// checks and permits duplicate keys/trailing data. Check these before parsing.
// This is a bounded lexical guard; JUCE remains responsible for JSON syntax.
Result checkJsonTokens(const juce::MemoryBlock& bytes)
{
    const auto* data = static_cast<const char*>(bytes.getData());
    const auto size = bytes.getSize();
    struct Level { char kind; std::set<String> keys; };
    std::vector<Level> levels;
    bool finished = false;
    char previous = 0;
    const auto space = [](char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n'; };
    const auto digit = [](char c) { return c >= '0' && c <= '9'; };
    for (std::size_t i = 0; i < size;) {
        const char c = data[i];
        if (space(c)) { ++i; continue; }
        if (c == 0 || finished) return Result::fail("The project JSON contains trailing or null data.");
        if (levels.empty() && c != '{') return Result::fail("The project must contain one JSON object.");
        if (c == '"') {
            const auto start = i++;
            bool closed = false;
            while (i < size) {
                const auto ch = static_cast<unsigned char>(data[i++]);
                if (ch < 0x20) return Result::fail("The project JSON contains an invalid string.");
                if (ch == '\\') {
                    if (i >= size || static_cast<unsigned char>(data[i]) < 0x20)
                        return Result::fail("The project JSON contains an invalid string escape.");
                    ++i;
                } else if (ch == '"') { closed = true; break; }
            }
            if (!closed) return Result::fail("The project JSON contains an unfinished string.");
            auto next = i;
            while (next < size && space(data[next])) ++next;
            if (next < size && data[next] == ':') {
                if (levels.back().kind != '{') return Result::fail("A JSON property is outside an object.");
                const auto text = String::fromUTF8(data + start, static_cast<int>(i - start));
                auto cursor = text.getCharPointer();
                var key;
                if (auto result = juce::JSON::parseQuotedString(cursor, key); result.failed()) return result;
                if (!levels.back().keys.insert(key.toString()).second)
                    return Result::fail("The project JSON contains a duplicate property: " + key.toString());
            }
            previous = '"';
            continue;
        }
        if (c == '{' || c == '[') {
            if (levels.size() >= 32) return Result::fail("The project JSON is nested too deeply.");
            levels.push_back({ c, {} }); previous = c; ++i; continue;
        }
        if (c == '}' || c == ']') {
            if (levels.empty() || levels.back().kind != (c == '}' ? '{' : '[') || previous == ',')
                return Result::fail("The project JSON has invalid object or array boundaries.");
            levels.pop_back(); finished = levels.empty(); previous = c; ++i; continue;
        }
        if (c == '-' || digit(c)) {
            if (c == '-') ++i;
            if (i >= size || !digit(data[i])) return Result::fail("The project JSON contains an invalid number.");
            const auto first = i;
            std::uint64_t value = 0;
            constexpr auto limit = static_cast<std::uint64_t>(std::numeric_limits<juce::int64>::max());
            while (i < size && digit(data[i])) {
                const auto next = static_cast<std::uint64_t>(data[i] - '0');
                if (value > (limit - next) / 10)
                    return Result::fail("A project JSON integer exceeds the supported int64 range.");
                value = value * 10 + next; ++i;
            }
            if (i - first > 1 && data[first] == '0')
                return Result::fail("The project JSON contains a number with a leading zero.");
            if (i < size && data[i] == '.') {
                ++i;
                if (i >= size || !digit(data[i])) return Result::fail("The project JSON contains an invalid decimal.");
                while (i < size && digit(data[i])) ++i;
            }
            if (i < size && (data[i] == 'e' || data[i] == 'E')) {
                ++i;
                if (i < size && (data[i] == '+' || data[i] == '-')) ++i;
                if (i >= size || !digit(data[i])) return Result::fail("The project JSON contains an invalid exponent.");
                int exponent = 0;
                while (i < size && digit(data[i])) {
                    const int next = data[i++] - '0';
                    // JUCE also accumulates exponents in an unchecked int.
                    if (exponent > (1000000 - next) / 10)
                        return Result::fail("A project JSON exponent exceeds the supported range.");
                    exponent = exponent * 10 + next;
                }
            }
            if (i < size && !space(data[i]) && data[i] != ',' && data[i] != '}' && data[i] != ']')
                return Result::fail("The project JSON contains an invalid number boundary.");
            previous = '0';
            continue;
        }
        previous = c; ++i;
    }
    return finished ? Result::ok() : Result::fail("The project JSON is incomplete.");
}

Result nativeAssetIds(const StoredPlugin& plugin, std::vector<String>& result)
{
    result.clear();
    if (plugin.format != "E-musician") return Result::ok();
    if (plugin.role == "effect") {
        if (plugin.state.getSize() == 0 || plugin.state.getSize() > maximumNativeDeviceStateBytes)
            return Result::fail("Native effect state is empty or exceeds 16 KiB.");
        if (auto status = checkJsonTokens(plugin.state); status.failed()) return status;
        native_effects::Settings settings; return native_effects::decode(plugin, settings);
    }
    const bool sampler = plugin.identifier == "native.sampler";
    const bool rack = plugin.identifier == "native.drum_rack";
    if ((!sampler && !rack) || plugin.role != "instrument")
        return Result::fail("A native instrument has an unsupported identity or role.");
    if (plugin.state.getSize() == 0 || plugin.state.getSize() > maximumNativeDeviceStateBytes)
        return Result::fail("Native instrument state is empty or exceeds 16 KiB.");
    if (auto status = checkJsonTokens(plugin.state); status.failed())
        return Result::fail("Invalid native instrument state: " + status.getErrorMessage());
    var parsed;
    const auto json = String::fromUTF8(static_cast<const char*>(plugin.state.getData()), static_cast<int>(plugin.state.getSize()));
    if (auto status = juce::JSON::parse(json, parsed); status.failed())
        return Result::fail("Cannot parse native instrument state: " + status.getErrorMessage());
    const auto version = parsed.getProperty("version", {}), type = parsed.getProperty("type", {});
    const auto root = parsed.getProperty("root_note", {}), start = parsed.getProperty("start", {}), end = parsed.getProperty("end", {});
    const auto pads = parsed.getProperty("pads", {});
    if (!parsed.isObject() || !integral(version) || (juce::int64(version) != 1 && juce::int64(version) != 2) || !type.isString()
        || type.toString() != (sampler ? "sampler" : "drum_rack")
        || !integral(root) || juce::int64(root) < 0 || juce::int64(root) > 127
        || !number(start) || !number(end) || !std::isfinite(double(start)) || !std::isfinite(double(end))
        || double(start) < 0 || double(end) > 1 || double(start) >= double(end)
        || !pads.isArray() || pads.size() != (sampler ? 1 : 16))
        return Result::fail("Native instrument state has an invalid version, type, range or pad count.");
    std::vector<String> candidate;
    for (const auto& pad : *pads.getArray()) {
        const auto id = pad.getProperty("asset_id", {}), gain = pad.getProperty("gain_db", {}), muted = pad.getProperty("muted", {});
        if (!pad.isObject() || !id.isString() || !number(gain) || !validGain(double(gain)) || !muted.isBool()
            || (id.toString().isNotEmpty() && !validIdentifier(id.toString())))
            return Result::fail("A native instrument pad has invalid asset ID, gain or mute state.");
        for (const auto* field : {"attack_ms", "release_ms"}) if (pad.hasProperty(field)) {
            const auto value = pad[field]; const bool attack = juce::String(field) == "attack_ms";
            if (!number(value) || !std::isfinite(double(value)) || double(value) < (attack ? .1 : 1.0) || double(value) > (attack ? 2000.0 : 5000.0))
                return Result::fail("A native instrument envelope is outside its supported range.");
        }
        if (pad.hasProperty("one_shot") && !pad["one_shot"].isBool())
            return Result::fail("A native instrument playback mode must be boolean.");
        if (id.toString().isNotEmpty()) candidate.push_back(id.toString());
    }
    result = std::move(candidate);
    return Result::ok();
}

Result readBytes(const File& file, juce::MemoryBlock& bytes)
{
    if (!file.existsAsFile() || file.getSize() <= 0 || file.getSize() > maximumManifestBytes)
        return Result::fail("The project file is missing, empty, or larger than 16 MiB.");
    auto input = file.createInputStream();
    if (!input) return Result::fail("The project file cannot be opened.");
    bytes.reset();
    input->readIntoMemoryBlock(bytes, static_cast<juce::ssize_t>(maximumManifestBytes + 1));
    if (input->getStatus().failed() || bytes.getSize() == 0
        || bytes.getSize() > static_cast<std::size_t>(maximumManifestBytes))
        return Result::fail("The project file could not be read within the 16 MiB limit.");
    return Result::ok();
}
Result readJson(const File& file, juce::MemoryBlock& bytes, var& parsed)
{
    if (auto result = readBytes(file, bytes); result.failed()) return result;
    if (auto result = checkJsonTokens(bytes); result.failed()) return result;
    if (auto result = juce::JSON::parse(bytes.toString(), parsed); result.failed())
        return Result::fail("The project JSON is damaged: " + result.getErrorMessage());
    return Result::ok();
}


#include "ProjectStorageAnalysis.inc"

Result validateProject(const StoredProject& project, bool allowLegacy, bool verifySources)
{
    if (project.schemaVersion != 4 && project.schemaVersion != 5 && !(allowLegacy && project.schemaVersion >= 1 && project.schemaVersion <= 3))
        return Result::fail("Saving requires a fully resolved schema 4 or 5 project.");
    if (auto result=validateAnalysis(project);result.failed())return result;
    if (!validIdentifier(project.projectId)) return Result::fail("The project ID is missing or invalid.");
    if (project.revision > static_cast<std::uint64_t>(std::numeric_limits<juce::int64>::max()))
        return Result::fail("The project revision exceeds the supported integer range.");
    if (!validGain(project.masterGainDb)) return Result::fail("Master gain must be between -60 and +6 dB.");
    if (!std::isfinite(project.bpm) || project.bpm < minimumBpm || project.bpm > maximumBpm)
        return Result::fail("Tempo must be between 20 and 300 BPM.");
    if (!validSignature(project.numerator, project.denominator)) return Result::fail("The time signature is not supported.");
    if (!validTime(project.loopStart) || !validTime(project.loopEnd)
        || !((project.loopStart == 0.0 && project.loopEnd == 0.0) || project.loopEnd > project.loopStart))
        return Result::fail("The loop range must be automatic (0, 0) or a positive range within 48 hours.");
    if (project.tracks.size() > maximumTracks) return Result::fail("This project version supports at most 64 tracks.");
    if (project.assets.size() > maximumAssets) return Result::fail("This project version supports at most 4096 audio assets.");

    std::set<String> assetIds, foldedAssets, trackIds, clipIds, noteIds, pluginIds, referencedAssets;
    std::size_t pluginCount = 0, pluginStateBytes = 0;
    const auto validatePlugins = [&](const std::vector<StoredPlugin>& plugins, bool instrumentTrack) -> Result {
        if (plugins.size() > maximumPlugins - pluginCount)
            return Result::fail("This project supports at most 256 plugin instances.");
        pluginCount += plugins.size();
        bool hasInstrument = false;
        for (std::size_t index = 0; index < plugins.size(); ++index) {
            const auto& plugin = plugins[index];
            if (!validIdentifier(plugin.id) || !pluginIds.insert(plugin.id.toLowerCase()).second)
                return Result::fail("Plugin instance IDs must be valid and unique.");
            if ((plugin.format != "VST" && plugin.format != "VST3" && plugin.format != "E-musician")
                || plugin.identifier.isEmpty() || plugin.identifier.length() > 4096
                || plugin.name.length() > 512 || plugin.manufacturer.length() > 512 || plugin.version.length() > 128)
                return Result::fail("A plugin contains an unsupported format or invalid identity.");
            if (plugin.role == "instrument") {
                if (!instrumentTrack || hasInstrument || index != 0)
                    return Result::fail("An instrument track may have one instrument in its first plugin slot.");
                hasInstrument = true;
            } else if (plugin.role != "effect") {
                return Result::fail("A plugin role must be instrument or effect.");
            }
            if (plugin.state.getSize() > maximumPluginStateBytes
                || plugin.state.getSize() > maximumTotalPluginStateBytes - pluginStateBytes)
                return Result::fail("Plugin state exceeds the 64 MiB per-instance or 256 MiB project limit.");
            pluginStateBytes += plugin.state.getSize();
            std::vector<String> nativeRefs;
            if (auto status = nativeAssetIds(plugin, nativeRefs); status.failed()) return status;
            referencedAssets.insert(nativeRefs.begin(), nativeRefs.end());
        }
        return Result::ok();
    };
    if (auto result = validatePlugins(project.masterPlugins, false); result.failed()) return result;
    for (const auto& asset : project.assets) {
        if (!validIdentifier(asset.id) || !foldedAssets.insert(asset.id.toLowerCase()).second)
            return Result::fail("Asset IDs must be valid and unique.");
        assetIds.insert(asset.id);
        if (!asset.source.hasFileExtension("wav;mp3")
            || (verifySources && (!asset.source.existsAsFile() || asset.source.getSize() <= 0)))
            return Result::fail("An audio source is missing or empty: " + asset.source.getFullPathName());
    }
    std::size_t clipCount = 0, noteCount = 0;
    const double maximumBeats = maximumTimelineSeconds * project.bpm / 60.0;
    for (const auto& track : project.tracks) {
        if (!validIdentifier(track.id) || !trackIds.insert(track.id.toLowerCase()).second)
            return Result::fail("Track IDs must be valid and unique.");
        if (track.name.length() > 512) return Result::fail("Track names must be no longer than 512 characters.");
        if (!validGain(track.gainDb)) return Result::fail("Track gain must be between -60 and +6 dB: " + track.name);
        if (!validPan(track.pan)) return Result::fail("Track pan must be between -1 and 1.");
        if (track.kind != "audio" && track.kind != "instrument" && track.kind != "bus") return Result::fail("Unsupported track kind.");
        if (track.kind == "bus" && !track.clips.empty()) return Result::fail("Bus tracks cannot contain clips.");
        if (auto result = validatePlugins(track.plugins, track.kind == "instrument"); result.failed()) return result;
        if (track.clips.size() > maximumClips - clipCount)
            return Result::fail("This project version supports at most 4096 clips.");
        clipCount += track.clips.size();
        for (const auto& clip : track.clips) {
            if (!validIdentifier(clip.id) || !clipIds.insert(clip.id.toLowerCase()).second)
                return Result::fail("Clip IDs must be valid and unique across all tracks.");
            if(clip.analysisRole.isNotEmpty()&&(project.schemaVersion!=5||clip.kind!="audio"||(clip.analysisRole!="vocals"&&clip.analysisRole!="drums"&&clip.analysisRole!="bass"&&clip.analysisRole!="other")))return Result::fail("Invalid clip analysis role.");
            if (clip.kind == "audio") {
                if (track.kind != "audio" || !clip.notes.empty() || !clip.controllers.empty()) return Result::fail("Audio clips belong on audio tracks and cannot contain MIDI events.");
                if (!validIdentifier(clip.assetId) || assetIds.count(clip.assetId) == 0)
                    return Result::fail("A clip references an unknown audio asset: " + clip.id);
                referencedAssets.insert(clip.assetId);
                const bool legacyDuration = allowLegacy && project.schemaVersion == 1 && clip.duration == 0.0;
                if (!validTime(clip.timelineStart) || !validTime(clip.sourceOffset) || !validTime(clip.duration)
                    || (!legacyDuration && clip.duration <= 0.0)
                    || clip.timelineStart + clip.duration > maximumTimelineSeconds
                    || clip.sourceOffset + clip.duration > maximumTimelineSeconds
                    || (!legacyDuration && (!(clip.timelineStart + clip.duration > clip.timelineStart)
                        || !(clip.sourceOffset + clip.duration > clip.sourceOffset))))
                    return Result::fail("Clip positions and source ranges must be finite, non-negative, and within 48 hours: " + clip.id);
                if (!validTime(clip.fadeIn) || !validTime(clip.fadeOut) || clip.fadeIn + clip.fadeOut > clip.duration + 1.0e-9)
                    return Result::fail("Audio fades must be non-negative and fit within the clip.");
            } else if (clip.kind == "midi") {
                if (track.kind != "instrument" || clip.assetId.isNotEmpty() || clip.sourceOffset != 0.0
                    || clip.fadeIn != 0.0 || clip.fadeOut != 0.0)
                    return Result::fail("MIDI clips belong on instrument tracks and cannot reference audio assets or fades.");
                if (!validTime(clip.timelineStart) || !validTime(clip.duration)
                    || !std::isfinite(clip.startBeats) || !std::isfinite(clip.lengthBeats)
                    || clip.startBeats < 0.0 || clip.lengthBeats <= 0.0
                    || !(clip.startBeats + clip.lengthBeats > clip.startBeats)
                    || clip.startBeats + clip.lengthBeats > maximumBeats)
                    return Result::fail("A MIDI clip has an invalid beat range.");
                if (clip.notes.size() > maximumNotes - noteCount) return Result::fail("A project supports at most 100000 MIDI notes.");
                noteCount += clip.notes.size();
                for (const auto& note : clip.notes) {
                    if (!validIdentifier(note.id) || !noteIds.insert(note.id.toLowerCase()).second)
                        return Result::fail("Note IDs must be valid and unique across the project.");
                    if (note.channel != clip.notes.front().channel)
                        return Result::fail("All notes in one MIDI clip must use the same MIDI channel.");
                    if (note.pitch < 0 || note.pitch > 127 || note.velocity < 1 || note.velocity > 127
                        || note.channel < 1 || note.channel > 16 || !std::isfinite(note.startBeats)
                        || !std::isfinite(note.lengthBeats) || note.startBeats < 0.0 || note.lengthBeats <= 0.0
                        || !(note.startBeats + note.lengthBeats > note.startBeats)
                        || note.startBeats + note.lengthBeats > clip.lengthBeats + 1.0e-9)
                        return Result::fail("A MIDI note has an invalid pitch, velocity, channel, or clip-relative beat range. Track: "
                            + track.name + ", clip: " + clip.id + ", note: " + note.id
                            + "; pitch=" + String(note.pitch) + ", velocity=" + String(note.velocity) + ", channel=" + String(note.channel)
                            + ", start=" + String(note.startBeats, 12) + ", length=" + String(note.lengthBeats, 12)
                            + ", clip length=" + String(clip.lengthBeats, 12));
                }
            } else return Result::fail("Unsupported clip kind.");
        }
    }
    for (const auto& id : referencedAssets)
        if (!assetIds.contains(id)) return Result::fail("A native instrument references an unknown audio asset: " + id);
    if (referencedAssets.size() != project.assets.size())
        return Result::fail("Unreferenced audio assets are not supported by this project version.");
    std::map<String, const StoredTrack*> graphTracks;
    for (const auto& track : project.tracks) graphTracks.emplace(track.id, &track);
    std::map<String, std::vector<String>> edges;
    std::set<String> sendIds, laneIds, pointIds, controllerIds;
    std::size_t sendCount = 0, laneCount = 0, pointCount = 0, controllerCount = 0;
    const auto validateAutomation = [&](const auto& lanes, const auto& plugins, bool master) -> Result {
        if (lanes.size() > maximumAutomationLanesPerTrack || lanes.size() > maximumAutomationLanes - laneCount)
            return Result::fail("Automation exceeds the 256-lane owner or 4096-lane project limit.");
        laneCount += lanes.size();
        std::set<String> targets;
        for (const auto& lane : lanes) {
            if (!validIdentifier(lane.id) || !laneIds.insert(lane.id.toLowerCase()).second)
                return Result::fail("Automation lane IDs must be valid and unique.");
            if (lane.target != "plugin_parameter" && !(master ? lane.target == "master_gain" : (lane.target == "track_gain" || lane.target == "track_pan")))
                return Result::fail("Unsupported automation target.");
            if (lane.target == "plugin_parameter") {
                if (!validIdentifier(lane.pluginId) || lane.parameterId.isEmpty() || lane.parameterId.length() > 512
                    || std::none_of(plugins.begin(), plugins.end(), [&](const auto& p) { return p.id == lane.pluginId; }))
                    return Result::fail("Plugin automation must reference a plugin slot on its owner and a stable parameter ID.");
            } else if (lane.pluginId.isNotEmpty() || lane.parameterId.isNotEmpty()) {
                return Result::fail("Gain/pan automation cannot contain plugin identity fields.");
            }
            if (!targets.insert(lane.target + ":" + lane.pluginId + ":" + lane.parameterId).second)
                return Result::fail("Only one automation lane per owner/parameter is supported.");
            if (lane.points.size() > maximumAutomationPoints - pointCount)
                return Result::fail("A project supports at most 100000 automation points.");
            pointCount += lane.points.size();
            double previous = -1;
            for (const auto& point : lane.points) {
                if (!validIdentifier(point.id) || !pointIds.insert(point.id.toLowerCase()).second
                    || !validTime(point.timeSeconds) || point.timeSeconds <= previous
                    || !std::isfinite(point.value) || point.value < 0 || point.value > 1
                    || !std::isfinite(point.curve) || point.curve < -1 || point.curve > 1)
                    return Result::fail("Automation points need unique IDs, increasing times, values 0..1 and curves -1..1.");
                previous = point.timeSeconds;
            }
        }
        return Result::ok();
    };
    if (auto result = validateAutomation(project.masterAutomation, project.masterPlugins, true); result.failed()) return result;
    const auto busTarget = [&](const String& id) { auto it = graphTracks.find(id); return it != graphTracks.end() && it->second->kind == "bus"; };
    for (const auto& track : project.tracks) {
        if (track.inputDeviceId.length() > 1024 || (track.kind == "bus" && track.inputDeviceId.isNotEmpty()))
            return Result::fail("Input device identity is invalid for this track.");
        if (track.outputTargetId != "master" && !busTarget(track.outputTargetId))
            return Result::fail("Track output must be master or an existing bus.");
        if (track.outputTargetId != "master") edges[track.id].push_back(track.outputTargetId);
        if (track.sends.size() > maximumSendsPerTrack || track.sends.size() > maximumSends - sendCount)
            return Result::fail("Routing exceeds the 32-send track or 512-send project limit.");
        sendCount += track.sends.size();
        std::set<String> targets;
        for (const auto& send : track.sends) {
            if (!validIdentifier(send.id) || !sendIds.insert(send.id.toLowerCase()).second || !busTarget(send.targetTrackId)
                || !targets.insert(send.targetTrackId).second || !validGain(send.gainDb))
                return Result::fail("Sends require unique IDs, distinct bus targets and gain between -60 and +6 dB.");
            edges[track.id].push_back(send.targetTrackId); // Disabled connections cannot hide a feedback cycle.
        }
        if (auto result = validateAutomation(track.automation, track.plugins, false); result.failed()) return result;
        for (const auto& clip : track.clips) {
            if (clip.controllers.size() > maximumControllerEvents - controllerCount)
                return Result::fail("A project supports at most 100000 MIDI controller events.");
            controllerCount += clip.controllers.size();
            for (const auto& event : clip.controllers) {
                const bool type = (event.type >= 0 && event.type <= 127) || event.type == 0x1001
                    || event.type == 0x1004 || event.type == 0x1005 || event.type == 0x1007;
                if (!validIdentifier(event.id) || !controllerIds.insert(event.id.toLowerCase()).second || !type
                    || event.value < 0 || event.value > 16383 || event.metadata < 0 || event.metadata > 127
                    || !std::isfinite(event.beats) || event.beats < 0 || event.beats > clip.lengthBeats)
                    return Result::fail("A MIDI controller has an invalid ID, type, 14-bit value or clip-relative time.");
            }
        }
    }
    std::map<String, int> colour;
    const std::function<bool(const String&)> visit = [&](const String& id) {
        if (colour[id] == 1) return false;
        if (colour[id] == 2) return true;
        colour[id] = 1;
        for (const auto& destination : edges[id]) if (!visit(destination)) return false;
        colour[id] = 2; return true;
    };
    for (const auto& track : project.tracks) if (!visit(track.id)) return Result::fail("Routing contains a feedback cycle.");
    return Result::ok();
}

// Only files created inside our fresh generation are removed on failure.
// Unexpected files prevent directory removal; there is no recursive deletion.
struct AssetCleanup {
    File directory;
    std::vector<File> files;
    bool keep = false;
    ~AssetCleanup()
    {
        if (keep) return;
        for (const auto& file : files) file.deleteFile();
        if (directory != File()) directory.deleteFile();
    }
};

Result resolveBundleFile(const File& manifest, const String& filename, const String& path, File& source, bool allowEmpty)
{
    if (path.isEmpty() || File::isAbsolutePath(path) || path.containsChar(':'))
        return Result::fail("Project paths must be relative to the project bundle.");
    const auto normal = path.replaceCharacter('\\', '/');
    const auto parts = juce::StringArray::fromTokens(normal, "/", "");
    const auto root = assetRoot(manifest);
    if (parts.size() != 3 || parts.joinIntoString("/") != normal
        || parts[0] != root.getFileName() || !validIdentifier(parts[1]) || parts[2] != filename)
        return Result::fail("A project path is outside its expected asset generation.");
    const auto generation = root.getChildFile(parts[1]);
    const auto candidate = generation.getChildFile(parts[2]);
    if (!candidate.isAChildOf(root) || root.isSymbolicLink() || generation.isSymbolicLink() || candidate.isSymbolicLink())
        return Result::fail("Linked or escaped project assets are not supported.");
    if (!candidate.existsAsFile() || (!allowEmpty && candidate.getSize() <= 0))
        return Result::fail("A project asset is missing or empty: " + candidate.getFullPathName());
    source = candidate;
    return Result::ok();
}
Result resolveSource(const File& manifest, const String& id, const String& path, File& source)
{
    const auto normal = path.replaceCharacter('\\', '/');
    const auto filename = normal.fromLastOccurrenceOf("/", false, false);
    if (filename != id + ".wav" && filename != id + ".mp3")
        return Result::fail("An asset filename does not match its asset ID.");
    return resolveBundleFile(manifest, filename, path, source, false);
}

Result readTrackMetadata(const juce::DynamicObject& object, StoredTrack& stored)
{
    const auto id = object.getProperty("id"), name = object.getProperty("name");
    const auto gain = object.getProperty("gain_db"), muted = object.getProperty("muted"), solo = object.getProperty("solo");
    if (!id.isString() || !validIdentifier(id.toString()) || !name.isString() || name.toString().length() > 512
        || !number(gain) || !validGain(static_cast<double>(gain)) || !muted.isBool() || !solo.isBool())
        return Result::fail("A track contains missing or invalid fields.");
    stored.id = id.toString(); stored.name = name.toString();
    stored.gainDb = static_cast<float>(static_cast<double>(gain));
    stored.muted = static_cast<bool>(muted); stored.solo = static_cast<bool>(solo);
    return Result::ok();
}

Result createLegacyBackup(const File& target, const juce::MemoryBlock& bytes, int schema)
{
    const auto label = "schema" + String(schema);
    const auto backup = target.getSiblingFile(target.getFileName() + "." + label + "-" + juce::Uuid().toString() + ".bak");
    if (backup.exists()) return Result::fail("Could not allocate a unique legacy project backup.");
    auto output = backup.createOutputStream();
    if (!output) return Result::fail("Could not create the " + label + " backup; the project has not been replaced.");
    const bool written = output->write(bytes.getData(), bytes.getSize());
    output->flush();
    const auto status = output->getStatus();
    output.reset();
    juce::MemoryBlock verified;
    const auto verifiedResult = readBytes(backup, verified);
    if (!written || status.failed() || verifiedResult.failed() || verified != bytes) {
        backup.deleteFile();
        return Result::fail("Could not verify the " + label + " backup; the project has not been replaced.");
    }
    // Keep a valid backup even if the subsequent manifest replacement fails.
    // To restore, copy these exact bytes back to target's original filename.
    return Result::ok();
}

struct TransferProgress {
    const IOOptions& options;
    double total = 0.0, done = 0.0;
    juce::int64 written = 0, reused = 0;
    juce::uint32 lastReport = 0;
    void reportBytes() const
    {
        if (options.transferred) try { options.transferred(written, reused); } catch (...) {}
    }
    void add(std::size_t count, const String& stage, bool isWrite = true)
    {
        done += static_cast<double>(count);
        (isWrite ? written : reused) += static_cast<juce::int64>(count);
        const auto now = juce::Time::getMillisecondCounter();
        if (now - lastReport >= 50 || done >= total) {
            progress(options, 0.05 + 0.90 * (total > 0.0 ? done / total : 1.0), stage);
            reportBytes();
            lastReport = now;
        }
    }
};

struct ReusedAsset {
    File file;
    juce::int64 size = 0;
    juce::Time modified;
    bool unchanged() const
    {
        return file.existsAsFile() && !file.isSymbolicLink() && !file.getParentDirectory().isSymbolicLink()
            && file.getSize() == size && file.getLastModificationTime() == modified;
    }
};

// JUCE's SHA256 consumes 64-byte chunks. Buffer file reads and poll the
// existing cancellation callback at bounded byte intervals, on the file worker.
struct CheckedHashInput final : juce::InputStream {
    juce::BufferedInputStream input;
    const IOOptions& options;
    juce::int64 consumed = 0, nextCheck = 0;
    bool stopped = false;
    CheckedHashInput(juce::InputStream& stream, const IOOptions& opts) : input(stream, 65536), options(opts) {}
    juce::int64 getTotalLength() override { return input.getTotalLength(); }
    juce::int64 getPosition() override { return input.getPosition(); }
    bool setPosition(juce::int64 position) override { return input.setPosition(position); }
    bool isExhausted() override { return stopped || input.isExhausted(); }
    int read(void* destination, int bytes) override {
        if (consumed >= nextCheck) {
            nextCheck = consumed + 65536;
            if (cancelled(options)) { stopped = true; return 0; }
        }
        const int amount = input.read(destination, bytes);
        consumed += amount;
        return amount;
    }
};

Result verifyExpectedAsset(const File& file, const String& expected, const IOOptions& options)
{
    if (cancelled(options)) return cancellation();
    const auto size = file.getSize();
    const auto timestamp = file.getLastModificationTime();
    if (size <= 0 || file.isSymbolicLink() || file.getParentDirectory().isSymbolicLink())
        return Result::fail("A native sample archive is missing or linked.");
    auto input = file.createInputStream();
    if (!input || input->getTotalLength() != size) return Result::fail("Could not open native sample archive for verification.");
    CheckedHashInput stream(*input, options);
    const auto actual = juce::SHA256(stream, size).toHexString();
    if (stream.stopped || cancelled(options)) return cancellation();
    if (stream.consumed != size || input->getStatus().failed() || file.getSize() != size
        || file.getLastModificationTime() != timestamp || file.isSymbolicLink() || file.getParentDirectory().isSymbolicLink())
        return Result::fail("A native sample archive changed during verification.");
    if (actual != expected.toLowerCase())
        return Result::fail("A native sample changed since it was loaded. Reload the sample before saving.");
    return Result::ok();
}
// The comparison is bounded and cancellable on the file worker. A Save As to
// another bundle never sees these candidates, so it remains self-contained.
Result canReuseAudio(const File& source, const File& archived, const IOOptions& options, bool& same)
{
    same = false;
    if (cancelled(options)) return cancellation();
    const auto size = source.getSize(), archivedSize = archived.getSize();
    const auto sourceTime = source.getLastModificationTime(), archivedTime = archived.getLastModificationTime();
    if (size <= 0 || size != archivedSize) return Result::ok();
    if (source == archived) { same = true; return Result::ok(); }
    auto input = source.createInputStream(), previous = archived.createInputStream();
    if (!input || !previous) return Result::fail("Could not compare an existing project asset.");
    juce::HeapBlock<char> a(65536), b(65536);
    for (juce::int64 remaining = size; remaining > 0;) {
        if (cancelled(options)) return cancellation();
        const int count = static_cast<int>(juce::jmin<juce::int64>(remaining, 65536));
        if (input->read(a.getData(), count) != count || previous->read(b.getData(), count) != count)
            return Result::fail("An audio source changed while comparing it with the archive.");
        if (std::memcmp(a.getData(), b.getData(), static_cast<std::size_t>(count)) != 0) return Result::ok();
        remaining -= count;
    }
    if (input->getStatus().failed() || previous->getStatus().failed() || source.getSize() != size
        || archived.getSize() != size || source.getLastModificationTime() != sourceTime
        || archived.getLastModificationTime() != archivedTime)
        return Result::fail("An audio source changed while comparing it with the archive.");
    same = true; return Result::ok();
}

Result copyAudio(const File& source, const File& destination, TransferProgress& transfer)
{
    if (cancelled(transfer.options)) return cancellation();
    const auto size = source.getSize();
    const auto modified = source.getLastModificationTime();
    auto input = source.createInputStream();
    auto output = destination.createOutputStream();
    if (!input || !output || size <= 0 || input->getTotalLength() != size)
        return Result::fail("Could not open audio for archiving: " + source.getFileName());
    juce::HeapBlock<char> buffer(65536);
    juce::int64 remaining = size;
    while (remaining > 0) {
        if (cancelled(transfer.options)) return cancellation();
        const int count = static_cast<int>(juce::jmin<juce::int64>(remaining, 65536));
        if (input->read(buffer.getData(), count) != count || !output->write(buffer.getData(), static_cast<std::size_t>(count)))
            return Result::fail("Could not archive complete audio: " + source.getFileName());
        remaining -= count;
        transfer.add(static_cast<std::size_t>(count), "Copying audio: " + source.getFileName());
    }
    output->flush();
    if (input->getStatus().failed() || output->getStatus().failed() || output->getPosition() != size
        || source.getSize() != size || source.getLastModificationTime() != modified)
        return Result::fail("The source changed or an audio copy failed: " + source.getFileName());
    return Result::ok();
}
Result writeState(const File& file, const juce::MemoryBlock& state, TransferProgress& transfer)
{
    if (cancelled(transfer.options)) return cancellation();
    auto output = file.createOutputStream();
    if (!output) return Result::fail("Could not create plugin state: " + file.getFileName());
    const auto* bytes = static_cast<const char*>(state.getData());
    for (std::size_t offset = 0; offset < state.getSize();) {
        if (cancelled(transfer.options)) return cancellation();
        const auto count = juce::jmin<std::size_t>(state.getSize() - offset, 65536);
        if (!output->write(bytes + offset, count)) return Result::fail("Could not write complete plugin state.");
        offset += count;
        transfer.add(count, "Writing plugin state");
    }
    output->flush();
    if (output->getStatus().failed() || output->getPosition() != static_cast<juce::int64>(state.getSize()))
        return Result::fail("Could not flush plugin state.");
    return Result::ok();
}
Result readState(const File& file, std::size_t expectedBytes, juce::MemoryBlock& state, const IOOptions& options)
{
    if (cancelled(options)) return cancellation();
    if (expectedBytes > maximumPluginStateBytes || file.getSize() != static_cast<juce::int64>(expectedBytes))
        return Result::fail("Plugin state size does not match the project manifest.");
    auto input = file.createInputStream();
    if (!input || input->getTotalLength() != static_cast<juce::int64>(expectedBytes))
        return Result::fail("Could not open plugin state.");
    juce::MemoryBlock candidate(expectedBytes);
    auto* bytes = static_cast<char*>(candidate.getData());
    for (std::size_t offset = 0; offset < expectedBytes;) {
        if (cancelled(options)) return cancellation();
        const int count = static_cast<int>(juce::jmin<std::size_t>(expectedBytes - offset, 65536));
        if (input->read(bytes + offset, count) != count) return Result::fail("Plugin state is incomplete.");
        offset += static_cast<std::size_t>(count);
    }
    char extra = 0;
    if (input->getStatus().failed() || input->read(&extra, 1) != 0)
        return Result::fail("Plugin state changed during reading.");
    state = std::move(candidate);
    return Result::ok();
}
bool int32Value(const var& value)
{
    return integral(value) && static_cast<juce::int64>(value) >= std::numeric_limits<int>::min()
        && static_cast<juce::int64>(value) <= std::numeric_limits<int>::max();
}
var serializeAutomation(const std::vector<StoredAutomationLane>& lanes)
{
    juce::Array<var> result;
    for (const auto& lane : lanes) {
        auto item = std::make_unique<juce::DynamicObject>();
        item->setProperty("id", lane.id); item->setProperty("target", lane.target);
        item->setProperty("plugin_id", lane.pluginId); item->setProperty("parameter_id", lane.parameterId);
        item->setProperty("enabled", lane.enabled);
        juce::Array<var> points;
        for (const auto& point : lane.points) {
            auto p = std::make_unique<juce::DynamicObject>(); p->setProperty("id", point.id);
            p->setProperty("time_seconds", point.timeSeconds); p->setProperty("value", double(point.value)); p->setProperty("curve", double(point.curve));
            points.add(var(p.release()));
        }
        item->setProperty("points", var(points)); result.add(var(item.release()));
    }
    return var(result);
}
Result parseAutomation(const var& values, std::vector<StoredAutomationLane>& lanes, std::size_t& laneCount,
                       std::size_t& pointCount, const IOOptions& options)
{
    if (!values.isArray() || static_cast<std::size_t>(values.size()) > maximumAutomationLanesPerTrack
        || static_cast<std::size_t>(values.size()) > maximumAutomationLanes - laneCount)
        return Result::fail("Automation lanes exceed the owner/project limit.");
    laneCount += static_cast<std::size_t>(values.size());
    for (const auto& item : *values.getArray()) {
        if (cancelled(options)) return cancellation();
        const auto id = item.getProperty("id", {}), target = item.getProperty("target", {});
        const auto plugin = item.getProperty("plugin_id", {}), parameter = item.getProperty("parameter_id", {});
        const auto enabled = item.getProperty("enabled", {}), points = item.getProperty("points", {});
        if (!item.isObject() || !id.isString() || !target.isString() || !plugin.isString() || !parameter.isString()
            || !enabled.isBool() || !points.isArray() || static_cast<std::size_t>(points.size()) > maximumAutomationPoints - pointCount)
            return Result::fail("An automation lane contains missing/invalid fields or too many points.");
        StoredAutomationLane lane; lane.id = id.toString(); lane.target = target.toString();
        lane.pluginId = plugin.toString(); lane.parameterId = parameter.toString(); lane.enabled = bool(enabled);
        pointCount += static_cast<std::size_t>(points.size());
        for (const auto& p : *points.getArray()) {
            if (cancelled(options)) return cancellation();
            const auto pointId = p.getProperty("id", {}), time = p.getProperty("time_seconds", {});
            const auto value = p.getProperty("value", {}), curve = p.getProperty("curve", {});
            if (!p.isObject() || !pointId.isString() || !number(time) || !number(value) || !number(curve))
                return Result::fail("An automation point contains missing or invalid fields.");
            lane.points.push_back({pointId.toString(), double(time), float(double(value)), float(double(curve))});
        }
        lanes.push_back(std::move(lane));
    }
    return Result::ok();
}
Result parseRouting(const juce::DynamicObject& item, StoredTrack& track, std::size_t& sendCount)
{
    const auto input = item.getProperty("input_device_id"), output = item.getProperty("output_target_id"), sends = item.getProperty("sends");
    if (!input.isString() || !output.isString() || !sends.isArray() || static_cast<std::size_t>(sends.size()) > maximumSendsPerTrack
        || static_cast<std::size_t>(sends.size()) > maximumSends - sendCount)
        return Result::fail("Track routing contains missing/invalid fields or too many sends.");
    track.inputDeviceId = input.toString(); track.outputTargetId = output.toString();
    sendCount += static_cast<std::size_t>(sends.size());
    for (const auto& send : *sends.getArray()) {
        const auto id = send.getProperty("id", {}), target = send.getProperty("target_track_id", {}), gain = send.getProperty("gain_db", {});
        const auto pre = send.getProperty("pre_fader", {}), enabled = send.getProperty("enabled", {});
        if (!send.isObject() || !id.isString() || !target.isString() || !number(gain) || !pre.isBool() || !enabled.isBool())
            return Result::fail("A send contains missing or invalid fields.");
        track.sends.push_back({id.toString(), target.toString(), float(double(gain)), bool(pre), bool(enabled)});
    }
    return Result::ok();
}
Result parseControllers(const var& values, StoredClip& clip, std::size_t& count, const IOOptions& options)
{
    if (!values.isArray() || static_cast<std::size_t>(values.size()) > maximumControllerEvents - count)
        return Result::fail("MIDI controllers exceed the 100000-event project limit.");
    count += static_cast<std::size_t>(values.size());
    for (const auto& item : *values.getArray()) {
        if (cancelled(options)) return cancellation();
        const auto id = item.getProperty("id", {}), beats = item.getProperty("beats", {}), type = item.getProperty("type", {});
        const auto value = item.getProperty("value", {}), metadata = item.getProperty("metadata", {});
        if (!item.isObject() || !id.isString() || !number(beats) || !int32Value(type) || !int32Value(value) || !int32Value(metadata))
            return Result::fail("A MIDI controller contains missing or invalid fields.");
        clip.controllers.push_back({id.toString(), double(beats), int(type), int(value), int(metadata)});
    }
    return Result::ok();
}
Result parsePlugins(const var& values, const File& manifest, std::vector<StoredPlugin>& result,
                    std::size_t& pluginCount, std::size_t& stateBytes, std::set<String>& ids, const IOOptions& options)
{
    if (!values.isArray() || static_cast<std::size_t>(values.getArray()->size()) > maximumPlugins - pluginCount)
        return Result::fail("Plugin slots must be an array within the 256-instance project limit.");
    pluginCount += static_cast<std::size_t>(values.getArray()->size());
    for (const auto& value : *values.getArray()) {
        if (cancelled(options)) return cancellation();
        const auto* item = value.getDynamicObject();
        if (!item) return Result::fail("A plugin slot is not an object.");
        const auto id = item->getProperty("id"), format = item->getProperty("format"), identifier = item->getProperty("identifier");
        const auto uid = item->getProperty("unique_id"), oldUid = item->getProperty("deprecated_unique_id");
        const auto name = item->getProperty("name"), manufacturer = item->getProperty("manufacturer"), version = item->getProperty("version");
        const auto enabled = item->getProperty("enabled"), role = item->getProperty("role");
        const auto statePath = item->getProperty("state_file"), hash = item->getProperty("state_sha256"), size = item->getProperty("state_bytes");
        if (!id.isString() || !validIdentifier(id.toString()) || !ids.insert(id.toString().toLowerCase()).second
            || !format.isString() || !identifier.isString() || !int32Value(uid) || !int32Value(oldUid)
            || !name.isString() || !manufacturer.isString() || !version.isString() || !enabled.isBool() || !role.isString()
            || !statePath.isString() || !hash.isString() || hash.toString().length() != 64
            || !hash.toString().containsOnly("0123456789abcdefABCDEF") || !integral(size)
            || static_cast<juce::int64>(size) < 0 || static_cast<juce::int64>(size) > static_cast<juce::int64>(maximumPluginStateBytes))
            return Result::fail("A plugin slot contains missing or invalid metadata.");
        const auto length = static_cast<std::size_t>(static_cast<juce::int64>(size));
        if (length > maximumTotalPluginStateBytes - stateBytes)
            return Result::fail("Plugin states exceed the 256 MiB project limit.");
        stateBytes += length;
        StoredPlugin plugin;
        plugin.id = id.toString(); plugin.format = format.toString(); plugin.identifier = identifier.toString();
        plugin.uniqueId = static_cast<int>(uid); plugin.deprecatedUniqueId = static_cast<int>(oldUid);
        plugin.name = name.toString(); plugin.manufacturer = manufacturer.toString(); plugin.version = version.toString();
        plugin.enabled = static_cast<bool>(enabled); plugin.role = role.toString();
        if ((plugin.format != "VST" && plugin.format != "VST3" && plugin.format != "E-musician") || plugin.identifier.isEmpty()
            || plugin.identifier.length() > 4096 || plugin.name.length() > 512 || plugin.manufacturer.length() > 512
            || plugin.version.length() > 128 || (plugin.role != "instrument" && plugin.role != "effect"))
            return Result::fail("A plugin slot has an unsupported identity or role.");
        File stateFile;
        if (auto status = resolveBundleFile(manifest, "plugin_" + plugin.id + ".bin", statePath.toString(), stateFile, true); status.failed()) return status;
        if (auto status = readState(stateFile, length, plugin.state, options); status.failed()) return status;
        if (cancelled(options)) return cancellation();
        if (juce::SHA256(plugin.state).toHexString() != hash.toString().toLowerCase())
            return Result::fail("Plugin state checksum does not match the saved project: " + plugin.name);
        result.push_back(std::move(plugin));
    }
    return Result::ok();
}
Result serializePlugins(const std::vector<StoredPlugin>& plugins, const File& root, AssetCleanup& cleanup,
                        TransferProgress& transfer, juce::Array<var>& values)
{
    for (const auto& plugin : plugins) {
        if (cancelled(transfer.options)) return cancellation();
        const auto file = cleanup.directory.getChildFile("plugin_" + plugin.id + ".bin");
        cleanup.files.push_back(file);
        if (auto status = writeState(file, plugin.state, transfer); status.failed()) return status;
        auto item = std::make_unique<juce::DynamicObject>();
        item->setProperty("id", plugin.id); item->setProperty("format", plugin.format);
        item->setProperty("identifier", plugin.identifier); item->setProperty("unique_id", plugin.uniqueId);
        item->setProperty("deprecated_unique_id", plugin.deprecatedUniqueId);
        item->setProperty("name", plugin.name); item->setProperty("manufacturer", plugin.manufacturer);
        item->setProperty("version", plugin.version); item->setProperty("enabled", plugin.enabled); item->setProperty("role", plugin.role);
        item->setProperty("state_file", root.getFileName() + "/" + cleanup.directory.getFileName() + "/" + file.getFileName());
        item->setProperty("state_sha256", juce::SHA256(plugin.state).toHexString());
        item->setProperty("state_bytes", static_cast<juce::int64>(plugin.state.getSize()));
        values.add(var(item.release()));
    }
    return Result::ok();
}
} // namespace

Result nativePluginAssetIds(const StoredPlugin& plugin, std::vector<String>& result)
{
    return nativeAssetIds(plugin, result);
}

Result validate(const StoredProject& project)
{
    return validateProject(project, false, false);
}

bool isSupportedChordLabel(const juce::String& label) { return validChordLabel(label); }

Result save(const File& target, const StoredProject& project, StoredProject& archived, const IOOptions& options)
{
    if (cancelled(options)) return cancellation();
    progress(options, 0.0, "Validating project");
    if (auto result = validateLocation(target); result.failed()) return result;
    if (auto result = validateProject(project, false, true); result.failed()) return result;
    for (const auto& [id, hash] : options.expectedAssetHashes) {
        if (!validIdentifier(id) || hash.length() != 64 || !hash.containsOnly("0123456789abcdefABCDEF")
            || std::none_of(project.assets.begin(), project.assets.end(), [&](const auto& asset) { return asset.id == id; }))
            return Result::fail("Invalid or unknown expected native sample hash.");
    }

    const bool hadTarget = target.existsAsFile();
    int legacySchema = 0;
    juce::MemoryBlock previousBytes;
    var previous;
    if (hadTarget) {
        if (auto result = readJson(target, previousBytes, previous); result.failed())
            return Result::fail("Cannot safely inspect the existing project before replacement: " + result.getErrorMessage());
        const auto* object = previous.getDynamicObject();
        const auto schema = object != nullptr ? object->getProperty("schema") : var();
        if (!integral(schema) || static_cast<juce::int64>(schema) < 1 || static_cast<juce::int64>(schema) > 5)
            return Result::fail("Cannot replace an existing project with an unsupported schema.");
        if (static_cast<int>(schema) < project.schemaVersion) legacySchema = static_cast<int>(schema);
    }

    if (cancelled(options)) return cancellation();
    const auto root = assetRoot(target);
    if (root.isSymbolicLink() || (root.exists() && !root.isDirectory()))
        return Result::fail("The project asset path must be a regular folder.");
    if (auto result = root.createDirectory(); result.failed())
        return Result::fail("Could not create the project asset folder: " + result.getErrorMessage());
    AssetCleanup cleanup;
    cleanup.directory = root.getChildFile(juce::Uuid().toString());
    if (cleanup.directory.exists()) {
        cleanup.keep = true;
        return Result::fail("Could not allocate a unique project asset generation. Try saving again.");
    }
    if (auto result = cleanup.directory.createDirectory(); result.failed())
        return Result::fail("Could not create the project asset generation: " + result.getErrorMessage());

    TransferProgress transfer { options };
    for (const auto& asset : project.assets) transfer.total += static_cast<double>(asset.source.getSize());
    for (const auto& plugin : project.masterPlugins) transfer.total += static_cast<double>(plugin.state.getSize());
    for (const auto& track : project.tracks)
        for (const auto& plugin : track.plugins) transfer.total += static_cast<double>(plugin.state.getSize());
    StoredProject candidate = project;
    std::map<String, File> priorAssets;
    if (auto* oldAssets = previous.getProperty("assets", {}).getArray())
        for (const auto& value : *oldAssets) {
            const auto id = value.getProperty("id", {}).toString(), path = value.getProperty("source", {}).toString();
            File file;
            if (validIdentifier(id) && resolveSource(target, id, path, file).wasOk()) priorAssets.emplace(id, file);
        }
    std::vector<ReusedAsset> reusedAssets;
    juce::Array<var> assetObjects, trackObjects;
    for (auto& asset : candidate.assets) {
        if (cancelled(options)) return cancellation();
        File destination;
        if (auto found = priorAssets.find(asset.id); found != priorAssets.end()
            && found->second.getFileExtension().equalsIgnoreCase(asset.source.getFileExtension())) {
            bool same = false;
            if (auto result = canReuseAudio(asset.source, found->second, options, same); result.failed()) return result;
            if (same) {
                destination = found->second;
                reusedAssets.push_back({destination, destination.getSize(), destination.getLastModificationTime()});
                transfer.add(static_cast<std::size_t>(destination.getSize()), "Reusing audio: " + asset.source.getFileName(), false);
            }
        }
        if (destination == File()) {
            destination = cleanup.directory.getChildFile(asset.id + asset.source.getFileExtension().toLowerCase());
            cleanup.files.push_back(destination);
            if (auto result = copyAudio(asset.source, destination, transfer); result.failed()) return result;
        }
        auto object = std::make_unique<juce::DynamicObject>();
        object->setProperty("id", asset.id);
        object->setProperty("source", root.getFileName() + "/" + destination.getParentDirectory().getFileName() + "/" + destination.getFileName());
        assetObjects.add(var(object.release()));
        asset.source = destination;
    }
    for (auto& track : candidate.tracks) {
        if (cancelled(options)) return cancellation();
        auto object = std::make_unique<juce::DynamicObject>();
        object->setProperty("id", track.id); object->setProperty("name", track.name); object->setProperty("kind", track.kind);
        object->setProperty("gain_db", static_cast<double>(track.gainDb));
        object->setProperty("pan", static_cast<double>(track.pan));
        object->setProperty("muted", track.muted); object->setProperty("solo", track.solo);
        object->setProperty("input_device_id", track.inputDeviceId); object->setProperty("output_target_id", track.outputTargetId);
        object->setProperty("automation", serializeAutomation(track.automation));
        juce::Array<var> sends;
        for (const auto& send : track.sends) {
            auto item = std::make_unique<juce::DynamicObject>(); item->setProperty("id", send.id); item->setProperty("target_track_id", send.targetTrackId);
            item->setProperty("gain_db", double(send.gainDb)); item->setProperty("pre_fader", send.preFader); item->setProperty("enabled", send.enabled);
            sends.add(var(item.release()));
        }
        object->setProperty("sends", var(sends));
        juce::Array<var> clips, plugins;
        if (auto result = serializePlugins(track.plugins, root, cleanup, transfer, plugins); result.failed()) return result;
        object->setProperty("plugins", var(plugins));
        for (auto& clip : track.clips) {
            if (cancelled(options)) return cancellation();
            auto item = std::make_unique<juce::DynamicObject>();
            item->setProperty("id", clip.id); item->setProperty("kind", clip.kind);
            if(candidate.schemaVersion==5)item->setProperty("analysis_role",clip.analysisRole);
            if (clip.kind == "audio") {
                item->setProperty("asset_id", clip.assetId); item->setProperty("source_offset", clip.sourceOffset);
                item->setProperty("fade_in", clip.fadeIn); item->setProperty("fade_out", clip.fadeOut);
            } else {
                // Beats are authoritative; seconds are a checked derived representation.
                clip.timelineStart = clip.startBeats * 60.0 / candidate.bpm;
                clip.duration = clip.lengthBeats * 60.0 / candidate.bpm;
                clip.sourceOffset = 0.0;
                item->setProperty("start_beats", clip.startBeats); item->setProperty("length_beats", clip.lengthBeats);
                juce::Array<var> notes;
                for (const auto& note : clip.notes) {
                    if (cancelled(options)) return cancellation();
                    auto noteObject = std::make_unique<juce::DynamicObject>();
                    noteObject->setProperty("id", note.id); noteObject->setProperty("pitch", note.pitch);
                    noteObject->setProperty("start_beats", note.startBeats); noteObject->setProperty("length_beats", note.lengthBeats);
                    noteObject->setProperty("velocity", note.velocity); noteObject->setProperty("channel", note.channel);
                    notes.add(var(noteObject.release()));
                }
                item->setProperty("notes", var(notes));
                juce::Array<var> controllers;
                for (const auto& event : clip.controllers) {
                    if (cancelled(options)) return cancellation();
                    auto controller = std::make_unique<juce::DynamicObject>(); controller->setProperty("id", event.id);
                    controller->setProperty("beats", event.beats); controller->setProperty("type", event.type);
                    controller->setProperty("value", event.value); controller->setProperty("metadata", event.metadata);
                    controllers.add(var(controller.release()));
                }
                item->setProperty("controllers", var(controllers));
            }
            item->setProperty("timeline_start", clip.timelineStart);
            item->setProperty("duration", clip.duration);
            clips.add(var(item.release()));
        }
        object->setProperty("clips", var(clips));
        trackObjects.add(var(object.release()));
    }
    juce::Array<var> masterPlugins;
    if (auto result = serializePlugins(candidate.masterPlugins, root, cleanup, transfer, masterPlugins); result.failed()) return result;
    auto object = std::make_unique<juce::DynamicObject>();
    object->setProperty("schema", candidate.schemaVersion);
    if(candidate.schemaVersion==5){object->setProperty("analyses",serializeAnalyses(candidate));object->setProperty("chord_regions",serializeChords(candidate));}
    object->setProperty("project_id", candidate.projectId);
    object->setProperty("revision", static_cast<juce::int64>(candidate.revision));
    object->setProperty("master_gain_db", static_cast<double>(candidate.masterGainDb));
    object->setProperty("looping", candidate.looping);
    object->setProperty("loop_start", candidate.loopStart); object->setProperty("loop_end", candidate.loopEnd);
    object->setProperty("bpm", candidate.bpm); object->setProperty("numerator", candidate.numerator);
    object->setProperty("denominator", candidate.denominator); object->setProperty("master_plugins", var(masterPlugins));
    object->setProperty("master_automation", serializeAutomation(candidate.masterAutomation));
    object->setProperty("assets", var(assetObjects));
    object->setProperty("tracks", var(trackObjects));
    if (cancelled(options)) return cancellation();
    progress(options, 0.96, "Writing project manifest");
    const auto text = juce::JSON::toString(var(object.release()), true) + "\n";
    if (text.getNumBytesAsUTF8() > static_cast<std::size_t>(maximumManifestBytes))
        return Result::fail("The project manifest exceeds the 16 MiB size limit.");

    juce::TemporaryFile temporary(target);
    auto output = temporary.getFile().createOutputStream();
    if (!output || !output->writeText(text, false, false, "\n"))
        return Result::fail("Could not write the temporary project manifest.");
    output->flush();
    const auto writeResult = output->getStatus();
    output.reset();
    if (writeResult.failed()) return Result::fail("Could not flush the project manifest: " + writeResult.getErrorMessage());
    transfer.written += static_cast<juce::int64>(text.getNumBytesAsUTF8()); transfer.reportBytes();
    if (cancelled(options)) return cancellation();
    if (root.isSymbolicLink() || std::any_of(reusedAssets.begin(), reusedAssets.end(), [](const auto& asset) { return !asset.unchanged(); }))
        return Result::fail("A reused project asset changed while saving. The old manifest is unchanged.");

    // Recheck the old manifest after copying potentially large assets. This
    // avoids knowingly replacing an external edit made during preparation.
    if (hadTarget) {
        juce::MemoryBlock current;
        if (auto result = readBytes(target, current); result.failed())
            return Result::fail("The existing project became unavailable while saving.");
        if (current != previousBytes || target.isSymbolicLink())
            return Result::fail("The existing project changed while saving. Save again after checking it.");
        if (legacySchema != 0)
            if (auto result = createLegacyBackup(target, previousBytes, legacySchema); result.failed()) return result;
    } else if (target.exists()) {
        return Result::fail("Another file appeared at the project path while saving.");
    }
    if (cancelled(options)) return cancellation();
    for (const auto& asset : candidate.assets) {
        const auto expected = options.expectedAssetHashes.find(asset.id);
        if (expected != options.expectedAssetHashes.end())
            if (auto result = verifyExpectedAsset(asset.source, expected->second, options); result.failed()) return result;
    }
    if (cancelled(options)) return cancellation();
    if (!temporary.overwriteTargetFileWithTemporary())
        return Result::fail("Could not replace the project file. The previous saved project is unchanged.");

    if (cleanup.files.empty()) cleanup.directory.deleteFile(); // Only our own empty generation.
    cleanup.keep = true;
    archived = std::move(candidate);
    progress(options, 1.0, "Project saved");
    return Result::ok();
}

Result load(const File& manifest, StoredProject& project, const IOOptions& options)
{
    if (cancelled(options)) return cancellation();
    progress(options, 0.0, "Reading project manifest");
    if (auto result = validateLocation(manifest); result.failed()) return result;
    juce::MemoryBlock bytes;
    var parsed;
    if (auto result = readJson(manifest, bytes, parsed); result.failed()) return result;
    if (cancelled(options)) return cancellation();
    const auto* object = parsed.getDynamicObject();
    if (!object) return Result::fail("The project must contain a JSON object.");
    const auto schema = object->getProperty("schema");
    const auto id = object->getProperty("project_id"), revision = object->getProperty("revision");
    const auto master = object->getProperty("master_gain_db"), looping = object->getProperty("looping");
    const auto tracks = object->getProperty("tracks");
    if (!integral(schema) || static_cast<juce::int64>(schema) < 1 || static_cast<juce::int64>(schema) > 5)
        return Result::fail("This project schema is not supported. Expected schema 1 through 5.");
    if (!id.isString() || !validIdentifier(id.toString()) || !integral(revision)
        || static_cast<juce::int64>(revision) < 0 || !number(master) || !validGain(static_cast<double>(master))
        || !looping.isBool() || !tracks.isArray())
        return Result::fail("The project header contains missing or invalid fields.");
    if (static_cast<std::size_t>(tracks.getArray()->size()) > maximumTracks)
        return Result::fail("This project version supports at most 64 tracks.");

    StoredProject candidate;
    candidate.schemaVersion = static_cast<int>(schema);
    candidate.projectId = id.toString();
    candidate.revision = static_cast<std::uint64_t>(static_cast<juce::int64>(revision));
    candidate.masterGainDb = static_cast<float>(static_cast<double>(master));
    candidate.looping = static_cast<bool>(looping);
    if (candidate.schemaVersion >= 3) {
        const auto bpm = object->getProperty("bpm"), numerator = object->getProperty("numerator"), denominator = object->getProperty("denominator");
        const auto loopStart = object->getProperty("loop_start"), loopEnd = object->getProperty("loop_end");
        if (!number(bpm) || !int32Value(numerator) || !int32Value(denominator) || !number(loopStart) || !number(loopEnd))
            return Result::fail("The project tempo, time signature, or loop range is missing or invalid.");
        candidate.bpm = static_cast<double>(bpm); candidate.numerator = static_cast<int>(numerator);
        candidate.denominator = static_cast<int>(denominator); candidate.loopStart = static_cast<double>(loopStart);
        candidate.loopEnd = static_cast<double>(loopEnd);
        if (!std::isfinite(candidate.bpm) || candidate.bpm < minimumBpm || candidate.bpm > maximumBpm)
            return Result::fail("Tempo must be between 20 and 300 BPM.");
    }
    if (candidate.schemaVersion >= 2) {
        const auto assets = object->getProperty("assets");
        if (!assets.isArray() || static_cast<std::size_t>(assets.getArray()->size()) > maximumAssets)
            return Result::fail("The project assets must be an array of at most 4096 entries.");
        std::set<String> ids;
        for (const auto& item : *assets.getArray()) {
            if (cancelled(options)) return cancellation();
            const auto* asset = item.getDynamicObject();
            if (!asset) return Result::fail("An asset entry is not an object.");
            const auto assetId = asset->getProperty("id"), source = asset->getProperty("source");
            if (!assetId.isString() || !validIdentifier(assetId.toString()) || !source.isString()
                || !ids.insert(assetId.toString().toLowerCase()).second)
                return Result::fail("An asset contains missing, duplicate, or invalid fields.");
            StoredAsset stored;
            stored.id = assetId.toString();
            if (auto result = resolveSource(manifest, stored.id, source.toString(), stored.source); result.failed()) return result;
            candidate.assets.push_back(std::move(stored));
            progress(options, 0.05 + 0.35 * static_cast<double>(candidate.assets.size()) / juce::jmax(1, assets.getArray()->size()), "Checking audio assets");
        }
    }
    std::size_t clipCount = 0, noteCount = 0, pluginCount = 0, stateBytes = 0;
    std::size_t sendCount = 0, laneCount = 0, pointCount = 0, controllerCount = 0;
    std::set<String> pluginIds;
    for (const auto& item : *tracks.getArray()) {
        if (cancelled(options)) return cancellation();
        const auto* track = item.getDynamicObject();
        if (!track) return Result::fail("A track entry is not an object.");
        StoredTrack stored;
        if (auto result = readTrackMetadata(*track, stored); result.failed()) return result;
        if (candidate.schemaVersion >= 3) {
            const auto kind = track->getProperty("kind"), pan = track->getProperty("pan");
            if (!kind.isString() || !number(pan) || !validPan(static_cast<double>(pan)))
                return Result::fail("A track kind or pan is missing or invalid.");
            stored.kind = kind.toString(); stored.pan = static_cast<float>(static_cast<double>(pan));
            if (auto result = parsePlugins(track->getProperty("plugins"), manifest, stored.plugins, pluginCount, stateBytes, pluginIds, options); result.failed()) return result;
        }
        if (candidate.schemaVersion >= 4) {
            if (auto result = parseRouting(*track, stored, sendCount); result.failed()) return result;
            if (auto result = parseAutomation(track->getProperty("automation"), stored.automation, laneCount, pointCount, options); result.failed()) return result;
        }
        if (candidate.schemaVersion == 1) {
            const auto source = track->getProperty("source");
            if (!source.isString()) return Result::fail("A legacy track is missing its source path.");
            StoredAsset asset;
            // Full hash keeps the migration deterministic even for a 128-char ID.
            const auto suffix = juce::SHA256(stored.id.toUTF8()).toHexString();
            asset.id = "legacy_asset_" + suffix;
            if (auto result = resolveSource(manifest, stored.id, source.toString(), asset.source); result.failed()) return result;
            stored.clips.push_back({ "legacy_clip_" + suffix, asset.id, 0.0, 0.0, 0.0 });
            candidate.assets.push_back(std::move(asset));
        } else {
            const auto clips = track->getProperty("clips");
            if (!clips.isArray() || static_cast<std::size_t>(clips.getArray()->size()) > maximumClips - clipCount)
                return Result::fail("Tracks must contain clip arrays; the project limit is 4096 clips.");
            clipCount += static_cast<std::size_t>(clips.getArray()->size());
            for (const auto& clipItem : *clips.getArray()) {
                if (cancelled(options)) return cancellation();
                const auto* clip = clipItem.getDynamicObject();
                if (!clip) return Result::fail("A clip entry is not an object.");
                const auto clipId = clip->getProperty("id");
                const auto start = clip->getProperty("timeline_start");
                const auto duration = clip->getProperty("duration");
                if (!clipId.isString() || !number(start) || !number(duration))
                    return Result::fail("A clip contains missing or invalid position fields.");
                StoredClip value;
                if(candidate.schemaVersion==5){const auto role=clip->getProperty("analysis_role");if(!role.isString())return Result::fail("Missing clip analysis role.");value.analysisRole=role.toString();}
                value.id = clipId.toString(); value.timelineStart = static_cast<double>(start); value.duration = static_cast<double>(duration);
                if (candidate.schemaVersion >= 3) {
                    const auto kind = clip->getProperty("kind");
                    if (!kind.isString()) return Result::fail("A clip is missing its kind.");
                    value.kind = kind.toString();
                }
                if (value.kind == "audio") {
                    const auto assetId = clip->getProperty("asset_id"), offset = clip->getProperty("source_offset");
                    if (!assetId.isString() || !number(offset)) return Result::fail("An audio clip is missing its source fields.");
                    value.assetId = assetId.toString(); value.sourceOffset = static_cast<double>(offset);
                    if (candidate.schemaVersion >= 3) {
                        const auto fadeIn = clip->getProperty("fade_in"), fadeOut = clip->getProperty("fade_out");
                        if (!number(fadeIn) || !number(fadeOut)) return Result::fail("An audio clip is missing its fade fields.");
                        value.fadeIn = static_cast<double>(fadeIn); value.fadeOut = static_cast<double>(fadeOut);
                    }
                } else if (value.kind == "midi" && candidate.schemaVersion >= 3) {
                    const auto beat = clip->getProperty("start_beats"), length = clip->getProperty("length_beats"), notes = clip->getProperty("notes");
                    if (!number(beat) || !number(length) || !notes.isArray()
                        || static_cast<std::size_t>(notes.getArray()->size()) > maximumNotes - noteCount)
                        return Result::fail("MIDI clips require beat ranges and note arrays within the 100000-note project limit.");
                    value.startBeats = static_cast<double>(beat); value.lengthBeats = static_cast<double>(length);
                    const double derivedStart = value.startBeats * 60.0 / candidate.bpm;
                    const double derivedDuration = value.lengthBeats * 60.0 / candidate.bpm;
                    if (!validTime(value.timelineStart) || !validTime(value.duration)
                        || !std::isfinite(derivedStart) || !std::isfinite(derivedDuration)
                        || std::abs(value.timelineStart - derivedStart) > 1.0e-9 || std::abs(value.duration - derivedDuration) > 1.0e-9)
                        return Result::fail("MIDI clip seconds do not match its authoritative beat range.");
                    value.timelineStart = derivedStart; value.duration = derivedDuration;
                    noteCount += static_cast<std::size_t>(notes.getArray()->size());
                    for (const auto& noteItem : *notes.getArray()) {
                        if (cancelled(options)) return cancellation();
                        const auto* note = noteItem.getDynamicObject();
                        if (!note) return Result::fail("A MIDI note is not an object.");
                        const auto noteId = note->getProperty("id"), pitch = note->getProperty("pitch");
                        const auto noteStart = note->getProperty("start_beats"), noteLength = note->getProperty("length_beats");
                        const auto velocity = note->getProperty("velocity"), channel = note->getProperty("channel");
                        if (!noteId.isString() || !int32Value(pitch) || !number(noteStart) || !number(noteLength)
                            || !int32Value(velocity) || !int32Value(channel))
                            return Result::fail("A MIDI note contains missing or invalid fields.");
                        value.notes.push_back({ noteId.toString(), static_cast<int>(pitch), static_cast<double>(noteStart),
                            static_cast<double>(noteLength), static_cast<int>(velocity), static_cast<int>(channel) });
                    }
                    if (candidate.schemaVersion >= 4)
                        if (auto result = parseControllers(clip->getProperty("controllers"), value, controllerCount, options); result.failed()) return result;
                } else return Result::fail("Unsupported clip kind.");
                stored.clips.push_back(std::move(value));
            }
        }
        candidate.tracks.push_back(std::move(stored));
        progress(options, 0.45 + 0.45 * static_cast<double>(candidate.tracks.size()) / juce::jmax(1, tracks.getArray()->size()), "Reading tracks and plugin states");
    }
    if (candidate.schemaVersion >= 3)
        if (auto result = parsePlugins(object->getProperty("master_plugins"), manifest, candidate.masterPlugins, pluginCount, stateBytes, pluginIds, options); result.failed()) return result;
    if (candidate.schemaVersion >= 4)
        if (auto result = parseAutomation(object->getProperty("master_automation"), candidate.masterAutomation, laneCount, pointCount, options); result.failed()) return result;
    if(candidate.schemaVersion==5)if(auto result=parseAnalysis(parsed,candidate);result.failed())return result;
    if (auto result = validateProject(candidate, true, true); result.failed()) return result;
    if (cancelled(options)) return cancellation();
    project = std::move(candidate);
    progress(options, 1.0, "Project data ready");
    return Result::ok();
}
} // namespace emusician::storage
