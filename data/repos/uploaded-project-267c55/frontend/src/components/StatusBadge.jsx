import React from "react";

const STATUS_LABELS = {
  picked_up: "Picked Up",
  out_for_delivery: "Out for Delivery",
  delivered: "Delivered",
  failed_attempt: "Failed Attempt",
  cancelled: "Cancelled",
  pending: "Pending",
};

export default function StatusBadge({ status }) {
  return (
    <span className={`status-badge ${status}`}>
      {STATUS_LABELS[status] || status}
    </span>
  );
}
