import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const forgotPasswordRequest = vi.fn();
const customerForgotPasswordRequest = vi.fn();

vi.mock("../../services/authApi", () => ({
  forgotPasswordRequest: (...args) => forgotPasswordRequest(...args),
  customerForgotPasswordRequest: (...args) => customerForgotPasswordRequest(...args),
}));
vi.mock("../../context/ThemeContext", () => ({
  useTheme: () => ({ theme: "dark", toggleTheme: vi.fn() }),
}));

import ForgotPasswordPage from "../ForgotPasswordPage";

/**
 * Regression coverage for the same bug class LoginPage.test.jsx's
 * getByLabelText calls already guard against (see PROJECT_WORKFLOW.md
 * / FEATURE_LOG.md's session #46 entry: an unlabeled input is a real
 * accessibility bug, not a style nitpick) — this page's Email field
 * had a bare <label> with no htmlFor/id pairing until now.
 */
describe("ForgotPasswordPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("exposes the email field to assistive tech via a properly associated label", async () => {
    const user = userEvent.setup();
    forgotPasswordRequest.mockResolvedValue({ message: "If that email exists, a reset link has been sent." });
    render(<ForgotPasswordPage onBackToLogin={() => {}} accountType="staff" />);

    // getByLabelText throws if the <label> isn't wired to the input via
    // htmlFor/id — this line IS the regression guard.
    await user.type(screen.getByLabelText(/email/i), "agent@example.com");
    await user.click(screen.getByRole("button", { name: /send reset link/i }));

    expect(forgotPasswordRequest).toHaveBeenCalledWith("agent@example.com", null);
    expect(await screen.findByText(/reset link has been sent/i)).toBeInTheDocument();
  });

  it("routes a customer account's request through the customer endpoint", async () => {
    const user = userEvent.setup();
    customerForgotPasswordRequest.mockResolvedValue({ message: "If that email exists, a reset link has been sent." });
    render(<ForgotPasswordPage onBackToLogin={() => {}} accountType="customer" />);

    await user.type(screen.getByLabelText(/email/i), "shopper@example.com");
    await user.click(screen.getByRole("button", { name: /send reset link/i }));

    expect(customerForgotPasswordRequest).toHaveBeenCalledWith("shopper@example.com", null);
    expect(forgotPasswordRequest).not.toHaveBeenCalled();
  });
});
