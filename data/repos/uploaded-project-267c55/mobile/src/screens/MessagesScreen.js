import React, { useCallback, useRef, useState } from "react";
import { View, Text, TextInput, TouchableOpacity, StyleSheet, FlatList, KeyboardAvoidingView, Platform, ActivityIndicator, AppState } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { fetchDeliveryMessages, sendDeliveryMessage, getAccessToken } from "../services/api";
import { connectWebSocket } from "../services/websocket";
import { useAuth } from "../context/AuthContext";
import { colors } from "../theme";

/**
 * Real-time, via the backend's existing `/ws/deliveries/{id}/messages`
 * socket — the same `chat_room` channel the web app already connects
 * to (see backend/app/routes/websockets.py; no backend changes needed
 * here either). Ported the reconnect-with-backoff logic from the web
 * app's own frontend/src/services/websocket.js almost verbatim (see
 * ../services/websocket.js) rather than reinventing it, since React
 * Native's built-in `WebSocket` implements the same interface a
 * browser's does.
 *
 * A one-time re-fetch on the app returning to the foreground (see the
 * AppState listener below) is kept as a safety net: a mobile OS can
 * suspend a background app's network activity far more aggressively
 * than a browser tab's, so a message sent by the other party while
 * this device was backgrounded might arrive right as the socket
 * reconnects, or might genuinely be missed by the live channel and
 * only show up on the next explicit fetch — the same "trust, but
 * verify on reconnect" pattern ../services/offlineSync.js already
 * uses for the offline queue.
 */
export default function MessagesScreen({ route }) {
  const { deliveryId, orderId } = route.params;
  const { user } = useAuth();
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [isLive, setIsLive] = useState(false);
  const [error, setError] = useState("");
  const listRef = useRef(null);
  const socketRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const data = await fetchDeliveryMessages(deliveryId);
      setMessages(data);
      setError("");
    } catch (err) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  }, [deliveryId]);

  function appendIfNew(message) {
    setMessages((prev) => (prev.some((m) => m.id === message.id) ? prev : [...prev, message]));
    setTimeout(() => listRef.current?.scrollToEnd({ animated: true }), 50);
  }

  useFocusEffect(
    useCallback(() => {
      let isActive = true;

      load();

      (async () => {
        const token = await getAccessToken();
        if (!isActive || !token) return;
        socketRef.current = connectWebSocket(`/ws/deliveries/${deliveryId}/messages?token=${token}`, {
          onOpen: () => setIsLive(true),
          onClose: () => setIsLive(false),
          onMessage: (data) => {
            if (data.event === "new_message" && data.message) {
              appendIfNew(data.message);
            }
          },
        });
      })();

      const appStateSubscription = AppState.addEventListener("change", (nextState) => {
        if (nextState === "active") load();
      });

      return () => {
        isActive = false;
        socketRef.current?.close();
        socketRef.current = null;
        appStateSubscription.remove();
      };
    }, [load, deliveryId])
  );

  async function handleSend() {
    const text = draft.trim();
    if (!text) return;
    setIsSending(true);
    setDraft("");
    try {
      const sent = await sendDeliveryMessage(deliveryId, text);
      // The socket will also receive this same message back as a
      // "new_message" broadcast (the backend broadcasts to the whole
      // room, including the sender's own connection) — appendIfNew's
      // id check is what keeps that from showing this message twice.
      appendIfNew(sent);
    } catch (err) {
      setError(err.message);
      setDraft(text); // give the agent their unsent text back to retry
    } finally {
      setIsSending(false);
    }
  }

  function renderItem({ item }) {
    const isMine = item.sender_id === user?.id;
    return (
      <View style={[styles.bubbleRow, isMine ? styles.bubbleRowMine : styles.bubbleRowTheirs]}>
        <View style={[styles.bubble, isMine ? styles.bubbleMine : styles.bubbleTheirs]}>
          {!isMine && <Text style={styles.senderName}>{item.sender_display_name} · {item.sender_role}</Text>}
          <Text style={isMine ? styles.messageTextMine : styles.messageText}>{item.message}</Text>
          <Text style={styles.timestamp}>{new Date(item.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</Text>
        </View>
      </View>
    );
  }

  return (
    <KeyboardAvoidingView style={styles.container} behavior={Platform.OS === "ios" ? "padding" : undefined} keyboardVerticalOffset={90}>
      <View style={styles.header}>
        <Text style={styles.headerText}>{orderId}</Text>
        <View style={styles.liveRow}>
          <View style={[styles.liveDot, { backgroundColor: isLive ? colors.success : colors.textMuted }]} />
          <Text style={styles.liveText}>{isLive ? "Live" : "Reconnecting…"}</Text>
        </View>
      </View>

      {isLoading ? (
        <ActivityIndicator color={colors.accent} style={{ marginTop: 40 }} />
      ) : (
        <FlatList
          ref={listRef}
          data={messages}
          keyExtractor={(item) => item.id}
          renderItem={renderItem}
          contentContainerStyle={{ padding: 16 }}
          onContentSizeChange={() => listRef.current?.scrollToEnd({ animated: false })}
          ListEmptyComponent={<Text style={styles.empty}>No messages yet — say hello.</Text>}
        />
      )}

      {error ? <Text style={styles.error}>{error}</Text> : null}

      <View style={styles.inputRow}>
        <TextInput
          style={styles.input}
          value={draft}
          onChangeText={setDraft}
          placeholder="Message dispatch…"
          placeholderTextColor={colors.textMuted}
          multiline
        />
        <TouchableOpacity style={styles.sendButton} onPress={handleSend} disabled={isSending || !draft.trim()}>
          <Text style={styles.sendButtonText}>Send</Text>
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bgPage },
  header: { padding: 14, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.bgSurface, flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  headerText: { color: colors.textSecondary, fontSize: 12, fontFamily: "monospace" },
  liveRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  liveDot: { width: 7, height: 7, borderRadius: 4 },
  liveText: { color: colors.textMuted, fontSize: 11, fontWeight: "600" },
  empty: { color: colors.textMuted, textAlign: "center", marginTop: 40, fontSize: 13 },
  bubbleRow: { marginBottom: 10, flexDirection: "row" },
  bubbleRowMine: { justifyContent: "flex-end" },
  bubbleRowTheirs: { justifyContent: "flex-start" },
  bubble: { maxWidth: "78%", borderRadius: 12, padding: 10 },
  bubbleMine: { backgroundColor: colors.accent, borderBottomRightRadius: 3 },
  bubbleTheirs: { backgroundColor: colors.bgSurface, borderWidth: 1, borderColor: colors.border, borderBottomLeftRadius: 3 },
  senderName: { color: colors.textMuted, fontSize: 10.5, marginBottom: 3, fontWeight: "600" },
  messageText: { color: colors.textPrimary, fontSize: 14 },
  messageTextMine: { color: colors.accentTextOn, fontSize: 14 },
  timestamp: { color: colors.textMuted, fontSize: 10, marginTop: 4, alignSelf: "flex-end" },
  error: { color: colors.danger, fontSize: 12, textAlign: "center", paddingBottom: 6 },
  inputRow: { flexDirection: "row", alignItems: "flex-end", padding: 12, gap: 8, borderTopWidth: 1, borderTopColor: colors.border, backgroundColor: colors.bgSurface },
  input: { flex: 1, backgroundColor: colors.bgInput, borderWidth: 1, borderColor: colors.border, borderRadius: 18, paddingHorizontal: 14, paddingVertical: 10, color: colors.textPrimary, fontSize: 14, maxHeight: 100 },
  sendButton: { backgroundColor: colors.accent, borderRadius: 18, paddingHorizontal: 18, paddingVertical: 10 },
  sendButtonText: { color: colors.accentTextOn, fontWeight: "700", fontSize: 13 },
});
