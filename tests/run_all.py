"""Run all engine tests. Exits non-zero if any fail."""
import sys, os, subprocess, glob

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

def main():
    tests = sorted(glob.glob(os.path.join(HERE, 'test_*.py')))
    total_pass = total = 0
    for t in tests:
        r = subprocess.run([sys.executable, t], capture_output=True, text=True,
                           env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}, cwd=ROOT)
        # parse "X/Y ... tests passed" or "X/Y ... passed"
        out = (r.stdout or '') + (r.stderr or '')
        import re
        m = re.search(r'(\d+)/(\d+)\s+\S*\s*tests?\s*passed', out)
        print(f'--- {os.path.basename(t)} ---')
        tail = out.strip().splitlines()[-2:] if out.strip() else ['(no output)']
        for line in tail:
            print('  ' + line)
        if m:
            total_pass += int(m.group(1)); total += int(m.group(2))
        if r.returncode != 0:
            print('  [non-zero exit]')
    print(f'\n==== TOTAL: {total_pass}/{total} tests passed ====')
    sys.exit(0 if total_pass == total and total > 0 else 1)

if __name__ == '__main__':
    main()
