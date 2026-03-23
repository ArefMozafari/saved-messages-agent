#!/usr/bin/env python3
"""Entry point — python run.py"""

import asyncio
from src.config import Settings
from src.main import Agent


def main() -> None:
    settings = Settings.from_env()
    agent = Agent(settings)
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
