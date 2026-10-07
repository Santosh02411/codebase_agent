import React, { useState } from "react";
import { View, TextInput, TouchableOpacity, Text, StyleSheet } from "react-native";
import { colors } from "../theme";

/**
 * Mobile counterpart to the web app's PasswordInput.jsx — a drop-in
 * replacement for a plain `secureTextEntry` TextInput that adds a
 * show/hide toggle inside the field. Purely visual state
 * (isVisible) — never touches the value itself, so it's safe
 * everywhere a bare password TextInput was used before
 * (LoginScreen.js, SignupScreen.js, ResetPasswordScreen.js).
 *
 * Uses a plain text "Show"/"Hide" label rather than an eye glyph: this
 * app has no icon library as a dependency (React Native has no
 * built-in inline-SVG the way a browser does, which is how the web
 * version draws its eye icon for free), and an emoji eye renders
 * inconsistently across Android/iOS fonts — a text label is
 * unambiguous everywhere and needs nothing new installed.
 *
 * Forwards every prop except `secureTextEntry` (which this always
 * controls itself) to the underlying TextInput — style, value,
 * onChangeText, placeholder, placeholderTextColor, autoFocus, etc.
 */
export default function PasswordInput({ style, ...inputProps }) {
  const [isVisible, setIsVisible] = useState(false);

  return (
    <View style={styles.wrap}>
      <TextInput
        {...inputProps}
        secureTextEntry={!isVisible}
        style={[style, styles.input]}
      />
      <TouchableOpacity
        style={styles.toggle}
        onPress={() => setIsVisible((v) => !v)}
        accessibilityRole="button"
        accessibilityLabel={isVisible ? "Hide password" : "Show password"}
      >
        <Text style={styles.toggleText}>{isVisible ? "Hide" : "Show"}</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { position: "relative", justifyContent: "center" },
  input: { paddingRight: 56 },
  toggle: { position: "absolute", right: 12, paddingVertical: 6, paddingHorizontal: 4 },
  toggleText: { color: colors.accent, fontSize: 12, fontWeight: "700" },
});
