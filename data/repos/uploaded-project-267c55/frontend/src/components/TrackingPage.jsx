import React, { useEffect, useState } from "react";
import { fetchPublicTracking, submitDeliveryFeedback } from "../services/api";
import { useTheme } from "../context/ThemeContext";
import StatusBadge from "./StatusBadge";
import LiveTrackingMap from "./LiveTrackingMap";

const STATUS_LABELS = {
  confirmed: "Order Confirmed",
  picked_up: "Picked Up",
  out_for_delivery: "Out for Delivery",
  delivered: "Delivered",
  failed_attempt: "Delivery Attempt Failed",
};

export default function TrackingPage({ deliveryId }) {
  const { theme, toggleTheme } = useTheme();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");
  const [isSubmittingFeedback, setIsSubmittingFeedback] = useState(false);
  const [feedbackError, setFeedbackError] = useState(null);

  useEffect(() => {
    loadTracking();
  }, [deliveryId]);

  function loadTracking() {
    fetchPublicTracking(deliveryId)
      .then(setData)
      .catch((err) => setError(err.message));
  }

  async function handleSubmitFeedback(e) {
    e.preventDefault();
    if (rating === 0) {
      setFeedbackError("Please pick a star rating.");
      return;
    }
    setFeedbackError(null);
    setIsSubmittingFeedback(true);
    try {
      await submitDeliveryFeedback(deliveryId, rating, comment.trim());
      await loadTracking();
    } catch (err) {
      setFeedbackError(err.message);
    } finally {
      setIsSubmittingFeedback(false);
    }
  }

  return (
    <div style={{ minHeight: "100vh", backgroundColor: "var(--bg-page)", padding: "24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", maxWidth: "480px", margin: "0 auto 20px" }}>
        <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, color: "var(--accent)" }}>
          Delivery Sync — Tracking
        </span>
        <button className="btn" onClick={toggleTheme}>
          {theme === "dark" ? "☀" : "☾"}
        </button>
      </div>

      <div className="card" style={{ maxWidth: "480px", margin: "0 auto", animation: "fadeSlideUp 0.35s ease" }}>
        {error && <p style={{ color: "var(--danger)" }}>{error}</p>}

        {!error && !data && <p style={{ color: "var(--text-secondary)" }}>Loading...</p>}

        {data && (
          <>
            <h2 className="mono" style={{ marginBottom: "8px" }}>{data.order_id}</h2>
            <StatusBadge status={data.status} />

            {(data.sla_status === "at_risk" || data.sla_status === "breached" || data.sla_status === "missed") && (
              <div style={{ marginTop: "10px", fontSize: "13px", color: "var(--warning, #b45309)", fontWeight: 600 }}>
                This delivery is running a bit behind schedule.
              </div>
            )}

            {(data.status === "picked_up" || data.status === "out_for_delivery") && (
              <div style={{ marginTop: "14px" }}>
                <LiveTrackingMap deliveryId={deliveryId} />
              </div>
            )}

            <div style={{ marginTop: "16px", display: "flex", flexDirection: "column", gap: "8px" }}>
              {data.zone && (
                <div style={{ fontSize: "13px", color: "var(--text-secondary)" }}>Zone: {data.zone}</div>
              )}
              {data.expected_by && (
                <div style={{ fontSize: "13px", color: "var(--text-secondary)" }}>
                  Expected by: {new Date(data.expected_by).toLocaleString()}
                </div>
              )}
              <div style={{ fontSize: "13px", color: "var(--text-secondary)" }}>
                Last updated: {new Date(data.updated_at).toLocaleString()}
              </div>
            </div>

            {data.proof_of_delivery && (
              <div style={{ marginTop: "16px" }}>
                <div style={{ fontSize: "12px", color: "var(--text-secondary)", marginBottom: "6px" }}>
                  Proof of Delivery
                </div>
                <img
                  src={data.proof_of_delivery}
                  alt="Proof of delivery"
                  style={{ maxWidth: "100%", borderRadius: "var(--radius-sm)", border: "1px solid var(--border-color)" }}
                />
              </div>
            )}

            <hr style={{ margin: "20px 0", border: "none", borderTop: "1px solid var(--border-color)" }} />

            <div style={{ fontSize: "13px", fontWeight: 600, marginBottom: "10px" }}>Order Timeline</div>
            {data.history.length === 0 && (
              <p style={{ fontSize: "12.5px", color: "var(--text-muted)" }}>No updates yet.</p>
            )}
            {data.history.map((entry, i) => (
              <div
                key={i}
                className="timeline-entry"
                style={{ borderLeft: "3px solid var(--accent)", paddingLeft: "10px", marginBottom: "10px", animationDelay: `${i * 0.05}s` }}
              >
                <div style={{ fontSize: "13px", fontWeight: 600 }}>
                  {entry.old_status
                    ? `${STATUS_LABELS[entry.old_status] || entry.old_status} → ${STATUS_LABELS[entry.new_status] || entry.new_status}`
                    : `Order Confirmed`}
                </div>
                <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>
                  {new Date(entry.changed_at).toLocaleString()}
                </div>
              </div>
            ))}

            {data.status === "delivered" && (
              <>
                <hr style={{ margin: "20px 0", border: "none", borderTop: "1px solid var(--border-color)" }} />
                <div style={{ fontSize: "13px", fontWeight: 600, marginBottom: "10px" }}>
                  How was your delivery?
                </div>

                {data.feedback ? (
                  <div>
                    <div style={{ fontSize: "20px", letterSpacing: "2px" }}>
                      {"★".repeat(data.feedback.rating)}
                      <span style={{ color: "var(--text-muted)" }}>
                        {"★".repeat(5 - data.feedback.rating)}
                      </span>
                    </div>
                    {data.feedback.comment && (
                      <p style={{ fontSize: "13px", color: "var(--text-secondary)", marginTop: "6px" }}>
                        "{data.feedback.comment}"
                      </p>
                    )}
                    <p style={{ fontSize: "11.5px", color: "var(--text-muted)", marginTop: "6px" }}>
                      Thanks for your feedback!
                    </p>
                  </div>
                ) : (
                  <form onSubmit={handleSubmitFeedback}>
                    <div style={{ fontSize: "26px", marginBottom: "10px" }}>
                      {[1, 2, 3, 4, 5].map((star) => (
                        <span
                          key={star}
                          onClick={() => setRating(star)}
                          style={{
                            cursor: "pointer",
                            color: star <= rating ? "var(--accent)" : "var(--text-muted)",
                          }}
                        >
                          ★
                        </span>
                      ))}
                    </div>
                    <textarea
                      className="input"
                      placeholder="Optional comment..."
                      value={comment}
                      onChange={(e) => setComment(e.target.value)}
                      style={{ width: "100%", minHeight: "60px", marginBottom: "10px" }}
                    />
                    {feedbackError && (
                      <p style={{ color: "var(--danger)", fontSize: "12.5px" }}>{feedbackError}</p>
                    )}
                    <button type="submit" className="btn btn-primary" disabled={isSubmittingFeedback}>
                      {isSubmittingFeedback ? "Submitting..." : "Submit Feedback"}
                    </button>
                  </form>
                )}
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
