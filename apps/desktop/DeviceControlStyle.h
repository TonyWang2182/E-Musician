#pragma once

#include <juce_gui_basics/juce_gui_basics.h>
#include <cmath>

namespace emusician::deviceui {
// Shared device controls. The look must outlive every slider using it.
// No model or engine state is stored here; normal Slider callbacks remain the
// only edit path, so graph/knob/text input share command and Undo semantics.
class ControlLook final : public juce::LookAndFeel_V4 {
public:
    ControlLook() {
        setColour(juce::Slider::textBoxTextColourId, ink);
        setColour(juce::Slider::textBoxBackgroundColourId, paper);
        setColour(juce::Slider::textBoxHighlightColourId, juce::Colour(0xffd5d8d1));
        setColour(juce::Slider::textBoxOutlineColourId, juce::Colour(0xffa9ada5));
    }
    juce::Label* createSliderTextBox(juce::Slider& slider) override {
        auto* label = juce::LookAndFeel_V4::createSliderTextBox(slider);
        label->setFont(juce::Font(juce::FontOptions(juce::Font::getDefaultMonospacedFontName(), 12.0f, juce::Font::plain)));
        label->setJustificationType(juce::Justification::centred);
        label->setColour(juce::Label::textColourId, ink);
        label->setColour(juce::Label::textWhenEditingColourId, ink);
        label->setColour(juce::Label::backgroundWhenEditingColourId, paper);
        label->setColour(juce::TextEditor::textColourId, ink);
        label->setColour(juce::TextEditor::backgroundColourId, paper);
        return label;
    }
    void drawRotarySlider(juce::Graphics& g, int x, int y, int width, int height,
                          float position, float start, float end, juce::Slider& slider) override {
        const float size = float(juce::jmin(width, height)) - 8.0f;
        if (size < 4.0f) return;
        const auto centre = juce::Point<float>(float(x) + float(width) * .5f, float(y) + float(height) * .5f);
        const auto radius = size * .5f;
        const auto colour = slider.isEnabled() ? ink : juce::Colour(0xff969a92);
        juce::Path track, value;
        track.addCentredArc(centre.x, centre.y, radius, radius, 0, start, end, true);
        value.addCentredArc(centre.x, centre.y, radius, radius, 0, start, start + position * (end - start), true);
        g.setColour(juce::Colour(0xffc6c9c3)); g.strokePath(track, juce::PathStrokeType(2.0f));
        g.setColour(colour); g.strokePath(value, juce::PathStrokeType(2.5f));
        const float body = radius * .77f;
        g.setColour(slider.isMouseOverOrDragging() && slider.isEnabled() ? juce::Colour(0xffe4e7df) : paper);
        g.fillEllipse(centre.x - body, centre.y - body, body * 2, body * 2);
        g.setColour(colour); g.drawEllipse(centre.x - body, centre.y - body, body * 2, body * 2, 1.0f);
        const float angle = start + position * (end - start);
        const auto inner = centre + juce::Point<float>(std::sin(angle), -std::cos(angle)) * (body * .35f);
        const auto outer = centre + juce::Point<float>(std::sin(angle), -std::cos(angle)) * (body * .90f);
        g.drawLine(juce::Line<float>(inner, outer), 2.0f);
        if (slider.hasKeyboardFocus(true)) {
            g.setColour(ink);
            g.drawRect(juce::Rectangle<float>(float(x), float(y), float(width), float(height)).reduced(1), 1.0f);
        }
    }
private:
    const juce::Colour ink {0xff171817}, paper {0xfffefefd};
};

inline void configureKnob(juce::Slider& slider, ControlLook& look, double defaultValue,
                          const juce::String& suffix = {}) {
    slider.setLookAndFeel(&look);
    slider.setSliderStyle(juce::Slider::RotaryVerticalDrag);
    slider.setRotaryParameters(juce::MathConstants<float>::pi * 1.25f,
                               juce::MathConstants<float>::pi * 2.75f, true);
    slider.setTextBoxStyle(juce::Slider::TextBoxBelow, false, 86, 22);
    slider.setTextValueSuffix(suffix);
    slider.setDoubleClickReturnValue(true, defaultValue);
    slider.setMouseDragSensitivity(180);
    slider.setVelocityModeParameters(.25, 1, 0, true, juce::ModifierKeys::shiftModifier);
    slider.setScrollWheelEnabled(false);
    slider.setWantsKeyboardFocus(true);
    slider.setTooltip("Drag vertically; Shift-drag for fine adjustment. Double-click the knob to reset. Click the value to type; arrow keys adjust.");
}
} // namespace emusician::deviceui
