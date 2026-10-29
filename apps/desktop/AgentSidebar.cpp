#include "AgentSidebar.h"
#include <array>
#include <atomic>
#include <cstring>
#if JUCE_WINDOWS
 #ifndef WIN32_LEAN_AND_MEAN
  #define WIN32_LEAN_AND_MEAN
 #endif
 #ifndef NOMINMAX
  #define NOMINMAX
 #endif
 #include <winsock2.h>
#else
 #include <cerrno>
 #include <fcntl.h>
#endif

namespace emusician {
namespace {
juce::var obj(std::initializer_list<std::pair<juce::Identifier,juce::var>> values) {
    auto* o = new juce::DynamicObject();
    for (const auto& [key, value] : values) o->setProperty(key, value);
    return o;
}
juce::String secureToken() {
    std::array<unsigned char,32> bytes{};
   #if JUCE_WINDOWS
    // UUIDs use JUCE's non-cryptographic Random. A bearer capability needs OS entropy.
    juce::DynamicLibrary library("advapi32.dll");
    using Generate = BOOLEAN (WINAPI*)(PVOID, ULONG);
    const auto generate = reinterpret_cast<Generate>(library.getFunction("SystemFunction036"));
    if (generate == nullptr || !generate(bytes.data(), ULONG(bytes.size()))) return {};
   #else
    const auto source = juce::File("/dev/urandom").createInputStream();
    if (source == nullptr || source->read(bytes.data(), int(bytes.size())) != int(bytes.size())) return {};
   #endif
    return juce::String::toHexString(bytes.data(), int(bytes.size()), 0);
}
bool nonBlocking(juce::StreamingSocket& socket) {
   #if JUCE_WINDOWS
    u_long enabled = 1;
    return ::ioctlsocket(SOCKET(socket.getRawSocketHandle()), FIONBIO, &enabled) == 0;
   #else
    const int flags = ::fcntl(socket.getRawSocketHandle(), F_GETFL, 0);
    return flags >= 0 && ::fcntl(socket.getRawSocketHandle(), F_SETFL, flags | O_NONBLOCK) == 0;
   #endif
}
bool wouldBlock() {
   #if JUCE_WINDOWS
    return ::WSAGetLastError() == WSAEWOULDBLOCK;
   #else
    return errno == EWOULDBLOCK || errno == EAGAIN;
   #endif
}
bool sameSecret(const juce::String& supplied, const juce::String& expected) {
    const auto a = supplied.toUTF8(); const auto b = expected.toUTF8();
    const auto length = expected.getNumBytesAsUTF8();
    if (supplied.getNumBytesAsUTF8() != length) return false;
    unsigned int difference = 0;
    for (size_t i = 0; i < length; ++i) difference |= unsigned(a[i]) ^ unsigned(b[i]);
    return difference == 0;
}
bool validLocalUrl(const juce::String& url) {
    if (url.length() > 512) return false;
    const juce::URL parsed(url);
    const auto token = url.fromFirstOccurrenceOf("#token=", false, false);
    return parsed.getScheme() == "http" && parsed.getDomain() == "127.0.0.1"
        && parsed.getPort() > 0 && parsed.getPort() <= 65535
        && token.length() >= 32 && token.length() <= 128
        && token.containsOnly("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_");
}
class Service final : public juce::Thread {
public:
    explicit Service(std::function<juce::var(const juce::var&)> fn)
        : Thread("Agent control"), dispatch(std::move(fn)) {}
    ~Service() override {
        stopOwnedWorker();
        // Every socket operation is nonblocking, waits are <=50ms and child wait <=1s.
        // Join cooperatively; never force-kill a thread holding JUCE/CRT resources.
        stopThread(-1);
    }
    juce::String url() const { const juce::ScopedLock lock(stateLock); return readyUrl; }
    juce::String status() const { const juce::ScopedLock lock(stateLock); return detail; }
    void stopOwnedWorker() { alive->store(false); signalThreadShouldExit(); notify(); }
private:
    struct Pending { juce::WaitableEvent done; juce::var result; std::atomic<bool> abandoned{false}; };
    std::shared_ptr<std::atomic<bool>> alive = std::make_shared<std::atomic<bool>>(true);
    std::function<juce::var(const juce::var&)> dispatch;
    mutable juce::CriticalSection stateLock;
    juce::String readyUrl, detail = "Starting local assistant...";
    void setStatus(const juce::String& value) { const juce::ScopedLock lock(stateLock); detail = value; }
    bool send(juce::StreamingSocket& socket, const juce::var& value) {
        const auto text = juce::JSON::toString(value, true) + "\n";
        const auto* bytes = text.toRawUTF8(); const int size = int(text.getNumBytesAsUTF8());
        if (size > 1024 * 1024) return false;
        int offset = 0; const auto deadline = juce::Time::getMillisecondCounterHiRes() + 10000;
        while (offset < size && !threadShouldExit() && juce::Time::getMillisecondCounterHiRes() < deadline) {
            const int ready = socket.waitUntilReady(false, 50);
            if (ready < 0) return false;
            if (ready == 0) continue;
            const int count = socket.write(bytes + offset, juce::jmin(4096, size - offset));
            if (count < 0 && wouldBlock()) continue;
            if (count <= 0) return false;
            offset += count;
        }
        return offset == size;
    }
    void run() override {
        juce::StreamingSocket listener;
        if (!listener.createListener(0, "127.0.0.1") || !nonBlocking(listener)) {
            setStatus("Unable to start local Agent connection."); return;
        }
        const auto root = juce::File::getSpecialLocation(juce::File::userApplicationDataDirectory)
            .getChildFile("E-musician").getChildFile("agent").getChildFile("sessions");
        if (root.createDirectory().failed()) { setStatus("Unable to create local Agent session."); return; }
        const auto id = juce::Uuid().toString().removeCharacters("-");
        const auto token = secureToken();
        if (token.isEmpty()) { setStatus("Unable to generate a secure Agent session."); return; }
        const auto input = root.getChildFile(id + ".json"), readyFile = root.getChildFile(id + ".ready.json");
        const auto config = obj({{"protocol", 1}, {"port", listener.getBoundPort()}, {"token", token}, {"ready_path", readyFile.getFullPathName()}});
        if (!input.replaceWithText(juce::JSON::toString(config))) { setStatus("Unable to prepare Agent session."); return; }
        juce::ChildProcess child;
        const juce::File python(EMUSICIAN_AGENT_PYTHON);
        auto script = juce::File(EMUSICIAN_SOURCE_DIR).getChildFile("scripts/run_agent.py");
        const auto packaged = juce::File::getSpecialLocation(juce::File::currentExecutableFile)
            .getSiblingFile("agent-runtime").getChildFile("run_agent.py");
        if (packaged.existsAsFile()) script = packaged;
        const bool started = !threadShouldExit() && python.existsAsFile() && script.existsAsFile()
            && child.start(juce::StringArray{python.getFullPathName(), script.getFullPathName(), "--serve", "--embedded-session", input.getFullPathName()}, 0);
        if (!started) { input.deleteFile(); setStatus("Agent could not start. Check the Python runtime and retry."); return; }
        std::unique_ptr<juce::StreamingSocket> client;
        juce::MemoryBlock pendingBytes;
        bool authenticated = false;
        double acceptedAt = 0;
        const auto start = juce::Time::getMillisecondCounterHiRes();
        while (!threadShouldExit()) {
            const auto now = juce::Time::getMillisecondCounterHiRes();
            if (!child.isRunning()) { setStatus("Assistant stopped. Your DAW remains open; Retry starts a new assistant."); break; }
            if (url().isEmpty() && now - start > 45000) { setStatus("Assistant connection timed out. Retry is available."); break; }
            if (authenticated && readyFile.existsAsFile() && url().isEmpty()) {
                if (readyFile.getSize() > 4096) { setStatus("Invalid Agent ready response."); break; }
                const auto info = juce::JSON::parse(readyFile);
                const auto address = info["url"].toString();
                if (!validLocalUrl(address)) { setStatus("Invalid Agent ready address."); break; }
                { const juce::ScopedLock lock(stateLock); readyUrl = address; detail = "Loading assistant..."; }
                readyFile.deleteFile();
            }
            if (!client) {
                if (listener.waitUntilReady(true, 50) > 0) {
                    client.reset(listener.waitForNextConnection());
                    if (client && !nonBlocking(*client)) { client->close(); client.reset(); }
                    acceptedAt = now;
                }
                continue;
            }
            if (!authenticated && now - acceptedAt > 5000) {
                client->close(); client.reset(); pendingBytes.reset(); continue;
            }
            const auto readable = client->waitUntilReady(true, 50);
            if (readable < 0) { setStatus("Assistant connection closed. Retry is available."); break; }
            if (readable == 0) continue;
            char buffer[4096]; const int count = client->read(buffer, sizeof(buffer), false);
            if (count <= 0) {
                if (!authenticated) { client->close(); client.reset(); pendingBytes.reset(); continue; }
                setStatus("Assistant disconnected. Your DAW remains open; Retry is available."); break;
            }
            pendingBytes.append(buffer, size_t(count));
            if (pendingBytes.getSize() > 1024 * 1024) { setStatus("Agent request exceeded its size limit."); break; }
            const auto* data = static_cast<const char*>(pendingBytes.getData());
            const auto* newline = static_cast<const char*>(std::memchr(data, '\n', pendingBytes.getSize()));
            if (!newline) continue;
            const int length = int(newline - data);
            const auto text = juce::String::fromUTF8(data, length);
            pendingBytes.removeSection(0, size_t(length + 1));
            if (pendingBytes.getSize() != 0) { setStatus("Agent protocol ordering error."); break; }
            const auto request = juce::JSON::parse(text);
            if (!authenticated) {
                if (!request.isObject() || !request["auth"].isString() || !sameSecret(request["auth"].toString(), token)) {
                    client->close(); client.reset(); pendingBytes.reset(); continue;
                }
                authenticated = true;
                listener.close();
                if (!send(*client, obj({{"status", "authenticated"}}))) break;
                continue;
            }
            if (!request.isObject()) { setStatus("Invalid Agent request."); break; }
            auto operation = std::make_shared<Pending>();
            auto execute = dispatch;
            const auto lifetime = alive;
            const bool queued = juce::MessageManager::callAsync([operation, lifetime, execute, request] {
                if (!lifetime->load() || operation->abandoned.load()) return;
                try { operation->result = execute(request); }
                catch (...) { operation->result = obj({{"request_id", request["request_id"]}, {"status", "failed"}, {"error", "Native Agent request failed."}}); }
                operation->done.signal();
            });
            if (!queued) { operation->abandoned = true; setStatus("Native Agent dispatcher stopped."); break; }
            const auto deadline = juce::Time::getMillisecondCounterHiRes() + 20000;
            bool completed = false;
            while (!threadShouldExit() && juce::Time::getMillisecondCounterHiRes() < deadline)
                if (operation->done.wait(25)) { completed = true; break; }
            if (!completed) { operation->abandoned = true; setStatus("Agent request timed out. Check the project before retrying."); break; }
            if (!send(*client, operation->result)) { setStatus("Agent reply connection closed."); break; }
        }
        alive->store(false);
        listener.close(); if (client) client->close();
        if (child.isRunning()) { child.kill(); child.waitForProcessToFinish(1000); }
        input.deleteFile(); readyFile.deleteFile();
    }
};
class Browser final : public juce::WebBrowserComponent {
public:
    explicit Browser(std::function<void()> close, std::function<void(bool)> focus)
      : WebBrowserComponent(Options().withBackend(Options::Backend::webview2)
          .withKeepPageLoadedWhenBrowserIsHidden().withNativeIntegrationEnabled()
          .withWinWebView2Options(Options::WinWebView2().withUserDataFolder(
              juce::File::getSpecialLocation(juce::File::userApplicationDataDirectory).getChildFile("E-musician/agent/webview")))
          .withEventListener("agentClose", [close](const juce::var&) { if (close) close(); })
          .withEventListener("agentFocus", [focus](const juce::var& event) {
              // This is only a focus hint, never text or a music mutation.
              if (event.isObject() && event.getDynamicObject()->getProperties().size() == 1
                  && event["focused"].isBool() && focus) focus(bool(event["focused"]));
          })) {}
    juce::String origin;
    bool pageLoaded = false, failed = false;
    bool pageAboutToLoad(const juce::String& address) override {
        const bool allowed = address == "about:blank" || (!origin.isEmpty() && (address == origin || address.startsWith(origin + "/")));
        if (allowed) { pageLoaded = false; failed = false; }
        return allowed;
    }
    void pageFinishedLoading(const juce::String& address) override {
        pageLoaded = !origin.isEmpty() && (address == origin || address.startsWith(origin + "/"));
    }
    bool pageLoadHadNetworkError(const juce::String&) override { pageLoaded = false; failed = true; return false; }
    void newWindowAttemptingToLoad(const juce::String&) override {}
};
}
struct AgentSidebar::Impl {
    AgentSidebar& owner;
    std::function<juce::var(const juce::var&)> dispatch;
    std::unique_ptr<Service> service;
    std::unique_ptr<Browser> browser;
    juce::Label status;
    juce::TextButton retry{"Retry assistant"};
    juce::String loaded;
    bool keyboardFocusHint = false;
    explicit Impl(AgentSidebar& o, std::function<juce::var(const juce::var&)> d) : owner(o), dispatch(std::move(d)) {
        owner.addAndMakeVisible(status); owner.addAndMakeVisible(retry);
        status.setJustificationType(juce::Justification::centred);
        status.setColour(juce::Label::textColourId, juce::Colour(0xff202020));
        retry.onClick = [this] { owner.restartWorker(); };
    }
};
AgentSidebar::AgentSidebar(std::function<juce::var(const juce::var&)> dispatch)
    : impl(std::make_unique<Impl>(*this, std::move(dispatch))) { setOpaque(true); startTimer(100); }
AgentSidebar::~AgentSidebar() { stopTimer(); if (impl->service) impl->service->stopOwnedWorker(); }
void AgentSidebar::restartWorker() {
    auto& state = *impl;
    if (state.service && state.service->isThreadRunning()) return;
    clearKeyboardFocusHint();
    state.browser.reset(); state.loaded.clear();
    state.service = std::make_unique<Service>(state.dispatch); state.service->startThread();
    state.status.setText("Starting assistant...", juce::dontSendNotification);
    state.status.setVisible(true); state.retry.setVisible(false);
}
void AgentSidebar::setPanelVisible(bool visible) {
    auto& state = *impl;
    if (!visible) clearKeyboardFocusHint();
    if (state.browser && isVisible() && !visible) state.browser->emitEventIfBrowserIsVisible("agentVisibility", obj({{"visible", false}}));
    setVisible(visible);
    if (visible && !state.service) restartWorker();
    if (visible && state.browser) state.browser->emitEventIfBrowserIsVisible("agentVisibility", obj({{"visible", true}}));
}
void AgentSidebar::stopWorkerForTest() { clearKeyboardFocusHint(); if (impl->service) impl->service->stopOwnedWorker(); }
bool AgentSidebar::isWorkerRunning() const { return impl->service && impl->service->isThreadRunning(); }
bool AgentSidebar::capturesKeyboard() const {
    return isShowing() && impl->browser && impl->browser->isShowing()
        && (impl->keyboardFocusHint || impl->browser->hasKeyboardFocus(true));
}
void AgentSidebar::clearKeyboardFocusHint() { impl->keyboardFocusHint = false; }
bool AgentSidebar::isReady() const { return isWorkerRunning() && impl->browser != nullptr && impl->browser->pageLoaded; }
juce::String AgentSidebar::diagnostic() const { return isReady() ? "Ready" : impl->service ? impl->service->status() : "Not started"; }
void AgentSidebar::evaluateForTest(const juce::String& script, juce::WebBrowserComponent::EvaluationCallback callback) {
    if (impl->browser) {
        impl->browser->evaluateJavascript(script, [safe = juce::Component::SafePointer<AgentSidebar>(this), callback = std::move(callback)](auto result) {
            if (safe && callback) callback(std::move(result));
        });
    } else if (callback) {
        callback(juce::WebBrowserComponent::EvaluationResult::Error{
            juce::WebBrowserComponent::EvaluationResult::Error::Type::unknown, "Agent browser is not ready."});
    }
}
void AgentSidebar::probeStateForTest(juce::WebBrowserComponent::EvaluationCallback callback) {
    const auto capability = impl->loaded.fromFirstOccurrenceOf("#token=", false, false);
    if (capability.isEmpty()) { evaluateForTest("null", std::move(callback)); return; }
    const auto script = "(()=>{window.__nativeSmokeState=null;fetch('/api/state',{headers:{'X-Agent-Token':"
        + juce::JSON::toString(juce::var(capability))
        + "}}).then(r=>{if(!r.ok)throw Error('State request failed');return r.json();})"
          ".then(v=>window.__nativeSmokeState=v).catch(()=>window.__nativeSmokeState={error:'State probe failed'});return true;})()";
    evaluateForTest(script, std::move(callback));
}
void AgentSidebar::timerCallback() {
    auto& state = *impl; if (!state.service) return;
    const auto url = state.service->url();
    if (!url.isEmpty() && state.loaded != url && state.service->isThreadRunning()) {
        if (!juce::WebBrowserComponent::areOptionsSupported(juce::WebBrowserComponent::Options().withBackend(juce::WebBrowserComponent::Options::Backend::webview2))) {
            state.status.setText("Microsoft WebView2 Runtime is required for this panel.", juce::dontSendNotification);
            state.retry.setVisible(false); return;
        }
        clearKeyboardFocusHint();
        state.browser = std::make_unique<Browser>(
            [safe = juce::Component::SafePointer<AgentSidebar>(this)] { if (safe && safe->onClose) safe->onClose(); },
            [safe = juce::Component::SafePointer<AgentSidebar>(this)](bool focused) {
                if (safe) safe->impl->keyboardFocusHint = focused && safe->isShowing();
            });
        const juce::URL parsed(url);
        state.browser->origin = "http://127.0.0.1:" + juce::String(parsed.getPort());
        addAndMakeVisible(*state.browser); state.loaded = url; state.browser->goToURL(url); resized();
    }
    if (state.browser && state.browser->failed && state.service->isThreadRunning()) state.service->stopOwnedWorker();
    const bool running = state.service->isThreadRunning();
    const bool pageReady = state.browser && state.browser->pageLoaded;
    state.status.setVisible(!pageReady || !running);
    state.retry.setVisible(!running);
    state.status.setText(state.browser && state.browser->failed ? "Assistant page could not load. Reopen the panel after restarting the assistant." : state.service->status(), juce::dontSendNotification);
    if (!running && state.browser) { clearKeyboardFocusHint(); state.browser->setVisible(false); state.status.toFront(false); state.retry.toFront(false); }
}
void AgentSidebar::resized() {
    auto area = getLocalBounds(); if (impl->browser) impl->browser->setBounds(area);
    impl->status.setBounds(area.withSizeKeepingCentre(juce::jmax(100, getWidth() - 32), 100));
    impl->retry.setBounds((getWidth() - 160) / 2, getHeight() / 2 + 62, 160, 30);
}
void AgentSidebar::paint(juce::Graphics& graphics) {
    graphics.fillAll(juce::Colours::white); graphics.setColour(juce::Colour(0xffcccccc));
    graphics.drawVerticalLine(0, 0.0f, float(getHeight()));
}
}
