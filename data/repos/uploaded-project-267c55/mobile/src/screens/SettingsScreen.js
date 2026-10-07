import React, { useCallback, useEffect, useState } from "react";
import { View, Text, TouchableOpacity, StyleSheet, Switch, Alert, ActivityIndicator } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { useAuth } from "../context/AuthContext";
import {
  startBackgroundLocationTracking,
  stopBackgroundLocationTracking,
  isBackgroundLocationTrackingActive,
} from "../locationTask";
import { getPendingCount } from "../services/offlineStore";
import { runSync } from "../services/offlineSync";
import { colors } from "../theme";

export default function SettingsScreen() {
  const { user, logout } = useAuth();
  const [isSharing, setIsSharing] = useState(false);
  const [permissionNote, setPermissionNote] = useState("");
  const [isBusy, setIsBusy] = useState(false);
  const [pendingCount, setPendingCount] = useState(0);
  const [isSyncing, setIsSyncing] = useState(false);

  useEffect(() => {
    isBackgroundLocationTrackingActive().then(setIsSharing);
  }, []);

  useFocusEffect(
    useCallback(() => {
      getPendingCount().then(setPendingCount);
    }, [])
  );

  async function handleSyncNow() {
    setIsSyncing(true);
    try {
      const result = await runSync();
      setPendingCount(await getPendingCount());
      if (result.success) {
        Alert.alert(
          "Sync complete",
          result.syncedCount > 0 ? `Synced ${result.syncedCount} update(s).` : "Nothing to sync — you're up to date."
        );
      } else {
        Alert.alert("Sync failed", result.error || "Couldn't reach the server. Still saved on this device.");
      }
    } finally {
      setIsSyncing(false);
    }
  }

  async function handleToggle(value) {
    setIsBusy(true);
    setPermissionNote("");
    try {
      if (value) {
        const result = await startBackgroundLocationTracking();
        if (result.granted === "denied") {
          setPermissionNote("Location permission denied — turn it on in your phone's Settings app to share your location.");
          setIsSharing(false);
        } else if (result.granted === "foreground") {
          setPermissionNote("Sharing while the app is open. Grant \"Always\" location access in Settings for this to keep working while your phone is locked.");
          setIsSharing(true);
        } else {
          setIsSharing(true);
        }
      } else {
        await stopBackgroundLocationTracking();
        setIsSharing(false);
      }
    } catch (err) {
      Alert.alert("Couldn't change location sharing", err.message);
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <View style={styles.container}>
      <View style={styles.section}>
        <Text style={styles.sectionLabel}>Signed in as</Text>
        <Text style={styles.value}>{user?.display_name}</Text>
        <Text style={styles.subvalue}>{user?.email}</Text>
      </View>

      <View style={styles.row}>
        <View style={{ flex: 1 }}>
          <Text style={styles.rowLabel}>Share my location</Text>
          <Text style={styles.rowHint}>
            Keeps updating dispatch and any customer's live tracking map — including while this
            app is in the background or your phone is locked.
          </Text>
        </View>
        <Switch
          value={isSharing}
          onValueChange={handleToggle}
          disabled={isBusy}
          trackColor={{ false: colors.border, true: colors.accent }}
          thumbColor={colors.bgSurface}
        />
      </View>

      {permissionNote ? <Text style={styles.note}>{permissionNote}</Text> : null}

      <View style={[styles.row, { marginTop: 16 }]}>
        <View style={{ flex: 1 }}>
          <Text style={styles.rowLabel}>Offline updates</Text>
          <Text style={styles.rowHint}>
            {pendingCount > 0
              ? `${pendingCount} update${pendingCount === 1 ? "" : "s"} saved on this device, waiting to sync.`
              : "Nothing waiting to sync — you're up to date."}
          </Text>
        </View>
        <TouchableOpacity style={styles.syncButton} onPress={handleSyncNow} disabled={isSyncing}>
          {isSyncing ? <ActivityIndicator color={colors.accentTextOn} size="small" /> : <Text style={styles.syncButtonText}>Sync Now</Text>}
        </TouchableOpacity>
      </View>

      <TouchableOpacity style={styles.logoutButton} onPress={logout}>
        <Text style={styles.logoutText}>Log Out</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bgPage, padding: 20 },
  section: { backgroundColor: colors.bgSurface, borderRadius: 10, borderWidth: 1, borderColor: colors.border, padding: 16, marginBottom: 20 },
  sectionLabel: { color: colors.textMuted, fontSize: 11, textTransform: "uppercase", marginBottom: 6 },
  value: { color: colors.textPrimary, fontSize: 16, fontWeight: "600" },
  subvalue: { color: colors.textSecondary, fontSize: 13, marginTop: 2 },
  row: { flexDirection: "row", alignItems: "center", backgroundColor: colors.bgSurface, borderRadius: 10, borderWidth: 1, borderColor: colors.border, padding: 16, gap: 12 },
  rowLabel: { color: colors.textPrimary, fontSize: 15, fontWeight: "600" },
  rowHint: { color: colors.textSecondary, fontSize: 12, marginTop: 4, lineHeight: 17 },
  note: { color: colors.accent, fontSize: 12, marginTop: 12, lineHeight: 17 },
  syncButton: { backgroundColor: colors.accent, borderRadius: 8, paddingVertical: 10, paddingHorizontal: 16 },
  syncButtonText: { color: colors.accentTextOn, fontWeight: "700", fontSize: 13 },
  logoutButton: { marginTop: 32, padding: 14, borderRadius: 8, borderWidth: 1, borderColor: colors.danger, alignItems: "center" },
  logoutText: { color: colors.danger, fontWeight: "700", fontSize: 14 },
});
