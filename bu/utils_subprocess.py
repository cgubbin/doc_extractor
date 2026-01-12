from __future__ import annotations
import subprocess
from dataclasses import dataclass
from typing import Sequence, Optional


@dataclass
class CmdResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


def run_cmd(args: Sequence[str], cwd: Optional[str] = None) -> CmdResult:
    p = subprocess.run(
        list(args),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return CmdResult(
        args=list(args), returncode=p.returncode, stdout=p.stdout, stderr=p.stderr
    )


def require_ok(res: CmdResult, context: str) -> None:
    if res.returncode != 0:
        raise RuntimeError(
            f"{context} failed (code {res.returncode}).\n"
            f"Command: {' '.join(res.args)}\n"
            f"STDERR: {res.stderr.strip()}"
        )
