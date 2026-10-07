import React, { useState } from "react";
import { View, ActivityIndicator, StyleSheet } from "react-native";
import { WebView } from "react-native-webview";

/**
 * The mobile half of this project's optional bot protection (see
 * backend/app/services/captcha.py and frontend/src/components/
 * Captcha.jsx for the web widget this mirrors). Google's reCAPTCHA v2
 * checkbox is JS-in-a-browser, not a native SDK, so there's no way to
 * render the real widget as a native RN view — the standard, genuinely
 * working way to embed it in a native app (what libraries like
 * react-native-recaptcha-that-works do under the hood) is exactly
 * this: a small WebView loads a self-contained HTML page that pulls
 * in Google's own recaptcha/api.js and renders the checkbox, then
 * hands the resulting token back to React Native via
 * `window.ReactNativeWebView.postMessage()`. react-native-webview is
 * already a dependency (see SignaturePad.js, which uses the identical
 * WebView<->postMessage pattern for signature capture).
 *
 * Renders nothing (and never calls onVerify) when
 * EXPO_PUBLIC_RECAPTCHA_SITE_KEY isn't set — see mobile/.env.example.
 * That's fine: exactly like the web widget, the backend only actually
 * enforces the check when its own RECAPTCHA_SECRET_KEY is configured,
 * so an unconfigured deployment paired with no widget here is a
 * normal, fully-working no-CAPTCHA state, not a broken one.
 */
const SITE_KEY = process.env.EXPO_PUBLIC_RECAPTCHA_SITE_KEY;

function buildHtml(siteKey) {
  return `
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<style>
  html, body { margin: 0; padding: 0; background-color: transparent; overflow: hidden; }
  body { display: flex; justify-content: center; align-items: center; height: 100%; }
</style>
</head>
<body>
<div id="captcha-container"></div>
<script src="https://www.google.com/recaptcha/api.js?onload=onRecaptchaLoad&render=explicit" async defer></script>
<script>
  function post(payload) {
    window.ReactNativeWebView.postMessage(JSON.stringify(payload));
  }
  function onRecaptchaLoad() {
    try {
      grecaptcha.render('captcha-container', {
        sitekey: '${siteKey}',
        callback: function (token) { post({ type: 'verify', token: token }); },
        'expired-callback': function () { post({ type: 'expired' }); },
        'error-callback': function () { post({ type: 'error' }); }
      });
    } catch (e) {
      post({ type: 'error' });
    }
  }
</script>
</body>
</html>
`;
}

export default function Captcha({ onVerify }) {
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);

  if (!SITE_KEY) return null;

  function handleMessage(event) {
    let data;
    try {
      data = JSON.parse(event.nativeEvent.data);
    } catch {
      return; // malformed message — nothing safe to act on
    }
    if (data.type === "verify") onVerify(data.token);
    else if (data.type === "expired" || data.type === "error") onVerify(null);
  }

  return (
    <View style={styles.wrapper}>
      {loading && !loadFailed && <ActivityIndicator style={styles.loader} color="#f2a93b" />}
      <WebView
        originWhitelist={["*"]}
        source={{ html: buildHtml(SITE_KEY) }}
        onMessage={handleMessage}
        onLoadEnd={() => setLoading(false)}
        onError={() => {
          setLoadFailed(true);
          onVerify(null);
        }}
        style={styles.webview}
        javaScriptEnabled
        domStorageEnabled
        mixedContentMode="always"
        // The widget itself scrolls/zooms fine without the outer page
        // doing so — this just stops the checkbox challenge iframe
        // from fighting the surrounding ScrollView on the signup/
        // forgot-password screens it's embedded in.
        scrollEnabled={false}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: { height: 88, marginVertical: 10, alignItems: "center", justifyContent: "center" },
  webview: { width: 300, height: 88, backgroundColor: "transparent" },
  loader: { position: "absolute" },
});
