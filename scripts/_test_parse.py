"""Quick test for parse_query and speller."""
import sys
sys.path.insert(0, "/app")
from bot.services.search_engine import parse_query

tests = [
    "песня руки вверх 18 мне уже",
    "скачать кино группа крови",
    "найди пропаганда яблоки",
    "Кино - Группа крови",
    "bass boost remix скриптонит",
    "слушать макан спарта",
    "включи земфиру",
]
for q in tests:
    p = parse_query(q)
    print(f"  Q: {q!r}")
    print(f"    clean={p['clean']!r}  artist={p.get('artist_hint')!r}  title={p.get('title_hint')!r}")
