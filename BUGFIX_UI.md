# ТЗ: Исправление UI — кнопки не нажимаются, карусель и ползунки глючат

> **Дата:** 2026-03-21
> **Симптомы:** При открытии приложения кнопки не реагируют на нажатия. Ползунки и карусель навигации прокручиваются рывками / неестественно.

---

## Корневая причина №1 (CRITICAL): Boot-loader блокирует весь экран 5+ секунд

### Где
- `webapp/frontend/src/main.tsx:111-119`
- `webapp/frontend/index.html:124-138`

### Что происходит
```
Таймлайн после открытия приложения:

0ms      — App рендерится, boot-loader покрывает ВЕСЬ экран (position:fixed; inset:0; z-index:999999)
0-4000ms — setTimeout 4 секунды (!) — boot-loader БЛОКИРУЕТ ВСЕ НАЖАТИЯ
4000ms   — добавляется класс "is-exiting" (начинается анимация)
4920ms   — добавляется класс "is-hidden" (pointer-events:none)
5020ms   — bootLoader.remove() — элемент удаляется из DOM
```

**Итого: первые ~5 секунд после открытия ни одна кнопка не работает**, потому что невидимый div с `z-index: 999999` лежит поверх всего интерфейса.

### Что исправить
1. **Убрать `setTimeout(…, 4000)`** — 4 секунды ожидания перед началом анимации выхода — это слишком много
2. **Либо** сразу поставить `pointer-events: none` на boot-loader после рендера App, не дожидаясь анимации
3. **Либо** привязать скрытие к событию "приложение готово" (первый рендер компонента), а не к фиксированному таймеру
4. Рекомендуемый подход:
```tsx
// main.tsx — сразу после render()
if (bootLoader) {
  bootLoader.style.pointerEvents = "none"; // ← мгновенно разблокировать клики
  bootLoader.classList.add("is-exiting");
  setTimeout(() => bootLoader.remove(), 1000);
}
```

---

## Корневая причина №2 (CRITICAL): e.preventDefault() в onTouchEnd убивает onClick на кнопках навигации

### Где
- `webapp/frontend/src/App.tsx:1836-1841` (кнопки табов)
- `webapp/frontend/src/App.tsx:1889` (кнопка смены темы)

### Что происходит
```tsx
<button
  onTouchEnd={(e) => {
    if (!navTouchMovedRef.current) {
      e.preventDefault();   // ← УБИВАЕТ последующий onClick
      activateView(v);
    }
  }}
  onClick={() => activateView(v)}  // ← НИКОГДА НЕ СРАБАТЫВАЕТ на тач-устройствах
>
```

На мобильных устройствах (а TMA = всегда мобильное):
1. Пользователь тапает кнопку
2. Браузер генерирует `touchend` → вызывается `preventDefault()`
3. Браузер **не генерирует** `click` (т.к. preventDefault отменил его)
4. Если `navTouchMovedRef.current === true` (система решила что был свайп) → **ни touchEnd, ни click не вызовет activateView** → кнопка мертва

### Что исправить
**Убрать `e.preventDefault()` из onTouchEnd** и оставить только `onClick`:
```tsx
<button
  onClick={() => activateView(v)}
  // onTouchEnd — НЕ НУЖЕН для простого тапа
>
```

Если нужно отличать свайп от тапа — делать это через `onClick` + проверку `navTouchMovedRef`:
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

## Корневая причина №3 (HIGH): Карусель навигации — конфликт touch-action и scroll-snap

### Где
- `webapp/frontend/src/App.tsx:1796-1827`

### Что происходит
На `<nav>` карусели одновременно:
1. `touchAction: "pan-x"` — разрешает только горизонтальный скролл
2. `scrollSnapType: "x proximity"` — snap-точки на каждом табе
3. `onTouchStart/Move/End` — кастомные обработчики тача
4. `WebkitOverflowScrolling: "touch"` — инерционный скролл

**Конфликт:** кастомные touch-хэндлеры мешают нативному `scroll-snap`. При свайпе:
- Нативный скролл двигает карусель
- `handleNavTouchMove` ставит `navTouchMovedRef = true`
- `handleNavTouchEnd` сбрасывает ref через `setTimeout(0)` — но к этому моменту snap-анимация ещё не закончилась
- Результат: карусель "дёргается", snap срабатывает непредсказуемо

### Что исправить
**Вариант А (простой):** Убрать кастомные touch-хэндлеры с `<nav>`, оставить только нативный скролл + `scroll-snap`:
```tsx
<nav ref={navCarouselRef} className="luxury-carousel" style={{
  // ... все стили остаются
  // touchAction: "pan-x" — оставить
  // scroll-snap — оставить
}}>
  {/* кнопки с обычным onClick */}
</nav>
```

**Вариант Б (если нужно различать свайп/тап):** Отслеживать только deltaX > порог, без preventDefault, без блокировки нативного скролла.

---

## Корневая причина №4 (HIGH): Глобальный preventDefault на touchmove при drag-reorder треков

### Где
- `webapp/frontend/src/components/TrackList.tsx:99-149`

### Что происходит
```tsx
useEffect(() => {
  if (dragIndex === null) return;

  const onMove = (e: TouchEvent) => {
    e.preventDefault();  // ← БЛОКИРУЕТ ВЕСЬ СКРОЛЛ НА СТРАНИЦЕ
    // ...
  };

  document.addEventListener("touchmove", onMove, { passive: false });
  // ...
}, [dragIndex, ...]);
```

Когда `dragIndex !== null` (пользователь зажал трек для перетаскивания):
- `preventDefault()` вешается на `document` — **блокируется скролл везде**: и в списке треков, и в карусели, и в плеере
- Если состояние `dragIndex` по какой-то причине не сбросится (ошибка, race condition) — **скролл ломается навсегда** до перезагрузки

### Что исправить
1. Ограничить `preventDefault` только контейнером TrackList, а не `document`:
```tsx
const onMove = (e: TouchEvent) => {
  // Проверить что цель тача внутри контейнера
  if (!containerRef.current?.contains(e.target as Node)) return;
  e.preventDefault();
  // ...
};
```
2. Добавить safety-таймаут: если drag длится > 10 секунд — автосброс:
```tsx
const safetyTimeout = setTimeout(() => {
  setDragIndex(null);
  setDragY(0);
}, 10000);
return () => clearTimeout(safetyTimeout);
```

---

## Корневая причина №5 (MEDIUM): Кнопка удаления трека — двойной обработчик

### Где
- `webapp/frontend/src/components/TrackList.tsx:255-258`

### Что происходит
```tsx
<div
  onClick={(e) => { e.preventDefault(); e.stopPropagation(); handleRemove(...); }}
  onTouchEnd={(e) => { e.preventDefault(); e.stopPropagation(); handleRemove(...); }}
>
```

На тач-устройствах `handleRemove` вызывается **дважды**: один раз из `onTouchEnd`, второй из `onClick` (если preventDefault в touchEnd не сработал из-за timing). Или наоборот — ни разу, если preventDefault заблокировал оба.

### Что исправить
Оставить только `onClick`, убрать `onTouchEnd`:
```tsx
<div onClick={(e) => { e.stopPropagation(); handleRemove(...); }}>
```
`pointer-events: none/auto` (строка 272) уже защищает от случайных нажатий.

---

## Корневая причина №6 (MEDIUM): touchAction: "manipulation" на кнопках конфликтует с pan-x на контейнере

### Где
- `webapp/frontend/src/App.tsx:1879` (кнопки) vs строка 1826 (контейнер)

### Что происходит
- Контейнер `<nav>`: `touchAction: "pan-x"` — разрешает только горизонтальный пан
- Кнопки `<button>`: `touchAction: "manipulation"` — разрешает pan + zoom, убирает 300ms задержку

**Конфликт:** когда палец на кнопке, браузер видит `manipulation` (pan в обе стороны разрешён), но родитель говорит `pan-x` only. Разные браузеры разрешают это по-разному → непредсказуемое поведение.

### Что исправить
Убрать `touchAction` с кнопок — достаточно `touchAction: "pan-x"` на контейнере:
```tsx
// На кнопках:
// touchAction: "manipulation"  ← УБРАТЬ
```

---

## Сводная таблица

| # | Проблема | Файл | Строки | Симптом | Приоритет |
|---|----------|------|--------|---------|-----------|
| 1 | Boot-loader блокирует 5 секунд | main.tsx | 111-119 | Кнопки не нажимаются при открытии | CRITICAL |
| 2 | preventDefault в onTouchEnd на табах | App.tsx | 1836-1841, 1889 | Табы не переключаются | CRITICAL |
| 3 | Конфликт touch handlers + scroll-snap | App.tsx | 1796-1827 | Карусель дёргается | HIGH |
| 4 | Глобальный preventDefault на document | TrackList.tsx | 99-149 | Скролл ломается при drag | HIGH |
| 5 | Двойной обработчик на кнопке удаления | TrackList.tsx | 255-258 | Удаление дважды или ни разу | MEDIUM |
| 6 | touchAction конфликт | App.tsx | 1826 vs 1879 | Непредсказуемый скролл | MEDIUM |

## Порядок фикса

1. **#1** — Boot-loader → мгновенный результат, все кнопки заработают
2. **#2** — preventDefault в табах → навигация заработает
3. **#3** — Убрать кастомные touch handlers с карусели → плавный скролл
4. **#6** — touchAction конфликт → чинится вместе с #3
5. **#4** — Ограничить drag preventDefault контейнером
6. **#5** — Упростить кнопку удаления

После фиксов #1 и #2 приложение уже должно стать значительно отзывчивее.
