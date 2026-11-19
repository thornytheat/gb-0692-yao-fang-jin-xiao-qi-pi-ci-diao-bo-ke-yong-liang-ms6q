STATUS_LABEL={'pending':'待落实','confirmed':'已落实'}
def invalidated(ctx):
    # 召回/过期批已离架：同一批号取最大记录量，按门店+药品汇总，从实盘中扣减。
    lots={}
    for q in ctx['quarantine']:
        if q.get('原因码') in ('RECALL','EXPIRED') and isinstance(q.get('qty_n'),int):
            key=(q.get('store',''),q.get('sku',''),q.get('lot',''))
            lots[key]=max(lots.get(key,0),q['qty_n'])
    totals={}
    for (store,sku,_lot),qty in lots.items():
        totals[(store,sku)]=totals.get((store,sku),0)+qty
    return totals
def apply(ctx):
    for s in ctx['usable']:
        s['available_pre']=s['available'];s['hold_pending']=0;s['hold_confirmed']=0
    groups={}
    for c in ctx.get('counts',[]): groups.setdefault((c['store'],c['sku']),[]).append(c)
    invalid=invalidated(ctx)
    batch_rows=[];group_rows=[];count_rows=[]
    totals={'pending':0,'confirmed':0,'surplus_pending':0,'surplus_confirmed':0,'unallocated':0}
    for (store,sku) in sorted(groups):
        counts=sorted(groups[(store,sku)],key=lambda c:(c['arrival'],c['record']))
        batches=sorted([s for s in ctx['usable'] if s['store']==store and s['sku']==sku],key=lambda s:(s['expiry'],s['lot']))
        book=sum(s['qty_n'] for s in batches);lost=invalid.get((store,sku),0)
        sellable={s['stock_key']:s['qty_n']-s['frozen_n'] for s in batches}
        hold={s['stock_key']:{'pending':0,'confirmed':0} for s in batches}
        surplus={'pending':0,'confirmed':0};unallocated=0;baseline=book+lost
        for i,c in enumerate(counts):
            diff=c['qty_n']-baseline
            if diff<0:
                # 盘亏未落实：按效期从近到远挂待落实扣减，与FEFO消耗顺序一致，保证不超发。
                need=-diff
                for s in batches:
                    key=s['stock_key'];room=sellable[key]-hold[key]['pending']-hold[key]['confirmed']
                    take=min(room,need)
                    if take: hold[key][c['status']]+=take;need-=take
                    if not need: break
                unallocated+=need
            elif diff>0:
                # 盘盈先释放待落实扣减（自远效期回放），余量挂盘盈，不推断未知批号、不入可拨。
                need=diff
                for s in reversed(batches):
                    key=s['stock_key'];release=min(hold[key]['pending'],need)
                    if release: hold[key]['pending']-=release;need-=release
                    if not need: break
                surplus[c['status']]+=need
            count_rows.append({'盘点单':c['record'],'门店':store,'药品':sku,'盘点日':c['arrival'],'状态':STATUS_LABEL[c['status']],'实盘':c['qty_n'],'差异':diff,'覆盖':'否' if i==len(counts)-1 else '是'})
            baseline=c['qty_n']
        for s in batches:
            key=s['stock_key'];h=hold[key]
            s['hold_pending']=h['pending'];s['hold_confirmed']=h['confirmed']
            post=sellable[key]-h['pending']-h['confirmed']
            s['available']=post//s['pack_n']*s['pack_n']
            batch_rows.append({'门店':store,'药品':sku,'批号':s['lot'],'到期日':s['expiry'],'盘前可用':s['available_pre'],'待落实扣减':h['pending'],'已落实扣减':h['confirmed'],'盘后可用':s['available']})
        pending=sum(h['pending'] for h in hold.values());confirmed=sum(h['confirmed'] for h in hold.values())
        group_rows.append({'门店':store,'药品':sku,'账面总数':book,'失效批扣减':lost,'实盘总数':counts[-1]['qty_n'],'有效实盘':counts[-1]['qty_n']-lost,'待落实扣减':pending,'已落实扣减':confirmed,'盘盈待落实':surplus['pending'],'盘盈已落实':surplus['confirmed'],'未分摊':unallocated,'盘后可用':sum(s['available'] for s in batches)})
        totals['pending']+=pending;totals['confirmed']+=confirmed;totals['surplus_pending']+=surplus['pending'];totals['surplus_confirmed']+=surplus['confirmed'];totals['unallocated']+=unallocated
    return {'rows':batch_rows,'groups':group_rows,'counts':count_rows,'metrics':[['盘点单',len(count_rows),'单'],['待落实扣减',totals['pending'],'件'],['盘后可用',sum(g['盘后可用'] for g in group_rows),'件']]}
