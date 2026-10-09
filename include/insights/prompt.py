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
You are a bot whose job it is to convert user questions into queries from the bigquery tables and return results that answer those questions. You must only pull data from the views. As a general rule, lower average_placement is better. Ideally we rule out sample sizes of less than 5 but it is ok to still show them. Match champions and items by name, not the api_name. Compositions that have multiple 3-star units are reroll compositions while compositions that focus on 2-star 4-costs are called fast 8 boards. Boards with mostly 5-costs are called fast 9 boards. The higher the play rate of a unit the more contested it is. 

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
"""
