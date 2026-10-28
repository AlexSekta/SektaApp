import * as XLSX from 'xlsx';

export type ExportSheet = {
  name: string;
  headers: string[];
  rows: Array<Array<string | number | null>>;
  widths?: number[];
};

// Called only by the user's export button; no data is fetched or modified here.
export function downloadWorkbook(filename: string, sheets: ExportSheet[]): void {
  const workbook = XLSX.utils.book_new();
  for (const sheet of sheets) {
    const worksheet = XLSX.utils.aoa_to_sheet([sheet.headers, ...sheet.rows]);
    worksheet['!cols'] = (sheet.widths ?? sheet.headers.map(() => 23)).map(wch => ({ wch }));
    // Preserve identifiers as text, never as spreadsheet formulas.
    for (const address of Object.keys(worksheet)) {
      if (address.startsWith('!')) continue;
      const cell = worksheet[address];
      if (typeof cell.v === 'string') { cell.t = 's'; delete cell.f; }
    }
    XLSX.utils.book_append_sheet(workbook, worksheet, sheet.name.substring(0, 31));
  }
  XLSX.writeFile(workbook, filename, { compression: true });
}
