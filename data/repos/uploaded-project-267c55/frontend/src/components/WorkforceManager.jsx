import React, { useEffect, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { fetchAgentsList } from "../services/api";
import {
  createShift, fetchShifts, updateShift, deleteShift,
  fetchAttendance,
  fetchLeaveRequests, approveLeaveRequest, rejectLeaveRequest,
  setPayRate,
  generateEarnings, fetchEarnings, finalizeEarnings, markEarningsPaid,
} from "../services/api";

const TAB_LABELS = {
  roster: "Shift Roster",
  attendance: "Attendance Log",
  leave: "Leave Requests",
  earnings: "Earnings",
};

/**
 * Dispatcher/admin console for Group 3 (workforce management) — the
 * roster-side counterpart to MyWorkforce.jsx's self-service view.
 * Covers creating/editing shifts for staff, viewing the org attendance
 * log, reviewing leave requests, and generating/finalizing/paying
 * earnings statements. Pay-rate editing lives inline in the Earnings
 * tab since that's the only place rates are actually consumed.
 */
export default function WorkforceManager() {
  const { token, user } = useAuth();
  const { showToast } = useToast();
  const [tab, setTab] = useState("roster");
  const [staff, setStaff] = useState([]);

  useEffect(() => {
    fetchAgentsList(token).then(setStaff).catch(() => {});
  }, []);

  return (
    <div>
      <h2 className="page-title">Workforce</h2>

      <div style={{ display: "flex", gap: "8px", marginBottom: "20px", flexWrap: "wrap" }}>
        {Object.keys(TAB_LABELS).map((key) => (
          <button key={key} className={tab === key ? "btn btn-primary" : "btn"} onClick={() => setTab(key)}>
            {TAB_LABELS[key]}
          </button>
        ))}
      </div>

      {tab === "roster" && <ShiftRoster token={token} staff={staff} showToast={showToast} />}
      {tab === "attendance" && <AttendanceLog token={token} staff={staff} showToast={showToast} />}
      {tab === "leave" && <LeaveApprovals token={token} showToast={showToast} />}
      {tab === "earnings" && <EarningsPanel token={token} staff={staff} showToast={showToast} />}
    </div>
  );
}

function ShiftRoster({ token, staff, showToast }) {
  const [shifts, setShifts] = useState([]);
  const [userId, setUserId] = useState("");
  const [shiftDate, setShiftDate] = useState("");
  const [startTime, setStartTime] = useState("09:00");
  const [endTime, setEndTime] = useState("17:00");
  const [notes, setNotes] = useState("");
  const [isCreating, setIsCreating] = useState(false);

  useEffect(() => { load(); }, []);

  async function load() {
    try {
      setShifts(await fetchShifts(token));
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleCreate(e) {
    e.preventDefault();
    if (!userId) return;
    setIsCreating(true);
    try {
      await createShift(token, { user_id: userId, shift_date: shiftDate, start_time: `${startTime}:00`, end_time: `${endTime}:00`, notes: notes.trim() || null });
      showToast("Shift scheduled.", "success");
      setShiftDate(""); setNotes("");
      await load();
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setIsCreating(false);
    }
  }

  async function handleCancel(shiftId) {
    try {
      await updateShift(token, shiftId, { status: "cancelled" });
      await load();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleDelete(shiftId) {
    try {
      await deleteShift(token, shiftId);
      await load();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  const staffName = (id) => staff.find((s) => s.id === id)?.display_name || id;

  return (
    <div>
      <form onSubmit={handleCreate} className="card" style={{ marginBottom: "20px", display: "flex", gap: "10px", flexWrap: "wrap", alignItems: "flex-end" }}>
        <div>
          <label className="field-label" htmlFor="wfm-roster-staff">Staff Member</label>
          <select id="wfm-roster-staff" className="input" value={userId} onChange={(e) => setUserId(e.target.value)} required>
            <option value="">Select…</option>
            {staff.map((s) => <option key={s.id} value={s.id}>{s.display_name}</option>)}
          </select>
        </div>
        <div>
          <label className="field-label" htmlFor="wfm-roster-date">Date</label>
          <input id="wfm-roster-date" className="input" type="date" value={shiftDate} onChange={(e) => setShiftDate(e.target.value)} required />
        </div>
        <div>
          <label className="field-label" htmlFor="wfm-roster-start">Start</label>
          <input id="wfm-roster-start" className="input" type="time" value={startTime} onChange={(e) => setStartTime(e.target.value)} required />
        </div>
        <div>
          <label className="field-label" htmlFor="wfm-roster-end">End</label>
          <input id="wfm-roster-end" className="input" type="time" value={endTime} onChange={(e) => setEndTime(e.target.value)} required />
        </div>
        <div style={{ flexGrow: 1, minWidth: "150px" }}>
          <label className="field-label" htmlFor="wfm-roster-notes">Notes (optional)</label>
          <input id="wfm-roster-notes" className="input" type="text" value={notes} onChange={(e) => setNotes(e.target.value)} style={{ width: "100%" }} />
        </div>
        <button type="submit" className="btn btn-primary" disabled={isCreating || !userId || !shiftDate}>
          {isCreating ? "Scheduling..." : "Schedule Shift"}
        </button>
      </form>

      <div style={{ display: "grid", gap: "8px" }}>
        {shifts.length === 0 && <p style={{ color: "var(--text-secondary)" }}>No shifts scheduled yet.</p>}
        {shifts.map((s) => (
          <div key={s.id} className="card" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <strong>{staffName(s.user_id)}</strong> — {s.shift_date}, {s.start_time}–{s.end_time}
              <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>
                {s.status}{s.notes ? ` — ${s.notes}` : ""}
              </div>
            </div>
            {s.status === "scheduled" && (
              <div style={{ display: "flex", gap: "6px" }}>
                <button className="btn" onClick={() => handleCancel(s.id)}>Cancel</button>
                <button className="btn-danger-outline" onClick={() => handleDelete(s.id)}>Delete</button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function AttendanceLog({ token, staff, showToast }) {
  const [records, setRecords] = useState([]);
  const [userId, setUserId] = useState("");

  useEffect(() => { load(); }, [userId]);

  async function load() {
    try {
      setRecords(await fetchAttendance(token, { userId: userId || undefined }));
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  const staffName = (id) => staff.find((s) => s.id === id)?.display_name || id;

  return (
    <div>
      <div style={{ marginBottom: "16px" }}>
        <label className="field-label" htmlFor="wfm-attendance-staff">Filter by staff member</label>
        <select id="wfm-attendance-staff" className="input" value={userId} onChange={(e) => setUserId(e.target.value)} style={{ maxWidth: "260px" }}>
          <option value="">Everyone</option>
          {staff.map((s) => <option key={s.id} value={s.id}>{s.display_name}</option>)}
        </select>
      </div>
      <div style={{ display: "grid", gap: "8px" }}>
        {records.length === 0 && <p style={{ color: "var(--text-secondary)" }}>No attendance recorded yet.</p>}
        {records.map((r) => (
          <div key={r.id} className="card">
            <strong>{staffName(r.user_id)}</strong>
            <div style={{ fontSize: "13px" }}>
              {new Date(r.clock_in_at).toLocaleString()} &rarr;{" "}
              {r.clock_out_at ? new Date(r.clock_out_at).toLocaleString() : <em>still clocked in</em>}
            </div>
            {r.is_unscheduled && <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>Unscheduled session</div>}
          </div>
        ))}
      </div>
    </div>
  );
}

function LeaveApprovals({ token, showToast }) {
  const [requests, setRequests] = useState([]);
  const [statusFilter, setStatusFilter] = useState("pending");

  useEffect(() => { load(); }, [statusFilter]);

  async function load() {
    try {
      setRequests(await fetchLeaveRequests(token, { status: statusFilter || undefined }));
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleApprove(id) {
    try {
      await approveLeaveRequest(token, id, null);
      showToast("Leave approved.", "success");
      await load();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleReject(id) {
    try {
      await rejectLeaveRequest(token, id, null);
      showToast("Leave rejected.", "success");
      await load();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  return (
    <div>
      <div style={{ marginBottom: "16px" }}>
        <label className="field-label" htmlFor="wfm-leave-status">Status</label>
        <select id="wfm-leave-status" className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} style={{ maxWidth: "200px" }}>
          <option value="pending">Pending</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
          <option value="cancelled">Cancelled</option>
          <option value="">All</option>
        </select>
      </div>
      <div style={{ display: "grid", gap: "8px" }}>
        {requests.length === 0 && <p style={{ color: "var(--text-secondary)" }}>No leave requests.</p>}
        {requests.map((r) => (
          <div key={r.id} className="card" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <strong>{r.leave_type}</strong>: {r.start_date} &rarr; {r.end_date}
              {r.reason && <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>{r.reason}</div>}
              <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>Status: {r.status}</div>
            </div>
            {r.status === "pending" && (
              <div style={{ display: "flex", gap: "6px" }}>
                <button className="btn btn-primary" onClick={() => handleApprove(r.id)}>Approve</button>
                <button className="btn-danger-outline" onClick={() => handleReject(r.id)}>Reject</button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function EarningsPanel({ token, staff, showToast }) {
  const [statements, setStatements] = useState([]);
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [genUserId, setGenUserId] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [rateUserId, setRateUserId] = useState("");
  const [hourlyRate, setHourlyRate] = useState("");
  const [perDeliveryRate, setPerDeliveryRate] = useState("");

  useEffect(() => { load(); }, []);

  async function load() {
    try {
      setStatements(await fetchEarnings(token));
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleGenerate(e) {
    e.preventDefault();
    setIsGenerating(true);
    try {
      await generateEarnings(token, { userId: genUserId || undefined, periodStart, periodEnd });
      showToast("Earnings generated.", "success");
      await load();
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setIsGenerating(false);
    }
  }

  async function handleSetRate(e) {
    e.preventDefault();
    if (!rateUserId) return;
    try {
      await setPayRate(token, rateUserId, {
        hourly_rate: hourlyRate === "" ? null : parseFloat(hourlyRate),
        per_delivery_rate: perDeliveryRate === "" ? null : parseFloat(perDeliveryRate),
      });
      showToast("Pay rate updated.", "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleFinalize(id) {
    try {
      await finalizeEarnings(token, id);
      await load();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleMarkPaid(id) {
    try {
      await markEarningsPaid(token, id);
      showToast("Marked paid.", "success");
      await load();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  const staffName = (id) => staff.find((s) => s.id === id)?.display_name || id;

  return (
    <div>
      <div style={{ display: "flex", gap: "20px", flexWrap: "wrap", marginBottom: "20px" }}>
        <form onSubmit={handleSetRate} className="card" style={{ minWidth: "280px" }}>
          <h4 style={{ marginTop: 0 }}>Set Pay Rate</h4>
          <div className="auth-field">
            <label htmlFor="wfm-rate-staff">Staff Member</label>
            <select id="wfm-rate-staff" className="input" value={rateUserId} onChange={(e) => setRateUserId(e.target.value)} required>
              <option value="">Select…</option>
              {staff.map((s) => <option key={s.id} value={s.id}>{s.display_name}</option>)}
            </select>
          </div>
          <div className="auth-field">
            <label htmlFor="wfm-hourly-rate">Hourly Rate ($)</label>
            <input id="wfm-hourly-rate" className="input" type="number" step="0.01" value={hourlyRate} onChange={(e) => setHourlyRate(e.target.value)} placeholder="Leave blank to clear" />
          </div>
          <div className="auth-field">
            <label htmlFor="wfm-per-delivery-rate">Per-Delivery Rate ($)</label>
            <input id="wfm-per-delivery-rate" className="input" type="number" step="0.01" value={perDeliveryRate} onChange={(e) => setPerDeliveryRate(e.target.value)} placeholder="Leave blank to clear" />
          </div>
          <button type="submit" className="btn btn-primary" disabled={!rateUserId}>Save Rate</button>
        </form>

        <form onSubmit={handleGenerate} className="card" style={{ minWidth: "280px" }}>
          <h4 style={{ marginTop: 0 }}>Generate Earnings</h4>
          <div className="auth-field">
            <label htmlFor="wfm-gen-staff">Staff Member (blank = whole org)</label>
            <select id="wfm-gen-staff" className="input" value={genUserId} onChange={(e) => setGenUserId(e.target.value)}>
              <option value="">Everyone</option>
              {staff.map((s) => <option key={s.id} value={s.id}>{s.display_name}</option>)}
            </select>
          </div>
          <div className="auth-field">
            <label htmlFor="wfm-period-start">Period Start</label>
            <input id="wfm-period-start" className="input" type="date" value={periodStart} onChange={(e) => setPeriodStart(e.target.value)} required />
          </div>
          <div className="auth-field">
            <label htmlFor="wfm-period-end">Period End</label>
            <input id="wfm-period-end" className="input" type="date" value={periodEnd} onChange={(e) => setPeriodEnd(e.target.value)} required />
          </div>
          <button type="submit" className="btn btn-primary" disabled={isGenerating || !periodStart || !periodEnd}>
            {isGenerating ? "Generating..." : "Generate"}
          </button>
        </form>
      </div>

      <div style={{ display: "grid", gap: "8px" }}>
        {statements.length === 0 && <p style={{ color: "var(--text-secondary)" }}>No earnings statements yet.</p>}
        {statements.map((e) => (
          <div key={e.id} className="card" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <strong>{staffName(e.user_id)}</strong> — {e.period_start} &rarr; {e.period_end}
              <span style={{ marginLeft: "8px", fontSize: "12px", color: "var(--text-secondary)" }}>({e.status})</span>
              <div style={{ fontSize: "13px" }}>
                {e.hours_worked}h base ${e.base_pay.toFixed(2)} + {e.deliveries_completed} deliveries ${e.delivery_pay.toFixed(2)} = <strong>${e.total_pay.toFixed(2)}</strong>
              </div>
            </div>
            <div style={{ display: "flex", gap: "6px" }}>
              {e.status === "draft" && <button className="btn" onClick={() => handleFinalize(e.id)}>Finalize</button>}
              {e.status === "finalized" && <button className="btn btn-primary" onClick={() => handleMarkPaid(e.id)}>Mark Paid</button>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
