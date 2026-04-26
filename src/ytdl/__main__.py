"""Allow running as python -m ytdl."""

import sys

from ytdl.cli import main

sys.exit(main())
