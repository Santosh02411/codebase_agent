import React, { createContext, useContext, useState, useCallback } from "react";

const ToastContext = createContext(null);

const TOAST_DURATION_MS = 3500;

/**
 * Simple toast notification system: call showToast(message, type) from
 * anywhere in the app (type is "success", "error", or "info"). Toasts
 * stack in the bottom-right corner and auto-dismiss after a few seconds.
 * Replaces the earlier inline plain-text status messages.
 */
export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const showToast = useCallback((message, type = "info") => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, TOAST_DURATION_MS);
  }, []);

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <div
        style={{
          position: "fixed",
          bottom: "20px",
          right: "20px",
          display: "flex",
          flexDirection: "column",
          gap: "8px",
          zIndex: 2000,
        }}
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            style={{
              padding: "12px 16px",
              borderRadius: "8px",
              color: "white",
              minWidth: "220px",
              maxWidth: "360px",
              boxShadow: "0 2px 10px rgba(0,0,0,0.2)",
              backgroundColor:
                toast.type === "success" ? "#2e7d32" : toast.type === "error" ? "#c62828" : "#37474f",
              fontSize: "14px",
            }}
          >
            {toast.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error("useToast must be used within a ToastProvider");
  }
  return context;
}
