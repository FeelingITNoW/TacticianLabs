


SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;


COMMENT ON SCHEMA "public" IS 'standard public schema';



CREATE EXTENSION IF NOT EXISTS "pg_graphql" WITH SCHEMA "graphql";






CREATE EXTENSION IF NOT EXISTS "pg_stat_statements" WITH SCHEMA "extensions";






CREATE EXTENSION IF NOT EXISTS "pgcrypto" WITH SCHEMA "extensions";






CREATE EXTENSION IF NOT EXISTS "supabase_vault" WITH SCHEMA "vault";






CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA "extensions";






CREATE EXTENSION IF NOT EXISTS "wrappers" WITH SCHEMA "extensions";






CREATE FOREIGN DATA WRAPPER "s3_wrapper" HANDLER "extensions"."s3_fdw_handler" VALIDATOR "extensions"."s3_fdw_validator";




CREATE SERVER "backblaze_server" FOREIGN DATA WRAPPER "s3_wrapper" OPTIONS (
    "aws_access_key_id" '798c1494eb30',
    "aws_region" 'ca-east-006',
    "aws_secret_access_key" '0067ec37c194b32a99c12cba26cc32443fc6549963',
    "endpoint_url" 's3.ca-east-006.backblazeb2.com'
);


ALTER SERVER "backblaze_server" OWNER TO "postgres";

SET default_tablespace = '';

SET default_table_access_method = "heap";


CREATE TABLE IF NOT EXISTS "public"."matches" (
    "match_id" "text" NOT NULL,
    "game_length" double precision,
    "game_version" "text",
    "tft_set_number" integer,
    "game_datetime" numeric
);


ALTER TABLE "public"."matches" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."participants" (
    "match_id" "text" NOT NULL,
    "puuid" "text" NOT NULL,
    "placement" integer,
    "level" integer,
    "gold_left" integer,
    "last_round" integer,
    "total_damage_to_players" integer
);


ALTER TABLE "public"."participants" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."player_ranked_stats" (
    "puuid" "text" NOT NULL,
    "tier" "text",
    "rank" "text",
    "league_points" integer,
    "wins" integer,
    "losses" integer,
    "hot_streak" boolean,
    "updated_at" timestamp without time zone DEFAULT "now"()
);


ALTER TABLE "public"."player_ranked_stats" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."players" (
    "puuid" "text" NOT NULL,
    "game_name" "text",
    "tag_line" "text",
    "region" "text",
    "created_at" timestamp without time zone DEFAULT "now"()
);


ALTER TABLE "public"."players" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."traits" (
    "match_id" "text" NOT NULL,
    "puuid" "text" NOT NULL,
    "name" "text" NOT NULL,
    "num_units" integer,
    "tier_current" integer,
    "tier_total" integer,
    "style" smallint
);


ALTER TABLE "public"."traits" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."units" (
    "match_id" "text" NOT NULL,
    "puuid" "text" NOT NULL,
    "character_id" "text",
    "tier" integer,
    "item_names" "text"[],
    "rarity" smallint,
    "uuid" "uuid" DEFAULT "gen_random_uuid"() NOT NULL
);


ALTER TABLE "public"."units" OWNER TO "postgres";


ALTER TABLE ONLY "public"."matches"
    ADD CONSTRAINT "matches_pkey" PRIMARY KEY ("match_id");



ALTER TABLE ONLY "public"."participants"
    ADD CONSTRAINT "participants_pkey" PRIMARY KEY ("match_id", "puuid");



ALTER TABLE ONLY "public"."player_ranked_stats"
    ADD CONSTRAINT "player_ranked_stats_pkey" PRIMARY KEY ("puuid");



ALTER TABLE ONLY "public"."players"
    ADD CONSTRAINT "players_pkey" PRIMARY KEY ("puuid");



ALTER TABLE ONLY "public"."traits"
    ADD CONSTRAINT "traits_pkey" PRIMARY KEY ("match_id", "puuid", "name");



ALTER TABLE ONLY "public"."units"
    ADD CONSTRAINT "units_pkey" PRIMARY KEY ("uuid");



ALTER TABLE ONLY "public"."participants"
    ADD CONSTRAINT "participants_match_id_fkey" FOREIGN KEY ("match_id") REFERENCES "public"."matches"("match_id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."participants"
    ADD CONSTRAINT "participants_puuid_fkey" FOREIGN KEY ("puuid") REFERENCES "public"."players"("puuid") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."player_ranked_stats"
    ADD CONSTRAINT "player_ranked_stats_puuid_fkey" FOREIGN KEY ("puuid") REFERENCES "public"."players"("puuid") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."traits"
    ADD CONSTRAINT "traits_match_id_puuid_fkey" FOREIGN KEY ("match_id", "puuid") REFERENCES "public"."participants"("match_id", "puuid") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."units"
    ADD CONSTRAINT "units_match_id_puuid_fkey" FOREIGN KEY ("match_id", "puuid") REFERENCES "public"."participants"("match_id", "puuid") ON DELETE CASCADE;



ALTER TABLE "public"."matches" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."participants" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."player_ranked_stats" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."players" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."traits" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."units" ENABLE ROW LEVEL SECURITY;




ALTER PUBLICATION "supabase_realtime" OWNER TO "postgres";


GRANT USAGE ON SCHEMA "public" TO "postgres";
GRANT USAGE ON SCHEMA "public" TO "anon";
GRANT USAGE ON SCHEMA "public" TO "authenticated";
GRANT USAGE ON SCHEMA "public" TO "service_role";










































































































































































































































































































































GRANT ALL ON TABLE "public"."matches" TO "anon";
GRANT ALL ON TABLE "public"."matches" TO "authenticated";
GRANT ALL ON TABLE "public"."matches" TO "service_role";



GRANT ALL ON TABLE "public"."participants" TO "anon";
GRANT ALL ON TABLE "public"."participants" TO "authenticated";
GRANT ALL ON TABLE "public"."participants" TO "service_role";



GRANT ALL ON TABLE "public"."player_ranked_stats" TO "anon";
GRANT ALL ON TABLE "public"."player_ranked_stats" TO "authenticated";
GRANT ALL ON TABLE "public"."player_ranked_stats" TO "service_role";



GRANT ALL ON TABLE "public"."players" TO "anon";
GRANT ALL ON TABLE "public"."players" TO "authenticated";
GRANT ALL ON TABLE "public"."players" TO "service_role";



GRANT ALL ON TABLE "public"."traits" TO "anon";
GRANT ALL ON TABLE "public"."traits" TO "authenticated";
GRANT ALL ON TABLE "public"."traits" TO "service_role";



GRANT ALL ON TABLE "public"."units" TO "anon";
GRANT ALL ON TABLE "public"."units" TO "authenticated";
GRANT ALL ON TABLE "public"."units" TO "service_role";









ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "service_role";































