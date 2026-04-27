import atexit
import os
import queue
import threading
from concurrent.futures import Future
from typing import Any, Callable, Optional, Tuple


_DEFAULT_MAX_CONCURRENCY = 3


class TrackingQueue:
    def __init__(self, max_concurrency: int = _DEFAULT_MAX_CONCURRENCY):
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")

        self._q: "queue.Queue[Optional[Tuple[Callable[..., Any], tuple, dict, Future]]]" = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._shutdown = threading.Event()

        for i in range(max_concurrency):
            t = threading.Thread(
                target=self._worker,
                name=f"tracking-worker-{i + 1}",
                daemon=True,
            )
            t.start()
            self._threads.append(t)

        atexit.register(self.shutdown)

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
        if self._shutdown.is_set():
            f: Future = Future()
            f.set_exception(RuntimeError("TrackingQueue is shut down"))
            return f

        f = Future()
        self._q.put((fn, args, kwargs, f))
        return f

    def shutdown(self) -> None:
        if self._shutdown.is_set():
            return
        self._shutdown.set()
        for _ in self._threads:
            self._q.put(None)

    def _worker(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                return

            fn, args, kwargs, f = item
            if f.cancelled():
                continue
            try:
                res = fn(*args, **kwargs)
            except Exception as e:
                f.set_exception(e)
            else:
                f.set_result(res)


tracking_queue = TrackingQueue(
    max_concurrency=int(os.getenv("MAX_CONCURRENT_TRACKING_JOBS", str(_DEFAULT_MAX_CONCURRENCY)))
)
