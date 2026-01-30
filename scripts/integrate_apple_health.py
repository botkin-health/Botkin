#!/usr/bin/env python3
"""
Интеграция Apple Health данных с системами HealthVault
Создает единые индексы и обновляет существующие файлы данными из Apple Health
"""

import json
import os
from datetime import datetime, date, timedelta
from pathlib import Path
from collections import defaultdict
import statistics

class AppleHealthIntegrator:
    def __init__(self):
        self.project_root = Path(__file__).parent.parent
        self.data_path = self.project_root / "data"
        self.apple_health_path = self.data_path / "apple-health"
        
    def load_apple_health_data(self):
        """Загружает обработанные данные Apple Health"""
        print("📱 Загружаем данные Apple Health...")
        
        # Загружаем summary
        summary_file = self.apple_health_path / "health_profile_summary.json"
        with open(summary_file, 'r', encoding='utf-8') as f:
            summary = json.load(f)
        
        # Загружаем дневные сводки
        daily_file = self.apple_health_path / "daily_summaries/health_metrics_daily.json"
        with open(daily_file, 'r', encoding='utf-8') as f:
            daily_data = json.load(f)
        
        # Загружаем последние записи веса
        weight_file = self.apple_health_path / "parsed/weight.json"
        with open(weight_file, 'r', encoding='utf-8') as f:
            weight_data = json.load(f)
        
        # Загружаем данные о сне
        sleep_file = self.apple_health_path / "parsed/sleep.json"
        with open(sleep_file, 'r', encoding='utf-8') as f:
            sleep_data = json.load(f)
        
        print(f"✅ Загружено:")
        print(f"   • Summary: период {summary['data_period']['first_date']} - {summary['data_period']['last_date']}")
        print(f"   • Дневные данные: {len(daily_data)} дней")
        print(f"   • Измерения веса: {len(weight_data)}")
        print(f"   • Записи сна: {len(sleep_data)}")
        
        return summary, daily_data, weight_data, sleep_data
    
    def create_unified_weight_log(self, weight_data):
        """Создает унифицированный лог веса"""
        print("\n⚖️ Создаем унифицированный лог веса...")
        
        # Группируем по дням и берем последнее измерение каждого дня
        daily_weights = {}
        for record in weight_data:
            record_date = record['date']
            record_datetime = datetime.fromisoformat(record['start_date'])
            
            if record_date not in daily_weights or record_datetime > datetime.fromisoformat(daily_weights[record_date]['start_date']):
                daily_weights[record_date] = record
        
        # Создаем структуру для сохранения
        weight_log = {
            'updated': datetime.now().isoformat(),
            'source': 'Apple Health Export',
            'total_measurements': len(weight_data),
            'daily_measurements': len(daily_weights),
            'period': {
                'first_date': min(daily_weights.keys()),
                'last_date': max(daily_weights.keys())
            },
            'data': daily_weights
        }
        
        # Сохраняем
        output_file = self.data_path / "unified_weight_log.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(weight_log, f, indent=2, ensure_ascii=False, sort_keys=True)
        
        print(f"✅ Унифицированный лог веса сохранен: {output_file}")
        print(f"   • Всего измерений: {len(weight_data)}")
        print(f"   • Дневных записей: {len(daily_weights)}")
        print(f"   • Период: {weight_log['period']['first_date']} - {weight_log['period']['last_date']}")
        
        return weight_log
    
    def analyze_weight_trends(self, weight_log):
        """Анализирует тренды веса"""
        print("\n📈 Анализируем тренды веса...")
        
        # Получаем последние N дней
        daily_weights = weight_log['data']
        dates = sorted(daily_weights.keys())
        
        # Анализируем разные периоды
        periods = {
            '7_days': dates[-7:] if len(dates) >= 7 else dates,
            '30_days': dates[-30:] if len(dates) >= 30 else dates,
            '90_days': dates[-90:] if len(dates) >= 90 else dates,
            '365_days': dates[-365:] if len(dates) >= 365 else dates
        }
        
        trends = {}
        for period_name, period_dates in periods.items():
            if len(period_dates) < 2:
                continue
                
            weights = [daily_weights[d]['value'] for d in period_dates]
            
            trends[period_name] = {
                'days': len(period_dates),
                'start_weight': weights[0],
                'end_weight': weights[-1],
                'change': round(weights[-1] - weights[0], 1),
                'avg_weight': round(statistics.mean(weights), 1),
                'min_weight': min(weights),
                'max_weight': max(weights),
                'trend': 'снижение' if weights[-1] < weights[0] else 'рост' if weights[-1] > weights[0] else 'стабильно'
            }
        
        # Сохраняем анализ
        analysis = {
            'updated': datetime.now().isoformat(),
            'current_weight': daily_weights[dates[-1]]['value'],
            'current_date': dates[-1],
            'trends': trends
        }
        
        output_file = self.data_path / "weight_trends_analysis.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(analysis, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Анализ трендов сохранен: {output_file}")
        
        # Выводим краткую сводку
        for period, data in trends.items():
            period_ru = period.replace('_days', ' дней')
            print(f"   • {period_ru}: {data['change']:+.1f} кг ({data['trend']})")
        
        return analysis
    
    def create_activity_summary(self, daily_data):
        """Создает сводку активности"""
        print("\n🚶 Создаем сводку активности...")
        
        # Анализируем последние 30, 90 и 365 дней
        dates = sorted(daily_data.keys())
        
        periods = {
            '30_days': dates[-30:] if len(dates) >= 30 else dates,
            '90_days': dates[-90:] if len(dates) >= 90 else dates,
            '365_days': dates[-365:] if len(dates) >= 365 else dates
        }
        
        activity_summary = {}
        
        for period_name, period_dates in periods.items():
            steps_data = [daily_data[d].get('steps_total', 0) for d in period_dates if 'steps_total' in daily_data[d]]
            active_energy_data = [daily_data[d].get('active_energy_total', 0) for d in period_dates if 'active_energy_total' in daily_data[d]]
            
            if steps_data:
                activity_summary[period_name] = {
                    'days_total': len(period_dates),
                    'days_with_data': len(steps_data),
                    'avg_steps': int(statistics.mean(steps_data)),
                    'max_steps': max(steps_data),
                    'min_steps': min(steps_data),
                    'days_10k_plus': len([s for s in steps_data if s >= 10000]),
                    'days_15k_plus': len([s for s in steps_data if s >= 15000]),
                    'days_20k_plus': len([s for s in steps_data if s >= 20000]),
                    'active_days_percentage': round(len([s for s in steps_data if s > 1000]) / len(steps_data) * 100, 1),
                    'avg_active_energy': round(statistics.mean(active_energy_data), 1) if active_energy_data else None
                }
        
        # Сохраняем
        output_file = self.data_path / "activity_summary.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump({
                'updated': datetime.now().isoformat(),
                'periods': activity_summary
            }, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Сводка активности сохранена: {output_file}")
        
        # Выводим краткую сводку
        for period, data in activity_summary.items():
            period_ru = period.replace('_days', ' дней')
            print(f"   • {period_ru}: {data['avg_steps']:,} шагов/день, {data['days_10k_plus']}/{data['days_with_data']} дней >10K")
        
        return activity_summary
    
    def create_health_dashboard(self, summary, weight_trends, activity_summary):
        """Создает дашборд здоровья"""
        print("\n📊 Создаем дашборд здоровья...")
        
        dashboard = {
            'updated': datetime.now().isoformat(),
            'data_source': 'Apple Health Export + HealthVault',
            'overview': {
                'data_period': summary['data_period'],
                'current_metrics': summary['current_metrics'],
                'trends_30_days': summary['trends_30_days']
            },
            'weight': {
                'current': weight_trends['current_weight'],
                'current_date': weight_trends['current_date'],
                'trends': weight_trends['trends']
            },
            'activity': activity_summary if activity_summary else {},
            'goals_progress': {
                'weight_loss': {
                    'target': 'снижение к 75 кг',
                    'current': weight_trends['current_weight'],
                    'progress': f"{weight_trends['current_weight'] - 75:.1f} кг до цели" if weight_trends['current_weight'] > 75 else "Цель достигнута!",
                    'trend_30_days': weight_trends['trends'].get('30_days', {}).get('change', 0)
                },
                'activity': {
                    'target': '10,000 шагов/день',
                    'current_avg_30': activity_summary.get('30_days', {}).get('avg_steps', 0) if activity_summary else 0,
                    'success_rate_30': f"{activity_summary.get('30_days', {}).get('days_10k_plus', 0)}/{activity_summary.get('30_days', {}).get('days_with_data', 0)} дней" if activity_summary else "0/0",
                    'status': '✅ Цель достигнута' if activity_summary and activity_summary.get('30_days', {}).get('avg_steps', 0) >= 10000 else '⚠️ Ниже цели'
                }
            }
        }
        
        # Сохраняем дашборд
        output_file = self.data_path / "health_dashboard.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(dashboard, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Дашборд здоровья сохранен: {output_file}")
        
        # Выводим основные показатели
        print(f"\n🎯 Основные показатели:")
        print(f"   • Текущий вес: {dashboard['weight']['current']} кг")
        print(f"   • Тренд за 30 дней: {dashboard['weight']['trends'].get('30_days', {}).get('change', 0):+.1f} кг")
        print(f"   • Активность: {dashboard['goals_progress']['activity']['status']}")
        print(f"   • Средние шаги: {dashboard['goals_progress']['activity']['current_avg_30']:,}/день")
        
        return dashboard
    
    def update_existing_files(self):
        """Обновляет существующие файлы данными из Apple Health"""
        print("\n🔄 Обновляем существующие файлы...")
        
        # Обновляем health_goals.json
        goals_file = self.data_path / "health_goals.json"
        if goals_file.exists():
            with open(goals_file, 'r', encoding='utf-8') as f:
                goals = json.load(f)
        else:
            goals = {}
        
        # Добавляем актуальные данные из Apple Health
        goals['updated'] = datetime.now().isoformat()
        goals['data_sources'] = goals.get('data_sources', [])
        if 'Apple Health' not in goals['data_sources']:
            goals['data_sources'].append('Apple Health')
        
        with open(goals_file, 'w', encoding='utf-8') as f:
            json.dump(goals, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Обновлен: {goals_file}")

def main():
    print("🔗 Интеграция Apple Health данных с HealthVault")
    print("-" * 60)
    
    integrator = AppleHealthIntegrator()
    
    # 1. Загружаем данные Apple Health
    summary, daily_data, weight_data, sleep_data = integrator.load_apple_health_data()
    
    # 2. Создаем унифицированный лог веса
    weight_log = integrator.create_unified_weight_log(weight_data)
    
    # 3. Анализируем тренды веса
    weight_trends = integrator.analyze_weight_trends(weight_log)
    
    # 4. Создаем сводку активности
    activity_summary = integrator.create_activity_summary(daily_data)
    
    # 5. Создаем дашборд здоровья
    dashboard = integrator.create_health_dashboard(summary, weight_trends, activity_summary)
    
    # 6. Обновляем существующие файлы
    integrator.update_existing_files()
    
    print(f"\n🎉 Интеграция завершена!")
    print(f"📁 Созданные файлы:")
    print(f"   • data/unified_weight_log.json")
    print(f"   • data/weight_trends_analysis.json") 
    print(f"   • data/activity_summary.json")
    print(f"   • data/health_dashboard.json")

if __name__ == "__main__":
    main()