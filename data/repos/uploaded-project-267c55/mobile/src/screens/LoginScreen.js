import React, { useState } from "react";
import { View, Text, TextInput, TouchableOpacity, StyleSheet, ActivityIndicator, KeyboardAvoidingView, Platform } from "react-native";
import { StatusBar } from "expo-status-bar";
import { useAuth } from "../context/AuthContext";
import PasswordInput from "../components/PasswordInput";
import { colors } from "../theme";

export default function LoginScreen({ onSwitchToSignup, onForgotPassword }) {
  const { login, completeTwoFactorLogin } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [twoFactorChallenge, setTwoFactorChallenge] = useState(null); // { challenge_token }
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleLogin() {
    setError("");
    setIsSubmitting(true);
    try {
      const result = await login(username.trim(), password);
      if (result.requires_2fa) {
        setTwoFactorChallenge(result);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleVerifyCode() {
    setError("");
    setIsSubmitting(true);
    try {
      await completeTwoFactorLogin(twoFactorChallenge.challenge_token, code.trim());
    } catch (err) {
      setError(err.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <KeyboardAvoidingView style={styles.container} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <StatusBar style="light" />
      <Text style={styles.wordmark}>Delivery Sync</Text>
      <Text style={styles.subtitle}>Agent App</Text>

      <View style={styles.card}>
        {!twoFactorChallenge ? (
          <>
            <Text style={styles.label}>Username</Text>
            <TextInput
              style={styles.input}
              value={username}
              onChangeText={setUsername}
              autoCapitalize="none"
              autoCorrect={false}
              placeholder="your.username"
              placeholderTextColor={colors.textMuted}
            />
            <Text style={styles.label}>Password</Text>
            <PasswordInput
              style={styles.input}
              value={password}
              onChangeText={setPassword}
              placeholder="••••••••"
              placeholderTextColor={colors.textMuted}
            />
            {error ? <Text style={styles.error}>{error}</Text> : null}
            <TouchableOpacity style={styles.button} onPress={handleLogin} disabled={isSubmitting}>
              {isSubmitting ? <ActivityIndicator color={colors.accentTextOn} /> : <Text style={styles.buttonText}>Log In</Text>}
            </TouchableOpacity>
            <TouchableOpacity onPress={onForgotPassword} style={{ marginTop: 16 }}>
              <Text style={styles.linkText}>Forgot password?</Text>
            </TouchableOpacity>
          </>
        ) : (
          <>
            <Text style={styles.label}>Enter your 2FA code</Text>
            <TextInput
              style={styles.input}
              value={code}
              onChangeText={setCode}
              keyboardType="number-pad"
              placeholder="123456"
              placeholderTextColor={colors.textMuted}
              maxLength={6}
            />
            {error ? <Text style={styles.error}>{error}</Text> : null}
            <TouchableOpacity style={styles.button} onPress={handleVerifyCode} disabled={isSubmitting}>
              {isSubmitting ? <ActivityIndicator color={colors.accentTextOn} /> : <Text style={styles.buttonText}>Verify</Text>}
            </TouchableOpacity>
          </>
        )}
      </View>

      <Text style={styles.footnote}>
        Uses the same account as the web dispatcher/agent console.
      </Text>
      {!twoFactorChallenge && (
        <TouchableOpacity onPress={onSwitchToSignup} style={{ marginTop: 12 }}>
          <Text style={styles.linkText}>New agent? Sign up</Text>
        </TouchableOpacity>
      )}
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bgPage, justifyContent: "center", padding: 24 },
  wordmark: { color: colors.accent, fontSize: 28, fontWeight: "700", textAlign: "center" },
  subtitle: { color: colors.textMuted, fontSize: 13, textAlign: "center", marginTop: 4, marginBottom: 32 },
  card: { backgroundColor: colors.bgSurface, borderRadius: 14, padding: 24, borderWidth: 1, borderColor: colors.border },
  label: { color: colors.textSecondary, fontSize: 12, marginBottom: 6, marginTop: 12 },
  input: { backgroundColor: colors.bgInput, borderWidth: 1, borderColor: colors.border, borderRadius: 8, padding: 12, color: colors.textPrimary, fontSize: 15 },
  button: { backgroundColor: colors.accent, borderRadius: 8, padding: 14, alignItems: "center", marginTop: 20 },
  buttonText: { color: colors.accentTextOn, fontWeight: "700", fontSize: 15 },
  error: { color: colors.danger, fontSize: 13, marginTop: 12 },
  footnote: { color: colors.textMuted, fontSize: 12, textAlign: "center", marginTop: 24 },
  linkText: { color: colors.accent, fontSize: 13, textAlign: "center", fontWeight: "600" },
});
