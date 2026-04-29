import os
import signal
import threading
import time


class LLMTimeoutError(TimeoutError):
    pass


def _coerce_timeout_seconds(timeout):
    if timeout is None:
        return None
    if isinstance(timeout, (int, float)):
        return float(timeout)
    if isinstance(timeout, tuple):
        values = [float(value) for value in timeout if isinstance(value, (int, float))]
        return max(values) if values else None
    for attr in ("read", "timeout", "total"):
        value = getattr(timeout, attr, None)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _call_with_hard_timeout(func, timeout_seconds):
    if (
        timeout_seconds is None
        or timeout_seconds <= 0
        or os.name != "posix"
        or threading.current_thread() is not threading.main_thread()
    ):
        return func()

    previous_handler = signal.getsignal(signal.SIGALRM)

    def _handle_timeout(signum, frame):
        raise LLMTimeoutError(f"LLM request exceeded {timeout_seconds:g} seconds")

    signal.signal(signal.SIGALRM, _handle_timeout)
    signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        return func()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def call_llm_with_retry(
    llm,
    messages,
    *,
    max_retries=5,
    initial_delay=2,
    max_delay=10,
    label="LLM",
):
    last_error = None
    hard_timeout = _coerce_timeout_seconds(getattr(llm, "request_timeout", None))
    for attempt in range(max_retries):
        try:
            return _call_with_hard_timeout(lambda: llm(messages), hard_timeout)
        except Exception as err:
            last_error = err
            if attempt == max_retries - 1:
                break
            delay = min(initial_delay * (2**attempt), max_delay)
            print(
                f"{label} request failed ({err}). Retrying in {delay} seconds "
                f"[{attempt + 1}/{max_retries}]"
            )
            time.sleep(delay)
    raise last_error
