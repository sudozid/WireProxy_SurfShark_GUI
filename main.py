"""Main entry point for WireProxy SurfShark GUI application."""

import sys
import logging

# Configure proper logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Import the main application manager
from app import WireproxyManager
import constants


def main():
    """Application entry point"""
    import argparse
    parser = argparse.ArgumentParser(description="Wireproxy Manager")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode without GUI")
    args = parser.parse_args()

    try:
        app = WireproxyManager()
        if args.headless:
            app.run_headless()
        else:
            app.run()
    except Exception as e:
        logger.exception(constants.LOG_FATAL_ERROR)
        if not args.headless:
            try:
                import tkinter.messagebox as mb
                mb.showerror(constants.FATAL_ERROR_TITLE, constants.FATAL_ERROR_MESSAGE.format(error=str(e)))
            except:
                print(f"Fatal error: {e}")
        else:
            print(f"Fatal error: {e}")


if __name__ == "__main__":
    main()