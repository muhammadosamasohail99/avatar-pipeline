import asyncio
import pytest
from workers.job_runner import JobRunner

@pytest.mark.asyncio
async def test_concurrency():
    runner = JobRunner(concurrency=2)
    results = []
    async def task(x):
        await asyncio.sleep(0.01)
        results.append(x)
    await runner.start()
    for i in range(4):
        await runner.submit(task(i))
    await asyncio.sleep(0.2)
    await runner.stop()
    assert sorted(results) == [0, 1, 2, 3]

@pytest.mark.asyncio
async def test_concurrency_min_2():
    runner = JobRunner(concurrency=1)
    assert runner.concurrency >= 2
