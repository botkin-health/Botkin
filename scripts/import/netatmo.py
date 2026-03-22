#!/usr/bin/env python3
import requests
import json
import os
import lnetatmo
from dotenv import load_dotenv

load_dotenv()

# User provided credentials
USERNAME = 'lyskovsky@gmail.com'
PASSWORD = 'Lyskovsky_8444'

# lnetatmo (v4.2.0+) strictly requires CLIENT_ID, CLIENT_SECRET and REFRESH_TOKEN.

# Because Netatmo recently heavily enforced OAuth2, Client ID/Secret are mandatory.
# I'll create the script skeleton. If the user didn't create an app, the API will reject it.

CLIENT_ID = os.getenv('NETATMO_CLIENT_ID', '')
CLIENT_SECRET = os.getenv('NETATMO_CLIENT_SECRET', '')

def fetch_homecoach_data():
    if not CLIENT_ID or not CLIENT_SECRET:
        print("❌ Ошибка: Необходимы Client ID и Client Secret от Netatmo (dev.netatmo.com).")
        print("Без них библиотека lnetatmo (и API Netatmo) не позволит пройти авторизацию OAuth2.")
        return []

    try:
        refresh_token = os.getenv('NETATMO_REFRESH_TOKEN')
        if not refresh_token:
            print("❌ Ошибка: В .env нет NETATMO_REFRESH_TOKEN. Сгенерируйте его в разделе Token generator на странице приложения.")
            return []

        # Initialize authorization
        authorization = lnetatmo.ClientAuth(
            clientId=CLIENT_ID,
            clientSecret=CLIENT_SECRET,
            refreshToken=refresh_token
        )
        
        # Get Home Coach data
        homecoach = lnetatmo.HomeCoach(authorization)
        data = []
        
        # Stations to skip (old/inactive devices)
        SKIP_STATIONS = {'Гнездышко'}

        # Fetch Current Data
        print("🔄 Извлечение текущих метрик Netatmo...")
        for station_data in homecoach.rawData:
            # Skip stations that are unreachable or have no recent dashboard data
            if not station_data.get('reachable', False) or 'dashboard_data' not in station_data:
                continue
            if station_data.get('station_name') in SKIP_STATIONS:
                print(f"⏭️  Пропускаю станцию {station_data.get('station_name')} (в списке исключений)")
                continue
                
            dashboard = station_data.get('dashboard_data', {})
            entry = {
                "device_name": station_data.get('station_name', 'Unknown Room'),
                "temperature_c": dashboard.get('Temperature'),
                "humidity_percent": dashboard.get('Humidity'),
                "co2_ppm": dashboard.get('CO2'),
                "noise_db": dashboard.get('Noise'),
                "health_idx": dashboard.get('health_idx'),
                "timestamp": dashboard.get('time_utc')
            }
            data.append(entry)
            print(f"🌡️  Текущие параметры {entry['device_name']}: {entry['temperature_c']}°C, {entry['co2_ppm']} ppm CO2")
            
        # Fetch Historical Data
        print("🔄 Извлечение истории Netatmo за последние 60 дней...")
        import time
        import requests
        
        history_data = {}
        for station_data in homecoach.rawData:
            device_id = station_data.get('_id')
            device_name = station_data.get('station_name', 'Unknown')
            if not device_id:
                continue
            if device_name in SKIP_STATIONS:
                print(f"⏭️  Пропускаю историю станции {device_name} (в списке исключений)")
                continue
                
            url = "https://api.netatmo.com/api/getmeasure"
            params = {
                "access_token": homecoach.getAuthToken,
                "device_id": device_id,
                "scale": "1day",
                "type": "Temperature,CO2,Humidity,Noise",
                "date_begin": int(time.time() - 60*24*3600),
                "optimize": "false"
            }
            resp = requests.post(url, data=params, timeout=15)
            if resp.status_code == 200:
                hist = resp.json().get('body', {})
                history_data[device_name] = hist
                print(f"✅ Успешно получена история для станции {device_name} (дней: {len(hist)})")
            else:
                print(f"⚠️ Ошибка получения истории для {device_name}: {resp.text}")

        # Save Historical Data
        if history_data:
            os.makedirs('data/environment', exist_ok=True)
            with open('data/environment/netatmo_history.json', 'w', encoding='utf-8') as f:
                json.dump(history_data, f, ensure_ascii=False, indent=2)
            print("✅ Исторические данные сохранены в data/environment/netatmo_history.json")

        return data

    except Exception as e:
        print(f"❌ Ошибка подключения к Netatmo API: {e}")
        return []

if __name__ == '__main__':
    data = fetch_homecoach_data()
    if data:
        os.makedirs('data/environment', exist_ok=True)
        with open('data/environment/netatmo_log.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("✅ Данные климата сохранены в data/environment/netatmo_log.json")
