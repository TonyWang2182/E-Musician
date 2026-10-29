"""Task-boundary pause and snapshot races; no model, native device or real credentials."""
import threading
import time
import unittest
import test_music_agent_runtime as base
from music_agent.bridge import BridgeError

class TaskControlTests(unittest.TestCase):
    setUp = base.RuntimeTests.setUp
    tearDown = base.RuntimeTests.tearDown
    make = base.RuntimeTests.make
    finish = base.RuntimeTests.finish
    ready = base.RuntimeTests.ready

    def until(self, predicate):
        deadline=time.monotonic()+3
        while not predicate() and time.monotonic()<deadline:
            time.sleep(.005)
        self.assertTrue(predicate())

    def paused(self):
        rt=self.make(base.proposal(base.TEMPO),block=True)
        rt.plan_request("tempo",scope="project")
        self.assertTrue(rt.provider.entered.wait(1))
        self.assertTrue(rt.pause()["pause_requested"])
        rt.provider.release.set()
        self.until(lambda:rt.state(False)["phase"]=="paused")
        return rt

    def test_pause_waits_for_inflight_and_does_not_publish_or_write(self):
        rt=self.paused()
        self.assertIsNone(rt.plan)
        self.assertEqual(len(rt.provider.requests),1)
        self.assertEqual(rt.bridge.calls,[])
        rt.cancel()
        self.assertEqual(self.finish(rt)["phase"],"cancelled")

    def test_resume_publishes_same_request_without_extra_model_call(self):
        rt=self.paused()
        rt.resume()
        state=self.finish(rt)
        self.assertEqual(state["phase"],"ready",state)
        self.assertEqual(len(rt.provider.requests),1)
        self.assertEqual(rt.bridge.calls,[])
        rt.apply(state["plan"]["id"])
        done=self.finish(rt)
        self.assertEqual(done["phase"],"done",done)
        self.assertEqual(done["progress"]["stage"],"done")
        self.assertGreater(done["progress"]["total"],0)

    def test_resume_rejects_intervening_music_change(self):
        rt=self.paused()
        rt.bridge.data["revision"]+=1
        rt.resume()
        state=self.finish(rt)
        self.assertEqual(state["phase"],"error")
        self.assertIsNone(state["plan"])
        self.assertEqual(rt.bridge.calls,[])

    def test_pause_rejected_when_no_planning_worker(self):
        rt=self.make()
        with self.assertRaises(ValueError): rt.pause()
        with self.assertRaises(ValueError): rt.resume()

    def test_old_idle_get_cannot_replace_new_task_snapshot(self):
        rt=self.make(base.proposal(base.TEMPO))
        entered=threading.Event(); release=threading.Event()
        original=rt.bridge.snapshot
        def delayed():
            result=original()
            if threading.current_thread().name=="old-state":
                entered.set()
                if not release.wait(3):raise RuntimeError("fixture deadline")
            return result
        rt.bridge.snapshot=delayed
        reader=threading.Thread(target=rt.state,name="old-state")
        reader.start()
        try:
            self.assertTrue(entered.wait(1))
            pid=self.ready(rt)
            rt.apply(pid);self.assertEqual(self.finish(rt)["phase"],"done")
            expected=rt.snapshot["revision"]
        finally:
            release.set();reader.join(3)
        self.assertFalse(reader.is_alive())
        self.assertEqual(rt.snapshot["revision"],expected)
        self.assertEqual(rt.snapshot["bpm"],100)

    def test_committed_edit_with_readback_failure_keeps_known_undo_receipt(self):
        rt=self.make(base.proposal(base.TEMPO))
        pid=self.ready(rt)
        apply=rt.bridge.apply
        def committed(plan):
            reply=apply(plan)
            def broken():raise BridgeError("simulated readback loss")
            rt.bridge.snapshot=broken
            return reply
        rt.bridge.apply=committed
        rt.apply(pid);state=self.finish(rt)
        self.assertEqual(state["phase"],"error")
        self.assertIn("修改已提交",state["error"])
        self.assertEqual(len(rt.bridge.calls),1)
        self.assertIsNotNone(rt.undo_target)
        self.assertFalse(state["plan"])


    def test_successful_undo_receipt_consumed_before_readback_failure(self):
        rt=self.make(base.proposal(base.TEMPO))
        pid=self.ready(rt);rt.apply(pid)
        self.assertEqual(self.finish(rt)["phase"],"done")
        undo=rt.bridge.undo
        def committed(*args):
            reply=undo(*args)
            def broken():raise BridgeError("simulated undo readback loss")
            rt.bridge.snapshot=broken
            return reply
        rt.bridge.undo=committed
        rt.undo();state=self.finish(rt)
        self.assertEqual(state["phase"],"error")
        self.assertIn("撤销已提交",state["error"])
        self.assertIsNone(rt.undo_target)
        self.assertFalse(state["can_undo"])

    def test_cancel_between_checkpoint_and_publication_cannot_publish(self):
        rt=self.make(base.proposal(base.TEMPO))
        reached=threading.Event();release=threading.Event()
        original=rt._check_planning_context
        boundary_reads=0
        def check(ctx,frozen):
            nonlocal boundary_reads
            original(ctx,frozen)
            if rt.usage["calls"]:
                boundary_reads+=1
            # Second post-response check is immediately before plan publication.
            if boundary_reads==2:
                reached.set()
                if not release.wait(3):raise RuntimeError("fixture deadline")
        rt._check_planning_context=check
        rt.plan_request("tempo",scope="project")
        try:
            self.assertTrue(reached.wait(1))
            rt.cancel()
        finally:release.set()
        state=self.finish(rt)
        self.assertEqual(state["phase"],"cancelled")
        self.assertIsNone(state["plan"])
        self.assertEqual(rt.bridge.calls,[])

    def test_pause_after_context_read_rechecks_before_publishing(self):
        rt=self.make(base.proposal(base.TEMPO))
        entered=threading.Event();release=threading.Event()
        original=rt._check_planning_context
        boundary_reads=0
        def check(ctx,frozen):
            nonlocal boundary_reads
            original(ctx,frozen)
            if rt.usage["calls"]:
                boundary_reads+=1
            if boundary_reads==2:
                entered.set()
                if not release.wait(3):raise RuntimeError("fixture deadline")
        rt._check_planning_context=check
        rt.plan_request("tempo",scope="project")
        try:
            self.assertTrue(entered.wait(1))
            rt.pause()
        finally:release.set()
        self.until(lambda:rt.state(False)["phase"]=="paused")
        rt.bridge.data["revision"]+=1
        rt.resume();state=self.finish(rt)
        self.assertEqual(state["phase"],"error")
        self.assertIsNone(state["plan"])
        self.assertEqual(rt.bridge.calls,[])

if __name__=="__main__":unittest.main()
