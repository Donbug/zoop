"""Test-only injection of the existing round clock seam; production HTTP and native commands."""
import sys
from datetime import datetime
from pathlib import Path

from zoop_ai_service import main
from zoop_ai_service.round_service import RoundService

clock_path = Path(sys.argv[1])
original = RoundService.__init__


def initialize(self, *args, **kwargs):
    kwargs["clock"] = lambda: datetime.fromisoformat(clock_path.read_text()).timestamp()
    original(self, *args, **kwargs)


RoundService.__init__ = initialize
raise SystemExit(main.main())
