"""Bob Manager Agent — Command runner with streaming output."""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def run_command(
    command: str,
    on_stdout: callable = None,
    on_stderr: callable = None,
    timeout: int = 300,
) -> dict:
    """Execute a shell command with streaming output.

    Args:
        command: Shell command to execute.
        on_stdout: Async callback for each stdout line.
        on_stderr: Async callback for each stderr line.
        timeout: Command timeout in seconds.

    Returns:
        Dict with exit_code, stdout, stderr.
    """
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def read_stream(stream, buffer, callback):
            """Read lines from a stream and invoke callback."""
            while True:
                line = await stream.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip("\n")
                buffer.append(decoded)
                if callback:
                    try:
                        await callback(decoded)
                    except Exception as e:
                        logger.warning("Callback error: %s", e)

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    read_stream(process.stdout, stdout_lines, on_stdout),
                    read_stream(process.stderr, stderr_lines, on_stderr),
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return {
                "exit_code": -1,
                "stdout": "\n".join(stdout_lines),
                "stderr": "\n".join(stderr_lines) + "\n[TIMEOUT]",
            }

        await process.wait()

        return {
            "exit_code": process.returncode,
            "stdout": "\n".join(stdout_lines),
            "stderr": "\n".join(stderr_lines),
        }

    except Exception as e:
        logger.error("Command execution failed: %s", e)
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e),
        }
