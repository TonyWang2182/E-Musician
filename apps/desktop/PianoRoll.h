#pragma once
#include <juce_audio_utils/juce_audio_utils.h>
#include <functional>
#include <memory>
#include <vector>

namespace emusician {
// An editor projection, never a second editable engine. Changes are submitted
// once at the end of a gesture through the same project command as other clients.
class PianoRoll final : public juce::Component {
public:
    struct Note {
        juce::String id;
        int pitch = 60;
        double startBeats = 0.0, lengthBeats = 0.25;
        int velocity = 90, channel = 1;
    };
    PianoRoll();
    ~PianoRoll() override;
    void setClip(const juce::String& projectId, const juce::String& clipId,
                 const juce::String& name, std::uint64_t revision,
                 double startBeats, double lengthBeats, double bpm,
                 const std::vector<Note>&);
    // Reuse the current note projection when the authoritative shared note
    // snapshot is unchanged. A new revision still cancels an in-flight preview.
    bool updateUnchangedClip(const juce::String& projectId, const juce::String& clipId,
                             const juce::String& name, std::uint64_t revision,
                             double startBeats, double lengthBeats, double bpm);
    void setPlayhead(double projectSeconds, bool playing);
    void setTimeSignature(int numerator, int denominator);
    void paint(juce::Graphics&) override;
    void resized() override;
    bool keyPressed(const juce::KeyPress&) override;
    juce::Result runInteractionSmokeTest(juce::DynamicObject& report, const juce::File& artifactDirectory = {});
    std::function<void(const juce::String&, const std::vector<Note>&, std::uint64_t)> onWriteNotes;
    // Rejected local clipboard operations leave the authoritative notes untouched.
    std::function<void(const juce::String&)> onEditError;
    std::function<void(double)> onSeek;
    std::function<void()> onTogglePlay;
    std::function<bool(const juce::KeyPress&)> onProjectKey;
private:
    struct Impl;
    std::unique_ptr<Impl> impl;
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(PianoRoll)
};
}
