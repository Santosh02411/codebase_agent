import React from "react";
import { useConnectivity } from "../hooks/useConnectivity";

export default function ConnectivityBanner() {
  const isOnline = useConnectivity();

  return (
    <div className={`connectivity-banner ${isOnline ? "online" : "offline"}`}>
      {isOnline ? "Online — changes will sync automatically" : "Offline — changes are being saved locally"}
    </div>
  );
}
