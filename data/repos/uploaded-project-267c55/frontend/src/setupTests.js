// Runs once before the test suite — adds jest-dom's matchers
// (toBeInTheDocument, toHaveTextContent, etc.) to Vitest's `expect`,
// which doesn't include them by default the way Jest+jest-dom's
// classic setup did.
import "@testing-library/jest-dom";
