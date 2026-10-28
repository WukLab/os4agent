"""TAGE for next-action prediction (after Seznec's ITTAGE): the "target" is the next action's key, the history is
the rollout's earlier actions.

Tables for history lengths 1, 2, 4, 8, indexed and tagged by hash(task, k, last k actions); each entry holds up to
`ncand` candidate actions with confidence counters and a useful counter u. The longest matching table predicts; a
global table keyed on the last action is the fallback. On a misprediction an entry is allocated in a longer table.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict

START = "^"


class Entry:
    """A table slot: tag (full context hash), candidates [[key, counter], ...], useful counter u (0..3)."""
    __slots__ = ("tag", "cands", "u")

    def __init__(self, tag, truth):
        self.tag, self.cands, self.u = tag, [[truth, 1]], 0

    def top(self):
        return max(self.cands, key=lambda c: c[1])[0] if self.cands else None

    def ranked(self):
        return [c[0] for c in sorted(self.cands, key=lambda c: -c[1])]

    def best_ctr(self):
        return max((c[1] for c in self.cands), default=0)


class Tage:
    """predict() at a decision, update() once the action is issued."""

    def __init__(self, ks=(1, 2, 4, 8), size=1 << 16, ncand=4, ctr_max=7, use_ctr=True, use_u=True,
                 alloc_on_miss=True, u_reset_every=4096, task_scoped=True):
        """use_ctr / use_u / alloc_on_miss are ablation switches. u_reset_every: halve all u this often so old
        entries become replaceable. task_scoped=False shares one history across tasks."""
        self.ks = tuple(sorted(ks, reverse=True))
        self.size, self.ncand, self.ctr_max = size, ncand, ctr_max
        self.use_ctr, self.use_u, self.alloc_on_miss = use_ctr, use_u, alloc_on_miss
        self.u_reset_every, self.task_scoped = u_reset_every, task_scoped
        self.tables = {k: {} for k in self.ks}  # k -> slot index -> Entry
        self.base = defaultdict(Counter)        # last action -> Counter(next), all tasks
        self.n = 0

    def _slot(self, task, hist, k):
        """(index, tag) of the last k actions, padded with START so early steps get their own contexts."""
        ctx = tuple([START] * max(0, k - len(hist)) + hist[max(0, len(hist) - k):])
        h = int.from_bytes(hashlib.blake2b(repr((task if self.task_scoped else None, k, ctx)).encode(),
                                           digest_size=8).digest(), "little")  # deterministic, unlike hash()
        return h % self.size, h

    def _hits(self, task, hist):
        """[(k, index, tag, entry or None)], longest first; a tag mismatch counts as a miss."""
        hits = []
        for k in self.ks:
            idx, tag = self._slot(task, hist, k)
            e = self.tables[k].get(idx)
            hits.append((k, idx, tag, e if e is not None and e.tag == tag else None))
        return hits

    def _order(self, hits, last):
        """Ranked candidates: provider (longest hit), then the other hits, then the base table. If the provider is a
        fresh weak entry (counter <= 1) and the alternate (next-longest hit) is more confident, the alternate goes
        first (TAGE's USE_ALT_ON_NA). Returns (list, hits that matched)."""
        found = [h for h in hits if h[3] is not None]
        lst = []
        if found:
            prov = found[0][3]
            alt = found[1][3] if len(found) > 1 else None
            if alt is not None and prov.best_ctr() <= 1 and alt.best_ctr() > prov.best_ctr():
                lst += alt.ranked() + prov.ranked()
            else:
                lst += prov.ranked()
            for h in found[1:]:
                lst += h[3].ranked()
        lst += [k for k, _ in self.base.get(last, Counter()).most_common(8)]
        seen, out = set(), []
        for x in lst:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out, found

    def predict(self, task, hist):
        """(up to 16 candidates, confidence = provider's counter / ctr_max, 0 if no table hit). Read-only."""
        last = hist[-1] if hist else START
        out, found = self._order(self._hits(task, hist), last)
        conf = found[0][3].best_ctr() / self.ctr_max if found else 0.0
        return out[:16], conf

    def update(self, task, hist, truth):
        """Learn that `truth` followed `hist`.
        - Train the provider toward truth. If provider and alternate disagreed, u += 1 when the provider was right,
          else u -= 1 (u says whether the longer history is worth keeping).
        - On a misprediction, allocate in the shortest longer table whose slot is free or has u == 0; if none,
          decrement those slots' u so a later miss can take them."""
        last = hist[-1] if hist else START
        hits = self._hits(task, hist)
        order, found = self._order(hits, last)
        pred = order[0] if order else None
        if not self.alloc_on_miss:  # ablation: every table learns every action
            for k, idx, tag, e in hits:
                if e is None:
                    self.tables[k][idx] = Entry(tag, truth)
                else:
                    self._train(e, truth)
        else:
            prov_k = None
            if found:
                prov_k, _, _, prov = found[0]
                alt_top = found[1][3].top() if len(found) > 1 else (self.base[last].most_common(1)[0][0]
                                                                   if self.base.get(last) else None)
                if self.use_u and alt_top != prov.top():
                    prov.u = min(3, prov.u + 1) if prov.top() == truth else max(0, prov.u - 1)
                self._train(prov, truth)
            if pred != truth:
                longer = [h for h in hits if prov_k is None or h[0] > prov_k]
                longer.sort(key=lambda h: h[0])  # shortest longer table first
                done = False
                for k, idx, tag, e in longer:
                    slot = self.tables[k].get(idx)
                    if slot is None or not self.use_u or slot.u == 0:
                        self.tables[k][idx] = Entry(tag, truth)
                        done = True
                        break
                if not done:
                    for k, idx, tag, e in longer:
                        slot = self.tables[k].get(idx)
                        if slot is not None:
                            slot.u = max(0, slot.u - 1)
        self.base[last][truth] += 1
        self.n += 1
        if self.use_u and self.u_reset_every and self.n % self.u_reset_every == 0:
            self.halve_u()

    def _train(self, e, truth):
        """truth's counter +1 (or it replaces the weakest candidate); a wrong top's counter -1."""
        if not self.use_ctr:
            e.cands = [[truth, 1]]
            return
        top = e.top()
        for c in e.cands:
            if c[0] == truth:
                c[1] = min(self.ctr_max, c[1] + 1)
                break
        else:
            if len(e.cands) >= self.ncand:
                e.cands.remove(min(e.cands, key=lambda c: c[1]))
            e.cands.append([truth, 1])
        if top != truth:
            for c in e.cands:
                if c[0] == top:
                    c[1] = max(0, c[1] - 1)

    def halve_u(self):
        for t in self.tables.values():
            for e in t.values():
                e.u >>= 1

    def reset_u(self):
        """All u to 0, e.g. at a policy update; not called by default."""
        for t in self.tables.values():
            for e in t.values():
                e.u = 0
