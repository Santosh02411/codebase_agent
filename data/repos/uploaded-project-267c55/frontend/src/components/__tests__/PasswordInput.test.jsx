import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PasswordInput from "../PasswordInput";

describe("PasswordInput", () => {
  it("renders as a password field by default", () => {
    render(<PasswordInput value="" onChange={() => {}} />);
    const input = screen.getByLabelText(/show password/i) && document.querySelector("input");
    expect(input).toHaveAttribute("type", "password");
  });

  it("toggles to a visible text field when the eye button is clicked", async () => {
    const user = userEvent.setup();
    render(<PasswordInput value="hunter2" onChange={() => {}} />);

    const input = document.querySelector("input");
    expect(input).toHaveAttribute("type", "password");

    const toggleButton = screen.getByRole("button", { name: /show password/i });
    await user.click(toggleButton);

    expect(input).toHaveAttribute("type", "text");
    expect(screen.getByRole("button", { name: /hide password/i })).toBeInTheDocument();
  });

  it("toggles back to hidden on a second click", async () => {
    const user = userEvent.setup();
    render(<PasswordInput value="hunter2" onChange={() => {}} />);

    const toggleButton = screen.getByRole("button", { name: /show password/i });
    await user.click(toggleButton);
    await user.click(screen.getByRole("button", { name: /hide password/i }));

    expect(document.querySelector("input")).toHaveAttribute("type", "password");
  });

  it("never calls onChange as a side effect of toggling visibility", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<PasswordInput value="hunter2" onChange={onChange} />);

    await user.click(screen.getByRole("button", { name: /show password/i }));

    expect(onChange).not.toHaveBeenCalled();
  });

  it("forwards standard input props through to the underlying input", () => {
    render(<PasswordInput value="x" onChange={() => {}} required minLength={6} placeholder="Password" />);
    const input = document.querySelector("input");
    expect(input).toHaveAttribute("required");
    expect(input).toHaveAttribute("minlength", "6");
    expect(input).toHaveAttribute("placeholder", "Password");
  });

  it("calls onChange when the user types, same as a plain input would", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<PasswordInput value="" onChange={onChange} />);

    await user.type(document.querySelector("input"), "a");

    expect(onChange).toHaveBeenCalled();
  });

  it("the toggle button is not part of the tab order (tabIndex -1)", () => {
    render(<PasswordInput value="" onChange={() => {}} />);
    expect(screen.getByRole("button", { name: /show password/i })).toHaveAttribute("tabindex", "-1");
  });
});
