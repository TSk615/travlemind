# Development Notes

## Local defaults

- API defaults to SQLite at `storage/travelmind.db`
- Jobs default to `inline` mode unless `TRAVELMIND_QUEUE_MODE=arq`
- Exports are written to `storage/exports`

## Production targets

- Web: Vercel or Netlify
- API and worker: Railway or any container host
- Database: managed PostgreSQL
- Cache/queue: managed Redis
- Storage: S3-compatible object storage

## License gate

Run the LangGraph replay quality gate and rollout drain audit before promoting a release. Application rollback after legacy-runtime removal uses the retained prior deployment version.
