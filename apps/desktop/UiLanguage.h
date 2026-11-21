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
    std::atomic<bool> chinese { false };
    std::atomic<unsigned> revision { 1 };
    State() { chinese.store(!showcase::enabled() && preferenceFile().loadFileAsString().trim() == "zh-CN"); }
};
inline State& state() { static State value; return value; }
}
inline juce::String uiLanguageCode() { return ui_language_detail::state().chinese.load() ? "zh-CN" : "en"; }
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
    if (showcase::enabled() && code != "en") return juce::Result::fail("This workspace uses English.");
    if (code != "en" && code != "zh-CN") return juce::Result::fail("Unsupported interface language.");
    if (persist) {
        const auto file = ui_language_detail::preferenceFile();
        if (file.getParentDirectory().createDirectory().failed() || !file.replaceWithText(code + "\n"))
            return juce::Result::fail("Could not save the interface language.");
    }
    auto& value = ui_language_detail::state();
    if (value.chinese.exchange(code == "zh-CN") != (code == "zh-CN")) ++value.revision;
    return juce::Result::ok();
}
inline juce::String uiText(const juce::String& english, const juce::String& chinese) {
    return ui_language_detail::state().chinese.load() ? chinese : english;
}
// Source files compile as UTF-8. JUCE String(const char*) is its ASCII path;
// explicitly decode authored UTF-8 literals before selecting the UI language.
// Existing String values (including user data) are never reinterpreted.
inline juce::String uiText(const char* english, const char* chinese) {
    return uiText(juce::String::fromUTF8(english), juce::String::fromUTF8(chinese));
}
inline juce::String uiText(const juce::String& english, const char* chinese) {
    return uiText(english, juce::String::fromUTF8(chinese));
}
inline juce::String uiText(const char* english, const juce::String& chinese) {
    return uiText(juce::String::fromUTF8(english), chinese);
}
inline juce::String uiText(const juce::String& english) {
    if (!ui_language_detail::state().chinese.load()) return english;
    struct Entry { const char* en; const char* zh; };
    static constexpr Entry entries[] {
        {"new", "新建"}, {"open", "打开"}, {"save", "保存"}, {"save as", "另存为"},
        {"export", "导出"}, {"settings", "设置"}, {"audio settings", "音频设置"}, {"language", "语言"},
        {"add...", "添加..."}, {"edit", "编辑"}, {"devices", "装置"}, {"source", "音源"},
        {"details", "详情"}, {"undo", "撤销"}, {"redo", "重做"}, {"analyze", "分析"},
        {"play", "播放"}, {"stop", "停止"}, {"rec", "录音"}, {"loop", "循环"},
        {"mute", "静音"}, {"solo", "独奏"}, {"fit", "适合"}, {"snap", "吸附"},
        {"copy", "复制"}, {"cut", "剪切"}, {"paste", "粘贴"}, {"delete", "删除"},
        {"duplicate", "重复"}, {"quantize", "量化"}, {"draw", "画笔"}, {"draw [B]", "画笔 [B]"},
        {"pitch -", "音高 -"}, {"pitch +", "音高 +"}, {"velocity", "力度"},
        {"drum steps", "鼓步进"}, {"close editor", "关闭编辑器"}, {"expand", "展开"}, {"restore", "还原"},
        {"separate", "分离"}, {"audio to MIDI", "音频转 MIDI"}, {"chords", "和弦"},
        {"run analysis", "开始分析"}, {"cancel", "取消"}, {"import result", "加入工程"},
        {"saved chords", "和弦轨"}, {"apply", "应用"}, {"play stem", "试听"},
        {"rename track", "重命名轨道"}, {"rename", "重命名"}, {"name", "名称"},
        {"add instrument", "添加乐器"}, {"load sample...", "载入采样..."}, {"clear", "清除"},
        {"full sample", "完整采样"}, {"gate", "门控"}, {"one-shot", "单次"},
        {"gain", "增益"}, {"pan", "声像"}, {"start", "起点"}, {"end", "终点"},
        {"attack", "起音"}, {"release", "释音"}, {"tune", "调音"}, {"root", "根音"},
        {"frequency", "频率"}, {"threshold", "阈值"}, {"ratio", "比率"}, {"knee", "拐点"},
        {"makeup", "补偿"}, {"mix", "混合"}, {"feedback", "反馈"}, {"time", "时间"},
        {"decay", "衰减"}, {"size", "空间"}, {"damping", "阻尼"}, {"width", "宽度"},
        {"cutoff", "截止"}, {"resonance", "共振"}, {"rate", "速率"}, {"depth", "深度"},
        {"I/O + sends", "输入输出 / 发送"}, {"automation", "自动化"}, {"master", "主轨"},
        {"bypass", "旁通"}, {"remove", "移除"}, {"up", "上移"}, {"down", "下移"},
        {"add plug-in...", "添加插件..."}, {"built-in effects...", "原生效果器..."},
        {"arm record", "准备录音"}, {"post-fader", "推子后"}, {"pre-fader", "推子前"},
        {"bypass send", "旁通发送"}, {"add send", "添加发送"}, {"remove send", "移除发送"},
        {"bypass lane", "旁通曲线"}, {"delete lane", "删除曲线"},
        {"recording input", "录音输入"}, {"send to bus", "发送至总线"}, {"track output", "轨道输出"},
        {"Choose recording input", "选择录音输入"}, {"Master signal chain", "主轨装置链"},
        {"Selected track signal chain", "当前轨道装置链"},
        {"Select a MIDI clip to edit notes.", "选择 MIDI 片段以编辑音符。"},
        {"Choose an available parameter", "选择可用参数"}, {"Double-click to add automation points", "双击添加自动化节点"},
        {"Monitoring applies to this track only.", "监听仅作用于当前轨道。"},
        {"Choose a track to configure recording inputs, output and sends.", "选择轨道以设置录音输入、输出和发送。"},
        {"Retry assistant", "重新连接助手"}, {"Starting assistant...", "正在启动助手..."},
        {"Starting local assistant...", "正在启动本机助手..."},
        {"Ready", "就绪"}, {"Not started", "未启动"}
        ,{"saving...", "正在保存..."}, {"Save failed - retry", "保存失败 - 重试"},
        {"Unsaved changes", "尚未保存"}, {"Saved", "已保存"}, {"New project", "新建工程"},
        {"mute on", "已静音"}, {"solo on", "已独奏"}, {"return to arrangement", "返回编曲"},
        {"clip properties...", "片段属性..."}, {"cancel task", "取消任务"}, {"set", "设置"},
        {"follow", "跟随"}, {"click", "节拍器"}, {"count-in", "预备拍"}, {"pause", "暂停"}, {"remove track", "移除轨道"},
        {"draw B", "画笔 B"}, {"block", "组"}, {"enable", "启用"}, {"enable lane", "启用曲线"},
        {"enable send", "启用发送"}, {"armed", "已准备"}, {"unmute", "取消静音"}, {"empty", "空"},
        {"sampler", "采样器"}, {"drum rack / 16 pads", "鼓组 / 16 鼓垫"},
        {"dry/wet", "干湿比"}, {"delay", "延迟"}, {"LFO rate", "LFO 速率"}, {"LFO depth", "LFO 深度"},
        {"on", "开启"}, {"bypassed", "已旁通"}, {"reset", "复位"}, {"reset band", "复位频段"},
        {"low pass", "低通"}, {"high pass", "高通"}, {"LFO on", "LFO 开"}, {"LFO off", "LFO 关"},
        {"band on", "频段开"}, {"band off", "频段关"}, {"Bell", "钟形"}, {"Low shelf", "低架"},
        {"High shelf", "高架"}, {"Notch", "陷波"},
        {"add EQ Eight", "添加八段均衡"}, {"add Compressor", "添加压缩器"}, {"add Stereo Delay", "添加延迟"},
        {"add Reverb", "添加混响"}, {"add Auto Filter", "添加滤波器"},
        {"monitor off", "监听关"}, {"monitor auto", "监听自动"}, {"monitor on", "监听开"},
        {"kick / 36", "底鼓 / 36"}, {"snare / 38", "军鼓 / 38"}, {"closed hat / 42", "闭镲 / 42"},
        {"open hat / 46", "开镲 / 46"}, {"clap / 39", "拍手 / 39"}, {"tom / 45", "通鼓 / 45"},
        {"tempo / BPM (20-300)", "速度 / BPM (20-300)"}, {"meter numerator", "拍号分子"}, {"meter denominator", "拍号分母"},
        {"loop start / bar:beat:tick", "循环起点 / 小节:拍:细分"}, {"loop start / seconds", "循环起点 / 秒"},
        {"loop end / bar:beat:tick", "循环终点 / 小节:拍:细分"}, {"loop end / seconds", "循环终点 / 秒"},
        {"start / bar:beat:tick", "起点 / 小节:拍:细分"}, {"start / seconds", "起点 / 秒"},
        {"length / bars (fraction allowed)", "长度 / 小节 (可用小数)"}, {"length / seconds", "长度 / 秒"},
        {"source offset / seconds", "源偏移 / 秒"}, {"fade in / seconds", "淡入 / 秒"}, {"fade out / seconds", "淡出 / 秒"},
        {"root / MIDI", "根音 / MIDI"}, {"start / 0..1", "起点 / 0..1"}, {"end / 0..1", "终点 / 0..1"},
        {"Master output", "主轨输出"}
    };
    for (const auto& entry : entries) if (english.equalsIgnoreCase(entry.en)) return juce::String::fromUTF8(entry.zh);
    return english;
}
inline juce::String uiText(const char* english) { return uiText(juce::String::fromUTF8(english)); }
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
