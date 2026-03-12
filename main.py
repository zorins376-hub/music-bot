#!/usr/bin/env python3
"""
Railway entrypoint - runs the bot by default.

For webapp, use: uvicorn webapp.api:app --host 0.0.0.0 --port $PORT
"""

if __name__ == "__main__":
    from bot.main import main
    import asyncio
    asyncio.run(main())
