#pragma once

#include "ProjectStorage.h"
#include <tracktion_engine/tracktion_engine.h>
#include <memory>
#include <vector>

namespace emusician::plugins {

struct CatalogEntry {
    juce::String id;
    juce::PluginDescription description;
    bool available = true;
    juce::String error;
};

struct ScanSnapshot {
    bool running = false, cancelled = false;
    int completed = 0, total = 0, failures = 0;
    juce::String currentModule, status;
};

// Native editors are owned by Tracktion's PluginWindowState; close them before
// removing the corresponding plugin or destroying its Edit.
std::unique_ptr<tracktion::UIBehaviour> createUIBehaviour();

// Control-thread facade. Only scanAsync/cancelScan/catalog/scanSnapshot are
// cross-thread safe. Scanning never loads a module in the parent process.
class PluginHost final {
public:
    explicit PluginHost(tracktion::Engine&);
    ~PluginHost();

    static juce::FileSearchPath defaultSearchPaths();
    juce::Result scanAsync(const juce::FileSearchPath&, const juce::Array<juce::File>& modules = {});
    void cancelScan();
    ScanSnapshot scanSnapshot() const;
    std::vector<CatalogEntry> catalog() const;
    bool getDescription(const juce::String& catalogId, juce::PluginDescription&) const;

    static bool isScanWorker(const juce::StringArray& arguments);
    // Call on the application's message thread before creating Engine/window.
    // Returns an exit code. The worker needs normal JUCE GUI initialisation.
    static int runScanWorker(const juce::StringArray& arguments);

    static juce::String catalogId(const juce::PluginDescription&);
    static storage::StoredPlugin describe(const juce::PluginDescription&);
    // Missing/failed plugins return nullptr and an error; caller retains its
    // StoredPlugin as a placeholder, including the original state bytes.
    // Positional parameter snapshots require the saved nonempty version to
    // match the scanned version. Cross-version parameter migration is unsupported.
    tracktion::Plugin::Ptr instantiate(tracktion::Edit&, const storage::StoredPlugin&, juce::Result&);
    // flushState=false updates metadata/enabled only, preserving cached state.
    static juce::Result capture(tracktion::Plugin&, storage::StoredPlugin&, bool flushState);
    // Cache on the existing ValueTree with no UndoManager before removal. Undo
    // retains those bytes even after Tracktion releases the actual instance.
    // An invalid slot is allowed for newly instantiated, not-yet-inserted plugins.
    static juce::Result cacheStateForUndo(tracktion::Plugin&, juce::ValueTree slot = {});
    // EngineBehaviour hooks: check identity/version before load, avoid deferred
    // VST3 program selection over native state, and restore parameter-only state.
    static bool matchesCachedIdentity(const tracktion::ExternalPlugin&);
    static juce::Result restoreCachedProgramIfNeeded(tracktion::ExternalPlugin&);
    static juce::Result showEditor(tracktion::Plugin&);
    static void closeEditor(tracktion::Plugin&);
    static void closeAllEditors(tracktion::Edit&);
    // Watch only installed live slots. Watchers retain the plugin until removed.
    // Detach before deleting/replacing its Edit or force-reinitialising a plugin.
    void watchPlugin(const tracktion::Plugin::Ptr&, const juce::String& id);
    // Immediately after structural Undo/Redo, before refreshing watchers. Only
    // detached instances are captured; ordinary parameter/note Undo captures none.
    // On failure the caller must reverse its Undo/Redo while watchers retain them.
    juce::Result cacheDetachedPluginsForUndo(tracktion::Edit&);
    void unwatchPlugin(const juce::String& id);
    void detachEdit(tracktion::Edit&);
    std::vector<juce::String> takeChangedPluginIds();
    // Snapshot/close guards can see pending edits before the timer drains them.
    // This never consumes notifications or changes the project revision.
    bool hasPendingChanges() const;
    // Monotonic meaningful parameter/non-parameter change counter. Reading is
    // message-thread only; listener updates are bounded and lock-free.
    std::uint64_t changeGeneration(const juce::String& id) const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl;
    JUCE_DECLARE_NON_COPYABLE(PluginHost)
};
}
