import React, { useEffect, useState } from "react";
import { fetchCodCollection, collectCod } from "../services/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";

/**
 * Shown on a delivery's detail view (Phase 5) — renders nothing if the
 * delivery isn't a COD order at all (fetchCodCollection returns null
 * for a 404/400, see services/api.js). Lets the assigned agent (or any
 * dispatcher/admin) record what was actually collected in cash against
 * the expected amount.
 */
export default function CodCollectionWidget({ deliveryId }) {
  const { token } = useAuth();
  const { showToast } = useToast();
  const [collection, setCollection] = useState(undefined); // undefined = loading, null = not a COD order
  const [amount, setAmount] = useState("");
  const [notes, setNotes] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    fetchCodCollection(token, deliveryId).then(setCollection).catch(() => setCollection(null));
  }, [deliveryId]);

  async function handleCollect(e) {
    e.preventDefault();
    if (!amount) return;
    setIsSaving(true);
    try {
      const result = await collectCod(token, deliveryId, Number(amount), notes || undefined);
      setCollection(result);
      showToast(result.status === "discrepancy" ? "Recorded — amount doesn't match expected." : "COD collected.", result.status === "discrepancy" ? "error" : "success");
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setIsSaving(false);
    }
  }

  if (collection === undefined || collection === null) return null;

  return (
    <div style={{ padding: "10px", background: "var(--bg-secondary, #f8fafc)", borderRadius: "var(--radius-sm)", marginBottom: "10px" }}>
      <div style={{ fontWeight: 600, fontSize: "13px", marginBottom: "6px" }}>Cash on Delivery</div>
      <div style={{ fontSize: "12.5px", color: "var(--text-secondary)", marginBottom: "8px" }}>
        Expected: ${collection.expected_amount.toFixed(2)}
        {collection.collected_amount != null && ` — Collected: $${collection.collected_amount.toFixed(2)}`}
        {" — "}
        <span style={{ fontWeight: 600, color: collection.status === "discrepancy" ? "var(--warning, #b45309)" : collection.status === "collected" ? "var(--success, #16a34a)" : "inherit", textTransform: "capitalize" }}>
          {collection.status}
        </span>
      </div>
      {collection.status === "pending" && (
        <form onSubmit={handleCollect} style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
          <input type="number" step="0.01" className="input" style={{ width: "110px" }} placeholder="Amount collected" value={amount} onChange={(e) => setAmount(e.target.value)} required />
          <input className="input" style={{ width: "160px" }} placeholder="Notes (optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
          <button type="submit" className="btn btn-primary" disabled={isSaving}>{isSaving ? "Saving..." : "Record Collection"}</button>
        </form>
      )}
    </div>
  );
}
