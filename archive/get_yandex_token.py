"""
Получение токена Яндекс.Музыки.

Запуск:
    python get_yandex_token.py

Введи логин и пароль от аккаунта Яндекса.
Если включена двухфакторная аутентификация — скрипт попросит код.
"""

def main():
    try:
        from yandex_music import Client
    except ImportError:
        print("Устанавливаю yandex-music...")
        import subprocess, sys
        subprocess.check_call([sys.executable, "-m", "pip", "install", "yandex-music"])
        from yandex_music import Client

    print("\n=== Получение токена Яндекс.Музыки ===\n")
    login = input("Логин (email или телефон): ").strip()
    password = input("Пароль: ").strip()

    try:
        client = Client.from_credentials(login, password)
        token = client.token
        print("\n✓ Токен получен!\n")
        print(f"YANDEX_MUSIC_TOKEN={token}")
        print("\nДобавь эту строку в Railway → Variables (или в .env файл).\n")

        # Проверка подписки
        status = client.account_status()
        plus = getattr(getattr(status, "plus", None), "has_plus", None)
        if plus:
            print("✓ Яндекс Плюс активен — будет 320 kbps")
        else:
            print("△ Яндекс Плюс не обнаружен — качество может быть ниже 320 kbps")

    except Exception as e:
        msg = str(e)
        if "invalid_credentials" in msg or "Bad credentials" in msg.lower():
            print("\n✗ Неверный логин или пароль.")
        elif "captcha" in msg.lower():
            print("\n✗ Яндекс требует капчу. Попробуй:\n"
                  "  1. Войди через браузер на music.yandex.ru\n"
                  "  2. Реши капчу там\n"
                  "  3. Запусти скрипт снова")
        else:
            print(f"\n✗ Ошибка: {e}")
            print("\nАльтернатива — токен через браузер:\n"
                  "  1. Открой music.yandex.ru (авторизован)\n"
                  "  2. F12 → Console → вставь:\n"
                  '     document.cookie.match(/Session_id=([^;]+)/)?.[1]\n'
                  "  3. Полученная строка — не токен, нужен OAuth.\n"
                  "  4. Открой: https://oauth.yandex.ru/authorize"
                  "?response_type=token&client_id=23cabbbdc6cd418abb4b39c32c41195d\n"
                  "  5. Авторизуйся, скопируй access_token из URL.")


if __name__ == "__main__":
    main()
