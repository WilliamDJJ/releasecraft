"""Execute the UI script with Node's VM and a minimal deterministic DOM harness."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class ScriptTests(unittest.TestCase):
    def test_ui_flow_and_safe_rendering(self):
        if not shutil.which("node"):
            self.skipTest("Node unavailable: JS interaction harness not run")
        import releasecraft

        html = (
            Path(releasecraft.__file__).with_name("ui.html").read_text(encoding="utf-8")
        )
        script = html.split("<script>")[1].split("</script>")[0]
        harness = r"""
const vm=require('node:vm');const assert=require('node:assert/strict');
class El {constructor(){this.value='';this.textContent='';this.disabled=false;this.children=[];}replaceChildren(){this.children=[];}append(x){this.children.push(x);}}
const els={};for(const id of ['analyze','build','policy','filter','files','status','summary','blockers'])els[id]=new El();els.policy.value='{}';
let calls=[];const plan={status:'PLANNED',plan_sha256:'a'.repeat(64),files:[{path:'<script>unsafe</script>.py',state:'INCLUDE',reason:'source'}],blockers:[]};
let data=plan;let storage={};const context={document:{getElementById:id=>els[id],createElement:()=>new El()},location:{hash:'#test-session',pathname:'/',port:'8765'},history:{replaceState(){}},sessionStorage:{getItem:k=>storage[k],setItem:(k,v)=>storage[k]=v},fetch:async(path,opts)=>{calls.push({path,opts});return {ok:true,json:async()=>data}}};
vm.createContext(context);vm.runInContext(SOURCE,context);
(async()=>{await els.analyze.onclick();assert.equal(els.status.textContent,'PLANNED');assert.equal(els.build.disabled,false);assert.equal(els.files.children[0].children[0].textContent,'<script>unsafe</script>.py');assert.equal(calls[0].opts.headers['X-Releasecraft-Token'],'test-session');
els.filter.value='no-match';els.filter.oninput();assert.equal(els.files.children.length,0);
data={status:'CANDIDATE',archive_sha256:'b'};await els.build.onclick();assert.equal(els.status.textContent,'CANDIDATE');assert.equal(els.build.disabled,true);
els.policy.value='{bad';await els.analyze.onclick();assert.equal(els.analyze.disabled,false);assert.equal(els.build.disabled,true);
assert.equal(storage['releasecraft:8765'],'test-session');console.log('UI interaction harness passed');})().catch(e=>{console.error(e);process.exitCode=1});
""".replace("SOURCE", json.dumps(script))
        with tempfile.TemporaryDirectory() as d:
            file = Path(d) / "ui-test.cjs"
            file.write_text(harness, encoding="utf-8")
            result = subprocess.run(
                ["node", str(file)], capture_output=True, text=True, timeout=20
            )
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
