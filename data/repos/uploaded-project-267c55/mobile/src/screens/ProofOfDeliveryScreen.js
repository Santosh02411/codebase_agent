import React, { useState } from "react";
import { View, Text, TextInput, TouchableOpacity, StyleSheet, ActivityIndicator, ScrollView, Image, Switch, Modal, Alert } from "react-native";
import * as ImagePicker from "expo-image-picker";
import * as Location from "expo-location";
import { submitProofOfDelivery, updateDeliveryStatus } from "../services/api";
import SignaturePad from "../components/SignaturePad";
import { colors } from "../theme";

/**
 * Marking a delivery "Delivered" is a two-step backend flow by design
 * (see api.js's submitProofOfDelivery docstring): submit POD first,
 * then PATCH the status. This screen exists to do exactly that as one
 * user-facing action — an agent shouldn't need to understand the
 * two-call sequence to use it.
 */
export default function ProofOfDeliveryScreen({ route, navigation }) {
  const { delivery } = route.params;

  const [recipientName, setRecipientName] = useState("");
  const [notes, setNotes] = useState("");
  const [photoDataUrl, setPhotoDataUrl] = useState(null);
  const [signatureDataUrl, setSignatureDataUrl] = useState(null);
  const [isPartial, setIsPartial] = useState(false);
  const [isSignaturePadOpen, setIsSignaturePadOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function handleTakePhoto() {
    const permission = await ImagePicker.requestCameraPermissionsAsync();
    if (!permission.granted) {
      Alert.alert("Camera permission needed", "Enable camera access in Settings to take a delivery photo.");
      return;
    }
    const result = await ImagePicker.launchCameraAsync({ base64: true, quality: 0.5 });
    if (!result.canceled && result.assets?.[0]?.base64) {
      setPhotoDataUrl(`data:image/jpeg;base64,${result.assets[0].base64}`);
    }
  }

  async function handleSubmit() {
    setError("");
    setIsSubmitting(true);
    try {
      let coords = {};
      try {
        const { status } = await Location.getForegroundPermissionsAsync();
        if (status === "granted") {
          const position = await Location.getLastKnownPositionAsync();
          if (position) {
            coords = { latitude: position.coords.latitude, longitude: position.coords.longitude };
          }
        }
      } catch {
        // GPS attachment on proof of delivery is a nice-to-have, never
        // a reason to block submission — silently proceed without it.
      }

      if (recipientName.trim() || photoDataUrl || signatureDataUrl || notes.trim() || coords.latitude) {
        await submitProofOfDelivery(delivery.id, {
          recipientName: recipientName.trim(),
          photoDataUrl,
          signatureDataUrl,
          notes: notes.trim(),
          ...coords,
        });
      }

      const result = await updateDeliveryStatus(delivery, "delivered", { is_partial: isPartial });
      // navigate (not push/replace with extra params) — DeliveryDetailScreen's
      // own useFocusEffect re-fetches on focus, so there's no need to
      // thread the just-updated record back through navigation params.
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

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ padding: 20 }}>
      <Text style={styles.title}>Mark Delivered</Text>
      <Text style={styles.subtitle}>{delivery.order_id}</Text>

      <Text style={styles.label}>Recipient Name (optional)</Text>
      <TextInput style={styles.input} value={recipientName} onChangeText={setRecipientName} placeholder="Who received it" placeholderTextColor={colors.textMuted} />

      <View style={styles.captureRow}>
        <TouchableOpacity style={styles.captureButton} onPress={handleTakePhoto}>
          <Text style={styles.captureButtonText}>{photoDataUrl ? "Retake Photo" : "📷 Take Photo"}</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.captureButton} onPress={() => setIsSignaturePadOpen(true)}>
          <Text style={styles.captureButtonText}>{signatureDataUrl ? "Redo Signature" : "✍️ Get Signature"}</Text>
        </TouchableOpacity>
      </View>

      {photoDataUrl ? <Image source={{ uri: photoDataUrl }} style={styles.preview} /> : null}
      {signatureDataUrl ? <Image source={{ uri: signatureDataUrl }} style={[styles.preview, styles.signaturePreview]} /> : null}

      <Text style={styles.label}>Notes (optional)</Text>
      <TextInput style={[styles.input, styles.multiline]} value={notes} onChangeText={setNotes} multiline placeholder="Anything worth noting" placeholderTextColor={colors.textMuted} />

      <View style={styles.partialRow}>
        <View style={{ flex: 1 }}>
          <Text style={styles.rowLabel}>Partial delivery</Text>
          <Text style={styles.rowHint}>Only some of the order's items were actually delivered.</Text>
        </View>
        <Switch value={isPartial} onValueChange={setIsPartial} trackColor={{ false: colors.border, true: colors.accent }} thumbColor={colors.bgSurface} />
      </View>

      {error ? <Text style={styles.error}>{error}</Text> : null}

      <TouchableOpacity style={styles.button} onPress={handleSubmit} disabled={isSubmitting}>
        {isSubmitting ? <ActivityIndicator color={colors.accentTextOn} /> : <Text style={styles.buttonText}>Confirm Delivered</Text>}
      </TouchableOpacity>

      <Modal visible={isSignaturePadOpen} animationType="slide">
        <SignaturePad
          onSave={(dataUrl) => {
            setSignatureDataUrl(dataUrl);
            setIsSignaturePadOpen(false);
          }}
          onCancel={() => setIsSignaturePadOpen(false)}
        />
      </Modal>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bgPage },
  title: { color: colors.textPrimary, fontSize: 20, fontWeight: "700" },
  subtitle: { color: colors.textMuted, fontSize: 13, fontFamily: "monospace", marginTop: 4, marginBottom: 16 },
  label: { color: colors.textSecondary, fontSize: 12, marginBottom: 6, marginTop: 14 },
  input: { backgroundColor: colors.bgInput, borderWidth: 1, borderColor: colors.border, borderRadius: 8, padding: 12, color: colors.textPrimary, fontSize: 15 },
  multiline: { minHeight: 70, textAlignVertical: "top" },
  captureRow: { flexDirection: "row", gap: 10, marginTop: 16 },
  captureButton: { flex: 1, backgroundColor: colors.bgSurface, borderWidth: 1, borderColor: colors.border, borderRadius: 8, padding: 14, alignItems: "center" },
  captureButtonText: { color: colors.textPrimary, fontWeight: "600", fontSize: 13 },
  preview: { width: "100%", height: 160, borderRadius: 8, marginTop: 14, resizeMode: "cover" },
  signaturePreview: { backgroundColor: "#ffffff", resizeMode: "contain" },
  partialRow: { flexDirection: "row", alignItems: "center", backgroundColor: colors.bgSurface, borderRadius: 10, borderWidth: 1, borderColor: colors.border, padding: 14, marginTop: 20, gap: 12 },
  rowLabel: { color: colors.textPrimary, fontSize: 14, fontWeight: "600" },
  rowHint: { color: colors.textSecondary, fontSize: 11.5, marginTop: 3 },
  error: { color: colors.danger, fontSize: 13, marginTop: 14 },
  button: { backgroundColor: colors.accent, borderRadius: 8, padding: 16, alignItems: "center", marginTop: 22 },
  buttonText: { color: colors.accentTextOn, fontWeight: "700", fontSize: 15 },
});
