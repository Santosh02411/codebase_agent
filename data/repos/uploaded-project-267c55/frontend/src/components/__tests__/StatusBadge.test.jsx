import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import StatusBadge from "../StatusBadge";

describe("StatusBadge", () => {
  it.each([
    ["picked_up", "Picked Up"],
    ["out_for_delivery", "Out for Delivery"],
    ["delivered", "Delivered"],
    ["failed_attempt", "Failed Attempt"],
    ["cancelled", "Cancelled"],
    ["pending", "Pending"],
  ])("renders the human-readable label for status %s", (status, label) => {
    render(<StatusBadge status={status} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("applies the raw status as a CSS class for status-specific styling", () => {
    render(<StatusBadge status="delivered" />);
    expect(screen.getByText("Delivered")).toHaveClass("status-badge", "delivered");
  });

  it("falls back to showing the raw status string for an unrecognized status", () => {
    render(<StatusBadge status="some_new_status" />);
    expect(screen.getByText("some_new_status")).toBeInTheDocument();
  });
});
