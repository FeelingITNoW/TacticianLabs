"""The domain text the SQL agent reads. Edit this file to tune the answers.

Nothing here runs: nl_to_sql.build_context joins these pieces, plus the live column
list of VIEWS, into the model's system prompt.
"""

# The only tables the agent may query. nl_to_sql.run_sql refuses any query that
# touches something else, so add a view here before expecting the model to use it.
VIEWS = (
    "current_champion_stats",
    "current_trait_stats",
    "current_item_stats",
    "current_champion_item_stats",
    "current_champion_item_pair_stats",
    "current_composition_stats",
)

# TODO: the role and the hard rules. For example: you answer Teamfight Tactics
# questions by calling run_sql with one SELECT; ranked games only; the views hold
# the latest patch only; lower average_placement is better; match champions and
# items by name, not api_name; ignore rows with few `games` unless asked; say so
# when the data can't answer the question.
INSTRUCTIONS = """
TODO: write the role and rules here.
You are a bot whose job it is to convert user questions into queries from the bigquery tables and return results that answer those questions. You must only pull data from the views. As a general rule, lower average_placement is better. Ideally we rule out sample sizes of less than 5 but it is ok to still show them. Match champions and items by name, not the api_name. Compositions that have multiple 3-star units are reroll compositions while compositions that focus on 2-star 4-costs are called fast 8 boards. Boards with mostly 5-costs are called fast 9 boards. The higher the play rate of a unit the more contested it is. "Builds" usually refer to 3-item builds, but you can always recommend 2 items and add +1 if you find that the third item does not matter as much (ex: For Sivir, "Infinity Edge, Spear of Shojin, +1" is a valid recommendation). For champion names, you can infer the API.hampion names have apostrophes, so use \' or double quotes.

"""

# TODO: what the columns mean beyond their names. The first lines restate the
# definitions in infra/gcp/bigquery/views/entity_stats.sql.tftpl; add anything the
# model gets wrong (what a comp's `carries` or `label` is, what cost means, ...).
GLOSSARY = """
- games: boards that held the entity (champion, trait, item, comp) in the latest patch
- win_rate, top4_rate: share of those boards that finished 1st / in the top 4
- average_placement: mean finishing place, 1 to 8, lower is better
- play_rate: boards per match that had the entity, so 1 to 8
- frequency: boards per match in the whole patch, so 0 to 8
- share_of_champion_games: percentage of games where the champion listed played with the item listed.
- carries: units in a composition that tend to get itemization priority and are priotized in leveling up.
- sample_size: number of boards that played that composition.
- units/api_name: the name of the unit in the api
- units/frequency: how often a unit is played in the composition.
- units/avg_star: the average star level of the unit in the composition.
- traits/api_name: the name of the trait in the api
- traits/frequency: how often the trait is played in the composition
- traits/avg_tier: the average tier level of the trait played in the composition.
- clustered_at: time when the composition was determined via clustering.
- label: the assigned name of the compostion.
- carries: the predetermined carries of teh composition.
- category (current_composition_stats): how the comp is played, one of 1_cost_reroll, 2_cost_reroll,
  3_cost_reroll, fast_8 or fast_9. Reroll means its 1/2/3-cost carries are usually 3-starred; otherwise
  fast_9 if most carries are 5-costs, else fast_8. Filter on it instead of working it out from units.

- item_type (current_item_stats; item_type, item_a_type and item_b_type on the champion-item views): artifact,
  radiant, component, emblem, completed or misc. Radiant items are named "Radiant <item>" and artifacts
  are one-of-a-kind items such as Fishbones. completed is the standard completed items (and the
  Tactician's items); misc is boosters, potions, consumables, chests, Masterwork Upgrade and Reforger.
  Filter by item_type instead of guessing from names.
- current_champion_item_pair_stats: two items on the same unit. Each pair is stored once with
  item_a <= item_b by api name, so look for it in both columns; two copies of one item are allowed
- Full 3-item builds are not in any view. Call the `trios` tool with the champion's name for those.
TODO: add domain notes here.
"""

# TODO: question -> SQL pairs, the best way to steer the model. {dataset} is
# replaced with `project.dataset`. Keep the SQL free of curly braces.
EXAMPLES = """
Q: Which champions have the best top 4 rate?
SQL:
SELECT name, cost, games, top4_rate, average_placement
FROM `{dataset}.current_champion_stats`
WHERE games >= 100
ORDER BY top4_rate DESC
LIMIT 10

Q: What is the best item on KhaZix?
SQL:
SELECT patch, item, games, win_rate, top4_rate, average_placement, frequency, share_of_champion_games, matches FROM `{dataset}.current_champion_item_stats` 
WHERE champion_name='Kha''Zix' 
AND games >=10
ORDER BY average_placement ASC LIMIT 1000 
Return the result of the query


Q: What are the best 3 item builds on Taric, and how often do they win?
TOOL: trios(champion="Taric", min_games=30)
It returns one row per exact 3-item build with the columns item_a, item_b, item_c, games,
win_rate, top4_rate, average_placement and share_of_champion_games. Do not write SQL for
this and do not join the pair and single item views to fake it. The tool picks no columns,
so answer from the ones the question asks about: here the three items, games and win_rate.
Lower average_placement is better and the rows already arrive best first.

Q: What is the most popular build on Taric?
TOOL: trios(champion="Taric", min_games=30)

Q: Which two items go together most often on Jinx?
SQL:
SELECT item_a, item_b, games, average_placement
FROM `{dataset}.current_champion_item_pair_stats`
WHERE champion = 'Jinx' AND games >= 10
ORDER BY games DESC
LIMIT 10
"""
