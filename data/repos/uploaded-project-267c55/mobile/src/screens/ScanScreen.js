import React, { useState } from "react";
import { View, Text, TouchableOpacity, StyleSheet, ActivityIndicator, Alert } from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import { resolveScannedCode, recordScan } from "../services/api";
import { colors } from "../theme";

// Mobile equivalent of the web app's browser-native BarcodeDetector
// scanning (see mobile/README.md's own "Not Yet Built" list, now
// closed) — expo-camera's built-in barcode scanning (CameraView +
// onBarcodeScanned) needs no separate scanning library, same
// "fewer native dependencies" reasoning as SignaturePad.js's
// WebView-canvas approach elsewhere in this app.
//
// barcodeTypes below matches the web app's BarcodeScannerModal.jsx
// format-for-format (qr_code, code_128, code_39, ean_13, upc_a) —
// previously this only listed "qr", so a package barcoded in any of
// the other four formats simply couldn't be read here even though
// the web scanner handles it fine. expo-camera's naming differs
// slightly from the web BarcodeDetector API's (no underscores), which
// is the only reason this list doesn't look identical to that one.
export default function ScanScreen({ navigation }) {
  const [permission, requestPermission] = useCameraPermissions();
  const [isProcessing, setIsProcessing] = useState(false);
  const [scannedOnce, setScannedOnce] = useState(false);

  async function handleBarcodeScanned({ data }) {
    // A CameraView keeps firing onBarcodeScanned for every frame that
    // still contains a recognized code — without this guard, a single
    // hold-the-phone-still scan would fire this handler dozens of
    // times and attempt dozens of duplicate scan submissions.
    if (scannedOnce || isProcessing) return;
    setScannedOnce(true);
    setIsProcessing(true);
    try {
      const delivery = await resolveScannedCode(data);
      try {
        await recordScan(delivery.id, inferScanType(delivery.status));
      } catch {
        // Recording the scan event is informational (a history/audit
        // trail) — a failure there should never block the agent from
        // actually reaching the delivery they just scanned.
      }
      navigation.replace("DeliveryDetail", { deliveryId: delivery.id });
    } catch (err) {
      Alert.alert("Couldn't resolve that code", err.message, [
        { text: "Try Again", onPress: () => setScannedOnce(false) },
      ]);
    } finally {
      setIsProcessing(false);
    }
  }

  function inferScanType(status) {
    if (status === "pending") return "pickup";
    if (status === "out_for_delivery") return "delivery";
    return "hub";
  }

  if (!permission) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  }

  if (!permission.granted) {
    return (
      <View style={styles.centered}>
        <Text style={styles.permissionText}>Camera access is needed to scan a package's QR code or barcode.</Text>
        <TouchableOpacity style={styles.button} onPress={requestPermission}>
          <Text style={styles.buttonText}>Grant Camera Access</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <CameraView
        style={StyleSheet.absoluteFillObject}
        barcodeScannerSettings={{ barcodeTypes: ["qr", "code128", "code39", "ean13", "upc_a"] }}
        onBarcodeScanned={handleBarcodeScanned}
      />
      <View style={styles.overlay}>
        <View style={styles.scanBox} />
        <Text style={styles.hint}>
          {isProcessing ? "Looking up delivery…" : "Point the camera at a package's QR code or barcode"}
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#000" },
  centered: { flex: 1, backgroundColor: colors.bgPage, justifyContent: "center", alignItems: "center", padding: 24 },
  permissionText: { color: colors.textSecondary, fontSize: 14, textAlign: "center", marginBottom: 20 },
  button: { backgroundColor: colors.accent, borderRadius: 8, paddingVertical: 12, paddingHorizontal: 24 },
  buttonText: { color: colors.accentTextOn, fontWeight: "700", fontSize: 14 },
  overlay: { flex: 1, justifyContent: "center", alignItems: "center" },
  scanBox: { width: 240, height: 240, borderWidth: 3, borderColor: colors.accent, borderRadius: 16, backgroundColor: "transparent" },
  hint: { color: "#ffffff", fontSize: 13, marginTop: 20, backgroundColor: "rgba(0,0,0,0.5)", paddingHorizontal: 14, paddingVertical: 8, borderRadius: 20 },
});
