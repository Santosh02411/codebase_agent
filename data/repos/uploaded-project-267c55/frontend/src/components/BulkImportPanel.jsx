import React, { useState, useRef, useEffect } from "react";
import { parseCSV } from "../services/csvParser";
import { bulkImportDeliveries, fetchAgentsList } from "../services/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";

const REQUIRED_COLUMNS = ["order_id", "agent_username"];
const EXAMPLE_CSV = `order_id,agent_username,notes,zone,expected_by
order-101,ravi_agent,Fragile,North,2026-08-01T18:00:00Z
order-102,priya_agent,,South,`;

/**
 * Lets a dispatcher upload a CSV of orders to create many deliveries at
 * once, instead of assigning one by one. Shows a preview before
 * submitting, and a clear per-row success/failure report afterward — a
 * bad row doesn't block the good ones (see backend bulk_import.py).
 *
 * Also fetches and displays the organization's actual registered agent
 * usernames, and cross-checks the CSV against them BEFORE submitting —
 * the single most common way this import "doesn't work" isn't a parsing
 * or backend bug, it's a CSV referencing agent_username values that
 * simply don't match anyone in the organization yet (e.g. a template/
 * example file with placeholder names). Catching that upfront, with the
 * real list right there to compare against, is much clearer than
 * submitting and getting back 100 identical-looking failure rows.
 */
export default function BulkImportPanel({ onImportComplete }) {
  const { token } = useAuth();
  const { showToast } = useToast();
  const [parsedRows, setParsedRows] = useState([]);
  const [parseError, setParseError] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [results, setResults] = useState(null);
  const [fileName, setFileName] = useState("");
  const [knownAgentUsernames, setKnownAgentUsernames] = useState([]);
  const fileInputRef = useRef(null);

  useEffect(() => {
    loadKnownAgents();
  }, []);

  async function loadKnownAgents() {
    try {
      const agents = await fetchAgentsList(token);
      setKnownAgentUsernames(agents.map((a) => a.username));
    } catch (err) {
      console.warn("Could not load agent list for CSV validation:", err.message);
    }
  }

  function handleFileSelect(e) {
    const file = e.target.files[0];
    if (!file) return;

    setFileName(file.name);
    setResults(null);
    setParseError(null);

    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const text = event.target.result;
        const rows = parseCSV(text);

        if (rows.length === 0) {
          setParseError("The file has no data rows (or couldn't be read as CSV).");
          setParsedRows([]);
          return;
        }

        const headerColumns = Object.keys(rows[0]);
        const missingColumns = REQUIRED_COLUMNS.filter((c) => !headerColumns.includes(c));
        if (missingColumns.length > 0) {
          setParseError(
            `Missing required column(s): ${missingColumns.join(", ")}. ` +
            `Expected at least: order_id, agent_username.`
          );
          setParsedRows([]);
          return;
        }

        setParsedRows(rows);
      } catch (err) {
        setParseError(`Could not parse this file as CSV: ${err.message}`);
        setParsedRows([]);
      }
    };
    reader.onerror = () => {
      setParseError("Could not read the selected file.");
    };
    reader.readAsText(file);
  }

  async function handleSubmit() {
    if (parsedRows.length === 0) return;

    setIsSubmitting(true);
    setResults(null);
    try {
      const rowsForApi = parsedRows.map((row) => ({
        order_id: row.order_id || "",
        agent_username: row.agent_username || "",
        notes: row.notes || null,
        zone: row.zone || null,
        expected_by: row.expected_by ? row.expected_by : null,
      }));

      const response = await bulkImportDeliveries(token, rowsForApi);
      setResults(response);

      if (response.success_count > 0) {
        showToast(
          `Imported ${response.success_count} deliver${response.success_count === 1 ? "y" : "ies"}` +
          (response.failure_count > 0 ? `, ${response.failure_count} failed.` : "."),
          response.failure_count > 0 ? "info" : "success"
        );
        onImportComplete();
      } else {
        showToast("No rows were imported — check the errors below.", "error");
      }
    } catch (err) {
      showToast(`Bulk import failed: ${err.message}`, "error");
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleReset() {
    setParsedRows([]);
    setParseError(null);
    setResults(null);
    setFileName("");
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  return (
    <div className="card" style={{ marginBottom: "24px" }}>
      <h3 style={{ marginBottom: "8px" }}>Bulk Import Deliveries (CSV)</h3>
      <p style={{ fontSize: "12.5px", color: "var(--text-secondary)", marginBottom: "12px" }}>
        Upload a CSV with columns: <code className="mono">order_id</code>,{" "}
        <code className="mono">agent_username</code> (required), plus optional{" "}
        <code className="mono">notes</code>, <code className="mono">zone</code>,{" "}
        <code className="mono">expected_by</code> (ISO datetime, e.g. 2026-08-01T18:00:00Z).
      </p>

      <div
        style={{
          fontSize: "12.5px",
          padding: "10px 12px",
          borderRadius: "var(--radius-sm)",
          backgroundColor: "var(--bg-input)",
          marginBottom: "12px",
        }}
      >
        <strong>agent_username must exactly match a real agent in your organization.</strong>{" "}
        {knownAgentUsernames.length > 0 ? (
          <>
            Your current agents:{" "}
            <span className="mono">{knownAgentUsernames.join(", ")}</span>
          </>
        ) : (
          <>No agents have joined your organization yet — have them sign up first.</>
        )}
      </div>

      <details style={{ marginBottom: "12px" }}>
        <summary style={{ cursor: "pointer", fontSize: "12.5px", color: "var(--accent)" }}>
          Show example CSV format
        </summary>
        <pre className="mono" style={{
          fontSize: "12px",
          backgroundColor: "var(--bg-input)",
          padding: "10px",
          borderRadius: "var(--radius-sm)",
          marginTop: "8px",
          overflowX: "auto",
        }}>
          {EXAMPLE_CSV}
        </pre>
      </details>

      <div style={{ display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap" }}>
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv,text/csv"
          onChange={handleFileSelect}
          className="input"
        />
        {fileName && (
          <button className="btn" onClick={handleReset}>Clear</button>
        )}
      </div>

      {parseError && (
        <p style={{ color: "var(--danger)", fontSize: "13px", marginTop: "10px" }}>{parseError}</p>
      )}

      {parsedRows.length > 0 && !results && (
        <div style={{ marginTop: "14px" }}>
          <p style={{ fontSize: "13px", color: "var(--text-secondary)" }}>
            Found {parsedRows.length} row{parsedRows.length === 1 ? "" : "s"}. Preview (first 5):
          </p>

          {(() => {
            const csvUsernames = [...new Set(parsedRows.map((r) => r.agent_username).filter(Boolean))];
            const unknownUsernames = csvUsernames.filter((u) => !knownAgentUsernames.includes(u));
            if (unknownUsernames.length === 0) return null;
            return (
              <div
                style={{
                  fontSize: "12.5px",
                  padding: "10px 12px",
                  borderRadius: "var(--radius-sm)",
                  backgroundColor: "rgba(239, 83, 80, 0.12)",
                  border: "1px solid var(--danger)",
                  marginTop: "10px",
                  marginBottom: "10px",
                }}
              >
                <strong>Warning:</strong> this file references agent username(s) not
                found in your organization: <span className="mono">{unknownUsernames.join(", ")}</span>.
                Rows using these will fail on import (agent must sign up and join
                first). You can still import — rows with a valid agent will succeed
                regardless.
              </div>
            );
          })()}

          <div style={{ overflowX: "auto" }}>
            <table className="data-table" style={{ marginTop: "8px" }}>
              <thead>
                <tr>
                  {Object.keys(parsedRows[0]).map((col) => (
                    <th key={col}>{col}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {parsedRows.slice(0, 5).map((row, i) => (
                  <tr key={i}>
                    {Object.keys(parsedRows[0]).map((col) => (
                      <td key={col} className="mono">{row[col] || "—"}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <button
            className="btn btn-primary"
            onClick={handleSubmit}
            disabled={isSubmitting}
            style={{ marginTop: "12px" }}
          >
            {isSubmitting ? "Importing..." : `Import ${parsedRows.length} Deliveries`}
          </button>
        </div>
      )}

      {results && (
        <div style={{ marginTop: "16px" }}>
          <p style={{ fontSize: "13.5px", fontWeight: 600 }}>
            {results.success_count} succeeded, {results.failure_count} failed
          </p>

          {(() => {
            if (results.failure_count === 0) return null;
            const errorCounts = {};
            results.results
              .filter((r) => !r.success)
              .forEach((r) => {
                errorCounts[r.error] = (errorCounts[r.error] || 0) + 1;
              });
            return (
              <div style={{ marginTop: "8px", marginBottom: "8px" }}>
                {Object.entries(errorCounts).map(([error, count]) => (
                  <div key={error} style={{ fontSize: "12.5px", color: "var(--danger)" }}>
                    {count}× — {error}
                  </div>
                ))}
              </div>
            );
          })()}

          <details>
            <summary style={{ cursor: "pointer", fontSize: "12.5px", color: "var(--accent)" }}>
              Show per-row detail ({results.results.length} rows)
            </summary>
            <div style={{ maxHeight: "220px", overflowY: "auto", marginTop: "8px" }}>
              {results.results.map((r) => (
                <div
                  key={r.row_number}
                  style={{
                    fontSize: "12.5px",
                    padding: "6px 0",
                    borderBottom: "1px solid var(--border-color)",
                    color: r.success ? "var(--status-delivered)" : "var(--danger)",
                  }}
                >
                  Row {r.row_number} ({r.order_id || "—"}): {r.success ? "Imported" : r.error}
                </div>
              ))}
            </div>
          </details>

          <button className="btn" onClick={handleReset} style={{ marginTop: "12px" }}>
            Import Another File
          </button>
        </div>
      )}
    </div>
  );
}
