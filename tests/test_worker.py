"""The scheduler process.

Exists so APScheduler is not hosted inside a gunicorn worker, where one
scheduler per worker means every job fires N times.
"""

import signal
import threading
from unittest.mock import MagicMock, patch


@patch("app.worker.init_scheduler")
@patch("app.worker.create_app")
def test_main_starts_and_shuts_down_cleanly(mock_create, mock_init, monkeypatch):
    sched = MagicMock()
    sched.get_jobs.return_value = [MagicMock(id="poll_feeds")]
    mock_init.return_value = sched

    # Stop waiting immediately, as SIGTERM would.
    real_event = threading.Event
    monkeypatch.setattr(threading, "Event",
                        lambda: type("E", (), {"wait": lambda s: None,
                                               "set": lambda s: None})())
    from app import worker
    assert worker.main() == 0
    monkeypatch.setattr(threading, "Event", real_event)

    sched.start.assert_called_once()
    sched.shutdown.assert_called_once_with(wait=True)


@patch("app.worker.init_scheduler")
@patch("app.worker.create_app")
def test_signal_handlers_release_the_wait(mock_create, mock_init, monkeypatch):
    """SIGTERM must shut the scheduler down rather than kill it mid-job."""
    sched = MagicMock()
    sched.get_jobs.return_value = []
    mock_init.return_value = sched

    handlers = {}
    monkeypatch.setattr(signal, "signal",
                        lambda sig, fn: handlers.__setitem__(sig, fn))

    class _Event:
        def __init__(self): self.waited = False
        def wait(self):
            self.waited = True
            handlers[signal.SIGTERM](signal.SIGTERM, None)   # arrive during wait
        def set(self): self.stopped = True

    monkeypatch.setattr(threading, "Event", _Event)
    from app import worker
    assert worker.main() == 0
    assert signal.SIGTERM in handlers and signal.SIGINT in handlers
    sched.shutdown.assert_called_once_with(wait=True)


@patch("app.worker.init_scheduler")
@patch("app.worker.create_app")
def test_scheduler_is_shut_down_even_if_waiting_raises(mock_create, mock_init, monkeypatch):
    sched = MagicMock()
    sched.get_jobs.return_value = []
    mock_init.return_value = sched

    class _Boom:
        def wait(self): raise KeyboardInterrupt
        def set(self): pass

    monkeypatch.setattr(threading, "Event", _Boom)
    from app import worker
    try:
        worker.main()
    except KeyboardInterrupt:
        pass
    sched.shutdown.assert_called_once_with(wait=True)
