from pathlib import Path

from cc_common.test_shared_handlers import install_shared_handler_fallback

install_shared_handler_fallback(Path(__file__).resolve().parent)
