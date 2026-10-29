#pragma once
#include "EngineSession.h"
#include <juce_audio_utils/juce_audio_utils.h>
#include <memory>
#include <functional>

namespace emusician {
class MainComponent final : public juce::Component, public juce::FileDragAndDropTarget, private juce::Timer, private juce::KeyListener {
public:
    explicit MainComponent(EngineSession&);
    ~MainComponent() override;
    void paint(juce::Graphics&) override;
    void resized() override;
    bool keyPressed(const juce::KeyPress&) override;
    bool isInterestedInFileDrag(const juce::StringArray&) override;
    void fileDragEnter(const juce::StringArray&, int, int) override;
    void fileDragExit(const juce::StringArray&) override;
    void filesDropped(const juce::StringArray&, int, int) override;
    void requestClose(std::function<void()> onReady);
    juce::Result runArrangementSmokeTest(const juce::File& outputDirectory);
    bool arrangementWaveformsReady() const;
private:
    struct Impl;
    EngineSession& session;
    std::unique_ptr<Impl> impl;
    void timerCallback() override;
    void refreshSnapshot();
    bool commitClipStart();
    void resetClipStartInput();
    void chooseSource();
    void importSources(const juce::Array<juce::File>&, std::uint64_t expectedRevision);
    void newProject();
    void openProject();
    void chooseProject();
    void saveProject(bool saveAs, std::function<void()> onSaved = {});
    void beginSave(const juce::File&, const juce::String& projectId, std::function<void()>, bool allowFollowup = true);
    void continueAfterSave(const juce::String& projectId, std::uint64_t savedRevision, std::function<void()>);
    void withUnsavedGuard(std::function<void()> proceed);
    void showResult(const juce::Result&);
    bool keyPressed(const juce::KeyPress& key, juce::Component*) override { return keyPressed(key); }
    void showAudioSettings();
    void showEditMenu();
    void showAddMenu();
    void showExportMenu();
    void showPlugins(const juce::String& trackId = {});
    void showPianoRoll();
    void showProjectTiming();
    void showMetronomeOptions();
    void clipClipboardAction(const juce::String&);
    void showClipProperties();
    void chooseMidi();
    void chooseExport(bool midi, bool selectedOnly, bool realtime);
    void execute(const juce::String&, const juce::var&);
    void finishOrAwaitSave(std::function<void()>);
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(MainComponent)
};
}
