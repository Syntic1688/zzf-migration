"""Prüfung der Datenqualität (Anhang B): Zählwerte zu Konsistenz, Vollständigkeit und Genauigkeit.

Aufruf: python3 -I datenqualitaet.py <Ordner der Kopie>
"""
import sys, os, glob, re, collections, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline"))
from dbf import Tabelle
root = sys.argv[1]
def lade(m):
    out=[]
    for d in sorted(glob.glob(os.path.join(root,m))): out.extend(Tabelle(d).saetze())
    return out
T={'KUNDEN':'KUNDEN.DBF','WAREN':'WAREN.DBF','LIEFER':'LIEFER.DBF','FIFO':'FIFO.DBF'}
d={k:list(Tabelle(os.path.join(root,v)).saetze()) for k,v in T.items()}
d['LH'],d['LD']=lade('LIF/LH*.DBF'),lade('LIF/LD*.DBF')
d['EH'],d['ED']=lade('EIN/EH*.DBF'),lade('EIN/ED*.DBF')
e={}
# Felder je Tabelle
def felder(m):
    f=sorted(glob.glob(os.path.join(root,m)))[0]; return Tabelle(f).felder
fl={'KUNDEN':felder('KUNDEN.DBF'),'WAREN':felder('WAREN.DBF'),'LIEFER':felder('LIEFER.DBF'),'FIFO':felder('FIFO.DBF'),
    'LH':felder('LIF/LH*.DBF'),'LD':felder('LIF/LD*.DBF'),'EH':felder('EIN/EH*.DBF'),'ED':felder('EIN/ED*.DBF')}
e['felder']={k:{'anzahl':len(v),'typen':dict(collections.Counter(x[1] for x in v))} for k,v in fl.items()}
e['saetze']={k:len(v) for k,v in d.items()}
def leer(x): return x is None or (isinstance(x,str) and not x.strip()) or (isinstance(x,(int,float)) and x==0)
K,W,L,F,LH,LD,EH,ED=[d[k] for k in ['KUNDEN','WAREN','LIEFER','FIFO','LH','LD','EH','ED']]
knr=collections.Counter(s['NUM'] for s in K); wnr={s['NR'] for s in W}; lnr={s['NUM'] for s in L}
lhnr={s['LIFNR'] for s in LH}; ehnr={s.get('EINNR') for s in EH}
# Verknüpfungen
e['lh_kunde_gefunden']=round(100*sum(1 for s in LH if s['NUM'] in knr)/len(LH),1)
e['ld_ls_gefunden']=round(100*sum(1 for s in LD if s['LIFNR'] in lhnr)/len(LD),1)
e['ld_artikel_gefunden']=round(100*sum(1 for s in LD if s['NR'] in wnr)/len(LD),1)
e['ed_artikel_gefunden']=round(100*sum(1 for s in ED if s['NR'] in wnr)/len(ED),1)
e['fifo_artikel_gefunden']=round(100*sum(1 for s in F if s['NR'] in wnr)/len(F),1)
# fehlende Kunden
fk=collections.Counter(s['NUM'] for s in LH if s['NUM'] and s['NUM'] not in knr)
e['fehlende_kundennummern']=len(fk); e['fehlende_kunden_ls']=sum(fk.values())
e['ls_ohne_kundennummer']=sum(1 for s in LH if not s['NUM'])
e['fehlend_fuehrende_null']=sum(1 for n in fk if ('0'+n.strip()) in {x.strip() for x in knr} or n.strip().lstrip('0') in {x.strip().lstrip('0') for x in knr if x.strip()!=n.strip()})
fa=collections.Counter(s['NR'] for s in LD if s['NR'] not in wnr)
e['fehlende_artikel']=len(fa); e['fehlende_artikel_pos']=sum(fa.values())
last=max(s['DATUM'] for s in LD).strftime('%Y-%m')
e['fehlende_artikel_im_letzten_monat']=sum(1 for s in LD if s['NR'] in fa and s['DATUM'].strftime('%Y-%m')==last)
dopp={n for n,c in knr.items() if c>1}
e['doppelte_kundennummern']=len(dopp); e['ls_mit_doppelter_nummer']=sum(1 for s in LH if s['NUM'] in dopp)
# Bestand
fs=collections.defaultdict(float)
for s in F: fs[s['NR']]+=s['MENGE'] or 0
e['bestand_gleich']=sum(1 for s in W if abs((s['MENGE'] or 0)-fs.get(s['NR'],0))<0.001)
neg=[s for s in F if (s['MENGE'] or 0)<0]
e['lagerposten_negativ']=len(neg)
lpcol=[c for c in F[0].keys()]
e['fifo_felder']=lpcol
# Vollständigkeit
e['ek_fehlt']=sum(1 for s in W if leer(s.get('EK_EURO')))
e['gewicht_fehlt']=sum(1 for s in W if leer(s.get('WEIGHT')))
e['warengruppe_fehlt']=sum(1 for s in W if leer(s.get('WG_NR')))
e['eh_mit_lieferant']=sum(1 for s in EH if not leer(s.get('NUM')))
e['waren_gueltiger_lieferant']=sum(1 for s in W if s.get('LIEFNR') in lnr and not leer(s.get('LIEFNR')))
e['fifo_mit_lieferant']=sum(1 for s in F if not leer(s.get('LFNUM')))
ohne_name=[s for s in K if leer(s.get('WNAME')) and leer(s.get('CNAME'))]
lsk=collections.Counter(s['NUM'] for s in LH)
e['kunden_ohne_namen']=len(ohne_name); e['kunden_ohne_namen_mit_ls']=sum(1 for s in ohne_name if lsk[s['NUM']])
e['uid_kunden_mit_ls']=sum(1 for s in K if lsk[s['NUM']] and not leer(s.get('UID')))
eht=collections.Counter(s['EHT'] for s in W if not leer(s['EHT']))
e['einheiten_schreibweisen']=len(eht)
def norm(x): return re.sub(r'[\W_]+','',(x or '').lower())
g=collections.defaultdict(set)
for s in K:
    if norm(s['WNAME']): g[(norm(s['WNAME']),norm(s['ZIP']))].add(s['NUM'])
dub=[v for v in g.values() if len(v)>1]
e['dubletten_gruppen']=len(dub); e['dubletten_nummern']=sum(len(v) for v in dub)
e['dubletten_gruppen_mehrere_mit_ls']=sum(1 for v in dub if sum(1 for n in v if lsk[n])>1)
print(json.dumps(e,ensure_ascii=False,indent=1,default=str))
