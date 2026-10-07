import React, { useEffect, useState } from "react";
import { View, ActivityIndicator, StyleSheet } from "react-native";
import * as Linking from "expo-linking";
import { AuthProvider, useAuth } from "./src/context/AuthContext";
import LoginScreen from "./src/screens/LoginScreen";
import SignupScreen from "./src/screens/SignupScreen";
import ForgotPasswordScreen from "./src/screens/ForgotPasswordScreen";
import ResetPasswordScreen from "./src/screens/ResetPasswordScreen";
import AppNavigator from "./src/AppNavigator";
import { colors } from "./src/theme";
import { startAutoSync } from "./src/services/offlineSync";
import { registerForPushNotifications } from "./src/services/pushNotifications";

// Registers the background location task (see src/locationTask.js) as
// a side effect of import — TaskManager.defineTask() must run once at
// module load time, before any screen tries to start/stop it, exactly
// like Expo's own docs specify.
import "./src/locationTask";

function Root() {
  const { user, isLoading } = useAuth();
  // Which unauthenticated screen is showing — only meaningful while
  // `user` is null; reset to "login" the moment a real session starts,
  // so signing out and back in another way doesn't reopen on whatever
  // screen was last showing.
  const [authScreen, setAuthScreen] = useState("login"); // "login" | "signup" | "forgotPassword"

  // The reset token pulled out of an incoming `deliverysync://
  // reset-password?token=...` link (see app.json's "scheme" field for
  // where that scheme is registered, and ForgotPasswordScreen.js /
  // frontend/src/components/ResetPasswordPage.jsx's "Open in app" link
  // for where it comes from). Deliberately tracked independently of
  // `user`/`authScreen`: someone tapping an old reset link while
  // already logged in as a different account should still be able to
  // finish resetting the OTHER account's password without signing out
  // first, so this takes priority over both the authenticated and
  // logged-out render branches below, whichever is currently showing.
  const [resetToken, setResetToken] = useState(null);

  useEffect(() => {
    function handleUrl(url) {
      if (!url) return;
      const { hostname, path, queryParams } = Linking.parse(url);
      if (hostname === "reset-password" || path === "reset-password") {
        if (queryParams?.token) setResetToken(queryParams.token);
      }
    }
    // Cold start (app was closed, link opened it) ...
    Linking.getInitialURL().then(handleUrl);
    // ...and warm start (app was already running/backgrounded).
    const subscription = Linking.addEventListener("url", ({ url }) => handleUrl(url));
    return () => subscription.remove();
  }, []);

  // Only runs once a real, logged-in user is known — the sync engine
  // has nothing to authenticate as before that, and (more importantly)
  // offlineStore's setActiveUser(profile.id) must have already run
  // (see AuthContext.js's applyUser) before any pending-queue read is
  // safe to attempt.
  useEffect(() => {
    if (!user) return undefined;
    setAuthScreen("login");
    const stopAutoSync = startAutoSync();
    return stopAutoSync;
  }, [user?.id]);

  // Same "only once a real user is known" reasoning as above — the
  // registered token needs to be attributed to somebody. Fire-and-
  // forget: registerForPushNotifications() never throws (see its own
  // docstring), so there's nothing to await or handle here.
  useEffect(() => {
    if (!user) return;
    registerForPushNotifications();
  }, [user?.id]);

  if (resetToken) {
    return <ResetPasswordScreen token={resetToken} onDone={() => setResetToken(null)} />;
  }

  if (isLoading) {
    return (
      <View style={styles.loading}>
        <ActivityIndicator color={colors.accent} size="large" />
      </View>
    );
  }

  if (user) return <AppNavigator />;

  if (authScreen === "signup") {
    return <SignupScreen onDone={() => setAuthScreen("login")} onSwitchToLogin={() => setAuthScreen("login")} />;
  }
  if (authScreen === "forgotPassword") {
    return <ForgotPasswordScreen onBackToLogin={() => setAuthScreen("login")} />;
  }
  return (
    <LoginScreen
      onSwitchToSignup={() => setAuthScreen("signup")}
      onForgotPassword={() => setAuthScreen("forgotPassword")}
    />
  );
}

export default function App() {
  return (
    <AuthProvider>
      <Root />
    </AuthProvider>
  );
}

const styles = StyleSheet.create({
  loading: { flex: 1, backgroundColor: colors.bgPage, justifyContent: "center", alignItems: "center" },
});
