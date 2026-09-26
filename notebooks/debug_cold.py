import sys
from datetime import date

sys.path.insert(0, "src")

from gridcast.eval.slices import _daily_temps

for unit, eval_start in (("NEM_TOTAL", date(2026, 4, 1)), ("GB", date(2026, 4, 21))):
    ref_start = date.fromordinal(eval_start.toordinal() - 90)
    ref_end = date.fromordinal(eval_start.toordinal() - 1)
    ref = _daily_temps(unit, ref_start, ref_end)
    ev = _daily_temps(unit, eval_start, date(2026, 9, 24))
    print(unit, "ref days:", len(ref), ref.index.min(), "->", ref.index.max())
    print("  ref temp min/mean:", round(ref.min(), 2), round(ref.mean(), 2))
    print("  eval temp min/mean:", round(ev.min(), 2), round(ev.mean(), 2), "n:", len(ev))
    thr = ref.quantile(0.1)
    print("  threshold:", round(thr, 2), "eval days below threshold:", int((ev <= thr).sum()))
