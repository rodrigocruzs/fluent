# Database instructions

This project uses Neon Postgres.

Environment variables are stored in `.env.local`.
Do not print, expose, commit, or reveal database credentials.

Before making database changes:
1. Inspect the app structure.
2. Detect whether the project uses Prisma, Drizzle, Kysely, Supabase client, raw SQL, or another database layer.
3. Run the safest available schema/migration command.
4. Never run destructive SQL such as DROP TABLE, TRUNCATE, DELETE without WHERE, or schema resets unless explicitly approved.
5. Prefer creating migrations over editing the production database manually.
6. Run the app locally and verify the database connection.

Useful commands:
- npm install
- npm run dev
- npm run build
- npx prisma studio
- npx prisma migrate dev
- npx drizzle-kit generate
- npx drizzle-kit migrate