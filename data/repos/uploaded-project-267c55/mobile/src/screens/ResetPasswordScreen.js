import React, { useState } from "react";
import { View, Text, TouchableOpacity, StyleSheet, ActivityIndicator } from "react-native";
import { resetPassword } from "../services/api";
import PasswordInput from "../components/PasswordInput";
import { colors } from "../theme";

/**
 * The second half of the password-reset flow ForgotPasswordScreen
 * starts — reached by tapping a `deliverysync://reset-password?token=
 * ...` link (see App.js's deep-link handling), whether that link came
 * from tapping "Open in app" on the web reset page in a mobile browser,
 * or from the app already having been in the foreground/background
 * when the link was tapped. `token` is handed down from App.js, which
 * parsed it out of the URL — this screen never touches Linking itself.
 *
 * Mirrors the web app's ResetPasswordPage.jsx (same two fields, same
 * POST /auth/reset-password call, same generic success message from
 * the backend) rather than reinventing the flow.
 */
export default function ResetPasswordScreen({ token, onDone }) {
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit() {
    setError("");

    if (newPassword !== confirmPassword) {
      setError("Passwords don't match.");
      return;
    }

    setIsSubmitting(true);
    try {
      const result = await resetPassword(token, newPassword);
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
        <Text style={styles.title}>Set a new password</Text>

        {!message ? (
          <>
            <Text style={styles.label}>New Password</Text>
            <PasswordInput
              style={styles.input}
              value={newPassword}
              onChangeText={setNewPassword}
              autoFocus
              placeholder="••••••••"
              placeholderTextColor={colors.textMuted}
            />

            <Text style={styles.label}>Confirm New Password</Text>
            <PasswordInput
              style={styles.input}
              value={confirmPassword}
              onChangeText={setConfirmPassword}
              placeholder="••••••••"
              placeholderTextColor={colors.textMuted}
            />

            {error ? <Text style={styles.error}>{error}</Text> : null}

            <TouchableOpacity style={styles.button} onPress={handleSubmit} disabled={isSubmitting}>
              {isSubmitting ? <ActivityIndicator color={colors.accentTextOn} /> : <Text style={styles.buttonText}>Reset Password</Text>}
            </TouchableOpacity>
          </>
        ) : (
          <>
            <Text style={styles.success}>{message}</Text>
            <TouchableOpacity style={styles.button} onPress={onDone}>
              <Text style={styles.buttonText}>Continue to Log In</Text>
            </TouchableOpacity>
          </>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bgPage, justifyContent: "center", padding: 24 },
  wordmark: { color: colors.accent, fontSize: 26, fontWeight: "700", textAlign: "center", marginBottom: 24 },
  card: { backgroundColor: colors.bgSurface, borderRadius: 14, padding: 22, borderWidth: 1, borderColor: colors.border },
  title: { color: colors.textPrimary, fontSize: 17, fontWeight: "700" },
  label: { color: colors.textSecondary, fontSize: 12, marginBottom: 6, marginTop: 16 },
  input: { backgroundColor: colors.bgInput, borderWidth: 1, borderColor: colors.border, borderRadius: 8, padding: 12, color: colors.textPrimary, fontSize: 15 },
  button: { backgroundColor: colors.accent, borderRadius: 8, padding: 14, alignItems: "center", marginTop: 18 },
  buttonText: { color: colors.accentTextOn, fontWeight: "700", fontSize: 15 },
  error: { color: colors.danger, fontSize: 13, marginTop: 14 },
  success: { color: colors.success, fontSize: 13, marginTop: 8, lineHeight: 18 },
});
