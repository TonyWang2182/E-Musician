#pragma once
#include <juce_core/juce_core.h>

namespace emusician {
// Only the interactive launch path uses this parser; worker/test arguments are
// dispatched first by Application. Explorer must never silently ignore a file.
struct ProjectLaunchRequest {
    juce::File file;
    bool showAgent = false;
    juce::String error;
};
inline ProjectLaunchRequest parseProjectLaunch(const juce::StringArray& arguments)
{
    ProjectLaunchRequest request;
    bool explicitFile = false;
    juce::String file;
    for (const auto& raw : arguments) {
        const auto argument = raw.unquoted();
        if (argument.isEmpty()) {
            request.error = "Choose an E-musician .emproj project file.";
            return request;
        }
        if (argument == "--agent" && !explicitFile) { request.showAgent = true; continue; }
        if (argument == "--open-project" && !explicitFile && file.isEmpty()) { explicitFile = true; continue; }
        if (argument.startsWith("--") || file.isNotEmpty()) {
            request.error = "Open one .emproj file at a time.";
            return request;
        }
        file = argument;
        explicitFile = false;
    }
    if (explicitFile) { request.error = "--open-project requires a project file."; return request; }
    if (file.isNotEmpty()) {
        request.file = juce::File::isAbsolutePath(file) ? juce::File(file)
            : juce::File::getCurrentWorkingDirectory().getChildFile(file);
        if (!request.file.hasFileExtension("emproj"))
            request.error = "Choose an E-musician .emproj project file.";
    }
    return request;
}
}
