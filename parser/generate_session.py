"""
Утилита для получения PYROGRAM_SESSION_STRING.
Запуск: python -m parser.generate_session
Результат скопировать в .env как PYROGRAM_SESSION_STRING=...
"""
import asyncio


async def main() -> None:
    try:
        from pyrogram import Client
    except ImportError:
        print("Установи pyrogram: pip install pyrogram TgCrypto")
        return

    api_id = int(input("Введи API_ID (с my.telegram.org): ").strip())
    api_hash = input("Введи API_HASH: ").strip()

    async with Client("temp_session", api_id=api_id, api_hash=api_hash) as app:
        session_string = await app.export_session_string()

    print("\n✅ Готово! Добавь в .env:\n")
    print(f"PYROGRAM_SESSION_STRING={session_string}\n")


if __name__ == "__main__":
    asyncio.run(main())
