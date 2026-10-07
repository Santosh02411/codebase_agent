import React, { useEffect, useState } from "react";
import { fetchMyFinancialDocuments, downloadFinancialDocumentPdf } from "../services/api";
import { useCustomerAuth } from "../context/CustomerAuthContext";

const TYPE_LABELS = {
  invoice: "Invoice", receipt: "Receipt", refund_receipt: "Refund Receipt",
  credit_note: "Credit Note", debit_note: "Debit Note",
};

/** Customer-facing invoice/credit-note history (Phase 13). */
export default function CustomerInvoicesPanel() {
  const { token } = useCustomerAuth();
  const [documents, setDocuments] = useState([]);
  const [error, setError] = useState(null);
  const [downloadingId, setDownloadingId] = useState(null);

  useEffect(() => { load(); }, []);

  async function load() {
    try {
      setDocuments(await fetchMyFinancialDocuments(token));
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleDownload(docId) {
    setDownloadingId(docId);
    try {
      await downloadFinancialDocumentPdf(token, docId, true);
    } catch (err) {
      setError(err.message);
    } finally {
      setDownloadingId(null);
    }
  }

  return (
    <div>
      <h2 className="page-title">Invoices & Receipts</h2>
      {error && <div className="alert alert-error" style={{ marginBottom: "12px" }}>{error}</div>}
      <div className="card" style={{ padding: 0, overflowX: "auto" }}>
        <table className="data-table">
          <thead><tr><th>Document</th><th>Type</th><th>Amount</th><th>Date</th><th></th></tr></thead>
          <tbody>
            {documents.length === 0 && <tr><td colSpan={5} style={{ color: "var(--text-muted)" }}>No invoices or receipts yet.</td></tr>}
            {documents.map((d) => (
              <tr key={d.id}>
                <td className="mono">{d.document_number}</td>
                <td>{TYPE_LABELS[d.document_type] || d.document_type}</td>
                <td>₹{d.amount.toFixed(2)}</td>
                <td>{new Date(d.created_at).toLocaleDateString()}</td>
                <td>
                  <button className="btn-info-outline" disabled={downloadingId === d.id} onClick={() => handleDownload(d.id)}>
                    {downloadingId === d.id ? "Downloading..." : "Download PDF"}
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
