// Offline process fixtures only: no model, GPU, network or user process.
namespace {
juce::Result runAnalysisWorkerProcessSmoke(juce::DynamicObject& report, const juce::File& directory)
{
    using namespace analysis_worker;
    int checks = 0;
    const auto check = [&](bool value, const juce::String& detail) {
        if (!value) throw std::runtime_error(detail.toStdString()); ++checks;
    };
    try {
        check(directory.createDirectory().wasOk(), "Create isolated process fixture directory");
        for (const auto* kind : {"separate", "transcribe", "beats", "chords"}) {
            const auto policy = Policy::forKind(kind);
            check(policy.admit({true, policy.minimumCommit, Policy::minimumPhysical}).wasOk(), "Memory boundary admitted");
            check(policy.admit({true, policy.minimumCommit-1, gib}).failed(), "Low commit refused");
            check(policy.admit({true, 8*gib, Policy::minimumPhysical-1}).failed(), "Low physical memory refused");
            check(juce::int64(policy.json()["minimum_available_commit_bytes"]) == juce::int64(policy.minimumCommit), "Policy contract uses bytes");
        }
        check(exitFailure(0xc0000005U).contains("access violation"), "Native fault includes concrete diagnosis");
        check(exitFailure(0xc0000017U).contains("memory"), "Native allocation failure includes concrete diagnosis");
        CriticalPressure pressure;
        const Resources low{true, Policy::criticalCommit-1, gib}, normal{true,gib,gib};
        check(!pressure.shouldStop(low,10) && !pressure.shouldStop(low,1009) && pressure.shouldStop(low,1010), "Critical pressure needs the full grace interval");
        check(!pressure.shouldStop(normal,1020) && !pressure.shouldStop(low,2000), "Recovered headroom resets the timer");
        check(!pressure.shouldStop({},3000) && !pressure.shouldStop(low,4000), "Unavailable probe is not fabricated critical pressure");
        check(validateAnalysisResult(juce::var(), "missing", "separate", 1.0).failed(), "Missing result never accepted as success");
#if JUCE_WINDOWS
        const auto python = juce::String(EMUSICIAN_AGENT_PYTHON);
        check(juce::File::isAbsolutePath(python) && juce::File(python).existsAsFile(), "Fixture Python exists");
        const auto wait = [&](Process& child, int milliseconds) {
            const auto end = juce::Time::getMillisecondCounterHiRes()+milliseconds;
            int turns = 0;
            while (child.isRunning() && juce::Time::getMillisecondCounterHiRes()<end) {
                juce::MessageManager::getInstance()->runDispatchLoopUntil(10); ++turns;
            }
            return turns;
        };
        {
            Process child;
            const auto log = directory.getChildFile("quoted argument process.log");
            const juce::String argument = "a space \"quote\" trailing\\";
            check(child.start({python,"-u","-c","import sys,time; print(sys.argv[1],flush=True); time.sleep(.15); sys.exit(37)",argument},log).wasOk(), "Start isolated nonzero fixture");
            const auto turns = wait(child,5000);
            check(!child.isRunning() && child.exitCode()==37, "Nonzero child exits within bound");
            check(turns>1 && log.loadFileAsString().contains(argument), "UI loop runs and argument/log isolation preserves exact text");
        }
        {
            Process child;
            // A deliberately invalid entry point on a fresh native thread.
            // Unlike a ctypes call on Python's own thread, this is an unhandled
            // Windows access violation; the private Job Object must suppress UI.
            const juce::String crash = "import ctypes,time; k=ctypes.WinDLL('kernel32',use_last_error=True); "
                "k.CreateThread.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ulong,ctypes.c_void_p]; "
                "k.CreateThread.restype=ctypes.c_void_p; assert k.CreateThread(None,0,ctypes.c_void_p(1),None,0,None); time.sleep(20)";
            check(child.start({python,"-u","-X","faulthandler","-c",crash},directory.getChildFile("native-crash.log")).wasOk(), "Start deliberate isolated native fault");
            wait(child,5000);
            check(!child.isRunning() && child.exitCode()==0xc0000005U, "Unhandled native fault exits without waiting for a dialog");
        }
        {
            Process child;
            const auto log = directory.getChildFile("cancel-tree.log");
            const juce::String spawn = "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)']); print(p.pid,flush=True); time.sleep(20)";
            check(child.start({python,"-u","-c",spawn},log).wasOk(), "Start isolated descendant fixture");
            const auto end = juce::Time::getMillisecondCounterHiRes()+5000;
            while (log.loadFileAsString().trim().isEmpty() && child.isRunning() && juce::Time::getMillisecondCounterHiRes()<end)
                juce::MessageManager::getInstance()->runDispatchLoopUntil(10);
            const DWORD pid = DWORD(log.loadFileAsString().trim().getIntValue());
            check(pid>0, "Fixture descendant created");
            HANDLE descendant = OpenProcess(SYNCHRONIZE,FALSE,pid);
            check(descendant!=nullptr, "Observe owned fixture descendant");
            child.terminate();
            const auto stopped = WaitForSingleObject(descendant,2000)==WAIT_OBJECT_0;
            CloseHandle(descendant);
            check(!child.isRunning() && stopped, "Cancellation kills only the owned process tree within bound");
        }
        {
            Process child;
            check(child.start({directory.getChildFile("missing-python.exe").getFullPathName()},directory.getChildFile("missing.log")).failed(), "Missing executable produces bounded error");
        }
        report.setProperty("analysis_worker_windows_native_crash_and_tree_cancel",true);
#endif
        report.setProperty("analysis_worker_process_fixture_checks", checks);
        return juce::Result::ok();
    } catch (const std::exception& error) { return juce::Result::fail(error.what()); }
}
}
