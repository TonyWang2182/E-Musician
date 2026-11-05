// Workspace layout and library/colour actions. Included once by MainComponent.cpp.
void MainComponent::resized()
{
    auto& p=*impl;constexpr int margin=8;
    p.compactAnalysisFooter=false;p.footerY=getHeight()-32;
    if(p.dock!=Impl::Dock::midi)p.pianoExpanded=false;
    const bool expanded=p.dock==Impl::Dock::midi&&p.pianoExpanded;
    const bool sidebar=p.agentVisible&&!expanded;
    // Narrow windows use an overlay; opening the assistant never squeezes the
    // piano/arrangement below a usable width. Wide windows get a fixed column.
    const bool sidebarDocked=sidebar&&getWidth()>=1180;
    const int sidebarWidth=sidebar?juce::jlimit(320,380,getWidth()/4):0;
    const int right=getWidth()-margin-(sidebarDocked?sidebarWidth+8:0);
    p.libraryDisplayed=p.libraryVisible&&!expanded&&(!sidebar||getWidth()>=1450);
    const int libraryWidth=p.libraryDisplayed?176:0;
    p.library={margin,88,libraryWidth,p.footerY-100};
    p.browser.setVisible(p.libraryDisplayed);p.browser.setBounds(p.library);
    p.libraryButton.setToggleState(p.libraryDisplayed,juce::dontSendNotification);
    p.libraryButton.setEnabled(!expanded&&(!sidebar||getWidth()>=1450));
    p.inspectorDisplayed=p.inspectorVisible&&!sidebar&&!expanded&&p.dock!=Impl::Dock::track&&p.dock!=Impl::Dock::native&&p.dock!=Impl::Dock::effect&&p.dock!=Impl::Dock::analysis&&p.dock!=Impl::Dock::source;
    const int inspectorWidth=p.inspectorDisplayed?210:0;
    p.inspector={right-inspectorWidth,88,inspectorWidth,p.footerY-100};
    const int left=margin+(p.libraryDisplayed?libraryWidth+8:0);
    p.workspace={left,88,right-left-(p.inspectorDisplayed?inspectorWidth+8:0),p.footerY-100};
    if(p.agentSidebar){p.agentSidebar->setBounds(getWidth()-margin-sidebarWidth,88,sidebarWidth,p.footerY-100);p.agentSidebar->setPanelVisible(sidebar);if(sidebar)p.agentSidebar->toFront(false);}
    p.trackList.setVisible(false);p.compose.setVisible(false);p.transcribe.setVisible(false);p.filename.setVisible(false);
    for(auto* b:{&p.newButton,&p.openButton,&p.saveAsButton,&p.exportMenu})b->setVisible(false);
    p.fileMenu.setButtonText(uiText("File","文件"));p.fileMenu.setBounds(48,8,44,30);
    const int titleWidth=getWidth()>=1180?196:130;
    p.titleBounds={100,4,titleWidth,22};p.saveStatus.setBounds(100,24,titleWidth,18);p.saveStatus.setFont(design::labelFont(11));
    p.saveButton.setBounds(p.titleBounds.getRight()+4,8,54,30);
    int tx=p.saveButton.getRight()+12;
    for(auto* b:{&p.play,&p.stop,&p.record,&p.loop}){b->setBounds(tx,8,32,30);tx+=35;}
    p.positionBounds={tx+3,8,82,30};tx+=89;
    p.tempo.setBounds(tx,8,84,30);tx+=88;
    p.metronome.setBounds(tx,8,44,30);tx+=46;p.metronomeOptions.setBounds(tx,8,24,30);tx+=28;
    p.countIn.setBounds(tx,8,60,30);tx+=62;p.countInBars.setBounds(tx,8,64,30);
    p.settings.setBounds(getWidth()-166,8,86,30);p.agentButton.setBounds(getWidth()-76,8,68,30);
    p.agentButton.setToggleState(p.agentVisible,juce::dontSendNotification);
    int x=margin;const auto place=[&](juce::Component& c,int width){c.setBounds(x,50,width,28);x+=width+4;};
    p.libraryButton.setButtonText(uiText("Library","资源库"));place(p.libraryButton,64);place(p.importButton,50);place(p.editMenu,45);
    place(p.plugins,60);place(p.separate,54);place(p.analyze,60);place(p.details,54);place(p.undoButton,42);place(p.redoButton,42);
    place(p.rulerMode,80);place(p.snap,46);place(p.gridMode,98);place(p.follow,100);
    p.zoomOut.setBounds(getWidth()-116,50,30,28);p.zoomIn.setBounds(getWidth()-82,50,30,28);p.fit.setBounds(getWidth()-48,50,40,28);
    for(juce::Component* c:std::initializer_list<juce::Component*>{&p.rulerMode,&p.snap,&p.gridMode,&p.follow})c->setVisible(!expanded);
    const bool visual=p.dock==Impl::Dock::native||p.dock==Impl::Dock::effect;
    const bool analysis=p.dock==Impl::Dock::analysis;
    const bool chain=p.dock==Impl::Dock::track||visual;
    const int overviewHeight=expanded?0:18;
    const auto body=p.workspace.withTrimmedTop(overviewHeight);
    p.overview.setVisible(!expanded);p.overview.setBounds(p.workspace.withHeight(14));
    // Keep workspace as the whole usable area; tests and Agent use its width.
    p.workspace={left,88,right-left-(p.inspectorDisplayed?inspectorWidth+8:0),p.footerY-100};
    const int minArrangement=198;
    const int minimumDock=chain?248:analysis?210:p.dock==Impl::Dock::source?203:180;
    const int preferred=(p.dock==Impl::Dock::midi||chain)?280:300;
    const int height=p.dock==Impl::Dock::closed?0:expanded?body.getHeight():juce::jlimit(minimumDock,juce::jmax(minimumDock,body.getHeight()-minArrangement-6),p.dockHeightUser>0?p.dockHeightUser:preferred);
    p.dockBounds=body.withTrimmedTop(body.getHeight()-height);
    p.arrangement.setBounds(body.withTrimmedBottom(height>0?height+6:0));
    p.arrangement.setCompactRows(height>0);p.arrangement.setVisible(!expanded);
    p.divider.setVisible(height>0&&!expanded);p.divider.setBounds(left,p.dockBounds.getY()-6,p.workspace.getWidth(),6);
    p.closeEditor.setVisible(height>0);p.closeEditor.setButtonText(uiText("close","关闭"));
    p.closeEditor.setBounds(p.dockBounds.getRight()-64,p.dockBounds.getY()+3,60,26);
    p.closeEditor.setTooltip(uiText("Close the lower editor panel","关闭下方编辑面板"));
    p.expandEditor.setVisible(p.dock==Impl::Dock::midi);p.expandEditor.setButtonText(uiText(expanded?"return to arrangement":"expand"));
    p.expandEditor.setBounds(p.dockBounds.getRight()-230,p.dockBounds.getY()+3,160,26);
    p.waveform.setVisible(p.dock==Impl::Dock::source);p.waveform.setBounds(p.dockBounds.withTrimmedTop(28));
    if(p.pianoRoll){p.pianoRoll->setVisible(p.dock==Impl::Dock::midi);p.pianoRoll->setBounds(p.dockBounds.withTrimmedTop(30));}
    p.deviceChain.setVisible(chain);p.deviceChain.setBounds(p.dockBounds.withTrimmedRight(68).removeFromTop(34));
    const auto deviceBody=p.dockBounds.withTrimmedTop(36);
    p.trackPanel.setVisible(p.dock==Impl::Dock::track);p.trackPanel.setBounds(deviceBody);
    if(p.dockNative){p.dockNative->setVisible(p.dock==Impl::Dock::native);p.dockNative->setBounds(deviceBody);}
    if(p.dockEffect){p.dockEffect->setVisible(p.dock==Impl::Dock::effect);p.dockEffect->setBounds(deviceBody);}
    if(p.dockAnalysis){p.dockAnalysis->setVisible(analysis);p.dockAnalysis->setBounds(p.dockBounds);}
    if(analysis)p.closeEditor.toFront(false);
    p.separate.setToggleState(p.dock==Impl::Dock::source,juce::dontSendNotification);p.analyze.setToggleState(analysis,juce::dontSendNotification);
    p.details.setToggleState(p.inspectorDisplayed,juce::dontSendNotification);p.details.setEnabled(!sidebar&&!visual&&!analysis&&p.dock!=Impl::Dock::source&&p.dock!=Impl::Dock::track);
    const int ix=p.inspector.getX(),iy=p.inspector.getY(),iw=p.inspector.getWidth();
    p.clipStart.setBounds(ix+48,iy+62,iw-94,28);p.setClipStart.setBounds(ix+iw-42,iy+62,42,28);
    p.clipProperties.setBounds(ix,iy+98,iw,28);p.trackGain.setBounds(ix,iy+154,iw,30);p.trackPan.setBounds(ix,iy+212,iw,30);
    p.mute.setBounds(ix,iy+250,(iw-6)/2,28);p.solo.setBounds(p.mute.getRight()+6,iy+250,(iw-6)/2,28);p.remove.setVisible(false);
    for(juce::Component* c:std::initializer_list<juce::Component*>{&p.clipStart,&p.setClipStart,&p.clipProperties,&p.trackGain,&p.trackPan,&p.mute,&p.solo})c->setVisible(p.inspectorDisplayed);
    p.layoutDeviceButtons();
    p.gain.setBounds(getWidth()-194,p.footerY+1,186,30);p.meterReset.setBounds(getWidth()-236,p.footerY+3,36,26);
    p.resources.setBounds(getWidth()-584,p.footerY+5,316,22);p.resources.setFont(design::numberFont(10.5f));
    p.cancelJob.setBounds(getWidth()-676,p.footerY+5,88,22);p.status.setBounds(8,p.footerY+5,juce::jmax(160,getWidth()-692),22);p.status.setFont(design::labelFont(12));
    if(sidebar&&p.agentSidebar)p.agentSidebar->toFront(false);
}

void MainComponent::paint(juce::Graphics& g)
{
    const auto& p=*impl;const auto& s=p.state;g.fillAll(design::paper);
    brand::draw(g,{8,5,34,36});
    g.setColour(ink);g.setFont(design::labelFont(14,true));
    g.drawFittedText((s.projectName.isEmpty()?uiText("Untitled","未命名"):s.projectName)+(s.dirty?" *":""),p.titleBounds,juce::Justification::centredLeft,1);
    g.setColour(rule);g.drawHorizontalLine(43,8.0f,float(getWidth()-8));g.drawHorizontalLine(83,8.0f,float(getWidth()-8));
    g.setColour(ink);g.setFont(design::numberFont(12));
    g.drawFittedText(p.rulerMode.getSelectedId()==2?clockText(s.position):positionText(s.position,s,true),p.positionBounds.withHeight(18),juce::Justification::centred,1);
    g.setColour(secondary);g.setFont(design::numberFont(10));g.drawText(juce::String(s.numerator)+"/"+juce::String(s.denominator)+"  "+clockText(s.duration),p.positionBounds.withTrimmedTop(17),juce::Justification::centred);
    if(p.inspectorDisplayed){
        const int ix=p.inspector.getX(),iy=p.inspector.getY(),iw=p.inspector.getWidth();g.setColour(rule);g.drawVerticalLine(ix-4,float(iy),float(p.footerY-12));
        g.setColour(ink);g.setFont(design::labelFont(14,true));g.drawFittedText(p.selectedTrack()?p.selectedTrack()->name:uiText("Select a track","选择轨道"),ix,iy+10,iw,30,juce::Justification::centredLeft,1);
        g.setColour(secondary);g.setFont(design::labelFont(12));g.drawText(uiText("start","起点"),ix,iy+62,48,28,juce::Justification::centredLeft);
        g.drawText(uiText("track volume","轨道音量"),ix,iy+132,iw,22,juce::Justification::centredLeft);g.drawText(uiText("pan / L - R","声像 / 左 - 右"),ix,iy+190,iw,22,juce::Justification::centredLeft);g.drawText(uiText("devices","装置"),ix,iy+295,iw,24,juce::Justification::centredLeft);
    }
    if(p.dock!=Impl::Dock::closed){
        g.setColour(rule);g.drawHorizontalLine(p.dockBounds.getY(),float(p.dockBounds.getX()),float(p.dockBounds.getRight()));
        if(p.dock==Impl::Dock::midi||p.dock==Impl::Dock::source){g.setColour(secondary);g.setFont(design::labelFont(12));g.drawFittedText((p.dock==Impl::Dock::midi?"MIDI / ":"Audio / ")+p.selectedClipName(),p.dockBounds.getX()+6,p.dockBounds.getY()+3,p.dockBounds.getWidth()-(p.dock==Impl::Dock::midi?240:76),24,juce::Justification::centredLeft,1);}
    }
    g.setColour(design::panel);g.fillRect(0,p.footerY,getWidth(),32);g.setColour(rule);g.drawHorizontalLine(p.footerY,0,float(getWidth()));
    for(int channel=0;channel<2;++channel){const auto db=channel?s.masterPeakRightDb:s.masterPeakLeftDb;const auto height=juce::jlimit(0.0f,1.0f,(db+60.0f)/60.0f)*23.0f;const float x=float(getWidth()-256+channel*8);g.setColour(rule);g.fillRect(x,float(p.footerY+5),5.0f,23.0f);g.setColour(s.masterOverloaded?juce::Colour(0xffb34840):design::focus);g.fillRect(x,float(p.footerY+28)-height,5.0f,height);}
}

void MainComponent::showFileMenu()
{
    juce::PopupMenu menu;menu.addItem(1,uiText("New project","新建工程")+"\tCtrl+N",impl->newButton.isEnabled());menu.addItem(2,uiText("Open project…","打开工程…")+"\tCtrl+O",impl->openButton.isEnabled());menu.addSeparator();menu.addItem(3,uiText("Save","保存")+"\tCtrl+S",impl->saveButton.isEnabled());menu.addItem(4,uiText("Save as…","另存为…")+"\tCtrl+Shift+S",impl->saveAsButton.isEnabled());menu.addSeparator();menu.addItem(5,uiText("Export…","导出…"),impl->exportMenu.isEnabled());
    menu.showMenuAsync(juce::PopupMenu::Options().withTargetComponent(&impl->fileMenu),[safe=juce::Component::SafePointer<MainComponent>(this)](int id){if(!safe)return;if(id==1)safe->newProject();if(id==2)safe->openProject();if(id==3)safe->saveProject(false);if(id==4)safe->saveProject(true);if(id==5)safe->showExportMenu();});
}

void MainComponent::chooseTrackColour(const juce::String& trackId)
{
    const auto state=session.snapshot();const auto found=std::find_if(state.tracks.begin(),state.tracks.end(),[&](const auto& t){return t.id==trackId;});if(found==state.tracks.end())return;
    juce::PopupMenu menu;menu.addSectionHeader(found->name+" / "+uiText("Colour","颜色"));
    const char* names[]{"Sage","Blue","Lavender","Rose","Sand","Moss","Teal","Clay","Slate","Plum"};
    for(int i=0;i<10;++i){juce::Image swatch(juce::Image::ARGB,18,18,true);juce::Graphics g(swatch);g.setColour(design::trackColour(design::trackPalette[i]));g.fillRect(2,2,14,14);menu.addItem(100+i,juce::String(names[i])+"  "+design::trackPalette[i],true,found->colour==design::trackPalette[i],swatch);}
    menu.addSeparator();menu.addItem(1,uiText("Reset colour","重置颜色"),true,found->colour.isEmpty());
    menu.showMenuAsync(juce::PopupMenu::Options().withMousePosition(),[safe=juce::Component::SafePointer<MainComponent>(this),state,trackId](int id){if(!safe||id==0||safe->session.snapshot().projectId!=state.projectId)return;const auto colour=id>=100&&id<110?juce::String(design::trackPalette[id-100]):juce::String();safe->showResult(safe->session.execute("set_track_colour",arguments({{"track_id",trackId},{"colour",colour}}),state.revision));safe->refreshSnapshot();});
}

void MainComponent::activateLibrary(const juce::String& kind,const juce::String& id,const juce::String& explicitTarget)
{
    if(kind=="browse"){if(id=="plugins")showPlugins();else chooseSource();return;}
    if(kind=="clip"){session.selectClip(id);refreshSnapshot();if(const auto* clip=impl->selectedClip())impl->arrangement.revealPosition(clip->timelineStart);impl->dock=Impl::Dock::source;resized();repaint();return;}
    auto state=session.snapshot();if(state.recording||state.recordingFinalizing||state.nativePending){showResult(juce::Result::fail("Finish recording or loading the sample before adding a device."));return;}
    bool instrument=kind=="instrument";juce::String name=id=="drum_rack"?"Drum Rack":id=="sampler"?"Sampler":id;
    if(kind=="plugin"){const auto it=std::find_if(state.pluginCatalog.begin(),state.pluginCatalog.end(),[&](const auto& p){return p.id==id;});if(it==state.pluginCatalog.end())return;instrument=it->isInstrument;name=it->name;}
    auto target=explicitTarget.isNotEmpty()?explicitTarget:state.selectedTrackId;
    auto track=std::find_if(state.tracks.begin(),state.tracks.end(),[&](const auto& t){return t.id==target;});
    if(track==state.tracks.end()||(instrument&&track->kind!="instrument")){
        auto result=session.execute("create_track",arguments({{"kind",instrument?"instrument":"audio"},{"name",instrument?name:juce::String("Audio track")}}),state.revision);if(result.failed()){showResult(result);return;}state=session.snapshot();target=state.selectedTrackId;
    }
    session.selectTrack(target);juce::var result;
    const auto status=session.execute(kind=="plugin"?"add_plugin":instrument?"add_native_instrument":"add_native_effect",kind=="plugin"?arguments({{"track_id",target},{"catalog_id",id}}):arguments({{"track_id",target},{"type",id}}),state.revision,&result);
    showResult(status);if(status.failed())return;refreshSnapshot();
    if(kind=="plugin"){impl->dock=Impl::Dock::track;impl->trackPanel.showDevices();resized();}
    else if(instrument)showNativeDevice(target);else showNativeEffect(target,result["device_id"].toString());
}
bool MainComponent::isInterestedInDragSource(const juce::DragAndDropTarget::SourceDetails& details){return bool(details.description["emusician_library"]);}
void MainComponent::itemDropped(const juce::DragAndDropTarget::SourceDetails& details)
{
    if(!isInterestedInDragSource(details))return;
    const auto target=impl->arrangement.trackAtPosition(impl->arrangement.getLocalPoint(this,details.localPosition));
    if(!impl->arrangement.getBounds().contains(details.localPosition)&&!impl->dockBounds.contains(details.localPosition))return;
    if(impl->arrangement.getBounds().contains(details.localPosition)&&target.isEmpty())return;
    activateLibrary(details.description["kind"].toString(),details.description["id"].toString(),target);
}
