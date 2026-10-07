/**
 * Minimal RFC4180-style CSV parser: handles quoted fields (so commas and
 * newlines inside a quoted field don't break parsing) and escaped quotes
 * ("" inside a quoted field means a literal "). A naive text.split(',')
 * approach breaks the moment a dispatcher's notes field contains a comma
 * (e.g. "Fragile, deliver before 5pm") — this handles that correctly.
 *
 * Returns an array of row objects, keyed by the header row's column names
 * (trimmed, exactly as written in the CSV).
 */
export function parseCSV(text) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;
  let i = 0;

  function pushField() {
    row.push(field);
    field = "";
  }

  function pushRow() {
    pushField();
    rows.push(row);
    row = [];
  }

  // Normalize line endings so \r\n and \r both behave like \n
  const normalized = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");

  while (i < normalized.length) {
    const char = normalized[i];

    if (inQuotes) {
      if (char === '"') {
        if (normalized[i + 1] === '"') {
          field += '"'; // escaped quote
          i += 2;
          continue;
        }
        inQuotes = false;
        i += 1;
        continue;
      }
      field += char;
      i += 1;
      continue;
    }

    if (char === '"') {
      inQuotes = true;
      i += 1;
      continue;
    }
    if (char === ",") {
      pushField();
      i += 1;
      continue;
    }
    if (char === "\n") {
      pushRow();
      i += 1;
      continue;
    }
    field += char;
    i += 1;
  }

  // Push the final field/row if the file doesn't end with a newline
  if (field.length > 0 || row.length > 0) {
    pushRow();
  }

  // Drop any fully-empty trailing rows (common with a trailing blank line)
  const cleanedRows = rows.filter((r) => !(r.length === 1 && r[0] === ""));

  if (cleanedRows.length === 0) return [];

  const headers = cleanedRows[0].map((h) => h.trim());
  const dataRows = cleanedRows.slice(1);

  return dataRows.map((r) => {
    const obj = {};
    headers.forEach((header, index) => {
      obj[header] = (r[index] ?? "").trim();
    });
    return obj;
  });
}
