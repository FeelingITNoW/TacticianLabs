ALTER TABLE "public"."participants"
ADD COLUMN "embedding" extensions.VECTOR(768);
