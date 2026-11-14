// Invoked only by --plugin-ui-test in an owned offline process. No control-stdio
// transport: exercise the actual Library and Add-plugin GUI callbacks.
juce::Result MainComponent::runInstalledPluginUISmoke(const juce::String& catalogId, const juce::File& directory)
{
    juce::DynamicObject::Ptr report = new juce::DynamicObject();
    report->setProperty("status", "running");
    report->setProperty("catalog_id", catalogId);
    report->setProperty("physical_audio", false);
    report->setProperty("editor_gestures_verified", false);
    report->setProperty("control_stdio", false);
    const auto write = [&] {
        directory.getChildFile("plugin-ui-report.json").replaceWithText(juce::JSON::toString(juce::var(report.get())));
    };
    const auto phase = [&](const juce::String& value) { report->setProperty("stage", value); write(); };
    const auto require = [](bool condition, const juce::String& message) {
        if (!condition) throw std::runtime_error(message.toStdString());
    };
    const auto command = [&](const juce::String& name, const juce::var& args) {
        const auto result = session.execute(name, args, session.snapshot().revision);
        require(result.wasOk(), name + ": " + result.getErrorMessage());
    };
    juce::String error;
    try {
        phase("validate_exact_instrument");
        const auto initial = session.snapshot();
        const auto descriptor = std::find_if(initial.pluginCatalog.begin(), initial.pluginCatalog.end(),
            [&](const auto& item) { return item.id == catalogId && item.isInstrument; });
        require(descriptor != initial.pluginCatalog.end(), "Exact catalog instrument unavailable.");
        report->setProperty("plugin_name", descriptor->name);
        command("set_master_gain", arguments({ {"gain_db", -60.0} }));
        command("create_track", arguments({ {"kind", "instrument"}, {"name", "Library native plug-in probe"} }));
        const auto libraryTrack = session.snapshot().selectedTrackId;
        const auto before = session.snapshot().revision;
        phase("library_activate_handler");
        activateLibrary("plugin", catalogId, libraryTrack);
        const auto added = session.snapshot();
        const auto track = std::find_if(added.tracks.begin(), added.tracks.end(), [&](const auto& t) { return t.id == libraryTrack; });
        require(added.revision == before + 1 && track != added.tracks.end() && track->plugins.size() == 1
                && !track->plugins.front().missing, "Library activation did not commit exactly one available slot/revision.");
        report->setProperty("library_real_activate_handler", true);
        const auto slot = track->plugins.front().id;
        phase("library_native_editor_open");
        command("open_plugin", arguments({ {"track_id", libraryTrack}, {"plugin_id", slot} }));
        juce::MessageManager::getInstance()->runDispatchLoopUntil(500);
        phase("library_remove_with_editor_open");
        command("remove_plugin", arguments({ {"track_id", libraryTrack}, {"plugin_id", slot} }));
        report->setProperty("library_native_editor_open_and_remove", true);
        command("create_track", arguments({ {"kind", "instrument"}, {"name", "Add-panel native plug-in probe"} }));
        const auto panelResult = PluginPanel::runInstalledPluginSmoke(session, catalogId, session.snapshot().selectedTrackId, *report, phase);
        require(panelResult.wasOk(), panelResult.getErrorMessage());
        phase("clear_owned_project");
        const auto cleared = session.newProject(session.snapshot().revision);
        require(cleared.wasOk(), cleared.getErrorMessage());
        require(session.snapshot().tracks.empty(), "Owned project did not clear after editor removal.");
        report->setProperty("status", "passed");
    } catch (const std::exception& failure) {
        error = failure.what(); report->setProperty("status", "failed"); report->setProperty("error", error);
    }
    write();
    return error.isEmpty() ? juce::Result::ok() : juce::Result::fail(error);
}
