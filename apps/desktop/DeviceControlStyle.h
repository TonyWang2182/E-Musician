#pragma once

#include <juce_gui_basics/juce_gui_basics.h>
#include <cmath>
#include "WorkspaceLookAndFeel.h"

namespace emusician::deviceui {
inline const auto paper=design::paper,surface=design::panel,ink=design::ink,quiet=design::secondary,rule=design::rule,accent=design::accent;
inline juce::Font labelFont(float size, bool bold=false) { return design::labelFont(size,bold); }
inline juce::Font valueFont(float size) { return design::numberFont(size); }
// Shared device controls. The look must outlive every slider using it.
// No model or engine state is stored here; normal Slider callbacks remain the
// only edit path, so graph/knob/text input share command and Undo semantics.
class ControlLook final : public design::WorkspaceLookAndFeel {
public:
    ControlLook() {
        setColour(juce::Slider::textBoxTextColourId, ink);
        setColour(juce::Slider::textBoxBackgroundColourId, paper);
        setColour(juce::Slider::textBoxHighlightColourId, juce::Colour(0xffd5d8d1));
        setColour(juce::Slider::textBoxOutlineColourId, juce::Colour(0xffa9ada5));
        setColour(juce::TextButton::buttonColourId, surface); setColour(juce::TextButton::buttonOnColourId, accent);
        setColour(juce::TextButton::textColourOffId, ink); setColour(juce::TextButton::textColourOnId, ink);
        setColour(juce::ComboBox::backgroundColourId, surface); setColour(juce::ComboBox::textColourId, ink);
        setColour(juce::ComboBox::outlineColourId, rule); setColour(juce::ComboBox::arrowColourId, quiet);
    }
    juce::Font getTextButtonFont(juce::TextButton&, int height) override { return labelFont(juce::jmin(13.0f,float(height)*.5f)); }
    juce::Font getComboBoxFont(juce::ComboBox&) override { return labelFont(12); }
    void drawButtonBackground(juce::Graphics& g, juce::Button& button, const juce::Colour&, bool over, bool down) override {
        const auto area=button.getLocalBounds().toFloat().reduced(.5f);
        g.setColour(button.getToggleState()?accent:down?rule:over?surface.darker(.04f):surface);g.fillRoundedRectangle(area,3);
        g.setColour(button.hasKeyboardFocus(true)?ink:rule);g.drawRoundedRectangle(area,3,button.hasKeyboardFocus(true)?1.5f:1.0f);
    }
    void drawComboBox(juce::Graphics& g,int width,int height,bool,int,int,int,int,juce::ComboBox& box) override {
        const auto area=juce::Rectangle<float>(.5f,.5f,float(width)-1,float(height)-1);
        g.setColour(surface);g.fillRoundedRectangle(area,3);g.setColour(box.hasKeyboardFocus(true)?ink:rule);g.drawRoundedRectangle(area,3,1);
        juce::Path arrow;const float x=float(width)-13,y=float(height)*.5f;
        arrow.startNewSubPath(x-3,y-2);arrow.lineTo(x,y+1);arrow.lineTo(x+3,y-2);g.setColour(quiet);g.strokePath(arrow,juce::PathStrokeType(1.3f));
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
        g.setColour(slider.isEnabled()?juce::Colour(0xff718e88):rule); g.strokePath(value, juce::PathStrokeType(3.0f));
        const float body = radius * .77f;
        g.setColour(slider.isMouseOverOrDragging() && slider.isEnabled() ? accent : surface);
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

// Escape must cancel the complete edit gesture even while a Slider owns focus.
class Knob final : public juce::Slider {
public:
    std::function<bool()> onEscape;
    void focusLost(FocusChangeType cause) override { juce::Slider::focusLost(cause);if(onEscape)onEscape(); }
    bool keyPressed(const juce::KeyPress& key) override {
        if(key==juce::KeyPress::escapeKey && onEscape && onEscape())return true;
        return juce::Slider::keyPressed(key);
    }
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
