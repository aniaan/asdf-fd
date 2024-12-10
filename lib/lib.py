import json
import platform
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Literal, TypedDict, Union
from urllib.error import URLError
from urllib.request import urlopen
import sys
import os

PlatformType = Literal["darwin", "linux"]
ArchType = Literal["x86_64", "aarch64"]


class FormatKwargs(TypedDict):
    name: str
    repo_name: str
    version: str
    normalize_version: str
    platform: str
    arch: str
    filename: str
    checksum_filename: str


LibTemplate = Union[str, Callable[[FormatKwargs], str]]


@dataclass(kw_only=True)
class Plugin:
    name: str
    cmd: str
    repo_name: str
    filename_template: LibTemplate = ""
    checksum_filename_template: LibTemplate = ""
    bin_path: LibTemplate = ""
    platform_map: dict[PlatformType, str] = None
    arch_map: dict[ArchType, str] = None
    recover_raw_version: Callable[[str], str] = lambda x: x
    custom_copy: Callable[["Plugin", Path, Path, FormatKwargs], None] = None


def get_plugin(plugin_name: str) -> Plugin:
    plugin_config_path = Path(__file__).parent / "plugins" / f"{plugin_name}.py"

    if not plugin_config_path.exists():
        raise Exception(f"Plugin config not found: {plugin_name}")

    import importlib.util

    spec = importlib.util.spec_from_file_location("plugin_config", plugin_config_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module.PLUGIN


API_RELEASE_URL = "https://api.github.com/repos/{repo_name}/releases"
GITHUB_URL = "https://github.com/{repo_name}"
DOWNLOAD_BASE_URL = GITHUB_URL + "/releases/download/{version}"
BINARY_URL = DOWNLOAD_BASE_URL + "/{filename}"
CHECKSUM_URL = DOWNLOAD_BASE_URL + "/{checksum_filename}"


def list_version(plugin_name: str) -> List[str]:
    plugin = get_plugin(plugin_name)
    url = API_RELEASE_URL.format(repo_name=plugin.repo_name)

    try:
        with urlopen(url) as response:
            releases = json.loads(response.read())

        sorted_releases = sorted(
            releases,
            key=lambda x: datetime.strptime(x["published_at"], "%Y-%m-%dT%H:%M:%SZ"),
            reverse=True,
        )

        recent_versions = sorted_releases[:10]

        versions = [release["tag_name"].lstrip("v") for release in recent_versions]
        versions = list(reversed(versions))

        return "\n".join(versions)

    except URLError as e:
        raise Exception(f"get version failed: {str(e)}")


def get_system_info() -> tuple[PlatformType, ArchType]:
    system = platform.system().lower()
    if system == "darwin":
        plat = "darwin"
    elif system == "linux":
        plat = "linux"
    else:
        raise Exception(f"Unsupported platform: {system}")

    machine = platform.machine().lower()
    if machine in ["x86_64", "amd64"]:
        arch = "x86_64"
    elif machine in ["arm64", "aarch64"]:
        arch = "aarch64"
    else:
        raise Exception(f"Unsupported architecture: {machine}")

    return plat, arch


def get_normalize_version(version: str) -> str:
    return version.lstrip("v")


def verify_checksum(file_path: Path, checksum_path: Path) -> bool:
    with open(checksum_path) as f:
        expected = None
        for line in f:
            if file_path.name in line:
                expected = line.split()[0]
                break
        if not expected:
            raise Exception(f"Checksum not found for {file_path.name}")

    cmd = ["shasum", "-a", "256"] if shutil.which("shasum") else ["sha256sum"]
    result = subprocess.run([*cmd, file_path], capture_output=True, text=True)
    actual = result.stdout.split()[0]

    return actual == expected


def format_template(template: LibTemplate, format_kwargs: FormatKwargs) -> str:
    if callable(template):
        return template(format_kwargs)
    return template.format(**format_kwargs)


def install_version(plugin_name: str, normalize_version: str, install_path: str):
    plugin = get_plugin(plugin_name)
    plat, arch = get_system_info()

    platform_name = plugin.platform_map[plat] if plugin.platform_map else plat
    arch_name = plugin.arch_map[arch] if plugin.arch_map else arch

    version = plugin.recover_raw_version(normalize_version)

    format_kwargs: FormatKwargs = {
        "name": plugin.name,
        "repo_name": plugin.repo_name,
        "version": version,
        "normalize_version": normalize_version,
        "platform": platform_name,
        "arch": arch_name,
        "filename": "",
        "checksum_filename": "",
    }

    filename = format_template(plugin.filename_template, format_kwargs)
    format_kwargs["filename"] = filename
    checksum_filename = format_template(
        plugin.checksum_filename_template, format_kwargs
    )
    format_kwargs["checksum_filename"] = checksum_filename

    bin_path = format_template(plugin.bin_path, format_kwargs)

    download_url = BINARY_URL.format(
        **format_kwargs,
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        download_path = tmp_path / filename

        print(f"Downloading {download_url}...")
        with urlopen(download_url) as response:
            download_path.write_bytes(response.read())

        if plugin.checksum_filename_template:
            checksum_url = CHECKSUM_URL.format(
                **format_kwargs,
            )
            checksum_path = tmp_path / checksum_filename

            print(f"Downloading checksum file {checksum_url}...")
            with urlopen(checksum_url) as response:
                checksum_path.write_bytes(response.read())

            print("Verifying checksum...")
            if not verify_checksum(download_path, checksum_path):
                raise Exception("Checksum verification failed")

            print("Checksum verification passed")

        extract_path = tmp_path / "extract"
        extract_path.mkdir(exist_ok=True)

        if filename.endswith(".tar.gz"):
            with tarfile.open(download_path, mode="r:gz") as tar:
                tar.extractall(extract_path, filter="data")
        elif filename.endswith(".gz"):
            import gzip

            dst = extract_path / bin_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(download_path, "rb") as f_in:
                dst.write_bytes(f_in.read())
        else:
            raise Exception(f"Unsupported file type: {filename}")

        if not plugin.custom_copy:
            print("Using default copy function...")
            src = extract_path / bin_path
            if not src.exists():
                raise Exception(f"Binary file not found: {src}")

            dst = Path(install_path) / "bin"
            dst.mkdir(parents=True, exist_ok=True)
            dst = dst / plugin.cmd

            shutil.copy2(src, dst)
            dst.chmod(0o755)
        else:
            print("Using custom copy function...")
            plugin.custom_copy(plugin, extract_path, Path(install_path), format_kwargs)

    print("Installation completed successfully!")


def main():
    if len(sys.argv) < 3:
        print("Usage:")
        print("  list <plugin_name>")
        print("  install <plugin_name> <version> <install_path>")
        sys.exit(1)

    command = sys.argv[1]
    plugin_name = sys.argv[2]

    if command == "list":
        print(list_version(plugin_name))
    elif command == "install":
        if len(sys.argv) != 5:
            print("Usage: install <plugin_name> <version> <install_path>")
            sys.exit(1)
        version = sys.argv[3]
        install_path = os.path.abspath(sys.argv[4])
        install_version(plugin_name, version, install_path)
    else:
        print(f"Unknown command: {command}")
        print("Available commands: list, install")
        sys.exit(1)


if __name__ == "__main__":
    main()
