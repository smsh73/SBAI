"""Full 46-page VLM analysis script"""
import sys, os, json, time
sys.path.insert(0, 'webapp/backend')

# Load API key
from pathlib import Path
env_path = Path('webapp/backend/.env')
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())

from app.services.vlm_bom_service import process_bom_with_vlm

pdf_path = '3. 260211-PIPE_BOM추출용.pdf'
out_dir = 'full_vlm_output'
os.makedirs(out_dir, exist_ok=True)

print(f"Starting full 46-page VLM analysis at {time.strftime('%H:%M:%S')}")
print(f"PDF: {pdf_path}")
print(f"Output: {out_dir}/")
print("=" * 60)

start = time.time()
results = process_bom_with_vlm(pdf_path, out_dir)
total = time.time() - start

print("=" * 60)
print(f"Total time: {total:.0f}s ({total/60:.1f} min)")
print(f"Pages processed: {len(results)}")
print(f"Avg per page: {total/len(results):.1f}s")

# Summary
ok_draw = sum(1 for r in results if r.get('drawing_analysis_ok'))
ok_table = sum(1 for r in results if r.get('table_analysis_ok'))
total_bom = sum(len(r.get('bom_table', [])) for r in results)
total_cuts = sum(len(r.get('cut_lengths', [])) for r in results)
total_welds = sum(len(r.get('weld_points', [])) for r in results)
total_pieces = sum(len(r.get('pipe_pieces', [])) for r in results)

print(f"\nDrawing analysis OK: {ok_draw}/{len(results)}")
print(f"Table analysis OK: {ok_table}/{len(results)}")
print(f"Total BOM items: {total_bom}")
print(f"Total cut lengths: {total_cuts}")
print(f"Total weld points: {total_welds}")
print(f"Total pipe pieces: {total_pieces}")

# Line numbers
lines = set()
for r in results:
    ln = r.get('line_no', '') or (r.get('drawing_info', {}) or {}).get('line_no', '')
    if ln:
        lines.add(str(ln))
print(f"Unique line numbers: {sorted(lines)}")

# Generate Excel
from app.services.excel_service import generate_vlm_bom_excel
excel_path = os.path.join(out_dir, 'vlm_bom_report.xlsx')
generate_vlm_bom_excel(results, excel_path)
print(f"\nExcel report: {excel_path}")
