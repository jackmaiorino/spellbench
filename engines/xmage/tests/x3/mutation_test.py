"""Mutation test for check_observations.py: each fault injected into a copy of one game must be caught."""
import copy, gzip, json, sys, tempfile
from pathlib import Path
import check_observations as co

src = Path(sys.argv[1])
lines = [json.loads(l) for l in gzip.open(src, 'rt', encoding='utf-8')]

def run(name, mutate):
    ls = copy.deepcopy(lines)
    ok = mutate(ls)
    if not ok:
        print(f"{name}: no site to mutate"); return
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / src.name
        with gzip.open(p, 'wt', encoding='utf-8') as f:
            for l in ls: f.write(json.dumps(l) + '\n')
        r = co.check_game(p)
    rules = sorted(k for k in r['stats'] if k.startswith('fail_'))
    print(f"{name}: caught {rules}" if rules else f"{name}: NOT CAUGHT")

def body(ls): return ls[1:-1]

def opp_hand(ls):
    for l in body(ls):
        o = l['observations']['p0']; o['players'][1]['hand'] = []; return True
def shared_id(ls):
    for l in body(ls):
        a0 = {a['key']: a['object_id'] for a in l['audit']['p0'] if not a['look']}
        for a in l['audit']['p1']:
            if a['key'] in a0 and not a['look']:
                old, new = a['object_id'], a0[a['key']]
                s = json.dumps(l['observations']['p1']).replace(old, new)
                l['observations']['p1'] = json.loads(s); a['object_id'] = new; return True
def leak(ls):
    for l in body(ls):
        names = l['audit']['leak_names']['p0']
        bf = l['observations']['p0']['players'][0]['graveyard']
        if names and bf:
            bf[0]['card_name'] = names[0]; bf[0]['full_name'] = None; return True
def face_down(ls):
    for l in body(ls):
        for e in l['audit']['face_down']:
            if e['zone'] == 'battlefield':
                viewer = 'p1' if e['visible_to'] == 'p0' else 'p0'
                ids = {a['key']: a['object_id'] for a in l['audit'][viewer]}
                for p in l['observations'][viewer]['players']:
                    for r in p['battlefield']:
                        if r['object_id'] == ids.get(e['key']):
                            r['card_name'] = 'Flourishing Bloom-Kin'; return True
def look_reuse(ls):
    for v in ('p0', 'p1'):
        first = None
        for l in body(ls):
            for a in l['audit'][v]:
                if a['look']:
                    if first is None:
                        first = (a['object_id'], l['i'])
                        continue
                    if l['i'] > first[1] + 1 and a['object_id'] != first[0]:
                        old = a['object_id']
                        l['observations'][v] = json.loads(json.dumps(l['observations'][v]).replace(old, first[0]))
                        l['option_refs'] = json.loads(json.dumps(l['option_refs']).replace(old, first[0]))
                        a['object_id'] = first[0]
                        return True


def library_record(ls):
    for l in body(ls):
        g = l['observations']['p0']['players'][0]['graveyard']
        if g: g[0]['zone'] = 'library'; return True
def flag_null(ls):
    body(ls)[5]['observations']['p1']['players'][0]['poison'] = None; return True
def zone_change_same_id(ls):
    for l in body(ls):
        for a in l['audit']['p0']:
            if a['zone'] == 'graveyard' and not a['look']:
                uuid = a['key'].rsplit(':z', 1)[0]
                for l2 in body(ls):
                    if l2['i'] >= l['i']: break
                    for b in l2['audit']['p0']:
                        if b['key'].startswith(uuid + ':z') and b['key'] != a['key']:
                            old = a['object_id']
                            l['observations']['p0'] = json.loads(json.dumps(l['observations']['p0']).replace(old, b['object_id']))
                            a['object_id'] = b['object_id']; return True

for name, m in [("opponent hand shown", opp_hand), ("id shared across viewers", shared_id),
                ("hidden name leaked", leak), ("face-down named to non-controller", face_down),
                ("look id reused after a gap", look_reuse), ("record in library zone", library_record),
                ("optional flag broken", flag_null), ("id kept across a zone change", zone_change_same_id)]:
    run(name, m)
