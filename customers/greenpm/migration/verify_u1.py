#!/usr/bin/env python3
"""U1 검증 단언 A~N — docs/spec/greenpm-data-migration/u1-normalized-extract.md"""
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent
D = json.loads((BASE / "normalized.json").read_text(encoding="utf-8"))
S, M, U, O, SUB = D["매출"], D["원부자재"], D["원단사용현황"], D["외주"], D["_외주소계"]

results = []


def check(tag, cond, detail):
    results.append((tag, bool(cond), detail))


# A
check("A", len(S) == 23, f"매출 레코드 {len(S)} == 23")
# B
tot = sum(r["총액"] for r in S)
check("B", tot == 5_350_600, f"매출 총액 합계 {tot:,} == 5,350,600")
# C
unpaid = sum(r["총액"] for r in S if not r["결제완료"])
n_unpaid = sum(1 for r in S if not r["결제완료"])
check("C", unpaid == 1_430_000 and n_unpaid == 2, f"미결제 {n_unpaid}건 {unpaid:,} == 2건 1,430,000")
# D
miss = [k for r in S for k in ("일자", "거래처", "담당자", "작업명", "총액", "발송일") if r[k] is None]
check("D", not miss, f"매출 필수필드 결측 {len(miss)}건 == 0")
# E
raw = sum(1 for r in M if r["자재구분"] == "원자재")
sub_ = sum(1 for r in M if r["자재구분"] == "부자재")
check("E", len(M) == 15 and raw == 8 and sub_ == 7, f"원부자재 {len(M)} (원자재 {raw} / 부자재 {sub_}) == 15 (8/7)")
# F
msum = sum(r["매입가"] for r in M if r["매입가"] is not None)
mnull = [r["구분"] for r in M if r["매입가"] is None]
check("F", msum == 3_737_440 and sorted(mnull) == sorted(["생분해성 / 600폭", "종이명찰 단면"]),
      f"매입가 합계 {msum:,} == 3,737,440 · 결측 {mnull}")
# G
qn = sum(1 for r in M if r["잔여량"] is None)
sn = sum(1 for r in M if r["스토리지"] is None)
check("G", qn == 3 and sn == 3, f"잔여량 결측 {qn} · 스토리지 결측 {sn} == 3 / 3")
# H
check("H", len(U) == 4, f"원단 사용현황 {len(U)} == 4")
# I
nokind = sum(1 for r in O if not r["구분"])
check("I", len(O) == 38 and nokind == 0, f"외주 {len(O)} == 38 · 구분 결측(소계혼입) {nokind} == 0")
# J
osum = sum(r["금액"] for r in O if r["금액"] is not None)
onull = sorted(r["구분"] for r in O if r["금액"] is None)
check("J", osum == 4_662_129 and onull == sorted(["sh공사 행사", "인플릿"]),
      f"외주 금액 합계 {osum:,} == 4,662,129 · 결측 {onull}")
# K
by_v = Counter()
for r in O:
    if r["금액"] is not None:
        by_v[r["매입처"]] += r["금액"]
oj = sum(v for k, v in by_v.items() if k.startswith("외주"))
check("K", by_v["DZ원"] == SUB["DZ원"] == 2_570_129 and oj == SUB["외주1"] == 277_000
      and by_v["세무법인"] == SUB["세무법인"] == 1_815_000,
      f"소계 대조: DZ원 {by_v['DZ원']:,}/{SUB['DZ원']:,} · 외주1~9 {oj:,}/{SUB['외주1']:,} · 세무법인 {by_v['세무법인']:,}/{SUB['세무법인']:,}")
# L
EXPECT = {("외주1", "디자인"): "2024-10-01", ("DZ원", "실사"): {"2024-11-01", "2024-12-01"}}
nodate = sum(1 for r in O if not r["시기"])
tax_dates = sorted(r["시기"] for r in O if r["매입처"] == "세무법인")
want = ["2024-11-01", "2024-12-01"] + [f"2025-{m:02d}-01" for m in range(1, 10)]
d1 = [r["시기"] for r in O if (r["매입처"], r["구분"]) == ("외주1", "디자인")]
d2 = sorted(r["시기"] for r in O if (r["매입처"], r["구분"]) == ("DZ원", "실사"))
check("L", nodate == 0 and tax_dates == want and d1 == ["2024-10-01"] and d2 == ["2024-11-01", "2024-12-01"],
      f"시기 결측 {nodate} == 0 · 세무법인 11건 {tax_dates[0]}~{tax_dates[-1]} · 외주1 {d1} · DZ원실사 {d2}")
# M
vend = Counter(r["매입처"] for r in O)
check("M", len(vend) == 11 and vend["DZ원"] == 18 and vend["세무법인"] == 11
      and all(vend[f"외주{n}"] == 1 for n in range(1, 10)),
      f"매입처 {len(vend)}종 == 11 · DZ원 {vend['DZ원']} · 세무법인 {vend['세무법인']}")
# N — 재실행 결정론
before = (BASE / "normalized.json").read_bytes()
subprocess.run([sys.executable, str(BASE / "u1_normalize.py")], check=True, capture_output=True)
check("N", before == (BASE / "normalized.json").read_bytes(), "재실행 결과 바이트 동일 (결정론)")

w = max(len(t) for t, _, _ in results)
ok = 0
for tag, passed, detail in results:
    print(f"  {'OK ' if passed else 'NOK'}  {tag:<{w}}  {detail}")
    ok += passed
print(f"\n{ok}/{len(results)} 통과")
sys.exit(0 if ok == len(results) else 1)
