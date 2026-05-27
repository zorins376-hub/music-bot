import sys, os
sys.path.insert(0, "/app")
os.chdir("/app")
from bot.services.search_engine import parse_query

tests = [
    "песня руки вверх 18 мне уже",
    "скачать кино группа крови",
    "найди пропаганда яблоки",
    "Кино - Группа крови",
    "bass boost remix скриптонит",
    "слушать макан спарта",
    "включи земфиру",
    "нурминский купить кайф",
]
for q in tests:
    p = parse_query(q)
    print(f"Q: {q}")
    print(f"  -> clean={p['clean']}  artist={p.get('artist_hint')}  title={p.get('title_hint')}")
    print()
