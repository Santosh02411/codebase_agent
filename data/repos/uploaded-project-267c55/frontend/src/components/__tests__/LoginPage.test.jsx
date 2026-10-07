import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const staffLogin = vi.fn();
const completeTwoFactorLogin = vi.fn();
const customerLogin = vi.fn();
const demoLogin = vi.fn();

vi.mock("../../context/AuthContext", () => ({
  useAuth: () => ({ login: staffLogin, completeTwoFactorLogin, demoLogin }),
}));
vi.mock("../../context/CustomerAuthContext", () => ({
  useCustomerAuth: () => ({ login: customerLogin }),
}));
vi.mock("../../context/ThemeContext", () => ({
  useTheme: () => ({ theme: "dark", toggleTheme: vi.fn() }),
}));
vi.mock("../../services/api", () => ({
  resendTwoFactorLoginCode: vi.fn(),
}));
vi.mock("../../services/authApi", () => ({
  getGoogleOAuthLoginUrl: vi.fn(),
  getCustomerGoogleOAuthLoginUrl: vi.fn(),
}));

import LoginPage from "../LoginPage";

describe("LoginPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("logs a staff user in with username and password", async () => {
    const user = userEvent.setup();
    staffLogin.mockResolvedValue({});
    render(<LoginPage onSwitchToSignup={() => {}} onForgotPassword={() => {}} />);

    await user.type(screen.getByLabelText(/username/i), "dispatcher1");
    await user.type(document.querySelector('input[type="password"]'), "correct-horse");
    await user.click(screen.getByRole("button", { name: /log in/i }));

    expect(staffLogin).toHaveBeenCalledWith("dispatcher1", "correct-horse");
  });

  it("shows the backend's error message when login fails", async () => {
    const user = userEvent.setup();
    staffLogin.mockRejectedValue(new Error("Incorrect username or password."));
    render(<LoginPage onSwitchToSignup={() => {}} onForgotPassword={() => {}} />);

    await user.type(screen.getByLabelText(/username/i), "dispatcher1");
    await user.type(document.querySelector('input[type="password"]'), "wrong-password");
    await user.click(screen.getByRole("button", { name: /log in/i }));

    expect(await screen.findByText("Incorrect username or password.")).toBeInTheDocument();
  });

  it("switches to the 2FA challenge step when the backend requires it", async () => {
    const user = userEvent.setup();
    staffLogin.mockResolvedValue({
      requires_2fa: true,
      challenge_token: "chal-123",
      two_factor_method: "totp",
    });
    render(<LoginPage onSwitchToSignup={() => {}} onForgotPassword={() => {}} />);

    await user.type(screen.getByLabelText(/username/i), "dispatcher1");
    await user.type(document.querySelector('input[type="password"]'), "correct-horse");
    await user.click(screen.getByRole("button", { name: /log in/i }));

    expect(await screen.findByText(/enter your code/i)).toBeInTheDocument();
  });

  it("completes login after entering a valid 2FA code", async () => {
    const user = userEvent.setup();
    staffLogin.mockResolvedValue({
      requires_2fa: true,
      challenge_token: "chal-123",
      two_factor_method: "totp",
    });
    completeTwoFactorLogin.mockResolvedValue({});
    render(<LoginPage onSwitchToSignup={() => {}} onForgotPassword={() => {}} />);

    await user.type(screen.getByLabelText(/username/i), "dispatcher1");
    await user.type(document.querySelector('input[type="password"]'), "correct-horse");
    await user.click(screen.getByRole("button", { name: /log in/i }));

    const input = await screen.findByLabelText(/6-digit code/i);
    await user.type(input, "123456");
    await user.click(screen.getByRole("button", { name: /verify/i }));

    expect(completeTwoFactorLogin).toHaveBeenCalledWith("chal-123", "123456");
  });

  it("switches the identifier field label between Username (staff) and Email (customer)", async () => {
    const user = userEvent.setup();
    render(<LoginPage onSwitchToSignup={() => {}} onForgotPassword={() => {}} />);

    expect(screen.getByLabelText(/username/i)).toBeInTheDocument();

    await user.selectOptions(screen.getByRole("combobox"), "customer");

    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
  });

  it("logs a customer in via the customer auth context when Customer is selected", async () => {
    const user = userEvent.setup();
    customerLogin.mockResolvedValue({});
    render(<LoginPage onSwitchToSignup={() => {}} onForgotPassword={() => {}} />);

    await user.selectOptions(screen.getByRole("combobox"), "customer");
    await user.type(screen.getByLabelText(/email/i), "customer@example.com");
    await user.type(document.querySelector('input[type="password"]'), "correct-horse");
    await user.click(screen.getByRole("button", { name: /log in/i }));

    expect(customerLogin).toHaveBeenCalledWith("customer@example.com", "correct-horse");
    expect(staffLogin).not.toHaveBeenCalled();
  });

  it("calls onForgotPassword with the current account type when clicked", async () => {
    const user = userEvent.setup();
    const onForgotPassword = vi.fn();
    render(<LoginPage onSwitchToSignup={() => {}} onForgotPassword={onForgotPassword} />);

    await user.click(screen.getByRole("button", { name: /forgot password/i }));

    expect(onForgotPassword).toHaveBeenCalledWith("staff");
  });

  it("logs straight in via demoLogin when Try the Demo is clicked, without touching staffLogin", async () => {
    const user = userEvent.setup();
    demoLogin.mockResolvedValue({});
    render(<LoginPage onSwitchToSignup={() => {}} onForgotPassword={() => {}} />);

    await user.click(screen.getByRole("button", { name: /try the demo/i }));

    expect(demoLogin).toHaveBeenCalled();
    expect(staffLogin).not.toHaveBeenCalled();
  });

  it("shows the backend's error message when the demo is unavailable", async () => {
    const user = userEvent.setup();
    demoLogin.mockRejectedValue(new Error("The demo isn't available right now. Please try again shortly."));
    render(<LoginPage onSwitchToSignup={() => {}} onForgotPassword={() => {}} />);

    await user.click(screen.getByRole("button", { name: /try the demo/i }));

    expect(await screen.findByText(/demo isn't available right now/i)).toBeInTheDocument();
  });

  it("disables the demo button while the request is in flight", async () => {
    const user = userEvent.setup();
    let resolveLogin;
    demoLogin.mockReturnValue(new Promise((resolve) => { resolveLogin = resolve; }));
    render(<LoginPage onSwitchToSignup={() => {}} onForgotPassword={() => {}} />);

    const demoButton = screen.getByRole("button", { name: /try the demo/i });
    await user.click(demoButton);

    expect(demoButton).toBeDisabled();

    resolveLogin({});
    // Let the resolved promise's state update settle before the test
    // (and React) considers this click's work finished.
    await screen.findByRole("button", { name: /try the demo/i });
  });
});
