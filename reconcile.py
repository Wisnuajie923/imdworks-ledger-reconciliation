"""Offline event fold; deliberately independent of model.py."""
import argparse
import json
import re
from pathlib import Path

class Failure(ValueError):
    pass

def require(ok, message):
    if not ok:
        raise Failure(message)

def fields(value, names, path):
    require(type(value) is dict and set(value)==set(names), f'{path}: fields must be {sorted(names)}')

def uint(value, bits, path):
    require(type(value) is int and 0 <= value < 2**bits, f'{path}: expected uint{bits}, got {value!r}')

def label(value, path):
    require(type(value) is str and re.fullmatch(r'(creator|winner|recipient|donor|attacker)-[0-9]+|synthetic-escrow', value), f'{path}: invalid synthetic address label')

def hash32(value, path):
    require(type(value) is str and re.fullmatch(r'0x[0-9a-f]{64}',value), f'{path}: invalid bytes32')

def strict_json(path):
    def pairs(items):
        out={}
        for k,v in items:
            require(k not in out, f'JSON duplicate field {k}')
            out[k]=v
        return out
    return json.loads(Path(path).read_text(), object_pairs_hook=pairs,
                      parse_constant=lambda v: (_ for _ in ()).throw(Failure(f'JSON nonfinite {v}')))

def reconcile(f, abi):
    fields(f, ['events','snapshot','anchor','headers'], 'fixture')
    fields(f['anchor'], ['number','hash'], 'anchor')
    anchor=f['anchor']; uint(anchor['number'],64,'anchor.number'); hash32(anchor['hash'],'anchor.hash')
    require(type(f['headers']) is dict, 'headers: expected object')
    require(f['headers'].get(str(anchor['number']))==anchor['hash'], 'anchor.hash: canonical header mismatch')
    for n,h in f['headers'].items():
        require(type(n) is str and n.isdigit() and str(int(n))==n, 'headers: noncanonical number')
        uint(int(n),64,'header.number'); hash32(h,'header.hash')
    s=f['snapshot']
    fields(s, ['block_number','block_hash','locked','credits','total_locked','total_claimable','liabilities','token_balance'], 'snapshot')
    uint(s['block_number'],64,'snapshot.block_number'); hash32(s['block_hash'],'snapshot.block_hash')
    require(s['block_number']==anchor['number'], f"snapshot.block_number: expected {anchor['number']}, got {s['block_number']}")
    require(s['block_hash']==anchor['hash'], 'snapshot.block_hash: anchor mismatch')
    for key in ['total_locked','total_claimable','liabilities','token_balance']: uint(s[key],256,'snapshot.'+key)
    for key in ['locked','credits']:
        require(type(s[key]) is dict, 'snapshot.'+key+': expected object')
        for k,v in s[key].items():
            if key=='credits': label(k,'snapshot.credit wallet')
            else: require(type(k) is str and k.isdigit() and str(int(k))==k, 'snapshot.locked: invalid bounty id')
            uint(v,256,f'snapshot.{key}[{k}]')
    schemas={e['name']:e['inputs'] for e in abi if e.get('type')=='event'}
    schemas['Transfer']=[dict(name='from',type='address'),dict(name='to',type='address'),dict(name='value',type='uint256')]
    supported={'BountyCreated','BountyAwarded','BountyRefunded','Withdrawn','Transfer'}
    require(type(f['events']) is list,'events: expected array')
    seen=set(); positions=set(); last=(-1,-1); locked={}; creators={}; credits={}; balance=0
    for i,e in enumerate(f['events']):
        p=f'events[{i}]'
        fields(e,['event','args','actor','source','block_number','block_hash','log_index','tx_hash'],p)
        name=e['event']; require(type(name) is str and name in supported and name in schemas,p+': unsupported canonical event')
        uint(e['block_number'],64,p+'.block_number'); uint(e['log_index'],64,p+'.log_index')
        require(0<e['block_number']<=anchor['number'],p+'.block_number: outside fixed block range')
        hash32(e['block_hash'],p+'.block_hash'); hash32(e['tx_hash'],p+'.tx_hash')
        require(f['headers'].get(str(e['block_number']))==e['block_hash'],p+'.block_hash: canonical header mismatch')
        identity=(e['tx_hash'],e['log_index']); position=(e['block_number'],e['log_index'])
        require(identity not in seen and position not in positions,p+': duplicate receipt/log identity')
        require(position>last,p+': noncanonical event order'); seen.add(identity); positions.add(position); last=position
        require(e['source']==('synthetic-token' if name=='Transfer' else 'synthetic-escrow'),p+'.source: unauthorized emitter')
        label(e['actor'],p+'.actor'); a=e['args']; fields(a,[x['name'] for x in schemas[name]],p+'.args')
        for spec in schemas[name]:
            v=a[spec['name']]; t=spec['type']; q=p+'.args.'+spec['name']
            if t.startswith('uint'): uint(v,int(t[4:]),q)
            elif t=='address': label(v,q)
            elif t=='bytes32': hash32(v,q)
            elif t=='string': require(type(v) is str,q+': expected string')
        if name=='Transfer':
            require(e['actor']==a['from'] or a['from']=='synthetic-escrow',p+': unauthorized token sender')
            if a['to']=='synthetic-escrow': balance+=a['value']
            if a['from']=='synthetic-escrow': balance-=a['value']
            require(balance>=0,p+': token balance underflow')
        elif name=='BountyCreated':
            bid=str(a['bountyId']); require(bid not in locked,p+': duplicate bounty creation')
            require(e['actor']==a['creator'],p+': unauthorized creator')
            require(a['reward']>0,p+': zero reward')
            locked[bid]=a['reward']; creators[bid]=a['creator']
        elif name in {'BountyAwarded','BountyRefunded'}:
            bid=str(a['bountyId']); require(bid in locked and locked[bid]>0,p+': unknown or settled bounty')
            require(e['actor']==creators[bid],p+': unauthorized settlement actor')
            require(a['amount']==locked[bid],p+f': settlement amount expected {locked[bid]}, got {a["amount"]}')
            if name=='BountyRefunded':
                require(a['creator']==creators[bid],p+': unauthorized refund beneficiary')
                require(a['status']==3,p+': unsupported local refund status')
            wallet=a['winner'] if name=='BountyAwarded' else a['creator']
            credits[wallet]=credits.get(wallet,0)+a['amount']; locked[bid]=0
        elif name=='Withdrawn':
            wallet=a['account']; require(e['actor']==wallet,p+': unauthorized withdrawal actor')
            require(a['amount']>0 and credits.get(wallet,0)==a['amount'],p+': withdrawal does not consume full existing credit')
            credits[wallet]=0
    calculated=dict(locked=locked,credits=credits,total_locked=sum(locked.values()),total_claimable=sum(credits.values()),token_balance=balance)
    calculated['liabilities']=calculated['total_locked']+calculated['total_claimable']
    errors=[]
    for key in ['locked','credits']:
        for k in sorted(set(calculated[key])|set(s[key])):
            if calculated[key].get(k)!=s[key].get(k): errors.append(f'{key}[{k}]: events={calculated[key].get(k)!r}, snapshot={s[key].get(k)!r}')
    for key in ['total_locked','total_claimable','liabilities','token_balance']:
        if calculated[key]!=s[key]: errors.append(f'{key}: events={calculated[key]}, snapshot={s[key]}')
    require(not errors,'; '.join(errors))
    require(balance>=calculated['liabilities'],'insolvent: token balance below liabilities')
    calculated['surplus']=balance-calculated['liabilities']
    return calculated

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('fixture'); parser.add_argument('--abi',default=str(Path(__file__).with_name('escrow-abi.json')))
    args=parser.parse_args()
    try:
        print(json.dumps({'ok':True,'result':reconcile(strict_json(args.fixture),strict_json(args.abi))},sort_keys=True)); return 0
    except (Failure, ValueError, OSError, TypeError, KeyError) as exc:
        print(json.dumps({'ok':False,'error':str(exc)},sort_keys=True)); return 2

if __name__=='__main__':
    raise SystemExit(main())
