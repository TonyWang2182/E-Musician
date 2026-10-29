#include "MainComponent.h"
#include "ArrangementView.h"
#include "PianoRoll.h"
#include "SelectedTrackPanel.h"
#include "core/time/MusicalPosition.hpp"
#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <unordered_map>
#include <utility>

namespace emusician {
namespace {
const juce::Colour ink { 0xff171817 };
const juce::Colour secondary { 0xff626560 };
const juce::Colour rule { 0xffc6c9c3 };
const juce::Colour paper { 0xfffefefd };

juce::Font mono(float height, int style = juce::Font::plain)
{
    return juce::Font(juce::FontOptions(juce::Font::getDefaultMonospacedFontName(), height, style));
}
juce::String clockText(double seconds)
{
    const auto tenths = static_cast<juce::int64>(std::llround(juce::jmax(0.0, seconds) * 10.0));
    return juce::String(tenths / 600).paddedLeft('0', 2) + ":"
         + juce::String((tenths / 10) % 60).paddedLeft('0', 2) + "." + juce::String(tenths % 10);
}
juce::String rateText(double rate)
{
    return rate > 0.0 ? juce::String(rate / 1000.0, std::fmod(rate, 1000.0) == 0.0 ? 0 : 1) + " kHz" : "--";
}
juce::String positionText(double seconds, const EngineSession::Snapshot& s, bool musical)
{
    return musical ? juce::String(time::musicalPosition(seconds,s.bpm,s.numerator,s.denominator)) : juce::String(seconds,6);
}
std::optional<double> positionValue(const juce::String& text,const EngineSession::Snapshot& s,bool musical)
{
    if(musical)return time::parseMusicalPosition(text.trim().toStdString(),s.bpm,s.numerator,s.denominator);
    const auto value=text.trim();const auto* begin=value.toRawUTF8();char* end=nullptr;const auto seconds=std::strtod(begin,&end);
    if(value.isEmpty()||end==begin||*end!='\0'||!std::isfinite(seconds)||seconds<0)return {};
    return seconds;
}
void openCorners(juce::Graphics& g, juce::Rectangle<float> bounds, juce::Colour colour)
{
    g.setColour(colour);
    const auto x = bounds.getX(), y = bounds.getY(), r = bounds.getRight(), b = bounds.getBottom();
    constexpr float arm = 13.0f;
    juce::Path p;
    p.startNewSubPath(x, y + arm); p.lineTo(x, y); p.lineTo(x + arm, y);
    p.startNewSubPath(r - arm, y); p.lineTo(r, y); p.lineTo(r, y + arm);
    p.startNewSubPath(x, b - arm); p.lineTo(x, b); p.lineTo(x + arm, b);
    p.startNewSubPath(r - arm, b); p.lineTo(r, b); p.lineTo(r, b - arm);
    g.strokePath(p, juce::PathStrokeType(1.0f));
}

class InstrumentLook final : public juce::LookAndFeel_V4 {
public:
    InstrumentLook()
    {
        setColour(juce::ResizableWindow::backgroundColourId, paper);
        setColour(juce::Label::textColourId, ink);
        setColour(juce::TextButton::textColourOffId, ink);
        setColour(juce::TextButton::textColourOnId, ink);
        setColour(juce::TextEditor::backgroundColourId, paper);
        setColour(juce::TextEditor::textColourId, ink);
        setColour(juce::TextEditor::outlineColourId, rule);
        setColour(juce::TextEditor::focusedOutlineColourId, ink);
        setColour(juce::TextEditor::highlightColourId, ink);
        setColour(juce::TextEditor::highlightedTextColourId, paper);
        setColour(juce::Slider::textBoxTextColourId, ink);
        setColour(juce::Slider::textBoxBackgroundColourId, paper);
        setColour(juce::Slider::textBoxOutlineColourId, juce::Colours::transparentBlack);
        setColour(juce::ComboBox::backgroundColourId, paper);
        setColour(juce::ComboBox::textColourId, ink);
        setColour(juce::ComboBox::outlineColourId, rule);
        setColour(juce::ComboBox::arrowColourId, ink);
        setColour(juce::PopupMenu::backgroundColourId, paper);
        setColour(juce::PopupMenu::textColourId, ink);
        setColour(juce::PopupMenu::highlightedBackgroundColourId, ink);
        setColour(juce::PopupMenu::highlightedTextColourId, paper);
        setColour(juce::TooltipWindow::backgroundColourId, paper);
        setColour(juce::TooltipWindow::textColourId, ink);
        setColour(juce::TooltipWindow::outlineColourId, rule);
        setColour(juce::ScrollBar::thumbColourId, rule);
    }
    juce::Font getTextButtonFont(juce::TextButton&, int) override { return mono(15.0f); }
    juce::Font getLabelFont(juce::Label& label) override { return label.getFont(); }
    juce::Font getComboBoxFont(juce::ComboBox&) override { return mono(14.0f); }
    void drawButtonBackground(juce::Graphics& g, juce::Button& button, const juce::Colour&, bool over, bool down) override
    {
        const auto bounds = button.getLocalBounds().toFloat().reduced(1.5f);
        const bool flat = static_cast<bool>(button.getProperties()["flat"]);
        if (button.isEnabled() && (over || down || button.getToggleState())) {
            g.setColour(button.getToggleState() ? ink : ink.withAlpha(down ? 0.12f : 0.055f));
            g.fillRoundedRectangle(bounds, flat ? 2.0f : bounds.getHeight() * 0.5f);
        }
        if (! flat) {
            g.setColour(button.isEnabled() ? ink : rule);
            g.drawRoundedRectangle(bounds, bounds.getHeight() * 0.5f, 1.0f);
        }
        if (button.hasKeyboardFocus(true)) {
            g.setColour(ink);
            g.drawRoundedRectangle(bounds.reduced(3.0f), flat ? 2.0f : bounds.getHeight() * 0.5f, 1.5f);
        }
    }
    void drawButtonText(juce::Graphics& g, juce::TextButton& button, bool, bool) override
    {
        g.setColour(button.isEnabled() ? (button.getToggleState() ? paper : ink) : secondary);
        g.setFont(mono(15.0f));
        g.drawFittedText(button.getButtonText(), button.getLocalBounds().reduced(8, 2), juce::Justification::centred, 1);
    }
    void drawLinearSlider(juce::Graphics& g, int x, int y, int width, int height, float position,
                          float, float, juce::Slider::SliderStyle, juce::Slider& slider) override
    {
        const auto centre = static_cast<float>(y) + static_cast<float>(height) * 0.5f;
        g.setColour(slider.isEnabled() ? ink : rule);
        g.drawLine(static_cast<float>(x), centre, static_cast<float>(x + width), centre, 1.0f);
        g.fillEllipse(position - 5.0f, centre - 5.0f, 10.0f, 10.0f);
        if (slider.hasKeyboardFocus(true)) g.drawEllipse(position - 8.0f, centre - 8.0f, 16.0f, 16.0f, 1.0f);
    }
};

class TransportButton final : public juce::Button {
public:
    enum Kind { play, stop, loop, record };
    TransportButton(juce::String name, Kind buttonKind) : juce::Button(name), kind(buttonKind) {}
    void paintButton(juce::Graphics& g, bool over, bool down) override
    {
        auto bounds = getLocalBounds().toFloat();
        const auto cy = bounds.getCentreY();
        const auto colour = isEnabled() ? ink : secondary;
        const bool active = getToggleState();
        const juce::Rectangle<float> disc(2.0f, cy - 16.0f, 32.0f, 32.0f);
        g.setColour(colour);
        if (active || down) g.fillEllipse(disc); else g.drawEllipse(disc, over ? 1.7f : 1.0f);
        g.setColour(active || down ? paper : colour);
        if (kind == play && active) {
            g.fillRect(juce::Rectangle<float>(13.0f, cy - 6.0f, 3.0f, 12.0f));
            g.fillRect(juce::Rectangle<float>(20.0f, cy - 6.0f, 3.0f, 12.0f));
        } else if (kind == play) {
            juce::Path triangle;
            triangle.addTriangle(14.0f, cy - 7.0f, 14.0f, cy + 7.0f, 25.0f, cy);
            g.fillPath(triangle);
        } else if (kind == stop) {
            g.fillRect(juce::Rectangle<float>(12.0f, cy - 6.0f, 12.0f, 12.0f));
        } else if (kind == record) {
            g.fillEllipse(juce::Rectangle<float>(12.0f, cy - 6.0f, 12.0f, 12.0f));
        } else {
            juce::Path arc;
            arc.addCentredArc(18.0f, cy, 8.0f, 8.0f, 0.0f, 0.15f, 5.45f, true);
            g.strokePath(arc, juce::PathStrokeType(1.4f));
            juce::Path arrow;
            arrow.startNewSubPath(11.1f, cy - 8.0f); arrow.lineTo(10.5f, cy - 3.4f); arrow.lineTo(15.0f, cy - 4.4f);
            g.strokePath(arrow, juce::PathStrokeType(1.4f));
        }
        g.setColour(colour); g.setFont(mono(15.0f));
        g.drawText(kind == play && active ? "pause" : getName(), 45, 0, getWidth() - 45, getHeight(), juce::Justification::centredLeft);
        if (hasKeyboardFocus(true)) g.drawRoundedRectangle(bounds.reduced(0.5f), 3.0f, 1.0f);
    }
private:
    Kind kind;
};

class WaveformView final : public juce::Component {
public:
    WaveformView(EngineSession& s, ArrangementView& waveforms) : engine(s), provider(waveforms)
    {
        setWantsKeyboardFocus(true);
        setTitle("Source waveform");
        setDescription("Click to seek. Left and right arrow keys seek five seconds; Home returns to the start.");
    }
    void invalidateSource() { provider.invalidateSources(); }
    void update(const EngineSession::Snapshot& next)
    {
        source = next.waveformSource; duration = next.sourceDuration;
        projectPosition = next.position; projectDuration = next.duration;
        trackId = next.selectedClipId;
        clipStart = sourceOffset = 0.0;
        clipDuration = duration;
        for (const auto& track : next.tracks) for (const auto& clip : track.clips)
            if (clip.id == next.selectedClipId) { clipStart = clip.timelineStart; sourceOffset = clip.sourceOffset; clipDuration = clip.duration; }
        position = sourceOffset + next.position - clipStart;
        hasSource = next.sourceDuration > 0.0 && source != juce::File();
        sourceRate = next.sourceSampleRate; sourceChannels = next.channels;
        repaint();
    }
    void paint(juce::Graphics& g) override
    {
        const auto bounds = getLocalBounds().toFloat().reduced(1.0f);
        openCorners(g, bounds, dropActive ? ink : rule);
        if (hasKeyboardFocus(true)) openCorners(g, bounds.reduced(4.0f), ink);
        if (! hasSource) {
            g.setColour(ink); g.setFont(mono(22.0f));
            g.drawFittedText(dropActive ? "Drop audio here." : "Start with a sound.", getLocalBounds().reduced(24).withTrimmedBottom(getHeight() / 2 - 12), juce::Justification::centredBottom, 2);
            g.setColour(secondary); g.setFont(mono(14.0f));
            g.drawFittedText("Drop WAV or MP3 files here,\nor choose add audio above.", 24, getHeight() / 2 + 15, getWidth() - 48, 52, juce::Justification::centredTop, 2);
            return;
        }
        const auto area = waveArea();
        g.setColour(rule.withAlpha(0.7f));
        const auto channels = juce::jmax(1, sourceChannels);
        for (int channel = 0; channel < channels; ++channel) {
            const auto y = area.getY() + area.getHeight() * (static_cast<float>(channel) + 0.5f) / static_cast<float>(channels);
            g.drawHorizontalLine(juce::roundToInt(y), area.getX(), area.getRight());
        }
        if (provider.trackWaveformReady(trackId)) {
            g.setColour(ink);
            provider.drawTrackWaveform(g, area.toNearestInt(), trackId, 0.0, duration, 0.86f);
        } else {
            g.setColour(secondary); g.setFont(mono(14.0f));
            g.drawText(provider.waveformStatus(trackId), area.toNearestInt(), juce::Justification::centred);
        }
        const auto axis = static_cast<float>(getHeight() - 34);
        g.setColour(rule);
        g.drawLine(area.getX(), axis, area.getRight(), axis, 1.0f);
        constexpr int intervals = 4;
        g.setFont(mono(12.0f));
        for (int i = 0; i <= intervals; ++i) {
            const auto fraction = static_cast<float>(i) / static_cast<float>(intervals);
            const auto x = area.getX() + fraction * area.getWidth();
            g.setColour(rule); g.drawLine(x, axis, x, axis + 5.0f, 1.0f);
            g.setColour(secondary);
            auto label = juce::Rectangle<int>(juce::roundToInt(x) - 36, getHeight() - 24, 72, 18);
            if (i == 0) label.setX(juce::roundToInt(area.getX()));
            if (i == intervals) label = label.withRightX(juce::roundToInt(area.getRight()));
            g.drawText(clockText(duration * fraction), label, i == 0 ? juce::Justification::centredLeft : (i == intervals ? juce::Justification::centredRight : juce::Justification::centred));
        }
        if (projectPosition >= clipStart && projectPosition <= clipStart + clipDuration) {
            const auto playhead = area.getX() + area.getWidth() * static_cast<float>(juce::jlimit(0.0, 1.0, position / duration));
            g.setColour(ink); g.drawLine(playhead, area.getY(), playhead, axis, 1.2f);
            juce::Path marker;
            marker.addTriangle(playhead - 4.0f, area.getY() - 7.0f, playhead + 4.0f, area.getY() - 7.0f, playhead, area.getY());
            g.fillPath(marker);
        }
    }
    void mouseDown(const juce::MouseEvent& event) override
    {
        if (isShowing()) grabKeyboardFocus();
        if (hasSource) {
            const auto sourceTime = duration * juce::jlimit(0.0, 1.0, static_cast<double>((event.position.x - waveArea().getX()) / waveArea().getWidth()));
            engine.seek(juce::jlimit(clipStart, clipStart + clipDuration, clipStart + sourceTime - sourceOffset));
        }
    }
    void mouseDrag(const juce::MouseEvent& event) override { mouseDown(event); }
    bool keyPressed(const juce::KeyPress& key) override
    {
        if (! hasSource) return false;
        if (key == juce::KeyPress::leftKey) engine.seek(juce::jmax(0.0, projectPosition - 5.0));
        else if (key == juce::KeyPress::rightKey) engine.seek(juce::jmin(projectDuration, projectPosition + 5.0));
        else if (key == juce::KeyPress::homeKey) engine.seek(0.0);
        else if (key == juce::KeyPress::endKey) engine.seek(projectDuration);
        else return false;
        return true;
    }
    void focusGained(FocusChangeType) override { repaint(); }
    void focusLost(FocusChangeType) override { repaint(); }
    double sourceRate = 0.0;
    int sourceChannels = 0;
    bool dropActive = false;
private:
    juce::Rectangle<float> waveArea() const { return getLocalBounds().toFloat().reduced(16.0f, 0.0f).withTrimmedTop(28.0f).withTrimmedBottom(47.0f); }
    EngineSession& engine;
    ArrangementView& provider;
    juce::File source;
    juce::String trackId;
    double duration = 0.0, position = 0.0;
    double projectPosition = 0.0, projectDuration = 0.0, clipStart = 0.0, sourceOffset = 0.0, clipDuration = 0.0;
    bool hasSource = false;
};
class ClipStartEditor final : public juce::TextEditor {
public:
    std::function<void()> onEditBegin;
    void focusGained(FocusChangeType cause) override
    {
        juce::TextEditor::focusGained(cause);
        if (onEditBegin) onEditBegin();
    }
};
juce::var arguments(std::initializer_list<std::pair<juce::Identifier, juce::var>> values)
{
    auto object = new juce::DynamicObject;
    for (const auto& item : values) object->setProperty(item.first, item.second);
    return juce::var(object);
}
juce::var idsValue(const juce::StringArray& ids)
{
    juce::Array<juce::var> list; for (const auto& id : ids) list.add(id); return list;
}
class ValueForm final : public juce::Component {
public:
    struct Field { juce::String key, label, value; bool numeric = true; };
    ValueForm(std::vector<Field> fields, std::function<juce::Result(const juce::var&)> callback) : data(std::move(fields)), submit(std::move(callback))
    {
        for (const auto& field : data) {
            auto label = std::make_unique<juce::Label>(); label->setText(field.label, juce::dontSendNotification); label->setFont(mono(14)); addAndMakeVisible(*label); labels.push_back(std::move(label));
            auto editor = std::make_unique<juce::TextEditor>(); editor->setFont(mono(14));
            // TextEditor stores the insertion colour in its text runs. These
            // fields are populated before the form inherits InstrumentLook.
            editor->setColour(juce::TextEditor::textColourId, ink);
            editor->setText(field.value, false); editor->setSelectAllWhenFocused(true);
            if (field.numeric) editor->setInputRestrictions(24, "0123456789.-");
            addAndMakeVisible(*editor); editors.push_back(std::move(editor));
        }
        addAndMakeVisible(error); error.setFont(mono(12));
        addAndMakeVisible(apply); apply.onClick = [this] {
            auto values = juce::var(new juce::DynamicObject);
            for (std::size_t i = 0; i < data.size(); ++i) {
                if (!data[i].numeric) { values.getDynamicObject()->setProperty(data[i].key, editors[i]->getText()); continue; }
                const auto text = editors[i]->getText().trim(); char* end = nullptr; const auto number = std::strtod(text.toRawUTF8(), &end);
                if (text.isEmpty() || end == text.toRawUTF8() || *end != '\0' || !std::isfinite(number)) { error.setText("Enter a finite number for " + data[i].label + ".", juce::dontSendNotification); return; }
                values.getDynamicObject()->setProperty(data[i].key, number);
            }
            const auto result = submit ? submit(values) : juce::Result::fail("This action is unavailable.");
            if (result.failed()) { error.setText(result.getErrorMessage(), juce::dontSendNotification); return; }
            juce::MessageManager::callAsync([safe = juce::Component::SafePointer<ValueForm>(this)] {
                if (safe) if (auto* dialog = safe->findParentComponentOfClass<juce::DialogWindow>()) dialog->exitModalState(0);
            });
        };
        setSize(470, 100 + int(data.size()) * 42);
    }
    void resized() override
    {
        int y = 12; for (std::size_t i = 0; i < data.size(); ++i) { labels[i]->setBounds(16, y, 200, 30); editors[i]->setBounds(226, y, getWidth() - 242, 30); y += 42; }
        apply.setBounds(getWidth() - 116, y, 100, 30);
        error.setBounds(12, y + 37, getWidth() - 24, 46);
    }
    void paint(juce::Graphics& g) override { g.fillAll(paper); }
private:
    std::vector<Field> data;
    std::vector<std::unique_ptr<juce::Label>> labels;
    std::vector<std::unique_ptr<juce::TextEditor>> editors;
    juce::TextButton apply { "apply" };
    juce::Label error;
    std::function<juce::Result(const juce::var&)> submit;
};
class ToolWindow final : public juce::DialogWindow {
public:
    ToolWindow(const juce::String& title, juce::Component* content, juce::Component* parent)
        : juce::DialogWindow(title, paper, true)
    {
        setUsingNativeTitleBar(true); setContentOwned(content, true); setResizable(true, false);
        centreAroundComponent(parent, getWidth(), getHeight()); setVisible(true);
    }
    void closeButtonPressed() override { delete this; }
};

class AudioSettingsPanel final : public juce::Component {
public:
    using Query = std::function<juce::var(bool)>;
    using Configure = std::function<juce::Result(const juce::var&)>;
    AudioSettingsPanel(Query readDevices, Configure configureDevice)
        : query(std::move(readDevices)), configure(std::move(configureDevice))
    {
        for (auto* box : { &driver, &output, &input, &rate, &buffer }) addAndMakeVisible(*box);
        for (auto* label : { &driverLabel, &outputLabel, &inputLabel, &rateLabel, &bufferLabel, &actual, &hint, &status }) {
            addAndMakeVisible(*label); label->setFont(mono(13)); label->setColour(juce::Label::textColourId, ink);
            label->setJustificationType(juce::Justification::centredLeft);
        }
        driverLabel.setText("Driver", juce::dontSendNotification); inputLabel.setText("Input", juce::dontSendNotification);
        rateLabel.setText("Sample rate", juce::dontSendNotification); bufferLabel.setText("Buffer size", juce::dontSendNotification);
        driver.setTitle("Audio driver"); output.setTitle("Audio output device"); input.setTitle("Audio input device");
        rate.setTitle("Audio sample rate"); buffer.setTitle("Audio buffer size");
        addAndMakeVisible(refresh); addAndMakeVisible(apply);
        driver.onChange = [this] { if (!updating) rebuildDevices(); };
        output.onChange = input.onChange = [this] { if (!updating) rebuildTiming(); };
        refresh.onClick = [this] { read(true); };
        apply.onClick = [this] { beginApply(); };
        hint.setColour(juce::Label::textColourId, secondary);
        actual.setColour(juce::Label::textColourId, secondary);
        setSize(660, 470); read(true);
    }
    void resized() override
    {
        auto y = 14;
        const std::pair<juce::Label*, juce::ComboBox*> rows[] {
            { &driverLabel, &driver }, { &outputLabel, &output }, { &inputLabel, &input }, { &rateLabel, &rate }, { &bufferLabel, &buffer }
        };
        for (const auto& row : rows) { row.first->setBounds(16, y, 130, 30); row.second->setBounds(150, y, getWidth() - 166, 30); y += 42; }
        actual.setBounds(16, 232, getWidth() - 32, 50); hint.setBounds(16, 290, getWidth() - 32, 52);
        status.setBounds(16, 350, getWidth() - 32, 64);
        refresh.setBounds(16, getHeight() - 42, 140, 30); apply.setBounds(getWidth() - 116, getHeight() - 42, 100, 30);
    }
    void paint(juce::Graphics& g) override { g.fillAll(paper); g.setColour(rule); g.drawHorizontalLine(224, 16.0f, float(getWidth() - 16)); }
    static juce::Result runInteractionSmokeTest(juce::DynamicObject& report)
    {
        auto devices = arguments({ { "drivers", juce::Array<juce::var> {
            arguments({ { "driver_type", "Separate" }, { "separate_inputs_and_outputs", true }, { "inputs", juce::Array<juce::var>{ "Microphone" } }, { "outputs", juce::Array<juce::var>{ "Speakers" } } }),
            arguments({ { "driver_type", "ASIO" }, { "separate_inputs_and_outputs", false }, { "inputs", juce::Array<juce::var>{ "Interface" } }, { "outputs", juce::Array<juce::var>{ "Interface" } } }) } },
            { "driver_type", "Separate" }, { "device_name", "Speakers + Microphone" }, { "input_device_name", "Microphone" }, { "output_device_name", "Speakers" },
            { "sample_rate", 44100.0 }, { "buffer_size", 256 }, { "sample_rates", juce::Array<juce::var>{ 44100.0, 48000.0 } }, { "buffer_sizes", juce::Array<juce::var>{ 256, 512 } } });
        int changes = 0; bool reject = false; juce::var submitted;
        AudioSettingsPanel panel([&](bool) { return arguments({ { "status", "completed" }, { "result", devices } }); }, [&](const juce::var& args) {
            ++changes; submitted = args;
            if (reject) return juce::Result::fail("Fixture: driver rejected the buffer. Previous device configuration restored.");
            auto* data = devices.getDynamicObject(); data->setProperty("driver_type", "ASIO"); data->setProperty("device_name", "Interface");
            data->setProperty("input_device_name", "Interface"); data->setProperty("output_device_name", "Interface"); data->setProperty("sample_rate", 48000.0); data->setProperty("buffer_size", 512);
            return juce::Result::ok();
        });
        if (panel.output.getText() != "Speakers" || panel.input.getText() != "Microphone") return juce::Result::fail("Audio settings did not read separate active input/output names.");
        panel.driver.setSelectedId(2, juce::dontSendNotification); panel.driver.onChange();
        if (changes != 0 || panel.rate.isEnabled() || panel.buffer.isEnabled()) return juce::Result::fail("Selecting a different driver applied it early or exposed the previous device's timing capabilities.");
        panel.apply.onClick();
        if (!panel.applying || panel.apply.isEnabled()) return juce::Result::fail("Audio settings did not show its pending Apply state.");
        const auto wait = [&] {
            const auto end = juce::Time::getMillisecondCounterHiRes() + 1000;
            while (panel.applying && juce::Time::getMillisecondCounterHiRes() < end) juce::MessageManager::getInstance()->runDispatchLoopUntil(1);
        };
        wait();
        if (changes != 1 || submitted["device_name"].toString() != "Interface" || submitted.hasProperty("sample_rate") || submitted.hasProperty("buffer_size")
            || panel.rate.getText() != "48000 Hz" || panel.buffer.getText() != "512 samples")
            return juce::Result::fail("Audio device Apply did not use defaults for the new driver and display actual readback.");
        reject = true; panel.buffer.setSelectedId(1, juce::dontSendNotification); panel.apply.onClick(); wait();
        if (changes != 2 || int(submitted["buffer_size"]) != 256 || panel.status.getText().isEmpty() || !panel.status.getText().contains("rejected")
            || panel.buffer.getText() != "512 samples" || !panel.apply.isEnabled())
            return juce::Result::fail("Rejected audio configuration did not retain visible failure and restored actual settings.");
        report.setProperty("audio_settings_draft_apply_actual_readback_and_failure", true); return juce::Result::ok();
    }
private:
    juce::var selectedDriver() const
    {
        if (const auto* list = devices["drivers"].getArray()) for (const auto& item : *list) if (item["driver_type"].toString() == driver.getText()) return item;
        return {};
    }
    bool separateDevices() const { return bool(selectedDriver()["separate_inputs_and_outputs"]); }
    juce::String inputName() const { return separateDevices() && input.getSelectedId() > 1 ? input.getText() : juce::String(); }
    bool activeSelection() const
    {
        return driver.getText() == devices["driver_type"].toString() && output.getText() == devices["output_device_name"].toString()
            && (!separateDevices() || inputName() == devices["input_device_name"].toString());
    }
    bool read(bool scan)
    {
        const auto response = query(scan);
        if (response["status"].toString() != "completed" || !response["result"].isObject()) {
            status.setText(response["error"].toString().isNotEmpty() ? response["error"].toString() : "Could not read audio devices. Refresh to try again.", juce::dontSendNotification);
            actual.setText("Active settings could not be confirmed. Refresh to read them again.", juce::dontSendNotification); updateEnabled(); return false;
        }
        devices = response["result"]; updating = true; driver.clear(juce::dontSendNotification);
        int chosen = 0;
        if (const auto* list = devices["drivers"].getArray()) for (const auto& item : *list) {
            const auto name = item["driver_type"].toString(); const int id = driver.getNumItems() + 1; driver.addItem(name, id);
            if (name == devices["driver_type"].toString()) chosen = id;
        }
        driver.setSelectedId(chosen, juce::dontSendNotification); updating = false; rebuildDevices();
        const auto name = devices["device_name"].toString();
        actual.setText(name.isEmpty() ? "No audio device is open." : "Active: " + name + "\n" + juce::String(double(devices["sample_rate"]), 0) + " Hz / "
            + juce::String(int(devices["buffer_size"])) + " samples / input " + juce::String(int(devices["input_latency_samples"])) + " + output "
            + juce::String(int(devices["output_latency_samples"])) + " latency samples", juce::dontSendNotification);
        if (scan) status.setText("Choose devices, then Apply. MIDI inputs are selected and armed in Devices / I/O.", juce::dontSendNotification);
        return true;
    }
    void rebuildDevices()
    {
        updating = true; const auto selected = selectedDriver(); const bool sameDriver = driver.getText() == devices["driver_type"].toString();
        output.clear(juce::dontSendNotification); int outputId = 0;
        if (const auto* list = selected["outputs"].getArray()) for (const auto& name : *list) {
            const int id = output.getNumItems() + 1; output.addItem(name.toString(), id);
            if (sameDriver && name.toString() == devices["output_device_name"].toString()) outputId = id;
        }
        output.setSelectedId(outputId > 0 ? outputId : output.getNumItems() > 0 ? 1 : 0, juce::dontSendNotification);
        output.setTextWhenNothingSelected("No output device available"); input.clear(juce::dontSendNotification); input.addItem(separateDevices() ? "None" : "Uses selected device", 1);
        int inputId = 1;
        if (separateDevices()) if (const auto* list = selected["inputs"].getArray()) for (const auto& name : *list) {
            const int id = input.getNumItems() + 1; input.addItem(name.toString(), id);
            if (sameDriver && name.toString() == devices["input_device_name"].toString()) inputId = id;
        }
        input.setSelectedId(inputId, juce::dontSendNotification); outputLabel.setText(separateDevices() ? "Output" : "Device", juce::dontSendNotification);
        updating = false; rebuildTiming();
    }
    void rebuildTiming()
    {
        updating = true; rate.clear(juce::dontSendNotification); buffer.clear(juce::dontSendNotification); rates.clear(); buffers.clear();
        const bool active = activeSelection();
        if (active) {
            if (const auto* values = devices["sample_rates"].getArray()) for (const auto& v : *values) if (double(v) > 0) rates.push_back(double(v));
            if (const auto* values = devices["buffer_sizes"].getArray()) for (const auto& v : *values) if (int(v) > 0) buffers.push_back(int(v));
            const auto currentRate = double(devices["sample_rate"]); const auto currentBuffer = int(devices["buffer_size"]);
            if (currentRate > 0 && std::find(rates.begin(), rates.end(), currentRate) == rates.end()) rates.push_back(currentRate);
            if (currentBuffer > 0 && std::find(buffers.begin(), buffers.end(), currentBuffer) == buffers.end()) buffers.push_back(currentBuffer);
            for (size_t i = 0; i < rates.size(); ++i) { rate.addItem(juce::String(rates[i], 0) + " Hz", int(i) + 1); if (rates[i] == currentRate) rate.setSelectedId(int(i) + 1, juce::dontSendNotification); }
            for (size_t i = 0; i < buffers.size(); ++i) { buffer.addItem(juce::String(buffers[i]) + " samples", int(i) + 1); if (buffers[i] == currentBuffer) buffer.setSelectedId(int(i) + 1, juce::dontSendNotification); }
        } else {
            rate.addItem("Device default", 1); buffer.addItem("Device default", 1); rate.setSelectedId(1, juce::dontSendNotification); buffer.setSelectedId(1, juce::dontSendNotification);
        }
        hint.setText(active ? "Choose the rate and buffer supported by the active device. New inputs start with monitoring off."
            : "Apply this device first, then choose its supported sample rate and buffer. New inputs start with monitoring off.", juce::dontSendNotification);
        updating = false; updateEnabled();
    }
    void updateEnabled()
    {
        driver.setEnabled(!applying); output.setEnabled(!applying); input.setEnabled(!applying && separateDevices());
        rate.setEnabled(!applying && activeSelection() && !rates.empty()); buffer.setEnabled(!applying && activeSelection() && !buffers.empty());
        refresh.setEnabled(!applying); apply.setEnabled(!applying && driver.getSelectedId() > 0 && output.getSelectedId() > 0);
        apply.setButtonText(applying ? "applying..." : "apply");
    }
    void beginApply()
    {
        if (applying || !apply.isEnabled()) return;
        auto args = arguments({ { "driver_type", driver.getText() } }); auto* fields = args.getDynamicObject();
        if (separateDevices()) { fields->setProperty("input_device_name", inputName()); fields->setProperty("output_device_name", output.getText()); }
        else fields->setProperty("device_name", output.getText());
        if (activeSelection()) {
            if (rate.getSelectedId() > 0 && rate.getSelectedId() <= int(rates.size())) fields->setProperty("sample_rate", rates[size_t(rate.getSelectedId() - 1)]);
            if (buffer.getSelectedId() > 0 && buffer.getSelectedId() <= int(buffers.size())) fields->setProperty("buffer_size", buffers[size_t(buffer.getSelectedId() - 1)]);
            juce::Array<juce::var> channels;
            if (const auto* list = devices["input_channels"].getArray()) for (const auto& channel : *list) if (bool(channel["active"])) channels.add(channel["index"]);
            fields->setProperty("input_channels", channels);
        }
        applying = true; updateEnabled(); status.setText("Applying audio settings...", juce::dontSendNotification);
        juce::MessageManager::callAsync([safe = juce::Component::SafePointer<AudioSettingsPanel>(this), args] {
            if (!safe) return;
            const auto result = safe->configure(args); safe->applying = false; const bool readback = safe->read(false); safe->updateEnabled();
            if (result.failed() || readback) safe->status.setText(result.failed() ? result.getErrorMessage() : "Audio settings applied. Active values are shown above.", juce::dontSendNotification);
        });
    }
    Query query; Configure configure; juce::var devices;
    juce::ComboBox driver, output, input, rate, buffer;
    juce::Label driverLabel, outputLabel, inputLabel, rateLabel, bufferLabel, actual, hint, status;
    juce::TextButton refresh { "refresh devices" }, apply { "apply" };
    std::vector<double> rates; std::vector<int> buffers;
    bool updating = false, applying = false;
};

class PluginPanel final : public juce::Component, private juce::Timer {
    struct Model final : juce::ListBoxModel {
        Model(PluginPanel& panel, bool isChain) : p(panel), chain(isChain) {}
        int getNumRows() override { return chain ? int(p.slots.size()) : int(p.filtered.size()); }
        void paintListBoxItem(int row, juce::Graphics& g, int width, int height, bool selected) override
        {
            if (row < 0 || row >= getNumRows()) return;
            if (selected) { g.setColour(ink.withAlpha(0.08f)); g.fillRect(0, 0, width, height); }
            g.setColour(ink); g.setFont(mono(13));
            if (chain) {
                const auto& slot = p.slots[std::size_t(row)];
                g.drawFittedText(juce::String(row + 1) + "  " + slot.name, 8, 4, width - 16, 23, juce::Justification::centredLeft, 1);
                g.setColour(secondary); g.setFont(mono(11));
                g.drawText(slot.format + (slot.missing ? " / missing" : slot.enabled ? " / on" : " / bypassed"), 8, 27, width - 16, 20, juce::Justification::centredLeft);
            } else {
                const auto& plugin = p.filtered[std::size_t(row)];
                g.drawFittedText(plugin.name, 8, 4, width - 16, 23, juce::Justification::centredLeft, 1);
                g.setColour(secondary); g.setFont(mono(11));
                g.drawFittedText(plugin.format + " / " + (plugin.isInstrument ? "instrument" : "effect") + " / " + plugin.manufacturer,
                                8, 27, width - 16, 20, juce::Justification::centredLeft, 1);
            }
            g.setColour(rule.withAlpha(0.5f)); g.drawHorizontalLine(height - 1, 8, float(width - 8));
        }
        void selectedRowsChanged(int) override { p.refreshButtons(); }
        void listBoxItemDoubleClicked(int, const juce::MouseEvent&) override { if (chain) p.open.onClick(); else p.add.onClick(); }
        PluginPanel& p; bool chain;
    };
public:
    PluginPanel(EngineSession& engine, std::function<void(const juce::Result&)> result) : session(engine), report(std::move(result)), catalogModel(*this, false), chainModel(*this, true), catalog("Installed plugins", &catalogModel), chain("Plugin chain", &chainModel)
    {
        for (juce::Component* c : std::initializer_list<juce::Component*> { &target, &search, &catalog, &chain, &scan, &directory, &add, &remove, &open, &bypass, &up, &down, &status }) addAndMakeVisible(c);
        search.setTextToShowWhenEmpty("Find an installed instrument or effect", secondary); search.onTextChange = [this] { filter(); };
        for (auto* list : { &catalog, &chain }) { list->setRowHeight(52); list->setColour(juce::ListBox::backgroundColourId, paper); }
        target.onChange = [this] { updateSlots(); };
        scan.onClick = [this] { run("scan_plugins", arguments({ { "paths", juce::var(juce::Array<juce::var>()) } })); };
        directory.onClick = [this] {
            if (chooser) return;
            chooser = std::make_unique<juce::FileChooser>("Scan a plugin folder", juce::File(), "*", true);
            chooser->launchAsync(juce::FileBrowserComponent::openMode | juce::FileBrowserComponent::canSelectDirectories,
                [safe = juce::Component::SafePointer<PluginPanel>(this)](const juce::FileChooser& dialog) {
                    const auto path = dialog.getResult();
                    juce::MessageManager::callAsync([safe, path] { if (safe) { safe->chooser.reset(); if (path.isDirectory()) safe->run("scan_plugins", arguments({ { "paths", juce::var(juce::Array<juce::var>{ path.getFullPathName() }) } })); } });
                });
        };
        add.onClick = [this] { const int row = catalog.getSelectedRow(); if (row >= 0 && row < int(filtered.size())) run("add_plugin", arguments({ { "track_id", targetId() }, { "catalog_id", filtered[std::size_t(row)].id } })); };
        remove.onClick = [this] { withSlot("remove_plugin"); };
        open.onClick = [this] { withSlot("open_plugin"); };
        bypass.onClick = [this] { const int row = chain.getSelectedRow(); if (row >= 0 && row < int(slots.size())) run("set_plugin_enabled", arguments({ { "track_id", targetId() }, { "plugin_id", slots[std::size_t(row)].id }, { "enabled", !slots[std::size_t(row)].enabled } })); };
        up.onClick = [this] { move(-1); }; down.onClick = [this] { move(1); };
        status.setFont(mono(12)); status.setColour(juce::Label::textColourId, secondary);
        setSize(900, 580); timerCallback(); startTimerHz(4);
    }
    ~PluginPanel() override { stopTimer(); catalog.setModel(nullptr); chain.setModel(nullptr); }
    void selectTarget(const juce::String& id)
    {
        timerCallback(); int chosen = 1;
        for (std::size_t i = 0; i < state.tracks.size(); ++i) if (state.tracks[i].id == id) chosen = int(i) + 2;
        target.setSelectedId(chosen, juce::dontSendNotification); updateSlots();
    }
    void paint(juce::Graphics& g) override
    {
        g.fillAll(paper); g.setColour(ink); g.setFont(mono(15));
        g.drawText("installed plugins", 16, 58, getWidth() / 2 - 30, 28, juce::Justification::centredLeft);
        g.drawText("signal chain", getWidth() / 2 + 14, 58, getWidth() / 2 - 30, 28, juce::Justification::centredLeft);
        g.setColour(rule); g.drawVerticalLine(getWidth() / 2, 58, float(getHeight() - 75));
    }
    void resized() override
    {
        const int half = getWidth() / 2;
        search.setBounds(16, 16, half - 30, 30); target.setBounds(half + 14, 16, half - 30, 30);
        catalog.setBounds(16, 90, half - 30, getHeight() - 210); chain.setBounds(half + 14, 90, half - 30, getHeight() - 210);
        scan.setBounds(16, getHeight() - 110, 122, 32); directory.setBounds(146, getHeight() - 110, 125, 32); add.setBounds(half - 111, getHeight() - 110, 95, 32);
        auto row = juce::Rectangle<int>(half + 14, getHeight() - 110, half - 30, 32);
        open.setBounds(row.removeFromLeft(80)); bypass.setBounds(row.removeFromLeft(85)); up.setBounds(row.removeFromLeft(38)); down.setBounds(row.removeFromLeft(38)); remove.setBounds(row);
        status.setBounds(16, getHeight() - 68, getWidth() - 32, 54);
    }
private:
    juce::String targetId() const { const int i = target.getSelectedId() - 2; return i >= 0 && i < int(state.tracks.size()) ? state.tracks[std::size_t(i)].id : "master"; }
    void run(const juce::String& command, const juce::var& args)
    {
        const auto result = session.execute(command, args, session.snapshot().revision);
        if (report) report(result);
        if (result.failed()) status.setText(result.getErrorMessage(), juce::dontSendNotification);
        timerCallback();
    }
    void withSlot(const juce::String& command)
    {
        const int row = chain.getSelectedRow(); if (row >= 0 && row < int(slots.size())) run(command, arguments({ { "track_id", targetId() }, { "plugin_id", slots[std::size_t(row)].id } }));
    }
    void move(int delta)
    {
        const int row = chain.getSelectedRow(); if (row >= 0 && row + delta >= 0 && row + delta < int(slots.size())) run("move_plugin", arguments({ { "track_id", targetId() }, { "plugin_id", slots[std::size_t(row)].id }, { "index", row + delta } }));
    }
    void filter()
    {
        filtered.clear(); const auto term = search.getText().trim();
        for (const auto& p : state.pluginCatalog) if (term.isEmpty() || (p.name + p.manufacturer + p.format).containsIgnoreCase(term)) filtered.push_back(p);
        catalog.updateContent(); catalog.repaint(); refreshButtons();
    }
    void updateSlots()
    {
        slots = state.masterPlugins; for (const auto& track : state.tracks) if (track.id == targetId()) slots = track.plugins;
        chain.updateContent(); chain.repaint(); refreshButtons();
    }
    void refreshButtons()
    {
        add.setEnabled(catalog.getSelectedRow() >= 0 && catalog.getSelectedRow() < int(filtered.size()));
        const int row = chain.getSelectedRow(); const bool chosen = row >= 0 && row < int(slots.size());
        remove.setEnabled(chosen); bypass.setEnabled(chosen); open.setEnabled(chosen && !slots[std::size_t(row)].missing);
        up.setEnabled(chosen && row > 0); down.setEnabled(chosen && row + 1 < int(slots.size()));
        bypass.setButtonText(chosen && !slots[std::size_t(row)].enabled ? "enable" : "bypass");
    }
    void timerCallback() override
    {
        auto next = session.snapshot();
        const bool tracksChanged = next.revision != state.revision || next.projectId != state.projectId || next.tracks.size() != state.tracks.size();
        const bool catalogChanged = next.pluginCatalog.size() != state.pluginCatalog.size() || next.pluginScanning != state.pluginScanning;
        const auto oldTarget = targetId(); const bool first = target.getNumItems() == 0; state = std::move(next);
        setEnabled(!state.recording && !state.recordingFinalizing);
        if (tracksChanged || first) {
            target.clear(juce::dontSendNotification); target.addItem("Master output", 1); int chosen = 1;
            for (std::size_t i = 0; i < state.tracks.size(); ++i) { target.addItem(state.tracks[i].name, int(i) + 2); if (state.tracks[i].id == (first ? state.selectedTrackId : oldTarget)) chosen = int(i) + 2; }
            target.setSelectedId(chosen, juce::dontSendNotification); updateSlots();
        }
        if (catalogChanged || first) filter();
        scan.setEnabled(!state.pluginScanning); directory.setEnabled(!state.pluginScanning);
        if (state.pluginScanning) status.setText("Scanning in a separate process. You can continue editing the project.", juce::dontSendNotification);
        else if (status.getText().isEmpty() || catalogChanged) status.setText(juce::String(int(state.pluginCatalog.size())) + " plugins. Select an instrument for a MIDI track, or add effects to a track / master.\nPlugin binaries and sample libraries stay in their installed locations.", juce::dontSendNotification);
    }
    EngineSession& session; std::function<void(const juce::Result&)> report;
    Model catalogModel, chainModel; juce::ListBox catalog, chain;
    juce::ComboBox target; juce::TextEditor search;
    juce::TextButton scan { "scan installed" }, directory { "scan folder..." }, add { "add >" }, remove { "remove" }, open { "open" }, bypass { "bypass" }, up { "up" }, down { "dn" };
    juce::Label status; std::unique_ptr<juce::FileChooser> chooser;
    EngineSession::Snapshot state;
    std::vector<EngineSession::PluginDescriptorSnapshot> filtered;
    std::vector<EngineSession::PluginSlotSnapshot> slots;
};
} // namespace

struct MainComponent::Impl : private juce::ListBoxModel {
    explicit Impl(MainComponent& component, EngineSession& engine)
        : owner(component), arrangement(engine), waveform(engine, arrangement), trackPanel(engine), tooltips(&component, 550), trackList("Audio tracks", this)
    {
        owner.setLookAndFeel(&look);
        juce::Component* children[] { &settings, &importButton, &transcribe, &compose, &separate, &filename,
            &status, &gain, &play, &stop, &loop, &waveform, &trackList, &newButton, &openButton,
            &saveButton, &saveAsButton, &undoButton, &redoButton, &trackGain, &mute, &solo, &remove,
            &arrangement, &zoomOut, &zoomIn, &fit, &clipStart, &setClipStart,
            &editMenu, &exportMenu, &plugins, &tempo, &gridMode, &clipProperties, &trackPan, &cancelJob,
            &closeEditor, &details, &saveStatus, &trackPanel, &record, &rulerMode, &snap, &follow,
            &metronome, &metronomeOptions, &countIn, &countInBars, &resources, &meterReset };
        for (auto* child : children) {
            owner.addAndMakeVisible(child);
            child->addKeyListener(&owner);
        }
        for (auto* label : { &filename, &status, &saveStatus }) {
            label->setFont(mono(15.0f));
            label->setColour(juce::Label::textColourId, ink);
            label->setInterceptsMouseClicks(false, false);
        }
        for (auto* button : { &separate, &transcribe, &compose, &newButton, &openButton, &saveButton, &saveAsButton,
                             &undoButton, &redoButton, &editMenu, &exportMenu, &plugins, &tempo })
            button->getProperties().set("flat", true);
        transcribe.setVisible(false);
        compose.setVisible(false);
        separate.setButtonText("source");
        compose.setTooltip("View every audio and MIDI track on one shared timeline.");
        separate.setTooltip("Inspect the selected track waveform. Source separation is not available yet.");
        compose.onClick = [this] { composeActive = true; dock = Dock::closed; owner.resized(); owner.refreshSnapshot(); owner.repaint(); };
        separate.onClick = [this] { dock = dock == Dock::source ? Dock::closed : Dock::source; owner.resized(); owner.refreshSnapshot(); owner.repaint(); };
        closeEditor.onClick = [this] { dock = Dock::closed; owner.resized(); owner.repaint(); };
        closeEditor.setTooltip("Close the lower editor. Double-click a MIDI clip to reopen it.");
        details.onClick = [this] { inspectorVisible = !inspectorVisible; owner.resized(); owner.repaint(); };
        details.setTooltip("Show or hide selected track and clip controls.");
        arrangement.onUserStateChange = [&component] { component.refreshSnapshot(); };
        arrangement.onEditResult = [&component](const juce::Result& result) { component.showResult(result); };
        arrangement.onOpenMidiClip = [&component](const juce::String&) { component.showPianoRoll(); };
        arrangement.onOpenTrackDevices = [this](const juce::String&) { dock = Dock::track; trackPanel.showDevices(); owner.resized(); owner.repaint(); };
        trackPanel.onResult = [&component](const juce::Result& result) { component.showResult(result); };
        trackPanel.onBrowsePlugins = [&component](const juce::String& target) { component.showPlugins(target); };
        editMenu.onClick = [&component] { component.showEditMenu(); };
        exportMenu.onClick = [&component] { component.showExportMenu(); };
        plugins.onClick = [this] { dock = dock == Dock::track ? Dock::closed : Dock::track; owner.resized(); owner.refreshSnapshot(); owner.repaint(); };
        tempo.onClick = [&component] { component.showProjectTiming(); };
        clipProperties.onClick = [&component] { component.showClipProperties(); };
        rulerMode.addItem("bars",1);rulerMode.addItem("seconds",2);rulerMode.addItem("both",3);
        rulerMode.setSelectedId(1,juce::dontSendNotification);
        rulerMode.onChange=[this]{arrangement.setRulerMode(rulerMode.getSelectedId()-1);owner.resetClipStartInput();owner.repaint();};
        rulerMode.setTooltip("Ruler units only. Musical position uses bar:beat:tick (960 ticks per meter beat). Snap is independent.");
        gridMode.addItem("adaptive",1);gridMode.addItem("1 bar",2);
        gridMode.addItem("1/4", 3); gridMode.addItem("1/8", 4); gridMode.addItem("1/16", 5); gridMode.addItem("1/32", 6);
        gridMode.addItem("1/8 triplet",7);gridMode.addItem("1/16 triplet",8);
        gridMode.setSelectedId(5, juce::dontSendNotification);
        gridMode.onChange = [this] { const int n=gridMode.getSelectedId();arrangement.setAdaptiveGrid(n==1);
            arrangement.setGridBeats(n==2?state.numerator*4.0/state.denominator:n==7?1.0/3:n==8?1.0/6:n==1?0.25:std::pow(0.5,n-3)); };
        gridMode.onChange();
        gridMode.setTooltip("Edit grid. Fixed spacing survives zoom; adaptive follows zoom. Alt temporarily bypasses snapping.");
        snap.setClickingTogglesState(true);snap.setToggleState(true,juce::dontSendNotification);
        snap.onClick=[this]{arrangement.setSnapEnabled(snap.getToggleState());};
        snap.setTooltip("Snap edits to grid and nearby clip edges. Ctrl+4 toggles; Alt temporarily bypasses.");
        follow.setClickingTogglesState(true);follow.onClick=[this]{arrangement.setFollowPlayhead(follow.getToggleState());};
        follow.setTooltip("Follow playback. Manual scrolling or editing pauses following until playback restarts.");
        metronome.onClick=[this]{owner.execute("set_recording_preferences",arguments({{"metronome_enabled",!state.metronomeEnabled}}));};
        metronome.setTooltip("Metronome on/off. Its sound is for monitoring and is excluded from export.");
        metronomeOptions.onClick=[this]{owner.showMetronomeOptions();};
        metronomeOptions.setTooltip("Metronome volume and recording-only mode.");
        countIn.onClick=[this]{owner.execute("set_recording_preferences",arguments({{"count_in_enabled",!state.countInEnabled}}));};
        countIn.setTooltip("Enable recording count-in. Stop cancels the count-in; normal playback has no count-in.");
        countInBars.addItem("1 bar",1);countInBars.addItem("2 bars",2);countInBars.addItem("4 bars",4);
        countInBars.onChange=[this]{owner.execute("set_recording_preferences",arguments({{"count_in_bars",countInBars.getSelectedId()}}));};
        resources.setFont(mono(11));resources.setJustificationType(juce::Justification::centredRight);
        meterReset.setTooltip("Master output peak meters. Click to reset overload indicators.");
        meterReset.onClick=[this]{owner.execute("reset_meters",arguments({}));};
        cancelJob.onClick = [this] {
            for (auto it = state.jobs.rbegin(); it != state.jobs.rend(); ++it) if (it->status == "queued" || it->status == "running") {
                owner.execute("cancel_job", arguments({ { "job_id", it->id } })); return;
            }
        };
        clipStart.setName("Selected clip start in seconds");
        clipStart.setFont(mono(13.0f));
        clipStart.setJustification(juce::Justification::centredRight);
        clipStart.setInputRestrictions(24, "0123456789.:-");
        clipStart.setSelectAllWhenFocused(true);
        clipStart.setTooltip("Start in ruler units: bar:beat:tick or seconds. Enter/set applies; Escape restores. 960 ticks per meter beat.");
        clipStart.onEditBegin = [this] {
            if (!startInputDirty) { startEditId = state.selectedClipId; startEditRevision = state.revision; }
        };
        clipStart.onTextChange = [this] {
            if (updatingStartInput) return;
            if (startEditId.isEmpty()) { startEditId = state.selectedClipId; startEditRevision = state.revision; }
            startInputDirty = true;
            setClipStart.setEnabled(selectedClip() != nullptr && chooser == nullptr && !confirming);
        };
        clipStart.onReturnKey = [&component] {
            if (!component.commitClipStart()) return;
            auto& p = *component.impl;
            juce::Component& workspace = p.composeActive ? static_cast<juce::Component&>(p.arrangement)
                                                         : static_cast<juce::Component&>(p.waveform);
            if (workspace.isShowing()) workspace.grabKeyboardFocus();
        };
        clipStart.onEscapeKey = [&component] { component.resetClipStartInput(); };
        setClipStart.onClick = [&component] { component.commitClipStart(); };
        setClipStart.setTooltip("Apply the clip start time. One move can be undone with Ctrl+Z.");
        zoomIn.setTitle("Zoom in timeline");
        zoomOut.setTitle("Zoom out timeline");
        zoomIn.setTooltip("Zoom in (up to 32x). Ctrl + wheel also zooms around the pointer.");
        zoomOut.setTooltip("Zoom out. Ctrl + wheel also zooms around the pointer.");
        fit.setTooltip("Fit the whole project into the timeline.");
        zoomIn.onClick = [this] { arrangement.zoomIn(); };
        zoomOut.onClick = [this] { arrangement.zoomOut(); };
        fit.onClick = [this] { arrangement.fitToProject(); };
        importButton.setButtonText("add...");
        importButton.setTooltip("Add audio files, import MIDI, or create an empty track.");
        settings.setTooltip("Choose the output device, sample rate, and buffer size.");
        newButton.setTooltip("New project (Ctrl+N). Unsaved changes will be checked.");
        openButton.setTooltip("Open an .emproj project (Ctrl+O).");
        saveButton.setTooltip("Save the project and copies of its source audio (Ctrl+S).");
        saveAsButton.setTooltip("Save a copy to another .emproj file (Ctrl+Shift+S).");
        remove.setTooltip("Remove the selected track. Undo restores it.");
        settings.onClick = [&component] { component.showAudioSettings(); };
        importButton.onClick = [&component] { component.showAddMenu(); };
        newButton.onClick = [&component] { component.newProject(); };
        openButton.onClick = [&component] { component.openProject(); };
        saveButton.onClick = [&component] { component.saveProject(false); };
        saveAsButton.onClick = [&component] { component.saveProject(true); };
        undoButton.onClick = [&component, &engine] {
            engine.endEditGesture();
            component.showResult(engine.undo(component.impl->state.revision));
        };
        redoButton.onClick = [&component, &engine] {
            engine.endEditGesture();
            component.showResult(engine.redo(component.impl->state.revision));
        };
        play.onClick = [&component, &engine] { component.impl->error.clear(); engine.togglePlay(); component.refreshSnapshot(); };
        stop.onClick = [&component, &engine] { component.impl->error.clear(); if (engine.snapshot().recording) component.execute("stop_recording", arguments({})); else engine.stop(); component.refreshSnapshot(); };
        record.onClick = [&component] {
            if (!component.impl->state.recording && component.impl->audioDialog != nullptr) {
                component.showResult(juce::Result::fail("Close Audio and MIDI devices before starting a recording.")); return;
            }
            component.execute(component.impl->state.recording ? "stop_recording" : "start_recording", arguments({}));
        };
        record.setTooltip("Record armed audio and MIDI tracks. Choose inputs in Devices / I/O first.");
        loop.onClick = [&component, &engine] {
            component.impl->error.clear(); engine.setLoop(! engine.snapshot().looping); component.refreshSnapshot();
        };
        play.setTooltip("Play or pause the project mix. Shortcut: Space.");
        stop.setTooltip("Stop playback and return to the start.");
        loop.setTooltip("Loop the chosen range. Shift-drag the ruler selects time; Ctrl+L loops the selection. Drag the loop brace to adjust.");
        for (auto* slider : { &gain, &trackGain }) {
            slider->setSliderStyle(juce::Slider::LinearHorizontal);
            slider->setTextBoxStyle(juce::Slider::TextBoxRight, false, 76, 30);
            slider->setRange(-60.0, 6.0, 0.1);
            slider->setTextValueSuffix(" dB");
            slider->setNumDecimalPlacesToDisplay(1);
            slider->onDragStart = [&engine] { engine.beginEditGesture(); };
            slider->onDragEnd = [&engine] { engine.endEditGesture(); };
        }
        gain.setName("Master output gain");
        gain.setTooltip("Master output gain. Source files are unchanged.");
        gain.setDoubleClickReturnValue(true, -6.0);
        gain.onValueChange = [&component, &engine] {
            component.impl->error.clear();
            engine.setGain(static_cast<float>(component.impl->gain.getValue()));
            component.refreshSnapshot();
        };
        trackGain.setName("Selected track gain");
        trackGain.setTooltip("Gain for the selected track. Double-click resets to 0 dB.");
        trackGain.setDoubleClickReturnValue(true, 0.0);
        trackGain.onDragStart = [this, &engine] {
            trackGestureId = state.selectedTrackId;
            engine.beginEditGesture();
        };
        trackGain.onDragEnd = [this, &engine] { engine.endEditGesture(); trackGestureId.clear(); };
        trackGain.onValueChange = [&component, &engine] {
            auto& p = *component.impl;
            const auto id = p.trackGestureId.isEmpty() ? p.state.selectedTrackId : p.trackGestureId;
            component.showResult(engine.setTrackGain(id, static_cast<float>(p.trackGain.getValue()), p.state.revision));
        };
        trackPan.setSliderStyle(juce::Slider::LinearHorizontal); trackPan.setTextBoxStyle(juce::Slider::TextBoxRight, false, 64, 27);
        trackPan.setRange(-1.0, 1.0, 0.01); trackPan.setDoubleClickReturnValue(true, 0.0); trackPan.setName("Selected track pan");
        trackPan.onDragStart = [this, &engine] { trackGestureId = state.selectedTrackId; engine.beginEditGesture(); };
        trackPan.onDragEnd = [this, &engine] { engine.endEditGesture(); trackGestureId.clear(); };
        trackPan.onValueChange = [this] { owner.execute("set_track_pan", arguments({ { "track_id", trackGestureId.isEmpty() ? state.selectedTrackId : trackGestureId }, { "pan", trackPan.getValue() } })); };
        mute.setTooltip("Mute the selected track. Mute and Solo are independent.");
        solo.setTooltip("Listen to soloed tracks in the project mix.");
        mute.onClick = [&component, &engine] {
            auto& p = *component.impl;
            if (const auto* track = p.selectedTrack())
                component.showResult(engine.setTrackMuted(track->id, !track->muted, p.state.revision));
        };
        solo.onClick = [&component, &engine] {
            auto& p = *component.impl;
            if (const auto* track = p.selectedTrack())
                component.showResult(engine.setTrackSolo(track->id, !track->solo, p.state.revision));
        };
        remove.onClick = [&component, &engine] {
            engine.endEditGesture();
            component.showResult(engine.removeTrack(component.impl->state.selectedTrackId, component.impl->state.revision));
        };
        trackList.setRowHeight(62);
        trackList.setColour(juce::ListBox::backgroundColourId, paper);
        trackList.setColour(juce::ListBox::outlineColourId, juce::Colours::transparentBlack);
        trackList.setMultipleSelectionEnabled(false);
        trackList.setTitle("Audio tracks");
        trackList.setDescription("Select a track to inspect its waveform, gain, mute and solo controls.");
    }
    ~Impl()
    {
        chooser.reset();
        trackList.setModel(nullptr);
        if (audioDialog != nullptr) delete audioDialog.getComponent();
        if (pluginDialog != nullptr) delete pluginDialog.getComponent();
        if (pianoDialog != nullptr) delete pianoDialog.getComponent();
        for (auto& form : forms) if (form != nullptr) delete form.getComponent();
        owner.setLookAndFeel(nullptr);
    }
    const EngineSession::TrackSnapshot* selectedTrack() const
    {
        for (const auto& track : state.tracks)
            if (track.id == state.selectedTrackId) return &track;
        return nullptr;
    }
    const EngineSession::ClipSnapshot* selectedClip() const
    {
        for (const auto& track : state.tracks) for (const auto& clip : track.clips)
            if (clip.id == state.selectedClipId) return &clip;
        return nullptr;
    }
    juce::String selectedClipName() const
    {
        for (const auto& track : state.tracks)
            for (std::size_t i = 0; i < track.clips.size(); ++i)
                if (track.clips[i].id == state.selectedClipId)
                    return track.name + (track.clips.size() > 1 ? " / clip " + juce::String(static_cast<int>(i) + 1) : juce::String());
        return "no clip selected";
    }
    void updateDeviceButtons()
    {
        const auto* track = selectedTrack();
        juce::String identity = state.selectedTrackId;
        if (track) for (const auto& slot : track->plugins) identity += "/" + slot.id + "/" + slot.name + (slot.enabled ? "+" : "-") + (slot.missing ? "?" : "");
        if (identity == deviceIdentity) return;
        deviceIdentity = identity; deviceButtons.clear();
        if (track) for (const auto& slot : track->plugins) {
            auto button = std::make_unique<juce::TextButton>((slot.enabled ? "" : "[off] ") + slot.name);
            button->setTooltip(slot.missing ? "This plug-in is missing. Open Devices to replace it." : "Open " + slot.name + ". Right-click the chain in Devices for other actions.");
            button->setEnabled(!slot.missing);
            button->onClick = [this, trackId = track->id, pluginId = slot.id] { owner.execute("open_plugin", arguments({ { "track_id", trackId }, { "plugin_id", pluginId } })); };
            owner.addAndMakeVisible(*button); deviceButtons.push_back(std::move(button));
        }
        layoutDeviceButtons();
    }
    void layoutDeviceButtons()
    {
        int y = 470;
        for (auto& button : deviceButtons) {
            button->setBounds(inspector.getX(), y, inspector.getWidth(), 28);
            button->setVisible(inspectorVisible && y + 28 <= footerY - 12);
            y += 34;
        }
    }
    int getNumRows() override { return static_cast<int>(state.tracks.size()); }
    juce::String getTooltipForRow(int row) override
    {
        if (row < 0 || row >= getNumRows()) return {};
        const auto& track = state.tracks[static_cast<std::size_t>(row)];
        return track.name + "\n" + track.source.getFullPathName()
             + (track.muted ? "\nMuted" : "") + (track.solo ? "\nSoloed" : "");
    }
    void paintListBoxItem(int row, juce::Graphics& g, int width, int height, bool selected) override
    {
        if (row < 0 || row >= getNumRows()) return;
        const auto& track = state.tracks[static_cast<std::size_t>(row)];
        if (selected) { g.setColour(ink.withAlpha(0.07f)); g.fillRect(0, 0, width, height); }
        g.setColour(ink); g.setFont(mono(14.0f, selected ? juce::Font::bold : juce::Font::plain));
        if (selected) g.fillEllipse(5.0f, 14.0f, 5.0f, 5.0f);
        g.drawFittedText(track.name, 16, 4, width - 23, 26, juce::Justification::centredLeft, 1);
        g.setColour(secondary); g.setFont(mono(11.5f));
        auto detail = track.format + "  " + clockText(track.duration);
        if (track.muted) detail += "  M";
        if (track.solo) detail += "  S";
        g.drawFittedText(detail, 16, 31, width - 23, 22, juce::Justification::centredLeft, 1);
        g.setColour(rule.withAlpha(0.55f));
        g.drawHorizontalLine(height - 1, 16.0f, static_cast<float>(width - 8));
    }
    void selectedRowsChanged(int row) override
    {
        if (updatingList || row < 0 || row >= getNumRows()) return;
        owner.session.endEditGesture();
        owner.session.selectTrack(state.tracks[static_cast<std::size_t>(row)].id);
        owner.refreshSnapshot();
    }
    MainComponent& owner;
    InstrumentLook look;
    ArrangementView arrangement;
    WaveformView waveform;
    SelectedTrackPanel trackPanel;
    juce::TooltipWindow tooltips;
    juce::ListBox trackList;
    juce::TextButton settings { "audio settings" }, importButton { "add audio" }, transcribe { "transcribe" }, compose { "compose" };
    juce::TextButton newButton { "new" }, openButton { "open" }, saveButton { "save" }, saveAsButton { "save as" };
    juce::TextButton undoButton { "undo" }, redoButton { "redo" }, mute { "mute" }, solo { "solo" }, remove { "remove track" };
    juce::TextButton separate { "separate" }, zoomOut { "-" }, zoomIn { "+" }, fit { "fit" };
    juce::TextButton editMenu { "edit" }, exportMenu { "export" }, plugins { "devices" }, tempo { "120 BPM" };
    juce::TextButton clipProperties { "clip properties..." }, cancelJob { "cancel task" };
    juce::ComboBox gridMode, rulerMode, countInBars;
    juce::TextButton snap { "snap" }, follow { "follow" }, metronome { "click" }, metronomeOptions { "..." }, countIn { "count-in" }, meterReset { "OUT" };
    juce::Label resources;
    juce::Label filename, status, saveStatus;
    juce::TextButton closeEditor { "close editor" }, details { "details" };
    ClipStartEditor clipStart;
    juce::TextButton setClipStart { "set" };
    juce::Slider gain, trackGain, trackPan;
    TransportButton play { "play", TransportButton::play }, stop { "stop", TransportButton::stop }, loop { "loop", TransportButton::loop };
    TransportButton record { "rec", TransportButton::record };
    std::unique_ptr<juce::FileChooser> chooser;
    juce::Component::SafePointer<juce::DialogWindow> audioDialog;
    juce::Component::SafePointer<juce::DialogWindow> pluginDialog, pianoDialog;
    juce::Component::SafePointer<PianoRoll> pianoRoll;
    std::unique_ptr<PianoRoll> dockPiano;
    std::vector<std::unique_ptr<juce::TextButton>> deviceButtons;
    juce::String deviceIdentity;
    std::vector<juce::Component::SafePointer<juce::DialogWindow>> forms;
    std::function<void()> pendingAfterSave;
    juce::String pendingSaveJob;
    juce::String saveProjectId, saveError, saveFeedback;
    juce::File saveTarget;
    bool savePreparing = false, saveAgain = false, saveFollowupAllowed = true, saveContinuationPending = false;
    std::uint64_t saveRevision = 0;
    EngineSession::Snapshot state;
    juce::String error, trackGestureId, startEditId;
    std::uint64_t startEditRevision = 0;
    juce::Rectangle<int> library, workspace, inspector, dockBounds;
    enum class Dock { closed, source, midi, track };
    Dock dock = Dock::closed;
    bool inspectorVisible = true;
    int footerY = 0;
    bool updatingList = false, confirming = false, composeActive = true, startInputDirty = false, updatingStartInput = false;
};

MainComponent::MainComponent(EngineSession& engine) : session(engine), impl(std::make_unique<Impl>(*this, engine))
{
    setOpaque(true);
    setWantsKeyboardFocus(true);
    setSize(1280, 800);
    refreshSnapshot();
    // Combo defaults use dontSendNotification while Impl is constructed.
    // Apply them only after impl exists, so a fresh view matches its toolbar.
    impl->rulerMode.onChange();impl->gridMode.onChange();impl->snap.onClick();impl->follow.onClick();
    startTimerHz(30);
}
MainComponent::~MainComponent() { stopTimer(); }

void MainComponent::resized()
{
    auto& p = *impl;
    constexpr int margin = 16;
    p.footerY = getHeight() - 110;
    const int inspectorWidth = p.inspectorVisible ? 226 : 0;
    p.inspector = { getWidth() - margin - inspectorWidth, 144, inspectorWidth, p.footerY - 156 };
    p.workspace = { margin, 144, getWidth() - margin * 2 - (p.inspectorVisible ? inspectorWidth + 16 : 0), p.footerY - 156 };
    p.library = {};
    p.trackList.setVisible(false); p.compose.setVisible(false); p.transcribe.setVisible(false); p.filename.setVisible(false);
    auto header = juce::Rectangle<int>(getWidth() - 590, 14, 574, 32);
    for (auto* b : { &p.newButton, &p.openButton, &p.saveButton, &p.saveAsButton, &p.exportMenu, &p.settings }) {
        const int w = b == &p.settings ? 140 : b == &p.saveAsButton ? 86 : b == &p.saveButton ? 94 : 76;
        b->setBounds(header.removeFromLeft(w).reduced(2, 0));
    }
    p.saveStatus.setBounds(71, 45, juce::jmax(160, p.newButton.getX() - 80), 22);
    int x = margin;
    for (auto* b : { &p.importButton, &p.editMenu, &p.plugins, &p.separate, &p.details }) {
        b->setBounds(x, 75, b == &p.importButton ? 80 : 76, 30); x = b->getRight() + 4;
    }
    p.undoButton.setBounds(x + 8, 75, 60, 30); p.redoButton.setBounds(x + 72, 75, 60, 30);
    p.rulerMode.setBounds(margin,113,102,28);p.snap.setBounds(126,113,66,28);
    p.gridMode.setBounds(200,113,128,28);p.follow.setBounds(336,113,76,28);
    p.zoomOut.setBounds(getWidth() - margin - 120, 75, 32, 30);
    p.zoomIn.setBounds(getWidth() - margin - 84, 75, 32, 30);
    p.fit.setBounds(getWidth() - margin - 48, 75, 48, 30);
    const int dockHeight = p.dock == Impl::Dock::closed ? 0 : juce::jlimit(180, 340, p.workspace.getHeight() - 204);
    p.dockBounds = p.workspace.withTrimmedTop(p.workspace.getHeight() - dockHeight);
    p.arrangement.setBounds(p.workspace.withTrimmedBottom(dockHeight > 0 ? dockHeight + 6 : 0));
    p.arrangement.setCompactRows(dockHeight > 0 && p.arrangement.getHeight() < 258);
    p.arrangement.setVisible(true);
    p.closeEditor.setVisible(dockHeight > 0);
    p.closeEditor.setBounds(p.dockBounds.getRight() - 112, p.dockBounds.getY(), 112, 26);
    p.waveform.setVisible(p.dock == Impl::Dock::source);
    p.waveform.setBounds(p.dockBounds.reduced(0, 30));
    if (p.pianoRoll) { p.pianoRoll->setVisible(p.dock == Impl::Dock::midi); p.pianoRoll->setBounds(p.dockBounds.withTrimmedTop(24)); }
    p.trackPanel.setVisible(p.dock == Impl::Dock::track); p.trackPanel.setBounds(p.dockBounds.withTrimmedTop(28));
    p.separate.setToggleState(p.dock == Impl::Dock::source, juce::dontSendNotification);
    p.details.setToggleState(p.inspectorVisible, juce::dontSendNotification);
    const int ix = p.inspector.getX(), iw = p.inspector.getWidth();
    p.clipStart.setBounds(ix + 54, 206, iw - 104, 28); p.setClipStart.setBounds(ix + iw - 46, 206, 46, 28);
    p.clipProperties.setBounds(ix, 242, iw, 28);
    p.trackGain.setBounds(ix, 298, iw, 30); p.trackPan.setBounds(ix, 356, iw, 30);
    p.mute.setBounds(ix, 394, (iw - 6) / 2, 28); p.solo.setBounds(p.mute.getRight() + 6, 394, (iw - 6) / 2, 28);
    p.remove.setVisible(false);
    for (juce::Component* c : std::initializer_list<juce::Component*>{ &p.clipStart, &p.setClipStart, &p.clipProperties, &p.trackGain, &p.trackPan, &p.mute, &p.solo }) c->setVisible(p.inspectorVisible);
    p.layoutDeviceButtons();
    p.play.setBounds(margin, p.footerY + 8, 88, 38); p.stop.setBounds(108, p.footerY + 8, 88, 38); p.record.setBounds(200, p.footerY + 8, 80, 38); p.loop.setBounds(284, p.footerY + 8, 88, 38);
    p.tempo.setBounds(498, p.footerY + 8, 102, 34);
    p.gain.setBounds(getWidth() - margin - 260, p.footerY + 8, 260, 36);
    p.meterReset.setBounds(p.gain.getX()-50,p.footerY+10,46,30);
    p.metronome.setBounds(margin,p.footerY+50,80,30);p.metronomeOptions.setBounds(100,p.footerY+50,38,30);
    p.countIn.setBounds(152,p.footerY+50,104,30);p.countInBars.setBounds(264,p.footerY+50,100,30);
    p.resources.setBounds(380,p.footerY+50,getWidth()-396,30);
    p.cancelJob.setBounds(getWidth() - margin - 116, p.footerY + 85, 116, 22);
    p.status.setBounds(margin, p.footerY + 86, getWidth() - margin * 2 - 125, 20);
}

void MainComponent::paint(juce::Graphics& g)
{
    const auto& p = *impl; const auto& s = p.state;
    g.fillAll(paper);
    g.setColour(ink); g.setFont(mono(30.0f, juce::Font::bold)); g.drawText("e~", 17, 14, 51, 40, juce::Justification::centredLeft);
    g.setFont(mono(17.0f));
    g.drawFittedText((s.projectName.isEmpty() ? juce::String("Untitled") : s.projectName) + (s.dirty ? " *" : ""), 71, 16,
        juce::jmax(120, p.newButton.getX() - 80), 29, juce::Justification::centredLeft, 1);
    g.setColour(rule); g.drawHorizontalLine(68, 16.0f, float(getWidth() - 16));
    g.drawHorizontalLine(109, 16.0f, float(getWidth() - 16));
    g.drawHorizontalLine(142,16.0f,float(getWidth()-16));
    g.setColour(secondary);g.setFont(mono(11));
    g.drawFittedText("drag empty: select clips   Shift-drag ruler: time   Ctrl+L: loop",426,115,getWidth()-442,24,juce::Justification::centredLeft,1);
    if (p.inspectorVisible) {
        const int ix = p.inspector.getX(), iw = p.inspector.getWidth();
        g.drawVerticalLine(ix - 8, 144.0f, float(p.footerY - 12));
        g.setColour(ink); g.setFont(mono(14.0f, juce::Font::bold));
        g.drawFittedText(p.selectedTrack() ? p.selectedTrack()->name : "Select a track", ix, 158, iw, 30, juce::Justification::centredLeft, 1);
        g.setColour(secondary); g.setFont(mono(12.0f));
        g.drawText(p.rulerMode.getSelectedId()==2?"start/s":"start", ix, 206, 54, 28, juce::Justification::centredLeft);
        g.drawText("track volume", ix, 276, iw, 22, juce::Justification::centredLeft);
        g.drawText("pan / L - R", ix, 334, iw, 22, juce::Justification::centredLeft);
        g.drawText("devices", ix, 439, iw, 24, juce::Justification::centredLeft);
        if (const auto* track = p.selectedTrack()) {
            if (track->plugins.empty()) g.drawFittedText(track->kind == "instrument" ? "Add an instrument in Devices." : "No effects. Add in Devices.", ix, 470, iw, 44, juce::Justification::topLeft, 2);
        }
    }
    if (p.dock != Impl::Dock::closed) {
        g.setColour(rule); g.drawHorizontalLine(p.dockBounds.getY(), float(p.dockBounds.getX()), float(p.dockBounds.getRight()));
        g.setColour(secondary); g.setFont(mono(12));
        g.drawFittedText(p.dock == Impl::Dock::track ? "track / " + (p.selectedTrack() ? p.selectedTrack()->name : juce::String("Select a track")) : (p.dock == Impl::Dock::midi ? "MIDI / " : "source / ") + p.selectedClipName(), p.dockBounds.getX() + 5, p.dockBounds.getY() + 2,
            p.dockBounds.getWidth() - 130, 24, juce::Justification::centredLeft, 1);
    }
    g.setColour(ink); g.drawHorizontalLine(p.footerY, 16.0f, float(getWidth() - 16));
    g.setFont(mono(14)); g.drawText(p.rulerMode.getSelectedId()==2?clockText(s.position):positionText(s.position,s,true), 382, p.footerY + 8, 110, 23, juce::Justification::centredLeft);
    g.setColour(secondary); g.setFont(mono(11)); g.drawText("/ " + clockText(s.duration), 382, p.footerY + 30, 110, 17, juce::Justification::centredLeft);
    g.drawText(juce::String(s.numerator) + "/" + juce::String(s.denominator), 602, p.footerY + 13, 40, 24, juce::Justification::centred);
    if (getWidth() >= 1200) g.drawFittedText(s.deviceAvailable ? s.deviceName : "No audio device", 652, p.footerY + 13, getWidth() - 1030, 24, juce::Justification::centredLeft, 1);
    for(int channel=0;channel<2;++channel){const auto db=channel?s.masterPeakRightDb:s.masterPeakLeftDb;
        const float height=juce::jlimit(0.0f,1.0f,(db+60.0f)/60.0f)*28.0f;
        const float x=float(p.gain.getX()-74+channel*10);g.setColour(rule);g.fillRect(x,float(p.footerY+12),6.0f,28.0f);
        g.setColour(ink);g.fillRect(x,float(p.footerY+40)-height,6.0f,height);}
}

void MainComponent::refreshSnapshot()
{
    auto& p = *impl;
    auto next = session.snapshot();
    const bool clipChanged = next.selectedClipId != p.state.selectedClipId;
    const bool tracksChanged = next.revision != p.state.revision || next.selectedTrackId != p.state.selectedTrackId || clipChanged
        || next.tracks.size() != p.state.tracks.size();
    const bool repaintChrome = tracksChanged || next.source != p.state.source || next.deviceName != p.state.deviceName
        || next.deviceAvailable != p.state.deviceAvailable || next.sampleRate != p.state.sampleRate
        || next.bufferSize != p.state.bufferSize || next.duration != p.state.duration || next.dirty != p.state.dirty
        || next.projectFile != p.state.projectFile;
    const auto* previousClip = p.pianoRoll ? p.selectedClip() : nullptr;
    const auto previousNotes = previousClip ? previousClip->notes : nullptr;
    p.state = std::move(next);
    if (tracksChanged) p.updateDeviceButtons();
    if (clipChanged) { p.startInputDirty = false; p.startEditId.clear(); }
    p.trackList.setVisible(false);
    p.arrangement.update(p.state);
    p.trackPanel.update(p.state);
    p.waveform.update(p.state);
    p.filename.setText(p.composeActive ? "arrangement~" : p.selectedClipName(), juce::dontSendNotification);
    p.filename.setTooltip(p.composeActive ? "Audio and MIDI clips on the project timeline." : p.state.source.getFullPathName());
    const bool playable = p.state.duration > 0.0 || p.state.metronomeEnabled;
    const bool recordingBusy = p.state.recording || p.state.recordingFinalizing;
    const bool busy = p.chooser != nullptr || p.confirming || bool(p.pendingAfterSave) || p.saveContinuationPending || recordingBusy;
    p.play.setEnabled(playable && p.state.deviceAvailable && !recordingBusy);
    p.stop.setEnabled(playable || recordingBusy);
    p.record.setEnabled(p.state.deviceAvailable && !p.state.recordingFinalizing && p.audioDialog == nullptr && p.chooser == nullptr && !p.confirming && p.pendingSaveJob.isEmpty() && !p.savePreparing && !p.saveContinuationPending);
    p.record.setToggleState(p.state.recording, juce::dontSendNotification);
    p.metronome.setToggleState(p.state.metronomeEnabled,juce::dontSendNotification);
    p.countIn.setToggleState(p.state.countInEnabled,juce::dontSendNotification);
    p.countInBars.setSelectedId(p.state.countInBars,juce::dontSendNotification);
    p.metronome.setEnabled(!recordingBusy);p.metronomeOptions.setEnabled(!recordingBusy);p.countIn.setEnabled(!recordingBusy);p.countInBars.setEnabled(!recordingBusy);
    const auto ram=p.state.memoryWorkingSetBytes>0?juce::String(double(p.state.memoryWorkingSetBytes)/(1024*1024),0)+" MiB":"--";
    p.resources.setText("RAM "+ram+"   DSP "+juce::String(p.state.cpuUsage*100,1)+"%   xruns "+juce::String(p.state.xruns)
        +"   "+rateText(p.state.sampleRate)+" / "+juce::String(p.state.bufferSize),juce::dontSendNotification);
    p.resources.setTooltip("RAM: process working set including in-process plugins; private commit: "+juce::String(double(p.state.memoryPrivateBytes)/(1024*1024),1)
        +" MiB. DSP: audio callback load, not system CPU. Xruns: device/host underrun count. RAM sampled once per second.");
    p.meterReset.setToggleState(p.state.masterOverloaded,juce::dontSendNotification);
    p.meterReset.setButtonText(p.state.masterOverloaded?"CLIP":"OUT");
    p.meterReset.setTooltip("Master L "+juce::String(p.state.masterPeakLeftDb,1)+" dB / R "+juce::String(p.state.masterPeakRightDb,1)+" dB. Click to reset peak overload indicators.");
    if(p.gridMode.getSelectedId()==2)p.arrangement.setGridBeats(p.state.numerator*4.0/p.state.denominator);
    p.settings.setEnabled(!recordingBusy);
    if (p.pianoRoll) p.pianoRoll->setEnabled(!busy);
    p.loop.setEnabled(playable && !busy);
    p.play.setToggleState(p.state.playing, juce::dontSendNotification);
    p.loop.setToggleState(p.state.looping, juce::dontSendNotification);
    p.gain.setEnabled(!busy);
    if (!p.gain.isMouseButtonDown()) p.gain.setValue(p.state.gainDb, juce::dontSendNotification);
    const auto* selected = p.selectedTrack();
    p.trackGain.setEnabled(selected != nullptr && !busy);
    p.trackPan.setEnabled(selected != nullptr && !busy);
    p.clipProperties.setEnabled(p.selectedClip() != nullptr && !busy);
    if (selected && !p.trackPan.isMouseButtonDown()) p.trackPan.setValue(selected->pan, juce::dontSendNotification);
    p.tempo.setButtonText(juce::String(p.state.bpm, std::fmod(p.state.bpm, 1.0) == 0 ? 0 : 1) + " BPM");
    if (p.pianoRoll) {
        p.pianoRoll->setTimeSignature(p.state.numerator, p.state.denominator);
        const auto* selectedMidi = p.selectedClip();
        if (selectedMidi && selectedMidi->kind == "midi") {
            if (tracksChanged && !(previousNotes == selectedMidi->notes
                && p.pianoRoll->updateUnchangedClip(p.state.projectId, selectedMidi->id, p.selectedClipName(),
                    p.state.revision, selectedMidi->startBeats, selectedMidi->lengthBeats, p.state.bpm))) {
                std::vector<PianoRoll::Note> notes;
                if (selectedMidi->notes) { notes.reserve(selectedMidi->notes->size()); for (const auto& n : *selectedMidi->notes) notes.push_back({ n.id, n.pitch, n.startBeats, n.lengthBeats, n.velocity, n.channel }); }
                p.pianoRoll->setClip(p.state.projectId, selectedMidi->id, p.selectedClipName(), p.state.revision, selectedMidi->startBeats, selectedMidi->lengthBeats, p.state.bpm, notes);
            }
            p.pianoRoll->setPlayhead(p.state.position, p.state.playing);
        } else p.pianoRoll->setClip(p.state.projectId, {}, {}, p.state.revision, 0, 4, p.state.bpm, {});
    }
    p.mute.setEnabled(selected != nullptr && !busy);
    p.solo.setEnabled(selected != nullptr && !busy);
    p.remove.setEnabled(selected != nullptr && !busy);
    p.trackList.setEnabled(!busy);
    p.arrangement.setEnabled(!busy);
    p.waveform.setEnabled(!busy);
    const auto* clip = p.selectedClip();
    p.clipStart.setEnabled(clip != nullptr && !busy);
    p.setClipStart.setEnabled(clip != nullptr && !busy && p.startInputDirty);
    if (!p.startInputDirty && (!p.clipStart.hasKeyboardFocus(true) || clipChanged)) {
        p.updatingStartInput = true;
        p.clipStart.setText(clip != nullptr ? positionText(clip->timelineStart,p.state,p.rulerMode.getSelectedId()!=2) : "", false);
        p.updatingStartInput = false;
        p.startEditId = p.state.selectedClipId;
        p.startEditRevision = p.state.revision;
    }
    if (!p.trackGain.isMouseButtonDown()) p.trackGain.setValue(selected != nullptr ? selected->gainDb : 0.0, juce::dontSendNotification);
    p.mute.setToggleState(selected != nullptr && selected->muted, juce::dontSendNotification);
    p.solo.setToggleState(selected != nullptr && selected->solo, juce::dontSendNotification);
    p.mute.setButtonText(selected != nullptr && selected->muted ? "mute on" : "mute");
    p.solo.setButtonText(selected != nullptr && selected->solo ? "solo on" : "solo");
    for (auto* button : { &p.newButton, &p.openButton, &p.importButton,
                         &p.editMenu, &p.exportMenu, &p.plugins, &p.tempo })
        button->setEnabled(!busy);
    const bool saving = p.savePreparing || p.pendingSaveJob.isNotEmpty();
    p.saveButton.setEnabled(!busy && !saving);
    p.saveAsButton.setEnabled(!busy && !saving);
    p.saveButton.setButtonText(saving ? "saving..." : "save");
    p.saveStatus.setText(saving ? "Saving..." : p.saveError.isNotEmpty() ? "Save failed - retry"
        : p.state.dirty ? "Unsaved changes" : p.state.projectFile != juce::File() ? "Saved" : "New project", juce::dontSendNotification);
    p.saveStatus.setTooltip(p.saveError.isNotEmpty() ? p.saveError : p.saveFeedback);
    p.undoButton.setEnabled(!busy && p.state.canUndo);
    p.redoButton.setEnabled(!busy && p.state.canRedo);
    p.undoButton.setTooltip(p.state.canUndo ? "Undo " + p.state.undoDescription + " (Ctrl+Z)" : "Nothing to undo");
    p.redoButton.setTooltip(p.state.canRedo ? "Redo " + p.state.redoDescription + " (Ctrl+Y)" : "Nothing to redo");
    juce::String taskText;
    for (auto it = p.state.jobs.rbegin(); it != p.state.jobs.rend(); ++it) if (it->status == "running" || it->status == "queued") {
        taskText = it->kind == "save_project" ? "Saving project" : it->kind;
        if (it->kind == "save_project" && it->phase == "capturing_plugins") taskText += " / " + it->detail;
        if (it->progress >= 0) taskText += " / " + juce::String(it->progress * 100, 0) + "%";
        break;
    }
    p.cancelJob.setVisible(taskText.isNotEmpty());
    const auto statusText = p.state.countingIn ? "Count-in: "+juce::String(int(std::ceil(p.state.countInBeatsRemaining)))+" beats remaining - Stop cancels"
        : p.state.recordingFinalizing ? juce::String("Finishing recording...") : p.state.recording ? juce::String("Recording - Stop finishes the take")
        : taskText.isNotEmpty() ? taskText : p.saveError.isNotEmpty() ? p.saveError : p.error.isNotEmpty() ? p.error
        : p.state.recordingError.isNotEmpty() ? p.state.recordingError : p.state.status;
    p.status.setText(statusText, juce::dontSendNotification);
    p.status.setTooltip(statusText);
    p.status.setColour(juce::Label::textColourId, p.error.isEmpty() ? secondary : ink);
    repaint(380, p.footerY + 8, 114, 40);
    repaint(p.gain.getX()-78,p.footerY+8,25,36);
    if (repaintChrome) repaint();
    if (p.pendingSaveJob.isNotEmpty()) {
        for (const auto& job : p.state.jobs) if (job.id == p.pendingSaveJob && job.status != "queued" && job.status != "running") {
            auto callback = std::move(p.pendingAfterSave); p.pendingSaveJob.clear();
            const bool repeat = std::exchange(p.saveAgain, false) && p.saveFollowupAllowed && p.state.dirty
                && p.state.projectId == p.saveProjectId && (job.status == "completed" || job.status == "conflict");
            if (repeat) {
                // A user-requested follow-up can recover a preparation conflict, but cannot schedule another automatic retry.
                p.savePreparing = true; p.saveFollowupAllowed = false; p.saveError.clear();
                juce::MessageManager::callAsync([safe = juce::Component::SafePointer<MainComponent>(this), target = p.saveTarget,
                    projectId = p.saveProjectId, callback = std::move(callback)]() mutable {
                    if (safe) safe->beginSave(target, projectId, std::move(callback), false);
                });
            } else if (job.status == "completed") {
                p.saveError.clear();
                p.saveFeedback = p.state.dirty ? "Earlier changes saved. New edits are not saved yet." : "Project saved.";
                if (!p.state.dirty) {
                    continueAfterSave(p.saveProjectId, p.state.revision, std::move(callback));
                } else if (callback) p.saveError = "New changes remain unsaved. Save again before closing.";
            } else { p.saveError = job.error.isNotEmpty() ? job.error : "Save did not complete. The project remains open; retry Save."; }
            p.saveButton.setButtonText(p.savePreparing ? "saving..." : "save");
            p.saveButton.setEnabled(p.chooser == nullptr && !p.confirming && !p.savePreparing && !p.saveContinuationPending);
            p.saveAsButton.setEnabled(p.saveButton.isEnabled());
            p.saveStatus.setText(p.savePreparing ? "Saving..." : p.saveError.isNotEmpty() ? "Save failed - retry" : p.state.dirty ? "Unsaved changes" : "Saved", juce::dontSendNotification);
            p.status.setText(p.savePreparing ? "Saving the requested changes..." : p.saveError.isNotEmpty() ? p.saveError : p.saveFeedback, juce::dontSendNotification);
            break;
        }
    }
}
void MainComponent::timerCallback() { refreshSnapshot(); }
void MainComponent::resetClipStartInput()
{
    auto& p = *impl;
    p.startInputDirty = false;
    p.startEditId = p.state.selectedClipId;
    p.startEditRevision = p.state.revision;
    p.updatingStartInput = true;
    const auto* clip = p.selectedClip();
    p.clipStart.setText(clip != nullptr ? positionText(clip->timelineStart,p.state,p.rulerMode.getSelectedId()!=2) : "", false);
    p.updatingStartInput = false;
    p.setClipStart.setEnabled(false);
}
bool MainComponent::commitClipStart()
{
    auto& p = *impl;
    if (!p.startInputDirty || p.chooser != nullptr || p.confirming) return false;
    const auto text = p.clipStart.getText().trim();
    const auto value = positionValue(text,p.state,p.rulerMode.getSelectedId()!=2);
    if (!value || *value>172800.0) {
        showResult(juce::Result::fail(p.rulerMode.getSelectedId()==2?"Enter seconds from 0 to 172800.":"Enter bar:beat:tick, e.g. 2:1:000. Ticks range 000-959; position must be within 48 hours."));
        return false;
    }
    if (p.startEditId != p.state.selectedClipId || p.startEditId.isEmpty()) {
        resetClipStartInput();
        showResult(juce::Result::fail("The selected clip changed. Enter its start time again."));
        return false;
    }
    if(const auto* clip=p.selectedClip();clip&&session.snapshot().revision==p.startEditRevision){
        const bool musical=p.rulerMode.getSelectedId()!=2;
        if(musical?text==positionText(clip->timelineStart,p.state,true)
            :*value==juce::String(clip->timelineStart,6).getDoubleValue()){
            resetClipStartInput();return true;
        }
    }
    session.endEditGesture();
    const auto result = session.moveClip(p.startEditId, *value, p.startEditRevision);
    if (result.wasOk() || session.snapshot().revision != p.startEditRevision) {
        p.startInputDirty = false;
        refreshSnapshot();
        resetClipStartInput();
    }
    showResult(result);
    return result.wasOk();
}
bool MainComponent::arrangementWaveformsReady() const { return impl->arrangement.waveformsReady(); }
juce::Result MainComponent::runArrangementSmokeTest(const juce::File& outputDirectory)
{
    auto& p = *impl;
    const juce::Point<int> originalSize { getWidth(), getHeight() };
    setSize(1280, 800);
    refreshSnapshot();
    const auto before = session.snapshot();
    auto report = std::make_unique<juce::DynamicObject>();
    report->setProperty("schema", 1);
    report->setProperty("status", "failed");
    report->setProperty("default_page", p.composeActive ? "compose" : "separate");
    auto result = juce::Result::ok();
    const auto capture = [this, &outputDirectory](const char* name) {
        const auto image = createComponentSnapshot(getLocalBounds(), true);
        juce::MemoryOutputStream png;
        return juce::PNGImageFormat().writeImageToStream(image, png)
            && outputDirectory.getChildFile(name).replaceWithData(png.getData(), png.getDataSize());
    };
    if (!p.composeActive || !p.arrangement.isVisible() || p.waveform.isVisible())
        result = juce::Result::fail("Compose is not the default visible arrangement page.");
    if (result.wasOk()) {
        p.separate.onClick();
        if (!p.arrangement.isVisible() || !p.waveform.isVisible() || p.dock != Impl::Dock::source)
            result = juce::Result::fail("Source details must open below the visible arrangement.");
        if (result.wasOk() && !capture("ui-separate-1280x800.png"))
            result = juce::Result::fail("Could not capture the Separate detail view.");
        p.compose.onClick();
        if (!p.arrangement.isVisible() || p.waveform.isVisible() || !p.composeActive || p.transcribe.isVisible() || p.trackList.isVisible())
            result = juce::Result::fail("Page navigation or unavailable transcription state is wrong.");
        report->setProperty("page_switch", result.wasOk());
    }
    if (result.wasOk()) {
        p.fit.onClick();
        p.zoomIn.onClick();
        if (p.arrangement.zoomFactor() != 2.0) result = juce::Result::fail("Zoom in button is not connected.");
        p.zoomOut.onClick();
        if (p.arrangement.zoomFactor() != 1.0) result = juce::Result::fail("Zoom out button is not connected.");
        p.zoomIn.onClick();
        p.fit.onClick();
        if (p.arrangement.zoomFactor() != 1.0) result = juce::Result::fail("Fit button is not connected.");
        for (int n = 0; n < 5; ++n) p.zoomIn.onClick();
        if (result.wasOk() && !capture("ui-zoom-1280x800.png"))
            result = juce::Result::fail("Could not capture the 32x arrangement view.");
        p.fit.onClick();
        report->setProperty("zoom_buttons", result.wasOk());
    }
    if (result.wasOk()) {
        p.arrangement.setGrid(0.0, false);
        result = p.arrangement.runSmokeTest(*report);
        p.gridMode.onChange();
        p.snap.onClick();p.rulerMode.onChange();
    }
    if (result.wasOk()) {
        // Exercise the same editor/button callbacks used by keyboard and pointer
        // input. The hidden smoke window never pretends to have OS focus.
        p.rulerMode.setSelectedId(2,juce::dontSendNotification);p.rulerMode.onChange();
        refreshSnapshot();
        const auto selected = p.selectedClip() != nullptr ? *p.selectedClip() : EngineSession::ClipSnapshot {};
        const auto editBefore = session.snapshot();
        p.clipStart.onEditBegin();
        p.clipStart.setText("8", false);
        p.clipStart.onTextChange();
        refreshSnapshot();
        if (p.clipStart.getText() != "8" || session.snapshot().revision != editBefore.revision)
            result = juce::Result::fail("Periodic refresh overwrote the clip start draft or applied it early.");
        if (p.clipStart.onFocusLost) p.clipStart.onFocusLost();
        if (session.snapshot().revision != editBefore.revision)
            result = juce::Result::fail("Leaving the start field applied an unconfirmed move.");
        if (result.wasOk()) {
            p.clipStart.onEscapeKey();
            if (p.startInputDirty || std::abs(p.clipStart.getText().getDoubleValue() - selected.timelineStart) > 0.000001)
                result = juce::Result::fail("Escape did not restore the clip start draft.");
            report->setProperty("clip_start_draft_refresh_blur_escape", result.wasOk());
        }
        if (result.wasOk()) {
            p.clipStart.onEditBegin();
            p.clipStart.setText("8", false);
            p.clipStart.onTextChange();
            p.clipStart.onReturnKey();
            const auto* updatedClip = p.selectedClip();
            if (updatedClip == nullptr || updatedClip->id != selected.id || std::abs(updatedClip->timelineStart - 8.0) > 0.0000001
                || session.snapshot().revision != editBefore.revision + 1)
                result = juce::Result::fail("The start field did not move the selected clip to exactly eight seconds once.");
            p.arrangement.fitToProject();
            if (result.wasOk() && !capture("ui-clip-start8-1280x800.png"))
                result = juce::Result::fail("Could not capture the real eight-second clip move.");
            if (result.wasOk()) {
                setSize(1000, 650);
                if (!capture("ui-clip-start8-1000x650.png")) result = juce::Result::fail("Could not capture the minimum-size clip inspector.");
                setSize(1280, 800);
            }
            if (auto undo = session.undo(session.snapshot().revision); undo.failed()) result = undo;
            refreshSnapshot();
            resetClipStartInput();
            if (result.wasOk() && (p.selectedClip() == nullptr || p.selectedClip()->timelineStart != selected.timelineStart
                || session.snapshot().dirty != editBefore.dirty)) result = juce::Result::fail("One Undo did not restore the exact start-field move.");
            report->setProperty("clip_start_exact_eight_seconds", result.wasOk());
            report->setProperty("clip_start_single_undo", result.wasOk());
        }
    }
    if (result.wasOk()) {
        juce::StringArray draggedFiles;
        draggedFiles.add(before.tracks.front().source.getFullPathName());
        if (!isInterestedInFileDrag(draggedFiles)) result = juce::Result::fail("The audio drag target rejected a supported project source.");
        fileDragEnter(draggedFiles, p.arrangement.getX() + 20, p.arrangement.getY() + 20);
        if (!p.arrangement.isDropActive()) result = juce::Result::fail("Compose does not show audio drag feedback.");
        if (result.wasOk() && !capture("ui-drag-1280x800.png")) result = juce::Result::fail("Could not capture the audio drag target state.");
        fileDragExit(draggedFiles);
        if (p.arrangement.isDropActive() || p.waveform.dropActive) result = juce::Result::fail("Audio drag feedback did not clear after leaving.");
        report->setProperty("drag_enter_exit_feedback", result.wasOk());
    }
    refreshSnapshot();
    const auto after = session.snapshot();
    if (result.wasOk() && before.dirty != after.dirty)
        result = juce::Result::fail("The clip edit tests did not restore the project's dirty state.");
    if (result.wasOk()) {
        for (std::size_t row = 0; row < before.tracks.size(); ++row) {
            if (row >= after.tracks.size() || before.tracks[row].clips.size() != after.tracks[row].clips.size()) { result = juce::Result::fail("Clip test cleanup changed the track contents."); break; }
            for (std::size_t c = 0; c < before.tracks[row].clips.size(); ++c) {
                const auto& a = before.tracks[row].clips[c];
                const auto& b = after.tracks[row].clips[c];
                if (a.id != b.id || a.timelineStart != b.timelineStart || a.sourceOffset != b.sourceOffset || a.duration != b.duration) {
                    result = juce::Result::fail("Clip test cleanup did not restore the musical layout."); break;
                }
            }
        }
        report->setProperty("clip_tests_restore_content_and_dirty", result.wasOk());
    }
    session.selectClip(before.selectedClipId);
    session.seek(before.position);
    p.arrangement.fitToProject();
    refreshSnapshot();
    const auto* selected = p.selectedTrack();
    if (result.wasOk() && (selected == nullptr || selected->id != after.selectedTrackId
        || std::abs(p.trackGain.getValue() - selected->gainDb) > 0.11))
        result = juce::Result::fail("The track inspector does not follow arrangement selection.");
    report->setProperty("inspector_matches_selection", result.wasOk());
    if (result.wasOk()) {
        PianoRoll editor; editor.setLookAndFeel(&p.look);
        result = editor.runInteractionSmokeTest(*report);
        const auto captureComponent = [&outputDirectory](juce::Component& component, const char* name) {
            juce::MemoryOutputStream png;
            return juce::PNGImageFormat().writeImageToStream(component.createComponentSnapshot(component.getLocalBounds(), true), png)
                && outputDirectory.getChildFile(name).replaceWithData(png.getData(), png.getDataSize());
        };
        if (result.wasOk() && !captureComponent(editor, "ui-piano-fixture-1000x580.png")) result = juce::Result::fail("Could not capture the MIDI interaction fixture.");
        editor.setSize(820, 440);
        if (result.wasOk() && !captureComponent(editor, "ui-piano-fixture-820x440.png")) result = juce::Result::fail("Could not capture the narrow MIDI interaction fixture.");
        PluginPanel browser(session, {}); browser.setLookAndFeel(&p.look);
        if (result.wasOk() && !captureComponent(browser, "ui-plugins-900x580.png")) result = juce::Result::fail("Could not capture the installed-plugin browser.");
        browser.setSize(780, 420);
        if (result.wasOk() && !captureComponent(browser, "ui-plugins-780x420.png")) result = juce::Result::fail("Could not capture the narrow plugin browser.");
        ValueForm values({ { "bpm", "tempo / BPM", "120" }, { "gain", "gain / dB", "-6.0" }, { "name", "track name", "Visible text", false } }, {});
        values.setLookAndFeel(&p.look);
        if (result.wasOk()) {
            // Check rendered glyph pixels, excluding borders and a possible
            // caret, so a white-on-white initial text run cannot pass merely
            // because getText() still returns the correct number.
            for (auto* child : values.getChildren()) if (auto* input = dynamic_cast<juce::TextEditor*>(child)) input->setCaretVisible(false);
            const auto rendered = values.createComponentSnapshot(values.getLocalBounds(), true);
            int visibleInputs = 0;
            for (auto* child : values.getChildren()) if (auto* input = dynamic_cast<juce::TextEditor*>(child)) {
                const auto content = input->getBounds().reduced(6);
                int glyphPixels = 0;
                for (int y = content.getY(); y < content.getBottom(); ++y)
                    for (int x = content.getX(); x < content.getRight(); ++x)
                        if (rendered.getPixelAt(x, y).getBrightness() < 0.5f) ++glyphPixels;
                if (input->getText().isNotEmpty() && glyphPixels >= 4) ++visibleInputs;
            }
            if (visibleInputs != 3) result = juce::Result::fail("Initial parameter values do not produce readable text on the form background.");
            report->setProperty("parameter_initial_values_render_visible", result.wasOk());
        }
        if (result.wasOk() && !captureComponent(values, "ui-parameters-470x226.png")) result = juce::Result::fail("Could not capture initial numeric and text parameters.");
        values.setLookAndFeel(nullptr);
        editor.setLookAndFeel(nullptr); browser.setLookAndFeel(nullptr);
    }
    if (result.wasOk()) result = AudioSettingsPanel::runInteractionSmokeTest(*report);
    if (result.wasOk()) {
        // Exercise the real asynchronous save and continuation in an isolated
        // session, so this check never saves or changes the user's open project.
        EngineSession saveSession(false);
        result = saveSession.execute("create_track", arguments({ { "kind", "instrument" }, { "name", "Save continuation fixture" } }), saveSession.snapshot().revision);
        MainComponent saveView(saveSession);
        const auto target = outputDirectory.getChildFile("ui-save-" + juce::Uuid().toString() + ".emproj");
        int calls = 0; bool dirtyOnCallback = false;
        if (result.wasOk()) result = saveSession.execute("save_project", arguments({ { "path", target.getFullPathName() } }), saveSession.snapshot().revision);
        if (result.wasOk()) saveView.finishOrAwaitSave([&] { ++calls; dirtyOnCallback = saveSession.snapshot().dirty; });
        const auto deadline = juce::Time::getMillisecondCounterHiRes() + 10000.0;
        while (result.wasOk() && calls == 0 && juce::Time::getMillisecondCounterHiRes() < deadline) {
            const auto observed = saveSession.snapshot();
            for (const auto& job : observed.jobs) if (job.kind == "save_project") {
                if (job.status == "completed" && observed.dirty) result = juce::Result::fail("Save was reported complete before its project metadata was committed.");
                if (job.status == "failed" || job.status == "cancelled" || job.status == "conflict") result = juce::Result::fail("Save continuation fixture failed: " + job.error);
            }
            juce::MessageManager::getInstance()->runDispatchLoopUntil(10);
        }
        if (result.wasOk() && (calls != 1 || dirtyOnCallback || saveSession.snapshot().dirty || saveSession.snapshot().projectFile != target))
            result = juce::Result::fail("The save continuation did not run exactly once after a committed, clean save.");
        report->setProperty("async_save_continuation_after_commit", result.wasOk());
        if (result.wasOk()) {
            // Force the worker to reach a failed terminal state before the UI observes its job.
            // The current project is clean, so dirty must never be used as a success proxy.
            const auto blocker = outputDirectory.getChildFile("ui-save-blocker-" + juce::Uuid().toString());
            if (!blocker.replaceWithText("This regular file cannot be used as a project directory.")) result = juce::Result::fail("Could not create the fast-failure save fixture.");
            const auto failedTarget = blocker.getChildFile("SaveAs.emproj");
            if (result.wasOk()) result = saveSession.execute("save_project", arguments({ { "path", failedTarget.getFullPathName() } }), saveSession.snapshot().revision);
            juce::String failedJob;
            const auto accepted = saveSession.snapshot();
            for (auto it = accepted.jobs.rbegin(); it != accepted.jobs.rend(); ++it) if (it->kind == "save_project") { failedJob = it->id; break; }
            bool sawFailure = false;
            const auto failureDeadline = juce::Time::getMillisecondCounterHiRes() + 5000.0;
            while (result.wasOk() && !sawFailure && juce::Time::getMillisecondCounterHiRes() < failureDeadline) {
                for (const auto& job : saveSession.snapshot().jobs) if (job.id == failedJob) sawFailure = job.status == "failed";
                if (!sawFailure) juce::MessageManager::getInstance()->runDispatchLoopUntil(2);
            }
            if (result.wasOk() && !sawFailure) result = juce::Result::fail("SaveAs failure did not reach a terminal state before observation.");
            int failedContinuationCalls = 0;
            if (result.wasOk()) saveView.finishOrAwaitSave([&] { ++failedContinuationCalls; });
            juce::MessageManager::getInstance()->runDispatchLoopUntil(10);
            if (result.wasOk() && (failedContinuationCalls != 0 || saveSession.snapshot().dirty || saveSession.snapshot().projectFile != target
                || saveView.impl->saveError.isEmpty() || saveView.impl->saveStatus.getText() != "Save failed - retry"))
                result = juce::Result::fail("An already-failed SaveAs on a clean project was treated as successful or continued closing.");
            report->setProperty("fast_failed_clean_saveas_never_continues", result.wasOk());
        }
        if (result.wasOk()) {
            const auto jobsBefore = saveSession.snapshot().jobs.size();
            const auto trackId = saveSession.snapshot().tracks.front().id;
            result = saveSession.setTrackGain(trackId, -3.0f, saveSession.snapshot().revision);
            saveView.refreshSnapshot();
            saveView.impl->saveButton.onClick();
            if (!saveView.impl->savePreparing || saveView.impl->saveButton.isEnabled() || saveView.impl->saveStatus.getText() != "Saving...")
                result = juce::Result::fail("Ordinary Save did not immediately show and lock its in-progress state.");
            for (int i = 0; i < 12; ++i) saveView.keyPressed(juce::KeyPress('S', juce::ModifierKeys::ctrlModifier, 0));
            const auto normalDeadline = juce::Time::getMillisecondCounterHiRes() + 10000.0;
            while (result.wasOk() && (saveView.impl->savePreparing || saveView.impl->pendingSaveJob.isNotEmpty()) && juce::Time::getMillisecondCounterHiRes() < normalDeadline) {
                juce::MessageManager::getInstance()->runDispatchLoopUntil(10); saveView.refreshSnapshot();
            }
            const auto saved = saveSession.snapshot();
            juce::Array<juce::var> savedJobs;
            for (const auto& job : saved.jobs) savedJobs.add(arguments({
                { "id", job.id }, { "kind", job.kind }, { "status", job.status },
                { "phase", job.phase }, { "detail", job.detail }, { "error", job.error }, { "progress", job.progress }
            }));
            report->setProperty("ordinary_save_evidence", arguments({
                { "dirty", saved.dirty }, { "revision", juce::int64(saved.revision) },
                { "jobs_before", juce::int64(jobsBefore) }, { "jobs_after", juce::int64(saved.jobs.size()) },
                { "save_button_enabled", saveView.impl->saveButton.isEnabled() },
                { "save_status", saveView.impl->saveStatus.getText() }, { "save_error", saveView.impl->saveError },
                { "footer_status", saveView.impl->status.getText() }, { "engine_status", saved.status },
                { "preparing", saveView.impl->savePreparing }, { "pending_job", saveView.impl->pendingSaveJob },
                { "continuation_pending", saveView.impl->saveContinuationPending },
                { "has_continuation", bool(saveView.impl->pendingAfterSave) }, { "save_again", saveView.impl->saveAgain },
                { "project_file", saved.projectFile.getFullPathName() }, { "jobs", savedJobs }
            }));
            if (result.wasOk() && (saved.dirty || saved.jobs.size() != jobsBefore + 1 || !saveView.impl->saveError.isEmpty()
                || !saveView.impl->saveButton.isEnabled() || saveView.impl->saveStatus.getText() != "Saved"))
                result = juce::Result::fail("Repeated Ctrl+S was not coalesced to one ordinary save with visible success and cleared save error.");
            report->setProperty("ordinary_save_feedback_and_repeated_shortcut_coalescing", result.wasOk());
        }
        if (result.wasOk()) {
            const auto saved = saveSession.snapshot(); int lateContinuationCalls = 0;
            saveView.continueAfterSave(saved.projectId, saved.revision, [&] { ++lateContinuationCalls; });
            result = saveSession.setTrackGain(saved.tracks.front().id, -2.0f, saved.revision);
            juce::MessageManager::getInstance()->runDispatchLoopUntil(10);
            if (result.wasOk() && (lateContinuationCalls != 0 || !saveSession.snapshot().dirty || saveView.impl->saveContinuationPending
                || !saveView.impl->error.contains("Changes arrived after saving")))
                result = juce::Result::fail("A save continuation discarded an edit received after it was queued.");
            report->setProperty("save_continuation_rechecks_late_edits", result.wasOk());
            if (result.wasOk()) result = saveSession.undo(saveSession.snapshot().revision);
            saveView.showResult(result);
        }
        if (result.wasOk()) {
            const auto beforeRepeat = saveSession.snapshot(); const auto jobsBefore = beforeRepeat.jobs.size();
            result = saveSession.setTrackGain(beforeRepeat.tracks.front().id, -4.0f, beforeRepeat.revision);
            saveView.refreshSnapshot(); saveView.saveProject(false);
            auto queuedEdit = std::make_shared<juce::Result>(juce::Result::ok());
            juce::MessageManager::callAsync([safe = juce::Component::SafePointer<MainComponent>(&saveView), queuedEdit, trackId = beforeRepeat.tracks.front().id] {
                if (!safe) return;
                *queuedEdit = safe->session.setTrackGain(trackId, -5.0f, safe->session.snapshot().revision);
                safe->keyPressed(juce::KeyPress('S', juce::ModifierKeys::ctrlModifier, 0));
            });
            bool secondSaveEdited = false;
            const auto repeatDeadline = juce::Time::getMillisecondCounterHiRes() + 10000.0;
            while (result.wasOk() && (saveView.impl->savePreparing || saveView.impl->pendingSaveJob.isNotEmpty()) && juce::Time::getMillisecondCounterHiRes() < repeatDeadline) {
                juce::MessageManager::getInstance()->runDispatchLoopUntil(1);
                const auto current = saveSession.snapshot();
                if (!secondSaveEdited && !saveView.impl->saveFollowupAllowed && current.jobs.size() == jobsBefore + 2
                    && saveView.impl->pendingSaveJob.isNotEmpty() && !saveView.impl->savePreparing) {
                    result = saveSession.setTrackGain(beforeRepeat.tracks.front().id, -6.0f, current.revision);
                    for (int i = 0; i < 5; ++i) saveView.keyPressed(juce::KeyPress('S', juce::ModifierKeys::ctrlModifier, 0));
                    secondSaveEdited = true;
                }
                saveView.refreshSnapshot();
            }
            if (result.wasOk() && (queuedEdit->failed() || !secondSaveEdited || !saveSession.snapshot().dirty
                || saveSession.snapshot().jobs.size() != jobsBefore + 2 || saveView.impl->savePreparing || saveView.impl->pendingSaveJob.isNotEmpty()))
                result = juce::Result::fail("A repeated save did not capture new edits exactly once, or automatically retried without a bound.");
            report->setProperty("repeated_save_captures_new_edits_once_without_loop", result.wasOk());
        }
        if (result.wasOk()) {
            const auto midiTrack = saveSession.snapshot().tracks.front().id;
            result = saveSession.execute("create_track", arguments({ { "kind", "audio" }, { "name", "Second visible track" } }), saveSession.snapshot().revision);
            saveSession.selectTrack(midiTrack);
            if (result.wasOk()) result = saveSession.execute("create_midi_clip", arguments({ { "track_id", midiTrack }, { "start_beats", 0.0 }, { "length_beats", 8.0 } }), saveSession.snapshot().revision);
            saveView.refreshSnapshot(); saveView.setSize(1000, 650); saveView.showPianoRoll();
            if (result.wasOk() && (!saveView.impl->arrangement.isVisible() || !saveView.impl->pianoRoll || !saveView.impl->pianoRoll->isVisible()
                || saveView.impl->arrangement.getHeight() < 198 || saveView.impl->pianoRoll->getBottom() > saveView.impl->footerY - 12))
                result = juce::Result::fail("The MIDI dock must fit below at least two compact track rows at the minimum window size.");
            report->setProperty("midi_dock_preserves_two_tracks_at_minimum_size", result.wasOk());
            if(result.wasOk()){
                juce::MemoryOutputStream png;
                if(!juce::PNGImageFormat().writeImageToStream(saveView.createComponentSnapshot(saveView.getLocalBounds(),true),png)
                    ||!outputDirectory.getChildFile("ui-midi-dock-1000x650.png").replaceWithData(png.getData(),png.getDataSize()))
                    result=juce::Result::fail("Could not capture minimum MIDI dock.");
            }
            saveView.impl->closeEditor.onClick();
            if (result.wasOk() && (saveView.impl->pianoRoll->isVisible() || !saveView.impl->arrangement.isVisible())) result = juce::Result::fail("Closing the dock hid the arrangement or left the editor visible.");
            saveView.impl->dock = Impl::Dock::track; saveView.resized();
            if (result.wasOk()) result = saveView.impl->trackPanel.runInteractionSmokeTest(*report);
        }
        saveView.impl->pendingAfterSave = {};
    }
    p.rulerMode.setSelectedId(1,juce::dontSendNotification);p.rulerMode.onChange();p.snap.onClick();
    report->setProperty("status", result.wasOk() ? "passed" : "failed");
    if (result.failed()) report->setProperty("error", result.getErrorMessage());
    setSize(originalSize.x, originalSize.y);
    const auto file = outputDirectory.getChildFile("arrangement-report.json");
    if (!file.replaceWithText(juce::JSON::toString(juce::var(report.release()), true)))
        return juce::Result::fail("Could not write arrangement-report.json.");
    return result;
}
void MainComponent::showResult(const juce::Result& result)
{
    impl->error = result.failed() ? result.getErrorMessage() : juce::String();
    refreshSnapshot();
}
void MainComponent::execute(const juce::String& command, const juce::var& args)
{
    showResult(session.execute(command, args, impl->state.revision));
}
void MainComponent::showAddMenu()
{
    juce::PopupMenu menu;
    menu.addItem(1, "Import audio... (WAV / MP3)"); menu.addItem(2, "Import MIDI..."); menu.addSeparator();
    menu.addItem(3, "New audio track"); menu.addItem(4, "New MIDI / instrument track");
    menu.addItem(6, "New bus / group track");
    const auto* track = impl->selectedTrack();
    menu.addItem(5, "New 4-bar MIDI clip at playhead", track && track->kind == "instrument");
    menu.showMenuAsync(juce::PopupMenu::Options().withTargetComponent(&impl->importButton), [safe = juce::Component::SafePointer<MainComponent>(this)](int id) {
        if (!safe) return;
        if (id == 1) safe->chooseSource();
        if (id == 2) safe->chooseMidi();
        if (id == 3 || id == 4) safe->execute("create_track", arguments({ { "kind", id == 4 ? "instrument" : "audio" }, { "name", id == 4 ? "MIDI track" : "Audio track" } }));
        if (id == 6) safe->execute("create_track", arguments({ { "kind", "bus" }, { "name", "Bus" } }));
        if (id == 5) {
            const auto& s = safe->impl->state;
            safe->execute("create_midi_clip", arguments({ { "track_id", s.selectedTrackId }, { "start_beats", s.position * s.bpm / 60.0 }, { "length_beats", 4.0 * s.numerator * 4.0 / s.denominator } }));
            safe->showPianoRoll();
        }
    });
}
void MainComponent::showEditMenu()
{
    const auto* clip = impl->selectedClip(); const auto* track = impl->selectedTrack();
    juce::PopupMenu menu;
    menu.addItem(1, "Split selected clip at playhead (S)", clip != nullptr);
    menu.addItem(2, "Duplicate selected clips (Ctrl+D)", clip != nullptr);
    menu.addItem(3, "Delete selected clips (Delete)", clip != nullptr);
    menu.addItem(4, "Clip properties...", clip != nullptr);
    menu.addItem(5, "Edit MIDI notes...", clip && clip->kind == "midi");
    menu.addSeparator();menu.addItem(11,"Copy selected clips (Ctrl+C)",clip!=nullptr);
    menu.addItem(12,"Cut selected clips (Ctrl+X)",clip!=nullptr);menu.addItem(13,"Paste clips at playhead (Ctrl+V)",track!=nullptr);
    menu.addItem(14,"Loop selection (Ctrl+L)",clip!=nullptr||!impl->arrangement.selectedTimeRange().isEmpty());
    menu.addSeparator(); menu.addItem(6, "Rename selected track...", track != nullptr);
    menu.addItem(7, "Move track up", track != nullptr); menu.addItem(8, "Move track down", track != nullptr);
    menu.addSeparator(); menu.addItem(9, "Tempo, meter and loop range...");
    menu.addSeparator(); menu.addItem(10, "Remove selected track", track != nullptr);
    menu.showMenuAsync(juce::PopupMenu::Options().withTargetComponent(&impl->editMenu), [safe = juce::Component::SafePointer<MainComponent>(this)](int id) {
        if (!safe) return; auto& p = *safe->impl;
        if(id>=11&&id<=13){safe->clipClipboardAction(id==11?"copy_clips":id==12?"cut_clips":"paste_clips");return;}
        if(id==14){safe->showResult(p.arrangement.loopSelection());return;}
        if (id == 1) safe->execute("split_clip", arguments({ { "clip_id", p.state.selectedClipId }, { "at_seconds", p.state.position } }));
        if (id == 2 || id == 3) safe->execute(id == 2 ? "duplicate_clips" : "delete_clips", arguments({ { "clip_ids", idsValue(p.arrangement.selectedClipIds()) } }));
        if (id == 4) safe->showClipProperties(); if (id == 5) safe->showPianoRoll();
        if (id == 6) {
            const auto* t = p.selectedTrack(); if (!t) return; const auto target = t->id; const auto expected = p.state.revision;
            auto content = std::make_unique<ValueForm>(std::vector<ValueForm::Field>{ { "name", "track name", t->name, false } }, [safe, target, expected](const juce::var& values) {
                if (!safe) return juce::Result::fail("The project window is closed.");
                const auto result = safe->session.execute("rename_track", arguments({ { "track_id", target }, { "name", values["name"] } }), expected);
                safe->showResult(result); return result;
            });
            content->setLookAndFeel(&p.look);
            juce::DialogWindow::LaunchOptions options; options.dialogTitle = "Rename track"; options.dialogBackgroundColour = paper;
            options.content.setOwned(content.release()); options.componentToCentreAround = safe; options.useNativeTitleBar = true;
            options.escapeKeyTriggersCloseButton = true; options.resizable = false; p.forms.emplace_back(options.launchAsync());
        }
        if (id == 7 || id == 8) for (std::size_t i = 0; i < p.state.tracks.size(); ++i) if (p.state.tracks[i].id == p.state.selectedTrackId) {
            safe->execute("reorder_track", arguments({ { "track_id", p.state.selectedTrackId }, { "index", juce::jlimit(0, int(p.state.tracks.size()) - 1, int(i) + (id == 7 ? -1 : 1)) } })); break;
        }
        if (id == 9) safe->showProjectTiming();
        if (id == 10) safe->execute("remove_track", arguments({ { "track_id", p.state.selectedTrackId } }));
    });
}
void MainComponent::showExportMenu()
{
    juce::PopupMenu menu;
    menu.addItem(1, "Export project WAV...", impl->state.duration > 0);
    menu.addItem(2, "Export loop range WAV...", impl->state.loopEnd > impl->state.loopStart);
    menu.addItem(3, "Export project WAV at real-time speed...", impl->state.duration > 0);
    menu.addSeparator(); menu.addItem(4, "Export project MIDI...");
    menu.addItem(5, "Export selected MIDI clips...", impl->selectedClip() && impl->selectedClip()->kind == "midi");
    menu.showMenuAsync(juce::PopupMenu::Options().withTargetComponent(&impl->exportMenu), [safe = juce::Component::SafePointer<MainComponent>(this)](int id) {
        if (safe && id > 0) safe->chooseExport(id >= 4, id == 2 || id == 5, id == 3);
    });
}
void MainComponent::showPlugins(const juce::String& trackId)
{
    const auto target = trackId.isNotEmpty() ? trackId : impl->state.selectedTrackId;
    if (impl->pluginDialog) {
        if (auto* panel = dynamic_cast<PluginPanel*>(impl->pluginDialog->getContentComponent())) panel->selectTarget(target);
        impl->pluginDialog->toFront(true); return;
    }
    auto panel = std::make_unique<PluginPanel>(session, [safe = juce::Component::SafePointer<MainComponent>(this)](const juce::Result& result) { if (safe) safe->showResult(result); });
    panel->selectTarget(target);
    panel->setLookAndFeel(&impl->look);
    impl->pluginDialog = new ToolWindow("Plugins / VST2 + VST3", panel.release(), this);
    if (impl->pluginDialog) impl->pluginDialog->setResizeLimits(780, 420, 1600, 1000);
}
void MainComponent::showPianoRoll()
{
    const auto* clip = impl->selectedClip();
    if (!clip || clip->kind != "midi") { showResult(juce::Result::fail("Select a MIDI clip, or add one on an instrument track first.")); return; }
    if (!impl->dockPiano) {
        auto piano = std::make_unique<PianoRoll>(); impl->pianoRoll = piano.get(); piano->setLookAndFeel(&impl->look);
        piano->onProjectKey = [safe = juce::Component::SafePointer<MainComponent>(this)](const juce::KeyPress& key) { return safe && safe->keyPressed(key); };
        piano->onEditError = [safe = juce::Component::SafePointer<MainComponent>(this)](const juce::String& error) {if(safe)safe->showResult(juce::Result::fail(error));};
        piano->onWriteNotes = [safe = juce::Component::SafePointer<MainComponent>(this)](const juce::String& id, const std::vector<PianoRoll::Note>& notes, std::uint64_t expected) {
            if (!safe) return;
            const auto serialise = [](const auto& n) { return arguments({ { "id", n.id }, { "pitch", n.pitch }, { "start_beats", n.startBeats }, { "length_beats", n.lengthBeats }, { "velocity", n.velocity }, { "channel", n.channel } }); };
            std::unordered_map<std::string, const EngineSession::NoteSnapshot*> remaining;
            const auto* currentClip = safe->impl->selectedClip();
            if (currentClip && currentClip->id == id && currentClip->notes) {
                remaining.reserve(currentClip->notes->size());
                for (const auto& n : *currentClip->notes) remaining.emplace(n.id.toStdString(), &n);
            }
            juce::Array<juce::var> changed, removed;
            for (const auto& n : notes) {
                const auto found = remaining.find(n.id.toStdString());
                if (found == remaining.end() || found->second->pitch != n.pitch
                    || found->second->startBeats != n.startBeats || found->second->lengthBeats != n.lengthBeats
                    || found->second->velocity != n.velocity || found->second->channel != n.channel) changed.add(serialise(n));
                if (found != remaining.end()) remaining.erase(found);
            }
            for (const auto& [key, note] : remaining) { juce::ignoreUnused(key); removed.add(note->id); }
            juce::Result result = juce::Result::ok();
            if (changed.size() <= 10000 && removed.size() <= 10000)
                result = safe->session.execute("edit_notes", arguments({ { "clip_id", id }, { "upsert", changed }, { "delete_ids", removed } }), expected);
            else {
                juce::Array<juce::var> values; values.ensureStorageAllocated(int(notes.size()));
                for (const auto& n : notes) values.add(serialise(n));
                result = safe->session.execute("write_notes", arguments({ { "clip_id", id }, { "notes", values } }), expected);
            }
            safe->showResult(result);
            if (result.failed()) {
                // Force a fresh read after rejected local preview, even though its revision did not change.
                if (safe->impl->pianoRoll) safe->impl->pianoRoll->setClip({}, {}, {}, 0, 0, 4, 120, {});
                safe->showPianoRoll();
            }
        };
        piano->onSeek = [safe = juce::Component::SafePointer<MainComponent>(this)](double seconds) { if (safe) { safe->session.seek(seconds); safe->refreshSnapshot(); } };
        piano->onTogglePlay = [safe = juce::Component::SafePointer<MainComponent>(this)] { if (safe) { safe->session.togglePlay(); safe->refreshSnapshot(); } };
        impl->dockPiano = std::move(piano);
        addAndMakeVisible(*impl->dockPiano);
    }
    impl->dock = Impl::Dock::midi; resized(); repaint();
    clip = impl->selectedClip(); if (!clip || !impl->pianoRoll) return;
    std::vector<PianoRoll::Note> notes;
    if (clip->notes) for (const auto& n : *clip->notes) notes.push_back({ n.id, n.pitch, n.startBeats, n.lengthBeats, n.velocity, n.channel });
    impl->pianoRoll->setClip(impl->state.projectId, clip->id, impl->selectedClipName(), impl->state.revision, clip->startBeats, clip->lengthBeats, impl->state.bpm, notes);
    impl->pianoRoll->setTimeSignature(impl->state.numerator, impl->state.denominator);
}
void MainComponent::clipClipboardAction(const juce::String& command)
{
    auto& p=*impl;juce::StringArray before;
    for(const auto& track:p.state.tracks)for(const auto& clip:track.clips)before.add(clip.id);
    const auto args=command=="paste_clips"?arguments({{"start_seconds",p.state.position},{"target_track_id",p.state.selectedTrackId}})
        :arguments({{"clip_ids",idsValue(p.arrangement.selectedClipIds())}});
    const auto result=session.execute(command,args,p.state.revision);showResult(result);
    if(result.wasOk()&&command=="paste_clips"){
        juce::StringArray added;for(const auto& track:p.state.tracks)for(const auto& clip:track.clips)if(!before.contains(clip.id))added.add(clip.id);
        p.arrangement.selectClipIds(added);
    }
}
void MainComponent::showMetronomeOptions()
{
    juce::PopupMenu menu;
    menu.addItem(1,"Only sound while recording",true,impl->state.metronomeRecordOnly);
    menu.addSeparator();const int volumes[]{-36,-30,-24,-18,-12,-6,0};
    for(int i=0;i<7;++i)menu.addItem(10+i,"Click volume "+juce::String(volumes[i])+" dB",true,std::abs(impl->state.metronomeGainDb-volumes[i])<0.01f);
    menu.showMenuAsync(juce::PopupMenu::Options().withTargetComponent(&impl->metronomeOptions),[safe=juce::Component::SafePointer<MainComponent>(this)](int id){
        if(!safe)return;
        if(id==1)safe->execute("set_recording_preferences",arguments({{"metronome_record_only",!safe->impl->state.metronomeRecordOnly}}));
        if(id>=10&&id<17)safe->execute("set_recording_preferences",arguments({{"metronome_gain_db",-36+(id-10)*6}}));
    });
}
void MainComponent::showProjectTiming()
{
    const auto s = impl->state; const auto expected = s.revision;
    const bool musical=impl->rulerMode.getSelectedId()!=2;
    auto content = std::make_unique<ValueForm>(std::vector<ValueForm::Field>{
        { "bpm", "tempo / BPM (20-300)", juce::String(s.bpm) },
        { "numerator", "meter numerator", juce::String(s.numerator) }, { "denominator", "meter denominator", juce::String(s.denominator) },
        { "start_seconds", musical?"loop start / bar:beat:tick":"loop start / seconds", positionText(s.loopStart,s,musical),!musical },
        { "end_seconds", musical?"loop end / bar:beat:tick":"loop end / seconds", positionText(s.loopEnd > s.loopStart ? s.loopEnd : juce::jmax(s.duration, 8.0),s,musical),!musical } },
        [safe = juce::Component::SafePointer<MainComponent>(this), expected, musical, s](const juce::var& values) {
            if (!safe) return juce::Result::fail("The project window is closed.");
            auto timing=s;timing.bpm=double(values["bpm"]);const auto n=double(values["numerator"]),d=double(values["denominator"]);
            if(!std::isfinite(n)||!std::isfinite(d)||n<1||n>32||d<1||d>32||n!=std::floor(n)||d!=std::floor(d)||timing.bpm<20||timing.bpm>300)
                return juce::Result::fail("Enter a valid tempo and integer meter before applying the loop.");
            timing.numerator=int(n);timing.denominator=int(d);
            auto start=positionValue(values["start_seconds"].toString(),timing,musical),end=positionValue(values["end_seconds"].toString(),timing,musical);
            if(!start||!end)return juce::Result::fail("Enter loop positions in the displayed units; bar:beat:tick uses ticks 000-959.");
            if(timing.bpm==s.bpm&&timing.numerator==s.numerator&&timing.denominator==s.denominator){
                const auto unchanged=[&](const juce::var& value,double old){return musical
                    ?value.toString()==positionText(old,s,true):double(value)==juce::String(old,6).getDoubleValue();};
                if(unchanged(values["start_seconds"],s.loopStart))start=s.loopStart;
                if(s.loopEnd>s.loopStart&&unchanged(values["end_seconds"],s.loopEnd))end=s.loopEnd;
            }
            juce::Array<juce::var> commands;
            commands.add(arguments({ { "command", "set_tempo" }, { "args", arguments({ { "bpm", values["bpm"] } }) } }));
            commands.add(arguments({ { "command", "set_time_signature" }, { "args", arguments({ { "numerator", values["numerator"] }, { "denominator", values["denominator"] } }) } }));
            commands.add(arguments({ { "command", "set_loop_range" }, { "args", arguments({ { "start_seconds", *start }, { "end_seconds", *end } }) } }));
            const auto result = safe->session.execute("batch", arguments({ { "commands", commands } }), expected);
            safe->showResult(result); return result;
        });
    content->setLookAndFeel(&impl->look);
    juce::DialogWindow::LaunchOptions options; options.dialogTitle = "Tempo, meter and loop"; options.dialogBackgroundColour = paper;
    options.content.setOwned(content.release()); options.componentToCentreAround = this; options.useNativeTitleBar = true;
    options.escapeKeyTriggersCloseButton = true; options.resizable = false; impl->forms.emplace_back(options.launchAsync());
}
void MainComponent::showClipProperties()
{
    const auto* clip = impl->selectedClip(); if (!clip) return;
    const auto id = clip->id; const auto expected = impl->state.revision;const auto original=*clip;
    const auto timing=impl->state;const bool musical=impl->rulerMode.getSelectedId()!=2,midi=clip->kind=="midi";
    const auto secondsPerBar=60.0/timing.bpm*timing.numerator*4.0/timing.denominator;
    std::vector<ValueForm::Field> fields{{"start_seconds",musical?"start / bar:beat:tick":"start / seconds",positionText(clip->timelineStart,timing,musical),!musical},
        {"length",musical?"length / bars (fraction allowed)":"length / seconds",juce::String(clip->duration/(musical?secondsPerBar:1.0),9)}};
    if(!midi){fields.push_back({"source_offset","source offset / seconds",juce::String(clip->sourceOffset,6)});
        fields.push_back({"fade_in_seconds","fade in / seconds",juce::String(clip->fadeIn,6)});fields.push_back({"fade_out_seconds","fade out / seconds",juce::String(clip->fadeOut,6)});}
    auto content = std::make_unique<ValueForm>(fields,
        [safe = juce::Component::SafePointer<MainComponent>(this), id, expected, timing, musical, midi, secondsPerBar, original](const juce::var& values) {
            if (!safe) return juce::Result::fail("The project window is closed."); juce::Array<juce::var> commands;
            auto start=positionValue(values["start_seconds"].toString(),timing,musical);
            if(!start)return juce::Result::fail("Enter a valid start in the displayed ruler units.");
            if(musical?values["start_seconds"].toString()==positionText(original.timelineStart,timing,true)
                :double(values["start_seconds"])==juce::String(original.timelineStart,6).getDoubleValue())start=original.timelineStart;
            auto duration=double(values["length"])*(musical?secondsPerBar:1.0);
            if(double(values["length"])==juce::String(original.duration/(musical?secondsPerBar:1.0),9).getDoubleValue())duration=original.duration;
            if(!std::isfinite(duration)||duration<=0)return juce::Result::fail("Clip length must be positive.");
            const auto preserve=[](double value,double old){return value==juce::String(old,6).getDoubleValue()?old:value;};
            const auto offset=midi?0.0:preserve(double(values["source_offset"]),original.sourceOffset);
            const auto fadeIn=midi?0.0:preserve(double(values["fade_in_seconds"]),original.fadeIn),fadeOut=midi?0.0:preserve(double(values["fade_out_seconds"]),original.fadeOut);
            // Relocate first, then trim at the new start: moving MIDI via its
            // properties must not shift or discard its clip-relative notes.
            if(*start!=original.timelineStart)commands.add(arguments({{"command","move_clip"},{"args",arguments({{"clip_id",id},{"start_seconds",*start}})}}));
            auto trim=arguments({{"clip_id",id},{"start_seconds",*start},{"end_seconds",*start+duration}});
            if(!midi)trim.getDynamicObject()->setProperty("source_offset",offset);
            if(duration!=original.duration||offset!=original.sourceOffset)commands.add(arguments({{"command","trim_clip"},{"args",trim}}));
            if(!midi&&(fadeIn!=original.fadeIn||fadeOut!=original.fadeOut))commands.add(arguments({ { "command", "set_clip_fades" }, { "args", arguments({ { "clip_id", id }, { "fade_in_seconds", fadeIn }, { "fade_out_seconds", fadeOut } }) } }));
            if(commands.isEmpty())return juce::Result::ok();
            const auto result = safe->session.execute("batch", arguments({ { "commands", commands } }), expected);
            safe->showResult(result); return result;
        });
    content->setLookAndFeel(&impl->look);
    juce::DialogWindow::LaunchOptions options; options.dialogTitle = midi?"MIDI clip properties":"Audio clip / non-destructive edit"; options.dialogBackgroundColour = paper;
    options.content.setOwned(content.release()); options.componentToCentreAround = this; options.useNativeTitleBar = true;
    options.escapeKeyTriggersCloseButton = true; options.resizable = false; impl->forms.emplace_back(options.launchAsync());
}
void MainComponent::chooseMidi()
{
    if (impl->chooser || impl->confirming) return;
    const auto expected = impl->state.revision;
    impl->chooser = std::make_unique<juce::FileChooser>("Import MIDI notes", juce::File::getSpecialLocation(juce::File::userMusicDirectory), "*.mid;*.midi", true);
    impl->chooser->launchAsync(juce::FileBrowserComponent::openMode | juce::FileBrowserComponent::canSelectFiles,
        [safe = juce::Component::SafePointer<MainComponent>(this), expected](const juce::FileChooser& dialog) {
            const auto file = dialog.getResult(); juce::MessageManager::callAsync([safe, file, expected] {
                if (!safe) return; safe->impl->chooser.reset();
                if (file.existsAsFile()) safe->showResult(safe->session.execute("import_midi", arguments({ { "path", file.getFullPathName() } }), expected));
            });
        });
}
void MainComponent::chooseExport(bool midi, bool selectedOnly, bool realtime)
{
    if (impl->chooser || impl->confirming) return;
    const auto s = impl->state; const auto selectedIds = impl->arrangement.selectedClipIds();
    const auto initial = juce::File::getSpecialLocation(juce::File::userMusicDirectory).getChildFile(s.projectName + (midi ? ".mid" : ".wav"));
    impl->chooser = std::make_unique<juce::FileChooser>(midi ? "Export MIDI notes" : "Export mix / WAV", initial, midi ? "*.mid" : "*.wav", true);
    impl->chooser->launchAsync(juce::FileBrowserComponent::saveMode | juce::FileBrowserComponent::canSelectFiles | juce::FileBrowserComponent::warnAboutOverwriting,
        [safe = juce::Component::SafePointer<MainComponent>(this), s, selectedIds, midi, selectedOnly, realtime](const juce::FileChooser& dialog) {
            const auto chosen = dialog.getResult(); juce::MessageManager::callAsync([safe, chosen, s, selectedIds, midi, selectedOnly, realtime] {
                if (!safe) return; safe->impl->chooser.reset(); if (chosen == juce::File()) return;
                const auto file = chosen.withFileExtension(midi ? ".mid" : ".wav");
                if (file != chosen && file.existsAsFile()) { safe->showResult(juce::Result::fail("The export target already exists. Select its exact filename to confirm replacement.")); return; }
                if (midi) {
                    auto args = arguments({ { "path", file.getFullPathName() } }); if (selectedOnly) args.getDynamicObject()->setProperty("clip_ids", idsValue(selectedIds));
                    safe->showResult(safe->session.execute("export_midi", args, s.revision)); return;
                }
                auto content = std::make_unique<ValueForm>(std::vector<ValueForm::Field>{
                    { "start_seconds", "start / seconds", juce::String(selectedOnly ? s.loopStart : 0, 6) },
                    { "end_seconds", "end / seconds", juce::String(selectedOnly ? s.loopEnd : s.duration, 6) },
                    { "sample_rate", "sample rate / Hz", "48000" }, { "bit_depth", "PCM bit depth", "24" }, { "tail_seconds", "extra tail / seconds", "2" } },
                    [safe, file, realtime, expected = s.revision](const juce::var& values) {
                        if (!safe) return juce::Result::fail("The project window is closed."); auto args = values.clone(); args.getDynamicObject()->setProperty("path", file.getFullPathName()); args.getDynamicObject()->setProperty("realtime", realtime);
                        const auto result = safe->session.execute("export_wav", args, expected); safe->showResult(result); return result;
                    });
                content->setLookAndFeel(&safe->impl->look);
                juce::DialogWindow::LaunchOptions options; options.dialogTitle = realtime ? "WAV export / real-time speed" : "WAV export / offline"; options.dialogBackgroundColour = paper;
                options.content.setOwned(content.release()); options.componentToCentreAround = safe; options.useNativeTitleBar = true;
                options.escapeKeyTriggersCloseButton = true; options.resizable = false; safe->impl->forms.emplace_back(options.launchAsync());
            });
        });
}
void MainComponent::chooseSource()
{
    auto& p = *impl;
    if (p.chooser != nullptr || p.confirming) return;
    session.endEditGesture();
    const auto expectedRevision = session.snapshot().revision;
    const auto initial = p.state.source == juce::File() ? juce::File::getSpecialLocation(juce::File::userMusicDirectory) : p.state.source;
    p.chooser = std::make_unique<juce::FileChooser>("Add WAV or MP3 tracks", initial, "*.wav;*.mp3", true);
    refreshSnapshot();
    p.chooser->launchAsync(juce::FileBrowserComponent::openMode | juce::FileBrowserComponent::canSelectFiles
                           | juce::FileBrowserComponent::canSelectMultipleItems,
        [safe = juce::Component::SafePointer<MainComponent>(this), expectedRevision](const juce::FileChooser& chooser) {
            const auto files = chooser.getResults();
            juce::MessageManager::callAsync([safe, files, expectedRevision] {
                if (safe == nullptr) return;
                safe->impl->chooser.reset();
                if (!files.isEmpty()) safe->importSources(files, expectedRevision);
                else safe->refreshSnapshot();
            });
        });
}
void MainComponent::importSources(const juce::Array<juce::File>& files, std::uint64_t expectedRevision)
{
    juce::Array<juce::var> paths;
    for (const auto& file : files) paths.add(file.getFullPathName());
    const auto result = session.execute("import_audio", arguments({ { "paths", paths } }), expectedRevision);
    if (result.wasOk()) impl->waveform.invalidateSource();
    showResult(result);
}
void MainComponent::withUnsavedGuard(std::function<void()> proceed)
{
    const auto recordingState = session.snapshot();
    if (recordingState.recording || recordingState.recordingFinalizing) { showResult(juce::Result::fail("Stop recording and wait for the take to finish before changing projects.")); return; }
    if (impl->savePreparing) { impl->pendingAfterSave = std::move(proceed); return; }
    if (impl->chooser != nullptr || impl->confirming || impl->pendingAfterSave || impl->saveContinuationPending) {
        impl->error = "Finish or cancel the open dialog first.";
        refreshSnapshot();
        return;
    }
    session.endEditGesture();
    const auto state = session.snapshot();
    for (const auto& job : state.jobs) if (job.kind == "save_project" && (job.status == "queued" || job.status == "running")) {
        finishOrAwaitSave(std::move(proceed)); return;
    }
    if (!state.dirty) { proceed(); return; }
    impl->confirming = true;
    refreshSnapshot();
    juce::AlertWindow::showYesNoCancelBox(juce::MessageBoxIconType::QuestionIcon, "Save changes?",
        "Save changes to " + (state.projectName.isEmpty() ? juce::String("Untitled") : state.projectName) + " before continuing?",
        "Save", "Discard", "Cancel", this,
        juce::ModalCallbackFunction::create([safe = juce::Component::SafePointer<MainComponent>(this),
                                             proceed = std::move(proceed), projectId = state.projectId](int choice) mutable {
            if (safe == nullptr) return;
            safe->impl->confirming = false;
            safe->refreshSnapshot();
            if (choice == 0) return;
            const auto current = safe->session.snapshot();
            if (current.projectId != projectId || current.recording || current.recordingFinalizing) {
                safe->impl->error = "The active project or recording state changed while the dialog was open. Try again.";
                safe->refreshSnapshot();
                return;
            }
            if (choice == 1) safe->saveProject(false, std::move(proceed));
            else if (choice == 2) proceed();
        }));
}
void MainComponent::requestClose(std::function<void()> onReady) { withUnsavedGuard(std::move(onReady)); }
void MainComponent::newProject()
{
    withUnsavedGuard([safe = juce::Component::SafePointer<MainComponent>(this)] {
        if (safe != nullptr) {
            const auto result = safe->session.newProject(safe->session.snapshot().revision);
            if (result.wasOk()) safe->impl->waveform.invalidateSource();
            safe->showResult(result);
        }
    });
}
void MainComponent::openProject()
{
    withUnsavedGuard([safe = juce::Component::SafePointer<MainComponent>(this)] {
        if (safe != nullptr) safe->chooseProject();
    });
}
void MainComponent::chooseProject()
{
    if (impl->chooser != nullptr) return;
    const auto state = session.snapshot();
    const auto initial = state.projectFile == juce::File() ? juce::File::getSpecialLocation(juce::File::userDocumentsDirectory) : state.projectFile;
    impl->chooser = std::make_unique<juce::FileChooser>("Open an E-musician project", initial, "*.emproj", true);
    refreshSnapshot();
    impl->chooser->launchAsync(juce::FileBrowserComponent::openMode | juce::FileBrowserComponent::canSelectFiles,
        [safe = juce::Component::SafePointer<MainComponent>(this), expectedRevision = state.revision](const juce::FileChooser& chooser) {
            const auto file = chooser.getResult();
            juce::MessageManager::callAsync([safe, file, expectedRevision] {
                if (safe == nullptr) return;
                safe->impl->chooser.reset();
                if (file != juce::File()) {
                    const auto result = safe->session.execute("open_project", arguments({ { "path", file.getFullPathName() } }), expectedRevision);
                    if (result.wasOk()) safe->impl->waveform.invalidateSource();
                    safe->showResult(result);
                } else safe->refreshSnapshot();
            });
        });
}
void MainComponent::saveProject(bool saveAs, std::function<void()> onSaved)
{
    if (impl->state.recording || impl->state.recordingFinalizing) { showResult(juce::Result::fail("Stop recording and wait for the take to finish before saving.")); return; }
    if (impl->savePreparing || impl->pendingSaveJob.isNotEmpty()) {
        // One follow-up captures edits made after the accepted save; repeated shortcuts never fan out jobs.
        if (!saveAs) impl->saveAgain = true;
        if (onSaved) impl->pendingAfterSave = std::move(onSaved);
        return;
    }
    if (impl->chooser != nullptr || impl->confirming || impl->saveContinuationPending) return;
    session.endEditGesture();
    const auto state = session.snapshot();
    if (!saveAs && state.projectFile != juce::File()) {
        beginSave(state.projectFile, state.projectId, std::move(onSaved));
        return;
    }
    const auto initial = state.projectFile == juce::File()
        ? juce::File::getSpecialLocation(juce::File::userDocumentsDirectory).getChildFile("Untitled.emproj") : state.projectFile;
    impl->chooser = std::make_unique<juce::FileChooser>("Save E-musician project", initial, "*.emproj", true);
    refreshSnapshot();
    impl->chooser->launchAsync(juce::FileBrowserComponent::saveMode | juce::FileBrowserComponent::canSelectFiles
                              | juce::FileBrowserComponent::warnAboutOverwriting,
        [safe = juce::Component::SafePointer<MainComponent>(this), projectId = state.projectId,
         onSaved = std::move(onSaved)](const juce::FileChooser& chooser) mutable {
            const auto selectedFile = chooser.getResult();
            juce::MessageManager::callAsync([safe, selectedFile, projectId, onSaved = std::move(onSaved)]() mutable {
                if (safe == nullptr) return;
                safe->impl->chooser.reset();
                if (selectedFile == juce::File()) { safe->refreshSnapshot(); return; }
                const auto target = selectedFile.hasFileExtension("emproj") ? selectedFile : selectedFile.withFileExtension(".emproj");
                // Native overwrite confirmation applies to the chosen name, not a changed extension.
                if (target != selectedFile && target.existsAsFile()) {
                    safe->impl->error = "That .emproj file already exists. Choose its exact name to confirm replacement.";
                    safe->refreshSnapshot();
                    return;
                }
                safe->beginSave(target, projectId, std::move(onSaved));
            });
        });
}
void MainComponent::beginSave(const juce::File& target, const juce::String& projectId, std::function<void()> onSaved, bool allowFollowup)
{
    auto& p = *impl;
    const auto current = session.snapshot();
    if (current.projectId != projectId || current.recording || current.recordingFinalizing) {
        p.savePreparing = false; p.pendingAfterSave = {};
        showResult(juce::Result::fail("The active project or recording state changed before saving. Retry Save when ready.")); return;
    }
    p.savePreparing = true; p.saveAgain = false; p.saveError.clear(); p.error.clear();
    p.saveProjectId = projectId; p.saveRevision = current.revision; p.saveTarget = target; p.saveFollowupAllowed = allowFollowup;
    p.pendingAfterSave = std::move(onSaved);
    refreshSnapshot(); // Paint feedback before asking plug-ins to capture state.
    juce::MessageManager::callAsync([safe = juce::Component::SafePointer<MainComponent>(this), target, projectId] {
        if (!safe) return;
        auto& p = *safe->impl;
        const auto current = safe->session.snapshot();
        if (current.projectId != projectId) {
            p.savePreparing = false; p.pendingAfterSave = {}; p.saveError = "The project changed before saving. Retry Save."; safe->refreshSnapshot(); return;
        }
        p.saveRevision = current.revision;
        juce::StringArray earlierJobs;
        for (const auto& job : current.jobs) earlierJobs.add(job.id);
        const auto result = safe->session.execute("save_project", arguments({ { "path", target.getFullPathName() } }), current.revision);
        p.savePreparing = false;
        if (result.failed()) { p.saveError = result.getErrorMessage(); p.pendingAfterSave = {}; safe->refreshSnapshot(); return; }
        const auto accepted = safe->session.snapshot();
        p.saveRevision = accepted.revision;
        p.pendingSaveJob.clear();
        for (auto it = accepted.jobs.rbegin(); it != accepted.jobs.rend(); ++it)
            if (it->kind == "save_project" && !earlierJobs.contains(it->id)) { p.pendingSaveJob = it->id; break; }
        if (p.pendingSaveJob.isEmpty()) {
            p.saveError = "Save was accepted without an identifiable task. The project remains open; retry Save.";
            p.pendingAfterSave = {}; safe->refreshSnapshot(); return;
        }
        safe->finishOrAwaitSave(std::move(p.pendingAfterSave));
    });
}
void MainComponent::finishOrAwaitSave(std::function<void()> next)
{
    const auto s = session.snapshot();
    for (auto it = s.jobs.rbegin(); it != s.jobs.rend(); ++it) if (it->kind == "save_project"
        && (impl->pendingSaveJob.isEmpty() || it->id == impl->pendingSaveJob)) {
        impl->pendingSaveJob = it->id; impl->pendingAfterSave = std::move(next); impl->saveProjectId = s.projectId;
        refreshSnapshot(); return; // Observe this exact job even if its worker has already failed.
    }
    impl->pendingSaveJob.clear(); impl->pendingAfterSave = {};
    impl->saveError = "The save task could not be found. The project remains open; retry Save."; refreshSnapshot();
}
void MainComponent::continueAfterSave(const juce::String& projectId, std::uint64_t savedRevision, std::function<void()> next)
{
    if (!next) return;
    impl->saveContinuationPending = true;
    juce::MessageManager::callAsync([safe = juce::Component::SafePointer<MainComponent>(this), projectId, savedRevision, next = std::move(next)] {
        if (!safe) return;
        safe->impl->saveContinuationPending = false;
        const auto current = safe->session.snapshot();
        if (current.projectId != projectId || current.revision != savedRevision || current.dirty || current.recording || current.recordingFinalizing) {
            safe->impl->error = "Changes arrived after saving. The project remains open; review them before continuing.";
            safe->refreshSnapshot(); return;
        }
        next();
    });
}
void MainComponent::showAudioSettings()
{
    if (impl->audioDialog != nullptr) { impl->audioDialog->toFront(true); return; }
    const auto current = session.snapshot();
    if (current.recording || current.recordingFinalizing) return;
    session.stop();
    auto selector = std::make_unique<AudioSettingsPanel>(
        [safe = juce::Component::SafePointer<MainComponent>(this)](bool scan) {
            if (!safe) return juce::var();
            return safe->session.executeRequest(arguments({ { "command", "get_audio_devices" }, { "args", arguments({ { "scan", scan } }) } }));
        },
        [safe = juce::Component::SafePointer<MainComponent>(this)](const juce::var& args) {
            if (!safe) return juce::Result::fail("The audio workspace was closed.");
            const auto result = safe->session.execute("configure_audio_device", args, safe->session.snapshot().revision);
            safe->showResult(result); return result;
        });
    selector->setLookAndFeel(&impl->look);
    juce::DialogWindow::LaunchOptions options;
    options.dialogTitle = "Audio and MIDI devices";
    options.dialogBackgroundColour = paper;
    options.content.setOwned(selector.release());
    options.componentToCentreAround = this;
    options.escapeKeyTriggersCloseButton = true;
    options.useNativeTitleBar = true;
    options.resizable = false;
    impl->audioDialog = options.launchAsync();
    refreshSnapshot();
}
bool MainComponent::keyPressed(const juce::KeyPress& key)
{
    if ((key.getModifiers().isCommandDown() || key.getModifiers().isCtrlDown())
        && (key.getKeyCode() == 's' || key.getKeyCode() == 'S')) {
        saveProject(key.getModifiers().isShiftDown()); return true;
    }
    if (impl->state.recording || impl->state.recordingFinalizing) {
        if (key.getKeyCode() == juce::KeyPress::spaceKey && impl->state.recording) execute("stop_recording", arguments({}));
        return true;
    }
    if (key == juce::KeyPress::escapeKey && impl->arrangement.cancelClipDrag()) return true;
    for (auto* focus = juce::Component::getCurrentlyFocusedComponent(); focus != nullptr; focus = focus->getParentComponent())
        if (dynamic_cast<juce::TextEditor*>(focus) != nullptr) return false;
    const auto modifiers = key.getModifiers();
    if (modifiers.isCommandDown() || modifiers.isCtrlDown()) {
        if (impl->chooser != nullptr || impl->confirming || impl->pendingAfterSave) return false;
        const int code = key.getKeyCode();
        if(code=='C'||code=='c'||code=='X'||code=='x'||code=='V'||code=='v'){
            if(impl->pianoRoll&&impl->pianoRoll->hasKeyboardFocus(true))return false;
            clipClipboardAction(code=='C'||code=='c'?"copy_clips":code=='X'||code=='x'?"cut_clips":"paste_clips");return true;
        }
        if(code=='L'||code=='l'){showResult(impl->arrangement.loopSelection());return true;}
        if(code=='4'){
            if(impl->pianoRoll&&impl->pianoRoll->hasKeyboardFocus(true))return false;
            impl->snap.setToggleState(!impl->snap.getToggleState(),juce::dontSendNotification);impl->snap.onClick();return true;
        }
        if (code == 's' || code == 'S') { saveProject(modifiers.isShiftDown()); return true; }
        if (code == 'o' || code == 'O') { openProject(); return true; }
        if (code == 'n' || code == 'N') { newProject(); return true; }
        if (code == 'z' || code == 'Z') {
            session.endEditGesture();
            showResult(modifiers.isShiftDown() ? session.redo(impl->state.revision) : session.undo(impl->state.revision));
            return true;
        }
        if (code == 'y' || code == 'Y') { session.endEditGesture(); showResult(session.redo(impl->state.revision)); return true; }
        if (code == 'd' || code == 'D') { execute("duplicate_clips", arguments({ { "clip_ids", idsValue(impl->arrangement.selectedClipIds()) } })); return true; }
    }
    if (impl->chooser != nullptr || impl->confirming || impl->pendingAfterSave) return false;
    if (!modifiers.isAnyModifierKeyDown() && (key.getKeyCode() == juce::KeyPress::deleteKey || key.getKeyCode() == juce::KeyPress::backspaceKey)) {
        execute("delete_clips", arguments({ { "clip_ids", idsValue(impl->arrangement.selectedClipIds()) } })); return true;
    }
    if (!modifiers.isAnyModifierKeyDown() && (key.getKeyCode() == 's' || key.getKeyCode() == 'S')) {
        execute("split_clip", arguments({ { "clip_id", impl->state.selectedClipId }, { "at_seconds", impl->state.position } })); return true;
    }
    if (key.getKeyCode() != juce::KeyPress::spaceKey || modifiers.isAnyModifierKeyDown()) return false;
    if ((impl->state.duration <= 0.0 && !impl->state.metronomeEnabled) || !impl->state.deviceAvailable) return false;
    impl->error.clear();
    session.togglePlay();
    refreshSnapshot();
    return true;
}
bool MainComponent::isInterestedInFileDrag(const juce::StringArray& files)
{
    if (files.isEmpty() || impl->chooser != nullptr || impl->confirming || impl->pendingAfterSave || impl->state.recording || impl->state.recordingFinalizing) return false;
    if (files.size() == 1 && juce::File(files[0]).hasFileExtension("mid;midi")) return true;
    for (const auto& path : files)
        if (!EngineSession::isSupportedAudioFile(juce::File(path))) return false;
    return true;
}
void MainComponent::fileDragEnter(const juce::StringArray&, int, int)
{
    impl->arrangement.setDropActive(true);
    impl->waveform.dropActive = true;
    impl->waveform.repaint();
}
void MainComponent::fileDragExit(const juce::StringArray&)
{
    impl->arrangement.setDropActive(false);
    impl->waveform.dropActive = false;
    impl->waveform.repaint();
}
void MainComponent::filesDropped(const juce::StringArray& files, int, int)
{
    impl->arrangement.setDropActive(false);
    impl->waveform.dropActive = false;
    if (impl->chooser != nullptr || impl->confirming || impl->pendingAfterSave || impl->state.recording || impl->state.recordingFinalizing) return;
    session.endEditGesture();
    if (files.size() == 1 && juce::File(files[0]).hasFileExtension("mid;midi")) {
        execute("import_midi", arguments({ { "path", juce::File(files[0]).getFullPathName() } }));
        return;
    }
    if (!isInterestedInFileDrag(files)) {
        showResult(juce::Result::fail("Drop audio files together, or import one MIDI file at a time."));
        return;
    }
    juce::Array<juce::File> audio;
    for (const auto& path : files) audio.add(juce::File(path));
    importSources(audio, session.snapshot().revision);
}
} // namespace emusician
