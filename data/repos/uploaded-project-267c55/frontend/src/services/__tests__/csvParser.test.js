import { describe, it, expect } from "vitest";
import { parseCSV } from "../csvParser";

describe("parseCSV", () => {
  it("parses a simple CSV with a header row", () => {
    const csv = "order_id,zone\nORD-1,Zone A\nORD-2,Zone B";
    expect(parseCSV(csv)).toEqual([
      { order_id: "ORD-1", zone: "Zone A" },
      { order_id: "ORD-2", zone: "Zone B" },
    ]);
  });

  it("handles a comma inside a quoted field without breaking column alignment", () => {
    const csv = 'order_id,notes\nORD-1,"Fragile, deliver before 5pm"';
    expect(parseCSV(csv)).toEqual([
      { order_id: "ORD-1", notes: "Fragile, deliver before 5pm" },
    ]);
  });

  it("handles an escaped double-quote inside a quoted field", () => {
    const csv = 'order_id,notes\nORD-1,"Say ""hello"" at the door"';
    expect(parseCSV(csv)).toEqual([
      { order_id: "ORD-1", notes: 'Say "hello" at the door' },
    ]);
  });

  it("handles a newline inside a quoted field", () => {
    const csv = 'order_id,notes\nORD-1,"Line one\nLine two"\nORD-2,plain';
    expect(parseCSV(csv)).toEqual([
      { order_id: "ORD-1", notes: "Line one\nLine two" },
      { order_id: "ORD-2", notes: "plain" },
    ]);
  });

  it("normalizes CRLF line endings the same as LF", () => {
    const csv = "order_id,zone\r\nORD-1,Zone A\r\nORD-2,Zone B";
    expect(parseCSV(csv)).toEqual([
      { order_id: "ORD-1", zone: "Zone A" },
      { order_id: "ORD-2", zone: "Zone B" },
    ]);
  });

  it("normalizes lone CR line endings the same as LF", () => {
    const csv = "order_id,zone\rORD-1,Zone A\rORD-2,Zone B";
    expect(parseCSV(csv)).toEqual([
      { order_id: "ORD-1", zone: "Zone A" },
      { order_id: "ORD-2", zone: "Zone B" },
    ]);
  });

  it("trims whitespace from header names and field values", () => {
    const csv = " order_id , zone \n ORD-1 , Zone A ";
    expect(parseCSV(csv)).toEqual([{ order_id: "ORD-1", zone: "Zone A" }]);
  });

  it("handles a file with no trailing newline after the last row", () => {
    const csv = "order_id\nORD-1\nORD-2";
    expect(parseCSV(csv)).toEqual([{ order_id: "ORD-1" }, { order_id: "ORD-2" }]);
  });

  it("drops a fully-empty trailing line (trailing newline in the file)", () => {
    const csv = "order_id\nORD-1\n";
    expect(parseCSV(csv)).toEqual([{ order_id: "ORD-1" }]);
  });

  it("fills in an empty string for a row with fewer fields than headers", () => {
    const csv = "order_id,zone,notes\nORD-1,Zone A";
    expect(parseCSV(csv)).toEqual([{ order_id: "ORD-1", zone: "Zone A", notes: "" }]);
  });

  it("returns an empty array for an empty string", () => {
    expect(parseCSV("")).toEqual([]);
  });

  it("returns an empty array for a header-only CSV (no data rows)", () => {
    expect(parseCSV("order_id,zone")).toEqual([]);
  });

  it("handles multiple quoted fields with commas in the same row", () => {
    const csv = 'a,b\n"one, two","three, four"';
    expect(parseCSV(csv)).toEqual([{ a: "one, two", b: "three, four" }]);
  });
});
