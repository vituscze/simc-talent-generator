# Talent Build Generator

This is a small python script that can be used to count, generate and output talent builds for all World of Warcraft classes and specializations. The script is primarily meant to be used together with [simc](github.com/simulationcraft/simc/), although it shouldn't be hard to adapt for any other use case.

## Requirements

* Recent Python installation (tested with 3.13)
* JSON with the talent data
    * The script is designed to work on JSON files provided by [Raidbots](https://www.raidbots.com/developers)
    * In particular, you'll likely want to grab [the latest beta talent JSON](https://mimiron.raidbots.com/static/data/beta/talents.json)

## Usage

The script is meant to be used interactively, but unlike my previous version, it is also easy to import in other Python scripts and use as a library. If you run the script interactively, such as:

```
$ python -i generate_talents.py
```

It will look for a file named `talents.json` in the working directory. Make sure the file is present in the directory you're running the script from. If everything goes well, the script loads and parses all the talent trees and creates a single global variable `talents` that contains the results.

You can access any talent tree by using tokenized class and specialization names on `talents`:

```py
>>> talents.mage.frost.spec
{Improved Flurry (108849), Deep Shatter (110258), ...}
```

Class talents are accessed via `class_` (note the underscore) and hero talents via `hero`. By default, the talent simply shows you all the talent nodes contained within. The three main methods provided by the tree are: `count_builds`, `generate_builds` and `generate_profiles`. The last one is discussed in a separate subsection.

```py
>>> talents.mage.frost.spec.count_builds()
7780352
```

If you want to access the actual builds, rather than just the count:

```py
>>> all_builds = talents.mage.frost.spec.generate_builds()
>>> next(all_builds)
{134405: 1, 134406: 1, 134407: 1, 134408: 2, 134409: 0, ...}
```

A build is simply a mapping from choice IDs (an ID of a talent entry) to the number of assigned points.

By default, these three methods try to generate talent builds with 34 points (13 for hero talents). If you want to change this (a lower level character, perhaps), there's an optional `points` argument:

```py
>>> talents.mage.frost.spec.count_builds(points=12)
1012
```

### Specifying Requirements

Typically, you want to generate only builds that satisfy certain requirements. This script allows you to specify how many points a given choice (or a talent node) should have. These three methods can be given a dictionary which maps choice IDs to either numbers or intervals (a tuple of numbers) that specify how many points should be assigned.

As an example, suppose we want to count only the builds that put between one and two points into Rimecaster (choice ID 134408) and zero points into Cold Snap (choice ID 134181):

```py
>>> frost = talents.mage.frost.spec
>>> frost.count_builds({134408:(1,2), 134181:0})
3869782
```

You can get the choice IDs by calling `all_choices()` on the tree. However, unless you're already working with these IDs, looking them up is annoying. For that reason, you can use `populate_globals()` which will create global variables corresponding to the choice nodes.

```py
>>> frost.populate_globals()
>>> cold_snap
Cold Snap (134181)
>>> rimecaster
Rimecaster (134408)
>>> apex_3
Hand of Frost (136179)
```

The previous code then becomes:

```py
>>> frost.count_builds({rimecaster:(1,2), cold_snap:0})
3869782
```

Sometimes, you might want to specify that a choice node should be picked but you don't care about the particular choice. In that case, you provide a second dictionary with *node IDs*. The easiest way to get a node ID is to find one of the choices and refer to the `node` attribute:

```py
>>> frigid_focus.node
Splintering Ray / Frigid Focus (103771)
>>> frost.count_builds({}, {frigid_focus.node:0})
328936
```

### Generating Profilesets

Once you are comfortable with the requirements (you can only realistically sim at most 100&nbsp;000 builds), you can use the `generate_profiles` method to get a simc input:

```py
>>> frost.count_builds({ray_of_frost:0})
53444
>>> frost.generate_profiles({ray_of_frost:0}).to_file('talents')
False
```

This will save all the generated profilesets to the file `talents1.txt`. Even with only 53&nbsp;444 builds, the file is already about 22 MiB large. For this reason, the `to_file` method limits the generation to 100&nbsp;000 builds by default. You can change this by providing the optional `limit` argument. If you reach this limit, the method returns `True`.

If you don't want all profilesets to end up in a single file, you can also specify the `split` argument, which will only put as many as `split` profilesets into each file.

You can also provide the optional argument `profileset=False` to generate copies instead.

## Integration

If you want to use this script in your own code, I've added fairly detailed docstrings to the script. Let me know if something was unclear!

## TLDR

```py
$ python -i generate_talents.py
>>> frost = talents.mage.frost.spec
>>> frost.populate_globals()
>>> frost.count_builds({ray_of_frost:0, glaciate:1, blizzard_1:1})
15642
>>> frost.generate_profiles({ray_of_frost:0, glaciate:1, blizzard_1:1}).to_file('talents')
False
```
