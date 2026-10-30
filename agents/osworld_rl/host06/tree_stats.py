"""Raw OSWorld accessibility XML: attributes of list-items (and of the combo-box/list they sit in), table-cell text, and
the dialog's buttons, to see what tells a closed drop-down's entries apart."""
import collections, sys, xml.etree.ElementTree as ET
root = ET.parse(sys.argv[1]).getroot()
parent = {c: p for p in root.iter() for c in p}
loc = lambda k: k.rsplit("}", 1)[-1]
attrs = lambda e: {loc(k): v for k, v in e.attrib.items()}
items = [e for e in root.iter() if e.tag == "list-item"]
print("list-items:", len(items))
anc = collections.Counter()
states = collections.Counter()
for e in items:
    a = attrs(e)
    states[(a.get("showing"), a.get("visible"))] += 1
    p, chain = parent.get(e), []
    while p is not None and len(chain) < 3:
        chain.append(p.tag)
        p = parent.get(p)
    anc[" < ".join(chain)] += 1
print("  (showing, visible):", dict(states))
print("  ancestors:", anc.most_common(4))
cb = [e for e in root.iter() if e.tag == "combo-box"]
print("combo-boxes:", len(cb), [(attrs(e).get("name"), attrs(e).get("expanded"), attrs(e).get("showing")) for e in cb[:5]])
ex = items[0]
print("example list-item attrs:", attrs(ex))
cells = [e for e in root.iter() if e.tag == "table-cell"]
print("table-cells:", len(cells), "| with text:", sum(bool((e.text or "").strip()) for e in cells),
      "| examples:", [(attrs(e).get("name"), (e.text or "").strip()[:12]) for e in cells if (e.text or "").strip()][:6])
btn = [(attrs(e).get("name"), attrs(e).get("showing")) for e in root.iter() if e.tag == "push-button" and attrs(e).get("name") in ("OK", "Next Tip", "Close")]
print("dialog-type buttons:", btn[:6])
