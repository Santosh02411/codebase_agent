import React from "react";

export default function SyncStatusBadge({ status }) {
  const isSynced = status === "synced";
  return (
    <span className={`sync-badge ${isSynced ? "synced" : "pending"}`}>
      {isSynced ? "Synced" : "Saved locally"}
    </span>
  );
}
