"""Offline HTML: inert JSON, text-only rendering and bounded product pages."""
import html

from cdr_report_terms import encoded

STYLE = '''<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{font:16px system-ui;max-width:1100px;margin:32px auto;padding:0 20px;color:#17232d;background:#fafbfc}
a{color:#17589c}h1{font-size:28px}input,select{font:inherit;padding:9px;margin:4px 8px 4px 0;max-width:95%}
input{width:380px}details{padding:12px 0;border-bottom:1px solid #ccd4db}summary{cursor:pointer;font-weight:600}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px ui-monospace,monospace}li{margin:10px 0}
.muted{color:#526474}.controls{position:sticky;top:0;background:#fafbfc;padding:10px 0}button{font:inherit;padding:8px 16px}
</style>'''
NOTICE = ('Published fields and selected-edition evidence. Missing fields remain unreported. '
          'Document completeness, bank approval and complete financial totals are not established.')


def document(title, body, data, script):
    safe = encoded(data).decode().replace('<', '\\u003c')
    return ('<!doctype html><html lang="en"><head>' + STYLE + '<title>' + html.escape(title)
            + '</title></head><body><h1>' + html.escape(title) + '</h1><p class="muted">'
            + NOTICE + '</p>' + body + '<script type="application/json" id="data">' + safe
            + '</script><script>' + script + '</script></body></html>').encode()


def index_html(data):
    body = '''<p id="edition"></p><p id="counts"></p><p><a href="manifest.json">Evidence manifest</a> ·
<a href="definitions.md">Definitions and limits</a> · <a href="products.csv">Product index CSV</a></p>
<details><summary>Source metadata and supplied metrics</summary><p>Every supplied value is retained with its source pointer.
These files preserve observed history; they do not reconstruct missing dates.</p><ul id="metadata"></ul></details>
<div class="controls"><input id="search" aria-label="Search all product names and banks" placeholder="Search product or bank">
<select id="bank" aria-label="Bank"><option value="">All banks</option></select></div>
<p id="matched" role="status"></p><ul id="products"></ul><button id="more">Show 100 more</button>'''
    script = '''const data=JSON.parse(document.getElementById('data').textContent),byId=id=>document.getElementById(id);
const make=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e};
byId('edition').textContent='Selected observation: '+data.run_date+' · '+data.binding.binding_mode;
byId('counts').textContent=data.products.length+' products · '+data.rate_rows+' published rate rows · '+data.parts+' parts';
for(const b of [...new Set(data.products.map(p=>p.provider))].sort()){const o=make('option',b);o.value=b;byId('bank').append(o)}
for(const f of data.metadata){const li=make('li'),a=make('a',f.file+' ('+f.rows+' rows)');a.href=f.file;li.append(a);byId('metadata').append(li)}
let limit=100;function draw(){const q=byId('search').value.toLowerCase(),b=byId('bank').value;
const hits=data.products.filter(p=>(!b||p.provider===b)&&(!q||JSON.stringify(p).toLowerCase().includes(q)));
byId('products').replaceChildren();byId('matched').textContent=hits.length+' matched · showing '+Math.min(limit,hits.length);
for(const p of hits.slice(0,limit)){const li=make('li'),a=make('a',p.provider+' — '+p.product_name);a.href=p.href;li.append(a,make('span',' · '+p.rate_rows+' rate rows'));byId('products').append(li)}
byId('more').hidden=limit>=hits.length}for(const id of ['search','bank'])byId(id).addEventListener('input',()=>{limit=100;draw()});
byId('more').addEventListener('click',()=>{limit+=100;draw()});draw();'''
    return document('Published products and evidence', body, data, script)


def part_html(name, value):
    body = '''<p><a href="../index.html">All products</a> · <a href="product-data.json.gz">Complete JSON (gzip)</a> ·
<a href="products.csv">Product summary CSV</a> · <a href="rates.csv">Rates CSV</a> ·
<a href="parameters.csv.gz">Every detail field (CSV gzip)</a> · <a href="terms.csv.gz">Terms evidence (CSV gzip)</a></p>
<input id="search" aria-label="Search all fields in this part" placeholder="Search any field in this part"><p id="matched" role="status"></p><main id="products"></main>'''
    script = '''const data=JSON.parse(document.getElementById('data').textContent),root=document.getElementById('products');
const make=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e};
const entries=Object.entries(data.products).map(([key,p],i)=>({key,p,id:'p'+i,search:JSON.stringify(p).toLowerCase()}));
function draw(){const q=document.getElementById('search').value.toLowerCase();root.replaceChildren();let count=0;
for(const {key,p,id,search} of entries){if(q&&!search.includes(q))continue;count++;const d=make('details');d.id=id;
d.append(make('summary',p.summary.provider+' — '+p.summary.product_name));let loaded=false;
const load=()=>{if(!d.open||loaded)return;loaded=true;for(const [label,value] of Object.entries(p)){const g=make('details');
g.append(make('summary',label),make('pre',JSON.stringify(value,null,2)));d.append(g)}};d.addEventListener('toggle',load);root.append(d);
if(location.hash==='#'+id){d.open=true;load()}}document.getElementById('matched').textContent=count+' products';}
document.getElementById('search').addEventListener('input',draw);draw();'''
    return document('Product evidence · ' + name, body, value, script)
