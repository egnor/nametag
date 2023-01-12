import asyncio
import logging
import os
import signal
import sys


class _LogFormatter(logging.Formatter):
    def format(self, record):
        m = record.getMessage()
        ml = m.lstrip()
        out = ml.rstrip()
        pre, post = m[: len(m) - len(ml)], ml[len(out) :]
        if record.name != "root":
            out = f"{record.name}: {out}"
        if record.levelno < logging.INFO:
            out = f"🕸  {out}"
        elif record.levelno >= logging.CRITICAL:
            out = f"💥 {out}"
        elif record.levelno >= logging.ERROR:
            out = f"🔥 {out}"
        elif record.levelno >= logging.WARNING:
            out = f"⚠️ {out}"
        else:
            out = f"  {out}"
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            out = f"{out.strip()}\n{record.exc_text}"
        if record.stack_info:
            out = f"{out.strip()}\n{record.stack_info}"
        return pre + out.strip() + post


def _sys_exception_hook(exc_type, exc_value, exc_tb):
    if issubclass(exc_type, KeyboardInterrupt):
        logging.critical("*** KeyboardInterrupt (^C)! ***")
    else:
        exc_info = (exc_type, exc_value, exc_tb)
        logging.critical("Uncaught exception", exc_info=exc_info)


def _asyncio_exception_hook(loop, context):
    exc = context.get("exception")
    if isinstance(exc, KeyboardInterrupt):
        logging.critical("*** KeyboardInterrupt (^C)! ***")
    elif exc:
        logging.critical(context["message"], exc_info=(type(exc), exc, None))
    else:
        logging.critical(context["message"])


def enable_debug():
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger("asyncio").setLevel(logging.INFO)
    logging.getLogger("bleak").setLevel(logging.INFO)


# Initialize on import.
_log_handler = logging.StreamHandler(stream=sys.stderr)
_log_handler.setFormatter(_LogFormatter())
logging.basicConfig(level=logging.INFO, handlers=[_log_handler])
sys.excepthook = _sys_exception_hook
asyncio.get_event_loop().set_exception_handler(_asyncio_exception_hook)
