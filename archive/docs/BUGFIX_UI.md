# ТЗ: Исправление UI — кнопки не нажимаются, карусель и ползунки глючат

> **Дата:** 2026-03-22
> **Симптомы:** При открытии приложения кнопки работают, но через несколько секунд перестают нажиматься. Карусель и ползунки ведут себя странно.

---

## ГЛАВНАЯ ПРИЧИНА: Фоновые overlay-ы без pointer-events: none перехватывают тачи

### Где
`webapp/frontend/src/App.tsx` — строки 1691-1738

### Что происходит — пошагово

```
ТАЙМЛАЙН:

0ms     — Приложение рендерится. state.current_track = null.
          Фоновых overlay-ов НЕТ → кнопки работают ✅

~2-3с   — fetchPlayerState() загружает последний трек
          → setState({ current_track: {...} })

~3-4с   — extractTopColors() извлекает цвета из обложки
          → setMeshColors([...])

~4с     — Рендерится ОДИН ИЗ ЭТИХ div-ов:
```

**Mesh gradient background (строки 1705-1722):**
```tsx
{state.current_track?.cover_url && !theme.bgImage && meshColors.length >= 3 && (
  <div style={{
    position: "fixed",    // ← покрывает ВСЮ область экрана
    top: 0, left: 0,
    right: 0, bottom: 0,
    background: `radial-gradient(...)`,
    zIndex: -1,
    // ❌ НЕТ pointerEvents: "none" !!!
  }} />
)}
```

**ИЛИ blurred cover fallback (строки 1724-1738):**
```tsx
{state.current_track?.cover_url && !theme.bgImage && meshColors.length < 3 && (
  <div style={{
    position: "fixed",    // ← покрывает ВСЮ область экрана
    top: 0, left: 0,
    right: 0, bottom: 0,
    backgroundImage: `url(${state.current_track.cover_url})`,
    filter: "blur(60px) brightness(0.4)",
    zIndex: -1,
    // ❌ НЕТ pointerEvents: "none" !!!
  }} />
)}
```

**И theme bgOverlay (строки 1691-1702):**
```tsx
{theme.bgOverlay && (
  <div style={{
    position: "fixed",
    top: 0, left: 0,
    right: 0, bottom: 0,
    background: theme.bgOverlay,
    zIndex: -1,
    // ❌ НЕТ pointerEvents: "none" !!!
  }} />
)}
```

### Почему zIndex: -1 не спасает

В теории `zIndex: -1` рисует элемент позади контента. Но в **WebView Telegram** (особенно на Android) hit-testing тачей работает не по z-index, а по DOM-позиции и `position: fixed`. Фиксированный элемент с `inset: 0` **перехватывает все touch-события** на всём viewport, даже если визуально он позади.

Для сравнения — декоративные blur-элементы Tequila-темы (строки 1632-1661) **правильно** имеют `pointerEvents: "none"`:
```tsx
// ✅ Эти работают правильно:
<div style={{
  position: "fixed",
  zIndex: -1,
  pointerEvents: "none",  // ← ЕСТЬ — тачи проходят сквозь
}} />
```

### Что исправить

Добавить `pointerEvents: "none"` на **3 элемента**:

**Фикс 1 — theme.bgOverlay (строка ~1693):**
```tsx
  style={{
    position: "fixed",
    top: 0, left: 0, right: 0, bottom: 0,
    background: theme.bgOverlay,
    zIndex: -1,
+   pointerEvents: "none",       // ← ДОБАВИТЬ
  }}
```

**Фикс 2 — mesh gradient (строка ~1707):**
```tsx
  style={{
    position: "fixed",
    top: 0, left: 0, right: 0, bottom: 0,
    background: `radial-gradient(...)`,
    animation: "meshRotate 20s ease-in-out infinite",
    zIndex: -1,
+   pointerEvents: "none",       // ← ДОБАВИТЬ
  }}
```

**Фикс 3 — blurred cover fallback (строка ~1726):**
```tsx
  style={{
    position: "fixed",
    top: 0, left: 0, right: 0, bottom: 0,
    backgroundImage: `url(...)`,
    filter: "blur(60px) brightness(0.4)",
    transform: "scale(1.2)",
    zIndex: -1,
+   pointerEvents: "none",       // ← ДОБАВИТЬ
  }}
```

**Также проверить theme.bgImage div (строка ~1676):**
```tsx
  style={{
    position: "fixed",
    top: 0, left: 0, right: 0, bottom: 0,
    backgroundImage: `url(${theme.bgImage})`,
    backgroundSize: "cover",
    zIndex: -2,
+   pointerEvents: "none",       // ← ДОБАВИТЬ на всякий случай
  }}
```

---

## ДОПОЛНИТЕЛЬНАЯ ПРИЧИНА: preventDefault() в onTouchEnd на кнопках навигации

### Где
`webapp/frontend/src/App.tsx` — строки 1836-1841, 1889

### Что происходит
```tsx
<button
  onTouchEnd={(e) => {
    if (!navTouchMovedRef.current) {
      e.preventDefault();   // ← убивает последующий onClick
      activateView(v);
    }
  }}
  onClick={() => activateView(v)}  // ← не сработает после preventDefault
>
```

На мобильных: `touchend` → `preventDefault()` → браузер **не генерирует** `click`. Если `navTouchMovedRef.current === true` (система решила что был свайп), то ни `touchEnd`, ни `click` не вызовут `activateView`. Кнопка мертва.

### Что исправить

Убрать `e.preventDefault()` из `onTouchEnd`, оставить только `onClick`:

```tsx
<button
  onClick={() => {
    if (!navTouchMovedRef.current) {
      activateView(v);
    }
  }}
>
```

То же самое для **кнопки смены темы** (строка 1889).

---

## ДОПОЛНИТЕЛЬНАЯ ПРИЧИНА: Конфликт touch handlers на карусели

### Где
`webapp/frontend/src/App.tsx` — строки 1796, 1826, 1879

### Что происходит
На `<nav>` карусели одновременно:
- `touchAction: "pan-x"` — на контейнере
- `touchAction: "manipulation"` — на каждой кнопке
- `onTouchStart/Move/End` — кастомные хэндлеры
- `scrollSnapType: "x proximity"` — нативный snap

Эти 4 вещи конфликтуют → карусель дёргается, snap срабатывает непредсказуемо.

### Что исправить
1. Убрать `touchAction: "manipulation"` с кнопок (строка 1879)
2. Убрать кастомные `onTouchStart/Move/End` с `<nav>` — нативный скролл + snap работает сам
3. Если нужно отличать свайп от тапа — делать через `onClick` + проверку дельты

---

## ДОПОЛНИТЕЛЬНАЯ ПРИЧИНА: Глобальный preventDefault на document при drag треков

### Где
`webapp/frontend/src/components/TrackList.tsx` — строки 99-149

### Что происходит
При зажатии трека для перетаскивания:
```tsx
document.addEventListener("touchmove", (e) => {
  e.preventDefault();  // ← блокирует ВЕСЬ скролл на ВСЕЙ странице
}, { passive: false });
```

Если drag-состояние зависнет — скролл ломается навсегда.

### Что исправить
Ограничить preventDefault контейнером TrackList:
```tsx
const onMove = (e: TouchEvent) => {
  if (!containerRef.current?.contains(e.target as Node)) return;
  e.preventDefault();
  // ...
};
```

---

## Сводка — порядок фикса

| # | Что | Файл | Строки | Эффект | Время |
|---|-----|------|--------|--------|-------|
| **1** | Добавить `pointerEvents: "none"` на 4 фоновых overlay | App.tsx | 1676, 1693, 1707, 1726 | **Кнопки перестанут блокироваться** | 2 мин |
| **2** | Убрать `e.preventDefault()` из onTouchEnd кнопок | App.tsx | 1838, 1889 | Табы будут надёжно работать | 2 мин |
| **3** | Убрать кастомные touch handlers с карусели | App.tsx | 1796, 1879 | Карусель перестанет дёргаться | 5 мин |
| **4** | Ограничить drag preventDefault контейнером | TrackList.tsx | 102-103 | Скролл не будет ломаться при drag | 3 мин |

**Фикс #1 — это 90% проблемы.** 4 строки кода, 2 минуты работы. После него кнопки сразу заработают.
