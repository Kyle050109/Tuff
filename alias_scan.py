import json, sys
sys.path.insert(0,__import__('os').path.dirname(__import__('os').path.abspath(__file__)))
from geolib import read_jsonl, dedupe_last
# 繁体对照（只覆盖本项目品牌用字；含港台常见异体）
T = {'奥':'奧','华':'華','荣':'榮','胜':'勝','仕':'仕','乐':'樂','吧':'吧','斯':'斯','摩':'摩','哒':'噠','宫':'宮','和':'和','尔':'爾',
     '汤':'湯','悦':'悅','崎':'崎','熹':'熹','户':'戶','极':'極','泉':'泉','源':'源','觅':'覓','光':'光','萌':'萌','灯':'燈',
     '纽':'紐','立':'立','索':'索','朗':'朗','特':'特','宙':'宙','雅':'雅','普':'普','初':'初','飞':'飛','利':'利','浦':'浦',
     '欧':'歐','莱':'萊','雅':'雅','康':'康','铂':'鉑','倍':'倍','轻':'輕','松':'松','听':'聽','研':'研','花':'花','至':'至',
     '可':'可','思':'思','美':'美','裹':'裹','水':'水','驰':'馳','傲':'傲','西':'西','屋':'屋','芝':'芝','迪':'迪','佳':'佳',
     '仁':'仁','本':'本','博':'博','克':'克','海':'海','稻':'稻','田':'田','阿':'阿','奇':'奇','拉':'拉','江':'江','大':'大','排':'排'}
def trad(s): return ''.join(T.get(ch,ch) for ch in s)
from pathlib import Path; P=str(Path(__file__).resolve().parent)
cats={'beauty':('meirongyi_final_v2','samples','ds_beauty_baseline'),'chair':('anmo_chair_v1','chair_samples','ds_chair_baseline'),'spa':('shenzhen_spa_v1','spa_samples','ds_spa_baseline')}
out={}
for cat,(pf,df,dsf) in cats.items():
    meta=json.load(open(f'{P}/prompts/{pf}.json',encoding='utf-8'))['meta']
    rows=dedupe_last(read_jsonl(f'{P}/data/{df}.jsonl'))
    R=[r for q in read_jsonl(f'{P}/data/deepseek/{dsf}.jsonl') for r in q['results']]
    names=list(dict.fromkeys(meta['own_brand']+meta['competitors']))
    print(f'== {cat}')
    out[cat]={}
    for n in names:
        t=trad(n)
        if t==n: continue
        # rows hit only by trad
        db_ans=sum(1 for r in rows if t in (r.get('answer') or '') and n not in (r.get('answer') or ''))
        db_cit=sum(1 for r in rows if any(t in (c.get('title') or '') for c in r.get('citations') or []))
        db_q=sum(1 for r in rows if t in r['text'])
        ds=sum(1 for r in R if t in (r.get('title') or '')+' '+(r.get('snippet') or ''))
        out[cat][n]=t
        flag='  ←' if (db_ans or db_cit or ds or db_q) else ''
        print(f'  {n}→{t}: 题面 {db_q} 豆包答案仅繁 {db_ans} 豆包引用 {db_cit} DS条 {ds}{flag}')
json.dump(out,open('out/trad_map.json','w'),ensure_ascii=False,indent=1)
