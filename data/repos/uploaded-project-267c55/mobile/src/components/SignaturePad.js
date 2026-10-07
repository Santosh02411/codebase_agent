import React, { useRef } from "react";
import { View, StyleSheet, TouchableOpacity, Text } from "react-native";
import { WebView } from "react-native-webview";
import { colors } from "../theme";

/**
 * A drawable signature pad, implemented as a plain HTML5 <canvas>
 * inside a WebView rather than a dedicated native signature-drawing
 * library — one fewer native dependency to keep in sync with Expo SDK
 * upgrades, and an HTML canvas free-hand drawing implementation is
 * genuinely simple (a few lines of pointer-event handling). The
 * canvas posts its final drawing back to React Native as a base64 PNG
 * data URL via `window.ReactNativeWebView.postMessage()` — the same
 * `data:image/png;base64,...` shape
 * backend/app/models/proof_of_delivery.py's `signature_data_url`
 * field already expects (this project's own web app's signature
 * capture, wherever it happens, produces the identical shape from an
 * HTML canvas for the exact same reason).
 */
export default function SignaturePad({ onSave, onCancel }) {
  const webviewRef = useRef(null);

  function handleMessage(event) {
    const dataUrl = event.nativeEvent.data;
    if (dataUrl && dataUrl.startsWith("data:image/png")) {
      onSave(dataUrl);
    }
  }

  function requestSave() {
    webviewRef.current?.injectJavaScript(`
      (function() {
        window.ReactNativeWebView.postMessage(canvas.toDataURL('image/png'));
      })();
      true;
    `);
  }

  function requestClear() {
    webviewRef.current?.injectJavaScript(`
      (function() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
      })();
      true;
    `);
  }

  return (
    <View style={styles.container}>
      <WebView
        ref={webviewRef}
        originWhitelist={["*"]}
        source={{ html: SIGNATURE_HTML }}
        onMessage={handleMessage}
        style={styles.webview}
        scrollEnabled={false}
      />
      <View style={styles.buttonRow}>
        <TouchableOpacity style={styles.secondaryButton} onPress={requestClear}>
          <Text style={styles.secondaryButtonText}>Clear</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.secondaryButton} onPress={onCancel}>
          <Text style={styles.secondaryButtonText}>Cancel</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.primaryButton} onPress={requestSave}>
          <Text style={styles.primaryButtonText}>Use Signature</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

// Deliberately plain, dependency-free HTML/JS — pointer events (not
// separate touch/mouse handlers) so this works identically whether
// tested in a physical device, a simulator, or expo start --web.
const SIGNATURE_HTML = `
<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <style>
    html, body { margin: 0; padding: 0; background: #ffffff; overflow: hidden; touch-action: none; }
    canvas { display: block; width: 100%; height: 100%; }
  </style>
</head>
<body>
  <canvas id="canvas"></canvas>
  <script>
    var canvas = document.getElementById('canvas');
    var ctx = canvas.getContext('2d');

    function resize() {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
      ctx.lineWidth = 3;
      ctx.lineCap = 'round';
      ctx.strokeStyle = '#0b0e14';
    }
    resize();
    window.addEventListener('resize', resize);

    var drawing = false;

    function pos(e) {
      var rect = canvas.getBoundingClientRect();
      return { x: e.clientX - rect.left, y: e.clientY - rect.top };
    }

    canvas.addEventListener('pointerdown', function(e) {
      drawing = true;
      var p = pos(e);
      ctx.beginPath();
      ctx.moveTo(p.x, p.y);
    });
    canvas.addEventListener('pointermove', function(e) {
      if (!drawing) return;
      var p = pos(e);
      ctx.lineTo(p.x, p.y);
      ctx.stroke();
    });
    canvas.addEventListener('pointerup', function() { drawing = false; });
    canvas.addEventListener('pointercancel', function() { drawing = false; });
  </script>
</body>
</html>
`;

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#ffffff" },
  webview: { flex: 1 },
  buttonRow: { flexDirection: "row", padding: 12, gap: 8, backgroundColor: colors.bgSurface, borderTopWidth: 1, borderTopColor: colors.border },
  secondaryButton: { flex: 1, padding: 12, borderRadius: 8, borderWidth: 1, borderColor: colors.border, alignItems: "center" },
  secondaryButtonText: { color: colors.textPrimary, fontWeight: "600", fontSize: 13 },
  primaryButton: { flex: 2, padding: 12, borderRadius: 8, backgroundColor: colors.accent, alignItems: "center" },
  primaryButtonText: { color: colors.accentTextOn, fontWeight: "700", fontSize: 13 },
});
