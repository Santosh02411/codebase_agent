import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const resetPasswordRequest = vi.fn();
const customerResetPasswordRequest = vi.fn();

vi.mock("../../services/authApi", () => ({
  resetPasswordRequest: (...args) => resetPasswordRequest(...args),
  customerResetPasswordRequest: (...args) => customerResetPasswordRequest(...args),
}));
vi.mock("../../context/ThemeContext", () => ({
  useTheme: () => ({ theme: "dark", toggleTheme: vi.fn() }),
}));

import ResetPasswordPage from "../ResetPasswordPage";

/**
 * Regression coverage for the same "bare <label>, no htmlFor/id" bug
 * class LoginPage.test.jsx's getByLabelText calls already guard
 * against (see FEATURE_LOG.md's session #46 entry) — this page's two
 * password fields had that exact bug until now.
 */
describe("ResetPasswordPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("exposes both password fields to assistive tech via properly associated labels", async () => {
    const user = userEvent.setup();
    resetPasswordRequest.mockResolvedValue({ message: "Your password has been reset." });
    render(<ResetPasswordPage token="reset-token-123" onDone={() => {}} accountType="staff" />);

    // getByLabelText throws if a <label> isn't wired to its input via
    // htmlFor/id — these two lines ARE the regression guard. Anchored
    // regexes distinguish "New Password" from "Confirm New Password".
    await user.type(screen.getByLabelText(/^new password$/i), "newSecurePw1");
    await user.type(screen.getByLabelText(/^confirm new password$/i), "newSecurePw1");
    await user.click(screen.getByRole("button", { name: /reset password/i }));

    expect(resetPasswordRequest).toHaveBeenCalledWith("reset-token-123", "newSecurePw1");
    expect(await screen.findByText(/password has been reset/i)).toBeInTheDocument();
  });

  it("shows a mismatch error and never calls the backend when the two fields differ", async () => {
    const user = userEvent.setup();
    render(<ResetPasswordPage token="reset-token-123" onDone={() => {}} />);

    await user.type(screen.getByLabelText(/^new password$/i), "passwordOne");
    await user.type(screen.getByLabelText(/^confirm new password$/i), "passwordTwo");
    await user.click(screen.getByRole("button", { name: /reset password/i }));

    expect(await screen.findByText(/don't match/i)).toBeInTheDocument();
    expect(resetPasswordRequest).not.toHaveBeenCalled();
  });

  it("routes a customer account's reset through the customer endpoint", async () => {
    const user = userEvent.setup();
    customerResetPasswordRequest.mockResolvedValue({ message: "Your password has been reset." });
    render(<ResetPasswordPage token="cust-token-456" onDone={() => {}} accountType="customer" />);

    await user.type(screen.getByLabelText(/^new password$/i), "newSecurePw1");
    await user.type(screen.getByLabelText(/^confirm new password$/i), "newSecurePw1");
    await user.click(screen.getByRole("button", { name: /reset password/i }));

    expect(customerResetPasswordRequest).toHaveBeenCalledWith("cust-token-456", "newSecurePw1");
    expect(resetPasswordRequest).not.toHaveBeenCalled();
  });

  it("only offers the mobile-app deep link to staff accounts, not customers", () => {
    render(<ResetPasswordPage token="reset-token-123" onDone={() => {}} accountType="staff" />);
    expect(screen.getByText(/open in the delivery sync app/i)).toBeInTheDocument();
  });

  it("does not show the mobile-app deep link for a customer reset", () => {
    render(<ResetPasswordPage token="cust-token-456" onDone={() => {}} accountType="customer" />);
    expect(screen.queryByText(/open in the delivery sync app/i)).not.toBeInTheDocument();
  });
});
