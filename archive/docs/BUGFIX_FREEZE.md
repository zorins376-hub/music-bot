# ТЗ: UI зависает при загрузке данных

> **Дата:** 2026-03-22
> **Симптом:** Без данных (пустые плейлисты/чарты) приложение отзывчивое. Как только данные загружаются — UI замирает, кнопки перестают реагировать.

---

## Диагноз

Проблема **НЕ** в сети и не в размере данных. Проблема в том, что при загрузке данных происходит **лавина ре-рендеров** на main thread, которая блокирует обработку тачей на 1-3 секунды.

### Что происходит при загрузке данных — пошагово

```
ТАЙМЛАЙН после открытия приложения:

0ms      — App рендерится (2455 строк, 46 useState). Рендер №1.
           → Кнопки работают ✅

~50ms    — useEffect срабатывает:
           → fetchUserProfile()        — HTTP запрос
           → fetchPlayerState(userId)  — HTTP запрос
           → fetchBroadcast()          — HTTP запрос
           Рендер №2 (broadcast state)

~200ms   — fetchBroadcast ответ:
           → setBroadcastLive()         — Рендер №3
           → setBroadcastDJ()           — Рендер №4
           → setLiveBannerDismissed()   — Рендер №5

~500ms   — fetchUserProfile ответ:
           → setUserProfile()           — Рендер №6

~800ms   — fetchPlayerState ответ:
           → setState({...s})           — Рендер №7
           → setView("player")          — Рендер №8

~900ms   — useEffect[cover_url] срабатывает:
           → extractDominantColor()     — БЛОКИРУЕТ main thread (canvas)
           → extractTopColors()         — БЛОКИРУЕТ main thread (canvas)

~1100ms  — extractDominantColor ответ:
           → setAccentColor()           — Рендер №9
           → setAccentColorAlpha()      — Рендер №10

~1200ms  — extractTopColors ответ:
           → setMeshColors()            — Рендер №11
           → Появляется фон без pointer-events:none → БЛОКИРУЕТ ТАЧИ

~1200ms  — ForYouView монтируется (если view = "foryou"):
           → fetchWave()               — HTTP запрос
           → fetchTrending()           — HTTP запрос
           → fetchTrackOfDay()         — HTTP запрос
           → fetchSmartPlaylists()     — HTTP запрос
           → setWaveLoading(true)      — Рендер №12
           → setTrendingLoading(true)  — Рендер №13

~1500ms  — ответы ForYouView:
           → setWaveTracks()           — Рендер №14
           → setWaveLoading(false)     — Рендер №15
           → setTrendingTracks()       — Рендер №16
           → setTrendingLoading(false) — Рендер №17
           → setTodTrack()             — Рендер №18
           → setSmartPlaylists()       — Рендер №19
           → fetchSimilar()            — ещё один HTTP запрос
           → setSimilarTracks()        — Рендер №20

ИТОГО: 20+ ре-рендеров за 1.5 секунды
       Каждый ре-рендер = пересчёт 2455-строчного App компонента
```

---

## Причина №1 (CRITICAL): 46 useState в одном компоненте App — каждый setState ре-рендерит ВСЁ

### Где
`webapp/frontend/src/App.tsx` — строки 171-249

### Проблема
```tsx
// 46 хуков useState в App():
const [view, setView] = useState("foryou");          // UI
const [state, setState] = useState<PlayerState>(...); // данные
const [accentColor, setAccentColor] = useState(...);  // визуал
const [meshColors, setMeshColors] = useState([]);     // визуал
const [sleepTimerEnd, setSleepTimerEnd] = useState(); // таймер
const [bassBoost, setBassBoost] = useState(false);    // аудио
const [panValue, setPanValue] = useState(0);          // аудио
// ... ещё 39 штук
```

**Каждый** вызов `setState` / `setView` / `setMeshColors` и т.д. заставляет Preact пересчитать весь `App()` — 2455 строк JSX, 50+ inline style объектов, все дочерние компоненты.

### Что исправить
**Батчить связанные обновления** — вместо 3-4 отдельных setState, делать одно обновление:

```tsx
// ❌ СЕЙЧАС: 3 отдельных ре-рендера
setBroadcastLive(b.is_live);       // Рендер
setBroadcastDJ(b.dj_name || "DJ"); // Рендер
setLiveBannerDismissed(false);     // Рендер

// ✅ НУЖНО: 1 ре-рендер через useReducer или объединённый state
dispatch({ type: "broadcast_update", payload: b });
```

**Или разбить App на подкомпоненты** со своим state:
- `<BroadcastProvider>` — своя broadcastLive/DJ state
- `<AudioSettingsProvider>` — bassBoost, pan, EQ, reverb, karaoke...
- `<ThemeProvider>` — accent, meshColors, theme
- `<PlayerProvider>` — state, elapsed, buffering

Каждый провайдер ре-рендерит только своих потребителей, а не весь App.

---

## Причина №2 (CRITICAL): Ни один дочерний компонент не мемоизирован (кроме 2)

### Где
Все компоненты в `webapp/frontend/src/components/`

### Проблема
```tsx
// Из 13+ вьюх, только 2 используют memo():
export const LiveRadioView = memo(function LiveRadioView(...) { ... });  // ✅
export const ProfileView = memo(function ProfileView(...) { ... });      // ✅

// Остальные — НЕТ:
export function ForYouView(...) { ... }     // ❌ ре-рендерится на КАЖДЫЙ setState в App
export function ChartsView(...) { ... }     // ❌
export function Player(...) { ... }         // ❌
export function TrackList(...) { ... }      // ❌
export function PlaylistView(...) { ... }   // ❌
export function PartyView(...) { ... }      // ❌
// ... и т.д.
```

Когда App ре-рендерится (а это 20+ раз при загрузке) — **ВСЕ дочерние компоненты** тоже ре-рендерятся, даже если их пропсы не изменились.

### Что исправить
Обернуть каждый view-компонент в `memo()`:
```tsx
export const ForYouView = memo(function ForYouView({ ... }) {
  // ...
});
```

А в App — мемоизировать callback-пропсы через `useCallback`:
```tsx
// ❌ СЕЙЧАС: новая функция на каждый рендер
onPlayTrack={(t) => { action("play", t.video_id, undefined, t); setView("player"); }}

// ✅ НУЖНО:
const handlePlayTrack = useCallback((t: Track) => {
  action("play", t.video_id, undefined, t);
  setView("player");
}, [action]);
```

---

## Причина №3 (HIGH): extractDominantColor + extractTopColors блокируют main thread

### Где
`webapp/frontend/src/colorExtractor.ts` — строки 12-72, 98-152

### Проблема
```tsx
// App.tsx строка 1185-1190:
extractDominantColor(coverUrl).then((color) => {
  setAccentColor(rgbToCSS(color));         // Рендер
  setAccentColorAlpha(rgbaToCSS(color, 0.4)); // Рендер
});
extractTopColors(coverUrl).then((colors) => {
  setMeshColors(colors.map(...));           // Рендер
});
```

Обе функции:
1. Создают `<img>` → загружают картинку (async, ОК)
2. Создают `<canvas>` 64×64 → рисуют картинку (sync, блокирует)
3. `getImageData()` → достают пиксели (sync, блокирует)
4. Цикл по пикселям + Map + сортировка (sync, блокирует)
5. Вызывают 3 setState (3 ре-рендера)

Пункты 2-4 выполняются **синхронно на main thread**. На слабых устройствах (Android TMA) это 50-200ms блокировки.

### Что исправить

**Вариант А (простой):** Объединить в одну функцию + один setState:
```tsx
// Одна загрузка изображения, один проход по пикселям, один setState
const { dominant, top3 } = await extractColors(coverUrl);
// Батч-обновление:
setColorState({ accent: dominant, alpha: rgbaToCSS(dominant, 0.4), mesh: top3 });
```

**Вариант Б (идеальный):** Вынести canvas-обработку в Web Worker:
```tsx
const worker = new Worker("colorWorker.js");
worker.postMessage({ imageData });
worker.onmessage = (e) => {
  const { dominant, top3 } = e.data;
  // один setState
};
```

**Вариант В (минимальный):** Добавить `requestIdleCallback` / `setTimeout(0)` чтобы не блокировать тачи:
```tsx
img.onload = () => {
  requestAnimationFrame(() => {
    // canvas операции здесь — выполнятся в следующем кадре
  });
};
```

---

## Причина №4 (HIGH): ForYouView делает 5 запросов с 8 setState при монтировании

### Где
`webapp/frontend/src/components/ForYouView.tsx` — строки 198-230

### Проблема
```tsx
// useEffect 1: монтирование
useEffect(() => {
  fetchTrackOfDay().then(setTodTrack);       // Рендер
  fetchSmartPlaylists().then(setSmartPlaylists); // Рендер
}, []);

// useEffect 2: волна
useEffect(() => {
  setWaveLoading(true);    // Рендер
  setWaveError(false);     // Рендер
  fetchWave(userId, 10)
    .then(setWaveTracks)   // Рендер
    .finally(() => setWaveLoading(false)); // Рендер
}, [userId]);

// useEffect 3: тренды
useEffect(() => {
  setTrendingLoading(true);   // Рендер
  setTrendingError(false);    // Рендер
  fetchTrending(24, 15)
    .then(setTrendingTracks)  // Рендер
    .finally(() => setTrendingLoading(false)); // Рендер
}, []);

// useEffect 4: похожие
useEffect(() => {
  setSimilarLoading(true);    // Рендер
  fetchSimilar(...)
    .then(setSimilarTracks)   // Рендер
    .finally(() => setSimilarLoading(false)); // Рендер
}, [currentTrack?.video_id]);
```

**5 параллельных запросов → 12+ setState вызовов → 12 ре-рендеров ForYouView** (плюс каждый из них тоже ре-рендерит App, если ForYouView не мемоизирован).

### Что исправить
**Объединить в один useEffect с одним batch-обновлением:**
```tsx
useEffect(() => {
  let cancelled = false;
  setLoading(true);

  Promise.allSettled([
    fetchWave(userId, 10),
    fetchTrending(24, 15),
    fetchTrackOfDay(),
    fetchSmartPlaylists(),
    currentTrack?.video_id ? fetchSimilar(currentTrack.video_id, 8) : Promise.resolve([]),
  ]).then(([wave, trending, tod, smart, similar]) => {
    if (cancelled) return;
    // ОДИН batch setState:
    setDataState({
      wave: wave.status === "fulfilled" ? wave.value : [],
      trending: trending.status === "fulfilled" ? trending.value : [],
      tod: tod.status === "fulfilled" ? tod.value : null,
      smart: smart.status === "fulfilled" ? smart.value : [],
      similar: similar.status === "fulfilled" ? similar.value : [],
    });
    setLoading(false);
  });

  return () => { cancelled = true; };
}, [userId, currentTrack?.video_id]);
```

---

## Причина №5 (MEDIUM): Broadcast polling каждые 30с — 3 setState даже без изменений

### Где
`webapp/frontend/src/App.tsx` — строки 1244-1259

### Проблема
```tsx
const check = () => {
  fetchBroadcast().then((b) => {
    setBroadcastLive(b.is_live);       // Рендер — ДАЖЕ ЕСЛИ ЗНАЧЕНИЕ НЕ ИЗМЕНИЛОСЬ
    setBroadcastDJ(b.dj_name || "DJ"); // Рендер — ДАЖЕ ЕСЛИ ЗНАЧЕНИЕ НЕ ИЗМЕНИЛОСЬ
    if (b.is_live && !wasLive) setLiveBannerDismissed(false); // Рендер
  });
};
setInterval(check, 30000);
```

Каждые 30 секунд — 2-3 бесполезных ре-рендера всего App (даже если broadcast не изменился).

### Что исправить
Проверять изменения перед setState:
```tsx
fetchBroadcast().then((b) => {
  if (b.is_live !== broadcastLiveRef.current) {
    setBroadcastLive(b.is_live);
  }
  if ((b.dj_name || "DJ") !== broadcastDJRef.current) {
    setBroadcastDJ(b.dj_name || "DJ");
  }
  // ...
});
```

---

## Причина №6 (MEDIUM): Inline стили пересоздаются на каждый рендер

### Где
Весь `App.tsx` и дочерние компоненты

### Проблема
```tsx
// Каждый рендер создаёт НОВЫЙ объект стиля для каждого элемента:
<div style={{
  position: "fixed",
  top: 0, left: 0, right: 0, bottom: 0,
  background: `radial-gradient(...)`,
  animation: "meshRotate 20s ease-in-out infinite",
  zIndex: -1,
}} />
```

При 20+ ре-рендерах × 50+ элементов с inline стилями = тысячи объектов создаются и сравниваются. Preact вынужден diff-ать каждый.

### Что исправить
Вынести статические стили в `useMemo` или CSS-классы:
```tsx
const meshBgStyle = useMemo(() => ({
  position: "fixed" as const,
  top: 0, left: 0, right: 0, bottom: 0,
  background: `radial-gradient(...)`,
  zIndex: -1,
  pointerEvents: "none" as const,
}), [meshColors, theme.bgColor]);
```

---

## Сводная таблица

| # | Проблема | Ре-рендеры | Файл | Приоритет |
|---|----------|-----------|------|-----------|
| 1 | 46 useState в App — каждый ре-рендерит всё | ×20 при загрузке | App.tsx | CRITICAL |
| 2 | 11 из 13 компонентов без memo() | умножает ×20 на каждый ребёнок | components/*.tsx | CRITICAL |
| 3 | Canvas color extraction на main thread | 50-200ms блок | colorExtractor.ts | HIGH |
| 4 | ForYouView: 5 fetch + 12 setState | 12 лишних рендеров | ForYouView.tsx | HIGH |
| 5 | Broadcast polling: setState без проверки | 2-3 каждые 30с | App.tsx | MEDIUM |
| 6 | Inline стили пересоздаются | GC pressure | App.tsx, все | MEDIUM |

## Порядок фикса

### Шаг 1 — Быстрые победы (30 мин, сразу заметный эффект)
1. Обернуть все view-компоненты в `memo()`
2. В broadcast polling — проверять изменения перед setState
3. В extractColors — объединить 2 функции + 3 setState в одну функцию + 1 setState

### Шаг 2 — Батчинг setState (1-2 часа)
4. ForYouView: один `Promise.allSettled` + один setState
5. App: batch broadcast обновления (3 setState → 1)
6. App: batch color обновления (3 setState → 1)

### Шаг 3 — Архитектура (3-5 часов)
7. Вынести группы state в `useReducer` или контексты:
   - AudioSettings (10 хуков → 1 reducer)
   - ThemeColors (4 хука → 1 reducer)
   - BroadcastState (3 хука → 1 reducer)
8. Мемоизировать callback-пропсы через `useCallback`
9. Вынести статические стили в `useMemo` или CSS

### Ожидаемый результат
- Шаг 1: с 20+ ре-рендеров → ~8 при загрузке
- Шаг 2: с ~8 → ~4
- Шаг 3: с ~4 → 2-3, каждый ре-рендерит только нужные компоненты
