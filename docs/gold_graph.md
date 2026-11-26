Create another tool for the chatbot to utilize when analyzing compositions: the total gold + exp projection tool. 

The tool will calculate the total gold and exp earned by a player between the first player combat round (2-1) and up to a set round (default 4-2). The gold and exp will come from three sources: Natural income, augments, and streak

Natural Income: 
- set amount of gold per round (4 gold 2-1, 5 gold 2-2 onwards)
- neutrals gold: assume 6 gold on average
- carousel: assume you get an average of 3 gold 

Augments:
- this should be modelled by it adding either gold at a specific round (2-1, 3-2, or 4-2), add rolls, or exp per round

Streak:
- every call for gold projection will have three parallel projections: one for full win streak, one for full loss streak, and one for mixed streak
- mixed streak will be randomized by picking between 2 or 3 and and placing them in random rounds per stage

The graph should have 3 values displayed:
- How much exp is earned naturally and from augments
- How much gold total is earned 
- How many rerolls total earned

make it clear how much gold would have to be spent to reach specific level thresholds and how much gold would be left over after reaching that target level.(specifically 8 and 9)

A masterlist of augments and their rewards in terms of gold/exp will be provided if needed just indicate as so