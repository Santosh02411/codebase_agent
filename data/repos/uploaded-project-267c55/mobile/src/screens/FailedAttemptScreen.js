import React, { useEffect, useState } from "react";
import { View, Text, TouchableOpacity, StyleSheet, ActivityIndicator, ScrollView, TextInput, Alert } from "react-native";
import { fetchActiveReasonCodes, updateDeliveryStatus } from "../services/api";
import { colors } from "../theme";

export default function FailedAttemptScreen({ route, navigation }) {
  const { delivery } = route.params;

  const [reasons, setReasons] = useState([]);
  const [selectedReasonId, setSelectedReasonId] = useState(null);
  const [notes, setNotes] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchActiveReasonCodes()
      .then(setReasons)
      .catch((err) => setError(err.message))
      .finally(() => setIsLoading(false));
  }, []);

  async function handleSubmit() {
    if (!selectedReasonId) {
      setError("Choose a reason for the failed attempt.");
      return;
    }
    setError("");
    setIsSubmitting(true);
    try {
      const result = await updateDeliveryStatus(delivery, "failed_attempt", {
        reason_code_id: selectedReasonId,
        notes: notes.trim() || undefined,
      });
      if (result.queued) {
        Alert.alert("Saved offline", "No connection right now — this will sync automatically once you're back online.");
      }
      navigation.navigate("DeliveryDetail", { deliveryId: delivery.id });
    } catch (err) {
      setError(err.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  if (isLoading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  }

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ padding: 20 }}>
      <Text style={styles.title}>Mark Failed Attempt</Text>
      <Text style={styles.subtitle}>{delivery.order_id}</Text>

      <Text style={styles.label}>Reason</Text>
      {reasons.length === 0 ? (
        <Text style={styles.empty}>No reason codes have been set up for your organization yet — ask a dispatcher/admin to add some in Settings.</Text>
      ) : (
        reasons.map((reason) => (
          <TouchableOpacity
            key={reason.id}
            style={[styles.reasonRow, selectedReasonId === reason.id && styles.reasonRowSelected]}
            onPress={() => setSelectedReasonId(reason.id)}
          >
            <View style={[styles.radio, selectedReasonId === reason.id && styles.radioSelected]} />
            <View style={{ flex: 1 }}>
              <Text style={styles.reasonLabel}>{reason.label}</Text>
              {reason.description ? <Text style={styles.reasonDescription}>{reason.description}</Text> : null}
              {reason.eligible_for_rto && <Text style={styles.rtoTag}>Eligible for return-to-origin</Text>}
            </View>
          </TouchableOpacity>
        ))
      )}

      <Text style={styles.label}>Notes (optional)</Text>
      <TextInput
        style={[styles.input, styles.multiline]}
        value={notes}
        onChangeText={setNotes}
        multiline
        placeholder="Anything else worth noting"
        placeholderTextColor={colors.textMuted}
      />

      {error ? <Text style={styles.error}>{error}</Text> : null}

      <TouchableOpacity style={styles.button} onPress={handleSubmit} disabled={isSubmitting || reasons.length === 0}>
        {isSubmitting ? <ActivityIndicator color={colors.accentTextOn} /> : <Text style={styles.buttonText}>Confirm Failed Attempt</Text>}
      </TouchableOpacity>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bgPage },
  centered: { flex: 1, backgroundColor: colors.bgPage, justifyContent: "center", alignItems: "center" },
  title: { color: colors.textPrimary, fontSize: 20, fontWeight: "700" },
  subtitle: { color: colors.textMuted, fontSize: 13, fontFamily: "monospace", marginTop: 4, marginBottom: 16 },
  label: { color: colors.textSecondary, fontSize: 12, marginBottom: 8, marginTop: 14 },
  empty: { color: colors.textMuted, fontSize: 13, lineHeight: 19 },
  reasonRow: { flexDirection: "row", alignItems: "flex-start", gap: 12, backgroundColor: colors.bgSurface, borderWidth: 1, borderColor: colors.border, borderRadius: 8, padding: 14, marginBottom: 10 },
  reasonRowSelected: { borderColor: colors.accent, backgroundColor: `${colors.accent}14` },
  radio: { width: 18, height: 18, borderRadius: 9, borderWidth: 2, borderColor: colors.border, marginTop: 2 },
  radioSelected: { borderColor: colors.accent, backgroundColor: colors.accent },
  reasonLabel: { color: colors.textPrimary, fontSize: 14, fontWeight: "600" },
  reasonDescription: { color: colors.textSecondary, fontSize: 12, marginTop: 3 },
  rtoTag: { color: colors.info, fontSize: 11, marginTop: 4, fontWeight: "600" },
  input: { backgroundColor: colors.bgInput, borderWidth: 1, borderColor: colors.border, borderRadius: 8, padding: 12, color: colors.textPrimary, fontSize: 15 },
  multiline: { minHeight: 70, textAlignVertical: "top" },
  error: { color: colors.danger, fontSize: 13, marginTop: 14 },
  button: { backgroundColor: colors.danger, borderRadius: 8, padding: 16, alignItems: "center", marginTop: 22 },
  buttonText: { color: "#ffffff", fontWeight: "700", fontSize: 15 },
});
