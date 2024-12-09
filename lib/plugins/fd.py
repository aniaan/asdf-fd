import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
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
)
