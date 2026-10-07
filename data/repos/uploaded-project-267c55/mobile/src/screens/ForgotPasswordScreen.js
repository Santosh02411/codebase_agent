import React, { useState } from "react";
import { View, Text, TextInput, TouchableOpacity, StyleSheet, ActivityIndicator } from "react-native";
import { forgotPassword } from "../services/api";
import Captcha from "../components/Captcha";
import { colors } from "../theme";

/**
 * Requests a password reset email — the same POST /auth/forgot-
 * password the web app's ForgotPasswordPage.jsx calls. The reset link
 * in that email opens the web app by default (see FRONTEND_URL in
 * backend/app/routes/auth.py), but that web page now also offers an
 * "Open in the Delivery Sync app" option (see frontend/src/components/
 * ResetPasswordPage.jsx) — a `deliverysync://reset-password?token=...`
 * link that, if this app is installed, opens it directly to
 * ../screens/ResetPasswordScreen.js instead. See App.js for how that
 * deep link is caught and routed. There's still no true
 * "click the email, land straight in the app, no browser involved"
 * flow — that needs a verified HTTPS domain (Android App Links / iOS
 * Universal Links) this sandbox has no way to register or test — so
 * the honest middle ground is: web link works everywhere, with a real
 * one-tap path into the app for anyone who has it installed.
 */
export default function ForgotPasswordScreen({ onBackToLogin }) {
  const [email, setEmail] = useState("");
  const [captchaToken, setCaptchaToken] = useState(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit() {
    setError("");
    setMessage("");
    setIsSubmitting(true);
    try {
      const result = await forgotPassword(email.trim(), captchaToken);
      setMessage(result.message);
    } catch (err) {
      setError(err.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <View style={styles.container}>
      <Text style={styles.wordmark}>Delivery Sync</Text>

      <View style={styles.card}>
        <Text style={styles.title}>Reset your password</Text>
        <Text style={styles.hint}>
          Enter your account email — we'll send a reset link. Tap it on this phone
          to open the app directly and set a new password, or open it in a browser
          if you'd rather do that instead.
        </Text>

        <Text style={styles.label}>Email</Text>
        <TextInput
          style={styles.input}
          value={email}
          onChangeText={setEmail}
          autoCapitalize="none"
          keyboardType="email-address"
          placeholder="you@example.com"
          placeholderTextColor={colors.textMuted}
          editable={!message}
        />

        {!message ? <Captcha onVerify={setCaptchaToken} /> : null}

        {error ? <Text style={styles.error}>{error}</Text> : null}
        {message ? <Text style={styles.success}>{message}</Text> : null}

        {!message ? (
          <TouchableOpacity style={styles.button} onPress={handleSubmit} disabled={isSubmitting}>
            {isSubmitting ? <ActivityIndicator color={colors.accentTextOn} /> : <Text style={styles.buttonText}>Send Reset Link</Text>}
          </TouchableOpacity>
        ) : null}

        <TouchableOpacity onPress={onBackToLogin} style={{ marginTop: 18 }}>
          <Text style={styles.switchLink}>Back to log in</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bgPage, justifyContent: "center", padding: 24 },
  wordmark: { color: colors.accent, fontSize: 26, fontWeight: "700", textAlign: "center", marginBottom: 24 },
  card: { backgroundColor: colors.bgSurface, borderRadius: 14, padding: 22, borderWidth: 1, borderColor: colors.border },
  title: { color: colors.textPrimary, fontSize: 17, fontWeight: "700" },
  hint: { color: colors.textSecondary, fontSize: 12.5, marginTop: 8, lineHeight: 18 },
  label: { color: colors.textSecondary, fontSize: 12, marginBottom: 6, marginTop: 16 },
  input: { backgroundColor: colors.bgInput, borderWidth: 1, borderColor: colors.border, borderRadius: 8, padding: 12, color: colors.textPrimary, fontSize: 15 },
  button: { backgroundColor: colors.accent, borderRadius: 8, padding: 14, alignItems: "center", marginTop: 18 },
  buttonText: { color: colors.accentTextOn, fontWeight: "700", fontSize: 15 },
  error: { color: colors.danger, fontSize: 13, marginTop: 14 },
  success: { color: colors.success, fontSize: 13, marginTop: 14, lineHeight: 18 },
  switchLink: { color: colors.accent, fontSize: 13, textAlign: "center", fontWeight: "600" },
});
