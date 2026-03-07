from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def is_windows_signable(path: Path) -> bool:
    return path.suffix.lower() in {".exe", ".dll", ".msi", ".sys"}


def find_artifacts_for_windows_signing(root: Path) -> list[Path]:
    candidates = [path for path in root.rglob("*") if path.is_file() and is_windows_signable(path)]
    return sorted(candidates)


def find_artifacts_for_gpg(root: Path) -> list[Path]:
    ignored_suffixes = {".sig", ".asc"}
    files = [path for path in root.rglob("*") if path.is_file() and path.suffix.lower() not in ignored_suffixes]
    return sorted(files)


def sign_windows_artifact(
    artifact: Path,
    *,
    signtool: str,
    timestamp_url: str,
    certificate_file: str | None = None,
    certificate_password: str | None = None,
    subject_name: str | None = None,
    digest: str = "SHA256",
) -> None:
    command = [signtool, "sign", "/fd", digest]
    if timestamp_url:
        command.extend(["/tr", timestamp_url, "/td", digest])
    if certificate_file:
        command.extend(["/f", certificate_file])
        if certificate_password:
            command.extend(["/p", certificate_password])
    elif subject_name:
        command.extend(["/n", subject_name])
    else:
        raise ValueError("either certificate_file or subject_name must be provided for signtool signing")
    command.append(str(artifact))
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise SystemExit(
            f"signtool signing failed for {artifact}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )


def verify_windows_artifact(artifact: Path, *, signtool: str) -> None:
    completed = subprocess.run([signtool, "verify", "/pa", str(artifact)], capture_output=True, text=True)
    if completed.returncode != 0:
        raise SystemExit(
            f"signtool verification failed for {artifact}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )


def gpg_detach_sign(
    artifact: Path,
    *,
    gpg: str = "gpg",
    homedir: str | None = None,
    passphrase: str | None = None,
) -> Path:
    signature_path = artifact.with_suffix(artifact.suffix + ".sig")
    command = [gpg, "--batch", "--yes", "--armor", "--detach-sign", "--output", str(signature_path), str(artifact)]
    if passphrase:
        command[1:1] = ["--pinentry-mode", "loopback", "--passphrase", passphrase]
    env = os.environ.copy()
    if homedir:
        env["GNUPGHOME"] = homedir
    completed = subprocess.run(command, capture_output=True, text=True, env=env)
    if completed.returncode != 0:
        raise SystemExit(
            f"gpg signing failed for {artifact}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return signature_path


def verify_gpg_signature(signature_path: Path, artifact: Path, *, gpg: str = "gpg", homedir: str | None = None) -> None:
    env = os.environ.copy()
    if homedir:
        env["GNUPGHOME"] = homedir
    completed = subprocess.run([gpg, "--verify", str(signature_path), str(artifact)], capture_output=True, text=True, env=env)
    if completed.returncode != 0:
        raise SystemExit(
            f"gpg verification failed for {artifact}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )


def require_signtool() -> str:
    tool = shutil.which("signtool")
    if not tool:
        raise SystemExit("signtool is required for Windows code signing. Install the Windows SDK signing tools and make signtool available on PATH.")
    return tool


def require_gpg() -> str:
    tool = shutil.which("gpg")
    if not tool:
        raise SystemExit("gpg is required for detached release signatures. Install GnuPG and make gpg available on PATH.")
    return tool
