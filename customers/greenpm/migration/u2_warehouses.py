# U2 — 창고 재편 (odoo shell)
# 계약: docs/spec/greenpm-data-migration/u2-warehouse-realign.md
# 스토리지 2곳(고양·백석)에 대응하는 창고만 남긴다.

WH = env['stock.warehouse']
TARGET = [("고양", "GY"), ("백석", "BS")]

moves = env['stock.move'].search_count([])
quants = env['stock.quant'].search_count([('location_id.usage', '=', 'internal')])
print(f"사전 확인: 재고이동 {moves}건 · 내부위치 재고 {quants}건")
assert moves == 0 and quants == 0, "재고 이동/수량이 존재하면 창고 구조를 바꾸지 않는다"

existing = WH.search([], order='id')
print(f"현재 창고 {len(existing)}개: {[(w.id, w.name, w.code) for w in existing]}")

# 앞의 2개를 고양·백석으로 개명하고, 나머지는 제거한다.
keep, drop = existing[:2], existing[2:]
for wh, (name, code) in zip(keep, TARGET):
    wh.write({'name': name, 'code': code})
    print(f"  개명: id={wh.id} → {name} ({code})")

for wh in drop:
    # 창고가 소유한 작업유형을 참조하는 재고규칙(외주생산 재공급 등)은 창고 삭제 시
    # 자동 정리되지 않으므로 먼저 제거한다. 재고 이동이 0건이므로 사실 손실이 없다.
    # 보관처리(archived)된 규칙도 FK를 잡으므로 active_test=False 로 함께 찾는다.
    pts = env['stock.picking.type'].with_context(active_test=False).search([('warehouse_id', '=', wh.id)])
    rules = env['stock.rule'].with_context(active_test=False).search(
        ['|', ('picking_type_id', 'in', pts.ids), ('warehouse_id', '=', wh.id)])
    print(f"  제거: id={wh.id} {wh.name} ({wh.code}) — 선행 정리 재고규칙 {len(rules)}건")
    rules.unlink()
    wh.unlink()

# 위치 이름·계층을 창고와 일치시킨다.
# 이전 테넌트에서 따라온 구조에는 한 창고의 보관위치가 다른 창고 뷰 아래 붙어 있는 경우가 있다.
for wh in WH.search([], order='id'):
    wh.view_location_id.write({'name': wh.code})
    wh.lot_stock_id.write({'name': wh.name})
    if wh.lot_stock_id.location_id != wh.view_location_id:
        print(f"  계층 교정: {wh.name} 보관위치 상위 {wh.lot_stock_id.location_id.name} → {wh.view_location_id.name}")
        wh.lot_stock_id.write({'location_id': wh.view_location_id.id})
    # 창고에 속한 나머지 위치도 자기 창고 뷰 아래로 모은다.
    for loc in env['stock.location'].with_context(active_test=False).search(
            [('warehouse_id', '=', wh.id), ('id', 'not in', (wh.view_location_id | wh.lot_stock_id).ids)]):
        if loc.location_id != wh.view_location_id:
            loc.write({'location_id': wh.view_location_id.id})
    print(f"  위치 정리: {wh.name} → {wh.view_location_id.name}/{wh.lot_stock_id.name}")

# 제거된 창고가 남긴 위치를 정리한다.
# 창고에 속하지 않는 내부/뷰 위치가 후보이나, 그중에는 창고와 무관하게 회사가 소유하는
# 위치(외주생산·창고간 경유)가 섞여 있으므로 제외한다. 남은 창고의 설정이 가리키는 위치와,
# 재고·이동 이력이 걸린 위치도 제외한다 (사실 손실 방지).
Loc = env['stock.location'].with_context(active_test=False)
kept = WH.search([])
protected = kept.view_location_id | kept.lot_stock_id \
    | env.company.subcontracting_location_id | env.company.internal_transit_location_id
for pt in env['stock.picking.type'].with_context(active_test=False).search([('warehouse_id', 'in', kept.ids)]):
    protected |= pt.default_location_src_id | pt.default_location_dest_id

orphans = Loc.search([('usage', 'in', ('internal', 'view'))]).filtered(
    lambda l: not l.warehouse_id and l not in protected)
for loc in orphans:
    used = env['stock.quant'].search_count([('location_id', '=', loc.id)]) \
        or env['stock.move.line'].with_context(active_test=False).search_count(
            ['|', ('location_id', '=', loc.id), ('location_dest_id', '=', loc.id)])
    if used:
        print(f"  위치 보존(사용 이력 있음): {loc.complete_name}")
        orphans -= loc
print(f"  잔재 위치 제거 {len(orphans)}건: {sorted(l.complete_name for l in orphans)}")
orphans.unlink()

env.cr.commit()

final = WH.search([], order='id')
print(f"\n결과: 창고 {len(final)}개")
for w in final:
    print(f"  {w.id} {w.name} ({w.code}) 보관위치={w.lot_stock_id.complete_name}")
left = Loc.search([('usage', 'in', ('internal', 'view')), ('warehouse_id', '=', False)])
print(f"창고 밖 내부/뷰 위치 잔존: {len(left)}건 {[(l.id, l.complete_name) for l in left]} (회사 소유 위치만 남아야 함)")
