import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import GoogleIcon from "../GoogleIcon";

describe("GoogleIcon", () => {
  it("renders an SVG marked decorative (aria-hidden) since the button text carries the label", () => {
    const { container } = render(<GoogleIcon />);
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
    expect(svg).toHaveAttribute("aria-hidden", "true");
  });

  it("defaults to an 18px square", () => {
    const { container } = render(<GoogleIcon />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("width", "18");
    expect(svg).toHaveAttribute("height", "18");
  });

  it("respects a custom size prop", () => {
    const { container } = render(<GoogleIcon size={32} />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("width", "32");
    expect(svg).toHaveAttribute("height", "32");
  });
});
