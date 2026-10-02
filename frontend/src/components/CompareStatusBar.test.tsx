import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { CompareStatusBar } from "./CompareStatusBar";

describe("CompareStatusBar", () => {
  it("renders nothing when data is not truncated", () => {
    const { container } = render(
      <CompareStatusBar totalEntries={5} displayedCount={5} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a role=alert banner with counts when truncated", () => {
    render(
      <CompareStatusBar
        totalEntries={50}
        displayedCount={12}
        truncated={true}
        truncatedIncluded={12}
        truncatedOmitted={38}
        onSwitchToCustom={() => {}}
      />,
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("50");
    expect(alert).toHaveTextContent("12");
    expect(alert).toHaveTextContent("38");
    expect(screen.getByText(/カスタムで対象を絞り込む/)).toBeInTheDocument();
  });

  it("hides the narrow-down button when no callback is provided", () => {
    render(
      <CompareStatusBar
        totalEntries={50}
        displayedCount={12}
        truncated={true}
        truncatedIncluded={12}
        truncatedOmitted={38}
      />,
    );
    expect(screen.queryByText(/カスタムで対象を絞り込む/)).not.toBeInTheDocument();
  });
});
