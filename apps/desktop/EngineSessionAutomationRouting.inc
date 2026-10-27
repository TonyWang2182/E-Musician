// Included inside namespace emusician. No audio-thread work lives here.
namespace production {
namespace {
const juce::Identifier productionId("emId"), productionMeta("EM_PRODUCTION"), laneType("LANE"), pointType("POINT");
juce::Result graphError(const juce::String& s) { return juce::Result::fail(s); }
juce::String freshId() { return juce::Uuid().toString(); }
te::AudioTrack* graphTrack(te::Edit& e, const juce::String& id) {
    for (auto* t : te::getAudioTracks(e)) if (t->state[productionId].toString() == id) return t;
    return nullptr;
}
juce::ValueTree graphOwner(te::Edit& e, const juce::String& id) {
    if (id == "master") return e.state.getOrCreateChildWithName("EM_PROJECT", nullptr);
    if (auto* t = graphTrack(e, id)) return t->state;
    return {};
}
struct SendGainChange final : juce::UndoableAction {
    te::Edit& edit; juce::String trackId, sendId; float before, after;
    SendGainChange(te::Edit& e, juce::String t, juce::String s, float a, float b)
        : edit(e), trackId(std::move(t)), sendId(std::move(s)), before(a), after(b) {}
    bool write(float value) {
        if (auto* track = graphTrack(edit, trackId)) for (auto* plugin : track->pluginList)
            if (plugin->state["emSendId"].toString() == sendId) if (auto* send = dynamic_cast<te::AuxSendPlugin*>(plugin)) { send->setGainDb(value); return true; }
        return false;
    }
    bool perform() override { return write(after); } bool undo() override { return write(before); }
    int getSizeInUnits() override { return 32; }
};
struct ControllerSequenceChange final : juce::UndoableAction {
    juce::ValueTree parent, before, after;
    ControllerSequenceChange(juce::ValueTree a, juce::ValueTree b) : parent(a.getParent()), before(std::move(a)), after(std::move(b)) {}
    bool write(juce::ValueTree from, juce::ValueTree to) {
        if (from.getParent() != parent || to.getParent().isValid()) return false;
        const auto index = parent.indexOf(from); parent.removeChild(index, nullptr); parent.addChild(to, index, nullptr);
        to.sendPropertyChangeMessage(te::IDs::channelNumber); return true;
    }
    bool perform() override { return write(before, after); } bool undo() override { return write(after, before); }
    int getSizeInUnits() override { return int(sizeof(*this)) + (before.getNumChildren() + after.getNumChildren()) * 64; }
};
te::AutomatableParameter* laneParameter(te::Edit& e, const juce::String& owner, const storage::StoredAutomationLane& lane) {
    auto* t = graphTrack(e, owner);
    auto* vol = owner == "master" ? e.getMasterVolumePlugin().get() : t ? t->getVolumePlugin() : nullptr;
    if (lane.target == "track_gain" || lane.target == "master_gain") return vol ? vol->volParam.get() : nullptr;
    if (lane.target == "track_pan") return vol ? vol->panParam.get() : nullptr;
    if (lane.target != "plugin_parameter") return nullptr;
    auto* list = owner == "master" ? &e.getMasterPluginList() : t ? &t->pluginList : nullptr;
    if (list) for (auto* plugin : *list) if (plugin->state[productionId].toString() == lane.pluginId) {
        auto* external = dynamic_cast<te::ExternalPlugin*>(plugin);
        if (!external || !external->getAudioPluginInstance() || lane.parameterId == "dryGain" || lane.parameterId == "wetGain") return nullptr;
        return external->getAutomatableParameterByID(lane.parameterId).get();
    }
    return nullptr;
}
storage::StoredAutomationLane readLane(juce::ValueTree tree) {
    storage::StoredAutomationLane lane;
    lane.id = tree["id"].toString(); lane.target = tree["target"].toString();
    lane.pluginId = tree["pluginId"].toString(); lane.parameterId = tree["parameterId"].toString(); lane.enabled = bool(tree.getProperty("enabled", true));
    for (auto p : tree) if (p.hasType(pointType)) lane.points.push_back({ p["id"].toString(), double(p["time"]), float(p["value"]), float(p["curve"]) });
    return lane;
}
juce::ValueTree laneTree(const storage::StoredAutomationLane& lane, bool retainPoints) {
    juce::ValueTree tree(laneType);
    tree.setProperty("id", lane.id, nullptr); tree.setProperty("target", lane.target, nullptr);
    tree.setProperty("pluginId", lane.pluginId, nullptr); tree.setProperty("parameterId", lane.parameterId, nullptr); tree.setProperty("enabled", lane.enabled, nullptr);
    if (retainPoints) for (const auto& p : lane.points) {
        juce::ValueTree child(pointType); child.setProperty("id", p.id, nullptr); child.setProperty("time", p.timeSeconds, nullptr);
        child.setProperty("value", p.value, nullptr); child.setProperty("curve", p.curve, nullptr); tree.addChild(child, -1, nullptr);
    }
    return tree;
}
void captureLanes(te::Edit& edit, const juce::String& owner, std::vector<storage::StoredAutomationLane>& out) {
    out.clear(); auto meta = graphOwner(edit, owner).getChildWithName(productionMeta);
    for (auto child : meta) if (child.hasType(laneType)) {
        auto lane = readLane(child);
        if (auto* parameter = laneParameter(edit, owner, lane)) {
            lane.points.clear(); auto& curve = parameter->getCurve(); lane.enabled = !bool(curve.bypass.get());
            for (int i = 0; i < curve.getNumPoints(); ++i) {
                auto p = curve.getPoint(i);
                lane.points.push_back({ curve.state.getChild(i)[productionId].toString(), p.time.inSeconds(), parameter->valueRange.convertTo0to1(p.value), p.curve });
            }
        }
        out.push_back(std::move(lane));
    }
}
void applyLanes(te::Edit& edit, const juce::String& owner, const std::vector<storage::StoredAutomationLane>& lanes, juce::UndoManager* um) {
    auto meta = graphOwner(edit, owner).getOrCreateChildWithName(productionMeta, um);
    // Clear only curves managed by this application. Missing-plugin lanes retain
    // their source points, so opening a project never binds them to another slot.
    for (int i = meta.getNumChildren(); --i >= 0;) {
        auto old = meta.getChild(i); if (!old.hasType(laneType)) continue;
        auto before = readLane(old);
        auto match = std::find_if(lanes.begin(), lanes.end(), [&](const auto& l) { return l.id == before.id; });
        if (match == lanes.end() || match->target != before.target || match->pluginId != before.pluginId || match->parameterId != before.parameterId) {
            if (auto* p = laneParameter(edit, owner, before)) {
                p->getCurve().clear();
                p->updateStream();
            }
            meta.removeChild(i, um);
        }
    }
    for (const auto& lane : lanes) {
        auto* parameter = laneParameter(edit, owner, lane);
        auto wanted = laneTree(lane, parameter == nullptr);
        auto old = meta.getChildWithProperty("id", lane.id);
        if (!old.isEquivalentTo(wanted)) { if (old.isValid()) meta.removeChild(old, um); meta.addChild(wanted, -1, um); }
        if (!parameter) continue;
        auto& curve = parameter->getCurve(); bool same = curve.getNumPoints() == int(lane.points.size());
        for (int i = 0; same && i < curve.getNumPoints(); ++i) {
            const auto& p = lane.points[size_t(i)]; const auto native = curve.getPoint(i);
            same = native.time.inSeconds() == p.timeSeconds && std::abs(parameter->valueRange.convertTo0to1(native.value) - p.value) < 1.0e-6f
                && native.curve == p.curve && curve.state.getChild(i)[productionId].toString() == p.id;
        }
        if (!same) {
            curve.clear(); for (const auto& p : lane.points) {
                const int index = curve.addPoint(te::TimePosition::fromSeconds(p.timeSeconds), parameter->valueRange.convertFrom0to1(p.value), p.curve);
                curve.state.getChild(index).setProperty(productionId, p.id, um);
            }
        }
        curve.state.setProperty(te::IDs::bypass, !lane.enabled, um);
        // The pinned engine otherwise rebuilds its AutomationIterator on a
        // deferred 10 ms message-thread timer. A render worker can start its
        // synchronous render before that timer ever runs, leaving this real
        // curve absent from the plugin's active parameter stream. Publish the
        // completed curve once here, after all its points have been installed.
        if (!same || (!lane.points.empty() && !parameter->isAutomationActive())) parameter->updateStream();
    }
}
juce::var graphObject(std::initializer_list<std::pair<juce::Identifier, juce::var>> values) {
    auto* o = new juce::DynamicObject(); for (const auto& p : values) o->setProperty(p.first, p.second); return juce::var(o);
}
}

juce::Result validateGraph(const storage::StoredProject& project) {
    std::map<juce::String, const storage::StoredTrack*> tracks;
    std::set<juce::String> identities;
    for (const auto& t : project.tracks) tracks[t.id] = &t;
    std::map<juce::String, std::vector<juce::String>> edges;
    size_t totalPoints = 0, totalSends = 0, totalLanes = 0;
    auto validLanes = [&](const auto& lanes, const juce::String& owner) -> juce::Result {
        if (lanes.size() > 256) return graphError("Automation lane limit per owner exceeded.");
        std::set<juce::String> targets;
        for (const auto& l : lanes) {
            if (++totalLanes > 4096) return graphError("Project automation lane limit exceeded.");
            if (l.id.isEmpty() || !identities.insert(l.id).second) return graphError("Automation lane IDs must be unique.");
            if (l.target != "track_gain" && l.target != "track_pan" && l.target != "master_gain" && l.target != "plugin_parameter") return graphError("Unsupported automation target.");
            if ((owner == "master" && (l.target == "track_gain" || l.target == "track_pan")) || (owner != "master" && l.target == "master_gain")) return graphError("Automation target belongs to a different mixer owner.");
            if (l.target == "plugin_parameter" && (l.pluginId.isEmpty() || l.parameterId.isEmpty())) return graphError("Plugin automation needs stable plugin and parameter IDs.");
            if (!targets.insert(l.target + "|" + l.pluginId + "|" + l.parameterId).second) return graphError("A parameter can have only one automation lane.");
            double previous = -1;
            for (const auto& p : l.points) {
                if (p.id.isEmpty() || !identities.insert(p.id).second) return graphError("Automation point IDs must be unique.");
                if (!std::isfinite(p.timeSeconds) || p.timeSeconds < 0 || p.timeSeconds > storage::maximumTimelineSeconds || p.timeSeconds <= previous) return graphError("Automation points need strictly increasing finite timeline seconds.");
                if (!std::isfinite(p.value) || p.value < 0 || p.value > 1 || !std::isfinite(p.curve) || p.curve < -1 || p.curve > 1) return graphError("Automation value must be 0..1; curvature must be -1..1.");
                previous = p.timeSeconds; if (++totalPoints > 100000) return graphError("Automation point limit exceeded.");
            }
        }
        return juce::Result::ok();
    };
    for (const auto& t : project.tracks) {
        if (t.sends.size() > 32) return graphError("Send limit per track exceeded.");
        std::set<juce::String> sendTargets;
        auto edge = [&](const juce::String& destination) -> juce::Result {
            if (destination == "master") return juce::Result::ok();
            auto found = tracks.find(destination);
            if (found == tracks.end() || found->second->kind != "bus") return graphError("Routing destination must be an existing audio bus or master.");
            if (destination == t.id) return graphError("A track cannot route to itself.");
            edges[t.id].push_back(destination); return juce::Result::ok();
        };
        if (auto r = edge(t.outputTargetId); r.failed()) return r;
        for (const auto& s : t.sends) {
            if (!sendTargets.insert(s.targetTrackId).second) return graphError("A track can send to a bus only once.");
            if (s.id.isEmpty() || !identities.insert(s.id).second || ++totalSends > 512) return graphError("Invalid or excessive send IDs.");
            if (s.targetTrackId == "master") return graphError("Use the track output to reach master; sends require a bus.");
            if (!std::isfinite(s.gainDb) || s.gainDb < -60 || s.gainDb > 6) return graphError("Send gain must be -60..6 dB.");
            // Disabled sends also participate: enabling one must not create a cycle.
            if (auto r = edge(s.targetTrackId); r.failed()) return r;
        }
        if (auto r = validLanes(t.automation, t.id); r.failed()) return r;
    }
    if (auto r = validLanes(project.masterAutomation, "master"); r.failed()) return r;
    std::map<juce::String, int> colour;
    std::function<bool(const juce::String&)> visit = [&](const juce::String& id) {
        if (colour[id] == 1) return false; if (colour[id] == 2) return true; colour[id] = 1;
        for (const auto& next : edges[id]) if (!visit(next)) return false;
        colour[id] = 2; return true;
    };
    for (const auto& t : project.tracks) if (!visit(t.id)) return graphError("Routing rejected: outputs and sends would form a feedback cycle.");
    return juce::Result::ok();
}

void captureGraph(te::Edit& edit, storage::StoredProject& out, bool includeControllers) {
    if (auto* vol = edit.getMasterVolumePlugin().get()) out.masterGainDb = stableGain(te::volumeFaderPositionToDB(vol->volParam->getCurrentExplicitValue()));
    captureLanes(edit, "master", out.masterAutomation);
    for (auto& t : out.tracks) if (auto* track = graphTrack(edit, t.id)) {
        auto meta = track->state.getChildWithName(productionMeta);
        t.inputDeviceId = meta["inputDeviceId"].toString(); t.outputTargetId = meta.getProperty("outputTargetId", "master").toString();
        if (auto* vol = track->getVolumePlugin()) { t.gainDb = stableGain(te::volumeFaderPositionToDB(vol->volParam->getCurrentExplicitValue())); t.pan = vol->panParam->getCurrentExplicitValue(); }
        t.sends.clear(); for (auto* p : track->pluginList) if (auto* send = dynamic_cast<te::AuxSendPlugin*>(p); send && send->state["emSendId"].toString().isNotEmpty())
            t.sends.push_back({ send->state["emSendId"].toString(), send->state["emSendTarget"].toString(), send->getGainDb(), bool(send->state["emPreFader"]), send->isEnabled() });
        captureLanes(edit, t.id, t.automation);
        if (includeControllers) for (auto& clip : t.clips) if (clip.kind == "midi") {
            clip.controllers.clear();
            for (auto* native : track->getClips()) if (native->state[productionId].toString() == clip.id)
                if (auto* midi = dynamic_cast<te::MidiClip*>(native)) for (auto* event : midi->getSequence().getControllerEvents())
                    clip.controllers.push_back({ event->state[productionId].toString(), event->getBeatPosition().inBeats(), event->getType(), event->getControllerValue(), event->getMetadata() });
        }
    }
}

juce::Result applyGraph(te::Edit& edit, const storage::StoredProject& wanted, bool loading) {
    if (auto r = validateGraph(wanted); r.failed()) return r;
    auto* um = loading ? nullptr : &edit.getUndoManager(); std::map<juce::String, int> busNumbers;
    for (const auto& t : wanted.tracks) if (t.kind == "bus") busNumbers[t.id] = int(busNumbers.size());
    // First detach changed direct outputs. This avoids transient native cycles
    // when a valid DAG changes direction in one undoable command.
    for (const auto& t : wanted.tracks) if (auto* track = graphTrack(edit, t.id)) {
        auto old = track->state.getChildWithName(productionMeta).getProperty("outputTargetId", "master").toString();
        if (old != t.outputTargetId) track->getOutput().setOutputToDefaultDevice(false);
    }
    for (const auto& t : wanted.tracks) {
        auto* track = graphTrack(edit, t.id); if (!track) return graphError("Routing track was not created.");
        auto meta = track->state.getOrCreateChildWithName(productionMeta, um);
        meta.setProperty("inputDeviceId", t.inputDeviceId, um); meta.setProperty("outputTargetId", t.outputTargetId, um);
        std::vector<te::Plugin::Ptr> obsolete;
        for (auto* p : track->pluginList) {
            if (p->state["emReturnBus"].toString().isNotEmpty() && t.kind != "bus") obsolete.push_back(p);
            auto id = p->state["emSendId"].toString();
            if (id.isNotEmpty() && std::none_of(t.sends.begin(), t.sends.end(), [&](const auto& s) { return s.id == id; })) obsolete.push_back(p);
        }
        for (auto& p : obsolete) p->deleteFromParent();
        if (t.kind == "bus") {
            te::AuxReturnPlugin* returnPlugin = nullptr;
            for (auto* p : track->pluginList) if (p->state["emReturnBus"].toString() == t.id) returnPlugin = dynamic_cast<te::AuxReturnPlugin*>(p);
            if (!returnPlugin) { auto p = edit.getPluginCache().createNewPlugin(te::AuxReturnPlugin::xmlTypeName, {}); if (!p) return graphError("Could not create audio return."); p->state.setProperty("emReturnBus", t.id, um); track->pluginList.insertPlugin(p, 0, nullptr); returnPlugin = dynamic_cast<te::AuxReturnPlugin*>(p.get()); }
            if (!returnPlugin) return graphError("Audio return has an invalid plugin type.");
            returnPlugin->busNumber = busNumbers.at(t.id);
            auto parent = returnPlugin->state.getParent(); parent.moveChild(parent.indexOf(returnPlugin->state), 0, um);
        }
        int postFaderIndex = 0;
        for (const auto& s : t.sends) {
            te::AuxSendPlugin* send = nullptr; for (auto* p : track->pluginList) if (p->state["emSendId"].toString() == s.id) send = dynamic_cast<te::AuxSendPlugin*>(p);
            if (!send) { auto p = edit.getPluginCache().createNewPlugin(te::AuxSendPlugin::xmlTypeName, {}); if (!p) return graphError("Could not create audio send."); p->state.setProperty("emSendId", s.id, um); track->pluginList.insertPlugin(p, -1, nullptr); send = dynamic_cast<te::AuxSendPlugin*>(p.get()); }
            if (!send) return graphError("Audio send has an invalid plugin type.");
            send->state.setProperty("emSendTarget", s.targetTrackId, um); send->state.setProperty("emPreFader", s.preFader, um);
            send->busNumber = busNumbers.at(s.targetTrackId);
            if (std::abs(send->getGainDb() - s.gainDb) > 1.0e-5f) {
                if (loading) send->setGainDb(s.gainDb);
                else edit.getUndoManager().perform(new SendGainChange(edit, t.id, s.id, send->getGainDb(), s.gainDb));
            }
            send->setEnabled(s.enabled);
            // Move adjacent to the fader after external plugin ordering is final.
            auto parent = send->state.getParent(); auto fader = track->getVolumePlugin()->state;
            int source = parent.indexOf(send->state), destination = parent.indexOf(fader) + (s.preFader ? 0 : 1 + postFaderIndex++);
            if (source < destination) --destination; if (source != destination) parent.moveChild(source, destination, um);
        }
        if (t.outputTargetId == "master") { if (!track->getOutput().usesDefaultAudioOut()) track->getOutput().setOutputToDefaultDevice(false); }
        else {
            auto* destination = graphTrack(edit, t.outputTargetId);
            // The native persistence form uses an audio-track number. Keep it
            // synchronized after reorder, even if the stable destination ID is unchanged.
            const auto wantedName = "track " + juce::String(destination->getAudioTrackNumber());
            const auto actualName = track->getOutput().state.getChildWithName(te::IDs::DEVICE)[te::IDs::name].toString();
            if (actualName != wantedName || track->getOutput().getDestinationTrack() != destination) track->getOutput().setOutputToTrack(destination);
        }
        applyLanes(edit, t.id, t.automation, um);
        for (const auto& clip : t.clips) if (clip.kind == "midi") for (auto* native : track->getClips()) if (native->state[productionId].toString() == clip.id)
            if (auto* midi = dynamic_cast<te::MidiClip*>(native)) {
                auto& sequence = midi->getSequence(); bool same = sequence.getNumControllerEvents() == int(clip.controllers.size());
                std::map<juce::String, te::MidiControllerEvent*> events;
                for (auto* event : sequence.getControllerEvents()) events[event->state[productionId].toString()] = event;
                for (const auto& event : clip.controllers) {
                    auto i = events.find(event.id); if (i == events.end()) { same = false; break; } auto* old = i->second;
                    if (old->getBeatPosition().inBeats() != event.beats || old->getType() != event.type || old->getControllerValue() != event.value || old->getMetadata() != event.metadata) { same = false; break; }
                }
                if (!same) {
                    const auto old = sequence.state; juce::ValueTree next(old.getType()); next.copyPropertiesFrom(old, nullptr);
                    const auto controllerType = te::MidiControllerEvent::createControllerEvent({}, 0, 0).getType();
                    for (auto child : old) if (!child.hasType(controllerType)) next.addChild(child.createCopy(), -1, nullptr);
                    for (const auto& event : clip.controllers) {
                        auto child = te::MidiControllerEvent::createControllerEvent(te::BeatPosition::fromBeats(event.beats), event.type, event.value, event.metadata);
                        child.setProperty(productionId, event.id, nullptr); next.addChild(child, -1, nullptr);
                    }
                    if (um) { if (!um->perform(new ControllerSequenceChange(old, next))) return graphError("Could not replace MIDI controllers."); }
                    else { ControllerSequenceChange change(old, next); if (!change.perform()) return graphError("Could not restore MIDI controllers."); }
                }
            }
    }
    applyLanes(edit, "master", wanted.masterAutomation, um);
    edit.getAutomationRecordManager().setReadingAutomation(true);
    edit.getAutomationRecordManager().setWritingAutomation(false);
    return juce::Result::ok();
}

juce::Result mutateGraph(storage::StoredProject& project, const juce::String& command, const juce::var& args) {
    if (!args.isObject()) return graphError("Production command arguments must be an object.");
    const auto isNumber = [](const juce::var& v) { return (v.isInt() || v.isInt64() || v.isDouble()) && std::isfinite(double(v)); };
    for (const auto* key : { "track_id", "input_device_id", "target_track_id", "send_id", "lane_id", "target", "plugin_id", "parameter_id" })
        if (args.hasProperty(key) && !args[key].isString()) return graphError(juce::String(key) + " must be a string.");
    for (const auto* key : { "enabled", "pre_fader" }) if (args.hasProperty(key) && !args[key].isBool()) return graphError(juce::String(key) + " must be a boolean.");
    if (args.hasProperty("gain_db") && !isNumber(args["gain_db"])) return graphError("gain_db must be a finite number.");
    if (!args.hasProperty("track_id") || args["track_id"].toString().isEmpty()) return graphError("track_id is required.");
    if (command == "set_track_input" && !args.hasProperty("input_device_id")) return graphError("input_device_id is required (empty clears the input).");
    if ((command == "set_track_output" || command == "add_send") && (!args.hasProperty("target_track_id") || args["target_track_id"].toString().isEmpty())) return graphError("target_track_id is required.");
    if ((command == "update_send" || command == "remove_send") && args["send_id"].toString().isEmpty()) return graphError("send_id is required.");
    if (command == "remove_automation_lane" && args["lane_id"].toString().isEmpty()) return graphError("lane_id is required.");
    const auto trackId = args["track_id"].toString(); storage::StoredTrack* track = nullptr;
    for (auto& t : project.tracks) if (t.id == trackId) track = &t;
    if (!track && trackId != "master") return graphError("Track not found.");
    if (command == "set_track_input") { if (!track || track->kind == "bus") return graphError("Select an audio or MIDI track for recording."); track->inputDeviceId = args["input_device_id"].toString(); }
    else if (command == "set_track_output") { if (!track) return graphError("Master output cannot route into the project."); track->outputTargetId = args["target_track_id"].toString(); }
    else if (command == "add_send" || command == "update_send" || command == "remove_send") {
        if (!track) return graphError("Sends require a track.");
        auto id = args["send_id"].toString(); auto it = std::find_if(track->sends.begin(), track->sends.end(), [&](const auto& s) { return s.id == id; });
        if (command == "remove_send") { if (it == track->sends.end()) return graphError("Send not found."); track->sends.erase(it); }
        else {
            if (command == "add_send") { if (it != track->sends.end()) return graphError("Send ID already exists."); storage::StoredSend s; s.id = id.isEmpty() ? freshId() : id; track->sends.push_back(s); it = std::prev(track->sends.end()); }
            else if (it == track->sends.end()) return graphError("Send not found.");
            if (args.hasProperty("target_track_id")) it->targetTrackId = args["target_track_id"].toString();
            if (args.hasProperty("gain_db")) it->gainDb = float(args["gain_db"]);
            if (args.hasProperty("pre_fader")) it->preFader = bool(args["pre_fader"]);
            if (args.hasProperty("enabled")) it->enabled = bool(args["enabled"]);
        }
    } else if (command == "set_automation_lane" || command == "remove_automation_lane") {
        auto& lanes = track ? track->automation : project.masterAutomation; auto id = args["lane_id"].toString();
        auto it = std::find_if(lanes.begin(), lanes.end(), [&](const auto& l) { return l.id == id; });
        if (command == "remove_automation_lane") { if (it == lanes.end()) return graphError("Automation lane not found."); lanes.erase(it); }
        else {
            storage::StoredAutomationLane lane; if (it != lanes.end()) lane = *it; else { if (!args.hasProperty("target")) return graphError("A new automation lane needs a target."); lane.id = id.isEmpty() ? freshId() : id; }
            if (args.hasProperty("target")) lane.target = args["target"].toString(); if (args.hasProperty("plugin_id")) lane.pluginId = args["plugin_id"].toString();
            if (args.hasProperty("parameter_id")) lane.parameterId = args["parameter_id"].toString(); if (args.hasProperty("enabled")) lane.enabled = bool(args["enabled"]);
            if (args.hasProperty("points")) {
                auto* array = args["points"].getArray(); if (!array) return graphError("Automation points must be an array."); if (array->size() > 100000) return graphError("Automation point limit exceeded."); lane.points.clear();
                for (const auto& point : *array) {
                    if (!point.isObject() || !isNumber(point["time_seconds"]) || !isNumber(point["value"]) || (point.hasProperty("curve") && !isNumber(point["curve"])) || (point.hasProperty("id") && !point["id"].isString())) return graphError("Each automation point needs numeric time_seconds/value, optional numeric curve, and optional string id.");
                    auto pid = point["id"].toString(); lane.points.push_back({ pid.isEmpty() ? freshId() : pid, double(point["time_seconds"]), float(point["value"]), float(point["curve"]) });
                }
                std::stable_sort(lane.points.begin(), lane.points.end(), [](const auto& a, const auto& b) { return a.timeSeconds < b.timeSeconds; });
            }
            if (it == lanes.end()) lanes.push_back(std::move(lane)); else *it = std::move(lane);
        }
    } else return graphError("Unsupported production command.");
    return validateGraph(project);
}

juce::var automationTargets(te::Edit& edit, const juce::String& trackId) {
    juce::Array<juce::var> result;
    auto add = [&](const juce::String& target, const juce::String& pluginId, te::AutomatableParameter* p) {
        if (!p) return; result.add(graphObject({ {"target", target}, {"plugin_id", pluginId}, {"parameter_id", target == "plugin_parameter" ? p->paramID : juce::String()}, {"name", p->getParameterName()}, {"current_normalized_value", p->getCurrentNormalisedValue()}, {"text", p->getCurrentValueAsString()} }));
    };
    auto* track = graphTrack(edit, trackId); auto* volume = trackId == "master" ? edit.getMasterVolumePlugin().get() : track ? track->getVolumePlugin() : nullptr;
    if (volume) { add(trackId == "master" ? "master_gain" : "track_gain", {}, volume->volParam.get()); if (track) add("track_pan", {}, volume->panParam.get()); }
    auto* list = trackId == "master" ? &edit.getMasterPluginList() : track ? &track->pluginList : nullptr;
    if (list) for (auto* plugin : *list) if (auto* external = dynamic_cast<te::ExternalPlugin*>(plugin); external && external->getAudioPluginInstance())
        for (auto* p : external->getAutomatableParameters()) if (p->paramID != "dryGain" && p->paramID != "wetGain") add("plugin_parameter", plugin->state[productionId].toString(), p);
    return graphObject({ {"targets", result} });
}
} // namespace production
