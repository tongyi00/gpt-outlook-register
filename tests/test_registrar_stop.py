import queue
import threading
import unittest

from webui import registrar


class RegistrarStopTests(unittest.TestCase):
    def test_stop_run_sets_cancel_event_and_emits_status(self):
        run_id = "teststoprun"
        q = queue.Queue()
        ev = threading.Event()
        with registrar._lock:
            registrar._run_queues[run_id] = q
            registrar._run_cancel_events[run_id] = ev

        try:
            result = registrar.stop_run(run_id)

            self.assertTrue(result["ok"])
            self.assertTrue(ev.is_set())
            event = q.get_nowait()
            self.assertTrue(event.startswith("__EVENT__:"))
            self.assertIn('"kind": "stopped"', event)
        finally:
            with registrar._lock:
                registrar._run_queues.pop(run_id, None)
                registrar._run_cancel_events.pop(run_id, None)


if __name__ == "__main__":
    unittest.main()
