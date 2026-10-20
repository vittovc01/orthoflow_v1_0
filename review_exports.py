"""Export the current editable product list, without technical/clinical fields."""
import csv
from io import BytesIO, StringIO

from review_editor import text_value, quantity_value, canonical_values


COLUMNS = [('REF', 'codice'), ('Lotto', 'lotto'), ('Scadenza', 'scadenza'),
           ('Descrizione', 'descrizione'), ('Quantità', 'quantita')]


def export_rows(rows):
    return [{title: ((quantity_value(row.get(key)) or text_value(row.get(key))) if key == 'quantita'
                     else text_value(row.get(key))) for title, key in COLUMNS}
            for row in map(canonical_values, rows) if not row.get('escludi_riga')]


def review_csv(rows):
    stream = StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=[c[0] for c in COLUMNS], delimiter=';')
    writer.writeheader()
    for row in export_rows(rows):
        # CSV applications can interpret leading operators as formulas.
        writer.writerow({k: "'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@', '\t', '\r'))
                         else v for k, v in row.items()})
    return stream.getvalue().encode('utf-8-sig')


def review_xlsx(rows):
    import pandas as pd
    stream = BytesIO()
    with pd.ExcelWriter(stream, engine='xlsxwriter', engine_kwargs={
            'options': {'strings_to_formulas': False, 'strings_to_urls': False}}) as writer:
        frame = pd.DataFrame(export_rows(rows), columns=[c[0] for c in COLUMNS])
        frame.to_excel(writer, index=False, sheet_name='Materiali')
        sheet = writer.sheets['Materiali']
        sheet.freeze_panes(1, 0)
        sheet.autofilter(0, 0, len(frame), len(COLUMNS)-1)
        sheet.set_column(0, 2, 22)
        sheet.set_column(3, 3, 55)
        sheet.set_column(4, 4, 12)
    return stream.getvalue()
