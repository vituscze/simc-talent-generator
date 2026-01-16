import collections
import itertools
import json
import math

def tokenize(name: str) -> str:
    '''
    Performs a simc-style tokenization on the given string. Converts the string to lowercase,
    replaces spaces with underscores and removes any special characters.

    >>> tokenize('Hello world')
    'hello_world'
    '''
    return ''.join(filter(lambda c: c == '_' or c.isalpha(), name.lower().replace(' ','_')))

class LazyDict[K, V]:
    '''
    LazyDict(lookup) implements a simple memoization scheme for the lookup function. It behaves
    as a dictionary {k:lookup(k) for k in all_keys}, except that the key-value pairs are computed
    on demand.

    >>> ld = LazyDict(lambda x: x * 2)
    >>> ld[5]
    25
    '''
    def __init__(self, lookup):
        self.lookup = lookup
        self.data: dict[K, V] = {}

    def __getitem__(self, key: K) -> V:
        '''
        Retrieves the value of lookup(key), using the cache if possible. If not, computes and caches
        the result.
        '''
        if key not in self.data:
            self.data[key] = self.lookup(key)
        return self.data[key]

class Choice:
    '''
    Choice represents a single choice in a talent node.

    Typically, a talent node contains two choices if it's a choice node and a single
    choice otherwise, although there have been some unusual exceptions.
    '''
    # TODO: Should probably be called TalentEntry or something like that, Choice
    # no longer makes sense in the presence of tiered nodes
    def __init__(self, raw_json, node: 'TalentNode'):
        self.__dict__.update(raw_json)
        self.id: int = raw_json['id']
        self.name: str = raw_json['name']
        self.max_ranks: int = raw_json['maxRanks']
        self.index: int = raw_json['index']
        self.node = node

        # Bookkeeping for requirements
        self.min_assign: int = 0
        self.max_assign: int = self.max_ranks

    def __repr__(self) -> str:
        return f'{self.name} ({self.id})'

    def __eq__(self, other) -> bool:
        return isinstance(other, type(self)) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

class TalentNode:
    '''
    TalentNode represents a single talent node of a talent tree.

    A TalentNode is constructed in three steps:

    a) The __init__ method sets up the relevant attributes using the provided JSON.

    b) The populate_next_1 method filters out links going to invalid nodes, using
       the provided set of all valid nodes.

    c) The populate_next_2 method filters out links going to valid but unpickable nodes,
       uisng the provided set of pickable nodes. It also sets up the set next_same
       (next_diff), which contains links to nodes in the same (different) talent tier.
    '''
    def __init__(self, raw_json):
        self.json = raw_json
        self.id: int = self.json['id']
        self.name: str = self.json['name']
        self.is_free = 'freeNode' in self.json
        self.is_entry = 'entryNode' in self.json
        self.req_points: int = self.json['reqPoints'] if 'reqPoints' in self.json else 0
        self.type: str = self.json['type']
        self.max_ranks: int = self.json['maxRanks'] if 'maxRanks' in self.json else 0
        self.sub_tree: int | None = self.json['subTreeId'] if 'subTreeId' in self.json else None
        # Some single nodes have additional empty entries, remove them
        self.choices = [Choice(entry, self) for entry in self.json['entries'] if 'id' in entry]
        self.choices.sort(key=lambda c: c.index)

        # Bookkeeping for requirements
        self.min_assign: int = 0
        self.max_assign: int = self.max_ranks
        self.allows_empty = True

        if not self.is_valid():
            return

        if self.type == 'single':
            # If a single node has multiple choices, it seems that the game
            # only lets you pick the first one.
            # TODO: Check if this is still the case
            self.choices = self.choices[:1]
            assert len(self.choices) == 1, f'{self.name} Single node without choices'
        elif self.type == 'choice':
            assert self.max_ranks == 1, 'Choice node with ranks'
        else:
            assert self.type == 'tiered', 'Unknown node type'

        if self.type == 'tiered':
            assert sum(c.max_ranks for c in self.choices) == self.max_ranks, 'Tiered node with inconsistent ranks'
        else:
            assert all(c.max_ranks == self.max_ranks for c in self.choices), 'Non-tiered node with inconsistent ranks'

    def __repr__(self) -> str:
        return f'{self.name} ({self.id})'

    def __eq__(self, other) -> bool:
        return isinstance(other, type(self)) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    def is_valid(self) -> bool:
        '''
        Checks if the node is valid. A valid talent node has well-defined max ranks.
        '''
        return self.max_ranks > 0

    def populate_next_1(self, valid_nodes: dict[int, 'TalentNode']) -> None:
        '''
        First stage of link creation: replace ids with actual nodes and remove
        invalid links.
        '''
        next_ids = set(self.json['next'])
        self.next = {valid_nodes[id] for id in next_ids if id in valid_nodes}

    def populate_next_2(self, unpickable: set['TalentNode']) -> None:
        '''
        Second stage of link creation: remove links going to unpickable nodes
        and split links by tier.
        '''
        self.next -= unpickable
        self.next_same = {node for node in self.next if node.req_points == self.req_points}
        self.next_diff = {node for node in self.next if node.req_points != self.req_points}

    def apply_requirements(self, choice_reqs: dict[int, tuple[int, int]],
                           node_reqs: dict[int, tuple[int, int]]) -> None:
        '''
        Apply requirements (as produced by TalentTree._normalize_reqs) to the node
        and its choices. Sets the relevant bookkeeping information and sets
        TalentNode.allows_empty to whether the requirements are compatible with
        an empty assignment.
        '''
        allows_empty = True

        def set_assign(obj: 'Choice | TalentNode',
                       reqs: dict[int, tuple[int, int]]) -> None:
            nonlocal allows_empty
            obj.min_assign = 0
            obj.max_assign = obj.max_ranks
            if obj.id in reqs:
                lo, hi = reqs[obj.id]
                obj.min_assign = max(obj.min_assign, lo)
                obj.max_assign = min(obj.max_assign, hi)
                if not (obj.min_assign <= 0 <= obj.max_assign):
                    allows_empty = False

        set_assign(self, node_reqs)
        for choice in self.choices:
            set_assign(choice, choice_reqs)
        # Node can be skipped if an assignment that allocates no points to
        # it or its choices is valid.
        self.allows_empty = allows_empty

    def generate_assignments(self):
        '''
        Yields all assignments that satisfy the requirements as given
        by TalentNode.apply_requirements. An assignment is given as a triple
        (count: int, full: bool, change: list[tuple[int, int]]):

        * `count'   the total number of assigned points
        * `full'    whether the node was filled completely
        * `change'  list of valid ways to assign the points

        If the change list contains no elements, no points need to be changed.
        If it contains 2 or more elements, these represent the choices
        that can be made when assigning the points. As an example, the list

            [(30,1),(40,1)]

        specifies a single point could be assigned either to choice id 30 or
        choice id 40.

        This method should only be used after TalentNode.apply_requirements.
        '''
        for pts in range(self.min_assign, self.max_assign + 1):
            assign: list[tuple[int, int]] = []
            any_valid = False
            for choice in self.choices:
                if not (choice.min_assign <= pts <= choice.max_assign):
                    continue
                if all(c.min_assign <= 0 <= c.max_assign for c in self.choices if c != choice):
                    any_valid = True
                    if pts > 0:
                        assign.append((choice.id, pts))
            if any_valid:
                yield pts, pts == self.max_ranks, assign

Assignment = list[tuple[int, int]]
RawTalentBuild = tuple[Assignment, list[Assignment]]
GraphSearchResult = dict[tuple[int, frozenset[TalentNode]], list[RawTalentBuild]]
GraphSearchDict = LazyDict[frozenset[TalentNode], GraphSearchResult]

class TalentTree:
    '''
    TalentTree represents a single talent tree (class, spec, hero) of
    a particular specialization.

    Several method are parametrized by requirements (generate_builds,
    generate_profiles and count_builds). A requirement specifies how
    many points should be assigned to each choice and talent node. This can
    either be given as a single int (choice/node must be assigned exactly
    that many points) or as a tuple[int, int] (choice/node may be assigned
    any number of points from the specified interval).

    The choice/talent node can be given either by using its id or
    Choice/TalentNode directly. Although choice and node ids currently don't
    collide, there's no guarantee that it won't happen in the future and for
    that reason, the requirements are split in two.

    a) choice_requirements is a dictionary representing the choice requirements

    b) node_requirements is a dictionary representing the talent node requirements

    Suppose that a talent with id 1 contains two choices with ids 2 and 3. Forcing
    both choices to have zero points can be done in the following ways:

    >>> tree = TalentTree(...)
    >>> tree.count_builds(choice_requirements={2:0, 3:0})
    ...
    >>> tree.count_builds(node_requirements={1:0})
    ...

    If we want the talent node to be assigned a single point but we don't care about
    which choice is selected:

    >>> tree.count_builds(node_requirements={1:1})
    ...
    '''
    def __init__(self, tree_type: str, raw_json):
        # Make sure we can treat ids as actual ids.
        is_unique = lambda vals: len(vals) == len(set(vals))
        assert is_unique([node['id'] for node in raw_json if 'id' in node]), 'Node id not unique'
        assert is_unique([choice['id'] for node in raw_json if 'id' in node
                          for choice in node['entries'] if 'id' in choice]), 'Choice id not unique'

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
        self.tiers: dict[int, set['TalentNode']] = {}
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

        # A final sanity check that links don't skip an entire tier
        for node in self.nodes.values():
            ix_1 = self.gates.index(node.req_points)
            for n_node in node.next_diff:
                ix_2 = self.gates.index(n_node.req_points)
                assert ix_2 == ix_1 + 1, 'Link going across multiple tiers'

    def __repr__(self) -> str:
        return str(set(self.nodes.values()))

    def all_nodes(self, tier: int | None=None) -> set[TalentNode]:
        '''
        Retrieves the set of all pickable talent nodes in the given tier, or
        the entire tree if the tier isn't specified.
        '''
        return {node for tier in self.tiers.values() for node in tier} if tier is None else self.tiers[tier]

    def all_node_ids(self, tier: int | None=None) -> set[int]:
        '''
        Retrieves the set of all pickable talent node ids in the given tier, or
        the entire tree if the tier isn't specified.
        '''
        return {node.id for node in self.all_nodes(tier)}

    def all_choices(self, tier: int | None=None) -> set[Choice]:
        '''
        Retrieves the set of all choices of pickable talent nodes in the
        given tier, or the entire tree if the tier isn't specified.
        '''
        return {choice for node in self.all_nodes(tier) for choice in node.choices}

    def all_choice_ids(self, tier: int | None=None) -> set[int]:
        '''
        Retrieves the set of all choice ids of pickable talent nodes in the
        given tier, or the entire tree if the tier isn't specified.
        '''
        return {choice.id for choice in self.all_choices(tier)}

    def ordered_choice_ids(self) -> list[int]:
        '''
        Returns a list of all choice ids in a specific, unchanging order.
        Used for profile generation.
        '''
        return sorted(self.all_choice_ids())

    def _normalize_reqs(self, tier: int | None, choices: dict, nodes: dict) -> \
            tuple[dict[int, tuple[int, int]], dict[int, tuple[int, int]]]:
        '''
        Converts choice and talent node requirements (as described by TalentTree)
        into a representation used by _search_graph. In particular, _search_graph
        expects choice requirements to have the type dict[int, tuple[int, int]]
        and talent node requirements dict[int, tuple[int, int]]. Also filters out
        requirements which are not relevant to the given talent tree tier.

        A single int requirement v is turned into a tuple (v, v). Choices and
        talent nodes are turned into their ids.

        Returns a tuple containing the new choice requirements and the new node
        requirements, in this order.
        '''
        choice_ids = self.all_choice_ids(tier)
        node_ids = self.all_node_ids(tier)

        split = lambda v: (v, v) if isinstance(v, int) else v
        toid = lambda v: v if isinstance(v, int) else v.id
        # Restrict requirements only to the tier we're interested in and set up intervals
        # for single-digit requirements.
        return {toid(c):split(v) for c, v in choices.items() if toid(c) in choice_ids}, \
               {toid(n):split(v) for n, v in nodes.items() if toid(n) in node_ids}

    def _search_graph(self, extra_entry: frozenset[TalentNode], tier: int,
                      raw_choice_reqs: dict, raw_node_reqs: dict) -> GraphSearchResult:
        '''
        Searches the graph of a given talent tree tier, starting with the static entry
        nodes and any additional nodes as specified by extra_entry.

        All valid (partial) builds are returned in a dictionary. The key is a tuple
        containing the total number of points assigned as well as set of talent tree nodes
        that are reachable in the next talent tree tier. The value is a list of corresponding
        builds, given by a tuple containing a list of single choice assignments and a list
        of multiple choice assignments. As an example, the following

           ([(10,1),(20,2)], [[(30,1),(40,1)]])

        represents two different talent builds: {10:1,20:2,30:1,40:0} and {10:1,20:2,30:0,40:1}
        (note the choice between choice ids 30 and 40).
        '''
        initial = extra_entry | self.entry
        initial &= self.tiers[tier]

        choice_reqs, node_reqs = self._normalize_reqs(tier, raw_choice_reqs, raw_node_reqs)
        total_nonempty_nodes = 0
        node_assignments: dict[int, list[tuple[int, bool, Assignment]]] = {}
        for node in self.all_nodes(tier):
            node.apply_requirements(choice_reqs, node_reqs)
            node_assignments[node.id] = list(node.generate_assignments())
            if not node.allows_empty:
                total_nonempty_nodes += 1

        result: GraphSearchResult = collections.defaultdict(list)

        def go(queue: list[TalentNode], visited: frozenset[TalentNode],
               count: int=0, unlock: frozenset[TalentNode]=frozenset(),
               subtree: int | None=None, nonempty_nodes: int=0,
               normal_assign: Assignment=[], choice_assign: list[Assignment]=[]):
            if len(queue) == 0:
                # We only have a valid build if we managed to allocate at least one point
                # to all nodes that require nonempty assignment.
                if nonempty_nodes == total_nonempty_nodes:
                    result[(count, unlock)].append((normal_assign, choice_assign))
            else:
                node = queue.pop()
                for extra_count, full, assign in node_assignments[node.id]:
                    new_subtree = subtree if extra_count == 0 else node.sub_tree
                    if extra_count > 0 and subtree is not None and new_subtree is not None and subtree != new_subtree:
                        # Already locked into another subtree, skip
                        continue

                    go(queue + list(node.next_same - visited) if full else queue,
                       visited | node.next_same if full else visited, count + extra_count,
                       unlock | node.next_diff if full else unlock, new_subtree,
                       nonempty_nodes if node.allows_empty else nonempty_nodes + 1,
                       normal_assign + assign if len(assign) == 1 else normal_assign,
                       choice_assign + [assign] if len(assign) > 1 else choice_assign)
                queue.append(node)

        go(list(initial), initial)
        return result

    def default_points(self) -> int:
        '''
        Number of available talent points that can be used at the max level.
        '''
        return 13 if self.tree_type == 'hero' else 34

    def _get_lazy_dict(self, *args) -> GraphSearchDict:
        '''
        Constructs a LazyDict given the talent tree and requirements.
        '''
        return LazyDict(lambda key: self._search_graph(key, *args))

    def _apply_choices(self, start: dict[int, int], *build: RawTalentBuild):
        '''
        Turns a series of raw build parts (given by a tuple with normal
        and choice assignments) into an actual build, that is a mapping
        from choice ids to the number of assigned points. Uses the start
        dictionary as a starting point.
        '''
        raw_normal, raw_choice = zip(*build)
        normal = start | dict(itertools.chain(*raw_normal))
        for choice in itertools.product(*itertools.chain(*raw_choice)):
            yield normal | dict(choice)

    def generate_builds(self, choice_requirements: dict={}, node_requirements: dict={},
                        points: int | None=None):
        '''
        Yields all valid talent builds given the choice/talent node requirements
        and the number of points to spend. If not provided, uses the default number
        of points as specified by default_points.

        See TalentTree for the description of requirements.
        '''
        if points is None:
            points = self.default_points()
        gate_builds: list[GraphSearchDict] = []
        for tier in self.gates:
            gate_builds.append(self._get_lazy_dict(tier, choice_requirements, node_requirements))
        empty_build = {c_id:0 for c_id in self.all_choice_ids()}

        def go(ix: int=0, pts: int=0, unlock: frozenset[TalentNode]=frozenset(), prev: list[RawTalentBuild]=[]):
            for (next_pts, next_unlock), build_parts in gate_builds[ix][unlock].items():
                new_pts = pts + next_pts
                if new_pts != points and (ix + 1 == len(self.gates) or new_pts < self.gates[ix + 1]):
                    continue
                if ix + 1 == len(self.gates):
                    for part in build_parts:
                        yield from self._apply_choices(empty_build, *prev, part)
                else:
                    for part in build_parts:
                        yield from go(ix + 1, new_pts, next_unlock, prev + [part])

        yield from go()

    def generate_profiles(self, choice_requirements: dict={}, node_requirements: dict={},
                          points: int | None=None, profileset: bool=True) -> 'ProfileGenerator':
        '''
        Yields all valid talent builds through the profile generator object.
        See generate_builds and ProfileGenerator for more details.
        '''
        return ProfileGenerator(self.generate_builds(choice_requirements, node_requirements, points),
                                self, profileset)

    def count_builds(self, choice_requirements: dict={}, node_requirements: dict={},
                     points : int | None=None) -> int:
        '''
        Returns the number of all valid talent builds given the choice/talent node
        requirements and the number of points to spend. If not provided, uses the
        default number of points as specified by default_points.

        See TalentTree for the description of requirements.

        count_builds(*args) is equivalent to sum(1 for _ in generate_builds(*args)),
        but much faster.
        '''
        if points is None:
            points = self.default_points()
        gate_builds: list[GraphSearchDict] = []
        for tier in self.gates:
            gate_builds.append(self._get_lazy_dict(tier, choice_requirements, node_requirements))
        part_counts: dict[tuple[int, frozenset[TalentNode], int, frozenset[TalentNode]], int] = {}

        def go(ix: int=0, pts: int=0, unlock: frozenset[TalentNode]=frozenset()):
            total = 0
            for (next_pts, next_unlock), build_parts in gate_builds[ix][unlock].items():
                new_pts = pts + next_pts
                if new_pts != points and (ix + 1 == len(self.gates) or new_pts < self.gates[ix + 1]):
                    continue
                key = (ix, unlock, next_pts, next_unlock)
                if (part_count := part_counts.get(key)) is None:
                    part_count = sum(math.prod(len(c) for c in choices) for _, choices in build_parts)
                    part_counts[key] = part_count
                total += part_count * (1 if ix + 1 == len(self.gates) else go(ix + 1, new_pts, next_unlock))
            return total

        return go()

    def encode_profile(self, build: dict[int, int]) -> tuple[str, str]:
        '''
        Encodes a build into a name and a relevant simc option.
        Returns both as a tuple of strings.

        This is similar to ProfileGenerator.fill_blueprint, but
        more flexible (though not as optimized).
        '''
        ordered = [(c_id, build[c_id]) for c_id in self.ordered_choice_ids()]
        assert all(0 <= pts <= 9 for _, pts in ordered), 'Too many digits for the profile name'
        opt_name = self.tree_type + '_talents='
        return ''.join(f'{pts}' for _, pts in ordered), \
               opt_name + '/'.join(f'{c_id}:{pts}' for c_id, pts in ordered)

    def decode_profile(self, name: str) -> dict[Choice, int]:
        '''
        Decodes a profile name back into a (human readable) mapping
        from choices to spent points.
        '''
        to_choice = {c.id:c for c in self.all_choices()}
        ordered = self.ordered_choice_ids()
        assert len(name) == len(ordered), 'Invalid profile name length'
        return {to_choice[c_id]:v for c_id, v in zip(ordered, map(int, name))}

    def tokenized_names(self, apex: bool=True) -> dict[str, Choice]:
        '''
        Returns a mapping from tokenized choice names to the actual choices.

        Name collisions are resolved by appending an underscore and an index to
        the tokenized choice name.

        If apex is true, also attempts to find the apex talent and potentially
        add 'apex_1' through 'apex_3' to the resulting dictionary.
        '''
        result: dict[str, Choice] = {}
        choices = sorted(self.all_choices(), key=lambda c: (tokenize(c.name), c.id))
        for name, iter in itertools.groupby(choices, key=lambda c: tokenize(c.name)):
            assert name, 'Empty choice name'
            group = list(iter)
            if len(group) == 1:
                result[name] = group[0]
            else:
                for i, choice in enumerate(group):
                    result[f'{name}_{i + 1}'] = choice
        # Try to find the apex talents
        if apex and self.tree_type == 'spec':
            assert 20 in self.tiers, 'Spec with nonstandard last gate'
            candidates = self.entry & self.tiers[20]
            assert len(candidates) == 1, 'More than one apex candidate'

            def layers(depth: int, ns: set[TalentNode]) -> set[TalentNode]:
                return ns if depth <= 0 else layers(depth - 1, ns | {n_node for node in ns for n_node in node.next})

            for node in layers(2, candidates):
                if node.is_entry:
                    key = 'apex_1'
                elif node.max_ranks == 2:
                    key = 'apex_2'
                else:
                    key = 'apex_3'
                assert len(node.choices) == 1
                result[key] = node.choices[0]
            assert {'apex_1','apex_2','apex_3'} <= set(result), 'Incomplete apex talents'
        return result

    def populate_globals(self, apex: bool=True) -> None:
        '''
        USE CAREFULLY! This method modifies the global environment.

        Creates global variables corresponding to the tokenized names
        from the tokenized_names method. While the risk of name conflicts
        is low (talent names are fairly specific), it is not zero.

        This method is here mainly for user convenience in the interactive
        environment, allowing to specify the choice requirements fairly
        easily. While a similar effect could be accomplished with keyword
        args, the main benefit of this approach is a working autocomplete.
        '''
        globals().update(self.tokenized_names(apex))

class Specialization:
    '''
    Represents a single specialization with its three talent trees:
    class_ tree, spec tree and hero tree.

    Some convenience methods are provided that simply call the relevant
    methods of TalentTree.
    '''
    def __init__(self, tree):
        self.class_ = TalentTree('class', tree['classNodes'])
        self.spec   = TalentTree('spec',  tree['specNodes'])
        self.hero   = TalentTree('hero',  tree['heroNodes'])

    def generate_all_builds(self, choice_requirements: dict={},
                            node_requirements: dict={}):
        '''
        See TalentTree.generate_builds
        '''
        for class_build in self.class_.generate_builds(choice_requirements, node_requirements):
            for spec_build in self.spec.generate_builds(choice_requirements, node_requirements):
                for hero_build in self.hero.generate_builds(choice_requirements, node_requirements):
                    yield {'class': class_build, 'spec': spec_build, 'hero': hero_build}

    def count_all_builds(self, choice_requirements: dict={},
                         node_requirements: dict={}) -> int:
        '''
        See TalentTree.count_builds
        '''
        class_count = self.class_.count_builds(choice_requirements, node_requirements)
        spec_count = self.spec.count_builds(choice_requirements, node_requirements)
        hero_count = self.hero.count_builds(choice_requirements, node_requirements)
        return class_count * spec_count * hero_count

    def encode_profile(self, build: dict[str, dict[int, int]]) -> \
            tuple[tuple[str, str, str], ...]:
        '''
        See TalentTree.encode_profile
        '''
        return tuple(zip(self.class_.encode_profile(build['class']),
                         self.spec.encode_profile(build['spec']),
                         self.hero.encode_profile(build['hero'])))

    def all_tokenized_names(self, apex: bool=True) -> dict[str, Choice]:
        '''
        See TalentTree.tokenized_names
        '''
        return self.class_.tokenized_names(apex) \
             | self.spec.tokenized_names(apex) \
             | self.hero.tokenized_names(apex)

    def populate_globals(self, apex: bool=True) -> None:
        '''
        USE CAREFULLY! This method modifies the global environment.

        See TalentTree.populate_globals
        '''
        globals().update(self.all_tokenized_names(apex))

class TalentJSON:
    '''
    TalentJSON represents the parsed talent trees for all classes
    and specializations.

    For user convenience, the object contains attributes derived from
    the tokenized class and spec names, allowing easy access.

    >>> t = TalentJSON(...)
    >>> t.mage.frost.spec.count_builds()
    ...
    '''
    class Helper:
        pass

    @classmethod
    def from_file(cls, path: str='talents.json'):
        '''
        Opens and parses talent trees in the file specified by path.
        '''
        with open(path, 'r') as f:
            return cls(json.load(f))

    def __init__(self, raw_json):
        '''
        Parses talent trees in the given JSON.
        '''
        key = lambda tree: (tree['className'], tree['specName'])
        self.table = {key(tree):Specialization(tree) for tree in raw_json}
        # Set up additional attributes for user convenience
        for (class_, spec), val in self.table.items():
            class_attr = tokenize(class_)
            class_helper = getattr(self, class_attr, self.Helper())
            setattr(self, class_attr, class_helper)

            spec_attr = tokenize(spec)
            spec_helper = getattr(class_helper, spec_attr, val)
            setattr(class_helper, spec_attr, spec_helper)

class ProfileGenerator:
    '''
    ProfileGenerator servers to turn the talent builds provided by
    TalentTree into profiles (copies or profilesets) in the simc format
    that can be written to a file.
    '''
    def __init__(self, generator, tree: TalentTree, profileset: bool=True):
        self.generator = generator
        self.tree = tree
        self.profileset = profileset
        self.choice_ids = self.tree.ordered_choice_ids()
        self.build_blueprint()

    def build_blueprint(self) -> None:
        '''
        Creates a profile bytearray with the correct format and node ids,
        but with no actual assigned points.

        For each choice id, it stores the index of the corresponding byte in
        the bytearray in the talent_ixs array.

        Length of the profile name is given by the number of choice ids and
        it starts at the index specified by name_ix.

        As an example, consider a profileset with 3 choice ids:

                   0 2                0   1   2
                   v v                v   v   v
        profileset.000=spec_talents=1:0/2:0/3:0
                    ^
                    1

        For the i-th choice id, the name byte is given by name_ix + i. The count
        byte is given by talent_ixs[i].
        '''
        blueprint = bytearray()
        blueprint += b'profileset.' if self.profileset else b'copy='
        self.name_ix = len(blueprint)
        blueprint += b'0' * len(self.choice_ids)
        blueprint += b'=' if self.profileset else b'\n'
        blueprint += bytes(self.tree.tree_type, encoding='utf-8') + b'_talents='
        talent_ixs = []
        for c_id in self.choice_ids:
            blueprint += bytes(str(c_id), encoding='utf-8') + b':'
            talent_ixs.append(len(blueprint))
            blueprint += b'0/'
        blueprint[-1] = ord('\n')
        self.blueprint = blueprint
        self.talent_ixs = talent_ixs

    def fill_blueprint(self, build: dict[int, int]) -> bytearray:
        '''
        Fills the marked positions in the profile blueprint as specified
        by the build. See build_blueprint for more details.

        Returns a copy of the filled blueprint.
        '''
        for offset, c_id in enumerate(self.choice_ids):
            value = build[c_id]
            assert 0 <= value < 10, 'Too many digits for the blueprint'
            byte = ord('0') + value
            self.blueprint[self.name_ix + offset] = byte
            self.blueprint[self.talent_ixs[offset]] = byte
        # TODO: Copy shouldn't be necessary
        return self.blueprint.copy()

    def items(self):
        '''
        Yields all profile bytearrays.
        '''
        yield from map(self.fill_blueprint, self.generator)

    def to_file(self, filename: str, split: int | None=None, limit: int=100000) -> bool:
        '''
        Writes all profiles to a file given by filename.

        If split is specified, the profiles are written to multiple files, each
        containing no more than split profiles. This can be useful for example
        for Raidbots, which only allows 6399 profiles in a single sim.
        The file names are dervied from filename and a numeric suffix.

        The limit parameter stops the generation after that many profiles have
        been generated.

        Returns whether the limit was reached.
        '''
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
    talents = TalentJSON.from_file()
