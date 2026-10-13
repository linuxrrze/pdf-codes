"""Locate Java and the optional Java components (KoSIT validator, XRechnung configuration, CII→UBL converter).

The components are downloaded by ``code-tools-setup-java`` into ``~/.cache/code-tools`` at pinned versions with
SHA-256 checksums. Each can be overridden with an environment variable pointing at an existing copy.
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
from dataclasses import dataclass

from ..core.output import ToolError


@dataclass(frozen=True)
class Component:
    key: str
    description: str
    url: str
    sha256: str
    target: str  # file name (jar) or directory name (unzipped archive) inside the cache
    env: str
    unzip: bool = False


COMPONENTS = {
    "kosit": Component(
        key="kosit",
        description="KoSIT validator 1.6.3",
        url="https://github.com/itplr-kosit/validator/releases/download/v1.6.3/validator-1.6.3-standalone.jar",
        sha256="799e64befca97d4080e03608c80b85dd5a5ecc5f4ae4f35d1116ec2855b9a7c9",
        target="validator-1.6.3-standalone.jar",
        env="CODE_TOOLS_KOSIT_JAR",
    ),
    "xrechnung-config": Component(
        key="xrechnung-config",
        description="XRechnung 3.0.2 validator configuration 2026-08-31",
        url="https://github.com/itplr-kosit/validator-configuration-xrechnung/releases/download/v2026-08-31/"
            "xrechnung-3.0.2-validator-configuration-2026-08-31.zip",
        sha256="2530cd107c414511c5d0462ec10f886910395abfca820db82e83d70bf01221a8",
        target="xrechnung-3.0.2-validator-configuration-2026-08-31",
        env="CODE_TOOLS_XR_CONFIG",
        unzip=True,
    ),
    "cii2ubl": Component(
        key="cii2ubl",
        description="phax en16931-cii2ubl 4.0.1",
        url="https://github.com/phax/en16931-cii2ubl/releases/download/en16931-cii2ubl-parent-pom-4.0.1/"
            "en16931-cii2ubl-cli-4.0.1-shaded.jar",
        sha256="1dee7e711cb861c10365467f1b4138ecb4bfc01c499d8a30235c28252ed795b3",
        target="en16931-cii2ubl-cli-4.0.1-shaded.jar",
        env="CODE_TOOLS_CII2UBL_JAR",
    ),
}

MIN_JAVA = 17


def cache_dir() -> pathlib.Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return pathlib.Path(base) / "code-tools"


def find_java() -> str:
    candidates = [os.environ.get("CODE_TOOLS_JAVA")]
    if os.environ.get("JAVA_HOME"):
        candidates.append(os.path.join(os.environ["JAVA_HOME"], "bin", "java"))
    candidates.append(shutil.which("java"))
    for java in candidates:
        if java and os.path.isfile(java) and os.access(java, os.X_OK):
            _check_version(java)
            return java
    raise ToolError(f"Java {MIN_JAVA}+ is required but was not found "
                    "(install it, or set JAVA_HOME or CODE_TOOLS_JAVA)")


def _check_version(java: str) -> None:
    try:
        proc = subprocess.run([java, "-version"], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ToolError(f"cannot run {java}: {exc}") from exc
    m = re.search(r'version "(\d+)(?:\.(\d+))?', proc.stderr + proc.stdout)
    if not m:
        return  # unusual vendor banner; let the jar complain if it really is too old
    major = int(m.group(1))
    if major == 1 and m.group(2):  # "1.8.0_x" style
        major = int(m.group(2))
    if major < MIN_JAVA:
        raise ToolError(f"{java} is Java {major}; Java {MIN_JAVA}+ is required")


def component_path(key: str) -> pathlib.Path:
    comp = COMPONENTS[key]
    override = os.environ.get(comp.env)
    path = pathlib.Path(override) if override else cache_dir() / comp.target
    if not path.exists():
        hint = f"set {comp.env}" if override else "run code-tools-setup-java"
        raise ToolError(f"{comp.description} not found at {path} ({hint})")
    return path


def run_jar(jar: pathlib.Path, args: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    java = find_java()
    try:
        return subprocess.run([java, "-jar", str(jar), *args], capture_output=True, text=True, timeout=timeout,
                              check=False)
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"{jar.name} did not finish within {timeout}s") from exc
