/**
 * Same palette as frontend/src/styles/theme.css's dark mode — kept in
 * sync by hand (React Native has no CSS custom properties to literally
 * share), so the mobile app doesn't look like a visually unrelated
 * product from the web console an agent's dispatcher uses.
 */
export const colors = {
  bgPage: "#0b0e14",
  bgSurface: "#141821",
  bgSurfaceElevated: "#1b212c",
  bgInput: "#0f1319",
  border: "#2a3140",
  borderLight: "#384056",
  textPrimary: "#e8eaed",
  textSecondary: "#8b93a3",
  textMuted: "#5a6272",
  accent: "#f2a93b",
  accentHover: "#d6941f",
  accentTextOn: "#14100a",
  statusPickedUp: "#4fa3f7",
  statusOutForDelivery: "#f2a93b",
  statusDelivered: "#3dd68c",
  statusFailed: "#ef5350",
  success: "#3dd68c",
  danger: "#ef5350",
  info: "#4fa3f7",
};

export const statusLabels = {
  pending: "Pending",
  picked_up: "Picked Up",
  out_for_delivery: "Out for Delivery",
  delivered: "Delivered",
  failed_attempt: "Failed Attempt",
  cancelled: "Cancelled",
};

export const statusColors = {
  pending: colors.textMuted,
  picked_up: colors.statusPickedUp,
  out_for_delivery: colors.statusOutForDelivery,
  delivered: colors.statusDelivered,
  failed_attempt: colors.statusFailed,
  cancelled: colors.textMuted,
};
