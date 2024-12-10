import sys
from pathlib import Path


parent_dir = Path(__file__).parent.parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from lib.lib import Plugin

PLUGIN = Plugin(
    name="fd",
    cmd="fd",
    repo_name="sharkdp/fd",
    filename_template="fd-{version}-{arch}-{platform}.tar.gz",
    platform_map={
        "darwin": "apple-darwin",
        "linux": "unknown-linux-gnu",
    },
    bin_path=lambda kwargs: f"{kwargs['filename'].rstrip('.tar.gz')}/fd",
    recover_raw_version=lambda x: f"v{x}",
)
