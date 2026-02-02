# HealthVault Crontab Setup Instructions

## Auto-Backup Configuration

### Crontab Entry
Add this line to your crontab to run backups every 12 hours:

```bash
0 */12 * * * cd /Users/alexlyskovsky/HealthVault && /usr/bin/make db-backup-auto >> /Users/alexlyskovsky/HealthVault/logs/cron_backup.log 2>&1
```

### Installation Steps

1. **Create log directory:**
```bash
mkdir -p /Users/alexlyskovsky/HealthVault/logs
```

2. **Add to crontab:**
```bash
crontab -e
```

Then add the line above.

3. **Verify crontab:**
```bash
crontab -l | grep healthvault
```

### Schedule Explained
- `0 */12 * * *` = Every 12 hours at minute 0 (00:00 and 12:00)
- Backups saved to: `/Users/alexlyskovsky/HealthVault/backup/`
- Logs saved to: `/Users/alexlyskovsky/HealthVault/logs/cron_backup.log` 
- Retention: 7 days (older backups auto-deleted)

### Manual Testing
Test the backup command manually first:
```bash
cd /Users/alexlyskovsky/HealthVault && make db-backup-auto
```

### Alternative Schedule Options

**Every 6 hours:**
```
0 */6 * * * cd /Users/alexlyskovsky/HealthVault && /usr/bin/make db-backup-auto >> /Users/alexlyskovsky/HealthVault/logs/cron_backup.log 2>&1
```

**Daily at 3 AM:**
```
0 3 * * * cd /Users/alexlyskovsky/HealthVault && /usr/bin/make db-backup-auto >> /Users/alexlyskovsky/HealthVault/logs/cron_backup.log 2>&1
```

**Twice daily (6 AM and 6 PM):**
```
0 6,18 * * * cd /Users/alexlyskovsky/HealthVault && /usr/bin/make db-backup-auto >> /Users/alexlyskovsky/HealthVault/logs/cron_backup.log 2>&1
```
