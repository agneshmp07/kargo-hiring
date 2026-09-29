import json, random, statistics as st
P = json.load(open(__import__("sys").argv[1] if len(__import__("sys").argv)>1 else "rubric_params.json"))
H = P["hire_coding"]; OUT = H["_outcome"]; POS=["P1","P2","P3","P4","P5"]; NEG=["N1","N2"]

def derive(names):
    E=[n for n in names if OUT[n]=="E"]; O=[n for n in names if OUT[n]!="E"]
    lift={v:(sum(H[v][n] for n in E)/len(E) - (sum(H[v][n] for n in O)/len(O) if O else 0)) for v in POS+NEG}
    pos_sum=sum(max(lift[v],0) for v in POS); unit=100/pos_sum
    w={v:max(lift[v],0)*unit for v in POS}
    w.update({v:lift[v]*unit*P["negative_collinearity_discount"] for v in NEG})  # negative lifts -> penalties
    return lift,w

def layer_a(c,w):
    x=dict(c["A"])
    if x.get("N1",0) and P["rules"]["n1_caps_p1_at_zero"]: x["P1"]=0
    return max(0, sum(w[v]*x.get(v,0) for v in POS) + sum(w[v]*x.get(v,0) for v in NEG))

def score(c,w,role,bands=None):
    bands=bands or P["bands"]; lb=P["layer_b"][role]
    B=sum(lb["weights"][k]*c["B"][role].get(k,0) for k in lb["weights"])
    A=layer_a(c,w); final=P["blend"]["layer_a_pattern"]*A+P["blend"]["layer_b_role"]*B
    lo,hi=lb["gate_years_pm"]; y=c["pm_years"]; tol=P["rules"]["gate_tolerance_years"]
    gate="pass" if lo<=y<=hi else ("near" if lo-tol<=y<=hi+tol else "fail")
    band="Strong" if final>=bands["strong"] else "Borderline" if final>=bands["borderline"] else "Not a fit"
    why=[]
    if gate=="fail": band="Not a fit"; why.append("gate fail")
    if gate=="near" and band=="Strong": band="Borderline"; why.append("gate near")
    rank={"Not a fit":0,"Borderline":1,"Strong":2}
    if c["A"].get("P1",0)>=P["rules"].get("p1_floor_min",1) and not c["A"].get("N1") and rank[band]<1: band="Borderline"; why.append("P1 floor")
    if c.get("low_conf") and rank[band]<1: band="Borderline"; why.append("low-conf floor")
    if B>=P["rules"].get("role_rescue_B",999) and rank[band]<1 and gate!="fail": band="Borderline"; why.append("role rescue")
    return round(A,1),round(B,1),round(final,1),gate,band,why

names=list(OUT)
lift,W=derive(names)
print("=== BASE WEIGHTS"); [print(f"{v}: lift {lift[v]:+.2f}  pts {W[v]:+.1f}") for v in POS+NEG]

print("\n=== BACK-TEST ON HIRES (Layer A only; circular by construction)")
for n in names:
    c={"A":{v:H[v][n] for v in POS+NEG}}
    print(f"{n:9s} {OUT[n]}  A={layer_a(c,W):5.1f}")

print("\n=== LEAVE-ONE-OUT WEIGHT STABILITY")
rows={v:[] for v in POS+NEG}
for d in names:
    _,w=derive([n for n in names if n!=d])
    print(f"drop {d:9s} " + "  ".join(f"{v}:{w[v]:+5.1f}" for v in POS+NEG))
    for v in POS+NEG: rows[v].append(w[v])
print("range   " + "  ".join(f"{v}:{min(rows[v]):+.0f}..{max(rows[v]):+.0f}" for v in POS+NEG))

C=json.load(open("synthetic_candidates.json"))
print("\n=== SYNTHETIC EDGE CASES (base params)")
base={}
for c in C:
    for role in c["roles"]:
        r=score(c,W,role); base[(c["id"],role)]=r
        print(f"{c['id']:4s} {role:3s} {c['label'][:44]:44s} A={r[0]:5.1f} B={r[1]:5.1f} F={r[2]:5.1f} gate={r[3]:4s} -> {r[4]:10s} {','.join(r[5])}  | expected {c['expect'][role]}")

print("\n=== MONTE CARLO: weights ±30%, thresholds ±5, 2000 runs -> band flip rate")
random.seed(7); flips={k:0 for k in base}; N=2000
for _ in range(N):
    w={v:W[v]*random.uniform(.7,1.3) for v in POS+NEG}
    s=sum(w[v] for v in POS); w={v:(w[v]*100/s if v in POS else w[v]) for v in w}
    b={"strong":65+random.uniform(-5,5),"borderline":45+random.uniform(-5,5)}
    for c in C:
        for role in c["roles"]:
            if score(c,w,role,b)[4]!=base[(c["id"],role)][4]: flips[(c["id"],role)]+=1
for k,v in flips.items(): print(f"{k[0]:4s} {k[1]:3s} flip {100*v/N:5.1f}%")

print("\n=== CODING-NOISE TEST: AI mis-reads each variable +/-0.5 with p=0.2, 2000 runs")
random.seed(11); cf={k:0 for k in base}
for _ in range(N):
    for c in C:
        cc=json.loads(json.dumps(c))
        for v in POS+NEG:
            if random.random()<0.2:
                cc["A"][v]=min(1,max(0,cc["A"].get(v,0)+random.choice([-.5,.5])))
        for role in c["roles"]:
            if score(cc,W,role)[4]!=base[(c["id"],role)][4]: cf[(c["id"],role)]+=1
for k,v in cf.items(): print(f"{k[0]:4s} {k[1]:3s} flip {100*v/N:5.1f}%")

print("\n=== FIX VARIANT: graded outcomes (E=1, M=0.5, B=0) + blend 60/40")
G={"E":1,"M":.5,"B":0}
def derive_graded():
    lift={}
    for v in POS+NEG:
        on=[G[OUT[n]] for n in names if H[v][n]>=1]; off=[G[OUT[n]] for n in names if H[v][n]<1]
        lift[v]=(st.mean(on) if on else 0)-(st.mean(off) if off else 0)
    unit=100/sum(max(lift[v],0) for v in POS)
    w={v:max(lift[v],0)*unit for v in POS}; w.update({v:lift[v]*unit*.5 if lift[v]<0 else 0 for v in NEG}); return lift,w
gl,GW=derive_graded()
print("  ".join(f"{v}:{GW[v]:+.1f}" for v in POS+NEG))
P["blend"]={"layer_a_pattern":.6,"layer_b_role":.4}
for c in C:
    for role in c["roles"]:
        r=score(c,GW,role); b0=base[(c["id"],role)]
        mark="  <-- changed" if r[4]!=b0[4] else ""
        print(f"{c['id']:4s} {role:3s} F {b0[2]:5.1f}->{r[2]:5.1f}  {b0[4]:10s}->{r[4]:10s}{mark}")
