import React, { useState } from "react";

/**
 * Drop-in replacement for `<input type="password">` that adds a
 * show/hide "eye" toggle button inside the field. Purely visual state
 * (isVisible) — never touches the value itself, so it's safe to swap
 * in anywhere a plain password input was used before.
 *
 * Pass through any standard input props (value, onChange, required,
 * minLength, placeholder, id, name, autoComplete, autoFocus, className,
 * style...) — everything except `type` is forwarded to the underlying
 * <input>.
 */
export default function PasswordInput({ className, wrapClassName, style, ...inputProps }) {
  const [isVisible, setIsVisible] = useState(false);

  return (
    <div className={`password-input-wrap ${wrapClassName || ""}`}>
      <input
        {...inputProps}
        type={isVisible ? "text" : "password"}
        className={className}
        style={style}
      />
      <button
        type="button"
        className="password-toggle-btn"
        onClick={() => setIsVisible((v) => !v)}
        tabIndex={-1}
        aria-label={isVisible ? "Hide password" : "Show password"}
        title={isVisible ? "Hide password" : "Show password"}
      >
        {isVisible ? (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M17.94 17.94A10.94 10.94 0 0 1 12 20c-7 0-11-8-11-8a18.6 18.6 0 0 1 5.06-5.94M9.9 4.24A10.94 10.94 0 0 1 12 4c7 0 11 8 11 8a18.6 18.6 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
            <line x1="1" y1="1" x2="23" y2="23" />
          </svg>
        ) : (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
            <circle cx="12" cy="12" r="3" />
          </svg>
        )}
      </button>
    </div>
  );
}
