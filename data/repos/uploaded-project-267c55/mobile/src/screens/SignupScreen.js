import React, { useState } from "react";
import { View, Text, TextInput, TouchableOpacity, StyleSheet, ActivityIndicator, ScrollView } from "react-native";
import { useAuth } from "../context/AuthContext";
import Captcha from "../components/Captcha";
import PasswordInput from "../components/PasswordInput";
import { colors } from "../theme";

// "Create a new organization" is a real, supported path (matches the
// web app's own SignupPage.jsx — whoever creates an org becomes its
// admin automatically), but the realistic case for THIS app is an
// agent joining a company that already has an account — so "Join with
// an invite code" is the default tab, not "Create a new org".
export default function SignupScreen({ onDone, onSwitchToLogin }) {
  const { signup } = useAuth();
  const [mode, setMode] = useState("join"); // "join" | "create"

  const [displayName, setDisplayName] = useState("");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("agent"); // "agent" | "dispatcher" — never "admin" via invite code, same rule the backend itself enforces
  const [inviteCode, setInviteCode] = useState("");
  const [orgName, setOrgName] = useState("");

  const [captchaToken, setCaptchaToken] = useState(null);
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit() {
    setError("");
    setIsSubmitting(true);
    try {
      const result = await signup({
        username: username.trim(),
        email: email.trim(),
        password,
        displayName: displayName.trim(),
        role: mode === "create" ? "agent" : role, // role is granted admin server-side on org creation regardless of what's sent
        orgName: mode === "create" ? orgName.trim() : undefined,
        inviteCode: mode === "join" ? inviteCode.trim() : undefined,
        captchaToken,
      });
      if (onDone) onDone(result);
    } catch (err) {
      setError(err.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ padding: 24 }}>
      <Text style={styles.wordmark}>Delivery Sync</Text>
      <Text style={styles.subtitle}>Create your account</Text>

      <View style={styles.card}>
        <View style={styles.tabRow}>
          <TouchableOpacity style={[styles.tab, mode === "join" && styles.tabActive]} onPress={() => setMode("join")}>
            <Text style={[styles.tabText, mode === "join" && styles.tabTextActive]}>Join a company</Text>
          </TouchableOpacity>
          <TouchableOpacity style={[styles.tab, mode === "create" && styles.tabActive]} onPress={() => setMode("create")}>
            <Text style={[styles.tabText, mode === "create" && styles.tabTextActive]}>Create new</Text>
          </TouchableOpacity>
        </View>

        <Text style={styles.label}>Display Name</Text>
        <TextInput style={styles.input} value={displayName} onChangeText={setDisplayName} placeholder="Jane Doe" placeholderTextColor={colors.textMuted} />

        <Text style={styles.label}>Username</Text>
        <TextInput style={styles.input} value={username} onChangeText={setUsername} autoCapitalize="none" autoCorrect={false} placeholder="jane.doe" placeholderTextColor={colors.textMuted} />

        <Text style={styles.label}>Email</Text>
        <TextInput style={styles.input} value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address" placeholder="jane@example.com" placeholderTextColor={colors.textMuted} />

        <Text style={styles.label}>Password</Text>
        <PasswordInput style={styles.input} value={password} onChangeText={setPassword} placeholder="••••••••" placeholderTextColor={colors.textMuted} />

        {mode === "join" ? (
          <>
            <Text style={styles.label}>Invite Code</Text>
            <TextInput style={styles.input} value={inviteCode} onChangeText={setInviteCode} autoCapitalize="characters" placeholder="ABC12345" placeholderTextColor={colors.textMuted} />

            <Text style={styles.label}>Role</Text>
            <View style={styles.tabRow}>
              <TouchableOpacity style={[styles.tab, role === "agent" && styles.tabActive]} onPress={() => setRole("agent")}>
                <Text style={[styles.tabText, role === "agent" && styles.tabTextActive]}>Agent</Text>
              </TouchableOpacity>
              <TouchableOpacity style={[styles.tab, role === "dispatcher" && styles.tabActive]} onPress={() => setRole("dispatcher")}>
                <Text style={[styles.tabText, role === "dispatcher" && styles.tabTextActive]}>Dispatcher</Text>
              </TouchableOpacity>
            </View>
            {role === "dispatcher" ? (
              <Text style={styles.hint}>
                This app only has an agent's delivery workflow today — a
                dispatcher account will work, but you'll see an empty
                delivery list here. Use the web app for dispatching,
                zone/workforce management, and the rest of the console.
              </Text>
            ) : null}
          </>
        ) : (
          <>
            <Text style={styles.label}>Organization Name</Text>
            <TextInput style={styles.input} value={orgName} onChangeText={setOrgName} placeholder="Acme Logistics" placeholderTextColor={colors.textMuted} />
            <Text style={styles.hint}>You'll become this organization's admin.</Text>
          </>
        )}

        <Captcha onVerify={setCaptchaToken} />

        {error ? <Text style={styles.error}>{error}</Text> : null}

        <TouchableOpacity style={styles.button} onPress={handleSubmit} disabled={isSubmitting}>
          {isSubmitting ? <ActivityIndicator color={colors.accentTextOn} /> : <Text style={styles.buttonText}>Sign Up</Text>}
        </TouchableOpacity>

        <TouchableOpacity onPress={onSwitchToLogin} style={{ marginTop: 16 }}>
          <Text style={styles.switchLink}>Already have an account? Log in</Text>
        </TouchableOpacity>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bgPage },
  wordmark: { color: colors.accent, fontSize: 26, fontWeight: "700", textAlign: "center" },
  subtitle: { color: colors.textMuted, fontSize: 13, textAlign: "center", marginTop: 4, marginBottom: 24 },
  card: { backgroundColor: colors.bgSurface, borderRadius: 14, padding: 22, borderWidth: 1, borderColor: colors.border },
  label: { color: colors.textSecondary, fontSize: 12, marginBottom: 6, marginTop: 14 },
  input: { backgroundColor: colors.bgInput, borderWidth: 1, borderColor: colors.border, borderRadius: 8, padding: 12, color: colors.textPrimary, fontSize: 15 },
  hint: { color: colors.textMuted, fontSize: 11.5, marginTop: 6 },
  tabRow: { flexDirection: "row", backgroundColor: colors.bgInput, borderRadius: 8, borderWidth: 1, borderColor: colors.border, padding: 3, gap: 3 },
  tab: { flex: 1, paddingVertical: 8, borderRadius: 6, alignItems: "center" },
  tabActive: { backgroundColor: colors.accent },
  tabText: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  tabTextActive: { color: colors.accentTextOn },
  button: { backgroundColor: colors.accent, borderRadius: 8, padding: 14, alignItems: "center", marginTop: 22 },
  buttonText: { color: colors.accentTextOn, fontWeight: "700", fontSize: 15 },
  error: { color: colors.danger, fontSize: 13, marginTop: 14 },
  switchLink: { color: colors.accent, fontSize: 13, textAlign: "center", fontWeight: "600" },
});
