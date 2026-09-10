"""A real ipykernel to test capture against (SPEC 17.2).

Hard rule 5: integration tests use a real kernel, not mocked IPython objects. The
bugs that matter here — hooks firing in an order we didn't expect, streams not
restored, a display published after the run "ended" — are exactly the ones a mock
would paper over.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

DEFAULT_TIMEOUT = 60.0


@dataclass
class Reply:
    """What one executed cell produced."""

    status: str
    stdout: str = ""
    stderr: str = ""
    displays: list[dict[str, Any]] = field(default_factory=list)
    result: str | None = None
    error: str | None = None

    @property
    def output(self) -> str:
        return self.stdout + self.stderr


class Kernel:
    """Drives a real ipykernel subprocess, one cell at a time."""

    def __init__(self, env: dict[str, str] | None = None, timeout: float = DEFAULT_TIMEOUT):
        from jupyter_client import KernelManager

        self.timeout = timeout
        self.km = KernelManager(kernel_name="python3")
        self.km.start_kernel(env={**os.environ, **(env or {})})
        self.kc = self.km.client()
        self.kc.start_channels()
        self.kc.wait_for_ready(timeout=timeout)

    # -- execution --------------------------------------------------------

    def run(self, code: str, cell_id: str | None = None) -> Reply:
        """Execute one cell and collect everything it emitted.

        ``cell_id`` is sent the way a real frontend sends it — in the execute_request
        *metadata* as ``cellId`` (see docs/decisions/0002). ``jupyter_client``'s own
        ``execute()`` never sends one, so both paths need testing.
        """
        msg_id = self._send(code, cell_id)
        reply = Reply(status="unknown")
        self._collect_iopub(msg_id, reply)
        shell = self._await_shell(msg_id)
        reply.status = shell["content"].get("status", "unknown")
        if reply.status == "error":
            reply.error = shell["content"].get("ename")
        return reply

    def _send(self, code: str, cell_id: str | None) -> str:
        content = {
            "code": code,
            "silent": False,
            "store_history": True,
            "user_expressions": {},
            "allow_stdin": False,
            "stop_on_error": False,
        }
        metadata = {"cellId": cell_id} if cell_id else {}
        msg = self.kc.session.msg("execute_request", content, metadata=metadata)
        self.kc.shell_channel.send(msg)
        return str(msg["header"]["msg_id"])

    def _await_shell(self, msg_id: str) -> dict[str, Any]:
        while True:
            msg = self.kc.get_shell_msg(timeout=self.timeout)
            if msg["parent_header"].get("msg_id") == msg_id:
                return msg

    def _collect_iopub(self, msg_id: str, reply: Reply) -> None:
        """Drain iopub until the kernel goes idle for our request."""
        while True:
            msg = self.kc.get_iopub_msg(timeout=self.timeout)
            if msg["parent_header"].get("msg_id") != msg_id:
                continue
            kind, content = msg["msg_type"], msg["content"]
            if kind == "stream":
                if content["name"] == "stdout":
                    reply.stdout += content["text"]
                else:
                    reply.stderr += content["text"]
            elif kind in ("display_data", "update_display_data"):
                reply.displays.append(content.get("data", {}))
            elif kind == "execute_result":
                reply.result = content.get("data", {}).get("text/plain")
            elif kind == "error":
                reply.error = content.get("ename")
            elif kind == "status" and content.get("execution_state") == "idle":
                return

    # -- control ----------------------------------------------------------

    def interrupt(self) -> None:
        self.km.interrupt_kernel()

    def close(self) -> None:
        try:
            self.kc.stop_channels()
        finally:
            self.km.shutdown_kernel(now=True)

    def __enter__(self) -> Kernel:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
