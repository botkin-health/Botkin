import paramiko
import json
import os

HOST = '116.203.213.137'
USER = 'root'
PASSWORD = 'W749a#j%37z8_138UBYA'

def run_ssh_query(ssh, query, output_file):
    print(f"Executing query for {output_file}...")
    # Command to run inside docker
    # Do not escape single quotes, bash double quotes handle it
    cmd = f"""docker exec healthvault_postgres psql -U healthvault -d healthvault -t -A -c "SELECT json_agg(row_to_json(t)) FROM ({query}) t;" """
    
    stdin, stdout, stderr = ssh.exec_command(cmd)
    output = stdout.read().decode('utf-8').strip()
    err = stderr.read().decode('utf-8').strip()
    
    if err and "WARNING" not in err:
        print(f"Error executing query: {err}")
    
    if output and output != "[]":
        try:
            data = json.loads(output)
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"✅ Saved {len(data)} records to {output_file}")
        except json.JSONDecodeError as e:
            print(f"❌ Failed to decode JSON for {output_file}: {e}\nOutput was: {output[:100]}...")
    else:
        print(f"⚠️ No data found for {output_file}")

def main():
    print("Connecting to SSH...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(HOST, username=USER, password=PASSWORD, timeout=10)
        print("✅ SSH connected successfully")
        
        queries = [
            (
                "SELECT * FROM nutrition_log WHERE user_id = 895655 ORDER BY date, meal_time",
                "data/nutrition/nutrition_log_remote.json"
            ),
            (
                "SELECT * FROM supplements_log WHERE user_id = 895655 ORDER BY date, time",
                "data/supplements/supplements_log_remote.json"
            ),
            (
                "SELECT * FROM weights WHERE user_id = 895655 AND source IN ('screenshot_ocr', 'manual', 'zepp', 'apple_health') ORDER BY measured_at",
                "data/weights/weights_remote.json"
            ),
            (
                "SELECT * FROM activity_log WHERE user_id = 895655 ORDER BY date",
                "data/activities/activities_remote.json"
            )
        ]
        
        for query, output_file in queries:
            run_ssh_query(ssh, query, output_file)
            
    except Exception as e:
        print(f"❌ Connection failed: {e}")
    finally:
        ssh.close()
        print("SSH connection closed.")

if __name__ == '__main__':
    main()
