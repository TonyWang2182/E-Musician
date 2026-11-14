#include "EngineSession.h"
#include "MainComponent.h"
#include "Branding.h"
#include "WorkspaceLookAndFeel.h"
#include "PluginHost.h"
#include "ControlServer.h"
#include "ProjectLaunch.h"
#include <juce_gui_extra/juce_gui_extra.h>
#include <stdexcept>
#include <iostream>

namespace emusician {
class Application final : public juce::JUCEApplication {
public:
    const juce::String getApplicationName() override { return "E-musician"; }
    const juce::String getApplicationVersion() override { return EMUSICIAN_APPLICATION_VERSION; }
    bool moreThanOneInstanceAllowed() override
    {
        // CTest must execute its own process even when the interactive app is open.
        const auto args = juce::StringArray::fromTokens(getCommandLineParameters(), true);
        return args.contains("--workspace-smoke") || args.contains("--agent-sidebar-smoke") || args.contains("--smoke-test") || args.contains("--review-project") || args.contains("--control-stdio")
            || args.contains("--plugin-scan-worker") || args.contains("--render-worker") || args.contains("--performance-test")
            || args.contains("--control-output-probe-child") || args.contains("--plugin-notification-test") || args.contains("--production-test");
    }
    void initialise(const juce::String& commandLine) override
    {
        juce::LookAndFeel::setDefaultLookAndFeel(&workspaceLook);
        auto args = juce::StringArray::fromTokens(commandLine, true);
        for(auto& argument:args)argument=argument.unquoted();
        if(args.size()==1&&args.contains("--control-output-probe-child")){
            setApplicationReturnValue(ControlStdio::runOutputProbeChild());quit();return;
        }
        if(plugins::PluginHost::isScanWorker(args)){setApplicationReturnValue(plugins::PluginHost::runScanWorker(args));quit();return;}
        if(args.contains("--render-worker")){setApplicationReturnValue(EngineSession::runRenderWorker(args));quit();return;}
        const int smokeIndex = args.indexOf("--smoke-test");
        const int reviewIndex = args.indexOf("--review-project");
        const bool smoke = smokeIndex >= 0;
        const bool review = reviewIndex >= 0;
        if (args.contains("--workspace-smoke") || args.contains("--agent-sidebar-smoke") || (smoke && args.contains("--offline")) || args.contains("--production-test") || args.contains("--control-output-probe"))
            EngineSession::setOfflineTestMode(true);
        reviewMode = review;
        try {
            if(args.contains("--control-stdio")){
                controlStdio=std::make_unique<ControlStdio>();
                if(args.contains("--control-output-probe")){
                    const auto probe=controlStdio->runOutputProbe();require(probe.wasOk(),probe.getErrorMessage());
                }
            }else if(args.contains("--control-output-probe")||args.contains("--control-output-probe-child")){
                setApplicationReturnValue(2);quit();return;
            }
            if (args.contains("--production-test")) {
                if (args.size() != 2 || args[0] != "--production-test" || !juce::File::isAbsolutePath(args[1])) {
                    setApplicationReturnValue(2); quit(); return;
                }
                session = std::make_unique<EngineSession>(false);
                const auto result = session->runProductionSmokeTest(juce::File(args[1]));
                if (result.failed()) std::cerr << result.getErrorMessage() << std::endl;
                setApplicationReturnValue(result.wasOk() ? 0 : 1); quit(); return;
            }
            session = std::make_unique<EngineSession>();
            if(args.contains("--workspace-smoke")){
                if(args.size()!=3||args[0]!="--workspace-smoke"||!juce::File::isAbsolutePath(args[1])||args[2]!="--offline"){setApplicationReturnValue(2);quit();return;}
                const juce::File directory(args[1]);require(!directory.exists(),"Workspace smoke output must be fresh");require(directory.createDirectory().wasOk(),"Create workspace smoke output");
                window=std::make_unique<Window>(*session,false);
                after(100,directory,[this,directory]{
                    auto report=std::make_unique<juce::DynamicObject>();const auto engine=session->runWorkspaceEngineSmokeTest(*report,directory.getChildFile("engine"));
                    directory.getChildFile("workspace-engine-report.json").replaceWithText(juce::JSON::toString(juce::var(report.release())));require(engine.wasOk(),engine.getErrorMessage());
                    const auto ui=static_cast<MainComponent*>(window->getContentComponent())->runWorkspaceUISmoke(directory);require(ui.wasOk(),ui.getErrorMessage());
                    setApplicationReturnValue(0);quit();
                });return;
            }
            const int agentSmoke=args.indexOf("--agent-sidebar-smoke");
            if(agentSmoke>=0){
                if(args.size()!=3||agentSmoke!=0||!juce::File::isAbsolutePath(args[1])||args[2]!="--offline"){setApplicationReturnValue(2);quit();return;}
                const juce::File directory(args[1]);
                require(!directory.exists(),"Agent smoke directory must be fresh");
                require(directory.createDirectory().wasOk(),"Could not create Agent smoke directory");
                window=std::make_unique<Window>(*session,false);
                window->setTopLeftPosition(-3000,-3000);window->setVisible(true);
                after(100,directory,[this,directory]{
                    const auto result=static_cast<MainComponent*>(window->getContentComponent())->runAgentSidebarSmokeTest(directory);
                    if(result.failed())std::cerr<<result.getErrorMessage()<<std::endl;
                    setApplicationReturnValue(result.wasOk()?0:1);quit();
                });
                return;
            }
            const int notificationTest=args.indexOf("--plugin-notification-test");
            if(notificationTest>=0){
                if(notificationTest+2>=args.size()){setApplicationReturnValue(2);quit();return;}
                const auto result=session->runPluginNotificationSmoke(juce::File(args[notificationTest+1]),args[notificationTest+2]);
                if(result.failed())std::cerr<<result.getErrorMessage()<<std::endl;
                setApplicationReturnValue(result.wasOk()?0:1);quit();return;
            }
            if(args.contains("--control-stdio")){
                if(args.contains("--show"))window=std::make_unique<Window>(*session,true);
                control=std::make_unique<ControlServer>(*session,*controlStdio,[this]{quit();});return;
            }
            const int performanceIndex=args.indexOf("--performance-test");
            if(performanceIndex>=0){
                if(performanceIndex+2>=args.size()){setApplicationReturnValue(2);quit();return;}
                const juce::File directory(args[performanceIndex+1].unquoted());const int seconds=args[performanceIndex+2].getIntValue();
                window=std::make_unique<Window>(*session,args.contains("--show"));
                const auto result=session->runPerformanceProbe(directory,seconds);require(result.wasOk(),result.getErrorMessage());
                waitForPerformance(directory,seconds+180);return;
            }
            window = std::make_unique<Window>(*session, !smoke && !review, !smoke && !review);
            if (!smoke && !review) dispatchProjectLaunch(args);
            if (smoke) {
                if (smokeIndex + 1 >= args.size()) { setApplicationReturnValue(2); quit(); return; }
                if (smokeIndex + 2 >= args.size()) { setApplicationReturnValue(2); quit(); return; }
                const juce::File directory(args[smokeIndex + 1].unquoted());
                const juce::File fixtures(args[smokeIndex + 2].unquoted());
                after(100, directory, [this, directory, fixtures] {
                    require(directory.createDirectory().wasOk(), "Could not create smoke directory");
                    capture(directory, "ui-empty-", { 1280, 800 });
                    const auto result = session->runOfflineSmokeTest(directory);
                    require(result.wasOk(), result.getErrorMessage());
                    const auto projectResult = session->runProjectSmokeTest(directory, fixtures);
                    require(projectResult.wasOk(), projectResult.getErrorMessage());
                    const auto clipResult = session->runClipSmokeTest(directory);
                    require(clipResult.wasOk(), clipResult.getErrorMessage());
                    const auto dawResult=session->runDawSmokeTest(directory,fixtures);
                    require(dawResult.wasOk(),dawResult.getErrorMessage());
                    const auto productionResult=session->runProductionSmokeTest(directory);
                    require(productionResult.wasOk(),productionResult.getErrorMessage());
                    // Allow normal UI timers and thumbnail work before exercising Space.
                    after(400, directory, [this, directory] { verifyTransport(directory); });
                });
            } else if (review) {
                if (reviewIndex + 2 >= args.size()) { setApplicationReturnValue(2); quit(); return; }
                const juce::File project(args[reviewIndex + 1].unquoted());
                const juce::File directory(args[reviewIndex + 2].unquoted());
                after(100, directory, [this, project, directory] {
                    require(!directory.exists(), "Review output directory must be fresh");
                    require(directory.createDirectory().wasOk(), "Could not create review directory");
                    const auto result = session->openProject(project, session->snapshot().revision);
                    require(result.wasOk(), result.getErrorMessage());
                    // A read-only native preview: no save, no edits, no audio playback.
                    waitForProjectPreview(directory, 600);
                });
            }
        } catch (const std::exception& e) {
            std::cerr << e.what() << std::endl;
            if (!smoke && !review && !args.contains("--workspace-smoke") && !args.contains("--agent-sidebar-smoke") && !args.contains("--control-stdio") && !args.contains("--production-test"))
                juce::AlertWindow::showMessageBoxAsync(juce::MessageBoxIconType::WarningIcon, "Unable to start", e.what());
            setApplicationReturnValue(1);
            quit();
        }
    }
    void shutdown() override
    {
        control.reset(); window.reset(); session.reset(); controlStdio.reset();
        juce::LookAndFeel::setDefaultLookAndFeel(nullptr);
    }
    void systemRequestedQuit() override
    {
        if (window) static_cast<MainComponent*>(window->getContentComponent())->requestClose([this] { quit(); });
        else quit();
    }
    void anotherInstanceStarted(const juce::String& commandLine) override
    {
        if (window) {
            window->setVisible(true); window->toFront(true);
            dispatchProjectLaunch(juce::StringArray::fromTokens(commandLine, true));
        }
    }
private:
    void dispatchProjectLaunch(const juce::StringArray& args)
    {
        const auto request = parseProjectLaunch(args);
        if (request.error.isNotEmpty()) {
            juce::AlertWindow::showMessageBoxAsync(juce::MessageBoxIconType::WarningIcon,
                                                  "Open project", request.error);
            return;
        }
        auto* content = window ? static_cast<MainComponent*>(window->getContentComponent()) : nullptr;
        if (!content) return;
        if (request.showAgent) content->showAgent();
        if (request.file != juce::File()) {
            // Defer until native startup and the single-instance handoff have
            // returned. The UI's normal unsaved/recording guard owns transition.
            juce::MessageManager::callAsync([safe = juce::Component::SafePointer<MainComponent>(content), file = request.file] {
                if (safe) safe->openProjectFile(file);
            });
        }
    }
    // Application-owned: unattached popup menus and async alerts use this theme.
    // It outlives all windows, controls and plug-in teardown.
    design::WorkspaceLookAndFeel workspaceLook;
    // Declared first and explicitly reset last: plugin teardown may log stdout.
    std::unique_ptr<ControlStdio> controlStdio;
    std::unique_ptr<ControlServer> control;
    void waitForPerformance(const juce::File& directory,int remaining){
        juce::Timer::callAfterDelay(1000,[this,directory,remaining]{
            auto report=directory.getChildFile("performance-report.json");
            if(report.existsAsFile()){auto data=juce::JSON::parse(report);const auto status=data.getProperty("status","").toString();setApplicationReturnValue(status=="passed"||(status=="unsupported"&&data.getProperty("actual_device_status","").toString()=="passed")?0:1);quit();}
            else if(remaining<=0){std::cerr<<"Performance probe timed out"<<std::endl;setApplicationReturnValue(1);quit();}
            else waitForPerformance(directory,remaining-1);
        });
    }
    static void require(bool condition, const juce::String& message)
    {
        if (!condition) throw std::runtime_error(message.toStdString());
    }
    void failSmoke(const juce::File& directory, const juce::String& message)
    {
        if (reviewMode) {
            // A rejected preview directory may belong to the user. Never put
            // diagnostics there until ownership is proven; stderr is sufficient.
            std::cerr << message << std::endl;
        } else {
            directory.createDirectory();
            directory.getChildFile("failure.txt").replaceWithText(message);
        }
        setApplicationReturnValue(1);
        quit();
    }
    void after(int milliseconds, const juce::File& directory, std::function<void()> action)
    {
        juce::Timer::callAfterDelay(milliseconds, [this, directory, action = std::move(action)] {
            // Pinned JUCE deletes its one-shot timer only after the callback.
            // A job test pumps the message loop; running it inside that timer
            // can re-enter the entire smoke suite and delete the timer twice.
            // Return from the timer first, then dispatch the one-shot action.
            juce::MessageManager::callAsync([this, directory, action] {
                try { action(); }
                catch (const std::exception& e) { failSmoke(directory, e.what()); }
                catch (...) { failSmoke(directory, "Unknown smoke test exception"); }
            });
        });
    }
    void capture(const juce::File& directory, const juce::String& prefix, juce::Point<int> size)
    {
        auto* content = window->getContentComponent();
        content->setSize(size.x, size.y);
        const auto image = content->createComponentSnapshot(content->getLocalBounds());
        auto file = directory.getChildFile(prefix + juce::String(size.x) + "x" + juce::String(size.y) + ".png");
        auto output = file.createOutputStream();
        if (output) { output->setPosition(0); output->truncate(); }
        require(output != nullptr && juce::PNGImageFormat().writeImageToStream(image, *output), "Could not write UI capture");
    }
    void waitForProjectPreview(const juce::File& directory, int attempts)
    {
        after(100, directory, [this, directory, attempts] {
            auto* content = static_cast<MainComponent*>(window->getContentComponent());
            if (!content->arrangementWaveformsReady()) {
                require(attempts > 0, "Project waveform preparation did not finish within 60 seconds");
                waitForProjectPreview(directory, attempts - 1);
                return;
            }
            const auto state = session->snapshot();
            require(!state.dirty && !state.playing, "Read-only preview changed the project or started playback");
            capture(directory, "ui-project-", { 1280, 800 });
            capture(directory, "ui-project-", { 1000, 650 });
            auto report = std::make_unique<juce::DynamicObject>();
            report->setProperty("status", "passed");
            report->setProperty("scope", "Read-only saved-project load and native arrangement captures; no save or playback");
            report->setProperty("tracks", static_cast<int>(state.tracks.size()));
            report->setProperty("duration_seconds", state.duration);
            report->setProperty("waveforms_complete", true);
            report->setProperty("dirty", state.dirty);
            report->setProperty("playing", state.playing);
            require(directory.getChildFile("preview-report.json").replaceWithText(juce::JSON::toString(juce::var(report.release()))),
                    "Could not write preview report");
            setApplicationReturnValue(0);
            quit();
        });
    }
    void finishSmoke(const juce::File& directory, bool deviceChecked)
    {
        auto report = std::make_unique<juce::DynamicObject>();
        report->setProperty("status", deviceChecked ? "passed" : "skipped");
        report->setProperty("scope", "short transport-clock check; no loopback, physical listening or performance claim");
        report->setProperty("reason", deviceChecked ? "play/pause/resume/end/loop/stop observed" : "No output device available");
        report->setProperty("test_gain_db", -60);
        require(directory.getChildFile("transport-report.json").replaceWithText(juce::JSON::toString(juce::var(report.release()))),
                "Could not save transport report");
        after(150, directory, [this, directory] {
            const auto result = static_cast<MainComponent*>(window->getContentComponent())->runArrangementSmokeTest(directory);
            require(result.wasOk(), result.getErrorMessage());
            capture(directory, "ui-", { 1280, 800 });
            capture(directory, "ui-", { 1000, 650 });
            setApplicationReturnValue(0);
            quit();
        });
    }
    void pressSpace()
    {
        auto* content = static_cast<MainComponent*>(window->getContentComponent());
        require(content->keyPressed(juce::KeyPress(juce::KeyPress::spaceKey)), "Space did not invoke transport");
    }
    void verifyTransport(const juce::File& directory)
    {
        if (!session->snapshot().deviceAvailable) { finishSmoke(directory, false); return; }
        session->setGain(-60.0f);
        session->stop();
        pressSpace();
        after(400, directory, [this, directory] {
            auto state = session->snapshot();
            require(state.playing && state.position > 0.05, "Playback clock did not advance");
            pressSpace();
            const double pausedPosition = session->snapshot().position;
            after(150, directory, [this, directory, pausedPosition] {
                auto state = session->snapshot();
                require(!state.playing && std::abs(state.position - pausedPosition) < 0.04, "Pause did not hold position");
                pressSpace();
                after(250, directory, [this, directory, pausedPosition] {
                    auto state = session->snapshot();
                    require(state.playing && state.position > pausedPosition + 0.05, "Resume did not advance");
                    session->stop();
                    session->seek(session->snapshot().duration - 0.15);
                    session->togglePlay();
                    after(400, directory, [this, directory] {
                        auto state = session->snapshot();
                        require(!state.playing && std::abs(state.position - state.duration) < 0.02, "Playback did not stop at source end");
                        session->setLoop(true);
                        session->seek(state.duration - 0.15);
                        session->togglePlay();
                        after(400, directory, [this, directory] {
                            const auto state = session->snapshot();
                            require(state.playing && state.looping && state.position < 1.0, "Loop did not wrap");
                            session->stop();
                            require(!session->snapshot().playing && session->snapshot().position == 0.0, "Stop did not reset");
                            session->setLoop(false);
                            session->setGain(-6.0f);
                            finishSmoke(directory, true);
                        });
                    });
                });
            });
        });
    }
    class Window final : public juce::DocumentWindow {
    public:
        Window(EngineSession& session, bool visible, bool showStartup=false)
            : DocumentWindow("E-musician " EMUSICIAN_APPLICATION_VERSION " - Audio workspace", juce::Colours::white, allButtons)
        {
            setUsingNativeTitleBar(true);
            setIcon(brand::logo());
            setContentOwned(new MainComponent(session), true);
            setResizable(true, false);
            setResizeLimits(1000, 650, 2400, 1600);
            centreWithSize(1440, 900);
            addChildComponent(startup);
            if(getContentComponent())startup.setBounds(getContentComponent()->getBounds());
            setVisible(visible);
            if(showStartup)startup.start();
        }
        void resized() override {DocumentWindow::resized();if(getContentComponent())startup.setBounds(getContentComponent()->getBounds());}
        void closeButtonPressed() override { juce::JUCEApplication::getInstance()->systemRequestedQuit(); }
    private:
        brand::Startup startup {EMUSICIAN_APPLICATION_VERSION};
    };
    std::unique_ptr<EngineSession> session;
    std::unique_ptr<Window> window;
    bool reviewMode = false;
};
}
START_JUCE_APPLICATION(emusician::Application)
