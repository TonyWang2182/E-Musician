// Included inside emusician after MainWorkspace.inc. Own offline fixture only.
juce::Result MainComponent::runWorkspaceUISmoke(const juce::File& directory)
{
    if (directory.createDirectory().failed()) return juce::Result::fail("Cannot create workspace evidence directory.");
    auto report = std::make_unique<juce::DynamicObject>();
    report->setProperty("schema_version", 1);
    report->setProperty("status", "failed");
    report->setProperty("fixture", "Six synthetic MIDI tracks; real native EQ; no audio device, third-party plug-in or provider.");
    report->setProperty("physical_input", false);
    report->setProperty("physical_audio", false);
    report->setProperty("model_calls", 0);
    report->setProperty("agent_geometry_only", true);
    juce::Array<juce::var> checks;
    const auto originalLanguage = uiLanguageCode();
    const auto preference = ui_language_detail::preferenceFile();
    const bool preferenceExisted = preference.existsAsFile();
    const auto preferenceBefore = preference.loadFileAsString();
    juce::String failure;
    EngineSession fixture(false);
    MainComponent view(fixture);
    auto& p = *view.impl;
    const auto require = [&](bool passed, const juce::String& name) {
        checks.add(arguments({ {"name", name}, {"passed", passed} }));
        if(!passed||checks.size()%100==0)directory.getChildFile("workspace-last-check.txt").replaceWithText(name + (passed ? " passed" : " failed"));
        if (!passed) throw std::runtime_error(name.toStdString());
    };
    const auto capture = [&](juce::Component& component, const juce::String& name) {
        juce::MemoryOutputStream bytes;
        require(juce::PNGImageFormat().writeImageToStream(component.createComponentSnapshot(component.getLocalBounds(), true), bytes)
            && directory.getChildFile(name).replaceWithData(bytes.getData(), bytes.getDataSize()), "capture " + name);
    };
    const auto command = [&](const juce::String& name, const juce::var& args) {
        const auto result = fixture.execute(name, args, fixture.snapshot().revision);
        require(result.wasOk(), name + (result.failed() ? ": " + result.getErrorMessage() : juce::String()));
    };
    const auto topGeometry = [&](const juce::String& label) {
        std::vector<juce::Component*> controls { &p.fileMenu, &p.saveButton, &p.play, &p.stop, &p.record, &p.loop,
            &p.tempo, &p.metronome, &p.metronomeOptions, &p.countIn, &p.countInBars, &p.settings, &p.agentButton,
            &p.libraryButton, &p.importButton, &p.editMenu, &p.plugins, &p.separate, &p.analyze, &p.details,
            &p.undoButton, &p.redoButton, &p.rulerMode, &p.snap, &p.gridMode, &p.follow, &p.zoomOut, &p.zoomIn, &p.fit };
        for (std::size_t a = 0; a < controls.size(); ++a) if (controls[a]->isVisible()) {
            require(view.getLocalBounds().contains(controls[a]->getBounds()), label + " visible top control in bounds " + juce::String(int(a)));
            for (std::size_t b = a + 1; b < controls.size(); ++b) if (controls[b]->isVisible())
                require(!controls[a]->getBounds().intersects(controls[b]->getBounds()), label + " top controls separated " + juce::String(int(a)) + "/" + juce::String(int(b)));
        }
        require(p.countInBars.getRight() <= p.settings.getX() && p.follow.getRight() <= p.zoomOut.getX(), label + " transport and edit row clearance");
        require(view.getLocalBounds().contains(p.titleBounds) && !p.titleBounds.intersects(p.saveButton.getBounds()), label + " project title clearance");
    };
    try {
        const auto browserLifetime = WorkspaceBrowser::runActivationLifetimeSmoke(*report);
        require(browserLifetime.wasOk(), "library activation lifetime: " + browserLifetime.getErrorMessage());
        const auto pluginLifetime = PluginPanel::runLifetimeSmokeTest(fixture, *report);
        require(pluginLifetime.wasOk(), "plugin panel callback lifetime: " + pluginLifetime.getErrorMessage());
        const auto popupStyle = style_smoke::run(directory.getChildFile("popup-style"), p.look);
        require(popupStyle.wasOk(), "popup/dialog style: " + popupStyle.getErrorMessage());
        require(brand::logo().isValid(), "approved logo decoded");
        brand::Startup startup("0.11.0 / synthetic smoke");
        startup.setSize(640, 420); startup.start();
        juce::MessageManager::getInstance()->runDispatchLoopUntil(260);
        capture(startup, "ui-workspace-brand-startup.png");
        const auto deadline = juce::Time::getMillisecondCounterHiRes() + 2200.0;
        while (startup.isVisible() && juce::Time::getMillisecondCounterHiRes() < deadline)
            juce::MessageManager::getInstance()->runDispatchLoopUntil(30);
        require(!startup.isVisible(), "startup timer completes without project work");
        startup.start(); require(startup.keyPressed(juce::KeyPress(juce::KeyPress::escapeKey)) && !startup.isVisible(), "startup key handler dismisses");

        std::vector<juce::String> trackIds, clipIds;
        const char* names[] { "Fixture Drums", "Fixture Bass", "Fixture Keys", "Fixture Pad", "Fixture Lead", "Fixture Texture" };
        for (int t = 0; t < 6; ++t) {
            command("create_track", arguments({ {"kind", "instrument"}, {"name", names[t]} }));
            const auto trackId = fixture.snapshot().selectedTrackId; trackIds.push_back(trackId);
            command("set_track_colour", arguments({ {"track_id", trackId}, {"colour", design::trackPalette[t]} }));
            for (int c = 0; c < 2; ++c) {
                command("create_midi_clip", arguments({ {"track_id", trackId}, {"start_beats", double(c * 16)}, {"length_beats", 16.0} }));
                const auto clipId = fixture.snapshot().selectedClipId; clipIds.push_back(clipId);
                juce::Array<juce::var> notes;
                for (int n = 0; n < 8; ++n) notes.add(arguments({ {"id", "fixture-" + juce::String(t) + "-" + juce::String(c) + "-" + juce::String(n)},
                    {"pitch", 48 + t * 3 + n % 5}, {"start_beats", double(n * 2)}, {"length_beats", 1.5}, {"velocity", 72 + n * 4}, {"channel", 1} }));
                command("write_notes", arguments({ {"clip_id", clipId}, {"notes", notes} }));
            }
        }
        require(fixture.snapshot().tracks.size() == 6, "six actual synthetic project tracks");
        fixture.selectTrack(trackIds[2]); view.refreshSnapshot();
        view.activateLibrary("effect", "eq8", trackIds[2]);
        const auto withEQ = fixture.snapshot();
        require(p.dock == Impl::Dock::effect && p.dockEffect && p.dockEffect->isVisible(), "library opens real native EQ");
        const auto eqTrack = std::find_if(withEQ.tracks.begin(), withEQ.tracks.end(), [&](const auto& track) { return track.id == trackIds[2]; });
        require(eqTrack != withEQ.tracks.end() && !eqTrack->plugins.empty(), "library activation adds actual project device");
        const auto stableRevision = fixture.snapshot().revision;
        p.overview.onReveal(8.0); view.refreshSnapshot();
        require(fixture.snapshot().revision == stableRevision && fixture.snapshot().tracks.size() == 6, "overview navigation does not edit music");

        for (const auto language : { "en", "zh-CN" }) {
            require(view.setInterfaceLanguage(language, false).wasOk(), "temporary locale " + juce::String(language));
            for (const auto size : { juce::Point<int>(1000, 650), juce::Point<int>(1280, 800), juce::Point<int>(1440, 900) }) {
                p.agentVisible = false; p.inspectorVisible = false; p.libraryVisible = true; p.dockHeightUser = 0;
                view.setSize(size.x, size.y); view.resized(); view.refreshSnapshot();
                const auto label = juce::String(language) + " " + juce::String(size.x);
                topGeometry(label);
                require(p.dockEffect->getHeight() >= 212 && p.dockEffect->getWidth() >= 600, label + " native body minimum");
                require(!p.arrangement.getBounds().intersects(p.dockBounds), label + " arrangement and dock separated");
                if(size.x==1440)require(p.arrangement.getHeight()-54-16>=6*64,label+" six compact tracks visible above native dock");
                capture(view, "ui-workspace-brand-" + juce::String(size.x) + "x" + juce::String(size.y) + (juce::String(language) == "en" ? "" : "-zh") + ".png");
                p.agentVisible = true; view.resized();
                const int expectedWidth = size.x < 1180 ? size.x - 16 : size.x - 16 - juce::jlimit(320, 380, size.x / 4) - 8;
                require(p.workspace.getWidth() == expectedWidth && !p.libraryDisplayed && !p.inspectorDisplayed,
                    label + (size.x < 1180 ? " agent overlay preserves music width" : " agent dock reserves its column"));
                require(p.dockEffect->getHeight() >= 212 && p.dockEffect->getWidth() >= 600, label + " agent native body minimum");
                require(!p.libraryButton.isEnabled(), label + " temporarily hidden library has no inert enabled button");
                p.agentVisible = false; view.resized();
            }
        }
        view.setSize(1000, 650); p.dock = Impl::Dock::track; p.inspectorVisible = true; p.libraryVisible = true; p.dockHeightUser = 248;
        view.resized(); view.refreshSnapshot();
        require(!p.inspectorDisplayed && p.trackPanel.getWidth() >= 636 && p.trackPanel.getHeight() >= 212, "track I/O retains usable width with Details requested");
        p.libraryVisible = false; view.resized();
        require(view.keyPressed(juce::KeyPress('F', juce::ModifierKeys::ctrlModifier, 0)) && p.libraryDisplayed && p.browser.isVisible(), "Ctrl+F reveals actual library");
        require(fixture.snapshot().revision == stableRevision, "layout and library search do not mutate music");
        p.libraryButton.onClick(); require(!p.libraryDisplayed, "library button hides browser");
        p.libraryButton.onClick(); require(p.libraryDisplayed, "library button restores browser");
        fixture.selectClip(clipIds[4]); view.refreshSnapshot(); p.arrangement.selectClipIds({ clipIds[4] }); view.showPianoRoll();
        require(p.pianoRoll && p.pianoRoll->isVisible() && p.pianoRoll->clipId() == clipIds[4], "selected coloured clip opens piano projection");
        p.pianoRoll->keyPressed(juce::KeyPress('A', juce::ModifierKeys::ctrlModifier, 0));
        for (const auto language : { "en", "zh-CN" }) {
            view.setInterfaceLanguage(language, false); p.inspectorVisible = false; p.agentVisible = false; p.dockHeightUser = 280;
            view.setSize(1280, 800); view.resized();
            capture(view, "ui-workspace-brand-piano-1280x800-" + juce::String(language) + ".png");
            p.expandEditor.onClick();
            require(p.pianoExpanded && !p.arrangement.isVisible() && !p.browser.isVisible() && p.pianoRoll->getHeight() > 500, "expanded piano preserves useful canvas " + juce::String(language));
            capture(view, "ui-workspace-brand-piano-expanded-" + juce::String(language) + ".png");
            p.expandEditor.onClick();
            require(!p.pianoExpanded && p.arrangement.isVisible() && p.pianoRoll->selectedNoteCount() == 8, "return preserves piano selection " + juce::String(language));
        }
        for(const auto language:{"en","zh-CN"}){
            view.setInterfaceLanguage(language,false);p.inspectorVisible=false;p.agentVisible=false;p.libraryVisible=true;p.dockHeightUser=284;
            view.showGenerationDock();
            for(const auto size:{juce::Point<int>(1000,650),juce::Point<int>(1280,800)}){
                view.setSize(size.x,size.y);view.resized();view.refreshSnapshot();
                require(p.dockGeneration&&p.dockGeneration->isVisible()&&p.dockGeneration->getHeight()>=284,"generation dock remains usable");
                require(!p.arrangement.getBounds().intersects(p.dockBounds),"generation dock keeps arrangement visible");
                capture(view,"ui-generation-workspace-"+juce::String(size.x)+"x"+juce::String(size.y)+"-"+language+".png");
            }
        }
        require(fixture.snapshot().revision == stableRevision, "all presentation checks preserve project revision");
    } catch (const std::exception& error) {
        failure = juce::String::fromUTF8(error.what());
        juce::MemoryOutputStream bytes;
        if (view.getWidth() > 0 && view.getHeight() > 0 && juce::PNGImageFormat().writeImageToStream(view.createComponentSnapshot(view.getLocalBounds(), true), bytes))
            directory.getChildFile("ui-workspace-brand-failed.png").replaceWithData(bytes.getData(), bytes.getDataSize());
    }
    setUiLanguage(originalLanguage, false);
    if (preference.existsAsFile() != preferenceExisted || preference.loadFileAsString() != preferenceBefore)
        failure += " UI language preference file changed unexpectedly.";
    report->setProperty("status", failure.isEmpty() ? "passed" : "failed");
    report->setProperty("checks", checks); report->setProperty("error", failure);
    if (!directory.getChildFile("workspace-brand-report.json").replaceWithText(juce::JSON::toString(juce::var(report.release()), true)))
        return juce::Result::fail("Cannot write workspace smoke report.");
    return failure.isEmpty() ? juce::Result::ok() : juce::Result::fail(failure);
}
