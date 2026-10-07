import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const staffSignup = vi.fn();
const customerSignup = vi.fn();

vi.mock("../../context/AuthContext", () => ({
  useAuth: () => ({ signup: staffSignup }),
}));
vi.mock("../../context/CustomerAuthContext", () => ({
  useCustomerAuth: () => ({ signup: customerSignup }),
}));
vi.mock("../../context/ThemeContext", () => ({
  useTheme: () => ({ theme: "dark", toggleTheme: vi.fn() }),
}));
vi.mock("../../services/authApi", () => ({
  getGoogleOAuthLoginUrl: vi.fn(),
  getCustomerGoogleOAuthLoginUrl: vi.fn(),
}));

import SignupPage from "../SignupPage";

/**
 * Regression coverage for the same "bare <label>, no htmlFor/id" bug
 * class LoginPage.test.jsx's getByLabelText calls already guard
 * against (see FEATURE_LOG.md's session #46 entry) — every field on
 * this page's role selector, customer form, and staff form had that
 * exact bug until now.
 */
describe("SignupPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("signs up a staff agent joining an org via invite code (the default role)", async () => {
    const user = userEvent.setup();
    staffSignup.mockResolvedValue({});
    render(<SignupPage onSwitchToLogin={() => {}} />);

    // getByLabelText throws if a <label> isn't wired to its input via
    // htmlFor/id — every one of these calls IS the regression guard.
    expect(screen.getByLabelText(/i am a/i)).toBeInTheDocument();
    await user.type(screen.getByLabelText(/display name/i), "Jane Doe");
    await user.type(screen.getByLabelText(/username/i), "jane.doe");
    await user.type(screen.getByLabelText(/^email$/i), "jane@example.com");
    await user.type(screen.getByLabelText(/^password$/i), "correct-horse");
    await user.type(screen.getByLabelText(/invite code/i), "ABC12345");
    await user.click(screen.getByRole("button", { name: /^sign up$/i }));

    expect(staffSignup).toHaveBeenCalledWith(expect.objectContaining({
      username: "jane.doe",
      email: "jane@example.com",
      display_name: "Jane Doe",
      invite_code: "ABC12345",
      role: "agent",
    }));
  });

  it("signs up a customer once 'I am a...' is switched to Customer", async () => {
    const user = userEvent.setup();
    customerSignup.mockResolvedValue({});
    render(<SignupPage onSwitchToLogin={() => {}} />);

    await user.selectOptions(screen.getByLabelText(/i am a/i), "customer");
    await user.type(screen.getByLabelText(/^name$/i), "Priya Shah");
    await user.type(screen.getByLabelText(/^email$/i), "priya@example.com");
    await user.type(screen.getByLabelText(/^password$/i), "correct-horse");
    await user.click(screen.getByRole("button", { name: /^sign up$/i }));

    expect(customerSignup).toHaveBeenCalledWith("priya@example.com", "correct-horse", "Priya Shah", null);
    expect(staffSignup).not.toHaveBeenCalled();
  });

  it("shows the Organization Name field, not Invite Code, for the admin role", async () => {
    const user = userEvent.setup();
    render(<SignupPage onSwitchToLogin={() => {}} />);

    await user.selectOptions(screen.getByLabelText(/i am a/i), "admin");

    expect(screen.getByLabelText(/organization name/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/invite code/i)).not.toBeInTheDocument();
  });
});
