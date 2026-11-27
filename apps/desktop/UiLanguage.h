#pragma once
#include <juce_gui_basics/juce_gui_basics.h>
#include <atomic>
#include "ReplayMode.h"

namespace emusician {
// UI-thread preference only. Never call from an audio callback. Project content,
// device identifiers, plugin names and command/API keys are not translated.
namespace ui_language_detail {
inline juce::File preferenceFile() {
    if (showcase::enabled()) return showcase::profile().getChildFile("ui-language.txt");
    return juce::File::getSpecialLocation(juce::File::userApplicationDataDirectory)
        .getChildFile("E-musician").getChildFile("ui-language.txt");
}
struct State {
    std::atomic<unsigned> revision { 1 };
};
inline State& state() { static State value; return value; }
}
inline juce::String uiLanguageCode() { return "en"; }
inline unsigned uiLanguageRevision() { return ui_language_detail::state().revision.load(); }
// View preference only: separate from project/audio state and never autosaved.
inline juce::File followPreferenceFile() {
    return ui_language_detail::preferenceFile().getSiblingFile("follow-playhead.txt");
}
inline bool loadFollowPlayheadPreference() { return followPreferenceFile().loadFileAsString().trim() == "on"; }
inline juce::Result saveFollowPlayheadPreference(bool enabled) {
    const auto file = followPreferenceFile();
    if (file.getParentDirectory().createDirectory().failed() || !file.replaceWithText(enabled ? "on\n" : "off\n"))
        return juce::Result::fail("Could not save the follow-playhead preference.");
    return juce::Result::ok();
}
inline juce::Result setUiLanguage(const juce::String& code, bool persist = true) {
    // Accept a legacy locale preference, but always display and persist English.
    if (code != "en" && code != "zh-CN") return juce::Result::fail("Unsupported interface language.");
    if (persist) {
        const auto file = ui_language_detail::preferenceFile();
        if (file.getParentDirectory().createDirectory().failed() || !file.replaceWithText("en\n"))
            return juce::Result::fail("Could not save the interface language.");
    }
    ++ui_language_detail::state().revision;
    return juce::Result::ok();
}
// Authored interface copy is English. Existing project/user strings remain UTF-8.
inline juce::String uiText(const juce::String& english) { return english; }
inline juce::String uiText(const char* english) { return juce::String::fromUTF8(english); }
// Explicitly register only static UI controls. A language refresh never scans or
// rewrites arbitrary labels containing user/project/plugin data.
inline void uiButton(juce::Button& button, const juce::String& english) {
    button.getProperties().set("em.ui.button", english);
    button.setButtonText(uiText(english));
}
inline void uiLabel(juce::Label& label, const juce::String& english) {
    label.getProperties().set("em.ui.label", english);
    label.setText(uiText(english), juce::dontSendNotification);
}
inline void uiComboItem(juce::ComboBox& combo, int id, const juce::String& english) {
    combo.getProperties().set("em.ui.item." + juce::String(id), english);
    if (combo.indexOfItemId(id) < 0) combo.addItem(uiText(english), id);
    else combo.changeItemText(id, uiText(english));
}
inline void refreshUiButtons(juce::Component& component) {
    if (auto* button = dynamic_cast<juce::Button*>(&component)) {
        const auto canonical = button->getProperties()["em.ui.button"].toString();
        if (canonical.isNotEmpty()) button->setButtonText(uiText(canonical));
    }
    if (auto* label = dynamic_cast<juce::Label*>(&component)) {
        const auto canonical = label->getProperties()["em.ui.label"].toString();
        if (canonical.isNotEmpty()) label->setText(uiText(canonical), juce::dontSendNotification);
    }
    if (auto* combo = dynamic_cast<juce::ComboBox*>(&component)) {
        const auto selectedId = combo->getSelectedId();
        bool selectedTranslated = false;
        for (int i = 0; i < combo->getNumItems(); ++i) {
            const int id = combo->getItemId(i);
            const auto canonical = combo->getProperties()["em.ui.item." + juce::String(id)].toString();
            if (canonical.isNotEmpty()) {
                combo->changeItemText(id, uiText(canonical));
                selectedTranslated = selectedTranslated || id == selectedId;
            }
        }
        // JUCE changeItemText changes only its menu. Refresh the displayed item
        // explicitly without emitting a choice or changing any project setting.
        if (selectedTranslated) combo->setSelectedId(selectedId, juce::dontSendNotification);
    }
    for (auto* child : component.getChildren()) refreshUiButtons(*child);
}
}
