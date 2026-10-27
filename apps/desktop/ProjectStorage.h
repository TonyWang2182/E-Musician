#pragma once

#include <juce_core/juce_core.h>
#include <cstdint>
#include <functional>
#include <vector>

namespace emusician::storage {

// Persistence DTOs only. The active, editable project remains owned by EngineSession.
struct StoredAsset {
    juce::String id;
    juce::File source;
};

struct StoredNote {
    juce::String id;
    int pitch = 60;
    double startBeats = 0.0, lengthBeats = 1.0;
    int velocity = 100, channel = 1;
};

struct StoredPlugin {
    juce::String id, format, identifier;
    int uniqueId = 0;
    juce::String name, manufacturer, version;
    bool enabled = true;
    juce::String role = "effect";
    juce::MemoryBlock state;
    int deprecatedUniqueId = 0;
};

struct StoredSend {
    juce::String id, targetTrackId;
    float gainDb = -12.0f;
    bool preFader = false, enabled = true;
};
struct StoredAutomationPoint {
    juce::String id;
    double timeSeconds = 0;
    float value = 0, curve = 0;
};
struct StoredAutomationLane {
    juce::String id, target = "track_gain", pluginId, parameterId;
    bool enabled = true;
    std::vector<StoredAutomationPoint> points;
};
struct StoredControllerEvent {
    juce::String id;
    double beats = 0;
    int type = 0, value = 0, metadata = 0;
};

struct StoredClip {
    juce::String id, assetId;
    double timelineStart = 0.0, sourceOffset = 0.0, duration = 0.0;
    juce::String kind = "audio";
    double startBeats = 0.0, lengthBeats = 4.0;
    double fadeIn = 0.0, fadeOut = 0.0;
    std::vector<StoredNote> notes;
    std::vector<StoredControllerEvent> controllers;
};

struct StoredTrack {
    juce::String id, name;
    float gainDb = 0.0f;
    bool muted = false, solo = false;
    std::vector<StoredClip> clips;
    juce::String kind = "audio";
    float pan = 0.0f;
    std::vector<StoredPlugin> plugins;
    juce::String inputDeviceId, outputTargetId = "master";
    std::vector<StoredSend> sends;
    std::vector<StoredAutomationLane> automation;
};

struct StoredProject {
    juce::String projectId;
    std::uint64_t revision = 0;
    float masterGainDb = -6.0f;
    bool looping = false;
    std::vector<StoredAsset> assets;
    std::vector<StoredTrack> tracks;
    // Loading schema 1 is read-only. Its one clip per track has duration == 0
    // until EngineSession resolves the original source length. Saves require 4.
    int schemaVersion = 4;
    double bpm = 120.0;
    int numerator = 4, denominator = 4;
    double loopStart = 0.0, loopEnd = 0.0;
    std::vector<StoredPlugin> masterPlugins;
    std::vector<StoredAutomationLane> masterAutomation;
};

inline constexpr std::size_t maximumTracks = 64;
inline constexpr std::size_t maximumClips = 4096;
inline constexpr std::size_t maximumAssets = 4096;
inline constexpr std::size_t maximumNotes = 100000;
inline constexpr std::size_t maximumPlugins = 256;
inline constexpr std::size_t maximumSendsPerTrack = 32;
inline constexpr std::size_t maximumSends = 512;
inline constexpr std::size_t maximumAutomationLanesPerTrack = 256;
inline constexpr std::size_t maximumAutomationLanes = 4096;
inline constexpr std::size_t maximumAutomationPoints = 100000;
inline constexpr std::size_t maximumControllerEvents = 100000;
inline constexpr double minimumBpm = 20.0, maximumBpm = 300.0;
inline constexpr double maximumTimelineSeconds = 172800.0; // Tracktion Edit's 48-hour bound.
inline constexpr juce::int64 maximumManifestBytes = 16 * 1024 * 1024;
inline constexpr std::size_t maximumPluginStateBytes = 64 * 1024 * 1024;
inline constexpr std::size_t maximumTotalPluginStateBytes = 256 * 1024 * 1024;

// Called only on the caller's file-work thread; callbacks must not mutate Edit.
// Cancellation before the atomic manifest switch leaves the old saved project.
struct IOOptions {
    std::function<bool()> cancelled;
    std::function<void(double fraction, const juce::String& stage)> progress;
    std::function<void(juce::int64 written, juce::int64 reused)> transferred;
};

// Pure DTO validation: no file reads, existence checks, or plugin instantiation.
juce::Result validate(const StoredProject&);

// Reuses verified unchanged audio in this bundle, copies changed/new audio into
// a fresh generation, then atomically replaces the schema 4 manifest.
// Plugin state is stored in separate hashed binaries in that generation.
// Replacing schema 1/2/3 first preserves its exact bytes in a unique sibling
// <original filename>.schemaN-<UUID>.bak; restore it to the original .emproj name.
// Older generations are retained. Outputs change only on success.
juce::Result save(const juce::File& target, const StoredProject&, StoredProject& archived, const IOOptions& = {});
juce::Result load(const juce::File& manifest, StoredProject&, const IOOptions& = {});

} // namespace emusician::storage
