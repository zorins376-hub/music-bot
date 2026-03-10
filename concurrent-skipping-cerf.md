# ТЕХНИЧЕСКОЕ ЗАДАНИЕ: Миграция рекомендательной системы BLACK ROOM RADIO BOT с SQL на ML

**Версия документа:** 1.0
**Дата:** 2026-03-10
**Проект:** BLACK ROOM RADIO BOT -- Telegram-бот для поиска и прослушивания музыки
**Цель:** Переход рекомендательной системы с SQL-based collaborative filtering на гибридную ML-систему с использованием implicit/LightFM + Word2Vec эмбеддингов треков

---

## 1. ОБЩЕЕ ОПИСАНИЕ

### 1.1 Описание задачи

Текущая рекомендательная система (`recommender/ai_dj.py`, 311 строк) использует чистый SQL для коллаборативной и контент-фильтрации. Необходимо заменить ядро на ML-модели, сохранив обратную совместимость API и обеспечив graceful fallback на текущий SQL-алгоритм при недоступности моделей.

### 1.2 Текущее состояние

**Файловая структура рекомендательной подсистемы:**

| Файл | Строк | Назначение |
|---|---|---|
| `recommender/ai_dj.py` | 311 | Ядро: collaborative + content-based + fallback |
| `recommender/__init__.py` | 1 | Пустой модуль |
| `bot/handlers/recommend.py` | 220 | Хэндлер /recommend + onboarding (3 шага) |
| `bot/handlers/mix.py` | 280 | Хэндлер /mix (daily mix) |
| `bot/services/daily_mix.py` | 107 | Построение daily mix из favorites + top artists |
| `bot/handlers/search.py:1182-1259` | ~77 | handle_similar -- поиск похожих треков через YouTube/Yandex |
| `tests/test_ai_dj.py` | 161 | Unit-тесты текущей системы |

**Текущий алгоритм** (из `recommender/ai_dj.py`):

1. Строка 34-51: Проверка Redis-кеша `reco:{user_id}` (TTL 3600 сек)
2. Строка 54-117: `_build_recommendations()` -- основная логика:
   - Строка 62-68: подсчет play_count пользователя
   - Строка 71-78: получение listened_ids (set прослушанных track_id)
   - Строка 87-88: collaborative filtering при play_count >= 50 (`_MIN_PLAYS_FOR_COLLAB = 50`, строка 24)
   - Строка 91: content-based filtering по fav_genres/fav_artists
   - Строка 94-104: слияние 60% collaborative + 40% content-based
   - Строка 107-116: дедупликация по source_id
3. Строка 120-159: `_collaborative()` -- SQL JOIN по shared tracks (порог 3+, лимит 50 users)
4. Строка 162-209: `_content_based()` -- SQL фильтрация по genre/artist, ранжирование по downloads
5. Строка 212-244: `_popular_fallback()` -- топ популярных за 7 дней
6. Строка 261-311: `update_user_profile()` -- ручной пересчет avg_bpm + fav_genres

**Текущий "Similar Tracks"** (`bot/handlers/search.py:1182-1259`):
- Строки 1206-1209: Формирует поисковый запрос из artist + genre трека
- Строки 1218-1226: Ищет через YouTube API + Yandex Music
- Нет track-to-track similarity -- просто текстовый поиск по метаданным

**Модели данных:**

- `User` (`bot/models/user.py`): поля fav_genres (JSON), fav_artists (JSON), fav_vibe (str), avg_bpm (int), onboarded (bool)
- `Track` (`bot/models/track.py:9-31`): source_id, source, title, artist, genre, bpm, duration, file_id, downloads
- `ListeningHistory` (`bot/models/track.py:34-54`): user_id, track_id, query, action (play/skip/like/dislike), listen_duration, source (search/radio/automix/recommend), created_at. Индекс: `(user_id, action, created_at DESC)`

**Автоматическое обновление профиля** (`bot/handlers/search.py:880-894`):
- Вызывается каждые 10 запросов (по `request_count % 10 == 0`), но ненадежно -- привязано к `_post_download`, не к play-событиям

### 1.3 Ключевые ограничения текущей системы

1. SQL collaborative filtering `_collaborative()` выполняет O(n*m) JOIN -- не масштабируется при 10K+ пользователей
2. Нет track-to-track similarity (handle_similar делает текстовый поиск по YouTube)
3. Нет учета временных паттернов (утро vs ночь)
4. Нет взвешенных implicit signals (skip и play имеют одинаковый вес)
5. Нет diversity enforcement (может вернуть 10 треков одного артиста)
6. Cold start: пользователи с <50 play получают только content-based или fallback
7. Профиль обновляется нерегулярно (каждые 10 request_count, а не play-событий)

---

## 2. КОМПОНЕНТ A: TRAINING PIPELINE

### 2.1 Описание задачи

Создать пайплайн обучения ML-моделей, извлекающий матрицу взаимодействий из `ListeningHistory`, обучающий ALS-модель (implicit) и Word2Vec-эмбеддинги треков, с сохранением артефактов и метрик.

### 2.2 Текущее состояние

Обучения моделей не существует. Все расчеты выполняются в реальном времени SQL-запросами в `_collaborative()` (строки 120-159 `recommender/ai_dj.py`).

### 2.3 Архитектурное решение

#### 2.3.1 Извлечение данных

Из таблицы `listening_history` извлекаются все записи с `track_id IS NOT NULL`. Формируется разреженная матрица user-item взаимодействий с взвешенным implicit feedback:

| Action | Вес | Обоснование |
|--------|-----|-------------|
| play | 1.0 | Базовый сигнал |
| like | 2.0 | Сильный позитивный сигнал (FeedbackCallback.act="like") |
| dislike | -1.0 | Негативный сигнал (записывается через FeedbackCallback.act="dislike") |
| skip | 0.3 | Слабый позитивный сигнал (трек был в потоке, но пользователь пропустил) |

Дополнительно: если `listen_duration IS NOT NULL` и `Track.duration IS NOT NULL`, вычисляется коэффициент прослушивания = `listen_duration / Track.duration`. При коэффициенте > 0.8 вес play умножается на 1.5 (полное прослушивание), при < 0.3 -- умножается на 0.5 (частичное).

#### 2.3.2 Построение матрицы

```python
# Псевдокод: извлечение и построение CSR-матрицы
import scipy.sparse as sp
import numpy as np

# Маппинг внутренних ID
user_ids -> user_idx (0..N_users-1)
track_ids -> track_idx (0..N_tracks-1)

# Фильтр: только треки с file_id IS NOT NULL (рекомендабельные)
# Фильтр: только треки, у которых Track.file_id is not None

# Построение COO -> CSR
interaction_matrix = sp.csr_matrix(
    (weights, (user_indices, track_indices)),
    shape=(n_users, n_tracks)
)
```

#### 2.3.3 Обучение ALS

Библиотека `implicit` (AlternatingLeastSquares):

```python
from implicit.als import AlternatingLeastSquares

model = AlternatingLeastSquares(
    factors=64,           # размерность эмбеддинга
    regularization=0.01,
    iterations=15,
    calculate_training_loss=True,
    use_gpu=False,        # CPU only для VPS
)
model.fit(interaction_matrix)
```

Параметры выбраны для баланса качества и скорости на CPU-only сервере (Railway/Docker).

#### 2.3.4 Обучение Word2Vec-эмбеддингов

Сессии определяются как последовательности play-событий одного пользователя с интервалом <= 30 минут (по `created_at`). Каждая сессия -- это список `source_id` треков в порядке прослушивания.

```python
from gensim.models import Word2Vec

# sessions = [["track_a", "track_b", "track_c"], ...]
w2v_model = Word2Vec(
    sentences=sessions,
    vector_size=64,
    window=5,
    min_count=2,     # трек должен появиться минимум 2 раза
    sg=1,            # Skip-gram (лучше для малых данных)
    workers=2,
    epochs=10,
)
```

#### 2.3.5 Метрики

На этапе обучения вычисляются offline-метрики:
- **Precision@10**: доля рекомендованных треков, которые пользователь реально слушал
- **Recall@10**: доля прослушанных треков, которые были в рекомендациях
- **Coverage**: процент каталога треков, попавших хотя бы в одну рекомендацию
- **Novelty**: средний "возраст" рекомендованных треков

Для вычисления используется train/test split по времени: 80% данных -- train, 20% последних по времени -- test.

#### 2.3.6 Расписание

Cron-задача (asyncio-loop по паттерну `_digest_loop` из `bot/services/daily_digest.py:22-37`):
- Запуск: ежедневно в 04:00 UTC (низкая нагрузка)
- Минимальный порог: переобучение только если >= 100 новых interactions с момента последнего обучения
- Таймаут: 10 минут (при превышении -- логирование ошибки, использование предыдущей модели)

### 2.4 Новые файлы

| Файл | ~Строк | Описание |
|------|--------|----------|
| `recommender/train.py` | ~350 | Пайплайн обучения: извлечение данных, построение матрицы, обучение ALS + W2V, метрики |
| `recommender/data_extractor.py` | ~150 | Извлечение и предобработка данных из БД, построение сессий |

### 2.5 Изменения в существующих файлах

| Файл | Строки | Изменение |
|------|--------|-----------|
| `bot/main.py` | После строки 101 | Добавить запуск scheduler для training loop (по аналогии с `start_weekly_recap_scheduler`) |
| `requirements.txt` | Новые строки | Добавить `implicit>=0.7.0`, `gensim>=4.3.0`, `scipy>=1.11.0`, `numpy>=1.24.0` |
| `Dockerfile` | Строка 15 | requirements.txt уже копируется и устанавливается, изменений не нужно |

### 2.6 Модели данных

**Новая таблица `ml_training_log`:**

```python
class MLTrainingLog(Base):
    __tablename__ = "ml_training_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_type: Mapped[str] = mapped_column(String(20))  # "als" | "w2v"
    version: Mapped[int] = mapped_column(Integer)
    n_users: Mapped[int] = mapped_column(Integer)
    n_tracks: Mapped[int] = mapped_column(Integer)
    n_interactions: Mapped[int] = mapped_column(Integer)
    precision_at_10: Mapped[float | None] = mapped_column(Float, nullable=True)
    recall_at_10: Mapped[float | None] = mapped_column(Float, nullable=True)
    coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    training_time_sec: Mapped[float] = mapped_column(Float)
    model_path: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
```

**Хранилище моделей на диске:**

```
data/models/
  als/
    model_v001.npz     # ALS модель (numpy arrays)
    mappings_v001.json  # user_id -> idx, track_id -> idx маппинги
    latest.txt          # "001" -- указатель на текущую версию
  w2v/
    model_v001.bin      # Word2Vec модель (gensim native format)
    latest.txt
```

Директория `data/` уже существует и монтируется как Docker-volume (`docker-compose.yml:8`: `./data:/app/data`), что обеспечивает персистентность между перезапусками.

### 2.7 Зависимости

```
implicit>=0.7.0        # ALS, BPR для implicit feedback (MIT)
gensim>=4.3.0          # Word2Vec для track embeddings (LGPL)
scipy>=1.11.0          # Sparse matrices (BSD)
numpy>=1.24.0          # Числовые массивы (BSD)
```

### 2.8 Критерии приемки

1. Скрипт `recommender/train.py` запускается автономно: `python -m recommender.train`
2. Обучение на 10K interactions завершается за < 60 сек на CPU
3. Модели сохраняются в `data/models/` с версионированием
4. Метрики логируются в `ml_training_log` и в stdout
5. При пустой БД (< 100 interactions) обучение пропускается с info-логом
6. Scheduler в `bot/main.py` запускается при старте бота

### 2.9 Риски и митигация

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| Недостаточно данных для ALS (< 1000 interactions) | Средняя | Минимальный порог 100 interactions; при недостатке -- skip training, использовать SQL fallback |
| Большое потребление памяти при обучении | Низкая | ALS factors=64 и CSR-матрица; типичный объем при 10K users / 50K tracks ~ 200MB RAM |
| Обучение блокирует event loop | Высокая | Запускать в `asyncio.to_thread()` или `loop.run_in_executor()` (паттерн из `mixer/automix.py:28-31`) |
| LGPL-лицензия gensim | Низкая | Бот приватный, не распространяется как библиотека; допустимо |

---

## 3. КОМПОНЕНТ B: MODEL STORE

### 3.1 Описание задачи

Модуль управления хранением, загрузкой и атомарной заменой обученных моделей без простоя.

### 3.2 Текущее состояние

Хранилища моделей не существует. Все вычисления -- SQL в реальном времени.

### 3.3 Архитектурное решение

```python
class ModelStore:
    """Thread-safe singleton for managing ML model lifecycle."""

    _instance: "ModelStore | None" = None
    _lock: asyncio.Lock

    def __init__(self, base_dir: Path):
        self._base_dir = base_dir  # data/models/
        self._als_model = None
        self._w2v_model = None
        self._user_map: dict[int, int] = {}    # user_id -> matrix idx
        self._track_map: dict[int, int] = {}   # track_id -> matrix idx
        self._track_reverse: dict[int, int] = {}  # matrix idx -> track_id
        self._version: int = 0
        self._lock = asyncio.Lock()

    @classmethod
    def get(cls) -> "ModelStore":
        if cls._instance is None:
            from bot.config import settings
            cls._instance = cls(settings.DATA_DIR / "models")
        return cls._instance

    async def load_latest(self) -> bool:
        """Load latest models from disk. Returns True if loaded."""

    async def swap(self, als_model, w2v_model, user_map, track_map, version):
        """Atomically swap current models with new ones."""
        async with self._lock:
            self._als_model = als_model
            self._w2v_model = w2v_model
            self._user_map = user_map
            self._track_map = track_map
            self._track_reverse = {v: k for k, v in track_map.items()}
            self._version = version

    @property
    def is_ready(self) -> bool:
        return self._als_model is not None

    def get_als_model(self): ...
    def get_w2v_model(self): ...
    def get_user_idx(self, user_id: int) -> int | None: ...
    def get_track_idx(self, track_id: int) -> int | None: ...
    def get_track_id(self, idx: int) -> int | None: ...
```

**Атомарная замена:**
1. Новая модель обучается и сохраняется с version N+1
2. `latest.txt` обновляется только после успешного сохранения
3. `ModelStore.swap()` заменяет in-memory модели под asyncio.Lock
4. Текущие запросы, использующие старую модель, завершаются штатно (swap не блокирует чтение -- новые запросы получат новую модель)

### 3.4 Новые файлы

| Файл | ~Строк | Описание |
|------|--------|----------|
| `recommender/model_store.py` | ~180 | Singleton хранилище моделей: load/save/swap |

### 3.5 Изменения в существующих файлах

| Файл | Строки | Изменение |
|------|--------|-----------|
| `bot/main.py` | Строка 73 (после `await init_db()`) | Добавить `await ModelStore.get().load_latest()` для предзагрузки моделей при старте |

### 3.6 Модели данных

Файловая структура `data/models/` описана в секции 2.6. Формат сохранения:
- ALS: `numpy.savez_compressed()` для user_factors и item_factors
- Word2Vec: `gensim.models.Word2Vec.save()` (native binary)
- Маппинги: `json.dump()` для dict[str, int] (user_id -> idx)

### 3.7 Зависимости

Зависит от `implicit`, `gensim`, `numpy` (уже в секции 2.7).

### 3.8 Критерии приемки

1. `ModelStore.get().load_latest()` загружает модели за < 2 сек
2. `ModelStore.get().swap()` атомарно заменяет модели без блокировки текущих запросов
3. При отсутствии моделей `is_ready` возвращает False, все get-методы возвращают None
4. При повреждении файлов модели -- graceful fallback (is_ready = False), логирование ошибки

### 3.9 Риски и митигация

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| Конкурентный доступ к моделям | Средняя | asyncio.Lock для swap; чтение не блокируется |
| Файлы моделей повреждены | Низкая | try/except при загрузке, is_ready=False, SQL fallback |
| Несовместимость маппингов после обучения | Средняя | Всегда загружать модель + маппинги одной версии атомарно |

---

## 4. КОМПОНЕНТ C: TRACK EMBEDDINGS

### 4.1 Описание задачи

Создать эмбеддинги треков на основе Word2Vec, обученного на сессиях прослушивания. Обеспечить функцию "похожие треки" через cosine similarity в пространстве эмбеддингов.

### 4.2 Текущее состояние

Функция "похожие треки" реализована в `bot/handlers/search.py:1182-1259` (handler `handle_similar`) как текстовый поиск по YouTube/Yandex на основе artist + genre. Нет настоящей track-to-track similarity.

### 4.3 Архитектурное решение

#### 4.3.1 Определение сессий

Сессия -- последовательность play-событий одного пользователя, где каждый следующий `created_at` отличается от предыдущего не более чем на 30 минут.

```python
async def extract_sessions(min_session_len: int = 2) -> list[list[str]]:
    """
    Извлечь сессии прослушивания из ListeningHistory.
    Каждая сессия — список source_id треков.
    """
    # SQL: SELECT user_id, t.source_id, lh.created_at
    #      FROM listening_history lh
    #      JOIN tracks t ON t.id = lh.track_id
    #      WHERE lh.action = 'play' AND lh.track_id IS NOT NULL
    #            AND t.file_id IS NOT NULL
    #      ORDER BY lh.user_id, lh.created_at
    #
    # Разделить на сессии: gap > 30 min -> новая сессия
    # Фильтр: len(session) >= min_session_len
```

#### 4.3.2 Embedding API

```python
class TrackEmbeddings:
    """Wrapper around Word2Vec model for track similarity."""

    def __init__(self, model_store: ModelStore):
        self._store = model_store

    def get_similar_tracks(
        self, source_id: str, topn: int = 20
    ) -> list[tuple[str, float]]:
        """
        Return list of (source_id, similarity_score) pairs.
        Uses Word2Vec most_similar.
        """
        w2v = self._store.get_w2v_model()
        if w2v is None or source_id not in w2v.wv:
            return []
        return w2v.wv.most_similar(source_id, topn=topn)

    def get_track_vector(self, source_id: str) -> np.ndarray | None:
        """Return embedding vector for a track."""
        w2v = self._store.get_w2v_model()
        if w2v is None or source_id not in w2v.wv:
            return None
        return w2v.wv[source_id]

    def get_session_vector(self, source_ids: list[str]) -> np.ndarray | None:
        """Average embedding of a set of tracks (for user taste vector)."""
        vectors = [self.get_track_vector(sid) for sid in source_ids]
        vectors = [v for v in vectors if v is not None]
        if not vectors:
            return None
        return np.mean(vectors, axis=0)
```

#### 4.3.3 Параметры Word2Vec

| Параметр | Значение | Обоснование |
|----------|----------|-------------|
| vector_size | 64 | Оптимально для каталога 10K-100K треков |
| window | 5 | Контекст сессии: 5 соседних треков |
| min_count | 2 | Отсечь треки, проигранные только 1 раз |
| sg | 1 (Skip-gram) | Лучше для редких элементов |
| epochs | 10 | Стандартное значение |
| workers | 2 | Не перегружать VPS |

### 4.4 Новые файлы

| Файл | ~Строк | Описание |
|------|--------|----------|
| `recommender/embeddings.py` | ~120 | TrackEmbeddings: similar tracks, track vectors, session vectors |

Логика извлечения сессий включена в `recommender/data_extractor.py` (описан в секции 2.4).

### 4.5 Изменения в существующих файлах

| Файл | Строки | Изменение |
|------|--------|-----------|
| `bot/handlers/search.py` | Строки 1182-1259 | Рефакторинг `handle_similar()`: сначала пробовать ML-embeddings через `get_similar_tracks()`, затем fallback на текущий текстовый поиск |

### 4.6 Модели данных

Данные хранятся в файлах Word2Vec модели (`data/models/w2v/model_v{N}.bin`). Отдельной таблицы не требуется.

### 4.7 Зависимости

`gensim>=4.3.0` (уже указана в секции 2.7).

### 4.8 Критерии приемки

1. `get_similar_tracks(source_id, topn=20)` возвращает результаты за < 10ms
2. Результаты семантически осмысленны: треки одного жанра/артиста имеют высокий similarity score
3. Треки без эмбеддингов (новые) корректно обрабатываются (пустой список)
4. `handle_similar()` сначала использует ML, при неудаче -- текущий YouTube/Yandex поиск

### 4.9 Риски и митигация

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| Мало сессий для обучения | Средняя | min_count=2 снижает порог; fallback на текстовый поиск |
| Популярные треки доминируют в embedding space | Средняя | Subsampling в Word2Vec (sample=1e-4) для снижения веса частых |
| Новые треки без эмбеддингов | Высокая | Fallback на content-based (genre/artist match) |

---

## 5. КОМПОНЕНТ D: HYBRID SCORER

### 5.1 Описание задачи

Создать единый гибридный скорер, объединяющий сигналы ALS, эмбеддингов, популярности и свежести с настраиваемыми весами и фильтрами разнообразия.

### 5.2 Текущее состояние

Текущее слияние -- простое: 60% collaborative + 40% content-based (строки 94-104 `recommender/ai_dj.py`). Нет scoring, нет diversity, нет time-awareness.

### 5.3 Архитектурное решение

#### 5.3.1 Архитектура скорера

```python
@dataclass
class ScoredTrack:
    track_id: int
    source_id: str
    score: float
    components: dict[str, float]  # для отладки: {"als": 0.8, "emb": 0.3, ...}
    algo: str  # "ml" | "sql" | "popular"

class HybridScorer:
    def __init__(
        self,
        model_store: ModelStore,
        embeddings: TrackEmbeddings,
        weights: ScorerWeights | None = None,
    ):
        self._store = model_store
        self._emb = embeddings
        self._weights = weights or ScorerWeights()

    async def score(
        self,
        user_id: int,
        candidate_ids: list[int],
        context: ScoringContext,
    ) -> list[ScoredTrack]:
        """Score candidates and return sorted by total score."""
```

#### 5.3.2 Компоненты скоринга

| Компонент | Вес (по умолчанию) | Источник | Описание |
|-----------|-------------------|----------|----------|
| ALS score | 0.40 | `implicit` model.recommend() | Коллаборативный сигнал |
| Embedding similarity | 0.25 | Word2Vec cosine similarity к последним N трекам пользователя | Контентный сигнал |
| Popularity | 0.15 | `Track.downloads` нормализованный (0..1) | Популярность |
| Freshness | 0.10 | Bonus для треков с `Track.created_at` < 7 дней | Свежесть контента |
| Time-of-day | 0.10 | Матч с предпочитаемым временем пользователя | Временной паттерн |

#### 5.3.3 Формула

```
total_score = (
    w_als * normalized_als_score +
    w_emb * cosine_similarity_to_user_taste +
    w_pop * log_normalized_downloads +
    w_fresh * freshness_bonus +
    w_time * time_match_bonus
)
```

Где:
- `normalized_als_score`: от model.recommend(), нормализовано к [0,1]
- `cosine_similarity_to_user_taste`: cosine similarity между track embedding и средним embedding последних 50 треков пользователя
- `log_normalized_downloads`: `log(1 + downloads) / log(1 + max_downloads)`
- `freshness_bonus`: 1.0 если трек < 7 дней, линейное затухание до 0.0 к 30 дням
- `time_match_bonus`: сравнение текущего часа UTC с предпочитаемыми часами пользователя (из нового поля `preferred_hours`)

#### 5.3.4 Diversity Filter

После скоринга применяется diversity enforcement:
1. Максимум 2 трека от одного артиста на 10 рекомендаций (настраиваемо)
2. Максимум 3 трека одного жанра на 10 рекомендаций
3. Реализация: greedy selection с проверкой ограничений

```python
def _apply_diversity(
    self,
    scored: list[ScoredTrack],
    limit: int,
    max_per_artist: int = 2,
    max_per_genre: int = 3,
) -> list[ScoredTrack]:
    result = []
    artist_counts: Counter[str] = Counter()
    genre_counts: Counter[str] = Counter()

    for st in scored:
        artist = ...  # получить из БД/кеша
        genre = ...
        if artist_counts[artist] >= max_per_artist:
            continue
        if genre_counts[genre] >= max_per_genre:
            continue
        result.append(st)
        artist_counts[artist] += 1
        genre_counts[genre] += 1
        if len(result) >= limit:
            break
    return result
```

#### 5.3.5 ScoringContext

```python
@dataclass
class ScoringContext:
    current_hour_utc: int          # для time-of-day
    recent_track_ids: list[int]    # последние N треков (для embedding similarity)
    listened_ids: set[int]         # исключить прослушанные
    source: str = "recommend"      # для A/B logging
```

### 5.4 Новые файлы

| Файл | ~Строк | Описание |
|------|--------|----------|
| `recommender/scorer.py` | ~250 | HybridScorer: scoring, diversity, time-awareness |
| `recommender/config.py` | ~80 | ScorerWeights, MLConfig -- dataclasses с настройками |

### 5.5 Изменения в существующих файлах

Нет прямых изменений. Scorer вызывается из рефакторенного `ai_dj.py` (компонент E).

### 5.6 Модели данных

Новый столбец `preferred_hours` в таблице `users` (JSON, опционально):

```python
# В bot/models/user.py, после строки 28 (avg_bpm):
preferred_hours: Mapped[list | None] = mapped_column(JSON, nullable=True)
# Формат: [22, 23, 0, 1] — часы UTC, в которые пользователь чаще всего слушает
```

### 5.7 Зависимости

`numpy` (уже указана), `scipy` (уже указана).

### 5.8 Критерии приемки

1. Scoring 100 кандидатов за < 50ms
2. Diversity filter: в 10 рекомендациях не более 2 треков одного артиста
3. Freshness boost: треки < 7 дней получают бонус >= 0.05
4. Time-of-day: ночью (22:00-04:00) предпочитаются треки с vibe="deep"/"chill"
5. Все веса конфигурируемы без перезапуска (через config dataclass)

### 5.9 Риски и митигация

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| Неоптимальные веса | Высокая | A/B тестирование (компонент G), логирование компонентов score для отладки |
| Diversity filter слишком агрессивен | Средняя | Настраиваемые лимиты; при недостатке кандидатов -- ослабление фильтра |
| Time-of-day не имеет данных | Средняя | Fallback: не применять time бонус, если preferred_hours == None |

---

## 6. КОМПОНЕНТ E: РЕФАКТОРИНГ ai_dj.py

### 6.1 Описание задачи

Рефакторить `recommender/ai_dj.py` для использования ML-моделей с graceful fallback на текущий SQL, сохранив существующий API.

### 6.2 Текущее состояние

Файл `recommender/ai_dj.py` (311 строк) содержит:
- Строки 27-51: `get_recommendations(user_id, limit)` -- публичный API
- Строки 54-117: `_build_recommendations()` -- основная логика
- Строки 120-159: `_collaborative()` -- SQL collaborative filtering
- Строки 162-209: `_content_based()` -- SQL content-based filtering
- Строки 212-244: `_popular_fallback()` -- fallback
- Строки 247-258: `_track_to_dict()` -- конвертация Track -> dict
- Строки 261-311: `update_user_profile()` -- обновление профиля

Все вызывающие модули:
- `bot/handlers/recommend.py:169` -- `get_recommendations(user.id, limit=10)`
- `bot/handlers/search.py:888` -- `update_user_profile(user_id)`

### 6.3 Архитектурное решение

#### 6.3.1 Новая структура ai_dj.py

```python
# recommender/ai_dj.py — Рефакторинг (v3, ML-hybrid)

async def get_recommendations(user_id: int, limit: int = 10) -> list[dict]:
    """Public API — unchanged signature."""
    # 1. Redis cache (existing, unchanged)
    # 2. Try ML recommendations
    # 3. Fallback to SQL recommendations
    # 4. Cache result

async def get_similar_tracks(track_id: int, limit: int = 10) -> list[dict]:
    """NEW: Find tracks similar to given track using embeddings."""
    # 1. Get track source_id from DB
    # 2. Query embeddings.get_similar_tracks()
    # 3. Filter: only tracks with file_id, not blocked
    # 4. Fallback: content-based by genre/artist

async def _build_ml_recommendations(user_id: int, limit: int) -> list[dict]:
    """ML-based recommendations using ALS + HybridScorer."""
    store = ModelStore.get()
    if not store.is_ready:
        return []  # trigger fallback to SQL

    # 1. Get ALS candidates (topN * 3 for diversity headroom)
    # 2. Get context: recent tracks, listened_ids, current hour
    # 3. Score candidates via HybridScorer
    # 4. Apply diversity filter
    # 5. Return top-limit as track dicts

async def _build_recommendations(user_id: int, limit: int) -> list[dict]:
    """EXISTING SQL fallback — renamed but preserved."""
    # Existing logic from lines 54-117 (unchanged)
```

#### 6.3.2 Ключевое изменение: поток выполнения

```
get_recommendations(user_id, limit)
  |
  +-- Redis cache hit? -> return cached
  |
  +-- ML_ENABLED and ModelStore.is_ready?
  |     |
  |     +-- YES -> _build_ml_recommendations()
  |     |           |
  |     |           +-- результат не пуст? -> cache + return
  |     |           +-- пуст? -> fallback ниже
  |     |
  |     +-- NO -> skip
  |
  +-- _build_recommendations()  (SQL fallback, текущая логика)
  |
  +-- cache + return
```

#### 6.3.3 Новая функция `get_similar_tracks()`

```python
async def get_similar_tracks(track_id: int, limit: int = 10) -> list[dict]:
    from recommender.model_store import ModelStore
    from recommender.embeddings import TrackEmbeddings

    store = ModelStore.get()
    if not store.is_ready:
        return []

    # Получить source_id трека
    async with async_session() as session:
        track = await session.get(Track, track_id)
        if not track:
            return []

    emb = TrackEmbeddings(store)
    similar = emb.get_similar_tracks(track.source_id, topn=limit * 2)

    if not similar:
        return []

    # Загрузить треки из БД
    source_ids = [sid for sid, _ in similar]
    async with async_session() as session:
        result = await session.execute(
            select(Track).where(
                Track.source_id.in_(source_ids),
                Track.file_id.is_not(None),
            )
        )
        tracks_by_sid = {t.source_id: t for t in result.scalars().all()}

    # Сохранить порядок по similarity
    result_list = []
    for sid, score in similar:
        if sid in tracks_by_sid:
            d = _track_to_dict(tracks_by_sid[sid])
            d["similarity"] = round(score, 3)
            d["algo"] = "ml_embedding"
            result_list.append(d)
        if len(result_list) >= limit:
            break

    return result_list
```

### 6.4 Новые файлы

Нет (рефакторинг существующего файла).

### 6.5 Изменения в существующих файлах

| Файл | Строки | Изменение |
|------|--------|-----------|
| `recommender/ai_dj.py` | Весь файл | Рефакторинг: добавить `_build_ml_recommendations()`, `get_similar_tracks()`; существующие SQL-функции оставить как fallback |
| `bot/handlers/search.py` | Строки 1182-1259 | Изменить `handle_similar()`: вызывать `get_similar_tracks()` вместо YouTube поиска, fallback на текущую логику |
| `bot/handlers/recommend.py` | Строка 169 | Без изменений (API `get_recommendations()` сохраняется) |

### 6.6 Модели данных

Добавить поле `algo` в `_track_to_dict()`:

```python
def _track_to_dict(track, algo: str = "sql") -> dict:
    d = {
        "video_id": track.source_id,
        "title": track.title or "Unknown",
        "uploader": track.artist or "Unknown",
        "duration": track.duration or 0,
        "duration_fmt": fmt_duration(track.duration),
        "source": track.source or "youtube",
        "file_id": track.file_id,
        "algo": algo,  # NEW: для A/B tracking
    }
    return d
```

### 6.7 Зависимости

Зависит от компонентов B, C, D (ModelStore, TrackEmbeddings, HybridScorer).

### 6.8 Критерии приемки

1. `get_recommendations()` возвращает ML-рекомендации при `ML_ENABLED=True` и наличии моделей
2. При `ML_ENABLED=False` или отсутствии моделей -- полная обратная совместимость с текущим SQL
3. `get_similar_tracks(track_id)` возвращает похожие треки за < 100ms
4. Все существующие тесты в `tests/test_ai_dj.py` проходят без изменений
5. Каждая рекомендация содержит поле `algo` для tracking
6. Redis кеш продолжает работать с тем же ключом `reco:{user_id}`

### 6.9 Риски и митигация

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| Регрессия качества рекомендаций | Средняя | A/B тест (компонент G); параллельная работа ML + SQL с отслеживанием CTR |
| ML-рекомендации пусты для cold users | Высокая | Для пользователей без ALS user_idx -- автоматический fallback на SQL `_build_recommendations()` |
| Сломанные тесты | Низкая | Все SQL-функции сохраняются; ML обернут в `if store.is_ready` |

---

## 7. КОМПОНЕНТ F: AUTO-UPDATE ПРОФИЛЯ

### 7.1 Описание задачи

Автоматический пересчет профиля пользователя после каждых N play-событий. Расширение профиля новыми полями.

### 7.2 Текущее состояние

- `update_user_profile()` в `recommender/ai_dj.py:261-311` -- обновляет только `avg_bpm` и `fav_genres`
- Вызывается из `bot/handlers/search.py:888` каждые 10 запросов (`request_count % 10`), но `request_count` привязан к HTTP-запросам, не к play-событиям
- Не обновляет: `fav_artists`, `preferred_hours`, genre diversity score

### 7.3 Архитектурное решение

#### 7.3.1 Триггер обновления

Интеграция в `bot/db.py:record_listening_event()` (строки 134-156):

```python
async def record_listening_event(...) -> None:
    # ... existing logic ...
    await session.commit()

    # NEW: автообновление профиля каждые 10 play-событий
    if action == "play":
        try:
            play_count = await _get_user_play_count(user_id)
            if play_count > 0 and play_count % 10 == 0:
                from recommender.profile_updater import update_user_profile_full
                asyncio.create_task(update_user_profile_full(user_id))
        except Exception:
            pass
```

#### 7.3.2 Расширенный профиль

```python
async def update_user_profile_full(user_id: int) -> None:
    """Full profile recalculation based on listening history."""
    async with async_session() as session:
        # 1. Top 5 genres (weighted by recency)
        # 2. Top 5 artists (weighted by recency)
        # 3. Avg BPM (last 100 tracks)
        # 4. Preferred hours (top 4 часа UTC по количеству plays)
        # 5. Genre diversity score (Shannon entropy normalized to 0..1)
        # 6. Preferred vibe (based on BPM + genre clusters)

        update_values = {
            "fav_genres": top_genres[:5],
            "fav_artists": top_artists[:5],
            "avg_bpm": avg_bpm,
            "preferred_hours": preferred_hours,  # NEW field
            # genre_diversity_score не сохраняется в User, используется scorer
        }
        await session.execute(
            update(User).where(User.id == user_id).values(**update_values)
        )
        await session.commit()
```

#### 7.3.3 Предпочитаемые часы

```sql
SELECT EXTRACT(HOUR FROM created_at) AS hour, COUNT(*) AS cnt
FROM listening_history
WHERE user_id = :uid AND action = 'play'
GROUP BY hour
ORDER BY cnt DESC
LIMIT 4;
```

Для SQLite (dev): `strftime('%H', created_at)` вместо `EXTRACT`.

#### 7.3.4 Genre Diversity Score

```python
from math import log2

def _genre_diversity(genre_counts: dict[str, int]) -> float:
    """Shannon entropy normalized to [0, 1]."""
    total = sum(genre_counts.values())
    if total == 0 or len(genre_counts) <= 1:
        return 0.0
    entropy = -sum(
        (c / total) * log2(c / total)
        for c in genre_counts.values()
        if c > 0
    )
    max_entropy = log2(len(genre_counts))
    return round(entropy / max_entropy, 3) if max_entropy > 0 else 0.0
```

### 7.4 Новые файлы

| Файл | ~Строк | Описание |
|------|--------|----------|
| `recommender/profile_updater.py` | ~150 | Расширенный update_user_profile_full, genre diversity, preferred hours |

### 7.5 Изменения в существующих файлах

| Файл | Строки | Изменение |
|------|--------|-----------|
| `bot/db.py` | Строки 134-156 (`record_listening_event`) | Добавить trigger автообновления каждые 10 play |
| `bot/models/user.py` | После строки 28 | Добавить `preferred_hours: Mapped[list \| None]` (JSON) |
| `bot/models/base.py` | Строки 62-65 (ALTER для PG) | Добавить `ALTER TABLE users ADD COLUMN IF NOT EXISTS preferred_hours JSONB` |
| `recommender/ai_dj.py` | Строки 261-311 | Пометить `update_user_profile()` как deprecated, перенаправить на `profile_updater.update_user_profile_full()` |
| `bot/handlers/search.py` | Строки 880-894 | Удалить старый вызов `update_user_profile()` (заменен на trigger в db.py) |

### 7.6 Модели данных

Новый столбец в `users`:
- `preferred_hours` (JSON, nullable) -- массив целых [0-23], предпочитаемые часы UTC

### 7.7 Зависимости

Нет новых зависимостей.

### 7.8 Критерии приемки

1. Профиль автоматически обновляется после каждых 10 play-событий
2. fav_artists обновляется (сейчас не обновляется в `update_user_profile`)
3. preferred_hours корректно вычисляется для PG и SQLite
4. Genre diversity > 0.7 для пользователей с разнообразным вкусом
5. Обновление профиля не блокирует ответ пользователю (asyncio.create_task)

### 7.9 Риски и митигация

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| Нагрузка на БД при частом обновлении | Средняя | Каждые 10 play, не каждый; create_task для асинхронности |
| EXTRACT не работает в SQLite (dev) | Высокая | Fallback: strftime('%H', ...) для SQLite; проверка `_is_pg` из base.py:12 |
| fav_genres/artists перезаписывают onboarding | Низкая | Если user.onboarded и данные есть -- обновлять; если onboarding не пройден -- не трогать |

---

## 8. КОМПОНЕНТ G: EVALUATION и A/B TESTING

### 8.1 Описание задачи

Система оценки качества рекомендаций (offline метрики) и A/B тестирование ML vs SQL алгоритмов (online метрики).

### 8.2 Текущее состояние

Никаких метрик рекомендательной системы не собирается. Нет возможности сравнить качество алгоритмов.

### 8.3 Архитектурное решение

#### 8.3.1 Offline Evaluation

Выполняется в рамках training pipeline (компонент A):

```python
async def evaluate_model(
    model,
    train_matrix: sp.csr_matrix,
    test_matrix: sp.csr_matrix,
    k: int = 10,
) -> dict[str, float]:
    """
    Compute offline metrics:
    - precision@k: relevant recommended / k
    - recall@k: relevant recommended / total relevant
    - coverage: unique tracks recommended / total tracks
    """
```

#### 8.3.2 Online A/B Testing

Простое разделение пользователей по `user_id % 2`:
- Группа 0 (четные user_id): ML-рекомендации
- Группа 1 (нечетные user_id): SQL-рекомендации (текущая система)

Управление через feature flag `ML_AB_TEST_ENABLED`.

#### 8.3.3 Логирование рекомендаций

**Новая таблица `recommendation_log`:**

```python
class RecommendationLog(Base):
    __tablename__ = "recommendation_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    track_id: Mapped[int] = mapped_column(Integer, ForeignKey("tracks.id"))
    algo: Mapped[str] = mapped_column(String(20))  # "ml" | "sql" | "popular"
    position: Mapped[int] = mapped_column(Integer)  # позиция в списке (0-indexed)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    clicked: Mapped[bool] = mapped_column(Boolean, default=False)  # обновляется при клике
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_reclog_user_created", "user_id", "created_at"),
        Index("ix_reclog_algo_created", "algo", "created_at"),
    )
```

#### 8.3.4 Click-Through Rate (CTR)

Когда пользователь кликает на трек из рекомендации (обработка в `bot/handlers/recommend.py`), обновляем `clicked = True`.

CTR = clicked / total по algo группе за период.

#### 8.3.5 A/B Dashboard (admin)

Добавить команду `/admin ab` (в `bot/handlers/admin.py`):

```
A/B Рекомендации (7 дней):
─────────────────────────
ML:  показано 1234, кликнуто 456, CTR = 37.0%
SQL: показано 1100, кликнуто 330, CTR = 30.0%
─────────────────────────
Lift: +23.3%
```

### 8.4 Новые файлы

| Файл | ~Строк | Описание |
|------|--------|----------|
| `recommender/evaluation.py` | ~120 | Offline метрики: precision@k, recall@k, coverage |
| `bot/models/recommendation_log.py` | ~40 | SQLAlchemy модель RecommendationLog |

### 8.5 Изменения в существующих файлах

| Файл | Строки | Изменение |
|------|--------|-----------|
| `recommender/ai_dj.py` | Строки 27-51 | В `get_recommendations()`: определить группу A/B и логировать результаты |
| `bot/handlers/recommend.py` | Строки 204-213 | При клике на рекомендованный трек: обновить `clicked=True` в RecommendationLog |
| `bot/handlers/admin.py` | Конец файла | Добавить handler `/admin ab` для A/B дашборда |
| `bot/models/base.py` | Строка 47 | Добавить import RecommendationLog |

### 8.6 Модели данных

Таблица `recommendation_log` (описана в 8.3.3).

### 8.7 Зависимости

Нет новых зависимостей.

### 8.8 Критерии приемки

1. Каждая рекомендация записывается в `recommendation_log` с algo и position
2. Клик пользователя обновляет `clicked = True`
3. `/admin ab` показывает CTR по ML и SQL за 7 дней
4. Offline метрики вычисляются при обучении и записываются в `ml_training_log`
5. A/B группы стабильны (один пользователь всегда в одной группе)

### 8.9 Риски и митигация

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| recommendation_log растет быстро | Средняя | Ротация: удалять записи старше 30 дней (cron) |
| Пользователей мало для статистической значимости | Высокая | A/B тест информативен при >= 100 users/group; при меньшем -- ориентироваться на offline метрики |
| Нечетное разделение user_id % 2 | Низкая | Простое и стабильное; при необходимости -- переход на Redis-based bucket |

---

## 9. КОМПОНЕНТ H: CONFIG и FEATURE FLAGS

### 9.1 Описание задачи

Централизованная конфигурация ML-подсистемы с возможностью runtime-переключения через feature flags.

### 9.2 Текущее состояние

Конфигурация бота -- `bot/config.py` (класс `Settings` на Pydantic, строки 12-112). Нет ML-related настроек.

### 9.3 Архитектурное решение

Расширить `Settings` в `bot/config.py` блоком ML-настроек:

```python
class Settings(BaseSettings):
    # ... existing fields ...

    # ── ML Recommendations ──────────────────────────────────────────────
    ML_ENABLED: bool = False                    # Master switch: ML on/off
    ML_AB_TEST_ENABLED: bool = False            # A/B test mode
    ML_MODEL_DIR: Path = _BASE / "data" / "models"
    ML_RETRAIN_HOUR: int = 4                    # UTC hour for nightly training
    ML_MIN_INTERACTIONS: int = 100              # Minimum interactions to train
    ML_MIN_USERS: int = 10                      # Minimum users to train ALS
    ML_ALS_FACTORS: int = 64                    # ALS embedding dimension
    ML_ALS_ITERATIONS: int = 15                 # ALS training iterations
    ML_ALS_REGULARIZATION: float = 0.01
    ML_W2V_VECTOR_SIZE: int = 64               # Word2Vec embedding dimension
    ML_W2V_WINDOW: int = 5
    ML_W2V_EPOCHS: int = 10
    ML_SESSION_GAP_MINUTES: int = 30           # Gap between sessions
    ML_SCORER_W_ALS: float = 0.40              # ALS weight in hybrid scorer
    ML_SCORER_W_EMB: float = 0.25              # Embedding weight
    ML_SCORER_W_POP: float = 0.15              # Popularity weight
    ML_SCORER_W_FRESH: float = 0.10            # Freshness weight
    ML_SCORER_W_TIME: float = 0.10             # Time-of-day weight
    ML_MAX_PER_ARTIST: int = 2                 # Diversity: max tracks per artist
    ML_MAX_PER_GENRE: int = 3                  # Diversity: max tracks per genre
    ML_COLD_START_THRESHOLD: int = 5           # Min plays for ML (vs pure content-based)
    ML_RECO_CACHE_TTL: int = 3600              # Override for ML reco cache TTL
```

Переменные окружения:

```env
# .env.example — добавить:
ML_ENABLED=false
ML_RETRAIN_HOUR=4
ML_MIN_INTERACTIONS=100
ML_SCORER_W_ALS=0.40
ML_SCORER_W_EMB=0.25
ML_SCORER_W_POP=0.15
ML_SCORER_W_FRESH=0.10
ML_SCORER_W_TIME=0.10
ML_MAX_PER_ARTIST=2
```

### 9.4 Новые файлы

| Файл | ~Строк | Описание |
|------|--------|----------|
| `recommender/config.py` | ~80 | ScorerWeights dataclass, MLConfig helper для доступа к settings |

### 9.5 Изменения в существующих файлах

| Файл | Строки | Изменение |
|------|--------|-----------|
| `bot/config.py` | После строки 105 (PREMIUM_DAYS) | Добавить ML-блок настроек (~20 строк) |
| `.env.example` | Конец файла | Добавить секцию ML_* переменных |

### 9.6 Модели данных

Нет новых таблиц.

### 9.7 Зависимости

Нет новых зависимостей.

### 9.8 Критерии приемки

1. `ML_ENABLED=False` (default) -- ML полностью отключен, бот работает на чистом SQL
2. `ML_ENABLED=True` -- ML активирован, при наличии моделей
3. Все ML-параметры настраиваемы через .env без изменения кода
4. Веса скорера можно менять в .env и перезапустить бот

### 9.9 Риски и митигация

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| Слишком много env-переменных | Низкая | Все ML_* имеют разумные defaults; достаточно ML_ENABLED=true для старта |
| Рассинхрон config и scorer | Низкая | ScorerWeights создается из settings при каждом запросе (не кешируется) |

---

## 10. СВОДНАЯ ТАБЛИЦА ПОДЗАДАЧ

| # | Компонент | Приоритет | Сложность | Часы | Зависимости |
|---|-----------|-----------|-----------|------|-------------|
| H | Config & Feature Flags | P0 (Critical) | Простая | 4 | -- |
| B | Model Store | P0 (Critical) | Средняя | 8 | H |
| A | Training Pipeline | P0 (Critical) | Высокая | 16 | H, B |
| C | Track Embeddings | P1 (High) | Средняя | 8 | A, B |
| D | Hybrid Scorer | P1 (High) | Высокая | 12 | B, C |
| E | Рефакторинг ai_dj.py | P0 (Critical) | Средняя | 10 | B, C, D |
| F | Profile Auto-Update | P1 (High) | Средняя | 6 | -- |
| G | Evaluation & A/B Testing | P2 (Medium) | Средняя | 10 | E |
| -- | Тесты (unit + integration) | P1 (High) | Средняя | 12 | All |
| -- | Документация + Makefile | P2 (Medium) | Простая | 4 | All |
| **ИТОГО** | | | | **90** | |

---

## 11. РЕКОМЕНДОВАННЫЙ ПОРЯДОК РЕАЛИЗАЦИИ

### Фаза 1: Фундамент (20 часов)
1. **H** -- Config & Feature Flags (4 ч)
2. **B** -- Model Store (8 ч)
3. **F** -- Profile Auto-Update (6 ч) -- независим, можно параллельно
4. Unit-тесты для H, B, F (2 ч)

### Фаза 2: ML-ядро (36 часов)
5. **A** -- Training Pipeline (16 ч)
6. **C** -- Track Embeddings (8 ч)
7. **D** -- Hybrid Scorer (12 ч)

### Фаза 3: Интеграция (20 часов)
8. **E** -- Рефакторинг ai_dj.py (10 ч)
9. Unit + integration тесты (10 ч)

### Фаза 4: Оценка и мониторинг (14 часов)
10. **G** -- Evaluation & A/B Testing (10 ч)
11. Документация, Makefile targets (4 ч)

### Важные контрольные точки:
- После Фазы 1: `ML_ENABLED=False` работает без регрессий; Profile Auto-Update активен
- После Фазы 2: `python -m recommender.train` обучает модели на реальных данных
- После Фазы 3: `ML_ENABLED=True` выдает ML-рекомендации; fallback работает
- После Фазы 4: A/B тест запущен, метрики собираются

---

## 12. МАТРИЦА ВЫБОРА БИБЛИОТЕКИ

### 12.1 Сравнение для данного проекта

| Критерий | implicit (ALS) | LightFM | Surprise | RecTools |
|----------|---------------|---------|----------|----------|
| **Тип данных** | Implicit (play/skip) -- НАШИ ДАННЫЕ | Implicit + content features | Explicit (ratings) -- нужно конвертировать | Implicit + content |
| **Cold start** | Не решает (нужен fallback) | Решает через content features | Не решает | Решает через HSTU |
| **Скорость обучения (10K users)** | ~5 сек (CPU) | ~15 сек | ~30 сек | ~60 сек (GPU recommended) |
| **Скорость inference** | <5ms (numpy dot product) | <10ms | <50ms | <10ms |
| **Зависимости** | numpy, scipy (легкие) | numpy, scipy | numpy, scipy, cython | torch, polars (тяжелые) |
| **Memory (10K users, 50K tracks)** | ~50MB | ~80MB | ~100MB | ~500MB (torch) |
| **API простота** | Простой: fit/recommend | Средний | Простой | Сложный |
| **Совместимость с CPU-only VPS** | Да | Да | Да | Нет (GPU) |
| **Docker image size impact** | +30MB | +35MB | +40MB | +1.5GB (torch) |
| **Лицензия** | MIT | Apache 2.0 | BSD-3 | MIT |
| **Production maturity** | Высокая (Spotify, Last.fm) | Высокая | Средняя (academ.) | Ранняя |

### 12.2 Решение

**Основная библиотека: `implicit` (ALS)**

Обоснование:
1. Наши данные -- implicit feedback (play/skip/like), не рейтинги. `implicit` создана именно для этого
2. Легковесная: numpy + scipy, минимальное влияние на Docker image (+30MB)
3. CPU-only: бот работает на Railway/VPS без GPU
4. Быстрая: обучение < 10 сек, inference < 5ms
5. Production-proven: Spotify использует ALS-подобные модели
6. MIT лицензия -- без ограничений

**Дополнительно: `gensim` (Word2Vec) для track embeddings**

Обоснование:
1. Track-to-track similarity невозможна только с ALS (ALS дает user-item scores, не item-item)
2. Word2Vec на сессиях прослушивания -- стандартный подход (Spotify "Track2Vec")
3. Gensim -- зрелая библиотека, быстрый inference

**Отклонены:**
- **LightFM**: Решает cold start, но наш fallback на content-based SQL уже решает его проще; добавляет сложность
- **Surprise**: Для explicit ratings; конвертация like=5/dislike=1 -- потеря информации
- **RecTools**: Требует GPU (torch); Docker image +1.5GB; overkill для текущего масштаба

### 12.3 Возможная миграция в будущем

При росте до 100K+ users рекомендуется пересмотреть в пользу:
- **LightFM**: если cold start станет критичным (>30% новых пользователей)
- **RecTools (HSTU)**: если появится GPU-сервер и нужны transformer-based рекомендации

---

## 13. ИТОГОВЫЙ СПИСОК НОВЫХ ФАЙЛОВ

| Файл | ~Строк | Компонент |
|------|--------|-----------|
| `recommender/config.py` | 80 | H |
| `recommender/model_store.py` | 180 | B |
| `recommender/data_extractor.py` | 150 | A |
| `recommender/train.py` | 350 | A |
| `recommender/embeddings.py` | 120 | C |
| `recommender/scorer.py` | 250 | D |
| `recommender/profile_updater.py` | 150 | F |
| `recommender/evaluation.py` | 120 | G |
| `bot/models/recommendation_log.py` | 40 | G |
| `tests/test_model_store.py` | 100 | B |
| `tests/test_train.py` | 120 | A |
| `tests/test_scorer.py` | 150 | D |
| `tests/test_embeddings.py` | 80 | C |
| `tests/test_profile_updater.py` | 80 | F |
| **ИТОГО** | **~1970** | |

## 14. ИТОГОВЫЙ СПИСОК ИЗМЕНЕНИЙ В СУЩЕСТВУЮЩИХ ФАЙЛАХ

| Файл | Компонент | Изменение |
|------|-----------|-----------|
| `bot/config.py` | H | +20 строк: ML_* настройки |
| `.env.example` | H | +10 строк: ML_* переменные |
| `requirements.txt` | A | +4 строки: implicit, gensim, scipy, numpy |
| `bot/models/base.py` | F, G | +2 импорта, +2 ALTER TABLE |
| `bot/models/user.py` | F | +1 поле: preferred_hours |
| `recommender/ai_dj.py` | E | Рефакторинг: +80 строк (ML path), сохранение SQL fallback |
| `bot/handlers/search.py` | C, E | Строки 1182-1259: рефакторинг handle_similar |
| `bot/handlers/recommend.py` | G | +10 строк: логирование клика в recommendation_log |
| `bot/handlers/admin.py` | G | +40 строк: /admin ab handler |
| `bot/db.py` | F | +10 строк: trigger автообновления профиля |
| `bot/main.py` | A, B | +5 строк: ModelStore preload + training scheduler |
| `tests/test_ai_dj.py` | E | +30 строк: тесты ML path |

---

### Critical Files for Implementation
- `C:\Users\sherh\music-bot\.claude\worktrees\strange-tharp\recommender\ai_dj.py` - Core recommendation engine to refactor: add ML path, get_similar_tracks(), preserve SQL fallback
- `C:\Users\sherh\music-bot\.claude\worktrees\strange-tharp\bot\config.py` - Settings class to extend with all ML_* feature flags and configuration parameters
- `C:\Users\sherh\music-bot\.claude\worktrees\strange-tharp\bot\models\track.py` - Data models (Track, ListeningHistory) used for training data extraction and interaction matrix
- `C:\Users\sherh\music-bot\.claude\worktrees\strange-tharp\bot\handlers\search.py` - Contains handle_similar (lines 1182-1259) and profile update trigger (lines 880-894) to refactor
- `C:\Users\sherh\music-bot\.claude\worktrees\strange-tharp\bot\services\daily_digest.py` - Pattern to follow for asyncio scheduler loop (training cron job)