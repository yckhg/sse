# 스펙 인덱스 (docs/spec)

`docs/spec/`는 **살아있는 계약 스펙(living contract specs)** 의 집입니다. 각 문서는
"무엇을 보장해야 하는가"를 선언적으로 기술하며, 구현 파일 참조·버그 이력·수정 지시는
담지 않습니다. 독자는 스펙 작성자입니다. (`spec-write` / `spec-tdd` 스킬과 짝을 이룹니다.)

## 스펙 목록

- [mcp-tenant-data-access.md](mcp-tenant-data-access.md) — MCP 테넌트 데이터 접근(읽기 전용): 사설 메시 도달성 · 읽기 전용 · 테넌트 범위 · 감사 계약 (Spec 1)
  - 적합성 테스트: `tests/spec/mcp-tenant-data-access/` (단언 A~L, `spec-tdd`)

## 설계 맵

- [greenpm-data-migration/SPEC-MAP.md](greenpm-data-migration/SPEC-MAP.md) — 그린피엠 운영 원장 엑셀 → Odoo 판매·구매·재고·회계 이관 (U1~U7 + 접합부 S1)
  - U1 [정규화 추출](greenpm-data-migration/u1-normalized-extract.md) · U2 [창고 재편](greenpm-data-migration/u2-warehouse-realign.md) · U3 [거래처](greenpm-data-migration/u3-partners.md) · U4 [품목](greenpm-data-migration/u4-products.md)
  - U5 [매출](greenpm-data-migration/u5-sales.md) · U6 [원부자재](greenpm-data-migration/u6-materials.md) · U7 [외주정산](greenpm-data-migration/u7-outsourcing.md)
  - 접합부: [_shared/greenpm-master-data-keys.md](_shared/greenpm-master-data-keys.md) — 기준정보 식별 키 (창고명·거래처명·품목명)
