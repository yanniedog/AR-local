/**
 * Minimal Google Sheets REST client (no googleapis dependency).
 * Reuses service-account JWT exchange from google-service-account-auth.mjs.
 */
import {
  getServiceAccountAccessToken,
  parseServiceAccountJson,
} from './google-service-account-auth.mjs';
import { CELL_COLORS } from './pr-bot-cell-status.mjs';

const SHEETS_SCOPE = 'https://www.googleapis.com/auth/spreadsheets';
const SHEETS_API = 'https://sheets.googleapis.com/v4/spreadsheets';

/**
 * @param {string} spreadsheetId
 * @param {string} accessToken
 * @param {string} path
 * @param {RequestInit} [init]
 */
async function sheetsFetch(spreadsheetId, accessToken, path, init = {}) {
  const url = `${SHEETS_API}/${spreadsheetId}${path}`;
  const response = await fetch(url, {
    ...init,
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
      ...(init.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.error?.message || response.statusText;
    throw new Error(`Google Sheets API ${response.status}: ${detail}`);
  }
  return payload;
}

/**
 * @param {string} rawJson
 * @param {string} [source]
 * @returns {Promise<string>}
 */
export async function getSheetsAccessToken(rawJson, source = 'PR_BOT_SHEET_SERVICE_ACCOUNT_JSON') {
  const sa = parseServiceAccountJson(rawJson, source);
  return getServiceAccountAccessToken(sa, SHEETS_SCOPE);
}

/**
 * @param {string} spreadsheetId
 * @param {string} accessToken
 * @param {string} [sheetTitle]
 * @returns {Promise<number>}
 */
export async function resolveSheetId(spreadsheetId, accessToken, sheetTitle = 'PR Bot Matrix') {
  const meta = await sheetsFetch(spreadsheetId, accessToken, '?fields=sheets(properties(sheetId,title))');
  const sheets = meta.sheets || [];
  const found = sheets.find((s) => s.properties?.title === sheetTitle);
  if (found?.properties?.sheetId != null) return found.properties.sheetId;
  if (sheets[0]?.properties?.sheetId != null) return sheets[0].properties.sheetId;
  throw new Error(`Sheet "${sheetTitle}" not found in spreadsheet`);
}

/**
 * @param {string[][]} values
 * @param {string[][]} statusMatrix - parallel matrix of CELL_STATUS strings (bot columns only)
 * @param {number} botColumnOffset - 0-based index where bot columns start
 */
function buildBatchRequests(sheetId, values, statusMatrix, botColumnOffset) {
  /** @type {object[]} */
  const requests = [];

  requests.push({
    updateCells: {
      range: {
        sheetId,
        startRowIndex: 0,
        endRowIndex: values.length,
        startColumnIndex: 0,
        endColumnIndex: values[0]?.length || 0,
      },
      rows: values.map((row, rowIdx) => ({
        values: row.map((cell, colIdx) => {
          const cellValue = { userEnteredValue: { stringValue: String(cell ?? '') } };
          if (rowIdx === 0) {
            return {
              ...cellValue,
              userEnteredFormat: {
                textFormat: { bold: true },
                backgroundColor: { red: 0.85, green: 0.85, blue: 0.85 },
              },
            };
          }
          const statusRow = statusMatrix[rowIdx - 1];
          const status = statusRow?.[colIdx - botColumnOffset];
          const color = status ? CELL_COLORS[status] : null;
          if (color && colIdx >= botColumnOffset) {
            return {
              ...cellValue,
              userEnteredFormat: { backgroundColor: color },
            };
          }
          return cellValue;
        }),
      })),
      fields: 'userEnteredValue,userEnteredFormat(backgroundColor,textFormat.bold)',
    },
  });

  return requests;
}

/**
 * Write the full matrix (header + rows) with color formatting.
 *
 * @param {object} opts
 * @param {string} opts.spreadsheetId
 * @param {string} opts.accessToken
 * @param {string[][]} opts.values
 * @param {string[][]} opts.statusMatrix - per data row, status per bot column
 * @param {number} opts.botColumnOffset
 * @param {string} [opts.sheetTitle]
 */
export async function writeSpreadsheetMatrix({
  spreadsheetId,
  accessToken,
  values,
  statusMatrix,
  botColumnOffset,
  sheetTitle = 'PR Bot Matrix',
}) {
  const sheetId = await resolveSheetId(spreadsheetId, accessToken, sheetTitle);
  const requests = buildBatchRequests(sheetId, values, statusMatrix, botColumnOffset);

  await sheetsFetch(spreadsheetId, accessToken, ':batchUpdate', {
    method: 'POST',
    body: JSON.stringify({ requests }),
  });
}
