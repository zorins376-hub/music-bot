import { useState, useEffect, useCallback, useRef } from "preact/hooks";

export type ToastType = "error" | "success" | "info" | "warning";

interface ToastItem {
  id: number;
  message: string;
  type: ToastType;
  exiting?: boolean;
}

let _addToast: ((message: string, type?: ToastType, duration?: number) => void) | null = null;

/** Global toast trigger — call from anywhere */
export function showToast(message: string, type: ToastType = "info", duration = 3000) {
  _addToast?.(message, type, duration);
}

const ICONS: Record<ToastType, string> = {
  error: "\u26A0",
  success: "\u2713",
  info: "\u24D8",
  warning: "\u26A0",
};

const BG: Record<ToastType, string> = {
  error: "rgba(244,67,54,0.92)",
  success: "rgba(76,175,80,0.92)",
  info: "rgba(33,150,243,0.92)",
  warning: "rgba(255,152,0,0.92)",
};

export function ToastContainer() {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const nextId = useRef(0);

  const addToast = useCallback((message: string, type: ToastType = "info", duration = 3000) => {
    const id = nextId.current++;
    setToasts((prev) => [...prev.slice(-4), { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.map((t) => (t.id === id ? { ...t, exiting: true } : t)));
      setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 300);
    }, duration);
  }, []);

  useEffect(() => {
    _addToast = addToast;
    return () => { _addToast = null; };
  }, [addToast]);

  if (!toasts.length) return null;

  return (
    <div style={{
      position: "fixed",
      top: 12,
      left: "50%",
      transform: "translateX(-50%)",
      zIndex: 99999,
      display: "flex",
      flexDirection: "column",
      gap: 8,
      pointerEvents: "none",
      maxWidth: "92vw",
    }}>
      {toasts.map((t) => (
        <div
          key={t.id}
          style={{
            background: BG[t.type],
            color: "#fff",
            padding: "10px 16px",
            borderRadius: 14,
            fontSize: 13,
            fontWeight: 600,
            display: "flex",
            alignItems: "center",
            gap: 8,
            backdropFilter: "blur(12px)",
            boxShadow: "0 8px 32px rgba(0,0,0,0.3)",
            animation: t.exiting ? "toastOut 0.3s ease forwards" : "toastIn 0.3s ease",
            pointerEvents: "auto",
            maxWidth: 360,
            wordBreak: "break-word",
          }}
        >
          <span style={{ fontSize: 16, flexShrink: 0 }}>{ICONS[t.type]}</span>
          {t.message}
        </div>
      ))}
      <style>{`
        @keyframes toastIn { from { opacity: 0; transform: translateY(-20px) scale(0.95); } to { opacity: 1; transform: translateY(0) scale(1); } }
        @keyframes toastOut { from { opacity: 1; transform: translateY(0) scale(1); } to { opacity: 0; transform: translateY(-20px) scale(0.95); } }
      `}</style>
    </div>
  );
}
