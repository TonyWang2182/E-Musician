#pragma once
#include <juce_audio_utils/juce_audio_utils.h>
#include <cstdint>
#include <memory>
#include <vector>

namespace emusician {
// UI/control-thread facade. No UI code owns or mutates a Tracktion Edit.
class EngineSession final {
public:
    struct NoteSnapshot {
        juce::String id;
        int pitch = 60;
        double startBeats = 0.0, lengthBeats = 1.0;
        int velocity = 100, channel = 1;
    };
    struct PluginSlotSnapshot {
        juce::String id, name, format;
        bool enabled = true, missing = false, isInstrument = false;
    };
    struct PluginDescriptorSnapshot {
        juce::String id, name, manufacturer, format;
        bool isInstrument = false;
    };
    struct SendSnapshot {
        juce::String id, targetTrackId;
        float gainDb = -12.0f;
        bool preFader = false, enabled = true;
    };
    struct AutomationPointSnapshot {
        juce::String id;
        double timeSeconds = 0;
        float value = 0, curve = 0;
    };
    struct AutomationLaneSnapshot {
        juce::String id, target, pluginId, parameterId;
        bool enabled = true;
        std::shared_ptr<const std::vector<AutomationPointSnapshot>> points;
    };
    struct JobSnapshot {
        juce::String id, kind, status, error;
        double progress = -1.0;
        juce::String phase, detail;
        double captureMs = 0.0, maxPluginCaptureMs = 0.0;
        juce::int64 bytesWritten = 0, bytesReused = 0;
        int pluginsCaptured = 0;
    };
    struct ClipSnapshot {
        juce::String id, assetId;
        juce::File source, waveformSource;
        juce::String format;
        double timelineStart = 0.0, sourceOffset = 0.0, duration = 0.0;
        double sourceDuration = 0.0, sampleRate = 0.0;
        int channels = 0;
        juce::String kind = "audio";
        double startBeats = 0.0, lengthBeats = 4.0, fadeIn = 0.0, fadeOut = 0.0;
        std::shared_ptr<const std::vector<NoteSnapshot>> notes;
        int controllerCount = 0;
    };
    struct TrackSnapshot {
        float peakLeftDb = -100.0f, peakRightDb = -100.0f, inputPeakDb = -100.0f;
        bool overloaded = false;
        juce::String id, name, format;
        juce::File source;
        // Read-only prepared playback source; MP3 points at the validated PCM cache.
        juce::File waveformSource;
        double duration = 0.0, sampleRate = 0.0;
        int channels = 0;
        float gainDb = 0.0f;
        bool muted = false, solo = false;
        std::vector<ClipSnapshot> clips;
        juce::String kind = "audio";
        float pan = 0.0f;
        std::vector<PluginSlotSnapshot> plugins;
        juce::String inputDeviceId, outputTargetId = "master";
        bool armed = false;
        juce::String monitorMode = "off";
        std::vector<SendSnapshot> sends;
        std::vector<AutomationLaneSnapshot> automation;
    };
    struct Snapshot {
        bool metronomeEnabled = false, metronomeRecordOnly = false, countInEnabled = false, countingIn = false;
        int countInBars = 1;
        float metronomeGainDb = -12.0f;
        double countInBeatsRemaining = 0;
        juce::int64 memoryWorkingSetBytes = 0, memoryPrivateBytes = 0;
        float masterPeakLeftDb = -100.0f, masterPeakRightDb = -100.0f;
        bool masterOverloaded = false;
        juce::File source;
        double duration = 0.0, position = 0.0, sampleRate = 0.0;
        juce::File waveformSource;
        double sourceDuration = 0.0, sourceSampleRate = 0.0;
        int channels = 0, bufferSize = 0;
        float gainDb = -6.0f;
        bool playing = false, looping = false, deviceAvailable = false;
        bool dirty = false, canUndo = false, canRedo = false;
        juce::String deviceName, status, projectId, selectedTrackId, projectName, sourceFormat;
        juce::String selectedClipId;
        juce::String undoDescription, redoDescription;
        juce::File projectFile;
        std::vector<TrackSnapshot> tracks;
        std::uint64_t revision = 0;
        double bpm = 120.0, loopStart = 0.0, loopEnd = 0.0, cpuUsage = 0.0;
        int numerator = 4, denominator = 4, xruns = 0;
        std::vector<JobSnapshot> jobs;
        std::vector<PluginDescriptorSnapshot> pluginCatalog;
        std::vector<PluginSlotSnapshot> masterPlugins;
        bool pluginScanning = false;
        std::vector<AutomationLaneSnapshot> masterAutomation;
        bool recording = false, recordingFinalizing = false;
        juce::String recordingError;
        juce::var recordingState;
    };
    // Process-local test isolation, set before constructing any test sessions.
    static void setOfflineTestMode(bool);
    explicit EngineSession(bool initialiseAudioDevice = true);
    ~EngineSession();
    Snapshot snapshot() const;
    // GUI and local Agent requests share this dispatcher; all editing is serialized
    // on the message thread. Transport reads never change the project revision.
    juce::Result execute(const juce::String& command, const juce::var& args, std::uint64_t expectedRevision,
                         juce::var* commandResult = nullptr);
    juce::var executeRequest(const juce::var& envelope);
    juce::var capabilities() const;
    juce::var snapshotJson() const;
    // Message-thread UI projection only; never changes music revision/dirty/Undo.
    void setSelectionContext(const juce::var& context);
    juce::var selectionContext() const;
    juce::Result runSelectionContextSmokeTest(juce::DynamicObject& report);
    juce::Result runBatchRefsSmokeTest(juce::DynamicObject& report);
    juce::var eventsSince(std::uint64_t sequence) const;
    bool hasActiveJobs() const;
    void cancelAllJobs();
    static int runRenderWorker(const juce::StringArray& arguments);
    juce::Result importFile(const juce::File&, std::uint64_t expectedRevision);
    juce::Result importFiles(const juce::Array<juce::File>&, std::uint64_t expectedRevision);
    juce::Result newProject(std::uint64_t expectedRevision);
    juce::Result saveProject(const juce::File&, std::uint64_t expectedRevision);
    juce::Result openProject(const juce::File&, std::uint64_t expectedRevision);
    void selectTrack(const juce::String& id);
    void selectClip(const juce::String& clipId);
    juce::Result moveClip(const juce::String& clipId, double timelineStart, std::uint64_t expectedRevision);
    juce::Result setTrackGain(const juce::String& id, float decibels, std::uint64_t expectedRevision);
    juce::Result setTrackMuted(const juce::String& id, bool muted, std::uint64_t expectedRevision);
    juce::Result setTrackSolo(const juce::String& id, bool solo, std::uint64_t expectedRevision);
    juce::Result removeTrack(const juce::String& id, std::uint64_t expectedRevision);
    juce::Result undo(std::uint64_t expectedRevision);
    juce::Result redo(std::uint64_t expectedRevision);
    void beginEditGesture();
    void endEditGesture();
    static bool isSupportedAudioFile(const juce::File& file);
    void togglePlay();
    void stop();
    void seek(double seconds);
    void setLoop(bool enabled);
    void setGain(float decibels);
    juce::AudioDeviceManager& deviceManager();
    juce::Result runOfflineSmokeTest(const juce::File& outputDirectory);
    juce::Result runProjectSmokeTest(const juce::File& outputDirectory, const juce::File& fixtureDirectory);
    juce::Result runClipSmokeTest(const juce::File& outputDirectory);
    juce::Result runDawSmokeTest(const juce::File& outputDirectory, const juce::File& fixtureDirectory);
    juce::Result runProductionSmokeTest(const juce::File& outputDirectory);
    juce::Result runPluginNotificationSmoke(const juce::File& outputDirectory, const juce::String& catalogId);
    juce::Result runPerformanceProbe(const juce::File& outputDirectory, int seconds);
private:
    struct Impl;
    std::unique_ptr<Impl> impl;
};
}
