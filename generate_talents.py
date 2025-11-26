import json

def tokenize(name):
    # simc-style tokenization
    return ''.join(filter(lambda c: c == '_' or c.isalpha(), name.lower().replace(' ','_')))

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
    class Choice:
        def __init__(self, raw_json):
            self.__dict__.update(raw_json)

        def __repr__(self):
            return f'{self.name} ({self.id})'

        def __eq__(self, other):
            return self.id == other.id if isinstance(other, self.Choice) else False

        def __hash__(self):
            return hash(self.id)

    def __init__(self, raw_json):
        self.json = raw_json
        self.id = self.json['id']
        self.name = self.json['name']
        self.is_free = 'freeNode' in self.json
        self.is_entry = 'entryNode' in self.json
        self.req_points = self.json['reqPoints'] if 'reqPoints' in self.json else 0
        self.is_choice = self.json['type'] == 'choice'
        self.max_ranks = self.json['maxRanks'] if 'maxRanks' in self.json else None
        self.sub_tree = self.json['subTreeId'] if 'subTreeId' in self.json else None
        # Some single nodes have additional empty entries, remove them
        self.choices = [self.Choice(entry) for entry in self.json['entries'] if 'id' in entry]

    def __repr__(self):
        return f'{self.name} ({self.id})'

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

    def generate_assignments(self, reqs):
        # TODO: These could be merged, if the edge cases are properly handled
        if self.is_choice:
            assert self.max_ranks == 1, 'Choice node with ranks'
            def check(assign):
                for c_id, v in assign.items():
                    if c_id not in reqs:
                        continue
                    lo, hi = reqs[c_id]
                    if not (lo <= v <= hi):
                        return False
                return True

            assign = {c.id:0 for c in self.choices}
            if check(assign):
                yield 0, False, assign
            for c_id in assign:
                new_assign = assign | {c_id:1}
                if check(new_assign):
                    yield 1, True, new_assign
        else:
            # TODO: If the following happens in game, it looks like it only offers the first choice
            # assert len(self.choices) == 1, 'Single node with choices'
            lo = 0; hi = self.max_ranks
            c = self.choices[0]
            if c.id in reqs:
                r_lo, r_hi = reqs[c.id]
                lo = max(lo, r_lo); hi = min(hi, r_hi)
            for i in range(lo, hi + 1):
                yield i, i == self.max_ranks, {c.id:i}

class TalentTree:
    def __init__(self, tree_type, raw_json):
        self.tree_type = tree_type
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

        # Pickable nodes by tier
        self.tiers = {}
        for node in self.nodes.values():
            if node.is_free:
                continue
            req = node.req_points
            if req in self.tiers:
                self.tiers[req].add(node)
            else:
                self.tiers[req] = {node}

        self.gates = sorted(self.tiers.keys())
        assert len(self.gates) > 0 and self.gates[0] == 0, 'Initial tier requires non-zero points'

        choices = [choice for node in self.nodes.values() for choice in node.choices]
        assert len(choices) == len(set(choices)), 'Choice ids not unique'

        # A final sanity check that links don't skip an entire tier
        for node in self.nodes.values():
            ix_1 = self.gates.index(node.req_points)
            for n_node in node.next_diff:
                ix_2 = self.gates.index(n_node.req_points)
                assert ix_2 == ix_1 + 1, 'Link going across multiple tiers'

    def __repr__(self):
        return str(set(self.nodes.values()))

    def _tier_nodes(self, tier):
        return {node for tier in self.tiers.values() for node in tier} if tier is None else self.tiers[tier]

    def all_choices(self, tier=None):
        return {choice for node in self._tier_nodes(tier) for choice in node.choices}

    def all_choice_ids(self, tier=None):
        return {choice.id for choice in self.all_choices(tier)}

    def _search_graph(self, extra_entry, tier, reqs):
        initial = extra_entry | self.entry
        initial &= self.tiers[tier]

        result = {}
        choice_ids = self.all_choice_ids(tier)
        build = {c_id:0 for c_id in choice_ids}
        # Restrict requirements only to the tier we're interested in and set up intervals
        # for single-digit requirements.
        split = lambda v: (v, v) if isinstance(v, int) else v
        reqs = {c_id:split(v) for c_id, v in reqs.items() if c_id in choice_ids}
        visited = set()

        def go(queue, count=0, unlock=set(), subtree=None):
            if len(queue) == 0:
                for c_id, (lo, hi) in reqs.items():
                    if not (lo <= build[c_id] <= hi):
                        return
                key = (count, frozenset(unlock))
                build_ = build.copy()
                if key in result:
                    result[key].append(build_)
                else:
                    result[key] = [build_]
            else:
                node, *rest = queue
                if node in visited:
                    go(rest, count, unlock, subtree)
                else:
                    visited.add(node)
                    for extra_count, full, assign in node.generate_assignments(reqs):
                        new_subtree = subtree if extra_count == 0 else node.sub_tree
                        if extra_count > 0 and subtree is not None and new_subtree is not None and subtree != new_subtree:
                            # Already locked into another subtree, skip
                            continue
                        # Apply assignment
                        for c_id, pts in assign.items():
                            build[c_id] = pts
                        new_queue = rest + list(node.next_same) if full else rest
                        new_unlock = unlock | node.next_diff if full else unlock
                        go(new_queue, count + extra_count, new_unlock, new_subtree)
                        # Unapply assignment
                        for c_id in assign:
                            build[c_id] = 0
                    visited.remove(node)

        go(initial)
        return result

    def default_points(self):
        return 13 if self.tree_type == 'hero' else 34

    def generate_builds(self, requirements={}, points=None):
        if points is None:
            points = self.default_points()
        gate_builds = []
        for tier in self.gates:
            gate_builds.append(LazyDict(self._search_graph, [tier, requirements]))

        def go(ix=0, pts=0, unlock=frozenset()):
            for (next_pts, next_unlock), build_parts in gate_builds[ix].at(unlock).items():
                new_pts = pts + next_pts
                if new_pts != points and (ix + 1 == len(self.gates) or new_pts < self.gates[ix + 1]):
                    continue
                if ix + 1 == len(self.gates):
                    yield from build_parts
                else:
                    for build_part in build_parts:
                        for build in go(ix + 1, new_pts, next_unlock):
                            yield build | build_part

        yield from go()

    def generate_profilesets(self, requirements={}, points=None):
        return ProfilesetGenerator(self.generate_builds(requirements, points), self)

    def count_builds(self, requirements={}, points=None):
        if points is None:
            points = self.default_points()
        gate_builds = []
        for tier in self.gates:
            gate_builds.append(LazyDict(self._search_graph, [tier, requirements]))

        def go(ix=0, pts=0, unlock=frozenset()):
            total = 0
            for (next_pts, next_unlock), build_parts in gate_builds[ix].at(unlock).items():
                new_pts = pts + next_pts
                if new_pts != points and (ix + 1 == len(self.gates) or new_pts < self.gates[ix + 1]):
                    continue
                total += len(build_parts) * (1 if ix + 1 == len(self.gates) else go(ix + 1, new_pts, next_unlock))
            return total

        return go()

class TalentJSON:
    class Helper:
        pass

    def __init__(self, file='talents.json'):
        with open(file, 'r') as f:
            raw = json.load(f)
        value = lambda tree: {
            'class': TalentTree('class', tree['classNodes']),
            'spec':  TalentTree('spec', tree['specNodes']),
            'hero':  TalentTree('hero', tree['heroNodes']),
        }
        key = lambda tree: (
            tree['className'],
            tree['specName'],
        )
        self._table = {key(tree):value(tree) for tree in raw}
        # Set up additional attributes for user convenience
        for (class_, spec), vals in self._table.items():
            class_attr = tokenize(class_)
            class_helper = getattr(self, class_attr, self.Helper())
            setattr(self, class_attr, class_helper)

            spec_attr = tokenize(spec)
            spec_helper = getattr(class_helper, spec_attr, self.Helper())
            setattr(class_helper, spec_attr, spec_helper)

            setattr(spec_helper, 'class_', vals['class'])
            setattr(spec_helper, 'spec', vals['spec'])
            setattr(spec_helper, 'hero', vals['hero'])

    def get_nodes(self, class_, spec, kind='spec'):
        return self._table[(class_, spec)][kind]

class ProfilesetGenerator:
    def __init__(self, generator, tree):
        self.generator = generator
        self.tree = tree
        self.choice_ids = sorted(self.tree.all_choice_ids())
        self.build_blueprint()

    def build_blueprint(self):
        blueprint = bytearray()
        blueprint += b'profileset.'
        self.name_ix = len(blueprint)
        blueprint += b'0' * len(self.choice_ids)
        blueprint += b'=' + bytes(self.tree.tree_type, encoding='utf-8') + b'_talents='
        talent_ixs = []
        for c_id in self.choice_ids:
            blueprint += bytes(str(c_id), encoding='utf-8') + b':'
            talent_ixs.append(len(blueprint))
            blueprint += b'0/'
        blueprint[-1] = ord('\n')
        self.blueprint = blueprint
        self.talent_ixs = talent_ixs

    def fill_blueprint(self, build):
        for offset, c_id in enumerate(self.choice_ids):
            value = build[c_id]
            assert 0 <= value < 10, 'Too many digits for the blueprint'
            byte = ord('0') + value
            self.blueprint[self.name_ix + offset] = byte
            self.blueprint[self.talent_ixs[offset]] = byte
        # TODO: Copy shouldn't be necessary
        return self.blueprint.copy()

    def items(self):
        yield from map(self.fill_blueprint, self.generator)

    # Returns whether the limit was reached
    def to_file(self, filename, split=None, limit=100000):
        file_count = 0
        file = None
        limit_reached = False
        for ix, bytes in enumerate(self.items()):
            if ix >= limit:
                limit_reached = True
                break
            if file is None or (split is not None and ix % split == 0):
                if file:
                    file.close()
                file_count += 1
                file = open(f'{filename}{file_count}.txt', 'wb')
            file.write(bytes)
        if file:
            file.close()
        return limit_reached

if __name__ == '__main__':
    talents = TalentJSON()
