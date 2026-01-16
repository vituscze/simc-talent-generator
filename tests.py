from generate_talents import *
import requests

class Empty:
    pass

if __name__ == '__main__':
    req = requests.get('https://mimiron.raidbots.com/static/data/12.0.0.64529/talents.json')
    talents = TalentJSON(req.json())
    hero: TalentTree = talents.mage.frost.hero
    assert hero.count_builds() == 16, 'hero count'
    hero_bs = list(hero.generate_builds())
    hero_b = hero_bs[0]
    assert len(hero_b) == len(hero.all_entries()), 'hero choice count'
    assert len(hero_bs) == 16, 'hero count gen'
    assert all(sum(b.values()) == 13 for b in hero_bs), 'hero points'
    hero_bs_sorted = [tuple(sorted(b.items())) for b in hero_bs]
    assert len(hero_bs_sorted) == len(set(hero_bs_sorted)), 'hero builds unique'

    t = Empty()
    class_: TalentTree = talents.mage.frost.class_
    t.__dict__.update(class_.tokenized_names())
    assert class_.count_builds() == 2444595642, 'class count'
    assert class_.count_builds({t.shimmer:1}) == 1156553567, 'shimmer'
    assert class_.count_builds({t.shimmer:0}) == 2444595642 - 1156553567, 'no shimmer'
    assert class_.count_builds({}, {t.shimmer.node:1}) == 2313107134, 'shimmer node'
    assert class_.count_builds({}, {t.shimmer.node:0}) == 2444595642 - 2313107134, 'no shimmer node'
    assert class_.count_builds({t.shimmer:1,t.improved_blink:1}) == 0, 'conflict'
    assert class_.count_builds({t.greater_invisibility:0,t.master_of_escape:1}) == 0, 'no link'
    assert class_.count_builds({t.inspired_intellect:0,t.tome_of_antonidas:0,t.tome_of_rhonin:0},
                               {t.shimmer.node:0,t.ice_nova.node:1}) == 2220, 'class reqs count'
    class_bs = list(class_.generate_builds({t.inspired_intellect:0,t.tome_of_antonidas:0,t.tome_of_rhonin:0},
                                           {t.shimmer.node:0,t.ice_nova.node:1}))
    class_b = class_bs[0]
    assert len(class_b) == len(class_.all_entries()), 'class choice count'
    assert len(class_bs) == 2220, 'class reqs count gen'
    c_t1 = class_.all_entry_ids(0)
    c_t2 = class_.all_entry_ids(8)
    c_t3 = class_.all_entry_ids(20)
    c_t12 = c_t1 | c_t2; c_t123 = c_t12 | c_t3
    any_in = False; any_fc = False
    any_sm = False; any_re = False
    any_no = False
    for b in class_bs:
        assert set(b.keys()) == c_t123, 'same keys'
        assert sum(b.values()) == 34, 'class points'
        assert sum(v for k, v in b.items() if k in c_t1) >= 8, 'class tier 1'
        assert sum(v for k, v in b.items() if k in c_t12) >= 20, 'class tier 2'
        assert sum(v for k, v in b.items() if k in c_t123) == 34, 'class tier 3'
        assert b[t.inspired_intellect.id] == 0, 'no insp int'
        assert b[t.tome_of_antonidas.id] == 0, 'no tome 1'
        assert b[t.tome_of_rhonin.id] == 0, 'no tome 2'
        assert b[t.shimmer.id] + b[t.improved_blink.id] == 0, 'no blink choice'
        assert b[t.ice_nova.id] + b[t.freezing_cold.id] == 1, 'ice nova choice'
        assert b[t.ice_nova.id] != b[t.freezing_cold.id], 'ice nova choice 2'
        assert b[t.spatial_manipulation.id] + b[t.reflection.id] <= 1, 'manip choice'
        assert b[t.spellsteal.id] == 0 or b[t.arcane_warding.id] == 2, 'ss req 2 pts'
        assert b[t.mirror_image.id] == 0 or b[t.winters_protection.id] == 2 or b[t.frost_conditioning.id] == 1, 'mi req either'
        assert b[t.flow_of_time.id] == 0, 'node w/o parents'
        any_in = any_in or b[t.ice_nova.id] == 1
        any_fc = any_fc or b[t.freezing_cold.id] == 1
        any_sm = any_sm or b[t.spatial_manipulation.id] == 1
        any_re = any_re or b[t.reflection.id] == 1
        any_no = any_no or (b[t.spatial_manipulation.id] == 0 and b[t.reflection.id] == 0)
    assert any_in, 'one build w/ ice nova'
    assert any_fc, 'one build w/ freezing cold'
    assert any_sm, 'one build w/ manip'
    assert any_re, 'one build w/ refl'
    assert any_no, 'one build w/o manip and refl'
    class_bs_sorted = [tuple(sorted(b.items())) for b in class_bs]
    assert len(class_bs_sorted) == len(set(class_bs_sorted)), 'class builds unique'

    spec: TalentTree = talents.mage.frost.spec
    t.__dict__.update(spec.tokenized_names())
    assert spec.count_builds() == 7780352, 'spec count'
    assert spec.count_builds({t.frigid_focus:1}) == 3725708, 'ff'
    assert spec.count_builds({t.frigid_focus:0}) == 7780352 - 3725708, 'no ff'
    assert spec.count_builds({}, {t.frigid_focus.node:1}) == 7451416, 'ff node'
    assert spec.count_builds({}, {t.frigid_focus.node:0}) == 7780352 - 7451416, 'no ff node'
    assert spec.count_builds({t.blizzard_1:1,t.blizzard_2:1}) == 0, 'conflict'
    assert spec.count_builds({t.icy_hand:1,t.flurry:0}) == 0, 'no link'
    assert spec.count_builds({t.apex_2:(1,2),t.rimecaster:2,t.glacial_attunement:(0,1),t.blizzard_1:0},
                             {t.frigid_focus.node:0}) == 1914, 'spec reqs count'
    specbs = list(spec.generate_builds({t.apex_2:(1,2),t.rimecaster:2,t.glacial_attunement:(0,1),t.blizzard_1:0},
                                       {t.frigid_focus.node:0}))
    specb = specbs[0]
    assert len(specb) == len(spec.all_entries()), 'spec choice count'
    assert len(specbs) == 1914, 'spec reqs count gen'
    s_t1 = spec.all_entry_ids(0)
    s_t2 = spec.all_entry_ids(8)
    s_t3 = spec.all_entry_ids(20)
    s_t12 = s_t1 | s_t2; s_t123 = s_t12 | s_t3
    any_cs = False; any_gb = False
    for b in specbs:
        assert set(b.keys()) == s_t123, 'same keys'
        assert sum(b.values()) == 34, 'class points'
        assert sum(v for k, v in b.items() if k in s_t1) >= 8, 'class tier 1'
        assert sum(v for k, v in b.items() if k in s_t12) >= 20, 'class tier 2'
        assert sum(v for k, v in b.items() if k in s_t123) == 34, 'class tier 3'
        assert b[t.summon_water_elemental.id] == 0, 'no welly'
        assert 1 <= b[t.apex_2.id] <= 2, '1-2 apex2'
        assert b[t.rimecaster.id] == 2, '2 rimecaster'
        assert 0 <= b[t.glacial_attunement.id] <= 1, '0-1 ga'
        assert b[t.blizzard_1.id] == 0, 'no blizzard1'
        assert b[t.blizzard_2.id] == 1, 'blizzard2'
        assert b[t.frigid_focus.id] + b[t.splintering_ray.id] == 0, 'no ray choice'
        assert b[t.cold_snap.id] + b[t.glacial_bulwark.id] <= 1, 'cold snap choice'
        assert b[t.apex_3.id] == 0 or b[t.apex_2.id] == 2, 'apex3 req 2 pts'
        assert b[t.glacial_attunement.id] == 0 or b[t.fractured_frost.id] == 1 or b[t.piercing_cold.id] == 1, 'si req either'
        assert b[t.summon_water_elemental.id] == 0, 'node w/o parents'
        any_cs = any_cs or b[t.cold_snap.id] == 1
        any_gb = any_gb or b[t.glacial_bulwark.id] == 1
    assert any_cs, 'one build w/ cold snap'
    assert any_gb, 'one build w/ glacial bulwark'
    specbs_sorted = [tuple(sorted(b.items())) for b in specbs]
    assert len(specbs_sorted) == len(set(specbs_sorted)), 'class builds unique'

    print('Tests OK')
