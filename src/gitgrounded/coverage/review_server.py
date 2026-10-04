import json
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from gitgrounded.cases.model import Case, Expectation
from gitgrounded.coverage.suite_store import SuiteStore

PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GitGrounded review</title>
<style>
body{margin:0;font:14px/1.5 system-ui,sans-serif;background:#f7f7f5;color:#1b1d21}
@media (prefers-color-scheme:dark){body{background:#0f1115;color:#e6e7ea}.card{background:#171a21!important;border-color:#2a2f3a!important}textarea{background:#11141a;color:#e6e7ea}}
main{max-width:900px;margin:0 auto;padding:20px 16px 80px}
.card{background:#fff;border:1px solid #e3e3df;border-radius:10px;padding:14px;margin:10px 0}
.card.active{outline:3px solid #2b6cb0}
.meta{color:#6b7078;font-size:12px}
textarea{width:100%;min-height:70px;font:13px ui-monospace,monospace;border-radius:6px;border:1px solid #ccc;padding:6px;box-sizing:border-box}
button{border:1px solid #ccc;border-radius:6px;padding:4px 10px;margin-right:6px;cursor:pointer}
.done{opacity:.45}
.tag{display:inline-block;font-size:11px;padding:1px 6px;border-radius:999px;background:#e3e3df;color:#333;margin-right:4px}
header{position:sticky;top:0;background:inherit;padding:8px 0;border-bottom:1px solid #e3e3df}
</style></head><body><main>
<header><b>GitGrounded review</b> &middot; <span id="progress"></span> &middot; keys: j/k move, a accept, r reject, e edit, s save edit</header>
<div id="list"></div></main>
<script>
var cases=[],behaviors={},idx=0;
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;"}[c]})}
function render(){
  var html="";var done=0;
  cases.forEach(function(c,i){
    var b=behaviors[(c.behaviors||[])[0]]||{};
    if(c._state)done++;
    html+='<div class="card '+(i===idx?'active ':'')+(c._state?'done':'')+'" id="c'+i+'">'+
    '<div class="meta">'+esc(c.id)+' &middot; '+esc(c.origin)+(c.reviewed?' &middot; reviewed':'')+(c._state?' &middot; '+c._state:'')+'</div>'+
    '<div><b>Behavior:</b> '+esc(b.statement||'none')+'</div>'+
    (b.source_text?'<div class="meta">source: '+esc(b.source_text.slice(0,240))+'</div>':'')+
    '<div>'+Object.keys(c.cell||{}).map(function(k){return '<span class="tag">'+esc(k)+'='+esc(c.cell[k])+'</span>'}).join('')+'</div>'+
    '<p><b>Input:</b></p><textarea id="in'+i+'">'+esc(typeof c.input==="string"?c.input:JSON.stringify(c.input,null,1))+'</textarea>'+
    '<p><b>Expectations</b> (one per line, kind: text):</p><textarea id="ex'+i+'">'+esc((c.expectations||[]).map(function(e){return e.kind+": "+e.text}).join("\\n"))+'</textarea>'+
    '<p><button onclick="act('+i+',\\'accept\\')">accept (a)</button><button onclick="act('+i+',\\'reject\\')">reject (r)</button><button onclick="act('+i+',\\'edit\\')">save edit (s)</button></p></div>';
  });
  document.getElementById("list").innerHTML=html;
  document.getElementById("progress").textContent=done+" / "+cases.length+" decided";
  var el=document.getElementById("c"+idx);if(el)el.scrollIntoView({block:"center"});
}
function act(i,action){
  var c=cases[i];var body={id:c.id,action:action};
  if(action==="edit"){
    var raw=document.getElementById("in"+i).value;var inp=raw;
    try{var p=JSON.parse(raw);if(Array.isArray(p))inp=p}catch(e){}
    body.input=inp;
    body.expectations=document.getElementById("ex"+i).value.split("\\n").filter(Boolean).map(function(l){var m=l.indexOf(":");return {kind:l.slice(0,m).trim()||"must",text:l.slice(m+1).trim()}});
  }
  fetch("/api/decision",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}).then(function(r){return r.json()}).then(function(){
    c._state=action==="reject"?"rejected":(action==="edit"?"edited":"accepted");
    if(i===idx&&idx<cases.length-1)idx++;render();
  });
}
document.addEventListener("keydown",function(e){
  if(e.target.tagName==="TEXTAREA"&&e.key!=="Escape")return;
  if(e.key==="j"){idx=Math.min(cases.length-1,idx+1);render()}
  if(e.key==="k"){idx=Math.max(0,idx-1);render()}
  if(e.key==="a")act(idx,"accept");
  if(e.key==="r")act(idx,"reject");
  if(e.key==="s")act(idx,"edit");
  if(e.key==="e"){var t=document.getElementById("in"+idx);if(t)t.focus()}
  if(e.key==="Escape")document.activeElement.blur();
});
fetch("/api/cases").then(function(r){return r.json()}).then(function(d){cases=d.cases;behaviors=d.behaviors;
  cases.sort(function(a,b){return (a.reviewed?1:0)-(b.reviewed?1:0)});render()});
</script></body></html>"""


class ReviewState:
    def __init__(self, store: SuiteStore, only_unreviewed: bool = True):
        self.store = store
        self.lock = threading.Lock()
        self.cases = store.cases()
        self.behaviors = {b.id: b.model_dump() for b in store.behaviors()}
        self.only_unreviewed = only_unreviewed
        self.log_path = store.path("review.jsonl")

    def listing(self) -> dict[str, Any]:
        cases = [c for c in self.cases if not (self.only_unreviewed and c.reviewed)]
        return {"cases": [c.model_dump(mode="json") for c in cases], "behaviors": self.behaviors}

    def decide(self, body: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            cid = body.get("id")
            action = body.get("action")
            match = [c for c in self.cases if c.id == cid]
            if not match or action not in ("accept", "reject", "edit"):
                return {"ok": False, "error": "unknown case or action"}
            case = match[0]
            if action == "reject":
                self.cases = [c for c in self.cases if c.id != cid]
            elif action == "accept":
                case.reviewed = True
            else:
                if body.get("input"):
                    case.input = body["input"]
                if isinstance(body.get("expectations"), list):
                    kinds = {"must", "must_not", "should", "refuse", "tool_call", "format"}
                    bid = case.behaviors[0] if case.behaviors else None
                    case.expectations = [
                        Expectation(
                            kind=e.get("kind") if e.get("kind") in kinds else "must",
                            text=e.get("text", ""),
                            behavior_id=bid,
                        )
                        for e in body["expectations"]
                        if e.get("text")
                    ]
                case.reviewed = True
                case.meta["edited"] = True
            self.store.write_cases(self.cases)
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(), "id": cid, "action": action}) + "\n")
            return {"ok": True, "remaining": sum(1 for c in self.cases if not c.reviewed)}


def serve(store: SuiteStore, port: int = 8799, open_browser: bool = True, only_unreviewed: bool = True) -> None:
    state = ReviewState(store, only_unreviewed)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                self._send(200, PAGE.encode(), "text/html; charset=utf-8")
            elif self.path == "/api/cases":
                self._send(200, json.dumps(state.listing()).encode(), "application/json")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            if self.path != "/api/decision":
                self._send(404, b"not found", "text/plain")
                return
            length = min(int(self.headers.get("Content-Length", 0)), 1_000_000)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                self._send(400, b'{"ok":false}', "application/json")
                return
            self._send(200, json.dumps(state.decide(body)).encode(), "application/json")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"review UI at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


__all__ = ["serve", "ReviewState", "Case"]
