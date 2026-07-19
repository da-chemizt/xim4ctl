#!/usr/bin/env python3
"""Extract consecutive 0x15 config writes from a capture and diff them (ignoring cksum@0-3 & seq@6-7).
Each single-value A/B save -> shows exactly which frame offset(s) moved. Usage: ab_diff.py <capture.btsnoop>"""
import sys, subprocess, os
HERE=os.path.dirname(os.path.abspath(__file__))
def writes(cap):
    out=subprocess.check_output(['python3',os.path.join(HERE,'rfcomm_decode.py'),cap,'--cmd','0015','--full'],text=True)
    frames=[]
    for line in out.splitlines():
        p=line.split()
        if len(p)>=5 and p[0]=='>XIM':
            frames.append(bytes.fromhex(p[4]))
    # dedupe consecutive identical (ignoring cksum+seq)
    def key(f): return f[8:]           # skip cksum(4)+cmd(2)+seq(2)
    uniq=[]
    for f in frames:
        if not uniq or key(uniq[-1])!=key(f): uniq.append(f)
    return uniq

def main(cap):
    u=writes(cap)
    print(f"{len(u)} distinct config states captured (of the 0x15 writes)")
    import xim4_config as X
    for i in range(1,len(u)):
        a,b=u[i-1],u[i]
        diffs=[(o,a[o],b[o]) for o in range(min(len(a),len(b))) if a[o]!=b[o] and o not in (0,1,2,3,6,7)]
        if not diffs: continue
        na=X.parse(a).get('name',''); nb=X.parse(b).get('name','')
        print(f"\n--- save #{i}  ({na} -> {nb}) : {len(diffs)} byte(s) changed ---")
        # group contiguous
        runs=[];
        for o,x,y in diffs:
            if runs and o==runs[-1][-1]+1: runs[-1].append(o)
            else: runs.append([o])
        for r in runs:
            oa=bytes(a[o] for o in r).hex(); ob=bytes(b[o] for o in r).hex()
            base='setting+0x%x'%(r[0]-66) if r[0]>=66 else 'cfghdr'
            print(f"   offset {r[0]}..{r[-1]} ({base}): {oa} -> {ob}")

if __name__=='__main__':
    main(sys.argv[1])
