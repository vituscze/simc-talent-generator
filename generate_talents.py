import json

class LazyDict:
    def __init__(self, lookup, extra_args=[]):
        self.lookup = lookup
        self.extra_args = extra_args
        self.data = {}

    def at(self, key):
        if key not in self.data:
            self.data[key] = self.lookup(key, *self.extra_args)
        return self.data[key]

class TalentNode:
    def __init__(self, raw_json):
        self.json = raw_json
        self.id = self.json['id']
        self.is_free = 'freeNode' in self.json
        self.is_entry = 'entryNode' in self.json
        self.req_points = self.json['reqPoints'] if 'reqPoints' in self.json else 0
        self.is_choice = self.json['type'] == 'choice'
        self.max_ranks = self.json['maxRanks'] if 'maxRanks' in self.json else None

    def __eq__(self, other):
        return self.id == other.id if isinstance(other, TalentNode) else False

    def __hash__(self):
        return hash(self.id)

    def is_valid(self):
        return self.max_ranks is not None

    # First stage of link creation: replace ids with actual nodes and remove invalid links
    def populate_next_1(self, valid_nodes):
        next_ids = set(self.json['next'])
        self.next = {valid_nodes[id] for id in next_ids if id in valid_nodes}

    # Second stage of link creation: remove links going to unpickable nodes and split links by tier
    def populate_next_2(self, unpickable):
        self.next -= unpickable
        self.next_same = {node for node in self.next if node.req_points == self.req_points}
        self.next_diff = {node for node in self.next if node.req_points != self.req_points}

    def get_sub_ids(self):
        if self.is_choice:
            return [choice['id'] for choice in self.json['entries']]
        else:
            return [self.id]

    def generate_assignments(self, reqs):
        if self.is_choice:
            assert self.max_ranks == 1, 'Multi-rank choice node'
            def check(assign):
                for k, v in assign.items():
                    if k not in reqs:
                        continue
                    lo, hi = reqs[k]
                    if not (lo <= v <= hi):
                        return False
                return True

            sub_ids = self.get_sub_ids()
            assign = {s_id:0 for s_id in sub_ids}
            if check(assign):
                yield 0, False, assign.copy()
            for s_id in sub_ids:
                assign[s_id] = 1
                if check(assign):
                    yield 1, True, assign.copy()
                assign[s_id] = 0
        else:
            lo = 0; hi = self.max_ranks
            if self.id in reqs:
                r_lo, r_hi = reqs[self.id]
                lo = max(lo, r_lo); hi = min(hi, r_hi)
            for i in range(lo, hi + 1):
                yield i, i == self.max_ranks, {self.id:i}

    def __repr__(self):
        return f'{self.json['name']} ({self.id})'

class TalentTree:
    def __init__(self, raw_json):
        self.nodes = {talent.id:talent for node in raw_json if (talent := TalentNode(node)).is_valid()}
        for node in self.nodes.values():
            node.populate_next_1(self.nodes)

        self.free = {node for node in self.nodes.values() if node.is_free}
        # Entry nodes can be either defined explicitly
        self.entry = {node for node in self.nodes.values() if node.is_entry}
        # or be a neighbor to a free node
        self.entry |= {n_node for node in self.free for n_node in node.next}
        # but not a free node itself.
        self.entry -= self.free

        for node in self.nodes.values():
            node.populate_next_2(self.free)

        self.tiers = {}
        for node in self.nodes.values():
            req = node.req_points
            if req in self.tiers:
                self.tiers[req].add(node)
            else:
                self.tiers[req] = {node}
        
        self.gates = sorted(self.tiers.keys())
        assert len(self.gates) > 0 and self.gates[0] == 0, 'Initial tier requires non-zero points'

        # Final sanity check that links don't skip an entire tier
        for node in self.nodes.values():
            ix_1 = self.gates.index(node.req_points)
            for n_node in node.next_diff:
                ix_2 = self.gates.index(n_node.req_points)
                assert ix_2 == ix_1 + 1, 'Link going across multiple tiers'

    def _search_graph(self, extra_entry, tier, reqs):
        initial = extra_entry | self.entry
        initial &= self.tiers[tier]

        result = {}
        sub_ids = {s_id for node in self.tiers[tier] for s_id in node.get_sub_ids()}
        build = {s_id:0 for s_id in sub_ids}
        # Restrict requirements only to the tier we're interested in
        reqs = {s_id:v for s_id, v in reqs.items() if s_id in sub_ids}
        visited = set()

        def go(queue, count=0, unlock=frozenset()):
            if len(queue) == 0:
                for s_id, (lo, hi) in reqs.items():
                    if not (lo <= build[s_id] <= hi):
                        return
                key = (count, frozenset(unlock))
                build_ = build.copy()
                if key in result:
                    result[key].append(build_)
                else:
                    result[key] = [build_]
            else:
                v, *rest = queue
                if v in visited:
                    go(rest, count, unlock)
                else:
                    visited.add(v)
                    for extra_count, full, assign in v.generate_assignments(reqs):
                        # Apply assignment
                        for s_id, pts in assign.items():
                            build[s_id] = pts
                        new_queue = rest + list(v.next_same) if full else rest
                        new_unlock = unlock | v.next_diff if full else unlock
                        go(new_queue, count + extra_count, new_unlock)
                        # Unapply assignment
                        for s_id, _ in assign.items():
                            build[s_id] = 0
                    visited.remove(v)

        go(initial)
        return result

    def generate_builds(self, requirements={}, points=34):
        gates = []
        for tier in self.gates:
            gates.append(LazyDict(self._search_graph, [tier, requirements]))

        # TODO: This could be more general
        assert len(self.gates) == 3, "Can't handle trees without exactly 3 tiers"
        for (pts1, g1_unlock), build1 in gates[0].at(frozenset()).items():
            if pts1 != points and pts1 < self.gates[1]:
                continue
            for (pts2, g2_unlock), build2 in gates[1].at(g1_unlock).items():
                if pts1 + pts2 != points and pts1 + pts2 < self.gates[2]:
                    continue
                for (pts3, _), build3 in gates[2].at(g2_unlock).items():
                    if pts1 + pts2 + pts3 != points:
                        continue
                    yield from (a | b | c for a in build1 for b in build2 for c in build3)

class TalentJSON:
    def __init__(self, file='talents.json'):
        with open(file, 'r') as f:
            raw = json.load(f)
        value = lambda tree: {
            'class': TalentTree(tree['classNodes']),
            'spec':  TalentTree(tree['specNodes']),
            'hero':  TalentTree(tree['heroNodes']),
        }
        key = lambda tree: (
            tree['className'],
            tree['specName'],
        )
        self._table = {key(tree):value(tree) for tree in raw}
    
    def get_nodes(self, class_, spec, kind='spec'):
        return self._table[(class_, spec)][kind]

# Testing
t = TalentJSON()
frost = t.get_nodes('Mage', 'Frost')
frost_class = t.get_nodes('Mage', 'Frost', 'class')