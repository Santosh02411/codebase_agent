import React, { useEffect, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import {
  clockIn, clockOut, fetchMyAttendance,
  fetchMyShifts,
  createLeaveRequest, fetchMyLeaveRequests, cancelLeaveRequest,
  fetchMyEarnings,
} from "../services/api";

const LEAVE_TYPES = [
  { value: "sick", label: "Sick" },
  { value: "vacation", label: "Vacation" },
  { value: "personal", label: "Personal" },
  { value: "unpaid", label: "Unpaid" },
];

const TAB_LABELS = {
  clock: "Clock In/Out",
  shifts: "My Shifts",
  leave: "Leave Requests",
  earnings: "My Earnings",
};

/**
 * Self-service workforce page for agents/dispatchers — clock in/out,
 * view assigned shifts, submit/track leave requests, and see computed
 * earnings statements. Roster management, leave approvals, and
 * earnings generation are admin/dispatcher-only and live in
 * WorkforceManager.jsx instead.
 */
export default function MyWorkforce() {
  const { token } = useAuth();
  const { showToast } = useToast();
  const [tab, setTab] = useState("clock");

  const [openSession, setOpenSession] = useState(null);
  const [attendance, setAttendance] = useState([]);
  const [isClockLoading, setIsClockLoading] = useState(false);

  const [shifts, setShifts] = useState([]);

  const [leaveRequests, setLeaveRequests] = useState([]);
  const [leaveType, setLeaveType] = useState("vacation");
  const [leaveStart, setLeaveStart] = useState("");
  const [leaveEnd, setLeaveEnd] = useState("");
  const [leaveReason, setLeaveReason] = useState("");
  const [isSubmittingLeave, setIsSubmittingLeave] = useState(false);

  const [earnings, setEarnings] = useState([]);

  useEffect(() => {
    loadAttendance();
    loadShifts();
    loadLeaveRequests();
    loadEarnings();
  }, []);

  async function loadAttendance() {
    try {
      const records = await fetchMyAttendance(token);
      setAttendance(records);
      setOpenSession(records.find((r) => !r.clock_out_at) || null);
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function loadShifts() {
    try {
      setShifts(await fetchMyShifts(token));
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function loadLeaveRequests() {
    try {
      setLeaveRequests(await fetchMyLeaveRequests(token));
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function loadEarnings() {
    try {
      setEarnings(await fetchMyEarnings(token));
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleClockIn() {
    setIsClockLoading(true);
    try {
      await clockIn(token, null, null);
      showToast("Clocked in.", "success");
      await loadAttendance();
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setIsClockLoading(false);
    }
  }

  async function handleClockOut() {
    setIsClockLoading(true);
    try {
      await clockOut(token, null);
      showToast("Clocked out.", "success");
      await loadAttendance();
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setIsClockLoading(false);
    }
  }

  async function handleClockInForShift(shiftId) {
    setIsClockLoading(true);
    try {
      await clockIn(token, shiftId, null);
      showToast("Clocked in for shift.", "success");
      await loadAttendance();
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setIsClockLoading(false);
    }
  }

  async function handleSubmitLeave(e) {
    e.preventDefault();
    setIsSubmittingLeave(true);
    try {
      await createLeaveRequest(token, {
        leave_type: leaveType,
        start_date: leaveStart,
        end_date: leaveEnd,
        reason: leaveReason.trim() || null,
      });
      showToast("Leave request submitted.", "success");
      setLeaveStart("");
      setLeaveEnd("");
      setLeaveReason("");
      await loadLeaveRequests();
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setIsSubmittingLeave(false);
    }
  }

  async function handleCancelLeave(id) {
    try {
      await cancelLeaveRequest(token, id);
      showToast("Leave request cancelled.", "success");
      await loadLeaveRequests();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  const totalEarned = earnings.reduce((sum, e) => sum + e.total_pay, 0);

  return (
    <div>
      <h2 className="page-title">My Workforce</h2>

      <div style={{ display: "flex", gap: "8px", marginBottom: "20px", flexWrap: "wrap" }}>
        {Object.keys(TAB_LABELS).map((key) => (
          <button
            key={key}
            className={tab === key ? "btn btn-primary" : "btn"}
            onClick={() => setTab(key)}
          >
            {TAB_LABELS[key]}
          </button>
        ))}
      </div>

      {tab === "clock" && (
        <div>
          <div className="card" style={{ maxWidth: "420px", marginBottom: "20px" }}>
            {openSession ? (
              <>
                <p style={{ fontSize: "14px" }}>
                  Clocked in at <strong>{new Date(openSession.clock_in_at).toLocaleString()}</strong>
                  {openSession.shift_id && " (against a scheduled shift)"}
                </p>
                <button className="btn btn-primary" onClick={handleClockOut} disabled={isClockLoading}>
                  {isClockLoading ? "..." : "Clock Out"}
                </button>
              </>
            ) : (
              <>
                <p style={{ fontSize: "14px", color: "var(--text-secondary)" }}>You're not clocked in.</p>
                <button className="btn btn-primary" onClick={handleClockIn} disabled={isClockLoading}>
                  {isClockLoading ? "..." : "Clock In"}
                </button>
              </>
            )}
          </div>

          <h4 style={{ marginBottom: "10px" }}>Recent Attendance</h4>
          {attendance.length === 0 && <p style={{ color: "var(--text-secondary)" }}>No attendance recorded yet.</p>}
          <div style={{ display: "grid", gap: "8px" }}>
            {attendance.map((a) => (
              <div key={a.id} className="card">
                <div style={{ fontSize: "13px" }}>
                  {new Date(a.clock_in_at).toLocaleString()} &rarr;{" "}
                  {a.clock_out_at ? new Date(a.clock_out_at).toLocaleString() : <em>still clocked in</em>}
                </div>
                {a.is_unscheduled && (
                  <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>Unscheduled session</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === "shifts" && (
        <div style={{ display: "grid", gap: "8px" }}>
          {shifts.length === 0 && <p style={{ color: "var(--text-secondary)" }}>No shifts scheduled.</p>}
          {shifts.map((s) => (
            <div key={s.id} className="card" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <strong>{s.shift_date}</strong> &nbsp; {s.start_time}–{s.end_time}
                <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>
                  {s.status}{s.notes ? ` — ${s.notes}` : ""}
                </div>
              </div>
              {s.status === "scheduled" && !openSession && (
                <button className="btn" onClick={() => handleClockInForShift(s.id)} disabled={isClockLoading}>
                  Clock In For This Shift
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {tab === "leave" && (
        <div>
          <form onSubmit={handleSubmitLeave} className="card" style={{ maxWidth: "480px", marginBottom: "20px" }}>
            <div className="auth-field">
              <label htmlFor="myworkforce-leave-type">Leave Type</label>
              <select id="myworkforce-leave-type" className="input" value={leaveType} onChange={(e) => setLeaveType(e.target.value)}>
                {LEAVE_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
            </div>
            <div className="auth-field">
              <label htmlFor="myworkforce-leave-start">Start Date</label>
              <input id="myworkforce-leave-start" className="input" type="date" value={leaveStart} onChange={(e) => setLeaveStart(e.target.value)} required />
            </div>
            <div className="auth-field">
              <label htmlFor="myworkforce-leave-end">End Date</label>
              <input id="myworkforce-leave-end" className="input" type="date" value={leaveEnd} onChange={(e) => setLeaveEnd(e.target.value)} required />
            </div>
            <div className="auth-field">
              <label htmlFor="myworkforce-leave-reason">Reason (optional)</label>
              <input id="myworkforce-leave-reason" className="input" type="text" value={leaveReason} onChange={(e) => setLeaveReason(e.target.value)} />
            </div>
            <button type="submit" className="btn btn-primary" disabled={isSubmittingLeave || !leaveStart || !leaveEnd}>
              {isSubmittingLeave ? "Submitting..." : "Submit Request"}
            </button>
          </form>

          <div style={{ display: "grid", gap: "8px" }}>
            {leaveRequests.map((r) => (
              <div key={r.id} className="card" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <strong>{r.leave_type}</strong>: {r.start_date} &rarr; {r.end_date}
                  <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>
                    Status: {r.status}
                    {r.review_note && ` — ${r.review_note}`}
                  </div>
                </div>
                {r.status === "pending" && (
                  <button className="btn" onClick={() => handleCancelLeave(r.id)}>Cancel</button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === "earnings" && (
        <div>
          <p style={{ fontSize: "14px", marginBottom: "12px" }}>
            Total across all statements: <strong>${totalEarned.toFixed(2)}</strong>
          </p>
          {earnings.length === 0 && <p style={{ color: "var(--text-secondary)" }}>No earnings statements yet.</p>}
          <div style={{ display: "grid", gap: "8px" }}>
            {earnings.map((e) => (
              <div key={e.id} className="card">
                <strong>{e.period_start} &rarr; {e.period_end}</strong>
                <span style={{ marginLeft: "8px", fontSize: "12px", color: "var(--text-secondary)" }}>({e.status})</span>
                <div style={{ fontSize: "13px", marginTop: "4px" }}>
                  {e.hours_worked}h {e.hourly_rate ? `@ $${e.hourly_rate}/hr = $${e.base_pay.toFixed(2)}` : ""}
                  {e.deliveries_completed > 0 && (
                    <> &nbsp;|&nbsp; {e.deliveries_completed} deliveries {e.per_delivery_rate ? `@ $${e.per_delivery_rate} = $${e.delivery_pay.toFixed(2)}` : ""}</>
                  )}
                </div>
                <div style={{ fontWeight: 600, marginTop: "4px" }}>Total: ${e.total_pay.toFixed(2)}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
