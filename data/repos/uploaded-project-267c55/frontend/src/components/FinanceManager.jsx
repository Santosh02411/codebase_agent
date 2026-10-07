import React, { useEffect, useState } from "react";
import {
  fetchFinancialDocuments, createCreditNote, createDebitNote, fetchFinancialReport, downloadFinancialDocumentPdf,
} from "../services/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";

const TYPE_LABELS = {
  invoice: "Invoice", receipt: "Receipt", refund_receipt: "Refund Receipt",
  credit_note: "Credit Note", debit_note: "Debit Note",
};

/** Staff-facing invoicing & finance (Phase 13): dispatcher/admin only. */
export default function FinanceManager() {
  const { token } = useAuth();
  const { showToast } = useToast();

  const [documents, setDocuments] = useState([]);
  const [typeFilter, setTypeFilter] = useState("");
  const [report, setReport] = useState(null);
  const [downloadingId, setDownloadingId] = useState(null);

  const [creditForm, setCreditForm] = useState({ order_id: "", amount: "", reason: "" });
  const [debitForm, setDebitForm] = useState({ order_id: "", amount: "", reason: "" });

  useEffect(() => { loadDocuments(); loadReport(); }, [typeFilter]);

  async function loadDocuments() {
    try {
      setDocuments(await fetchFinancialDocuments(token, { document_type: typeFilter }));
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function loadReport() {
    try {
      setReport(await fetchFinancialReport(token));
    } catch (err) {}
  }

  async function handleDownload(docId) {
    setDownloadingId(docId);
    try {
      await downloadFinancialDocumentPdf(token, docId, false);
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setDownloadingId(null);
    }
  }

  async function handleCreateCredit(e) {
    e.preventDefault();
    try {
      await createCreditNote(token, { ...creditForm, amount: parseFloat(creditForm.amount) });
      showToast("Credit note issued.", "success");
      setCreditForm({ order_id: "", amount: "", reason: "" });
      await loadDocuments();
      await loadReport();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleCreateDebit(e) {
    e.preventDefault();
    try {
      const payload = { amount: parseFloat(debitForm.amount), reason: debitForm.reason };
      if (debitForm.order_id) payload.order_id = debitForm.order_id;
      await createDebitNote(token, payload);
      showToast("Debit note issued.", "success");
      setDebitForm({ order_id: "", amount: "", reason: "" });
      await loadDocuments();
      await loadReport();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  return (
    <div>
      <h2 className="page-title">Invoicing & Finance</h2>

      {report && (
        <div className="card" style={{ marginBottom: "20px", display: "flex", flexWrap: "wrap", gap: "24px" }}>
          <div><strong>₹{report.total_invoiced}</strong><div style={{ fontSize: "12px", color: "var(--text-muted)" }}>Total Invoiced</div></div>
          <div><strong>₹{report.total_credited}</strong><div style={{ fontSize: "12px", color: "var(--text-muted)" }}>Total Credited</div></div>
          <div><strong>₹{report.total_debited}</strong><div style={{ fontSize: "12px", color: "var(--text-muted)" }}>Total Debited</div></div>
          <div><strong>{report.document_counts.invoice}</strong><div style={{ fontSize: "12px", color: "var(--text-muted)" }}>Invoices Issued</div></div>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "20px" }}>
        <form onSubmit={handleCreateCredit} className="card">
          <strong style={{ display: "block", marginBottom: "8px" }}>Issue Credit Note</strong>
          <input className="input" placeholder="Order ID" required style={{ marginBottom: "8px", width: "100%" }} value={creditForm.order_id} onChange={(e) => setCreditForm({ ...creditForm, order_id: e.target.value })} />
          <input type="number" min={0.01} step="0.01" className="input" placeholder="Amount" required style={{ marginBottom: "8px", width: "100%" }} value={creditForm.amount} onChange={(e) => setCreditForm({ ...creditForm, amount: e.target.value })} />
          <input className="input" placeholder="Reason" required style={{ marginBottom: "8px", width: "100%" }} value={creditForm.reason} onChange={(e) => setCreditForm({ ...creditForm, reason: e.target.value })} />
          <button type="submit" className="btn btn-primary">Issue</button>
        </form>

        <form onSubmit={handleCreateDebit} className="card">
          <strong style={{ display: "block", marginBottom: "8px" }}>Issue Debit Note</strong>
          <input className="input" placeholder="Order ID (optional)" style={{ marginBottom: "8px", width: "100%" }} value={debitForm.order_id} onChange={(e) => setDebitForm({ ...debitForm, order_id: e.target.value })} />
          <input type="number" min={0.01} step="0.01" className="input" placeholder="Amount" required style={{ marginBottom: "8px", width: "100%" }} value={debitForm.amount} onChange={(e) => setDebitForm({ ...debitForm, amount: e.target.value })} />
          <input className="input" placeholder="Reason" required style={{ marginBottom: "8px", width: "100%" }} value={debitForm.reason} onChange={(e) => setDebitForm({ ...debitForm, reason: e.target.value })} />
          <button type="submit" className="btn btn-primary">Issue</button>
        </form>
      </div>

      <div style={{ marginBottom: "12px" }}>
        <select className="input" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
          <option value="">All document types</option>
          {Object.keys(TYPE_LABELS).map((t) => <option key={t} value={t}>{TYPE_LABELS[t]}</option>)}
        </select>
      </div>

      <div className="card" style={{ padding: 0, overflowX: "auto" }}>
        <table className="data-table">
          <thead><tr><th>Document</th><th>Type</th><th>Order</th><th>Amount</th><th>Reason</th><th>Date</th><th></th></tr></thead>
          <tbody>
            {documents.length === 0 && <tr><td colSpan={7} style={{ color: "var(--text-muted)" }}>No documents.</td></tr>}
            {documents.map((d) => (
              <tr key={d.id}>
                <td className="mono">{d.document_number}</td>
                <td>{TYPE_LABELS[d.document_type] || d.document_type}</td>
                <td className="mono">{d.order_id || "—"}</td>
                <td>₹{d.amount.toFixed(2)}</td>
                <td>{d.reason || "—"}</td>
                <td>{new Date(d.created_at).toLocaleDateString()}</td>
                <td>
                  <button className="btn-info-outline" disabled={downloadingId === d.id} onClick={() => handleDownload(d.id)}>
                    {downloadingId === d.id ? "..." : "PDF"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
