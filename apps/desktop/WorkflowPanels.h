#pragma once
#include "UiLanguage.h"
#include <functional>

namespace emusician {
namespace workflow_ui {
inline const juce::Colour ink { 0xff171817 }, secondary { 0xff626560 }, rule { 0xffc6c9c3 }, paper { 0xfffefefd };
inline juce::Font font(float size) { return juce::Font(juce::FontOptions(juce::Font::getDefaultMonospacedFontName(), size, juce::Font::plain)); }
inline void label(juce::Label& item, const juce::String& text, float size = 14) {
    item.setFont(font(size)); item.setColour(juce::Label::textColourId, ink); item.setText(text, juce::dontSendNotification);
}
}

// UI preferences are kept out of Edit. Device configuration still goes through
// the existing native selector and its validated configure_audio_device command.
class WorkspaceSettingsPanel final : public juce::Component {
public:
    std::function<void()> onAudio;
    std::function<void(bool)> onFollow;
    std::function<void(const juce::String&)> onLanguage;
    WorkspaceSettingsPanel() {
        for (auto* component : std::initializer_list<juce::Component*>{ &audio, &editing, &language, &heading, &detail, &openAudio, &follow, &languages, &hint }) addAndMakeVisible(component);
        audio.onClick = [this] { selectPage(0); }; editing.onClick = [this] { selectPage(1); }; language.onClick = [this] { selectPage(2); };
        openAudio.onClick = [this] { if (onAudio) onAudio(); };
        follow.setClickingTogglesState(true); follow.onClick = [this] { if (onFollow) onFollow(follow.getToggleState()); };
        languages.addItem("English", 1); languages.addItem(juce::String::fromUTF8("简体中文"), 2);
        languages.onChange = [this] { if (onLanguage) onLanguage(languages.getSelectedId() == 2 ? "zh-CN" : "en"); refreshLanguage(); };
        heading.setFont(workflow_ui::font(22)); detail.setFont(workflow_ui::font(14)); hint.setFont(workflow_ui::font(13));
        hint.setColour(juce::Label::textColourId, workflow_ui::secondary);
        detail.setJustificationType(juce::Justification::topLeft); hint.setJustificationType(juce::Justification::topLeft);
        setSize(720, 380); refreshLanguage();
    }
    void update(const juce::String& device, double rate, int buffer, bool following, bool recording) {
        deviceSummary = device.isEmpty() ? uiText("No audio device selected", "尚未选择音频设备") : device;
        deviceSummary += "\n" + juce::String(rate, 0) + " Hz  /  " + juce::String(buffer) + uiText(" samples", " 采样");
        follow.setToggleState(following, juce::dontSendNotification); openAudio.setEnabled(!recording); refreshLanguage();
    }
    void selectPage(int value) { page = juce::jlimit(0, 2, value); refreshLanguage(); resized(); repaint(); }
    void refreshLanguage() {
        hint.setFont(workflow_ui::font(uiLanguageCode() == "zh-CN" ? 15.0f : 13.0f));
        audio.setButtonText(uiText("Audio / MIDI", "音频 / MIDI")); editing.setButtonText(uiText("Editing", "编辑")); language.setButtonText(uiText("Language", "语言"));
        audio.setToggleState(page == 0, juce::dontSendNotification); editing.setToggleState(page == 1, juce::dontSendNotification); language.setToggleState(page == 2, juce::dontSendNotification);
        heading.setText(page == 0 ? uiText("Audio and MIDI", "音频与 MIDI") : page == 1 ? uiText("Timeline behavior", "时间线操作") : uiText("Interface language", "界面语言"), juce::dontSendNotification);
        detail.setText(page == 0 ? deviceSummary : page == 1 ? uiText("Keep the playhead in view during playback.", "播放时让播放头保持在视图中。") : uiText("Changes apply immediately and are remembered.", "立即生效，下次启动保持此设置。"), juce::dontSendNotification);
        openAudio.setButtonText(uiText("Configure audio devices...", "配置音频设备..."));
        follow.setButtonText(uiText("Follow playhead", "视图跟随播放头"));
        hint.setText(page == 0 ? uiText("Select MIDI keyboard inputs in each track's Devices / I/O. Arm and Monitor apply only to that track.", "在各轨道的装置／输入输出面板选择 MIDI 键盘。\n录音准备与监听仅作用于该轨道。")
            : page == 1 ? uiText("Manual scrolling or editing pauses following. Restart playback or turn Follow off/on to resume. This preference also appears above the timeline and in its right-click menu.", "手动滚动或编辑会暂停跟随。\n重新播放或重新开关跟随可恢复。\n时间线上方和标尺右键菜单也可切换此设置。")
            : uiText("Project names, track names, plug-in names and your messages keep their original text.", "工程名称、轨道名称、插件名称\n和输入的消息保留原文。"), juce::dontSendNotification);
        languages.setSelectedId(uiLanguageCode() == "zh-CN" ? 2 : 1, juce::dontSendNotification);
        openAudio.setVisible(page == 0); follow.setVisible(page == 1); languages.setVisible(page == 2);
    }
    void resized() override {
        audio.setBounds(16, 66, 144, 36); editing.setBounds(16, 112, 144, 36); language.setBounds(16, 158, 144, 36);
        const int x = 196, width = getWidth() - x - 24;
        heading.setBounds(x, 30, width, 38); detail.setBounds(x, 84, width, 62);
        openAudio.setBounds(x, 166, juce::jmin(340, width), 38); follow.setBounds(x, 166, juce::jmin(340, width), 38); languages.setBounds(x, 166, juce::jmin(280, width), 36);
        hint.setBounds(x, 230, width, getHeight() - 250);
    }
    void paint(juce::Graphics& g) override {
        g.fillAll(workflow_ui::paper); g.setColour(workflow_ui::ink); g.setFont(workflow_ui::font(16));
        g.drawText(uiText("Settings", "设置"), 18, 20, 142, 30, juce::Justification::centredLeft);
        g.setColour(workflow_ui::rule); g.drawVerticalLine(176, 20.0f, float(getHeight() - 20));
    }
    void toggleFollowForTest() { follow.setToggleState(!follow.getToggleState(), juce::dontSendNotification); follow.onClick(); }
    bool audioAvailableForTest() const { return openAudio.isEnabled(); }
private:
    juce::TextButton audio, editing, language, openAudio, follow;
    juce::ComboBox languages;
    juce::Label heading, detail, hint;
    juce::String deviceSummary;
    int page = 0;
};

// A concrete save destination. The panel never serializes a project itself;
// its accepted path enters MainComponent's existing asynchronous save pipeline.
class ProjectSavePanel final : public juce::Component {
public:
    std::function<void(const juce::File&)> onSave;
    std::function<void()> onCancel;
    explicit ProjectSavePanel(const juce::File& initial, const juce::String& currentStatus) : directory(initial.getParentDirectory()) {
        for (auto* component : std::initializer_list<juce::Component*>{ &title, &nameLabel, &locationLabel, &status, &name, &location, &browse, &save, &cancel, &hint }) addAndMakeVisible(component);
        workflow_ui::label(title, uiText("Save project", "保存工程"), 23);
        workflow_ui::label(nameLabel, uiText("Project name", "工程名称")); workflow_ui::label(locationLabel, uiText("Location", "保存位置"));
        workflow_ui::label(status, currentStatus); status.setColour(juce::Label::textColourId, workflow_ui::secondary);
        workflow_ui::label(hint, uiText("Audio, MIDI, plug-in state and edits are saved together.", "音频、MIDI、插件状态和编辑内容一起保存。"), 12);
        name.setFont(workflow_ui::font(16)); name.setColour(juce::TextEditor::textColourId, workflow_ui::ink); name.setText(initial.getFileNameWithoutExtension(), false); name.setSelectAllWhenFocused(true);
        location.setFont(workflow_ui::font(12)); location.setColour(juce::TextEditor::textColourId, workflow_ui::ink); location.setReadOnly(true); location.setMultiLine(true); location.setText(directory.getFullPathName(), false);
        browse.setButtonText(uiText("Choose folder...", "选择文件夹...")); save.setButtonText(uiText("Save project", "保存工程")); cancel.setButtonText(uiText("Cancel", "取消"));
        save.setToggleState(true, juce::dontSendNotification);
        save.setColour(juce::TextButton::textColourOffId, workflow_ui::ink);
        name.onTextChange = [this] { validate(); }; name.onReturnKey = [this] { if (save.isEnabled()) save.onClick(); };
        browse.onClick = [this] {
            if (chooser) return;
            chooser = std::make_unique<juce::FileChooser>(uiText("Choose project folder", "选择工程文件夹"), directory, "", true);
            chooser->launchAsync(juce::FileBrowserComponent::openMode | juce::FileBrowserComponent::canSelectDirectories,
                [safe = juce::Component::SafePointer<ProjectSavePanel>(this)](const juce::FileChooser& dialog) {
                    const auto selected = dialog.getResult();
                    juce::MessageManager::callAsync([safe, selected] { if (!safe) return; safe->chooser.reset(); if (selected.isDirectory()) { safe->directory = selected; safe->location.setText(selected.getFullPathName(), false); } });
                });
        };
        save.onClick = [this] { if (validate() && onSave) onSave(destination()); };
        cancel.onClick = [this] { if (onCancel) onCancel(); };
        setSize(640, 356); validate();
    }
    juce::File destination() const { return directory.getChildFile(name.getText().trim().trimCharactersAtEnd(".").replaceCharacter('\n', ' ') + ".emproj"); }
    void refreshLanguage(const juce::String& currentStatus) {
        workflow_ui::label(title, uiText("Save project", "保存工程"), 23);
        workflow_ui::label(nameLabel, uiText("Project name", "工程名称")); workflow_ui::label(locationLabel, uiText("Location", "保存位置"));
        status.setText(currentStatus, juce::dontSendNotification);
        browse.setButtonText(uiText("Choose folder...", "选择文件夹...")); save.setButtonText(uiText("Save project", "保存工程")); cancel.setButtonText(uiText("Cancel", "取消")); validate();
    }
    bool validate() {
        const auto value = name.getText().trim();
        const bool valid = value.isNotEmpty() && value == juce::File::createLegalFileName(value) && value != "." && value != ".." && !value.endsWithChar('.');
        save.setEnabled(valid);
        hint.setText(valid ? uiText("Audio, MIDI, plug-in state and edits are saved together.", "音频、MIDI、插件状态和编辑内容一起保存。") : uiText("Enter a file name without / \\ : * ? \" < > |", "请输入不含 / \\ : * ? \" < > | 的文件名"), juce::dontSendNotification);
        return valid;
    }
    void resized() override {
        title.setBounds(24, 18, getWidth() - 48, 34); status.setBounds(24, 56, getWidth() - 48, 25);
        nameLabel.setBounds(24, 102, 132, 32); name.setBounds(164, 102, getWidth() - 188, 34);
        locationLabel.setBounds(24, 158, 132, 32); location.setBounds(164, 158, getWidth() - 188, 56);
        browse.setBounds(164, 224, 190, 30); hint.setBounds(24, 268, getWidth() - 48, 25);
        cancel.setBounds(getWidth() - 300, getHeight() - 48, 110, 34); save.setBounds(getWidth() - 174, getHeight() - 48, 150, 34);
    }
    void paint(juce::Graphics& g) override { g.fillAll(workflow_ui::paper); g.setColour(workflow_ui::rule); g.drawHorizontalLine(89, 24.0f, float(getWidth() - 24)); }
    void submitForTest() { save.onClick(); }
private:
    juce::File directory;
    juce::Label title, nameLabel, locationLabel, status, hint;
    juce::TextEditor name, location;
    juce::TextButton browse, save, cancel;
    std::unique_ptr<juce::FileChooser> chooser;
};
}
