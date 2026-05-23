"""Bob Manager Agent — PTY terminal handler.

Provides interactive shell sessions via WebSocket relay.
"""

import asyncio
import fcntl
import logging
import os
import pty
import select
import signal
import struct
import termios

logger = logging.getLogger(__name__)


class TerminalSession:
    """A single PTY shell session."""

    def __init__(self, session_id: str, cols: int = 120, rows: int = 40):
        self.session_id = session_id
        self.cols = cols
        self.rows = rows
        self.master_fd: int | None = None
        self.child_pid: int | None = None
        self._running = False

    def start(self) -> None:
        """Fork a PTY and start a bash shell."""
        pid, fd = pty.fork()
        if pid == 0:
            # Child process — exec bash (pty.fork already called setsid)
            os.execvpe("bash", ["bash", "--login"], os.environ)
        else:
            # Parent
            self.child_pid = pid
            self.master_fd = fd
            self._running = True
            # Set initial size
            self.resize(self.cols, self.rows)
            # Make master non-blocking
            fl = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
            logger.info("Terminal session %s started (pid=%d)", self.session_id, pid)

    def write(self, data: str) -> None:
        """Write input data to the PTY."""
        if self.master_fd is not None and self._running:
            os.write(self.master_fd, data.encode("utf-8"))

    def read(self) -> str | None:
        """Non-blocking read from PTY. Returns None if no data."""
        if self.master_fd is None or not self._running:
            return None
        try:
            r, _, _ = select.select([self.master_fd], [], [], 0)
            if r:
                data = os.read(self.master_fd, 65536)
                if data:
                    return data.decode("utf-8", errors="replace")
                else:
                    self._running = False
                    return None
            return None
        except OSError:
            self._running = False
            return None

    def resize(self, cols: int, rows: int) -> None:
        """Resize the PTY."""
        self.cols = cols
        self.rows = rows
        if self.master_fd is not None:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)

    def close(self) -> None:
        """Kill the shell and close the PTY."""
        self._running = False
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = None
        if self.child_pid is not None:
            try:
                os.kill(self.child_pid, signal.SIGTERM)
                os.waitpid(self.child_pid, os.WNOHANG)
            except (OSError, ChildProcessError):
                pass
            self.child_pid = None
        logger.info("Terminal session %s closed", self.session_id)

    @property
    def is_alive(self) -> bool:
        return self._running and self.master_fd is not None


class TerminalManager:
    """Manages multiple terminal sessions."""

    def __init__(self):
        self._sessions: dict[str, TerminalSession] = {}
        self._output_tasks: dict[str, asyncio.Task] = {}

    def create_session(self, session_id: str, cols: int = 120, rows: int = 40) -> TerminalSession:
        """Create and start a new terminal session."""
        session = TerminalSession(session_id, cols, rows)
        session.start()
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> TerminalSession | None:
        return self._sessions.get(session_id)

    def close_session(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session:
            session.close()
        task = self._output_tasks.pop(session_id, None)
        if task:
            task.cancel()

    def close_all(self) -> None:
        for sid in list(self._sessions.keys()):
            self.close_session(sid)

    async def start_output_loop(self, session_id: str, send_callback) -> None:
        """Poll PTY output and send via callback. Runs as a task."""
        session = self._sessions.get(session_id)
        if not session:
            return

        async def _loop():
            try:
                while session.is_alive:
                    data = session.read()
                    if data:
                        await send_callback(data)
                    else:
                        await asyncio.sleep(0.02)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error("Terminal output loop error: %s", e)

        task = asyncio.create_task(_loop())
        self._output_tasks[session_id] = task


# Singleton
terminal_manager = TerminalManager()
