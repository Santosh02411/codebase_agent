import React from "react";
import { NavigationContainer, DefaultTheme } from "@react-navigation/native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import { TouchableOpacity, Text, View } from "react-native";
import DeliveryListScreen from "./screens/DeliveryListScreen";
import DeliveryDetailScreen from "./screens/DeliveryDetailScreen";
import SettingsScreen from "./screens/SettingsScreen";
import ProofOfDeliveryScreen from "./screens/ProofOfDeliveryScreen";
import FailedAttemptScreen from "./screens/FailedAttemptScreen";
import ScanScreen from "./screens/ScanScreen";
import MessagesScreen from "./screens/MessagesScreen";
import { colors } from "./theme";

const Stack = createNativeStackNavigator();

const navTheme = {
  ...DefaultTheme,
  dark: true,
  colors: {
    ...DefaultTheme.colors,
    background: colors.bgPage,
    card: colors.bgSurface,
    text: colors.textPrimary,
    border: colors.border,
    primary: colors.accent,
  },
};

export default function AppNavigator() {
  return (
    <NavigationContainer theme={navTheme}>
      <Stack.Navigator
        screenOptions={{
          headerStyle: { backgroundColor: colors.bgSurface },
          headerTintColor: colors.textPrimary,
          headerTitleStyle: { fontWeight: "700" },
        }}
      >
        <Stack.Screen
          name="DeliveryList"
          component={DeliveryListScreen}
          options={({ navigation }) => ({
            title: "My Deliveries",
            headerRight: () => (
              <View style={{ flexDirection: "row", gap: 16, alignItems: "center" }}>
                <TouchableOpacity onPress={() => navigation.navigate("Scan")}>
                  <Text style={{ color: colors.accent, fontWeight: "600" }}>📷 Scan</Text>
                </TouchableOpacity>
                <TouchableOpacity onPress={() => navigation.navigate("Settings")}>
                  <Text style={{ color: colors.accent, fontWeight: "600" }}>Settings</Text>
                </TouchableOpacity>
              </View>
            ),
          })}
        />
        <Stack.Screen name="DeliveryDetail" component={DeliveryDetailScreen} options={{ title: "Delivery" }} />
        <Stack.Screen name="Settings" component={SettingsScreen} options={{ title: "Settings" }} />
        <Stack.Screen name="ProofOfDelivery" component={ProofOfDeliveryScreen} options={{ title: "Proof of Delivery" }} />
        <Stack.Screen name="FailedAttempt" component={FailedAttemptScreen} options={{ title: "Failed Attempt" }} />
        <Stack.Screen name="Scan" component={ScanScreen} options={{ title: "Scan Package" }} />
        <Stack.Screen name="Messages" component={MessagesScreen} options={{ title: "Messages" }} />
      </Stack.Navigator>
    </NavigationContainer>
  );
}

