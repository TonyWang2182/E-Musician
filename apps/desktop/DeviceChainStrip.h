#pragma once

#include "EngineSession.h"
#include "DeviceControlStyle.h"
#include "UiLanguage.h"
#include <functional>
#include <memory>
#include <vector>

namespace emusician {

// A view of the authoritative ordered plug-in slots, never a second model.
class DeviceChainStrip final : public juce::Component {
public:
    using Slot = EngineSession::PluginSlotSnapshot;
    std::function<void(const juce::String&, const Slot&)> onSelect;
    std::function<void(const juce::String&, const juce::String&)> onAdd;
    std::function<void(const juce::String&)> onBrowse;

    DeviceChainStrip() {
        setLookAndFeel(&look);
        for (auto* c : std::initializer_list<juce::Component*>{&targetLabel,&previous,&next,&viewport,&addButton}) addAndMakeVisible(c);
        targetLabel.setFont(deviceui::labelFont(12.0f,true));
        targetLabel.setColour(juce::Label::textColourId,deviceui::ink);
        targetLabel.setJustificationType(juce::Justification::centredLeft);
        targetLabel.setBorderSize(juce::BorderSize<int>(0,7,0,5));
        targetLabel.setTitle("Device chain target track");
        viewport.setViewedComponent(&content, false); viewport.setScrollBarsShown(false, false);
        previous.setTooltip("Previous device in signal order"); next.setTooltip("Next device in signal order");
        previous.onClick = [this] { step(-1); }; next.onClick = [this] { step(1); };
        addButton.setTooltip("Add a native device or browse installed plug-ins");
        addButton.onClick = [this] {
            juce::PopupMenu menu;menu.addItem(1,"Sampler",canInstrument);menu.addItem(2,"Drum Rack",canInstrument);
            menu.addSeparator();menu.addItem(3,"EQ Eight");menu.addItem(4,"Compressor");menu.addItem(5,"Stereo Delay");menu.addItem(6,"Reverb");menu.addItem(7,"Auto Filter");
            menu.addSeparator();menu.addItem(8,uiText("Browse plug-ins..."));
            const auto project=projectId,target=trackId;
            menu.showMenuAsync(juce::PopupMenu::Options().withTargetComponent(&addButton),[safe=juce::Component::SafePointer<DeviceChainStrip>(this),project,target](int choice){
                if(!safe||safe->projectId!=project||safe->trackId!=target)return;
                if(choice>=1&&choice<=7){const char* types[]{"sampler","drum_rack","eq8","compressor","delay","reverb","auto_filter"};safe->add(types[choice-1]);}
                else if(choice==8&&safe->onBrowse)safe->onBrowse(target);
            });
        };
        setTitle("Device chain and built-in devices");
    }
    ~DeviceChainStrip() override { setLookAndFeel(nullptr); viewport.setViewedComponent(nullptr, false); }

    void update(const juce::String& project, const juce::String& target, const juce::String& name,
                const std::vector<Slot>& values, const juce::String& selected,
                bool instrumentTrack, bool canEdit) {
        juce::String signature = project + "\n" + target;
        for (const auto& slot : values) signature += "\n" + slot.id + "/" + slot.name + "/" + slot.format + "/" + slot.identifier + (slot.isInstrument ? "I" : "E") + (slot.enabled ? "+" : "-") + (slot.missing ? "?" : "");
        projectId=project; trackId=target; trackName=name; selectedId=selected;
        const auto targetText=target.isEmpty()?uiText("Select a track"):name.isEmpty()?target:name;
        targetLabel.setText(targetText,juce::dontSendNotification);
        targetLabel.setTooltip(uiText("Device chain: ")+targetText);
        if (signature != identity) {
            identity=std::move(signature); slots=values; buttons.clear();
            for (const auto& slot : slots) {
                auto button=std::make_unique<juce::TextButton>((slot.enabled ? "" : "[off] ") + slot.name + (slot.missing ? " [missing]" : ""));
                button->setClickingTogglesState(false); button->setToggleState(slot.id==selectedId, juce::dontSendNotification);
                button->setTooltip(slot.missing ? "Plug-in missing; open the device list to manage it." : "Open " + slot.name + " in signal order");
                button->setEnabled(!slot.missing);
                button->onClick=[this,id=slot.id] { select(id); };
                content.addAndMakeVisible(*button); buttons.push_back(std::move(button));
            }
            resized();
        }
        for (std::size_t i=0;i<buttons.size();++i) buttons[i]->setToggleState(slots[i].id==selectedId,juce::dontSendNotification);
        const bool hasTarget = target.isNotEmpty();
        canInstrument=instrumentTrack;addButton.setEnabled(canEdit && hasTarget);
        addButton.setButtonText(uiText("+ Add device"));
        previous.setEnabled(!slots.empty()); next.setEnabled(!slots.empty());
        repaint();
    }
    void resized() override {
        auto chain=getLocalBounds();
        targetLabel.setBounds(chain.removeFromLeft(getWidth()>=600?120:100).reduced(0,2));
        addButton.setBounds(chain.removeFromRight(116).reduced(3,2));
        previous.setBounds(chain.removeFromLeft(30).reduced(2)); next.setBounds(chain.removeFromRight(30).reduced(2));
        viewport.setBounds(chain.reduced(2,1));
        int x=0; for (auto& button:buttons) { const int w=juce::jlimit(92,180,button->getButtonText().length()*7+28); button->setBounds(x,0,w,27); x+=w+4; }
        content.setSize(juce::jmax(x,viewport.getWidth()),27);
    }
    void paint(juce::Graphics& g) override {
        g.fillAll(juce::Colour(0xfffefefd));
        g.setColour(juce::Colour(0xffc6c9c3)); g.drawHorizontalLine(getHeight()-1,0,float(getWidth()));
        if (slots.empty()&&trackId.isNotEmpty()) { g.setColour(deviceui::quiet); g.setFont(deviceui::labelFont(12.0f)); g.drawText(uiText("No devices"),viewport.getBounds().reduced(4,0),juce::Justification::centredLeft,true); }
    }
    int deviceCount() const noexcept { return int(slots.size()); }
    juce::String selectedForTest() const { return selectedId; }
    void selectForTest(const juce::String& id) { select(id); }
    void stepForTest(int delta) { step(delta); }

private:
    void add(const juce::String& type) { if (onAdd && trackId.isNotEmpty()) onAdd(trackId,type); }
    void select(const juce::String& id) {
        for (const auto& slot : slots) if (slot.id==id && !slot.missing) {
            selectedId=id; for (std::size_t i=0;i<slots.size();++i) buttons[i]->setToggleState(slots[i].id==id,juce::dontSendNotification);
            if(onSelect)onSelect(trackId,slot); return;
        }
    }
    void step(int delta) {
        if (slots.empty()) return;
        int current=-1; for(int i=0;i<int(slots.size());++i) if(slots[std::size_t(i)].id==selectedId)current=i;
        const int first=current<0 ? (delta>0?0:int(slots.size())-1) : juce::jlimit(0,int(slots.size())-1,current+delta);
        for(int i=first;i>=0&&i<int(slots.size());i+=delta) if(!slots[std::size_t(i)].missing) {
            const auto bounds=buttons[std::size_t(i)]->getBounds();
            viewport.setViewPosition(juce::jlimit(0,juce::jmax(0,content.getWidth()-viewport.getWidth()),bounds.getX() - viewport.getWidth()/2 + bounds.getWidth()/2),0);
            select(slots[std::size_t(i)].id); return;
        }
    }
    juce::String projectId, trackId, trackName, selectedId, identity;
    std::vector<Slot> slots;
    std::vector<std::unique_ptr<juce::TextButton>> buttons;
    struct Arrow final:juce::TextButton {
        explicit Arrow(bool forward):next(forward){setTitle(forward?"Next device":"Previous device");}
        void paintButton(juce::Graphics& g,bool hover,bool down) override {
            g.setColour(down?deviceui::rule:hover?deviceui::surface:deviceui::paper);g.fillRoundedRectangle(getLocalBounds().toFloat().reduced(1),3);
            g.setColour(isEnabled()?deviceui::ink:deviceui::rule);const float cx=getWidth()*.5f,cy=getHeight()*.5f,sign=next?1.0f:-1.0f;
            juce::Path arrow;arrow.startNewSubPath(cx-sign*2,cy-4);arrow.lineTo(cx+sign*2,cy);arrow.lineTo(cx-sign*2,cy+4);g.strokePath(arrow,juce::PathStrokeType(1.4f));
            if(hasKeyboardFocus(true))g.drawRoundedRectangle(getLocalBounds().toFloat().reduced(1),3,1);
        }
        bool next;
    };
    deviceui::ControlLook look;
    bool canInstrument=false;
    Arrow previous{false},next{true};juce::TextButton addButton{"+ Add device"};
    juce::Label targetLabel;
    juce::Viewport viewport;
    juce::Component content;
};
}
