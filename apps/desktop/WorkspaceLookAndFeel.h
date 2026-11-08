#pragma once

#include "UiDesign.h"

namespace emusician::design {

// Shared by the application default, workspace and device-control looks.
// PopupMenu is not a child of its target, and AlertWindow can be unassociated;
// the application must keep a default instance alive until all windows close.
// This class only paints controls. It never owns project state or callbacks.
class WorkspaceLookAndFeel : public juce::LookAndFeel_V4 {
public:
    WorkspaceLookAndFeel()
        : juce::LookAndFeel_V4(juce::LookAndFeel_V4::ColourScheme(
              paper, panel, paper, rule, ink, focus, ink, accent, ink))
    {
        setColour(juce::ResizableWindow::backgroundColourId, paper);
        setColour(juce::Label::textColourId, ink);
        setColour(juce::TextButton::buttonColourId, panel);
        setColour(juce::TextButton::buttonOnColourId, accent);
        setColour(juce::TextButton::textColourOffId, ink);
        setColour(juce::TextButton::textColourOnId, ink);
        setColour(juce::ToggleButton::textColourId, ink);
        setColour(juce::ToggleButton::tickColourId, focus);
        setColour(juce::ToggleButton::tickDisabledColourId, secondary);
        setColour(juce::TextEditor::backgroundColourId, paper);
        setColour(juce::TextEditor::textColourId, ink);
        setColour(juce::TextEditor::outlineColourId, rule);
        setColour(juce::TextEditor::focusedOutlineColourId, focus);
        setColour(juce::TextEditor::highlightColourId, accent);
        setColour(juce::TextEditor::highlightedTextColourId, ink);
        setColour(juce::TextEditor::shadowColourId, juce::Colours::transparentBlack);
        setColour(juce::CaretComponent::caretColourId, ink);
        setColour(juce::ComboBox::backgroundColourId, paper);
        setColour(juce::ComboBox::textColourId, ink);
        setColour(juce::ComboBox::outlineColourId, rule);
        setColour(juce::ComboBox::focusedOutlineColourId, focus);
        setColour(juce::ComboBox::arrowColourId, secondary);
        setColour(juce::PopupMenu::backgroundColourId, paper);
        setColour(juce::PopupMenu::textColourId, ink);
        setColour(juce::PopupMenu::headerTextColourId, secondary);
        setColour(juce::PopupMenu::highlightedBackgroundColourId, accent);
        setColour(juce::PopupMenu::highlightedTextColourId, ink);
        setColour(juce::AlertWindow::backgroundColourId, paper);
        setColour(juce::AlertWindow::textColourId, ink);
        setColour(juce::AlertWindow::outlineColourId, rule);
        setColour(juce::TooltipWindow::backgroundColourId, paper);
        setColour(juce::TooltipWindow::textColourId, ink);
        setColour(juce::TooltipWindow::outlineColourId, rule);
        setColour(juce::ListBox::backgroundColourId, paper);
        setColour(juce::ListBox::textColourId, ink);
        setColour(juce::ListBox::outlineColourId, rule);
        setColour(juce::ScrollBar::thumbColourId, rule);
        setColour(juce::Slider::backgroundColourId, rule);
        setColour(juce::Slider::trackColourId, focus);
        setColour(juce::Slider::thumbColourId, ink);
        setColour(juce::Slider::textBoxTextColourId, ink);
        setColour(juce::Slider::textBoxBackgroundColourId, paper);
        setColour(juce::Slider::textBoxOutlineColourId, rule);
    }

    juce::Font getPopupMenuFont() override { return labelFont(13.0f); }
    int getPopupMenuBorderSize() override { return 5; }

    void drawPopupMenuBackground(juce::Graphics& g, int width, int height) override
    {
        g.fillAll(paper);
        g.setColour(rule);
        g.drawRoundedRectangle(juce::Rectangle<float>(.5f, .5f, float(width - 1), float(height - 1)), 3.0f, 1.0f);
    }

    void getIdealPopupMenuItemSize(const juce::String& text, bool separator,
                                   int requestedHeight, int& width, int& height) override
    {
        height = separator ? 9 : juce::jmax(28, requestedHeight);
        if (separator) { width = 64; return; }
        const auto label = text.upToFirstOccurrenceOf("\t", false, false);
        const auto shortcut = text.containsChar('\t') ? text.fromFirstOccurrenceOf("\t", false, false).trim() : juce::String();
        width = juce::GlyphArrangement::getStringWidthInt(getPopupMenuFont(), label) + 58;
        if (shortcut.isNotEmpty()) width += 24 + juce::GlyphArrangement::getStringWidthInt(numberFont(11.5f), shortcut);
    }

    void drawPopupMenuItem(juce::Graphics& g, const juce::Rectangle<int>& area,
                           bool separator, bool active, bool highlighted, bool ticked,
                           bool submenu, const juce::String& text,
                           const juce::String& shortcutText, const juce::Drawable* icon,
                           const juce::Colour* customColour) override
    {
        if (separator) {
            g.setColour(rule);
            g.drawHorizontalLine(area.getCentreY(), float(area.getX() + 10), float(area.getRight() - 10));
            return;
        }
        if (active && highlighted) {
            g.setColour(accent);
            g.fillRoundedRectangle(area.toFloat().reduced(2.0f, 1.0f), 3.0f);
        }
        const auto colour = active ? (customColour != nullptr ? *customColour : ink) : secondary;
        g.setColour(colour);
        auto bounds = area.reduced(10, 0);
        const auto iconBounds = bounds.removeFromLeft(19).toFloat().withSizeKeepingCentre(13, 13);
        if (icon != nullptr) icon->drawWithin(g, iconBounds, juce::RectanglePlacement::centred, active ? 1.0f : .45f);
        else if (ticked) {
            juce::Path tick;
            tick.startNewSubPath(iconBounds.getX() + 1, iconBounds.getCentreY());
            tick.lineTo(iconBounds.getX() + 5, iconBounds.getBottom() - 2);
            tick.lineTo(iconBounds.getRight() - 1, iconBounds.getY() + 2);
            g.strokePath(tick, juce::PathStrokeType(1.5f));
        }
        const auto arrowBounds = bounds.removeFromRight(13);
        if (submenu) {
            const auto x = float(arrowBounds.getCentreX()), y = float(arrowBounds.getCentreY());
            juce::Path arrow;
            arrow.startNewSubPath(x - 2, y - 4); arrow.lineTo(x + 2, y); arrow.lineTo(x - 2, y + 4);
            g.strokePath(arrow, juce::PathStrokeType(1.3f));
        }
        auto label = text;
        auto shortcut = shortcutText;
        if (text.containsChar('\t')) {
            label = text.upToFirstOccurrenceOf("\t", false, false);
            if (shortcut.isEmpty()) shortcut = text.fromFirstOccurrenceOf("\t", false, false).trim();
        }
        if (shortcut.isNotEmpty()) {
            const auto font = numberFont(11.5f);
            const auto shortcutWidth = juce::GlyphArrangement::getStringWidthInt(font, shortcut) + 2;
            g.setFont(font); g.setColour(secondary);
            g.drawText(shortcut, bounds.removeFromRight(shortcutWidth), juce::Justification::centredRight, true);
            bounds.removeFromRight(24);
        }
        g.setFont(getPopupMenuFont()); g.setColour(colour);
        g.drawText(label, bounds, juce::Justification::centredLeft, true);
    }

    void drawPopupMenuSectionHeader(juce::Graphics& g, const juce::Rectangle<int>& area,
                                    const juce::String& text) override
    {
        g.setColour(secondary); g.setFont(labelFont(12.0f, true));
        g.drawText(text, area.reduced(10, 0), juce::Justification::centredLeft, true);
    }

    int getCallOutBoxBorderSize(const juce::CallOutBox&) override { return 12; }
    float getCallOutBoxCornerSize(const juce::CallOutBox&) override { return 3.0f; }
    void drawCallOutBoxBackground(juce::CallOutBox&, juce::Graphics& g,
                                  const juce::Path& path, juce::Image&) override
    {
        // Options sheets keep JUCE's anchor, dismissal and content ownership,
        // but share the same opaque paper and fine rule as menus and dialogs.
        g.setColour(paper); g.fillPath(path);
        g.setColour(rule); g.strokePath(path, juce::PathStrokeType(1.0f));
    }

    juce::Font getComboBoxFont(juce::ComboBox&) override { return labelFont(13.0f); }
    void positionComboBoxText(juce::ComboBox& box, juce::Label& label) override
    {
        label.setBounds(10, 1, juce::jmax(0, box.getWidth() - 34), juce::jmax(0, box.getHeight() - 2));
        label.setFont(getComboBoxFont(box));
    }
    void drawComboBox(juce::Graphics& g, int width, int height, bool down,
                      int, int, int, int, juce::ComboBox& box) override
    {
        const auto bounds = juce::Rectangle<float>(.5f, .5f, float(width - 1), float(height - 1));
        g.setColour(box.isEnabled() && down ? panel : box.findColour(juce::ComboBox::backgroundColourId));
        g.fillRoundedRectangle(bounds, 3.0f);
        g.setColour(box.isEnabled() && box.hasKeyboardFocus(true) ? focus : rule);
        g.drawRoundedRectangle(bounds, 3.0f, box.hasKeyboardFocus(true) ? 1.5f : 1.0f);
        const auto x = float(width - 14), y = float(height) * .5f;
        juce::Path arrow;
        arrow.startNewSubPath(x - 3, y - 2); arrow.lineTo(x, y + 1); arrow.lineTo(x + 3, y - 2);
        g.setColour(box.isEnabled() ? secondary : rule); g.strokePath(arrow, juce::PathStrokeType(1.3f));
    }

    juce::Font getTextButtonFont(juce::TextButton&, int) override { return labelFont(13.0f); }
    void drawButtonBackground(juce::Graphics& g, juce::Button& button, const juce::Colour&, bool over, bool down) override
    {
        const bool primary = bool(button.getProperties()["workspaceDialogPrimary"]);
        const auto bounds = button.getLocalBounds().toFloat().reduced(1.0f);
        auto fill = primary || button.getToggleState() ? accent : paper;
        if (button.isEnabled() && (over || down)) fill = fill.interpolatedWith(focus, down ? .22f : .10f);
        g.setColour(button.isEnabled() ? fill : panel); g.fillRoundedRectangle(bounds, 3.0f);
        g.setColour(primary ? focus : rule); g.drawRoundedRectangle(bounds, 3.0f, 1.0f);
        if (button.hasKeyboardFocus(true)) {
            g.setColour(focus); g.drawRoundedRectangle(bounds.reduced(2), 2.0f, 1.5f);
        }
    }
    void drawButtonText(juce::Graphics& g, juce::TextButton& button, bool, bool) override
    {
        g.setColour(button.isEnabled() ? ink : secondary); g.setFont(getTextButtonFont(button, button.getHeight()));
        g.drawFittedText(button.getButtonText(), button.getLocalBounds().reduced(10, 2), juce::Justification::centred, 1);
    }
    void fillTextEditorBackground(juce::Graphics& g, int width, int height, juce::TextEditor& editor) override
    {
        g.setColour(editor.findColour(juce::TextEditor::backgroundColourId));
        g.fillRoundedRectangle(juce::Rectangle<float>(0, 0, float(width), float(height)), 3.0f);
    }
    void drawTextEditorOutline(juce::Graphics& g, int width, int height, juce::TextEditor& editor) override
    {
        const bool focused = editor.isEnabled() && editor.hasKeyboardFocus(true) && !editor.isReadOnly();
        g.setColour(focused ? focus : rule);
        g.drawRoundedRectangle(juce::Rectangle<float>(.5f, .5f, float(width - 1), float(height - 1)), 3.0f, focused ? 1.5f : 1.0f);
    }

    int getAlertWindowButtonHeight() override { return 32; }
    juce::Font getAlertWindowTitleFont() override { return labelFont(18.0f, true); }
    juce::Font getAlertWindowMessageFont() override { return labelFont(14.0f); }
    juce::Font getAlertWindowFont() override { return labelFont(13.0f); }
    int getAlertBoxWindowFlags() override { return juce::ComponentPeer::windowAppearsOnTaskbar; }
    juce::Array<int> getWidthsForTextButtons(juce::AlertWindow&, const juce::Array<juce::TextButton*>& buttons) override
    {
        juce::Array<int> widths;
        for (auto* button : buttons) widths.add(juce::jmax(86, juce::GlyphArrangement::getStringWidthInt(labelFont(13), button->getButtonText()) + 28));
        return widths;
    }
    juce::AlertWindow* createAlertWindow(const juce::String& title, const juce::String& message,
                                        const juce::String& button1, const juce::String& button2,
                                        const juce::String& button3, juce::MessageBoxIconType icon,
                                        int count, juce::Component* associated) override
    {
        // V2 supplies the original result IDs and keyboard/callback semantics;
        // V4 adds excessive icon/padding styling which is deliberately omitted.
        auto* alert = juce::LookAndFeel_V2::createAlertWindow(title, message, button1, button2, button3, icon, count, associated);
        alert->setLookAndFeel(this);
        alert->setDropShadowEnabled(false);
        const auto bounds = alert->getBounds();
        alert->setBounds(bounds.withSizeKeepingCentre(juce::jmax(380, bounds.getWidth()), juce::jmax(176, bounds.getHeight() + 12)));
        int right = alert->getWidth() - 24;
        for (int i = alert->getNumButtons() - 1; i >= 0; --i) {
            auto* button = alert->getButton(i);
            button->setTopLeftPosition(right - button->getWidth(), alert->getHeight() - 24 - button->getHeight());
            button->getProperties().set("workspaceDialogPrimary", i == 0);
            button->setExplicitFocusOrder(i + 1);
            right = button->getX() - 8;
        }
        return alert;
    }
    void drawAlertBox(juce::Graphics& g, juce::AlertWindow& alert,
                      const juce::Rectangle<int>& textArea, juce::TextLayout& text) override
    {
        g.fillAll(paper);
        int footer = alert.getHeight();
        for (int i = 0; i < alert.getNumButtons(); ++i) footer = juce::jmin(footer, alert.getButton(i)->getY() - 18);
        if (footer < alert.getHeight()) {
            g.setColour(panel); g.fillRect(1, footer, alert.getWidth() - 2, alert.getHeight() - footer - 1);
            g.setColour(rule); g.drawHorizontalLine(footer, 1.0f, float(alert.getWidth() - 1));
        }
        g.setColour(ink);
        // Keep JUCE's laid-out, accessible message; the title already expresses
        // the question/warning, without a decorative 130-pixel stock glyph.
        const auto available = juce::Rectangle<float>(24, 24, float(alert.getWidth() - 48), float(juce::jmax(1, footer - 30)));
        text.draw(g, alert.containsAnyExtraComponents() ? textArea.toFloat() : available);
        g.setColour(rule); g.drawRoundedRectangle(alert.getLocalBounds().toFloat().reduced(.5f), 3.0f, 1.0f);
    }
};
} // namespace emusician::design
