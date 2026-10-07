import { useEffect, useRef } from "react";

const SITE_KEY = import.meta.env.VITE_RECAPTCHA_SITE_KEY;
const SCRIPT_ID = "recaptcha-script";

let scriptLoadPromise = null;

function loadRecaptchaScript() {
  if (scriptLoadPromise) return scriptLoadPromise;
  scriptLoadPromise = new Promise((resolve, reject) => {
    if (window.grecaptcha) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.id = SCRIPT_ID;
    script.src = "https://www.google.com/recaptcha/api.js?render=explicit";
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Failed to load reCAPTCHA"));
    document.head.appendChild(script);
  });
  return scriptLoadPromise;
}

/**
 * The "I'm not a robot" checkbox widget, rendered on the signup and
 * forgot-password forms. Genuinely functional once VITE_RECAPTCHA_SITE_KEY
 * is set (see frontend/.env.example) — until then it renders nothing
 * and `onVerify` is simply never called, so `captcha_token` stays null
 * on whatever form embeds this. That's fine: the backend (see
 * services/captcha.py) only actually enforces the check when its own
 * RECAPTCHA_SECRET_KEY is configured, so an unconfigured frontend
 * paired with an unconfigured backend is a normal, fully-working
 * no-CAPTCHA state — not a broken one. The two keys come from the same
 * Google reCAPTCHA site registration, so they're set together in
 * practice, but each side degrades independently and safely if only
 * one is set.
 */
export default function Captcha({ onVerify }) {
  const containerRef = useRef(null);
  const widgetIdRef = useRef(null);

  useEffect(() => {
    if (!SITE_KEY) return;

    let cancelled = false;

    loadRecaptchaScript()
      .then(() => {
        if (cancelled || !containerRef.current || widgetIdRef.current !== null) return;
        widgetIdRef.current = window.grecaptcha.render(containerRef.current, {
          sitekey: SITE_KEY,
          callback: (token) => onVerify(token),
          "expired-callback": () => onVerify(null),
        });
      })
      .catch(() => {
        // Script failed to load (offline, blocked, etc.) — leave the
        // widget absent rather than breaking the rest of the form.
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!SITE_KEY) return null;

  return <div ref={containerRef} style={{ margin: "8px 0" }} />;
}
