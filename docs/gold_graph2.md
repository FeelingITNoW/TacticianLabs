Edit the gold projection tool to be more flexible for the bot to use to simulate gold better. Add custom control that the bot can use over round wins and losses. For example: allow the chatbot to tailor the tool to a full winstreak stage 2 and 3 into stage 4 full lose streak with a string like "wwwwwwwwwwwllll" to project gold earnings of winning 11 rounds in a row until 4-1 and lose 4 rounds in a row on 4-2. 

Additionally, add custom control for gold spent to simulate spending gold for buying units and leveling up or recieving gold from augments. An example of this is spending 4 gold on 2-1 to level to 4, another 4 gold on 2-5 to level to 5, 12 gold to level to 6 on 3-2 and so on. For example, a full winstreak board on average should level as much as possible to preserve streak.

An input could look like
[-4, -3, 0, -4, 0, -2, -2, -16, 12, -3, -24, 0, -4, 20]
where each round represents a round from 2-1 to 4-2, where inputs -4, -4, -16, and -24 were used on leveling, 12 and 20 were gold gained from augments, and the others were spent on buying units. This would be used to make the gold projection resemble a real game more. For lose streak, it would be closer to full zeroes in order to save as much gold as possible, with spending all gold in leveling that is above 50. 

Additionally, remove the natural XP earned and Free Rolls tables as they do not add any value.

