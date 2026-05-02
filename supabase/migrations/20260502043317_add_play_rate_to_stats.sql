ALTER TABLE "public"."champion_stats"
ADD COLUMN "play_rate" FLOAT;

ALTER TABLE "public"."trait_stats"
ADD COLUMN "play_rate" FLOAT;

ALTER TABLE "public"."item_stats"
ADD COLUMN "play_rate" FLOAT;
