#pragma once

#include "../apps/desktop/WorkspaceLookAndFeel.h"
#include "../apps/desktop/DeviceControlStyle.h"
#include <set>
#include <stdexcept>
#include <string>

namespace emusician::style_smoke {
inline juce::Result run(const juce::File& directory, design::WorkspaceLookAndFeel& look)
{
    juce::Array<juce::var> checks;
    juce::String error;
    const auto require = [&](bool passed, const juce::String& name) {
        auto item = std::make_unique<juce::DynamicObject>();
        item->setProperty("name", name); item->setProperty("passed", passed); checks.add(juce::var(item.release()));
        if (!passed) throw std::runtime_error(name.toStdString());
    };
    const auto capture = [&](juce::Component& component, const juce::String& name, float scale = 1.0f) {
        juce::MemoryOutputStream bytes;
        require(juce::PNGImageFormat().writeImageToStream(component.createComponentSnapshot(component.getLocalBounds(), true, scale), bytes)
            && directory.getChildFile(name).replaceWithData(bytes.getData(), bytes.getDataSize()), "capture " + name);
    };
    struct Surface final : juce::Component {
        void paint(juce::Graphics& g) override { g.fillAll(design::paper); }
    } surface;
    surface.setSize(640, 320);
    surface.setLookAndFeel(&look);
    juce::ComboBox box;
    surface.addAndMakeVisible(box); box.setBounds(20, 16, 280, 32);
    box.addItem("Cloud / SCNet", 1); box.setSelectedId(1);
    try {
        require(directory.createDirectory().wasOk(), "create popup evidence directory");
        require(dynamic_cast<design::WorkspaceLookAndFeel*>(&juce::LookAndFeel::getDefaultLookAndFeel()) != nullptr,
                "application default reaches unassociated menus and dialogs");
        deviceui::ControlLook device;
        require(device.findColour(juce::PopupMenu::backgroundColourId) == design::paper,
                "device-control popups inherit shared paper theme");
        require(look.findColour(juce::AlertWindow::backgroundColourId) == design::paper
                && look.findColour(juce::PopupMenu::highlightedTextColourId) == design::ink,
                "popup and alert palettes match workspace");

        {
            juce::Image atlas(juce::Image::RGB, 500, 360, true);
            { // Finish deferred native drawing before reading or encoding pixels.
            juce::Graphics sheet(atlas); sheet.fillAll(design::paper);
            auto& application = static_cast<design::WorkspaceLookAndFeel&>(juce::LookAndFeel::getDefaultLookAndFeel());
            int column = 0;
            for (auto* theme : { static_cast<design::WorkspaceLookAndFeel*>(&device), &application }) {
                const int left = column * 250;
                sheet.setColour(design::ink); sheet.setFont(design::labelFont(13, true));
                sheet.drawText(column == 0 ? "Track / device controls" : "Application controls", left + 8, 4, 234, 24, juce::Justification::centredLeft);
                int row = 0;
                for (const int size : { 20, 24, 28 }) for (int state = 0; state < 3; ++state) {
                    const int top = 36 + row++ * 35;
                    sheet.setColour(design::secondary); sheet.setFont(design::labelFont(11));
                    sheet.drawText(juce::String(size) + "px / " + (state == 0 ? "off" : state == 1 ? "on" : "disabled"), left + 8, top, 98, 28, juce::Justification::centredLeft);
                    std::set<std::string> shapes;
                    int index = 0;
                    for (const auto* label : { "M", "S", "R" }) {
                        juce::TextButton button(label); button.setLookAndFeel(theme); button.setSize(size, size); button.setVisible(true);
                        button.setToggleState(state == 1, juce::dontSendNotification); button.setEnabled(state != 2);
                        juce::Image glyph(juce::Image::ARGB, size, size, true);
                        { juce::Graphics textGraphics(glyph); theme->drawButtonText(textGraphics, button, false, false); }
                        int occupiedRows = 0; std::string shape;
                        for (int y = 0; y < size; ++y) {
                            bool occupied = false;
                            for (int x = 0; x < size; ++x) {
                                const bool painted = glyph.getPixelAt(x, y).getAlpha() > 48;
                                occupied |= painted; shape += painted ? '1' : '0';
                            }
                            if (occupied) ++occupiedRows;
                        }
                        require(occupiedRows >= 5, "compact " + juce::String(label) + " remains a full-height glyph at " + juce::String(size) + "px state " + juce::String(state));
                        shapes.insert(std::move(shape));
                        sheet.drawImageAt(button.createComponentSnapshot(button.getLocalBounds(), true), left + 112 + index++ * 38, top);
                        button.setLookAndFeel(nullptr);
                    }
                    require(shapes.size() == 3, "M S R remain distinct instead of identical ellipses at " + juce::String(size) + "px state " + juce::String(state));
                }
                ++column;
            }
            }
            require(atlas.getPixelAt(0, 0) == design::paper, "compact atlas background is committed before encoding");
            int inkPixels = 0;
            for (int y = 36; y < atlas.getHeight(); ++y) for (int x = 112; x < 230; ++x)
                if (atlas.getPixelAt(x, y).getBrightness() < 0.5f) ++inkPixels;
            require(inkPixels > 100, "compact atlas contains painted control labels instead of an empty image");
            juce::MemoryOutputStream bytes;
            require(juce::PNGImageFormat().writeImageToStream(atlas, bytes)
                    && directory.getChildFile("ui-compact-track-buttons.png").replaceWithData(bytes.getData(), bytes.getDataSize()),
                    "capture actual compact button raster states");
        }

        juce::PopupMenu submenu; submenu.addItem(31, "Sampler"); submenu.addItem(32, "Drum Rack");
        juce::PopupMenu menu;
        menu.addItem(1, "New project\tCtrl+N");
        menu.addItem(2, "Save as...\tCtrl+Shift+S");
        menu.addSeparator();
        menu.addItem(3, "Snap to grid", true, true);
        menu.addItem(4, "Unavailable action", false);
        menu.addSubMenu("Native instruments", submenu);
        menu.showMenuAsync(juce::PopupMenu::Options().withTargetComponent(&box).withParentComponent(&surface), [](int) {});
        juce::MessageManager::getInstance()->runDispatchLoopUntil(40);
        juce::Component* popup = nullptr;
        for (auto* child : surface.getChildren()) if (child != &box) popup = child;
        require(popup != nullptr && popup->isVisible(), "actual detached popup is created by JUCE");
        require(dynamic_cast<design::WorkspaceLookAndFeel*>(&popup->getLookAndFeel()) != nullptr,
                "actual popup resolves application theme");
        require(surface.getLocalBounds().contains(popup->getBounds()), "popup fits fixture canvas");
        capture(surface, "ui-popup-menu.png");
        capture(surface, "ui-popup-menu-150.png", 1.5f);
        juce::PopupMenu::dismissAllActiveMenus();
        juce::MessageManager::getInstance()->runDispatchLoopUntil(40);

        {
            Surface options; options.setSize(340, 146);
            juce::Label title; title.setText("Analysis options", juce::dontSendNotification);
            title.setFont(design::labelFont(14, true)); title.setBounds(12, 8, 306, 24); options.addAndMakeVisible(title);
            juce::ComboBox scope; scope.addItem("Selected clips", 1); scope.addItem("Time selection", 2);
            scope.setSelectedId(1); scope.setBounds(12, 42, 306, 30); options.addAndMakeVisible(scope);
            juce::ToggleButton preserve("Keep original tracks");
            preserve.setToggleState(true, juce::dontSendNotification); preserve.setBounds(12, 88, 306, 28); options.addAndMakeVisible(preserve);
            juce::CallOutBox callout(options, box.getBounds(), &surface);
            callout.setArrowSize(8); callout.updatePosition(box.getBounds(), surface.getLocalBounds());
            require(dynamic_cast<design::WorkspaceLookAndFeel*>(&callout.getLookAndFeel()) != nullptr,
                    "Options CallOutBox inherits shared theme");
            require(surface.getLocalBounds().contains(callout.getBounds()), "Options CallOutBox fits fixture canvas");
            capture(surface, "ui-options-callout.png");
            capture(surface, "ui-options-callout-200.png", 2.0f);
            const auto image = callout.createComponentSnapshot(callout.getLocalBounds(), true);
            const auto contentBounds = callout.getLocalArea(&options, options.getLocalBounds());
            require(image.getPixelAt(contentBounds.getX() - 3, contentBounds.getCentreY()) == design::paper,
                    "Options shell is opaque paper without stock translucent shadow");
        }

        for (const bool chinese : { false, true }) {
            const juce::String title = chinese ? juce::String::fromUTF8("保存更改？") : juce::String("Save changes?");
            const juce::String message = chinese ? juce::String::fromUTF8("继续之前，要保存当前工程的更改吗？")
                                                 : juce::String("Save changes to Untitled before continuing?");
            std::unique_ptr<juce::AlertWindow> alert(look.createAlertWindow(title, message,
                chinese ? juce::String::fromUTF8("保存") : juce::String("Save"),
                chinese ? juce::String::fromUTF8("不保存") : juce::String("Discard"),
                chinese ? juce::String::fromUTF8("取消") : juce::String("Cancel"),
                juce::MessageBoxIconType::QuestionIcon, 3, &surface));
            require(alert->getNumButtons() == 3 && alert->getAlertType() == juce::MessageBoxIconType::QuestionIcon,
                    "question semantics and three actions preserved");
            require(alert->getButton(0)->getCommandID() == 1 && alert->getButton(1)->getCommandID() == 2
                    && alert->getButton(2)->getCommandID() == 0, "Save Discard Cancel result IDs unchanged");
            require(alert->getButton(2)->isRegisteredForShortcut(juce::KeyPress(juce::KeyPress::escapeKey)),
                    "Escape still maps to Cancel");
            require(alert->getButton(0)->getExplicitFocusOrder() < alert->getButton(1)->getExplicitFocusOrder()
                    && alert->getButton(1)->getExplicitFocusOrder() < alert->getButton(2)->getExplicitFocusOrder(),
                    "dialog keyboard focus order follows button order");
            for (int i = 0; i < alert->getNumButtons(); ++i) {
                require(alert->getLocalBounds().contains(alert->getButton(i)->getBounds()), "dialog button in bounds");
                if (i + 1 < alert->getNumButtons()) require(!alert->getButton(i)->getBounds().intersects(alert->getButton(i + 1)->getBounds()),
                                                          "dialog buttons do not overlap");
            }
            capture(*alert, chinese ? "ui-save-confirm-zh.png" : "ui-save-confirm-en.png");
            capture(*alert, chinese ? "ui-save-confirm-zh-200.png" : "ui-save-confirm-en-200.png", 2.0f);
            const auto image = alert->createComponentSnapshot(alert->getLocalBounds(), true);
            require(image.getPixelAt(8, 8) == design::paper, "alert body is paper without stock giant glyph");
            require(image.getPixelAt(8, image.getHeight() - 8) == design::panel, "alert footer is quiet panel");
        }
    } catch (const std::exception& failure) { error = juce::String::fromUTF8(failure.what()); }
    juce::PopupMenu::dismissAllActiveMenus();
    juce::MessageManager::getInstance()->runDispatchLoopUntil(40);
    box.setLookAndFeel(nullptr); surface.setLookAndFeel(nullptr);
    auto report = std::make_unique<juce::DynamicObject>();
    report->setProperty("status", error.isEmpty() ? "passed" : "failed");
    report->setProperty("checks", checks); report->setProperty("error", error);
    report->setProperty("fixture_only", true); report->setProperty("physical_dpi_tested", false);
    directory.getChildFile("popup-style-report.json").replaceWithText(juce::JSON::toString(juce::var(report.release()), true));
    return error.isEmpty() ? juce::Result::ok() : juce::Result::fail(error);
}
} // namespace emusician::style_smoke
