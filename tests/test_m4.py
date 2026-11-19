from app.pipeline import calculate
from app.modules.m4_count.rules import apply
def group(ctx,sku): return next(g for g in ctx['stages']['4']['groups'] if g['药品']==sku)
def batches(ctx,sku): return {r['批号']:r for r in ctx['stages']['4']['rows'] if r['药品']==sku}
def test_stage_position(ctx):
    assert ctx['stages']['4']['name']=='盘点对平'
    assert [ctx['stages'][str(n)]['name'] for n in range(1,9)]==['库存接收','批号裁决','效期分层','盘点对平','需求净额','调拨分配','收发对账','方案复核']
def test_group_balances_to_physical_count(ctx):
    for g in ctx['stages']['4']['groups']:
        assert g['账面总数']-g['待落实扣减']-g['已落实扣减']-g['未分摊']+g['盘盈待落实']+g['盘盈已落实']==g['有效实盘']
def test_pending_shortage_follows_fefo_order(ctx):
    rows=batches(ctx,'0001')
    assert rows['B0020']['待落实扣减']==190 and rows['B0020']['盘后可用']==0
    assert rows['B0002']['待落实扣减']==90 and rows['B0002']['已落实扣减']==10
def test_confirmed_and_pending_tracked_separately(ctx):
    g=group(ctx,'0001');assert g['待落实扣减']==280 and g['已落实扣减']==10
def test_available_never_exceeds_effective_count(ctx):
    for g in ctx['stages']['4']['groups']: assert g['盘后可用']<=g['有效实盘']
    assert sum(s['available'] for s in ctx['usable'] if s['sku']=='0001')==1570
def test_surplus_never_allocatable(ctx):
    g=group(ctx,'0002')
    assert g['盘盈待落实']==30 and g['待落实扣减']==0
    assert sum(s['available'] for s in ctx['usable'] if s['sku']=='0002')==1800
def test_original_count_records_kept(ctx):
    counts=ctx['stages']['4']['counts']
    assert len(counts)==3
    assert next(c for c in counts if c['盘点单']=='C0001')['覆盖']=='是'
    assert next(c for c in counts if c['盘点单']=='C0003')['覆盖']=='否'
def test_rerun_never_double_deducts(client,raw):
    first=client.post('/api/run',json={'csv':raw}).get_json();again=client.post('/api/run',json={'csv':raw}).get_json()
    assert again['reused'] is True
    row=next(r for r in first['stages']['4']['rows'] if r['批号']=='B0020')
    assert row['待落实扣减']==190 and row['盘后可用']==0
def test_duplicate_count_row_applied_once(raw):
    result=calculate(raw+'C0001,count,0001,,1900,,,,中央仓,,2026-11-15,1,pending\n')
    assert result['duplicates']==2
    assert group(result,'0001')['待落实扣减']==280
def test_conflicting_count_isolated(raw):
    result=calculate(raw+'C0001,count,0001,,1500,,,,中央仓,,2026-11-15,1,pending\n')
    assert any(q['原因码']=='CONFLICT' and q.get('record')=='C0001' for q in result['quarantine'])
    assert group(result,'0001')['实盘总数']==1890
def test_count_row_with_lot_isolated(raw):
    result=calculate(raw+'C0099,count,0001,B0001,100,,,,中央仓,,2026-11-18,1,pending\n')
    assert any(q['原因码']=='LOT' for q in result['quarantine'])
def test_count_row_bad_status_isolated(raw):
    result=calculate(raw+'C0099,count,0001,,100,,,,中央仓,,2026-11-18,1,normal\n')
    assert any(q['原因码']=='STATUS' for q in result['quarantine'])
def test_recall_recomputes_holds(raw):
    result=calculate(raw+'S0903,stock,0001,B0022,210,0,5,2026-12-03,中央仓,0,2026-11-20,1,recall\n')
    g=group(result,'0001')
    assert g['失效批扣减']==410 and g['账面总数']==1770
    assert g['账面总数']-g['待落实扣减']-g['已落实扣减']-g['未分摊']==g['有效实盘']
    assert all(s['lot']!='B0022' for s in result['usable'])
def test_expired_batch_recomputes_holds(raw):
    result=calculate(raw+'S0904,stock,0002,B0904,50,0,5,2026-11-10,中央仓,0,2026-11-20,1,normal\n')
    g=group(result,'0002')
    assert g['失效批扣减']==50 and g['有效实盘']==1900 and g['待落实扣减']==20
def test_shortage_beyond_sellable_is_unallocated(raw):
    result=calculate(raw+'C0098,count,0002,,10,,,,中央仓,,2026-11-18,1,pending\n')
    g=group(result,'0002')
    assert g['未分摊']==140 and g['盘后可用']==0 and g['盘盈待落实']==30
def test_surplus_releases_pending_holds_farthest_first():
    def stock(lot,expiry,qty): return {'sku':'s','store':'w','lot':lot,'expiry':expiry,'qty_n':qty,'frozen_n':0,'pack_n':1,'available':qty,'stock_key':'s:'+lot}
    ctx={'usable':[stock('L1','2026-12-01',100),stock('L2','2026-12-05',100)],'quarantine':[],
         'counts':[{'store':'w','sku':'s','record':'C1','arrival':'2026-11-10','qty_n':150,'status':'pending'},
                   {'store':'w','sku':'s','record':'C2','arrival':'2026-11-12','qty_n':180,'status':'pending'}]}
    apply(ctx)
    assert {s['lot']:s['hold_pending'] for s in ctx['usable']}=={'L1':20,'L2':0}
def test_allocation_respects_post_count_available(ctx):
    from collections import Counter
    shipped=Counter()
    for a in ctx['allocations']: shipped[a['批号']]+=a['调拨数量']
    for s in ctx['usable']: assert shipped[s['lot']]<=s['available']
def test_reconcile_shows_count_row(ctx):
    row=next(r for r in ctx['stages']['7']['rows'] if r['项目']=='盘点对平(可售)')
    assert row['发出']==290 and row['差额']==0
def test_page_shows_pre_post_pending(client):
    client.post('/api/run',json={})
    page=client.get('/work/4').data.decode()
    assert '盘前可用' in page and '盘后可用' in page and '待落实' in page and '盘点单记录' in page
def test_module_endpoint(client):
    response=client.post('/api/m4',json={})
    assert response.status_code==200 and response.get_json()['stage']==4
def test_evidence_keeps_count_records(client):
    client.post('/api/run',json={})
    text=client.get('/api/evidence.csv').data.decode('utf-8-sig')
    assert 'C0001' in text and '盘点单' in text
