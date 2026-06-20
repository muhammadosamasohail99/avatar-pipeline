import asyncio
from typing import Coroutine, Any

class JobRunner:
    def __init__(self, concurrency: int = 2):
        self.concurrency = max(2, concurrency)
        self.queue: asyncio.Queue = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._running = False

    async def start(self) -> None:
        self._running = True
        for _ in range(self.concurrency):
            self._workers.append(asyncio.create_task(self._worker()))

    async def _worker(self) -> None:
        while self._running:
            try:
                coro = await asyncio.wait_for(self.queue.get(), timeout=0.05)
            except asyncio.TimeoutError:
                continue
            try:
                await coro
            except Exception:
                import traceback
                traceback.print_exc()
            finally:
                self.queue.task_done()

    async def submit(self, coro: Coroutine[Any, Any, Any]) -> None:
        await self.queue.put(coro)

    async def stop(self) -> None:
        self._running = False
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
